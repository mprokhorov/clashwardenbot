import asyncio
import calendar
import json
import logging
import os
import time
from datetime import datetime, timedelta, UTC
from typing import Optional, Any

import asyncpg
from aiogram import Bot
from aiogram.enums import ChatType, ParseMode
from aiogram.types import Chat, User, Message, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from asyncpg import Record, Pool

from async_client import AsyncClient
from bot.commands import bot_cmd_list, get_shown_bot_commands
from config import config
from entities import ClanWarLeagueWar, BotUser, RaidsMember, WarMember
from entities.game_entities import CWLWPlayerRating, CWLPlayerRating, CWLRatingConfig, PlayerRating, PlayerRatingConfig
from output_formatter import OutputFormatter
from output_formatter.output_formatter import Event


class AcquiredConnection:
    def __init__(self, connection_pool: Pool):
        self.connection_pool = connection_pool

    async def fetchval(self, query: str, *args: Any) -> Any:
        async with self.connection_pool.acquire() as connection:
            value = await connection.fetchval(query, *args)
            return value

    async def fetchrow(self, query: str, *args: Any) -> Record:
        async with self.connection_pool.acquire() as connection:
            row = await connection.fetchrow(query, *args)
            return row

    async def fetch(self, query: str, *args: Any) -> list[Record]:
        async with self.connection_pool.acquire() as connection:
            rows = await connection.fetch(query, *args)
            return rows

    async def execute(self, query: str, *args: Any) -> None:
        async with self.connection_pool.acquire() as connection:
            await connection.execute(query, *args)

    async def executemany(self, query: str, *args: Any) -> None:
        async with self.connection_pool.acquire() as connection:
            await connection.executemany(query, *args)


MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), 'migrations')
MIGRATIONS_LOCK_ID = 2026111801
OPPONENT_INFO_REFRESH_SECONDS = 30 * 60
PLAYER_RATINGS_CACHE_SECONDS = 60
PLAYER_RATING_SEASONS_CACHE_SECONDS = 10 * 60


