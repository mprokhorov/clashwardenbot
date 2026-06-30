import asyncio
import calendar
import json
from datetime import datetime, UTC
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

        self.clan_name = None
        self.name = None
        self.name_and_tag = None
        self.first_name = None
        self.full_name = None
        self.username = None
        self.full_name_and_username = None

        self.is_privacy_mode_enabled = None
        self.blocked_user_ids = None
        self.ignore_updates_player_tags = None

        self.player_rating_config = None
        self.cwl_rating_config = None

    async def connect_to_pool(self) -> None:
        self.connection_pool = await asyncpg.create_pool(
            host=config.postgres_host.get_secret_value(),
            database=config.postgres_database.get_secret_value(),
            user=config.postgres_user.get_secret_value(),
            password=config.postgres_password.get_secret_value(),
            server_settings={'search_path': config.postgres_schema.get_secret_value()}
        )
        self.acquired_connection = AcquiredConnection(self.connection_pool)

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
        self.scheduler.add_job(
            self.frequent_jobs,
            'cron',
            minute=frequent_jobs_minutes_str,
            second=str(bot_number * self.job_timespan_seconds)
        )
        self.scheduler.add_job(
            self.infrequent_jobs,
            'cron',
            minute=infrequent_jobs_minutes_str,
            second=str(bot_number * self.job_timespan_seconds)
        )
        self.scheduler.start()

    async def frequent_jobs(self) -> None:
        were_clan_members_dumped = await self.check_clan_members()
        if not were_clan_members_dumped:
            await self.load_and_cache_names()
        await self.dump_clan_games()
        await self.load_clan_war_league_rating_config()
        await self.dump_clan_war()
        await self.dump_raid_weekends()
        await self.dump_clan_war_league()
        await self.dump_clan_war_league_wars()

    async def infrequent_jobs(self) -> None:
        await self.load_privacy_mode()
        await self.set_actual_commands()
        await self.load_blocked_users()
        await self.load_ignore_updates_players()
        await self.dump_clan()
        were_clan_members_dumped = await self.check_clan_members()
        old_contributions = await self.load_capital_contributions()
        if not were_clan_members_dumped:
            await self.dump_clan_members()
            await self.load_and_cache_names()
        new_contributions = await self.load_capital_contributions()
        await self.dump_capital_contributions(old_contributions, new_contributions)
        await self.dump_clan_games()
        await self.dump_clan_war()
        await self.dump_raid_weekends()
        await self.dump_clan_war_league()
        await self.dump_clan_war_league_wars()
        await self.load_clan_war_league_rating_config()

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
        cw = await self.load_clan_war()
        cw_start_time = self.of.to_datetime(cw['startTime']) if cw else datetime.min

        _, cwlw = await self.load_clan_war_league_own_war()
        cwlw_start_time = self.of.to_datetime(cwlw['startTime']) if cwlw else datetime.min

        if cw_start_time > cwlw_start_time:
            await self.bot.set_my_commands(
                commands=get_shown_bot_commands(bot_cmd_list, ['group'], ['CW']),
                scope=BotCommandScopeAllGroupChats()
            )
            await self.bot.set_my_commands(
                commands=get_shown_bot_commands(bot_cmd_list, ['private'], ['CW']),
                scope=BotCommandScopeAllPrivateChats()
            )
        elif cw_start_time < cwlw_start_time:
            await self.bot.set_my_commands(
                commands=get_shown_bot_commands(bot_cmd_list, ['group'], ['CWL']),
                scope=BotCommandScopeAllGroupChats()
            )
            await self.bot.set_my_commands(
                commands=get_shown_bot_commands(bot_cmd_list, ['private'], ['CWL']),
                scope=BotCommandScopeAllPrivateChats()
            )
        else:
            await self.bot.set_my_commands(
                commands=get_shown_bot_commands(bot_cmd_list, ['group'], ['ANY']),
                scope=BotCommandScopeAllGroupChats()
            )
            await self.bot.set_my_commands(
                commands=get_shown_bot_commands(bot_cmd_list, ['private'], ['ANY']),
                scope=BotCommandScopeAllPrivateChats()
            )

        return True

    async def load_blocked_users(self) -> None:
        rows = await self.acquired_connection.fetch('''
            SELECT user_id
            FROM blocked_bot_user
            WHERE clan_tag = $1 OR clan_tag IS NULL
        ''', self.clan_tag)
        self.blocked_user_ids = [row['user_id'] for row in rows]

    async def load_ignore_updates_players(self) -> None:
        rows = await self.acquired_connection.fetch('''
            SELECT player_tag
            FROM ignore_updates_player
            WHERE clan_tag = $1
        ''', self.clan_tag)
        self.ignore_updates_player_tags = [row['player_tag'] for row in rows]

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
        await self.acquired_connection.execute('''
            UPDATE player
            SET is_player_in_clan = FALSE
            WHERE clan_tag = $1
        ''', self.clan_tag)
        await self.acquired_connection.executemany('''
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
        await self.acquired_connection.executemany('''
            INSERT INTO player_league (clan_tag, player_tag, league_date, league_tier, trophies)
            VALUES ($1, $2, NOW() AT TIME ZONE 'UTC', $3, $4)
            ON CONFLICT (clan_tag, player_tag, league_date)
            DO UPDATE SET (league_tier, trophies) = ($3, $4)
            WHERE (player_league.league_tier, player_league.trophies) < ($3, $4)
        ''', league_tier_rows)
        return True

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

    async def load_capital_contributions(self) -> dict:
        rows = await self.acquired_connection.fetch('''
            SELECT player_tag, capital_gold_contributed
            FROM player
            WHERE is_player_in_clan AND clan_tag = $1
        ''', self.clan_tag)
        return {row['player_tag']: row['capital_gold_contributed'] for row in rows}

    async def dump_capital_contributions(self, old_contributions, new_contributions) -> None:
        for player_tag in old_contributions:
            has_player_contributed = new_contributions[player_tag] > old_contributions[player_tag]
            if new_contributions.get(player_tag) is not None and has_player_contributed:
                await self.acquired_connection.execute('''
                    INSERT INTO capital_contribution (clan_tag, player_tag, gold_amount, contribution_timestamp)
                    VALUES ($1, $2, $3, NOW() AT TIME ZONE 'UTC')
                ''', self.clan_tag, player_tag, new_contributions[player_tag] - old_contributions[player_tag])

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
        old_clan_war = await self.load_clan_war() or {'preparationStartTime': None, 'state': None}

        retrieved_clan_war = await self.api_client.get_clan_current_war(clan_tag=self.clan_tag)
        if retrieved_clan_war is None or retrieved_clan_war.get('preparationStartTime') is None:
            return False
        await self.acquired_connection.execute('''
            INSERT INTO clan_war (clan_tag, preparation_start_time, data)
            VALUES ($1, $2, $3)
            ON CONFLICT (clan_tag, preparation_start_time)
            DO UPDATE SET data = $3
        ''', self.clan_tag, self.of.to_datetime(retrieved_clan_war['preparationStartTime']), json.dumps(retrieved_clan_war))

        new_clan_war = await self.load_clan_war()
        await asyncio.gather(
            self.dump_war_win_streak(clan_tag=new_clan_war['opponent']['tag']),
            self.dump_clan_war_log(clan_tag=new_clan_war['opponent']['tag']),
            self.dump_opponent_players(war=new_clan_war)
        )
        war_win_streak = await self.load_war_win_streak(clan_tag=new_clan_war['opponent']['tag'])
        clan_war_log = await self.load_clan_war_log(clan_tag=new_clan_war['opponent']['tag'])
        await self.clan_war_alert(old_clan_war, new_clan_war, war_win_streak, clan_war_log)
        await self.maintenance_alert(old_clan_war, new_clan_war)
        return True

    async def load_clan_war(self) -> Optional[dict]:
        row = await self.acquired_connection.fetchrow('''
            SELECT data
            FROM clan_war
            WHERE clan_tag = $1
            ORDER BY preparation_start_time DESC
        ''', self.clan_tag)
        if row is None:
            return None
        return json.loads(row['data'])

    async def dump_clan_war_log(self, clan_tag: str) -> bool:
        retrieved_clan_war_log = await self.api_client.get_war_log(clan_tag=clan_tag)
        if retrieved_clan_war_log is None:
            return False
        await self.acquired_connection.execute('''
            INSERT INTO clan_war_log (clan_tag, data)
            VALUES ($1, $2)
            ON CONFLICT (clan_tag)
            DO UPDATE SET data = $2
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
        ''', clan_tag, retrieved_clan['warWinStreak'])

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
        old_raids = await self.load_raid_weekend() or {'startTime': None, 'state': None}

        retrieved_raid_weekends = await self.api_client.get_clan_capital_raid_seasons(clan_tag=self.clan_tag)
        if not retrieved_raid_weekends or not retrieved_raid_weekends['items']:
            return False
        await self.acquired_connection.executemany('''
            INSERT INTO raid_weekend (clan_tag, start_time, data)
            VALUES ($1, $2, $3)
            ON CONFLICT (clan_tag, start_time)
            DO UPDATE SET data = $3
        ''', [
            (self.clan_tag, self.of.to_datetime(item['startTime']), json.dumps(item))
            for item in retrieved_raid_weekends['items']
            if item.get('members') is not None
        ])

        new_raids = await self.load_raid_weekend()

        await self.raid_weekend_alert(old_raids, new_raids)

        return True

    async def load_raid_weekend(self) -> Optional[dict]:
        row = await self.acquired_connection.fetchrow('''
            SELECT data
            FROM raid_weekend
            WHERE clan_tag = $1
            ORDER BY start_time DESC
        ''', self.clan_tag)
        if row is None:
            return None
        return json.loads(row['data'])

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
                preparation_message_sent, start_message_sent, half_time_remaining_message_sent, end_message_sent
            FROM activity
            WHERE (clan_tag, name, start_time) = ($1, $2, $3)
        ''', self.clan_tag, 'raid_weekend', self.of.to_datetime(raids['startTime']))
        texts = []
        pings = []
        are_raids_updated = old_raids['startTime'] != raids['startTime']
        is_raids_state_updated = self.of.state(old_raids) != self.of.state(raids)
        if not row['end_message_sent'] and self.of.state(raids) == 'ended' and is_raids_state_updated:
            texts.append(
                f'<b>💬 Рейды закончились</b>\n'
                f'\n'
                f'{self.of.raids_ongoing_or_ended(raids)}'
            )
            pings.append(False)
            await self.set_activity_end_message_sent(
                self.clan_tag, 'raid_weekend', self.of.to_datetime(raids['startTime'])
            )
        elif not row['start_message_sent'] and are_raids_updated and self.of.state(raids) == 'ongoing' and len(raids['attackLog']) > 0:
            texts.append(
                f'<b>📣 Рейды начались</b>\n'
                f'\n'
                f'{self.of.raids_ongoing_or_ended(raids)}'
            )
            pings.append(True)
            await self.set_activity_start_message_sent(
                self.clan_tag, 'raid_weekend', self.of.to_datetime(raids['startTime'])
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

    async def dump_clan_war_league(self) -> bool:
        retrieved_clan_war_league = await self.api_client.get_clan_war_league_group(clan_tag=self.clan_tag)
        if retrieved_clan_war_league is None:
            return False
        await self.acquired_connection.execute('''
            INSERT INTO clan_war_league (clan_tag, season, data)
            VALUES ($1, $2, $3)
            ON CONFLICT (clan_tag, season)
            DO UPDATE SET data = $3
        ''', self.clan_tag, retrieved_clan_war_league['season'], json.dumps(retrieved_clan_war_league))
        return True

    async def load_clan_war_league(self) -> tuple[Optional[str], Optional[dict]]:
        row = await self.acquired_connection.fetchrow('''
            SELECT season, data
            FROM clan_war_league
            WHERE clan_tag = $1
            ORDER BY season DESC 
        ''', self.clan_tag)
        if row is None:
            return None, None
        return row['season'], json.loads(row['data'])

    async def get_season_cwl_amount(self, season: str) -> int:
        return await self.acquired_connection.fetchval('''
            SELECT COUNT(*)
            FROM clan_war_league
            WHERE clan_tag = $1 AND season LIKE $2
        ''', self.clan_tag, f'{season[0:7]}%')

    async def dump_clan_war_league_wars(self) -> bool:
        old_cwl_season, _ = await self.load_clan_war_league()
        old_cwlws = await self.load_clan_war_league_own_wars() or []

        loaded_clan_war_league_season, loaded_clan_war_league = await self.load_clan_war_league()
        if loaded_clan_war_league is None:
            return False
        clan_war_league_wars = [
            ClanWarLeagueWar(clan_tag=self.clan_tag, war_tag=war_tag, season=loaded_clan_war_league_season, day=day)
            for day, war_tags in enumerate(loaded_clan_war_league['rounds'])
            for war_tag in war_tags['warTags']
            if war_tag != '#0'
        ]
        clan_war_league_wars_to_retrieve = []
        for clan_war_league_war in clan_war_league_wars:
            row = await self.acquired_connection.fetchrow('''
                SELECT clan_tag, war_tag, data->>'state' AS state
                FROM clan_war_league_war
                WHERE (clan_tag, war_tag) = ($1, $2) AND data->>'state' = 'warEnded'
            ''', clan_war_league_war.clan_tag, clan_war_league_war.war_tag)
            if row is None:
                clan_war_league_wars_to_retrieve.append(clan_war_league_war)
        clan_war_league_war_tasks = [
            self.api_client.get_clan_war_league_war(war_tag=clan_war_league_war_to_retrieve.war_tag)
            for clan_war_league_war_to_retrieve in clan_war_league_wars_to_retrieve
        ]
        retrieved_clan_war_league_wars = list(await asyncio.gather(*clan_war_league_war_tasks))
        if None in retrieved_clan_war_league_wars:
            return False
        rows = zip(
            [clan_war_league_war.clan_tag for clan_war_league_war in clan_war_league_wars_to_retrieve],
            [clan_war_league_war.war_tag for clan_war_league_war in clan_war_league_wars_to_retrieve],
            [clan_war_league_war.season for clan_war_league_war in clan_war_league_wars_to_retrieve],
            [clan_war_league_war.day for clan_war_league_war in clan_war_league_wars_to_retrieve],
            map(json.dumps, retrieved_clan_war_league_wars)
        )
        await self.acquired_connection.executemany('''
            INSERT INTO clan_war_league_war (clan_tag, war_tag, season, day, data)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (clan_tag, war_tag)
            DO UPDATE SET (season, day, data) = ($3, $4, $5)
        ''', rows)
        new_cwl_season, _ = await self.load_clan_war_league()
        new_cwlws = await self.load_clan_war_league_own_wars()
        opponent_players_tasks = [
            self.dump_opponent_players(war=new_cwlw)
            for new_cwlw in new_cwlws
        ]
        clan_war_log_tasks = [
            self.dump_clan_war_log(clan_tag=new_cwlw['opponent']['tag'])
            for new_cwlw in new_cwlws
        ]
        war_win_streak_tasks = [
            self.dump_war_win_streak(clan_tag=new_cwlw['opponent']['tag'])
            for new_cwlw in new_cwlws
        ]
        await asyncio.gather(*opponent_players_tasks, *clan_war_log_tasks, *war_win_streak_tasks)
        if old_cwl_season != new_cwl_season:
            old_cwlws = []
        if len(old_cwlws) < len(new_cwlws):
            old_cwlws += [{'preparationStartTime': None, 'state': None}] * (len(new_cwlws) - len(old_cwlws))
        was_maintenance_alert_sent = False
        for cwl_day, (old_cwlw, new_cwlw) in enumerate(zip(old_cwlws, new_cwlws)):
            war_win_streak = await self.load_war_win_streak(clan_tag=new_cwlw['opponent']['tag'])
            cw_log = await self.load_clan_war_log(clan_tag=new_cwlw['opponent']['tag'])
            await self.clan_war_league_war_alert(old_cwlw, new_cwlw, new_cwl_season, cwl_day, war_win_streak, cw_log)
            if not was_maintenance_alert_sent:
                was_maintenance_alert_sent = await self.maintenance_alert(old_cwlw, new_cwlw)
        return True

    async def load_clan_war_league_own_war(self) -> tuple[Optional[int], Optional[dict]]:
        clan_war_league_wars = await self.load_clan_war_league_own_wars()
        if clan_war_league_wars is None:
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

    async def load_clan_war_league_last_day_wars(self) -> Optional[list[dict]]:
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

    async def load_player_rating_config(self) -> bool:
        rows = await self.acquired_connection.fetch('''
            SELECT child_clan_tag, minimum_average_cwl_stars, minimum_cwl_wars, cw_bonus
            FROM player_rating_config
            WHERE clan_tag = $1
        ''', self.clan_tag)
        if len(rows) == 0:
            return False
        self.player_rating_config = {
            row['child_clan_tag']: PlayerRatingConfig(
                row['minimum_average_cwl_stars'], row['minimum_cwl_wars'], row['cw_bonus']
            )
            for row in rows
        }
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

    async def get_max_town_hall_level(self) -> int:
        return await self.acquired_connection.fetchval('''
            SELECT MAX(town_hall_level)
            FROM (
                SELECT town_hall_level FROM player
                UNION ALL
                SELECT town_hall_level FROM opponent_player
            ) AS combined_town_hall_levels
        ''')

    async def get_player_ratings(self, season: str) -> dict[str, PlayerRating]:
        LEAGUE_POINTS_BY_LEAGUE_NUMBER = {36: 20, 35: 15, 34: 10, 33: 5, 32: 3, 31: 1}
        GOLD_POINTS_THRESHOLDS = [(50000, 7), (40000, 6), (30000, 5), (25000, 4), (20000, 3), (15000, 2), (10000, 1)]

        def gold_points(gold_amount: int) -> int:
            for threshold, points in GOLD_POINTS_THRESHOLDS:
                if gold_amount >= threshold:
                    return points
            return 0

        rows = await self.acquired_connection.fetch('''
            SELECT data
            FROM raid_weekend
            WHERE clan_tag = $1 AND TO_CHAR(start_time + INTERVAL '3 days', 'YYYY-MM') = $2
            ORDER BY start_time DESC
        ''', self.clan_tag, season)
        total_raid_weekends = len(rows)
        gold_list_by_tag = {}
        raid_attack_list_by_tag = {}
        for row in rows:
            raid_weekend = json.loads(row['data'])
            gold_by_tag_raw = {}
            for raids_member in raid_weekend['members']:
                if raids_member['tag'] not in gold_by_tag_raw:
                    gold_by_tag_raw[raids_member['tag']] = raids_member['capitalResourcesLooted']
                else:
                    gold_by_tag_raw[raids_member['tag']] += raids_member['capitalResourcesLooted']
            rows_users = await self.acquired_connection.fetch('''
                SELECT DISTINCT bot_user.user_id, player.player_tag
                FROM
                    player_bot_user
                    JOIN player ON
                        player_bot_user.clan_tag = player.clan_tag
                        AND player_bot_user.player_tag = player.player_tag
                        AND player.player_tag = any($2::varchar[])
                    JOIN bot_user ON
                        player_bot_user.clan_tag = bot_user.clan_tag
                        AND player_bot_user.chat_id = bot_user.chat_id
                        AND player_bot_user.user_id = bot_user.user_id
                        AND is_user_in_chat
                  WHERE player.clan_tag = $1
              ''', self.clan_tag, list(gold_by_tag_raw))
            users_by_tag = {player_tag: [] for player_tag in [row_users['player_tag'] for row_users in rows_users]}
            for row_users in rows_users:
                users_by_tag[row_users['player_tag']].append(row_users['user_id'])
            tags_by_user = {user_id: [] for user_id in [row_users['user_id'] for row_users in rows_users]}
            for row_users in rows_users:
                tags_by_user[row_users['user_id']].append(row_users['player_tag'])
            gold_by_tag = {player_tag: 0 for player_tag in gold_by_tag_raw}
            for player_tag in gold_by_tag_raw:
                if player_tag not in users_by_tag or len(users_by_tag[player_tag]) == 0:
                    gold_by_tag[player_tag] = gold_by_tag_raw[player_tag]
                else:
                    for user_id in users_by_tag[player_tag]:
                        for tag in tags_by_user[user_id]:
                            gold_by_tag[tag] += gold_by_tag_raw[player_tag] / (len(tags_by_user[user_id]) * len(users_by_tag[player_tag]))
            for player_tag, gold in gold_by_tag.items():
                gold_list_by_tag[player_tag] = gold_list_by_tag.get(player_tag, []) + [gold]
            for raid_member in raid_weekend['members']:
                raid_attack_list_by_tag[raid_member['tag']] = raid_attack_list_by_tag.get(raid_member['tag'], []) + [raid_member['attacks']]

        rows = await self.acquired_connection.fetch('''
            SELECT child_clan_tag, minimum_average_cwl_stars, minimum_cwl_wars
            FROM player_rating_config
            WHERE clan_tag = $1 AND minimum_average_cwl_stars IS NOT NULL AND minimum_cwl_wars IS NOT NULL
        ''', self.clan_tag)
        cwl_eligibility_config_by_clan_tag = {
            row['child_clan_tag']: (row['minimum_average_cwl_stars'], row['minimum_cwl_wars']) for row in rows
        }
        cwl_total_stars = {}
        cwl_total_wars = {}
        cwl_clan_tag_by_player = {}
        for cwl_clan_tag in cwl_eligibility_config_by_clan_tag:
            cwl_own_wars = await self.load_clan_war_league_own_wars(season, cwl_clan_tag) or []
            for cwl_own_war in cwl_own_wars:
                for cwlw_member in cwl_own_war['clan']['members']:
                    cwlw_total_stars = sum(attack['stars'] for attack in cwlw_member.get('attacks', []))
                    cwl_total_stars[cwlw_member['tag']] = cwl_total_stars.get(cwlw_member['tag'], 0) + cwlw_total_stars
                    cwl_total_wars[cwlw_member['tag']] = cwl_total_wars.get(cwlw_member['tag'], 0) + 1
                    if cwlw_member['tag'] not in cwl_clan_tag_by_player:
                        cwl_clan_tag_by_player[cwlw_member['tag']] = cwl_own_war['clan']['tag']

        rows = await self.acquired_connection.fetch('''
            SELECT child_clan_tag, cw_bonus
            FROM player_rating_config
            WHERE clan_tag = $1 AND cw_bonus IS NOT NULL
        ''', self.clan_tag)
        cw_bonus_by_clan_tag = {row['child_clan_tag']: row['cw_bonus'] for row in rows}
        rows = await self.acquired_connection.fetch('''
            SELECT clan_tag, data
            FROM clan_war
            WHERE TO_CHAR((data->>'endTime')::timestamp, 'YYYY-MM') = $1 AND clan_tag = ANY($2::varchar[])
        ''', season, list(cw_bonus_by_clan_tag))
        cw_total_attacks_by_tag = {}
        cw_penalty_points_by_tag = {}
        for row in rows:
            cw = json.loads(row['data'])
            cw_bonus = cw_bonus_by_clan_tag[row['clan_tag']]
            for member in cw['clan']['members']:
                attacks_made = len(member.get('attacks', []))
                cw_total_attacks_by_tag[member['tag']] = cw_total_attacks_by_tag.get(member['tag'], []) + [attacks_made]
                cw_penalty_points_by_tag[member['tag']] = (
                    cw_penalty_points_by_tag.get(member['tag'], 0) + cw_bonus[min(attacks_made, len(cw_bonus) - 1)]
                )

        rows = await self.acquired_connection.fetch('''
            SELECT DISTINCT ON (player_tag) player_tag, town_hall_level
            FROM player
            WHERE clan_tag = $1 OR clan_tag IN (SELECT child_clan_tag FROM child_clan WHERE father_clan_tag = $1)
            ORDER BY player_tag, town_hall_level DESC
        ''', self.clan_tag)
        town_hall_levels = {row['player_tag']: row['town_hall_level'] for row in rows}
        MAX_TOWN_HALL_LEVEL = await self.get_max_town_hall_level()

        is_eligible_for_prize = {}
        for player_tag in {*cwl_total_stars, *cwl_total_wars}:
            cwl_clan_tag = cwl_clan_tag_by_player.get(player_tag)
            if (
                cwl_clan_tag is None or
                cwl_clan_tag not in cwl_eligibility_config_by_clan_tag or
                player_tag not in town_hall_levels
            ):
                continue
            minimum_average_cwl_stars, minimum_cwl_wars = cwl_eligibility_config_by_clan_tag[cwl_clan_tag]
            total_wars = cwl_total_wars.get(player_tag, 0)
            if total_wars < minimum_cwl_wars:
                continue
            town_hall_difference = MAX_TOWN_HALL_LEVEL - town_hall_levels[player_tag]
            bracket = min(town_hall_difference, len(minimum_average_cwl_stars) - 1)
            average_cwl_stars = cwl_total_stars.get(player_tag, 0) / total_wars
            is_eligible_for_prize[player_tag] = average_cwl_stars >= minimum_average_cwl_stars[bracket]

        rows = await self.acquired_connection.fetch('''
            SELECT child_clan_tag
            FROM child_clan
            WHERE father_clan_tag = $1
        ''', self.clan_tag)
        family_clan_tags = [self.clan_tag] + [row['child_clan_tag'] for row in rows]
        rows = await self.acquired_connection.fetch('''
            SELECT player_tag, league_date, league_tier, trophies
            FROM player_league
            WHERE TO_CHAR(league_date, 'YYYY-MM') = $1 AND clan_tag = ANY($2::varchar[])
        ''', season, family_clan_tags)
        best_league_reading_by_day = {}
        for row in rows:
            key = (row['player_tag'], row['league_date'])
            candidate = (row['league_tier'], row['trophies'])
            if key not in best_league_reading_by_day or candidate > best_league_reading_by_day[key]:
                best_league_reading_by_day[key] = candidate
        readings_by_day = {}
        for (player_tag, league_date), (league_tier, trophies) in best_league_reading_by_day.items():
            readings_by_day.setdefault(league_date, []).append((player_tag, league_tier, trophies))

        league_numbers_by_tag = {}
        leagues_places_by_tag = {}
        league_points_by_tag = {}
        place_points_by_tag = {}
        for entries in readings_by_day.values():
            for player_tag, league_tier, _ in entries:
                league_numbers_by_tag.setdefault(player_tag, []).append(league_tier)
                league_points_by_tag[player_tag] = (
                    league_points_by_tag.get(player_tag, 0) + LEAGUE_POINTS_BY_LEAGUE_NUMBER.get(league_tier, 0)
                )
            eligible_entries = sorted(
                (entry for entry in entries if is_eligible_for_prize.get(entry[0], False)),
                key=lambda entry: (entry[1], entry[2]),
                reverse=True
            )
            count_eligible = len(eligible_entries)
            if count_eligible == 0:
                continue
            if count_eligible == 1:
                player_tag = eligible_entries[0][0]
                leagues_places_by_tag.setdefault(player_tag, []).append(1)
                place_points_by_tag[player_tag] = place_points_by_tag.get(player_tag, 0) + 10
                continue
            i = 0
            while i < count_eligible:
                j = i
                while j + 1 < count_eligible and eligible_entries[j + 1][1:] == eligible_entries[i][1:]:
                    j += 1
                place = (i + 1 + j + 1) / 2
                place_points = 10 * (count_eligible - place) / (count_eligible - 1)
                for k in range(i, j + 1):
                    player_tag = eligible_entries[k][0]
                    leagues_places_by_tag.setdefault(player_tag, []).append(place)
                    place_points_by_tag[player_tag] = place_points_by_tag.get(player_tag, 0) + place_points
                i = j + 1

        raids_gold_points_by_tag = {}
        for player_tag, gold_values in gold_list_by_tag.items():
            raids_gold_points_by_tag[player_tag] = sum(gold_points(gold) for gold in gold_values)
        raids_attack_points_by_tag = {}
        for player_tag, attack_values in raid_attack_list_by_tag.items():
            raids_attack_points_by_tag[player_tag] = sum(attacks / 6 * 3 for attacks in attack_values)

        days_in_month = calendar.monthrange(*map(int, season.split('-')))[1]
        total_player_tags = {
            *gold_list_by_tag, *raid_attack_list_by_tag, *cwl_total_stars, *cwl_total_wars, *cw_total_attacks_by_tag,
            *league_numbers_by_tag
        }
        player_rating = {
            player_tag: PlayerRating(
                town_hall_difference=MAX_TOWN_HALL_LEVEL - town_hall_levels.get(player_tag, MAX_TOWN_HALL_LEVEL),
                cwl_clan_tag=None,
                cwl_total_stars=0,
                cwl_total_wars=0,
                league_numbers=[],
                leagues_places=[],
                raids_total_attacks=[],
                raids_total_gold=[],
                cw_total_attacks=[],
                is_eligible_for_prize=is_eligible_for_prize.get(player_tag, False),
                total_cwl_points=None,
                total_league_points=None,
                total_place_points=None,
                total_raids_attack_points=None,
                total_raids_gold_points=None,
                total_raids_points=None,
                total_cw_penalty_points=None,
                total_points=None
            )
            for player_tag in total_player_tags
        }
        for tag, gold in gold_list_by_tag.items():
            player_rating[tag].raids_total_gold = gold
        for tag, attacks in raid_attack_list_by_tag.items():
            player_rating[tag].raids_total_attacks = attacks
        for tag, total_stars in cwl_total_stars.items():
            player_rating[tag].cwl_total_stars = total_stars
        for tag, total_wars in cwl_total_wars.items():
            player_rating[tag].cwl_total_wars = total_wars
        for tag, total_attacks in cw_total_attacks_by_tag.items():
            player_rating[tag].cw_total_attacks = total_attacks
        for tag, cwl_clan_tag in cwl_clan_tag_by_player.items():
            player_rating[tag].cwl_clan_tag = cwl_clan_tag
        for tag, league_numbers in league_numbers_by_tag.items():
            player_rating[tag].league_numbers = league_numbers
        for tag, leagues_places in leagues_places_by_tag.items():
            player_rating[tag].leagues_places = leagues_places

        for tag, rating in player_rating.items():
            rating.total_cwl_points = rating.cwl_total_stars / 21 * 55 + (5 if rating.cwl_total_stars >= 21 else 0)
            rating.total_league_points = league_points_by_tag.get(tag, 0) / days_in_month
            rating.total_place_points = place_points_by_tag.get(tag, 0) / days_in_month
            rating.total_raids_attack_points = (
                raids_attack_points_by_tag.get(tag, 0) / total_raid_weekends if total_raid_weekends > 0 else 0
            )
            rating.total_raids_gold_points = (
                raids_gold_points_by_tag.get(tag, 0) / total_raid_weekends if total_raid_weekends > 0 else 0
            )
            rating.total_raids_points = rating.total_raids_attack_points + rating.total_raids_gold_points
            rating.total_cw_penalty_points = cw_penalty_points_by_tag.get(tag, 0)
            rating.total_points = (
                rating.total_cwl_points +
                rating.total_league_points +
                rating.total_place_points +
                rating.total_raids_points +
                rating.total_cw_penalty_points
            )

        player_rating = {
            player_tag: rating for player_tag, rating in player_rating.items()
            if player_tag in town_hall_levels or rating.total_points != 0
        }

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

    def load_mentioned_first_name_and_username_to_html(self, chat_id: int, user_id: int) -> str:
        text = (
            f'<a href="tg://user?id={user_id}">'
            f'{self.of.to_html(self.load_first_name(chat_id, user_id))}</a>'
        )
        if self.load_username(chat_id, user_id) is not None:
            text += f' {self.of.to_html(self.load_username(chat_id, user_id))}'
        return text

    def load_mentioned_full_name_and_username_to_html(self, chat_id: int, user_id: int) -> str:
        text = (
            f'<a href="tg://user?id={user_id}">'
            f'{self.of.to_html(self.load_full_name(chat_id, user_id))}</a>'
        )
        if self.load_username(chat_id, user_id) is not None:
            text += f' {self.of.to_html(self.load_username(chat_id, user_id))}'
        return text

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

    async def can_user_edit_cw_list(self, chat_id: int, user_id: int) -> bool:
        row = await self.acquired_connection.fetchrow('''
            SELECT clan_tag, chat_id, user_id
            FROM bot_user
            WHERE
                ((clan_tag, chat_id, user_id) = ($1, $2, $3) OR (clan_tag, chat_id, user_id) = ($1, $3, $3))
                AND can_edit_cw_list
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

    async def get_clan_member_user_ids(self, chat_id: int) -> list[int]:
        rows = await self.acquired_connection.fetch('''
            SELECT DISTINCT user_id, first_name
            FROM
                player
                JOIN player_bot_user USING (clan_tag, player_tag)
                JOIN bot_user USING (clan_tag, chat_id, user_id)
            WHERE clan_tag = $1 AND is_player_in_clan AND chat_id = $2 AND is_user_in_chat
            ORDER BY first_name
        ''', self.clan_tag, chat_id)
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
                    self.load_mentioned_first_name_and_username_to_html(chat_id, user_id_to_ping)
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
                text += f'👤 {self.load_mentioned_full_name_and_username_to_html(chat_id, user_id)} — '
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