class DatabaseManager:
    def __init__(self, clan_tag: str, bot: Bot):
        self.api_client = AsyncClient(
            email=config.clash_of_clans_api_login.get_secret_value(),
            password=config.clash_of_clans_api_password.get_secret_value(),
            key_name=config.clash_of_clans_api_key_name.get_secret_value(),
            key_description=config.clash_of_clans_api_key_description.get_secret_value()
        )
        self.of = OutputFormatter()

        self.connection_pool = None
        self.acquired_connection = None

        self.scheduler = None
        self.frequent_jobs_frequency_minutes = int(config.frequent_jobs_frequency_minutes.get_secret_value())
        self.infrequent_jobs_frequency_minutes = int(config.infrequent_jobs_frequency_minutes.get_secret_value())
        self.job_timespan_seconds = int(config.job_timespan_seconds.get_secret_value())

        self.clan_tag = clan_tag
        self.bot = bot

        # Caches start empty instead of None, so a failed first load does not break message handling
        self.clan_name = {}
        self.name = {}
        self.name_and_tag = {}
        self.first_name = {}
        self.full_name = {}
        self.username = {}
        self.full_name_and_username = {}

        self.is_privacy_mode_enabled = True
        self.blocked_user_ids = set()
        self.ignore_updates_player_tags = set()

        self.player_rating_config = None
        self.cwl_rating_config = None

        self.jobs_lock = asyncio.Lock()
        self.shown_commands_events = None
        self.are_raid_weekends_backfilled = False
        # Opponent players, war logs and win streaks change rarely, so they are refreshed at most this often
        self.opponent_info_dumped_at = {}
        self.player_ratings_cache = {}
        self.player_rating_seasons_cache = None

    async def connect_to_pool(self) -> None:
        self.connection_pool = await asyncpg.create_pool(
            host=config.postgres_host.get_secret_value(),
            database=config.postgres_database.get_secret_value(),
            user=config.postgres_user.get_secret_value(),
            password=config.postgres_password.get_secret_value(),
            server_settings={'search_path': config.postgres_schema.get_secret_value()},
            # asyncpg keeps 10 connections per pool by default, which is 10 idle Postgres processes for every bot
            min_size=1,
            max_size=5
        )
        self.acquired_connection = AcquiredConnection(self.connection_pool)

    async def apply_migrations(self) -> None:
        # Bots of all clans start at the same time, the advisory lock makes them apply migrations one by one
        async with self.connection_pool.acquire() as connection:
            await connection.execute('SELECT pg_advisory_lock($1)', MIGRATIONS_LOCK_ID)
            try:
                await connection.execute('''
                    CREATE TABLE IF NOT EXISTS schema_migration
                    (
                        name       varchar(128) not null
                            constraint schema_migration_pk
                                primary key,
                        applied_at timestamp    not null
                    )
                ''')
                rows = await connection.fetch('''
                    SELECT name
                    FROM schema_migration
                ''')
                applied_migrations = {row['name'] for row in rows}
                for migration in sorted(os.listdir(MIGRATIONS_DIR)):
                    if not migration.endswith('.sql') or migration in applied_migrations:
                        continue
                    with open(os.path.join(MIGRATIONS_DIR, migration), encoding='utf-8') as file:
                        migration_sql = file.read()
                    async with connection.transaction():
                        await connection.execute(migration_sql)
                        await connection.execute('''
                            INSERT INTO schema_migration (name, applied_at)
                            VALUES ($1, NOW() AT TIME ZONE 'UTC')
                        ''', migration)
                    logging.info(f'Migration {migration} was applied')
            except Exception:
                logging.exception('Migrations were not applied')
            finally:
                await connection.execute('SELECT pg_advisory_unlock($1)', MIGRATIONS_LOCK_ID)

    async def start_scheduler(self, bot_number: int) -> None:
        SECONDS_IN_MINUTE = 60
        self.scheduler = AsyncIOScheduler()
        infrequent_jobs_minutes = [
            minute * self.infrequent_jobs_frequency_minutes
            for minute in range(0, SECONDS_IN_MINUTE // self.infrequent_jobs_frequency_minutes)
        ]
        frequent_jobs_minutes = [
            minute * self.frequent_jobs_frequency_minutes
            for minute in range(0, SECONDS_IN_MINUTE // self.frequent_jobs_frequency_minutes)
            if minute * self.frequent_jobs_frequency_minutes not in infrequent_jobs_minutes
        ]
        infrequent_jobs_minutes_str = ','.join(map(str, infrequent_jobs_minutes))
        frequent_jobs_minutes_str = ','.join(map(str, frequent_jobs_minutes))
        job_options = {'misfire_grace_time': 60, 'coalesce': True, 'max_instances': 1}
        self.scheduler.add_job(
            self.frequent_jobs,
            'cron',
            minute=frequent_jobs_minutes_str,
            second=str(bot_number * self.job_timespan_seconds),
            **job_options
        )
        self.scheduler.add_job(
            self.infrequent_jobs,
            'cron',
            minute=infrequent_jobs_minutes_str,
            second=str(bot_number * self.job_timespan_seconds),
            **job_options
        )
        self.scheduler.start()

    async def run_jobs(self, jobs: list) -> None:
        # Frequent and infrequent jobs must not overlap: two runs comparing old and new states at the same time
        # would send the same alert twice
        if self.jobs_lock.locked():
            logging.warning(f'Previous jobs are still running, {[job.__name__ for job in jobs]} skipped')
            return
        async with self.jobs_lock:
            for job in jobs:
                # A failed job is logged and does not stop the next ones
                try:
                    await job()
                except Exception:
                    logging.exception(f'Job {job.__name__} failed')

    async def frequent_jobs(self) -> None:
        await self.run_jobs([
            self.check_clan_members,
            self.dump_clan_games,
            self.load_clan_war_league_rating_config,
            self.dump_clan_war,
            self.dump_raid_weekends,
            self.raid_weekend_start_reminder,
            self.dump_clan_war_league,
            self.dump_clan_war_league_wars,
            self.set_actual_commands
        ])

    async def infrequent_jobs(self) -> None:
        await self.run_jobs([
            self.load_privacy_mode,
            self.load_blocked_users,
            self.load_ignore_updates_players,
            self.dump_clan,
            self.dump_clan_members_if_not_changed,
            self.load_and_cache_names,
            self.dump_clan_games,
            self.dump_clan_war,
            self.dump_raid_weekends,
            self.raid_weekend_start_reminder,
            self.dump_clan_war_league,
            self.dump_clan_war_league_wars,
            self.load_clan_war_league_rating_config,
            self.set_actual_commands
        ])

    async def dump_clan_members_if_not_changed(self) -> None:
        # When the members changed, check_clan_members has already dumped them
        if not await self.check_clan_members():
            await self.dump_clan_members()

    async def maintenance_alert(self, old_war: dict, war: dict) -> bool:
        are_wars_same = old_war.get('preparationStartTime') == war.get('preparationStartTime')
        is_war_shifted = old_war.get('startTime') != war.get('startTime') or old_war.get('endTime') != war.get('endTime')
        if are_wars_same and is_war_shifted:
            rows = await self.acquired_connection.fetch('''
                SELECT chat_id
                FROM clan_chat
                WHERE clan_tag = $1 AND send_activity_updates
            ''', self.clan_tag)
            for row in rows:
                await self.send_message_to_chat(
                    user_id=None,
                    chat_id=row['chat_id'],
                    message_text=f'<b>💬 Технический перерыв завершён</b>\n',
                    user_ids_to_ping=None
                )
            return True
        return False

    async def load_privacy_mode(self) -> bool:
        self.is_privacy_mode_enabled = await self.acquired_connection.fetchval('''
            SELECT privacy_mode_enabled
            FROM clan
            WHERE clan_tag = $1
        ''', self.clan_tag)
        return True

    async def set_actual_commands(self) -> bool:
        cw = await self.load_clan_war_timing()
        cw_start_time = self.of.to_datetime(cw['startTime']) if cw else datetime.min

        _, cwlw = await self.load_clan_war_league_own_war()
        cwlw_start_time = self.of.to_datetime(cwlw['startTime']) if cwlw else datetime.min

        if cw_start_time > cwlw_start_time:
            events = ['CW']
        elif cw_start_time < cwlw_start_time:
            events = ['CWL']
        else:
            events = ['CW', 'CWL']

        # Raid commands are shown from the "raids started" alert till the "raids ended" alert:
        # the raid is launched by the clan (the attack log has an entry) and the raid weekend is not over
        are_raids_ongoing = await self.acquired_connection.fetchval('''
            SELECT data->>'state' = 'ongoing' AND COALESCE(jsonb_array_length(data->'attackLog'), 0) > 0
            FROM raid_weekend
            WHERE clan_tag = $1
            ORDER BY start_time DESC
            LIMIT 1
        ''', self.clan_tag)
        if are_raids_ongoing:
            events.append('RW')

        # The command menu is changed only when the current events change
        if events == self.shown_commands_events:
            return True
        await self.bot.set_my_commands(
            commands=get_shown_bot_commands(bot_cmd_list, ['group'], events),
            scope=BotCommandScopeAllGroupChats()
        )
        await self.bot.set_my_commands(
            commands=get_shown_bot_commands(bot_cmd_list, ['private'], events),
            scope=BotCommandScopeAllPrivateChats()
        )
        self.shown_commands_events = events
        return True

    async def load_blocked_users(self) -> None:
        rows = await self.acquired_connection.fetch('''
            SELECT user_id
            FROM blocked_bot_user
            WHERE clan_tag = $1 OR clan_tag IS NULL
        ''', self.clan_tag)
        self.blocked_user_ids = {row['user_id'] for row in rows}

    async def load_ignore_updates_players(self) -> None:
        rows = await self.acquired_connection.fetch('''
            SELECT player_tag
            FROM ignore_updates_player
            WHERE clan_tag = $1
        ''', self.clan_tag)
        self.ignore_updates_player_tags = {row['player_tag'] for row in rows}

    async def check_clan_members(self) -> bool:
        were_clan_members_dumped = False
        retrieved_clan_members = await self.api_client.get_clan_members(clan_tag=self.clan_tag)
        if retrieved_clan_members is None:
            return False
        rows = await self.acquired_connection.fetch('''
            SELECT player_tag
            FROM player
            WHERE player.clan_tag = $1 AND is_player_in_clan
        ''', self.clan_tag)
        loaded_clan_member_tags = [row['player_tag'] for row in rows]
        retrieved_clan_member_tags = [clan_member['tag'] for clan_member in retrieved_clan_members['items']]
        joined_clan_member_tags = [
            clan_member_tag
            for clan_member_tag in retrieved_clan_member_tags
            if clan_member_tag not in loaded_clan_member_tags
        ]
        left_clan_member_tags = [
            clan_member_tag
            for clan_member_tag in loaded_clan_member_tags
            if clan_member_tag not in retrieved_clan_member_tags
        ]
        not_ignored_player_tags = [
            player_tag
            for player_tag in left_clan_member_tags + joined_clan_member_tags
            if player_tag not in self.ignore_updates_player_tags
        ]
        if left_clan_member_tags + joined_clan_member_tags:
            were_clan_members_dumped = True
            await self.dump_clan_members()
            await self.load_and_cache_names()
        if len(not_ignored_player_tags) > 0:
            rows = await self.acquired_connection.fetch('''
                SELECT chat_id
                FROM clan_chat
                WHERE clan_tag = $1 AND send_member_updates
            ''', self.clan_tag)
            chat_ids = [row['chat_id'] for row in rows]
            for chat_id in chat_ids:
                for clan_member_tag in not_ignored_player_tags:
                    rows = await self.acquired_connection.fetch('''
                        SELECT user_id
                        FROM
                            player
                            JOIN player_bot_user USING (clan_tag, player_tag)
                            JOIN bot_user USING (clan_tag, chat_id, user_id)
                        WHERE clan_tag = $1 AND player_tag = $2 AND chat_id = $3 AND is_user_in_chat
                    ''', self.clan_tag, clan_member_tag, chat_id)
                    user_ids = [row['user_id'] for row in rows]
                    mentions = ''
                    if len(user_ids) > 0:
                        mentions += f' ({', '.join(
                            '👤 ' + self.of.to_html(self.load_full_name(chat_id, user_id)) for user_id in user_ids
                        )})'
                    row = await self.acquired_connection.fetchrow('''
                        SELECT
                            town_hall_level, barbarian_king_level, archer_queen_level,
                            minion_prince_level, grand_warden_level, royal_champion_level, dragon_duke_level
                        FROM player
                        WHERE clan_tag = $1 AND player_tag = $2
                    ''', self.clan_tag, clan_member_tag)
                    message_text = (
                        f'<b>{self.of.to_html(self.load_name(clan_member_tag))}</b> '
                        f'{self.of.get_player_info_with_custom_emoji(
                            row['town_hall_level'],
                            row['barbarian_king_level'],
                            row['archer_queen_level'],
                            row['minion_prince_level'],
                            row['grand_warden_level'],
                            row['royal_champion_level'],
                            row['dragon_duke_level']
                        )}{mentions} ')
                    if clan_member_tag in left_clan_member_tags:
                        message_text += f'больше не состоит в клане'
                    elif clan_member_tag in joined_clan_member_tags:
                        message_text += f'вступил в клан'
                    message_text += f' ({len(retrieved_clan_members['items'])} / 50 🪖)'
                    await self.send_message_to_chat(
                        user_id=None,
                        chat_id=chat_id,
                        message_text=message_text,
                        user_ids_to_ping=None
                    )
        return were_clan_members_dumped

    async def dump_clan(self) -> bool:
        retrieved_clan = await self.api_client.get_clan(clan_tag=self.clan_tag)
        if retrieved_clan is None:
            return False
        await self.acquired_connection.execute('''
            UPDATE clan
            SET clan_name = $1
            WHERE clan_tag = $2
        ''', retrieved_clan['name'], self.clan_tag)
        return True

    async def dump_clan_members(self) -> bool:
        retrieved_clan_members = await self.api_client.get_clan_members(clan_tag=self.clan_tag)
        if retrieved_clan_members is None:
            return False
        player_tasks = [
            self.api_client.get_player(player_tag=clan_member['tag'])
            for clan_member in retrieved_clan_members['items']
        ]
        retrieved_players = list(await asyncio.gather(*player_tasks))
        if None in retrieved_players:
            return False
        rows = []
        league_tier_rows = []
        for player in retrieved_players:
            player_heroes = player.get('heroes', [])
            barbarian_king_level = 0
            archer_queen_level = 0
            minion_price_level = 0
            grand_warden_level = 0
            royal_champion_level = 0
            dragon_duke_level = 0
            for player_hero in player_heroes:
                if player_hero['name'] == 'Barbarian King':
                    barbarian_king_level = player_hero['level']
                elif player_hero['name'] == 'Archer Queen':
                    archer_queen_level = player_hero['level']
                elif player_hero['name'] == 'Minion Prince':
                    minion_price_level = player_hero['level']
                elif player_hero['name'] == 'Grand Warden':
                    grand_warden_level = player_hero['level']
                elif player_hero['name'] == 'Royal Champion':
                    royal_champion_level = player_hero['level']
                elif player_hero['name'] == 'Dragon Duke':
                    dragon_duke_level = player_hero['level']
            rows.append((
                self.clan_tag, player['tag'],
                player['name'], True,
                False, False,
                barbarian_king_level, archer_queen_level, minion_price_level,
                grand_warden_level, royal_champion_level, dragon_duke_level, json.dumps(player['heroEquipment']),
                player['townHallLevel'], player.get('builderHallLevel', 0),
                player['trophies'], player.get('builderBaseTrophies', 0),
                player['leagueTier']['id'] - 105000000,
                player['role'], player['clanCapitalContributions'],
                player['donations'], player['donationsReceived']
            ))
            league_tier_rows.append(
                (self.clan_tag, player['tag'], player['leagueTier']['id'] - 105000000, player['trophies'])
            )
        async with self.connection_pool.acquire() as connection:
            async with connection.transaction():
                await self.save_clan_members(connection, rows, league_tier_rows)
        return True

    async def save_clan_members(self, connection: asyncpg.Connection, rows: list[tuple], league_tier_rows: list[tuple]) -> None:
        # Capital contributions are the growth of capital_gold_contributed since the previous dump
        contribution_rows = await connection.fetch('''
            SELECT player_tag, capital_gold_contributed
            FROM player
            WHERE clan_tag = $1 AND is_player_in_clan
        ''', self.clan_tag)
        old_contributions = {row['player_tag']: row['capital_gold_contributed'] for row in contribution_rows}
        new_contributions = {row[1]: row[19] for row in rows}
        await connection.executemany('''
            INSERT INTO capital_contribution (clan_tag, player_tag, gold_amount, contribution_timestamp)
            VALUES ($1, $2, $3, NOW() AT TIME ZONE 'UTC')
        ''', [
            (self.clan_tag, player_tag, new_contributions[player_tag] - old_contribution)
            for player_tag, old_contribution in old_contributions.items()
            if new_contributions.get(player_tag, 0) > old_contribution
        ])
        await connection.execute('''
            UPDATE player
            SET is_player_in_clan = FALSE
            WHERE clan_tag = $1 AND is_player_in_clan AND player_tag <> ALL($2::varchar[])
        ''', self.clan_tag, list(new_contributions))
        await connection.executemany('''
            INSERT INTO player
                (clan_tag, player_tag,
                player_name, is_player_in_clan,
                is_player_set_for_clan_wars, is_player_set_for_clan_war_league,
                barbarian_king_level, archer_queen_level, minion_prince_level,
                grand_warden_level, royal_champion_level, dragon_duke_level, hero_equipment,
                town_hall_level, builder_hall_level,
                home_village_trophies, builder_base_trophies,
                home_village_league_tier,
                player_role, capital_gold_contributed,
                donations_given, donations_received,
                first_seen, last_seen)
            VALUES
                ($1, $2,
                $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22,
                NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC')
            ON CONFLICT (clan_tag, player_tag)
            DO UPDATE SET
                (player_name, is_player_in_clan,
                barbarian_king_level, archer_queen_level, minion_prince_level,
                grand_warden_level, royal_champion_level, dragon_duke_level, hero_equipment,
                town_hall_level, builder_hall_level,
                home_village_trophies, builder_base_trophies,
                home_village_league_tier,
                player_role, capital_gold_contributed,
                donations_given, donations_received,
                last_seen) =
                ($3, $4, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22,
                NOW() AT TIME ZONE 'UTC')
        ''', rows)
        await connection.executemany('''
            INSERT INTO player_league (clan_tag, player_tag, league_date, league_tier, trophies)
            VALUES ($1, $2, NOW() AT TIME ZONE 'UTC', $3, $4)
            ON CONFLICT (clan_tag, player_tag, league_date)
            DO UPDATE SET (league_tier, trophies) = ($3, $4)
            WHERE (player_league.league_tier, player_league.trophies) < ($3, $4)
        ''', league_tier_rows)

    async def load_and_cache_names(self) -> None:
        rows = await self.acquired_connection.fetch('''
            SELECT clan_tag, clan_name
            FROM clan
        ''')
        self.clan_name = {
            row['clan_tag']: row['clan_name'] for row in rows
        }

        rows = await self.acquired_connection.fetch('''
            SELECT player_tag, player_name
            FROM player
            WHERE clan_tag = $1
        ''', self.clan_tag)
        self.name = {
            row['player_tag']: row['player_name'] for row in rows
        }
        self.name_and_tag = {
            row['player_tag']: f'{row['player_name']} ({row['player_tag']})' for row in rows
        }

        try:
            rows = await self.acquired_connection.fetch('''
                SELECT player_name
                FROM non_clickable_player_name
            ''')
            OutputFormatter.non_clickable_names = frozenset(row['player_name'] for row in rows)
        except asyncpg.UndefinedTableError:
            logging.warning('Table non_clickable_player_name does not exist, migrations were not applied')

        rows = await self.acquired_connection.fetch('''
            SELECT chat_id, user_id, username, first_name, last_name
            FROM bot_user
            WHERE clan_tag = $1
        ''', self.clan_tag)
        self.first_name = {
            (row['chat_id'], row['user_id']): row['first_name'] for row in rows
        }
        self.full_name = {
            (row['chat_id'], row['user_id']):
                row['first_name'] + (f' {row['last_name']}' if row['last_name'] else '')
            for row in rows
        }
        self.username = {
            (row['chat_id'], row['user_id']): f'@{row['username']}' if row['username'] is not None else None
            for row in rows
        }
        self.full_name_and_username = {
            (row['chat_id'], row['user_id']):
                (f'{row['first_name']}{(' ' + row['last_name']) if row['last_name'] else ''}'
                 f'{(' (@' + row['username'] + ')') if row['username'] else ''}')
            for row in rows
        }

    async def get_clan_games(self) -> Optional[dict]:
        clan_games_begin = (22, 8, 0, 0)
        clan_games_end = (28, 8, 0, 0)
        dt_now = datetime.now(UTC)
        if clan_games_begin <= (dt_now.day, dt_now.hour, dt_now.minute, dt_now.second) < clan_games_end:
            return {
                'startTime': self.of.from_datetime(datetime(dt_now.year, dt_now.month, *clan_games_begin)),
                'endTime': self.of.from_datetime(datetime(dt_now.year, dt_now.month, *clan_games_end)),
                'state': 'ongoing'
            }
        cg = await self.load_clan_games()
        if cg is not None:
            cg['state'] = 'ended'
            return cg
        else:
            return None

    async def dump_clan_games(self) -> bool:
        old_clan_games = await self.load_clan_games() or {'startTime': None, 'state': None}

        retrieved_clan_games = await self.get_clan_games()
        if retrieved_clan_games is None or retrieved_clan_games.get('startTime') is None:
            return False
        await self.acquired_connection.execute('''
            INSERT INTO clan_games (clan_tag, start_time, data)
            VALUES ($1, $2, $3)
            ON CONFLICT (clan_tag, start_time)
            DO UPDATE SET data = $3
        ''', self.clan_tag, self.of.to_datetime(retrieved_clan_games['startTime']), json.dumps(retrieved_clan_games))

        new_clan_games = await self.load_clan_games()

        await self.clan_games_alert(old_clan_games, new_clan_games)

        return True

    async def load_clan_games(self) -> Optional[dict]:
        row = await self.acquired_connection.fetchrow('''
            SELECT data
            FROM clan_games
            WHERE clan_tag = $1
            ORDER BY start_time DESC
        ''', self.clan_tag)
        if row is None:
            return None
        return json.loads(row['data'])

    async def clan_games_alert(self, old_cg: dict, cg: dict) -> None:
        await self.acquired_connection.execute('''
            INSERT INTO activity
                (clan_tag, name, start_time,
                preparation_message_sent, start_message_sent, half_time_remaining_message_sent, end_message_sent)
            VALUES
                ($1, $2, $3, NULL, FALSE, NULL, FALSE)
            ON CONFLICT (clan_tag, name, start_time) DO NOTHING;
        ''', self.clan_tag, 'clan_games', self.of.to_datetime(cg['startTime']))
        row = await self.acquired_connection.fetchrow('''
            SELECT
                clan_tag, name, start_time,
                preparation_message_sent, start_message_sent, half_time_remaining_message_sent, end_message_sent
            FROM activity
            WHERE (clan_tag, name, start_time) = ($1, $2, $3)
        ''', self.clan_tag, 'clan_games', self.of.to_datetime(cg['startTime']))
        texts = []
        pings = []
        if not row['end_message_sent'] and cg['state'] == 'ended' and old_cg['state'] != cg['state']:
            texts.append(
                f'<b>💬 ИК закончились</b>\n'
                f'\n'
                f'{self.of.clan_games_ongoing_or_ended(cg)}')
            pings.append(False)
            await self.set_activity_end_message_sent(
                self.clan_tag, 'clan_games', self.of.to_datetime(cg['startTime'])
            )
        elif not row['start_message_sent'] and cg['state'] == 'ongoing' and old_cg['startTime'] != cg['startTime']:
            texts.append(
                f'<b>📣 ИК начались</b>\n'
                f'\n'
                f'{self.of.clan_games_ongoing_or_ended(cg)}'
            )
            pings.append(True)
            await self.set_activity_start_message_sent(
                self.clan_tag, 'clan_games', self.of.to_datetime(cg['startTime'])
            )
        for text, ping in zip(texts, pings):
            rows = await self.acquired_connection.fetch('''
                SELECT chat_id
                FROM clan_chat
                WHERE clan_tag = $1 AND send_activity_updates
            ''', self.clan_tag)
            for row in rows:
                await self.send_message_to_chat(
                    user_id=None,
                    chat_id=row['chat_id'],
                    message_text=text,
                    user_ids_to_ping=await self.get_clan_member_user_ids(row['chat_id']) if ping else None
                )

    async def dump_clan_war(self) -> bool:
        old_clan_war = await self.load_clan_war_timing() or {'preparationStartTime': None, 'state': None, 'keys_count': 0}

        retrieved_clan_war = await self.api_client.get_clan_current_war(clan_tag=self.clan_tag)
        if retrieved_clan_war is None or retrieved_clan_war.get('preparationStartTime') is None:
            return False
        # The time format is fixed-width, so comparing strings compares times
        if (old_clan_war['preparationStartTime'] is not None
                and retrieved_clan_war['preparationStartTime'] < old_clan_war['preparationStartTime']):
            return False
        # Do not overwrite stored war data with a partial API response that has fewer keys
        retrieved_keys_count = sum(value is not None for value in retrieved_clan_war.values())
        if (old_clan_war['preparationStartTime'] == retrieved_clan_war['preparationStartTime']
                and retrieved_keys_count < old_clan_war.get('keys_count', 0)):
            return False
        # Unchanged data is not rewritten: every rewrite of a big JSON leaves a dead row and bloats the table.
        # Partial API responses with fewer keys never overwrite more complete stored data
        await self.acquired_connection.execute('''
            INSERT INTO clan_war (clan_tag, preparation_start_time, data)
            VALUES ($1, $2, $3)
            ON CONFLICT (clan_tag, preparation_start_time)
            DO UPDATE SET data = $3
            WHERE clan_war.data IS DISTINCT FROM EXCLUDED.data
                AND (SELECT COUNT(*) FROM jsonb_object_keys(jsonb_strip_nulls(EXCLUDED.data)))
                    >= (SELECT COUNT(*) FROM jsonb_object_keys(jsonb_strip_nulls(clan_war.data)))
        ''', self.clan_tag, self.of.to_datetime(retrieved_clan_war['preparationStartTime']), json.dumps(retrieved_clan_war))

        new_clan_war = retrieved_clan_war
        await self.dump_opponent_info(new_clan_war)
        war_win_streak, clan_war_log = None, None
        if self.of.state(new_clan_war) == 'preparation':
            war_win_streak = await self.load_war_win_streak(clan_tag=new_clan_war['opponent']['tag'])
            clan_war_log = await self.load_clan_war_log(clan_tag=new_clan_war['opponent']['tag'])
        await self.clan_war_alert(old_clan_war, new_clan_war, war_win_streak, clan_war_log)
        await self.maintenance_alert(old_clan_war, new_clan_war)
        return True

    async def load_clan_war_timing(self) -> Optional[dict]:
        # Alerts compare only these fields, so the whole war JSON is not parsed every minute
        row = await self.acquired_connection.fetchrow('''
            SELECT
                data->>'preparationStartTime' AS "preparationStartTime", data->>'startTime' AS "startTime",
                data->>'endTime' AS "endTime", data->>'state' AS state,
                (SELECT COUNT(*) FROM jsonb_object_keys(jsonb_strip_nulls(data))) AS keys_count
            FROM clan_war
            WHERE clan_tag = $1
            ORDER BY preparation_start_time DESC
            LIMIT 1
        ''', self.clan_tag)
        return dict(row) if row is not None else None

    async def load_clan_war(self, preparation_start_time: Optional[datetime] = None) -> Optional[dict]:
        if preparation_start_time is None:
            row = await self.acquired_connection.fetchrow('''
                SELECT data
                FROM clan_war
                WHERE clan_tag = $1
                ORDER BY preparation_start_time DESC
                LIMIT 1
            ''', self.clan_tag)
        else:
            row = await self.acquired_connection.fetchrow('''
                SELECT data
                FROM clan_war
                WHERE clan_tag = $1 AND preparation_start_time >= $2 AND preparation_start_time < $3
                ORDER BY preparation_start_time
                LIMIT 1
            ''', self.clan_tag, preparation_start_time, preparation_start_time + timedelta(seconds=1))
        if row is None:
            return None
        return json.loads(row['data'])

    async def load_adjacent_clan_wars(
            self, preparation_start_time: datetime
    ) -> tuple[Optional[dict], Optional[dict]]:
        older_row = await self.acquired_connection.fetchrow('''
            SELECT
                preparation_start_time,
                data->>'startTime' AS "startTime",
                data->>'endTime' AS "endTime"
            FROM clan_war
            WHERE clan_tag = $1 AND preparation_start_time < $2
            ORDER BY preparation_start_time DESC
            LIMIT 1
        ''', self.clan_tag, preparation_start_time)
        newer_row = await self.acquired_connection.fetchrow('''
            SELECT
                preparation_start_time,
                data->>'startTime' AS "startTime",
                data->>'endTime' AS "endTime"
            FROM clan_war
            WHERE clan_tag = $1 AND preparation_start_time > $2
            ORDER BY preparation_start_time ASC
            LIMIT 1
        ''', self.clan_tag, preparation_start_time)
        return (
            dict(older_row) if older_row is not None else None,
            dict(newer_row) if newer_row is not None else None
        )

    async def load_clan_wars_page(self, page: int, page_size: int) -> tuple[list[dict], int]:
        total = await self.acquired_connection.fetchval('''
            SELECT COUNT(*)
            FROM clan_war
            WHERE clan_tag = $1
        ''', self.clan_tag)
        if total == 0:
            return [], 0
        total_pages = (total + page_size - 1) // page_size
        page = max(0, min(page, total_pages - 1))
        rows = await self.acquired_connection.fetch('''
            SELECT
                preparation_start_time,
                data->>'state' AS state,
                data->>'startTime' AS "startTime",
                data->>'endTime' AS "endTime",
                data->'opponent'->>'name' AS opponent_name,
                (data->'clan'->>'stars')::integer AS clan_stars,
                (data->'clan'->>'destructionPercentage')::double precision AS clan_destruction,
                (data->'opponent'->>'stars')::integer AS opponent_stars,
                (data->'opponent'->>'destructionPercentage')::double precision AS opponent_destruction
            FROM clan_war
            WHERE clan_tag = $1
            ORDER BY preparation_start_time DESC
            LIMIT $2 OFFSET $3
        ''', self.clan_tag, page_size, page * page_size)
        return [dict(row) for row in rows], total

    async def dump_opponent_info(self, war: dict) -> bool:
        # Opponent players, war log and win streak are shown only for wars in preparation or in progress and
        # change rarely, so they are dumped when such a war appears and then at most every half an hour
        if self.of.state(war) not in ['preparation', 'inWar']:
            return False
        key = (war['opponent']['tag'], war['preparationStartTime'])
        now = time.monotonic()
        if now - self.opponent_info_dumped_at.get(key, -OPPONENT_INFO_REFRESH_SECONDS) < OPPONENT_INFO_REFRESH_SECONDS:
            return False
        results = await asyncio.gather(
            self.dump_war_win_streak(clan_tag=war['opponent']['tag']),
            self.dump_clan_war_log(clan_tag=war['opponent']['tag']),
            self.dump_opponent_players(war=war)
        )
        if all(results):
            self.opponent_info_dumped_at = {
                dumped_key: dumped_at for dumped_key, dumped_at in self.opponent_info_dumped_at.items()
                if now - dumped_at < OPPONENT_INFO_REFRESH_SECONDS
            }
            self.opponent_info_dumped_at[key] = now
        return all(results)

    async def dump_clan_war_log(self, clan_tag: str) -> bool:
        retrieved_clan_war_log = await self.api_client.get_war_log(clan_tag=clan_tag)
        if retrieved_clan_war_log is None:
            # A private war log is a normal answer for many clans, there is nothing to retry
            return True
        await self.acquired_connection.execute('''
            INSERT INTO clan_war_log (clan_tag, data)
            VALUES ($1, $2)
            ON CONFLICT (clan_tag)
            DO UPDATE SET data = $2
            WHERE clan_war_log.data IS DISTINCT FROM EXCLUDED.data
                AND (SELECT COUNT(*) FROM jsonb_object_keys(jsonb_strip_nulls(EXCLUDED.data)))
                    >= (SELECT COUNT(*) FROM jsonb_object_keys(jsonb_strip_nulls(clan_war_log.data)))
        ''', clan_tag, json.dumps(retrieved_clan_war_log))
        return True

    async def load_clan_war_log(self, clan_tag: str) -> Optional[dict]:
        row = await self.acquired_connection.fetchrow('''
            SELECT data
            FROM clan_war_log
            WHERE clan_tag = $1
        ''', clan_tag)
        if row is None:
            return None
        return json.loads(row['data'])

    async def dump_war_win_streak(self, clan_tag: str) -> bool:
        retrieved_clan = await self.api_client.get_clan(clan_tag=clan_tag)
        if retrieved_clan is None:
            return False
        await self.acquired_connection.execute('''
            INSERT INTO war_win_streak
            VALUES ($1, $2)
            ON CONFLICT (clan_tag)
            DO UPDATE SET war_win_streak = $2
            WHERE war_win_streak.war_win_streak IS DISTINCT FROM EXCLUDED.war_win_streak
        ''', clan_tag, retrieved_clan['warWinStreak'])
        return True

    async def load_war_win_streak(self, clan_tag: str) -> Optional[int]:
        val = await self.acquired_connection.fetchval('''
            SELECT war_win_streak
            FROM war_win_streak
            WHERE clan_tag = $1
        ''', clan_tag)
        return val

    async def dump_opponent_players(self, war: dict) -> bool:
        opponent_player_tasks = [
            self.api_client.get_player(player_tag=member['tag'])
            for member in war['opponent']['members']
        ]
        retrieved_opponent_players = list(await asyncio.gather(*opponent_player_tasks))
        if None in retrieved_opponent_players:
            return False
        rows = []
        for opponent_player in retrieved_opponent_players:
            player_heroes = opponent_player.get('heroes', [])
            barbarian_king_level = 0
            archer_queen_level = 0
            minion_prince_level = 0
            grand_warden_level = 0
            royal_champion_level = 0
            dragon_duke_level = 0
            for player_hero in player_heroes:
                if player_hero['name'] == 'Barbarian King':
                    barbarian_king_level = player_hero['level']
                elif player_hero['name'] == 'Archer Queen':
                    archer_queen_level = player_hero['level']
                elif player_hero['name'] == 'Minion Prince':
                    minion_prince_level = player_hero['level']
                elif player_hero['name'] == 'Grand Warden':
                    grand_warden_level = player_hero['level']
                elif player_hero['name'] == 'Royal Champion':
                    royal_champion_level = player_hero['level']
                elif player_hero['name'] == 'Dragon Duke':
                    dragon_duke_level = player_hero['level']
            rows.append((
                war['opponent']['tag'], opponent_player['tag'],
                opponent_player['name'], opponent_player['townHallLevel'],
                barbarian_king_level, archer_queen_level, minion_prince_level,
                grand_warden_level, royal_champion_level, dragon_duke_level
            ))
        await self.acquired_connection.executemany('''
            INSERT INTO opponent_player
                (clan_tag, player_tag,
                player_name, town_hall_level,
                barbarian_king_level, archer_queen_level, minion_prince_level,
                grand_warden_level, royal_champion_level, dragon_duke_level)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (clan_tag, player_tag)
            DO UPDATE SET
                (player_name, town_hall_level,
                barbarian_king_level, archer_queen_level, minion_prince_level,
                grand_warden_level, royal_champion_level, dragon_duke_level) =
                ($3, $4, $5, $6, $7, $8, $9, $10)
            WHERE
                (opponent_player.player_name, opponent_player.town_hall_level,
                opponent_player.barbarian_king_level, opponent_player.archer_queen_level,
                opponent_player.minion_prince_level, opponent_player.grand_warden_level,
                opponent_player.royal_champion_level, opponent_player.dragon_duke_level)
                IS DISTINCT FROM
                (EXCLUDED.player_name, EXCLUDED.town_hall_level,
                EXCLUDED.barbarian_king_level, EXCLUDED.archer_queen_level,
                EXCLUDED.minion_prince_level, EXCLUDED.grand_warden_level,
                EXCLUDED.royal_champion_level, EXCLUDED.dragon_duke_level)
        ''', rows)
        return True

    async def clan_war_alert(self, old_cw: dict, cw: dict, war_win_streak: int, cw_log: Optional[dict]) -> None:
        SECONDS_IN_HOUR = 3600
        await self.acquired_connection.execute('''
            INSERT INTO activity
                (clan_tag, name, start_time,
                preparation_message_sent, start_message_sent, half_time_remaining_message_sent, end_message_sent)
            VALUES
                ($1, $2, $3, FALSE, FALSE, FALSE, FALSE)
            ON CONFLICT (clan_tag, name, start_time) DO NOTHING;
        ''', self.clan_tag, 'clan_war', self.of.to_datetime(cw['preparationStartTime']))
        row = await self.acquired_connection.fetchrow('''
            SELECT
                clan_tag, name, start_time,
                preparation_message_sent, start_message_sent, half_time_remaining_message_sent, end_message_sent
            FROM activity
            WHERE (clan_tag, name, start_time) = ($1, $2, $3)
        ''', self.clan_tag, 'clan_war', self.of.to_datetime(cw['preparationStartTime']))
        texts = []
        pings = []
        is_cw_updated = old_cw['preparationStartTime'] != cw['preparationStartTime']
        is_cw_state_updated = self.of.state(old_cw) != self.of.state(cw)
        is_cw_midpoint_passed = (self.of.to_datetime(cw['endTime']) - self.of.utc_now()).seconds <= 12 * SECONDS_IN_HOUR
        if not row['end_message_sent'] and self.of.state(cw) == 'warEnded' and is_cw_state_updated:
            texts.append(
                f'<b>💬 КВ закончилась</b>\n'
                f'\n'
                f'{self.of.cw_in_war_or_war_ended(cw, False, None, None)}'
            )
            pings.append(False)
            await self.set_activity_end_message_sent(
                self.clan_tag, 'clan_war', self.of.to_datetime(cw['preparationStartTime'])
            )
        elif not row['half_time_remaining_message_sent'] and self.of.state(cw) == 'inWar' and is_cw_midpoint_passed:
            texts.append(
                f'<b>📣 До конца КВ осталось менее 12 часов</b>\n'
                f'\n'
                f'{self.of.cw_in_war_or_war_ended(cw, False, None, None)}'
            )
            pings.append(True)
            await self.set_activity_half_time_remaining_message_sent(
                self.clan_tag, 'clan_war', self.of.to_datetime(cw['preparationStartTime'])
            )
        elif not row['start_message_sent'] and self.of.state(cw) == 'inWar' and is_cw_state_updated:
            texts.append(
                f'<b>📣 КВ началась</b>\n'
                f'\n'
                f'{self.of.cw_in_war_or_war_ended(cw, False, None, None)}'
            )
            pings.append(True)
            await self.set_activity_start_message_sent(
                self.clan_tag, 'clan_war', self.of.to_datetime(cw['preparationStartTime'])
            )
        elif not row['preparation_message_sent'] and self.of.state(cw) == 'preparation' and is_cw_updated:
            texts.append(
                f'<b>💬 КВ найдена</b>\n'
                f'\n'
                f'{self.of.cw_preparation(cw, True, war_win_streak, cw_log)}'
            )
            pings.append(False)
            await self.set_activity_preparation_message_sent(
                self.clan_tag, 'clan_war', self.of.to_datetime(cw['preparationStartTime'])
            )
        for text, ping in zip(texts, pings):
            rows = await self.acquired_connection.fetch('''
                SELECT chat_id
                FROM clan_chat
                WHERE clan_tag = $1 AND send_activity_updates
            ''', self.clan_tag)
            for row in rows:
                await self.send_message_to_chat(
                    user_id=None,
                    chat_id=row['chat_id'],
                    message_text=text,
                    user_ids_to_ping=await self.get_war_member_user_ids(row['chat_id'], cw, 2) if ping else None
                )

    async def dump_raid_weekends(self) -> bool:
        old_raids = await self.load_raid_weekend_timing() or {'startTime': None, 'state': None}

        # After the start the history is loaded once to fill gaps, later only the last two weekends can change
        retrieved_raid_weekends = await self.api_client.get_clan_capital_raid_seasons(
            clan_tag=self.clan_tag, limit=2 if self.are_raid_weekends_backfilled else None
        )
        if not retrieved_raid_weekends or not retrieved_raid_weekends['items']:
            return False
        await self.acquired_connection.executemany('''
            INSERT INTO raid_weekend (clan_tag, start_time, data)
            VALUES ($1, $2, $3)
            ON CONFLICT (clan_tag, start_time)
            DO UPDATE SET data = $3
            WHERE raid_weekend.data IS DISTINCT FROM EXCLUDED.data
                AND (SELECT COUNT(*) FROM jsonb_object_keys(jsonb_strip_nulls(EXCLUDED.data)))
                    >= (SELECT COUNT(*) FROM jsonb_object_keys(jsonb_strip_nulls(raid_weekend.data)))
        ''', [
            (self.clan_tag, self.of.to_datetime(item['startTime']), json.dumps(item))
            for item in retrieved_raid_weekends['items']
            if item.get('members') is not None
        ])

        self.are_raid_weekends_backfilled = True

        new_raids = await self.load_raid_weekend()
        if new_raids is None:
            return False

        await self.raid_weekend_alert(old_raids, new_raids)

        return True

    async def raid_weekend_start_reminder(self) -> bool:
        # When a raid weekend begins and the clan has not launched the raid yet, elders and above are pinged,
        # because only they can launch it. The reminder is sent once per raid weekend
        raid_weekend_start, raid_weekend_end = self.of.calculate_next_raid_weekend()
        if not raid_weekend_start <= self.of.utc_now() < raid_weekend_end:
            return False
        await self.acquired_connection.execute('''
            INSERT INTO activity
                (clan_tag, name, start_time,
                preparation_message_sent, start_message_sent, half_time_remaining_message_sent, end_message_sent)
            VALUES
                ($1, $2, $3, NULL, FALSE, NULL, NULL)
            ON CONFLICT (clan_tag, name, start_time) DO NOTHING
        ''', self.clan_tag, 'raid_weekend_start_reminder', raid_weekend_start)
        is_reminder_sent = await self.acquired_connection.fetchval('''
            SELECT start_message_sent
            FROM activity
            WHERE (clan_tag, name, start_time) = ($1, $2, $3)
        ''', self.clan_tag, 'raid_weekend_start_reminder', raid_weekend_start)
        if is_reminder_sent:
            return False
        # The attack log gets an entry when the clan launches the raid
        is_raid_launched = await self.acquired_connection.fetchval('''
            SELECT COALESCE(jsonb_array_length(data->'attackLog'), 0) > 0
            FROM raid_weekend
            WHERE clan_tag = $1 AND start_time BETWEEN $2 AND $3
            ORDER BY start_time DESC
            LIMIT 1
        ''', self.clan_tag, raid_weekend_start - timedelta(hours=1), raid_weekend_start + timedelta(hours=1))
        await self.set_activity_start_message_sent(self.clan_tag, 'raid_weekend_start_reminder', raid_weekend_start)
        if is_raid_launched:
            return False
        text = (
            f'<b>📣 Рейды можно запускать</b>\n'
            f'\n'
            f'{self.of.event_datetime(
                Event.RW, self.of.from_datetime(raid_weekend_start), self.of.from_datetime(raid_weekend_end), True
            )}\n'
        )
        rows = await self.acquired_connection.fetch('''
            SELECT chat_id
            FROM clan_chat
            WHERE clan_tag = $1 AND send_activity_updates
        ''', self.clan_tag)
        for row in rows:
            await self.send_message_to_chat(
                user_id=None,
                chat_id=row['chat_id'],
                message_text=text,
                user_ids_to_ping=await self.get_clan_member_user_ids(row['chat_id'], ['admin', 'coLeader', 'leader'])
            )
        return True

    async def load_raid_weekend_timing(self) -> Optional[dict]:
        row = await self.acquired_connection.fetchrow('''
            SELECT data->>'startTime' AS "startTime", data->>'state' AS state
            FROM raid_weekend
            WHERE clan_tag = $1
            ORDER BY start_time DESC
            LIMIT 1
        ''', self.clan_tag)
        return dict(row) if row is not None else None

    async def load_raid_weekend(self, start_time: Optional[datetime] = None) -> Optional[dict]:
        if start_time is None:
            row = await self.acquired_connection.fetchrow('''
                SELECT data
                FROM raid_weekend
                WHERE clan_tag = $1
                ORDER BY start_time DESC
                LIMIT 1
            ''', self.clan_tag)
        else:
            row = await self.acquired_connection.fetchrow('''
                SELECT data
                FROM raid_weekend
                WHERE clan_tag = $1 AND start_time >= $2 AND start_time < $3
                ORDER BY start_time
                LIMIT 1
            ''', self.clan_tag, start_time, start_time + timedelta(seconds=1))
        if row is None:
            return None
        return json.loads(row['data'])

    async def load_adjacent_raid_weekends(
            self, start_time: datetime
    ) -> tuple[Optional[dict], Optional[dict]]:
        older_row = await self.acquired_connection.fetchrow('''
            SELECT
                start_time,
                data->>'startTime' AS "startTime",
                data->>'endTime' AS "endTime"
            FROM raid_weekend
            WHERE clan_tag = $1 AND start_time < $2
            ORDER BY start_time DESC
            LIMIT 1
        ''', self.clan_tag, start_time)
        newer_row = await self.acquired_connection.fetchrow('''
            SELECT
                start_time,
                data->>'startTime' AS "startTime",
                data->>'endTime' AS "endTime"
            FROM raid_weekend
            WHERE clan_tag = $1 AND start_time > $2
            ORDER BY start_time ASC
            LIMIT 1
        ''', self.clan_tag, start_time)
        return (
            dict(older_row) if older_row is not None else None,
            dict(newer_row) if newer_row is not None else None
        )

    async def load_raid_weekends_page(self, page: int, page_size: int) -> tuple[list[dict], int]:
        total = await self.acquired_connection.fetchval('''
            SELECT COUNT(*)
            FROM raid_weekend
            WHERE clan_tag = $1
        ''', self.clan_tag)
        if total == 0:
            return [], 0
        total_pages = (total + page_size - 1) // page_size
        page = max(0, min(page, total_pages - 1))
        rows = await self.acquired_connection.fetch('''
            SELECT
                start_time,
                data->>'state' AS state,
                data->>'startTime' AS "startTime",
                data->>'endTime' AS "endTime",
                (data->>'totalAttacks')::integer AS total_attacks,
                (data->>'offensiveReward')::integer AS offensive_reward,
                (data->>'defensiveReward')::integer AS defensive_reward
            FROM raid_weekend
            WHERE clan_tag = $1
            ORDER BY start_time DESC
            LIMIT $2 OFFSET $3
        ''', self.clan_tag, page_size, page * page_size)
        return [dict(row) for row in rows], total

    async def raid_weekend_alert(self, old_raids: dict, raids: dict) -> None:
        await self.acquired_connection.execute('''
            INSERT INTO activity
                (clan_tag, name, start_time,
                preparation_message_sent, start_message_sent, half_time_remaining_message_sent, end_message_sent)
            VALUES
                ($1, $2, $3, NULL, FALSE, NULL, FALSE)
            ON CONFLICT (clan_tag, name, start_time) DO NOTHING;
        ''', self.clan_tag, 'raid_weekend', self.of.to_datetime(raids['startTime']))
        row = await self.acquired_connection.fetchrow('''
            SELECT
                clan_tag, name, start_time,
                preparation_message_sent, start_message_sent, half_time_remaining_message_sent, end_message_sent,
                day_remaining_message_sent
            FROM activity
            WHERE (clan_tag, name, start_time) = ($1, $2, $3)
        ''', self.clan_tag, 'raid_weekend', self.of.to_datetime(raids['startTime']))
        texts = []
        # Who is pinged: None, 'clan' (all clan members) or 'raids' (members who have not spent all raid attacks)
        pings = []
        are_raids_updated = old_raids['startTime'] != raids['startTime']
        # The attack log gets an entry when the clan launches the raid; reminders make sense only after that
        is_raid_launched = len(raids.get('attackLog', [])) > 0
        remaining_time = self.of.to_datetime(raids['endTime']) - self.of.utc_now()
        is_raids_state_updated = self.of.state(old_raids) != self.of.state(raids)
        # Like the start alert, the end alert is sent only if the clan actually raided
        were_raids_played = raids.get('totalAttacks', 0) > 0
        if (not row['end_message_sent'] and self.of.state(raids) == 'ended' and is_raids_state_updated
                and were_raids_played):
            texts.append(
                f'<b>💬 Рейды закончились</b>\n'
                f'\n'
                f'{self.of.raids_ongoing_or_ended(raids)}'
            )
            pings.append(None)
            await self.set_activity_end_message_sent(
                self.clan_tag, 'raid_weekend', self.of.to_datetime(raids['startTime'])
            )
        elif not row['start_message_sent'] and are_raids_updated and self.of.state(raids) == 'ongoing' and len(raids['attackLog']) > 0:
            texts.append(
                f'<b>📣 Рейды начались</b>\n'
                f'\n'
                f'{self.of.raids_ongoing_or_ended(raids)}'
            )
            pings.append('clan')
            await self.set_activity_start_message_sent(
                self.clan_tag, 'raid_weekend', self.of.to_datetime(raids['startTime'])
            )
        elif (not row['half_time_remaining_message_sent'] and self.of.state(raids) == 'ongoing' and is_raid_launched
              and timedelta(0) < remaining_time <= timedelta(hours=12)):
            texts.append(
                f'<b>📣 До конца рейдов осталось менее 12 часов</b>\n'
                f'\n'
                f'{self.of.raids_ongoing_or_ended(raids)}'
            )
            pings.append('raids')
            await self.set_activity_half_time_remaining_message_sent(
                self.clan_tag, 'raid_weekend', self.of.to_datetime(raids['startTime'])
            )
        elif (not row['day_remaining_message_sent'] and self.of.state(raids) == 'ongoing' and is_raid_launched
              and timedelta(hours=12) < remaining_time <= timedelta(days=1)):
            texts.append(
                f'<b>📣 До конца рейдов осталось менее суток</b>\n'
                f'\n'
                f'{self.of.raids_ongoing_or_ended(raids)}'
            )
            pings.append('raids')
            await self.acquired_connection.execute('''
                UPDATE activity
                SET day_remaining_message_sent = TRUE
                WHERE (clan_tag, name, start_time) = ($1, $2, $3)
            ''', self.clan_tag, 'raid_weekend', self.of.to_datetime(raids['startTime']))
        for text, ping in zip(texts, pings):
            rows = await self.acquired_connection.fetch('''
                SELECT chat_id
                FROM clan_chat
                WHERE clan_tag = $1 AND send_activity_updates
            ''', self.clan_tag)
            for row in rows:
                await self.send_message_to_chat(
                    user_id=None,
                    chat_id=row['chat_id'],
                    message_text=text,
                    user_ids_to_ping=(
                        await self.get_clan_member_user_ids(row['chat_id']) if ping == 'clan'
                        else await self.get_raids_member_user_ids(row['chat_id'], raids) if ping == 'raids'
                        else None
                    )
                )

    async def get_raids_member_user_ids(self, chat_id: int, raids: dict) -> list[int]:
        # Like /raids_ping: members who have not spent all raid attacks, including those who did not attack at all
        raids_members = {raids_member['tag']: raids_member for raids_member in raids.get('members', [])}
        rows = await self.acquired_connection.fetch('''
            SELECT player_tag
            FROM player
            WHERE clan_tag = $1 AND is_player_in_clan
        ''', self.clan_tag)
        player_tags = [
            row['player_tag'] for row in rows
            if row['player_tag'] not in raids_members
            or raids_members[row['player_tag']]['attacks'] < (
                raids_members[row['player_tag']]['attackLimit'] + raids_members[row['player_tag']]['bonusAttackLimit']
            )
        ]
        rows = await self.acquired_connection.fetch('''
            SELECT DISTINCT user_id, first_name
            FROM
                player
                JOIN player_bot_user USING (clan_tag, player_tag)
                JOIN bot_user USING (clan_tag, chat_id, user_id)
            WHERE
                clan_tag = $1 AND is_player_in_clan
                AND chat_id = $2 AND is_user_in_chat
                AND player_tag = any($3::varchar[])
            ORDER BY first_name
        ''', self.clan_tag, chat_id, player_tags)
        return [row['user_id'] for row in rows]

    async def dump_clan_war_league(self) -> bool:
        retrieved_clan_war_league = await self.api_client.get_clan_war_league_group(clan_tag=self.clan_tag)
        if retrieved_clan_war_league is None:
            return False
        await self.acquired_connection.execute('''
            INSERT INTO clan_war_league (clan_tag, season, data)
            VALUES ($1, $2, $3)
            ON CONFLICT (clan_tag, season)
            DO UPDATE SET data = $3
            WHERE clan_war_league.data IS DISTINCT FROM EXCLUDED.data
                AND (SELECT COUNT(*) FROM jsonb_object_keys(jsonb_strip_nulls(EXCLUDED.data)))
                    >= (SELECT COUNT(*) FROM jsonb_object_keys(jsonb_strip_nulls(clan_war_league.data)))
        ''', self.clan_tag, retrieved_clan_war_league['season'], json.dumps(retrieved_clan_war_league))
        return True

    async def load_clan_war_league(self) -> tuple[Optional[str], Optional[dict]]:
        row = await self.acquired_connection.fetchrow('''
            SELECT season, data
            FROM clan_war_league
            WHERE clan_tag = $1
            ORDER BY season DESC
            LIMIT 1
        ''', self.clan_tag)
        if row is None:
            return None, None
        return row['season'], json.loads(row['data'])

    async def load_clan_war_league_seasons(self) -> list[str]:
        rows = await self.acquired_connection.fetch('''
            SELECT DISTINCT season
            FROM clan_war_league_war
            WHERE clan_tag = $1
            ORDER BY season
        ''', self.clan_tag)
        return [row['season'] for row in rows]

    async def get_season_cwl_amount(self, season: str) -> int:
        return await self.acquired_connection.fetchval('''
            SELECT COUNT(*)
            FROM clan_war_league
            WHERE clan_tag = $1 AND season LIKE $2
        ''', self.clan_tag, f'{season[0:7]}%')

    async def dump_clan_war_league_wars(self) -> bool:
        cwl_season, clan_war_league = await self.load_clan_war_league()
        if clan_war_league is None:
            return False
        old_cwlws = await self.load_clan_war_league_own_wars_timing(cwl_season)
        clan_war_league_wars = [
            ClanWarLeagueWar(clan_tag=self.clan_tag, war_tag=war_tag, season=cwl_season, day=day)
            for day, war_tags in enumerate(clan_war_league['rounds'])
            for war_tag in war_tags['warTags']
            if war_tag != '#0'
        ]
        rows = await self.acquired_connection.fetch('''
            SELECT war_tag
            FROM clan_war_league_war
            WHERE clan_tag = $1 AND war_tag = any($2::varchar[]) AND data->>'state' = 'warEnded'
        ''', self.clan_tag, [clan_war_league_war.war_tag for clan_war_league_war in clan_war_league_wars])
        ended_war_tags = {row['war_tag'] for row in rows}
        clan_war_league_wars_to_retrieve = [
            clan_war_league_war for clan_war_league_war in clan_war_league_wars
            if clan_war_league_war.war_tag not in ended_war_tags
        ]
        retrieved_clan_war_league_wars = list(await asyncio.gather(*[
            self.api_client.get_clan_war_league_war(war_tag=clan_war_league_war.war_tag)
            for clan_war_league_war in clan_war_league_wars_to_retrieve
        ]))
        if None in retrieved_clan_war_league_wars:
            return False
        await self.acquired_connection.executemany('''
            INSERT INTO clan_war_league_war (clan_tag, war_tag, season, day, data)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (clan_tag, war_tag)
            DO UPDATE SET (season, day, data) = ($3, $4, $5)
            WHERE (clan_war_league_war.season, clan_war_league_war.day, clan_war_league_war.data)
                IS DISTINCT FROM (EXCLUDED.season, EXCLUDED.day, EXCLUDED.data)
                AND (SELECT COUNT(*) FROM jsonb_object_keys(jsonb_strip_nulls(EXCLUDED.data)))
                    >= (SELECT COUNT(*) FROM jsonb_object_keys(jsonb_strip_nulls(clan_war_league_war.data)))
        ''', [
            (clan_war_league_war.clan_tag, clan_war_league_war.war_tag, clan_war_league_war.season,
             clan_war_league_war.day, json.dumps(retrieved_clan_war_league_war))
            for clan_war_league_war, retrieved_clan_war_league_war
            in zip(clan_war_league_wars_to_retrieve, retrieved_clan_war_league_wars)
        ])
        new_cwlws = await self.load_clan_war_league_own_wars(cwl_season) or []
        await asyncio.gather(*[self.dump_opponent_info(new_cwlw) for new_cwlw in new_cwlws])
        if len(old_cwlws) < len(new_cwlws):
            old_cwlws += [{'preparationStartTime': None, 'state': None}] * (len(new_cwlws) - len(old_cwlws))
        was_maintenance_alert_sent = False
        for cwl_day, (old_cwlw, new_cwlw) in enumerate(zip(old_cwlws, new_cwlws)):
            war_timing = ['preparationStartTime', 'startTime', 'endTime', 'state']
            is_cwlw_unchanged = all(old_cwlw.get(key) == new_cwlw.get(key) for key in war_timing)
            # An unchanged war can produce only the half time alert, which needs the war to be in progress
            if is_cwlw_unchanged and self.of.state(new_cwlw) != 'inWar':
                continue
            war_win_streak, cw_log = None, None
            if self.of.state(new_cwlw) == 'preparation':
                war_win_streak = await self.load_war_win_streak(clan_tag=new_cwlw['opponent']['tag'])
                cw_log = await self.load_clan_war_log(clan_tag=new_cwlw['opponent']['tag'])
            await self.clan_war_league_war_alert(old_cwlw, new_cwlw, cwl_season, cwl_day, war_win_streak, cw_log)
            if not was_maintenance_alert_sent:
                was_maintenance_alert_sent = await self.maintenance_alert(old_cwlw, new_cwlw)
        return True

    async def load_clan_war_league_own_war(
            self, season: Optional[str] = None
    ) -> tuple[Optional[int], Optional[dict]]:
        clan_war_league_wars = await self.load_clan_war_league_own_wars(season)
        if not clan_war_league_wars:
            return None, None
        for day, clan_war_league_war in (list(enumerate(clan_war_league_wars)))[::-1]:
            if self.of.state(clan_war_league_war) == 'inWar':
                return day, clan_war_league_war
        for day, clan_war_league_war in (list(enumerate(clan_war_league_wars)))[::-1]:
            if self.of.state(clan_war_league_war) == 'preparation':
                return day, clan_war_league_war
        for day, clan_war_league_war in (list(enumerate(clan_war_league_wars)))[::-1]:
            if self.of.state(clan_war_league_war) == 'warEnded':
                return day, clan_war_league_war
        for day, clan_war_league_war in enumerate(clan_war_league_wars):
            return day, clan_war_league_war
        return None, None

    async def load_clan_war_league_own_wars(
            self, season: Optional[str] = None, clan_tag: Optional[str] = None
    ) -> Optional[list[dict]]:
        if season is None:
            season, _ = await self.load_clan_war_league()
        if season is None:
            return None
        if clan_tag is None:
            clan_tag = self.clan_tag
        rows = await self.acquired_connection.fetch('''
            SELECT data
            FROM clan_war_league_war
            WHERE (clan_tag, season) = ($1, $2) AND $1 IN (data->'clan'->>'tag', data->'opponent'->>'tag')
            ORDER BY day
        ''', clan_tag, season)
        clan_war_league_wars = []
        for row in rows:
            clan_war_league_war = json.loads(row['data'])
            if clan_war_league_war['opponent']['tag'] == clan_tag:
                clan_war_league_war['clan'], clan_war_league_war['opponent'] = (
                    clan_war_league_war['opponent'], clan_war_league_war['clan']
                )
            clan_war_league_wars.append(clan_war_league_war)
        return clan_war_league_wars

    async def load_clan_war_league_own_wars_timing(self, season: str) -> list[dict]:
        rows = await self.acquired_connection.fetch('''
            SELECT
                data->>'preparationStartTime' AS "preparationStartTime", data->>'startTime' AS "startTime",
                data->>'endTime' AS "endTime", data->>'state' AS state
            FROM clan_war_league_war
            WHERE (clan_tag, season) = ($1, $2) AND $1 IN (data->'clan'->>'tag', data->'opponent'->>'tag')
            ORDER BY day
        ''', self.clan_tag, season)
        return [dict(row) for row in rows]

    async def load_clan_war_league_last_day_wars(self, season: Optional[str] = None) -> Optional[list[dict]]:
        if season is None:
            season, _ = await self.load_clan_war_league()
        if season is None:
            return None
        rows = await self.acquired_connection.fetch('''
            SELECT data
            FROM clan_war_league_war
            WHERE
                (clan_tag, season) = ($1, $2)
                AND day IN (SELECT MAX(day) FROM clan_war_league_war WHERE (clan_tag, season) = ($1, $2))
        ''', self.clan_tag, season)
        if not rows:
            return None
        return [json.loads(row['data']) for row in rows]

    async def clan_war_league_war_alert(
            self, old_cwlw: dict, cwlw: dict, cwl_season: str, cwl_day: int, war_win_streak: int, cw_log: Optional[dict]
    ) -> None:
        SECONDS_IN_HOUR = 3600
        await self.acquired_connection.execute('''
            INSERT INTO activity
                (clan_tag, name, start_time,
                preparation_message_sent, start_message_sent, half_time_remaining_message_sent, end_message_sent)
            VALUES
                ($1, $2, $3, FALSE, FALSE, FALSE, FALSE)
            ON CONFLICT (clan_tag, name, start_time) DO NOTHING;
        ''', self.clan_tag, 'clan_war_league_war', self.of.to_datetime(cwlw['preparationStartTime']))
        row = await self.acquired_connection.fetchrow('''
            SELECT
                clan_tag, name, start_time,
                preparation_message_sent, start_message_sent, half_time_remaining_message_sent, end_message_sent
            FROM activity
            WHERE (clan_tag, name, start_time) = ($1, $2, $3)
        ''', self.clan_tag, 'clan_war_league_war', self.of.to_datetime(cwlw['preparationStartTime']))
        texts = []
        pings = []
        is_cwlw_updated = old_cwlw['preparationStartTime'] != cwlw['preparationStartTime']
        is_cwlw_state_updated = self.of.state(old_cwlw) != self.of.state(cwlw)
        cwlw_remaining_time = (self.of.to_datetime(cwlw['endTime']) - self.of.utc_now()).seconds
        is_cwlw_midpoint_passed = cwlw_remaining_time <= 12 * SECONDS_IN_HOUR
        if not row['end_message_sent'] and self.of.state(cwlw) == 'warEnded' and is_cwlw_state_updated:
            texts.append(
                f'<b>💬 День ЛВК закончился</b>\n'
                f'\n'
                f'{self.of.cwlw_in_war_or_war_ended(cwlw, cwl_season, await self.get_season_cwl_amount(cwl_season) == 2, cwl_day, False, None, None)}'
            )
            pings.append(False)
            await self.set_activity_end_message_sent(
                self.clan_tag, 'clan_war_league_war', self.of.to_datetime(cwlw['preparationStartTime'])
            )
        elif not row['half_time_remaining_message_sent'] and self.of.state(cwlw) == 'inWar' and is_cwlw_midpoint_passed:
            texts.append(
                f'<b>📣 До конца дня ЛВК осталось менее 12 часов</b>\n'
                f'\n'
                f'{self.of.cwlw_in_war_or_war_ended(cwlw, cwl_season, await self.get_season_cwl_amount(cwl_season) == 2, cwl_day, False, None, None)}'
            )
            pings.append(True)
            await self.set_activity_half_time_remaining_message_sent(
                self.clan_tag, 'clan_war_league_war', self.of.to_datetime(cwlw['preparationStartTime'])
            )
        elif not row['start_message_sent'] and self.of.state(cwlw) == 'inWar' and is_cwlw_state_updated:
            texts.append(
                f'<b>📣 День ЛВК начался</b>\n'
                f'\n'
                f'{self.of.cwlw_in_war_or_war_ended(cwlw, cwl_season, await self.get_season_cwl_amount(cwl_season) == 2, cwl_day, False, None, None)}'
            )
            pings.append(True)
            await self.set_activity_start_message_sent(
                self.clan_tag, 'clan_war_league_war', self.of.to_datetime(cwlw['preparationStartTime'])
            )
        elif not row['preparation_message_sent'] and self.of.state(cwlw) == 'preparation' and is_cwlw_updated:
            texts.append(
                f'<b>💬 Подготовка ко дню ЛВК началась</b>\n'
                f'\n'
                f'{self.of.cwlw_preparation(cwlw, cwl_season, await self.get_season_cwl_amount(cwl_season) == 2, cwl_day, True, war_win_streak, cw_log)}'
            )
            pings.append(False)
            await self.set_activity_preparation_message_sent(
                self.clan_tag, 'clan_war_league_war', self.of.to_datetime(cwlw['preparationStartTime'])
            )
        for text, ping in zip(texts, pings):
            rows = await self.acquired_connection.fetch('''
                SELECT chat_id
                FROM clan_chat
                WHERE clan_tag = $1 AND send_activity_updates
            ''', self.clan_tag)
            for row in rows:
                await self.send_message_to_chat(
                    user_id=None,
                    chat_id=row['chat_id'],
                    message_text=text,
                    user_ids_to_ping=await self.get_war_member_user_ids(row['chat_id'], cwlw, 1) if ping else None
                )

    async def load_clan_war_league_rating_config(self) -> bool:
        row = await self.acquired_connection.fetchrow('''
            SELECT
                attack_stars_points, attack_destruction_points, attack_map_position_points,
                attack_skip_points, defense_stars_points, defense_destruction_points
            FROM clan_war_league_rating_config
            WHERE clan_tag = $1
        ''', self.clan_tag)
        if row is None:
            return False
        self.cwl_rating_config = CWLRatingConfig(
            row['attack_stars_points'], row['attack_destruction_points'], row['attack_map_position_points'],
            row['attack_skip_points'], row['defense_stars_points'], row['defense_destruction_points']
        )
        return True

    async def get_clan_war_league_rating(self, cwlw: dict) -> dict[str, CWLWPlayerRating]:
        cwlw_rating = {}
        opponent_map_position_by_tag = self.of.calculate_map_positions(cwlw['opponent']['members'])
        if self.of.state(cwlw) == 'preparation':
            return {}
        for player in cwlw['clan']['members']:
            if len(player.get('attacks', [])) > 0:
                attack = player['attacks'][0]
                previous_stars = [
                    clanmate['attacks'][0]['stars']
                    if (clanmate.get('attacks') is not None and
                        clanmate['attacks'][0]['order'] < attack['order'] and
                        clanmate['attacks'][0]['defenderTag'] == attack['defenderTag'])
                    else 0
                    for clanmate
                    in cwlw['clan']['members']
                ]
                attack_new_stars = attack['stars'] - (max(previous_stars) if len(previous_stars) > 0 else 0)
                attack_destruction_percentage = attack['destructionPercentage']
                if attack_new_stars < 0:
                    attack_new_stars = 0
                    attack_destruction_percentage = 0
                attack_map_position = opponent_map_position_by_tag[attack['defenderTag']]
            else:
                if self.of.state(cwlw) == 'inWar':
                    attack_new_stars, attack_destruction_percentage, attack_map_position = None, None, None
                else:
                    attack_new_stars, attack_destruction_percentage, attack_map_position = 0, 0, None
            if self.of.state(cwlw) == 'warEnded':
                if player.get('bestOpponentAttack'):
                    defense_stars = player['bestOpponentAttack']['stars']
                    defense_destruction_percentage = player['bestOpponentAttack']['destructionPercentage']
                else:
                    defense_stars = 0
                    defense_destruction_percentage = 0
            else:
                defense_stars = None
                defense_destruction_percentage = None
            cwlw_rating[player['tag']] = CWLWPlayerRating(
                attack_new_stars,
                attack_destruction_percentage,
                attack_map_position,
                defense_stars,
                defense_destruction_percentage
            )
        return cwlw_rating

    async def get_cwl_ratings(self, cwl_season: str, cwlws: list[dict], count_bonus_points: bool) -> dict[str, CWLPlayerRating]:
        player_tags = {}
        for cwlw in cwlws:
            for player in cwlw['clan']['members']:
                player_tags[player['tag']] = CWLPlayerRating(
                    [], [], [], [], [], [], None, None, None, None, None, None, None, None
                )
        wars_ended = sum(1 if self.of.state(cwlw) == 'warEnded' else 0 for cwlw in cwlws)
        if count_bonus_points:
            rows = await self.acquired_connection.fetch('''
                SELECT player_tag, points
                FROM clan_war_league_rating
                WHERE (clan_tag, season) = ($1, $2)
            ''', self.clan_tag, cwl_season)
            for row in rows:
                if row['player_tag'] in player_tags:
                    player_tags[row['player_tag']].bonus_points.append(row['points'])
        for cwlw in cwlws:
            cwlw_rating = await self.get_clan_war_league_rating(cwlw)
            for player_tag, rating in cwlw_rating.items():
                if rating.attack_new_stars is not None:
                    player_tags[player_tag].attack_new_stars.append(rating.attack_new_stars)
                if rating.attack_destruction_percentage is not None:
                    player_tags[player_tag].attack_destruction_percentage.append(rating.attack_destruction_percentage)
                if rating.attack_map_position is not None:
                    player_tags[player_tag].attack_map_position.append(rating.attack_map_position)
                if rating.defense_stars is not None:
                    player_tags[player_tag].defense_stars.append(rating.defense_stars)
                if rating.defense_destruction_percentage is not None:
                    player_tags[player_tag].defense_destruction_percentage.append(rating.defense_destruction_percentage)
        for player_tag, r in player_tags.items():
            player_tags[player_tag].total_attack_new_stars_points = sum(
                self.cwl_rating_config.attack_stars_points[attack_new_stars]
                for attack_new_stars in r.attack_new_stars
            )
            player_tags[player_tag].total_attack_destruction_percentage_points = sum(
                self.cwl_rating_config.attack_destruction_points * attack_destruction_percentage
                for attack_destruction_percentage in r.attack_destruction_percentage
            )
            player_tags[player_tag].total_attack_map_position_points = sum(
                self.cwl_rating_config.attack_map_position_points * (31 - attack_map_position)
                for attack_map_position in r.attack_map_position
            )
            wars_skips = wars_ended - len(r.attack_new_stars)
            if wars_skips < 0:
                wars_skips = 0
            player_tags[player_tag].total_attack_skips_points = self.cwl_rating_config.attack_skip_points[wars_skips]
            player_tags[player_tag].total_defense_stars_points = sum(
                self.cwl_rating_config.defense_stars_points[defense_stars]
                for defense_stars in r.defense_stars
            )
            player_tags[player_tag].total_defense_destruction_percentage_points = sum(
                self.cwl_rating_config.defense_destruction_points * (100 - defense_destruction_percentage)
                for defense_destruction_percentage in r.defense_destruction_percentage
            )
            player_tags[player_tag].total_bonus_points = sum(player_tags[player_tag].bonus_points)
            player_tags[player_tag].total_points = (
                    player_tags[player_tag].total_attack_new_stars_points +
                    player_tags[player_tag].total_attack_destruction_percentage_points +
                    player_tags[player_tag].total_attack_map_position_points +
                    player_tags[player_tag].total_attack_skips_points +
                    player_tags[player_tag].total_defense_stars_points +
                    player_tags[player_tag].total_defense_destruction_percentage_points +
                    player_tags[player_tag].total_bonus_points
            )
        return player_tags

    async def get_family_clan_tags(self) -> list[str]:
        father_clan_tag = await self.acquired_connection.fetchval('''
            SELECT father_clan_tag
            FROM child_clan
            WHERE child_clan_tag = $1
        ''', self.clan_tag) or self.clan_tag
        rows = await self.acquired_connection.fetch('''
            SELECT child_clan_tag
            FROM child_clan
            WHERE father_clan_tag = $1
        ''', father_clan_tag)
        return [father_clan_tag] + [
            row['child_clan_tag'] for row in rows if row['child_clan_tag'] != father_clan_tag
        ]

    async def get_max_town_hall_level(self) -> int:
        return await self.acquired_connection.fetchval('''
            SELECT MAX(town_hall_level)
            FROM (
                SELECT town_hall_level FROM player
                UNION ALL
                SELECT town_hall_level FROM opponent_player
            ) town_hall_levels
        ''')

    async def load_player_rating_config(self) -> bool:
        family_clan_tags = await self.get_family_clan_tags()
        rows = await self.acquired_connection.fetch('''
            SELECT clan_tag, child_clan_tag, minimum_average_cwl_stars, minimum_cwl_wars, cw_bonus
            FROM player_rating_config
            WHERE clan_tag = any($1::varchar[])
            ORDER BY clan_tag = $2
        ''', family_clan_tags, family_clan_tags[0])
        if len(rows) == 0:
            self.player_rating_config = None
            return False
        self.player_rating_config = {
            row['child_clan_tag']: PlayerRatingConfig(
                row['minimum_average_cwl_stars'], row['minimum_cwl_wars'], row['cw_bonus']
            )
            for row in rows
        }
        return True

    async def get_player_rating_seasons(self) -> list[str]:
        # The list of seasons changes once a month, while it is needed on every rating button press
        if self.player_rating_seasons_cache is not None:
            cached_at, seasons = self.player_rating_seasons_cache
            if time.monotonic() - cached_at < PLAYER_RATING_SEASONS_CACHE_SECONDS:
                return seasons
        rows = await self.acquired_connection.fetch('''
            SELECT DISTINCT TO_CHAR(league_date, 'YYYY-MM') AS season
            FROM player_league
            WHERE clan_tag = any($1::varchar[])
            ORDER BY season
        ''', await self.get_family_clan_tags())
        seasons = [row['season'] for row in rows]
        self.player_rating_seasons_cache = (time.monotonic(), seasons)
        return seasons

    async def get_player_ratings(self, season: str) -> dict[str, PlayerRating]:
        # Every rating button press needs the whole season, so the result is reused for a minute.
        # The returned ratings are shared between callers and must not be modified
        now = time.monotonic()
        self.player_ratings_cache = {
            cached_season: (cached_at, ratings) for cached_season, (cached_at, ratings) in self.player_ratings_cache.items()
            if now - cached_at < PLAYER_RATINGS_CACHE_SECONDS
        }
        if season not in self.player_ratings_cache:
            self.player_ratings_cache[season] = (now, await self.compute_player_ratings(season))
        return self.player_ratings_cache[season][1]

    async def compute_player_ratings(self, season: str) -> dict[str, PlayerRating]:
        LEAGUE_TIER_POINTS = {36: 20, 35: 15, 34: 10, 33: 5, 32: 3, 31: 1}
        LEAGUE_PLACE_POINTS = 10
        CWL_STARS_POINTS = 55
        CWL_FULL_STARS_BONUS_POINTS = 5
        CWL_MAX_STARS = 21
        RAIDS_ATTACKS_POINTS = 3
        RAIDS_MAX_ATTACKS = 6
        RAIDS_GOLD_POINTS = [(50000, 7), (40000, 6), (30000, 5), (25000, 4), (20000, 3), (15000, 2), (10000, 1)]

        family_clan_tags = await self.get_family_clan_tags()
        await self.load_player_rating_config()
        player_rating_config = self.player_rating_config or {}
        year, month = map(int, season.split('-'))
        days_in_month = calendar.monthrange(year, month)[1]
        # Month bounds as ranges, so the filters can use the primary key indexes instead of scanning whole tables
        month_start = datetime(year, month, 1)
        month_end = month_start + timedelta(days=days_in_month)
        max_town_hall_level = await self.get_max_town_hall_level()

        rows = await self.acquired_connection.fetch('''
            SELECT DISTINCT ON (player_tag)
                player_tag, player_name, town_hall_level,
                BOOL_OR(is_player_in_clan) OVER (PARTITION BY player_tag) AS is_player_in_family
            FROM player
            WHERE clan_tag = any($1::varchar[])
            ORDER BY player_tag, last_seen DESC
        ''', family_clan_tags)
        player_rating = {
            row['player_tag']: PlayerRating(
                player_tag=row['player_tag'],
                player_name=row['player_name'],
                is_player_in_family=row['is_player_in_family'],
                town_hall_difference=max_town_hall_level - row['town_hall_level']
            )
            for row in rows
        }

        def get_player_rating(player_tag: str) -> PlayerRating:
            if player_tag not in player_rating:
                player_rating[player_tag] = PlayerRating(
                    player_tag=player_tag, player_name=player_tag, is_player_in_family=False, town_hall_difference=0
                )
            return player_rating[player_tag]

        # CWL: seasons 'YYYY-MM' and 'YYYY-MM-DD' of the same month are different CWLs, sorted chronologically
        rows = await self.acquired_connection.fetch('''
            SELECT clan_tag, season
            FROM clan_war_league
            WHERE clan_tag = any($1::varchar[]) AND season LIKE $2
            ORDER BY season
        ''', family_clan_tags, f'{season}%')
        cwl_amount_by_clan = {}
        cwl_wars_by_clan_by_player = {}
        for row in rows:
            cwl_amount_by_clan[row['clan_tag']] = cwl_amount_by_clan.get(row['clan_tag'], 0) + 1
            cwl_stars_by_player = {}
            cwlws = await self.load_clan_war_league_own_wars(row['season'], row['clan_tag']) or []
            for cwlw in cwlws:
                if self.of.state(cwlw) not in ['inWar', 'warEnded']:
                    continue
                for cwlw_member in cwlw['clan']['members']:
                    cwlw_member_stars = sum(attack['stars'] for attack in cwlw_member.get('attacks', []))
                    cwl_stars_by_player[cwlw_member['tag']] = (
                        cwl_stars_by_player.get(cwlw_member['tag'], 0) + cwlw_member_stars
                    )
                    cwl_wars_by_clan = cwl_wars_by_clan_by_player.setdefault(cwlw_member['tag'], {})
                    cwl_wars_by_clan[row['clan_tag']] = cwl_wars_by_clan.get(row['clan_tag'], 0) + 1
                    get_player_rating(cwlw_member['tag']).cwl_wars += 1
            for player_tag, cwl_stars in cwl_stars_by_player.items():
                get_player_rating(player_tag).cwl_stars.append(cwl_stars)
        for player_tag, cwl_wars_by_clan in cwl_wars_by_clan_by_player.items():
            r = player_rating[player_tag]
            r.cwl_clan_tag = max(cwl_wars_by_clan, key=cwl_wars_by_clan.get)
            cwl_amount = max(cwl_amount_by_clan[r.cwl_clan_tag], len(r.cwl_stars))
            r.cwl_points = sum(
                cwl_stars / CWL_MAX_STARS * CWL_STARS_POINTS
                + (CWL_FULL_STARS_BONUS_POINTS if cwl_stars >= CWL_MAX_STARS else 0)
                for cwl_stars in r.cwl_stars
            ) / cwl_amount
            config = player_rating_config.get(r.cwl_clan_tag)
            if config and config.minimum_cwl_wars is not None and config.minimum_average_cwl_stars:
                r.cwl_required_wars = config.minimum_cwl_wars * cwl_amount_by_clan[r.cwl_clan_tag]
                r.cwl_required_average_stars = config.minimum_average_cwl_stars[
                    min(max(r.town_hall_difference, 0), len(config.minimum_average_cwl_stars) - 1)
                ]
                r.is_eligible_for_prize = (
                    r.cwl_wars >= r.cwl_required_wars
                    and r.cwl_average_stars() >= r.cwl_required_average_stars - 1e-9
                )

        # Only players who are in the family right now can compete for the prize
        prize_candidate_tags = {
            player_tag for player_tag, r in player_rating.items() if r.is_eligible_for_prize and r.is_player_in_family
        }

        # Raids: a raid weekend belongs to the month in which it ends
        rows = await self.acquired_connection.fetch('''
            SELECT start_time, data
            FROM raid_weekend
            WHERE clan_tag = any($1::varchar[]) AND start_time >= $2 AND start_time < $3
            ORDER BY start_time
        ''', family_clan_tags, month_start - timedelta(days=3), month_end - timedelta(days=3))
        raids_gold_by_week = {}
        raids_attacks_by_week = {}
        for row in rows:
            raid_weekend = json.loads(row['data'])
            raids_gold = raids_gold_by_week.setdefault(row['start_time'], {})
            raids_attacks = raids_attacks_by_week.setdefault(row['start_time'], {})
            for raids_member in raid_weekend.get('members', []):
                raids_gold[raids_member['tag']] = (
                    raids_gold.get(raids_member['tag'], 0) + raids_member['capitalResourcesLooted']
                )
                raids_attacks[raids_member['tag']] = raids_attacks.get(raids_member['tag'], 0) + raids_member['attacks']
        rows = await self.acquired_connection.fetch('''
            SELECT DISTINCT player_tag, user_id
            FROM player_bot_user
            WHERE clan_tag = any($1::varchar[]) AND player_tag IS NOT NULL AND user_id IS NOT NULL
        ''', family_clan_tags)
        users_by_player = {}
        players_by_user = {}
        for row in rows:
            users_by_player.setdefault(row['player_tag'], set()).add(row['user_id'])
            players_by_user.setdefault(row['user_id'], set()).add(row['player_tag'])
        raids_weeks = sorted(raids_gold_by_week)
        for raids_gold in raids_gold_by_week.values():
            for player_tag in raids_gold:
                get_player_rating(player_tag)
        for raids_week in raids_weeks:
            raids_gold = raids_gold_by_week[raids_week]
            raids_attacks = raids_attacks_by_week[raids_week]
            for player_tag in raids_gold:
                # Gold is averaged over all accounts of the same person that played this raid weekend
                same_user_player_tags = {player_tag} | {
                    same_user_player_tag
                    for user_id in users_by_player.get(player_tag, set())
                    for same_user_player_tag in players_by_user[user_id]
                    if same_user_player_tag in raids_gold
                }
                r = get_player_rating(player_tag)
                r.raids_attacks.append(raids_attacks[player_tag])
                r.raids_gold.append(
                    sum(raids_gold[tag] for tag in same_user_player_tags) / len(same_user_player_tags)
                )
            for player_tag, r in player_rating.items():
                if player_tag not in raids_gold:
                    r.raids_attacks.append(0)
                    r.raids_gold.append(0)
        if len(raids_weeks) > 0:
            for r in player_rating.values():
                r.raids_attacks_points = sum(
                    min(raids_attacks, RAIDS_MAX_ATTACKS) / RAIDS_MAX_ATTACKS * RAIDS_ATTACKS_POINTS
                    for raids_attacks in r.raids_attacks
                ) / len(raids_weeks)
                r.raids_gold_points = sum(
                    next((points for min_gold, points in RAIDS_GOLD_POINTS if raids_gold >= min_gold), 0)
                    for raids_gold in r.raids_gold
                ) / len(raids_weeks)

        # CW: only ended regular wars, penalties are taken from the config of the clan where the war took place
        rows = await self.acquired_connection.fetch('''
            SELECT clan_tag, data
            FROM clan_war
            WHERE
                clan_tag = any($1::varchar[])
                AND data->>'state' = 'warEnded'
                AND COALESCE((data->>'attacksPerMember')::integer, 2) = 2
                AND preparation_start_time >= $3 AND preparation_start_time < $4
                AND LEFT(data->>'endTime', 6) = $2
            ORDER BY preparation_start_time, clan_tag
        ''', family_clan_tags, season.replace('-', ''), month_start - timedelta(days=3), month_end)
        for row in rows:
            config = player_rating_config.get(row['clan_tag'])
            if config is None or not config.cw_bonus_points:
                continue
            cw = json.loads(row['data'])
            for cw_member in cw['clan']['members']:
                cw_member_attacks = len(cw_member.get('attacks', []))
                r = get_player_rating(cw_member['tag'])
                r.cw_attacks.append(cw_member_attacks)
                r.cw_points += config.cw_bonus_points[min(cw_member_attacks, len(config.cw_bonus_points) - 1)]

        # League: the best league tier and trophies of each player for each day among all family clans
        rows = await self.acquired_connection.fetch('''
            SELECT DISTINCT ON (player_tag, league_date) player_tag, league_date, league_tier, trophies
            FROM player_league
            WHERE clan_tag = any($1::varchar[]) AND league_date >= $2 AND league_date < $3
            ORDER BY player_tag, league_date, league_tier DESC, trophies DESC
        ''', family_clan_tags, month_start.date(), month_end.date())
        league_results_by_day = {}
        for row in rows:
            r = get_player_rating(row['player_tag'])
            r.league_days[row['league_tier']] = r.league_days.get(row['league_tier'], 0) + 1
            r.league_tier_points += LEAGUE_TIER_POINTS.get(min(row['league_tier'], 36), 0) / days_in_month
            if row['player_tag'] in prize_candidate_tags:
                league_results_by_day.setdefault(row['league_date'], []).append(
                    (row['league_tier'], row['trophies'], row['player_tag'])
                )
        for league_date in sorted(league_results_by_day):
            league_results = sorted(league_results_by_day[league_date], reverse=True)
            candidates_count = len(league_results)
            first_place = 1
            while first_place <= candidates_count:
                last_place = first_place
                while (last_place < candidates_count
                       and league_results[last_place][:2] == league_results[first_place - 1][:2]):
                    last_place += 1
                # Players with equal league tier and trophies share the average of their places
                place = (first_place + last_place) / 2
                if candidates_count == 1:
                    place_points = LEAGUE_PLACE_POINTS
                else:
                    place_points = LEAGUE_PLACE_POINTS * (candidates_count - place) / (candidates_count - 1)
                for _, _, player_tag in league_results[first_place - 1:last_place]:
                    player_rating[player_tag].league_places.append(place)
                    player_rating[player_tag].league_place_points += place_points / days_in_month
                first_place = last_place + 1

        for r in player_rating.values():
            if len(r.raids_attacks) == 0:
                r.raids_attacks = [0] * len(raids_weeks)
                r.raids_gold = [0] * len(raids_weeks)
            r.total_points = (
                r.cwl_points + r.league_tier_points + r.league_place_points +
                r.raids_attacks_points + r.raids_gold_points + r.cw_points
            )

        # Chances to win are proportional to squared points: P = max(x, 0)² / Σ max(x, 0)².
        # Negative points give no chance; if no candidate has positive points, all chances are equal
        if len(prize_candidate_tags) > 0:
            weights = {
                player_tag: max(player_rating[player_tag].total_points, 0) ** 2
                for player_tag in prize_candidate_tags
            }
            weights_sum = sum(weights.values())
            for player_tag, weight in weights.items():
                player_rating[player_tag].win_chance = (
                    weight / weights_sum if weights_sum > 0 else 1 / len(prize_candidate_tags)
                )

        return player_rating

    async def dump_user(self, chat: Chat, user: User) -> None:
        if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
            await self.acquired_connection.execute('''
                INSERT INTO bot_user
                    (clan_tag, chat_id, user_id,
                    username, first_name, last_name, is_user_in_chat, first_seen, last_seen)
                VALUES 
                    ($1, $2, $3, $4, $5, $6, TRUE, NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC')
                ON CONFLICT
                    (clan_tag, chat_id, user_id)
                DO UPDATE SET
                    (username, first_name, last_name, is_user_in_chat, last_seen) = 
                    ($4, $5, $6, TRUE, NOW() AT TIME ZONE 'UTC')
            ''', self.clan_tag, chat.id, user.id, user.username, user.first_name, user.last_name)
        elif chat.type == ChatType.PRIVATE:
            await self.acquired_connection.execute('''
                INSERT INTO bot_user
                    (clan_tag, chat_id, user_id,
                    username, first_name, last_name, is_user_in_chat, first_seen, last_seen)
                VALUES 
                    ($1, $2, $3, $4, $5, $6, TRUE, NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC')
                ON CONFLICT
                (clan_tag, chat_id, user_id)
                DO UPDATE SET
                    (username, first_name, last_name, is_user_in_chat, last_seen) = 
                    ($4, $5, $6, TRUE, NOW() AT TIME ZONE 'UTC')
            ''', self.clan_tag, chat.id, user.id, user.username, user.first_name, user.last_name)

    async def undump_user(self, chat: Chat, user: User) -> None:
        await self.acquired_connection.execute('''
            UPDATE bot_user
            SET (username, first_name, last_name, is_user_in_chat, last_seen) = 
                ($4, $5, $6, FALSE, NOW() AT TIME ZONE 'UTC')
            WHERE (clan_tag, chat_id, user_id) = ($1, $2, $3)
        ''', self.clan_tag, chat.id, user.id, user.username, user.first_name, user.last_name)

    async def dump_chat(self, chat: Chat) -> None:
        if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
            await self.acquired_connection.execute('''
                INSERT INTO chat (clan_tag, chat_id, type, title)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (clan_tag, chat_id)
                DO UPDATE SET (type, title) = ($3, $4)
            ''', self.clan_tag, chat.id, chat.type, chat.title)
        elif chat.type == ChatType.PRIVATE:
            await self.acquired_connection.execute('''
                INSERT INTO chat (clan_tag, chat_id, type, username, first_name, last_name)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (clan_tag, chat_id)
                DO UPDATE SET (type, username, first_name, last_name) = ($3, $4, $5, $6)
            ''', self.clan_tag, chat.id, chat.type, chat.username, chat.first_name, chat.last_name)

    def load_name(self, player_tag: str) -> str:
        return self.name.get(player_tag, player_tag)

    def load_name_and_tag(self, player_tag: str) -> str:
        return self.name_and_tag.get(player_tag, player_tag)

    def load_first_name(self, chat_id: int, user_id: int) -> str:
        return self.first_name.get((chat_id, user_id), f'{chat_id}:{user_id}')

    def load_full_name(self, chat_id: int, user_id: int) -> str:
        return self.full_name.get((chat_id, user_id), f'{chat_id}:{user_id}')

    def load_username(self, chat_id: int, user_id: int) -> str:
        return self.username.get((chat_id, user_id), f'{chat_id}:{user_id}')

    def load_full_name_and_username(self, chat_id: int, user_id: int) -> str:
        return self.full_name_and_username.get((chat_id, user_id), f'{chat_id}:{user_id}')

    def load_mentioned_first_name_to_html(self, chat_id: int, user_id: int) -> str:
        return (
            f'<a href="tg://user?id={user_id}">'
            f'{self.of.to_html(self.load_first_name(chat_id, user_id))}</a>'
        )

    def load_mentioned_full_name_to_html(self, chat_id: int, user_id: int) -> str:
        return (
            f'<a href="tg://user?id={user_id}">'
            f'{self.of.to_html(self.load_full_name(chat_id, user_id))}</a>'
        )

    async def dump_message_owner(self, message: Message, user: User) -> None:
        await self.acquired_connection.execute('''
            INSERT INTO message_bot_user (clan_tag, chat_id, message_id, user_id)
            VALUES ($1, $2, $3, $4)
        ''', self.clan_tag, message.chat.id, message.message_id, user.id)

    async def is_user_message_owner(self, message: Message, user: User) -> bool:
        row = await self.acquired_connection.fetchrow('''
            SELECT user_id
            FROM message_bot_user
            WHERE (clan_tag, chat_id, message_id) = ($1, $2, $3)
        ''', self.clan_tag, message.chat.id, message.message_id)
        return row is not None and row['user_id'] == user.id

    async def get_message_owner(self, message: Message) -> BotUser:
        row = await self.acquired_connection.fetchrow('''
            SELECT chat_id, user_id
            FROM message_bot_user
            WHERE (clan_tag, chat_id, message_id) = ($1, $2, $3)
        ''', self.clan_tag, message.chat.id, message.message_id)
        return BotUser(chat_id=row['chat_id'], user_id=row['user_id'])

    async def get_group_chat_id(self, message: Message) -> int:
        if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
            return message.chat.id
        else:
            return await self.get_main_chat_id()

    async def can_user_use_bot(self, user_id: int) -> bool:
        row = await self.acquired_connection.fetchrow('''
            SELECT clan_tag, chat_id, user_id
            FROM bot_user
            WHERE
                clan_tag = $1
                AND (chat_id IN (SELECT chat_id FROM clan_chat WHERE clan_tag = $1)
                     AND is_user_in_chat
                     OR can_use_bot_without_clan_group)
                AND user_id = $2
        ''', self.clan_tag, user_id)
        return row is not None

    async def can_user_ping_group_members(self, chat_id: int, user_id: int) -> bool:
        row = await self.acquired_connection.fetchrow('''
            SELECT clan_tag, chat_id, user_id
            FROM bot_user
            WHERE
                ((clan_tag, chat_id, user_id) = ($1, $2, $3) OR (clan_tag, chat_id, user_id) = ($1, $3, $3))
                AND can_ping_group_members
        ''', self.clan_tag, chat_id, user_id)
        return row is not None

    async def can_user_link_group_members(self, chat_id: int, user_id: int) -> bool:
        row = await self.acquired_connection.fetchrow('''
            SELECT clan_tag, chat_id, user_id
            FROM bot_user
            WHERE
                ((clan_tag, chat_id, user_id) = ($1, $2, $3) OR (clan_tag, chat_id, user_id) = ($1, $3, $3))
                AND can_link_group_members
        ''', self.clan_tag, chat_id, user_id)
        return row is not None

    async def can_user_edit_war_lists(self, chat_id: int, user_id: int) -> bool:
        row = await self.acquired_connection.fetchrow('''
            SELECT clan_tag, chat_id, user_id
            FROM bot_user
            WHERE
                ((clan_tag, chat_id, user_id) = ($1, $2, $3) OR (clan_tag, chat_id, user_id) = ($1, $3, $3))
                AND can_edit_war_lists
        ''', self.clan_tag, chat_id, user_id)
        return row is not None

    async def can_user_send_messages_from_bot(self, chat_id: int, user_id: int) -> bool:
        row = await self.acquired_connection.fetchrow('''
            SELECT clan_tag, chat_id, user_id
            FROM bot_user
            WHERE
                ((clan_tag, chat_id, user_id) = ($1, $2, $3) OR (clan_tag, chat_id, user_id) = ($1, $3, $3))
                AND can_send_messages_from_bot
        ''', self.clan_tag, chat_id, user_id)
        return row is not None

    async def can_user_run_player_rating_giveaway(self, chat_id: int, user_id: int) -> bool:
        row = await self.acquired_connection.fetchrow('''
            SELECT clan_tag, chat_id, user_id
            FROM bot_user
            WHERE
                ((clan_tag, chat_id, user_id) = ($1, $2, $3) OR (clan_tag, chat_id, user_id) = ($1, $3, $3))
                AND can_run_player_rating_giveaway
        ''', self.clan_tag, chat_id, user_id)
        return row is not None

    async def create_player_rating_draw(
            self, season: str, chat_id: int, message_id: int, user_id: int,
            seed: str, seed_hash: str, participants: list[dict]
    ) -> Optional[int]:
        return await self.acquired_connection.fetchval('''
            INSERT INTO player_rating_draw
                (clan_tag, season, chat_id, message_id, user_id, created_at, seed, seed_hash, participants)
            SELECT $1, $2, $3, $4, $5, NOW() AT TIME ZONE 'UTC', $6, $7, $8
            WHERE NOT EXISTS (SELECT FROM player_rating_draw WHERE (chat_id, message_id) = ($3, $4))
            ON CONFLICT (chat_id, message_id) DO NOTHING
            RETURNING draw_id
        ''', self.clan_tag, season, chat_id, message_id, user_id, seed, seed_hash, json.dumps(participants))

    async def load_player_rating_draw(self, draw_id: int, chat_id: int, message_id: int) -> Optional[Record]:
        return await self.acquired_connection.fetchrow('''
            SELECT draw_id, season, seed, seed_hash, participants, drawn_at, cancelled_at
            FROM player_rating_draw
            WHERE (draw_id, chat_id, message_id) = ($1, $2, $3)
        ''', draw_id, chat_id, message_id)

    async def finish_player_rating_draw(
            self, draw_id: int, client_seed: str, ticket: int, winner_tag: str, user_id: int
    ) -> bool:
        # The condition on drawn_at makes the draw happen only once even if the button is pressed several times
        draw_id = await self.acquired_connection.fetchval('''
            UPDATE player_rating_draw
            SET (client_seed, ticket, winner_tag, drawn_by_user_id, drawn_at) =
                ($2, $3, $4, $5, NOW() AT TIME ZONE 'UTC')
            WHERE draw_id = $1 AND drawn_at IS NULL AND cancelled_at IS NULL
            RETURNING draw_id
        ''', draw_id, client_seed, ticket, winner_tag, user_id)
        return draw_id is not None

    async def cancel_player_rating_draw(self, draw_id: int) -> bool:
        draw_id = await self.acquired_connection.fetchval('''
            UPDATE player_rating_draw
            SET cancelled_at = NOW() AT TIME ZONE 'UTC'
            WHERE draw_id = $1 AND drawn_at IS NULL AND cancelled_at IS NULL
            RETURNING draw_id
        ''', draw_id)
        return draw_id is not None

    async def is_player_linked_to_user(self, player_tag: str, chat_id: int, user_id: int) -> bool:
        rows = await self.acquired_connection.fetch('''
            SELECT player_tag
            FROM
                player
                JOIN player_bot_user USING (clan_tag, player_tag)
                JOIN bot_user USING (clan_tag, chat_id, user_id)
            WHERE
                ((clan_tag, chat_id, user_id) = ($1, $2, $3) OR (clan_tag, chat_id, user_id) = ($1, $3, $3))
                AND is_player_in_clan
                AND is_user_in_chat
        ''', self.clan_tag, chat_id, user_id)
        return player_tag in [row['player_tag'] for row in rows]

    async def load_groups_where_user_can_link_members(self, chat_id: int, user_id: int) -> list[Record]:
        if not await self.can_user_link_group_members(chat_id, user_id):
            return []
        rows = await self.acquired_connection.fetch('''
            SELECT chat.chat_id, chat.title
            FROM
                chat
                JOIN clan_chat ON
                    chat.clan_tag = clan_chat.clan_tag
                    AND chat.chat_id = clan_chat.chat_id
                    AND clan_chat.clan_tag = $1
        ''', self.clan_tag)
        return rows

    async def get_main_chat_id(self) -> int:
        row = await self.acquired_connection.fetchrow('''
            SELECT main_chat_id
            FROM clan
            WHERE clan_tag = $1
        ''', self.clan_tag)
        return row['main_chat_id']

    async def get_clan_name(self) -> str:
        row = await self.acquired_connection.fetchrow('''
            SELECT clan_name
            FROM clan
            WHERE clan_tag = $1
        ''', self.clan_tag)
        return row['clan_name']

    async def get_chats_linked_to_clan(self) -> list[int]:
        row = await self.acquired_connection.fetch('''
            SELECT chat_id
            FROM clan_chat
            WHERE clan_tag = $1
        ''', self.clan_tag)
        return [row['chat_id'] for row in row]

    async def get_clan_member_user_ids(self, chat_id: int, player_roles: Optional[list[str]] = None) -> list[int]:
        rows = await self.acquired_connection.fetch('''
            SELECT DISTINCT user_id, first_name
            FROM
                player
                JOIN player_bot_user USING (clan_tag, player_tag)
                JOIN bot_user USING (clan_tag, chat_id, user_id)
            WHERE
                clan_tag = $1 AND is_player_in_clan AND chat_id = $2 AND is_user_in_chat
                AND ($3::varchar[] IS NULL OR player_role = any($3::varchar[]))
            ORDER BY first_name
        ''', self.clan_tag, chat_id, player_roles)
        return [row['user_id'] for row in rows]

    async def get_war_member_user_ids(self, chat_id: int, war: dict, attacks_required: int) -> list[int]:
        war_member_tags = []
        for war_member in war['clan']['members']:
            if len(war_member.get('attacks', [])) < attacks_required:
                war_member_tags.append(war_member['tag'])
        rows = await self.acquired_connection.fetch('''
            SELECT DISTINCT user_id, first_name
            FROM
                player
                JOIN player_bot_user USING (clan_tag, player_tag)
                JOIN bot_user USING (clan_tag, chat_id, user_id)
            WHERE
                clan_tag = $1 AND is_player_in_clan
                AND chat_id = $2 AND is_user_in_chat
                AND player_tag = any($3::varchar[])
            ORDER BY first_name
        ''', self.clan_tag, chat_id, war_member_tags)
        return [row['user_id'] for row in rows]

    async def send_message_to_chat(
            self,
            user_id: Optional[int],
            chat_id: int,
            message_text: str,
            user_ids_to_ping: Optional[list[int]]
    ) -> None:
        chat_title = await self.acquired_connection.fetchval('''
            SELECT title
            FROM chat
            WHERE chat_id = $1
        ''', chat_id)
        if user_ids_to_ping:
            message_text += (
                f'\n'
                f'{', '.join(
                    self.load_mentioned_first_name_to_html(chat_id, user_id_to_ping)
                    for user_id_to_ping in user_ids_to_ping
                )}\n')
        log_text = f'Message "{message_text}" was sent to group {chat_title} ({chat_id})'
        await self.bot.send_message(
            chat_id=chat_id,
            text=message_text,
            parse_mode=ParseMode.HTML,
            reply_markup=None
        )
        await self.acquired_connection.execute('''
            INSERT INTO action (clan_tag, chat_id, user_id, action_timestamp, description)
            VALUES ($1, $2, $3, NOW() AT TIME ZONE 'UTC', $4)
        ''', self.clan_tag, user_id, user_id, log_text)

    async def set_activity_preparation_message_sent(self, clan_tag: str, name: str, start_time: datetime) -> None:
        await self.acquired_connection.execute('''
            UPDATE activity
            SET preparation_message_sent = TRUE
            WHERE (clan_tag, name, start_time) = ($1, $2, $3)
        ''', clan_tag, name, start_time)

    async def set_activity_start_message_sent(self, clan_tag: str, name: str, start_time: datetime) -> None:
        await self.acquired_connection.execute('''
            UPDATE activity
            SET start_message_sent = TRUE
            WHERE (clan_tag, name, start_time) = ($1, $2, $3)
        ''', clan_tag, name, start_time)

    async def set_activity_half_time_remaining_message_sent(
            self, clan_tag: str, name: str, start_time: datetime
    ) -> None:
        await self.acquired_connection.execute('''
            UPDATE activity
            SET half_time_remaining_message_sent = TRUE
            WHERE (clan_tag, name, start_time) = ($1, $2, $3)
        ''', clan_tag, name, start_time)

    async def set_activity_end_message_sent(self, clan_tag: str, name: str, start_time: datetime) -> None:
        await self.acquired_connection.execute('''
            UPDATE activity
            SET end_message_sent = TRUE
            WHERE (clan_tag, name, start_time) = ($1, $2, $3)
        ''', clan_tag, name, start_time)

    async def skips(
            self, chat_id: int, players: list[WarMember | RaidsMember], ping: bool, desired_attacks_spent: int
    ) -> str:
        rows = await self.acquired_connection.fetch('''
            SELECT player.player_tag, bot_user.user_id
            FROM
                player_bot_user
                JOIN player ON
                    player_bot_user.clan_tag = player.clan_tag
                    AND player_bot_user.player_tag = player.player_tag
                    AND is_player_in_clan
                JOIN bot_user ON
                    player_bot_user.clan_tag = bot_user.clan_tag
                    AND player_bot_user.chat_id = bot_user.chat_id
                    AND player_bot_user.user_id = bot_user.user_id
                    AND is_user_in_chat
            WHERE player.clan_tag = $1 AND bot_user.chat_id = $2
        ''', self.clan_tag, chat_id)
        players_by_user_to_mention = {}
        unlinked_players = []
        users_by_player = {player_tag: [] for player_tag in [row['player_tag'] for row in rows]}
        for row in rows:
            users_by_player[row['player_tag']].append(row['user_id'])
        for player in players:
            if player.attacks_spent < desired_attacks_spent or player.attacks_spent < player.attacks_limit:
                for user_id in users_by_player.get(player.player_tag, []):
                    if players_by_user_to_mention.get(user_id) is None:
                        players_by_user_to_mention[user_id] = []
                    players_by_user_to_mention[user_id].append(player)
                if users_by_player.get(player.player_tag) is None:
                    unlinked_players.append(player)
        for user, players in players_by_user_to_mention.items():
            players.sort(
                key=lambda _player: (
                    -(_player.attacks_limit - _player.attacks_spent),
                    self.of.str_sort_key(self.load_name(_player.player_tag))
                )
            )

        text = ''
        for user_id, players in sorted(
            players_by_user_to_mention.items(),
            key=lambda item: (
                -sum(_player.attacks_limit - _player.attacks_spent for _player in item[1]),
                self.of.str_sort_key(self.load_full_name(chat_id, item[0]))
            )
        ):
            if ping:
                text += f'👤 {self.load_mentioned_full_name_to_html(chat_id, user_id)} — '
            else:
                text += f'👤 {self.of.to_html(self.load_full_name(chat_id, user_id))} — '
            text += f'{', '.join(
                [f'{self.of.to_html(self.load_name(player.player_tag))}: '
                 f'{player.attacks_spent} / {player.attacks_limit}'
                 for player in players]
            )}\n'
        if len(players_by_user_to_mention) > 0:
            text += '\n'
        for player in sorted(
            unlinked_players,
            key=lambda _player: (
                -(_player.attacks_limit - _player.attacks_spent),
                self.of.str_sort_key(self.load_name(_player.player_tag))
            )
        ):
            text += (
                f'{self.of.to_html(self.load_name(player.player_tag))}: '
                f'{player.attacks_spent} / {player.attacks_limit}\n'
            )
        if len(players_by_user_to_mention) + len(unlinked_players) == 0:
            text += f'Список пуст\n'
        return text
