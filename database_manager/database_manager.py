import asyncio
import json
from collections import namedtuple
from datetime import datetime, UTC
from typing import Optional, Tuple, Any

import asyncpg
from aiogram import Bot
from aiogram.enums import ChatType, ParseMode
from aiogram.types import Chat, User, Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from asyncpg import Record, Pool

from async_client import AsyncClient
from bot.commands import set_cw_commands, set_cwl_commands, set_commands
from bot.config import config
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
    def __init__(self,
                 clan_tag: str,
                 bot: Bot):
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
        self.frequent_jobs_frequency_minutes = 1
        self.infrequent_jobs_frequency_minutes = 10
        self.job_timespan_seconds = 10

        self.clan_tag = clan_tag
        self.bot = bot

        self.name = None
        self.name_and_tag = None
        self.first_name = None
        self.full_name = None
        self.full_name_and_username = None

    async def establish_connections(self) -> None:
        self.connection_pool = await asyncpg.create_pool(
            host=config.postgres_host.get_secret_value(),
            database=config.postgres_database.get_secret_value(),
            user=config.postgres_user.get_secret_value(),
            password=config.postgres_password.get_secret_value(),
            server_settings={'search_path': 'public'}
        )
        self.acquired_connection = AcquiredConnection(self.connection_pool)

    async def start_scheduler(self, bot_number: int) -> None:
        scheduler = AsyncIOScheduler()
        infrequent_jobs_minutes = [
            minute * self.infrequent_jobs_frequency_minutes
            for minute in range(0, 60 // self.infrequent_jobs_frequency_minutes)
        ]
        frequent_jobs_minutes = [
            minute * self.frequent_jobs_frequency_minutes
            for minute in range(0, 60 // self.frequent_jobs_frequency_minutes)
            if minute * self.frequent_jobs_frequency_minutes not in infrequent_jobs_minutes
        ]
        infrequent_jobs_minutes_str = ','.join(map(str, infrequent_jobs_minutes))
        frequent_jobs_minutes_str = ','.join(map(str, frequent_jobs_minutes))
        scheduler.add_job(
            self.frequent_jobs,
            'cron',
            minute=frequent_jobs_minutes_str,
            second=str(bot_number * self.job_timespan_seconds)
        )
        scheduler.add_job(
            self.infrequent_jobs,
            'cron',
            minute=infrequent_jobs_minutes_str,
            second=str(bot_number * self.job_timespan_seconds)
        )
        scheduler.start()

    async def frequent_jobs(self) -> None:
        were_clan_members_dumped = await self.check_clan_members()
        if not were_clan_members_dumped:
            await self.load_and_cache_names()
        await self.dump_clan_games()
        await self.dump_clan_war()
        await self.dump_raid_weekends()
        await self.dump_clan_war_league()
        await self.dump_clan_war_league_wars()

    async def infrequent_jobs(self) -> None:
        await self.set_actual_commands()
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

    async def set_actual_commands(self) -> bool:
        cw_start_time = None
        cw = await self.load_clan_war()
        if cw:
            cw_start_time = cw['startTime']
        cwlw_start_time = None
        _, cwlw = await self.load_clan_war_league_own_war()
        if cwlw:
            cwlw_start_time = cwlw['startTime']
        if cw_start_time and cwlw_start_time and cw_start_time > cwlw_start_time:
            await set_cw_commands(self.bot)
        elif cw_start_time and cwlw_start_time and cw_start_time < cwlw_start_time:
            await set_cwl_commands(self.bot)
        else:
            await set_commands(self.bot)
        return True

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
            clan_member_tag for clan_member_tag in retrieved_clan_member_tags
            if clan_member_tag not in loaded_clan_member_tags
        ]
        left_clan_member_tags = [
            clan_member_tag for clan_member_tag in loaded_clan_member_tags
            if clan_member_tag not in retrieved_clan_member_tags
        ]
        if left_clan_member_tags or joined_clan_member_tags:
            were_clan_members_dumped = True
            await self.dump_clan_members()
            await self.load_and_cache_names()
            rows = await self.acquired_connection.fetch('''
                SELECT chat_id
                FROM clan_chat
                WHERE clan_tag = $1 AND send_member_updates
            ''', self.clan_tag)
            chat_ids = [row['chat_id'] for row in rows]
            for chat_id in chat_ids:
                message_text = (
                    f'<b>💬 Список участников клана изменился</b>\n'
                    f'\n'
                )
                for clan_member_tag in left_clan_member_tags + joined_clan_member_tags:
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
                            self.of.to_html(self.load_full_name(chat_id, user_id)) for user_id in user_ids
                        )})'
                    message_text += f'Игрок <b>{self.of.to_html(self.load_name(clan_member_tag))}</b>{mentions} '
                    if clan_member_tag in left_clan_member_tags:
                        message_text += f'больше не состоит в клане\n'
                    elif clan_member_tag in joined_clan_member_tags:
                        message_text += f'вступил в клан\n'
                message_text += (
                    f'\n'
                    f'Количество участников: {len(retrieved_clan_members['items'])} / 50 👤\n'
                )
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
        player_tasks = [self.api_client.get_player(player_tag=clan_member['tag'])
                        for clan_member
                        in retrieved_clan_members['items']]
        retrieved_players = list(await asyncio.gather(*player_tasks))
        if None in retrieved_players:
            return False
        rows = []
        for player in retrieved_players:
            player_heroes = player.get('heroes', [])
            barbarian_king_level = 0
            archer_queen_level = 0
            grand_warden_level = 0
            royal_champion_level = 0
            for player_hero in player_heroes:
                if player_hero['name'] == 'Barbarian King':
                    barbarian_king_level = player_hero['level']
                elif player_hero['name'] == 'Archer Queen':
                    archer_queen_level = player_hero['level']
                elif player_hero['name'] == 'Grand Warden':
                    grand_warden_level = player_hero['level']
                elif player_hero['name'] == 'Royal Champion':
                    royal_champion_level = player_hero['level']
            rows.append((
                self.clan_tag, player['tag'],
                player['name'], True, False,
                barbarian_king_level, archer_queen_level,
                grand_warden_level, royal_champion_level,
                player['townHallLevel'], player.get('builderHallLevel', 0),
                player['trophies'], player.get('builderBaseTrophies', 0),
                player['role'], player['clanCapitalContributions'],
                player['donations'], player['donationsReceived']
            ))
        await self.acquired_connection.execute('''
            UPDATE player
            SET is_player_in_clan = FALSE
            WHERE clan_tag = $1
        ''', self.clan_tag)
        await self.acquired_connection.executemany('''
            INSERT INTO player
                (clan_tag, player_tag,
                player_name, is_player_in_clan, is_player_set_for_clan_wars,
                barbarian_king_level, archer_queen_level,
                grand_warden_level, royal_champion_level,
                town_hall_level, builder_hall_level,
                home_village_trophies, builder_base_trophies,
                player_role, capital_gold_contributed,
                donations_given, donations_received,
                first_seen, last_seen)
            VALUES
                ($1, $2,
                $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17,
                CURRENT_TIMESTAMP(0), CURRENT_TIMESTAMP(0))
            ON CONFLICT (clan_tag, player_tag)
            DO UPDATE SET
                (player_name, is_player_in_clan,
                barbarian_king_level, archer_queen_level,
                grand_warden_level, royal_champion_level,
                town_hall_level, builder_hall_level,
                home_village_trophies, builder_base_trophies,
                player_role, capital_gold_contributed,
                donations_given, donations_received,
                last_seen) =
                ($3, $4, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17,
                CURRENT_TIMESTAMP(0))
        ''', rows)
        return True

    async def load_and_cache_names(self) -> None:
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
            if new_contributions.get(player_tag) and new_contributions[player_tag] > old_contributions[player_tag]:
                await self.acquired_connection.execute('''
                    INSERT INTO capital_contribution (clan_tag, player_tag, gold_amount, contribution_timestamp)
                    VALUES ($1, $2, $3, CURRENT_TIMESTAMP(0))
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
        old_clan_war = await self.load_clan_war() or {'startTime': None, 'state': None}

        retrieved_clan_war = await self.api_client.get_clan_current_war(clan_tag=self.clan_tag)
        if retrieved_clan_war is None or retrieved_clan_war.get('startTime') is None:
            return False
        await self.acquired_connection.execute('''
            INSERT INTO clan_war (clan_tag, start_time, data)
            VALUES ($1, $2, $3)
            ON CONFLICT (clan_tag, start_time)
            DO UPDATE SET data = $3
        ''', self.clan_tag, self.of.to_datetime(retrieved_clan_war['startTime']), json.dumps(retrieved_clan_war))

        new_clan_war = await self.load_clan_war()

        await self.clan_war_alert(old_clan_war, new_clan_war)

        return True

    async def load_clan_war(self) -> Optional[dict]:
        row = await self.acquired_connection.fetchrow('''
            SELECT data
            FROM clan_war
            WHERE clan_tag = $1
            ORDER BY start_time DESC
        ''', self.clan_tag)
        if row is None:
            return None
        return json.loads(row['data'])

    async def clan_war_alert(self, old_cw: dict, cw: dict) -> None:
        HOUR = 3600
        await self.acquired_connection.execute('''
            INSERT INTO activity
                (clan_tag, name, start_time,
                preparation_message_sent, start_message_sent, half_time_remaining_message_sent, end_message_sent)
            VALUES
                ($1, $2, $3, FALSE, FALSE, FALSE, FALSE)
            ON CONFLICT (clan_tag, name, start_time) DO NOTHING;
        ''', self.clan_tag, 'clan_war', self.of.to_datetime(cw['startTime']))
        row = await self.acquired_connection.fetchrow('''
            SELECT
                clan_tag, name, start_time,
                preparation_message_sent, start_message_sent, half_time_remaining_message_sent, end_message_sent
            FROM activity
            WHERE (clan_tag, name, start_time) = ($1, $2, $3)
        ''', self.clan_tag, 'clan_war', self.of.to_datetime(cw['startTime']))
        texts = []
        pings = []
        if (not row['end_message_sent'] and self.of.war_state(cw) == 'warEnded'
                and self.of.war_state(old_cw) != self.of.war_state(cw)):
            texts.append(
                f'<b>💬 КВ закончилась</b>\n'
                f'\n'
                f'{self.of.cw_in_war_or_ended(cw)}'
            )
            pings.append(False)
            await self.set_activity_end_message_sent(
                self.clan_tag, 'clan_war', self.of.to_datetime(cw['startTime'])
            )
        elif (not row['half_time_remaining_message_sent']
              and self.of.war_state(cw) == 'inWar'
              and (8 * HOUR) <= (self.of.to_datetime(cw['endTime']) - self.of.utc_now()).seconds <= 12 * HOUR):
            texts.append(
                f'<b>📣 До конца КВ осталось менее 12 часов</b>\n'
                f'\n'
                f'{self.of.cw_in_war_or_ended(cw)}'
            )
            pings.append(True)
            await self.set_activity_half_time_remaining_message_sent(
                self.clan_tag, 'clan_war', self.of.to_datetime(cw['startTime'])
            )
        elif (not row['start_message_sent'] and self.of.war_state(cw) == 'inWar'
              and self.of.war_state(old_cw) != self.of.war_state(cw)):
            texts.append(
                f'<b>📣 КВ началась</b>\n'
                f'\n'
                f'{self.of.cw_in_war_or_ended(cw)}'
            )
            pings.append(True)
            await self.set_activity_start_message_sent(
                self.clan_tag, 'clan_war', self.of.to_datetime(cw['startTime'])
            )
        elif (not row['preparation_message_sent'] and self.of.war_state(cw) == 'preparation'
              and old_cw['startTime'] != cw['startTime']):
            texts.append(
                f'<b>💬 КВ найдена</b>\n'
                f'\n'
                f'{self.of.cw_preparation(cw)}'
            )
            pings.append(False)
            await self.set_activity_preparation_message_sent(
                self.clan_tag, 'clan_war', self.of.to_datetime(cw['startTime'])
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
                    user_ids_to_ping=await self.get_war_member_user_ids(row['chat_id'], cw) if ping else None
                )

    async def dump_raid_weekends(self) -> bool:
        old_raid = await self.load_raid_weekend() or {'startTime': None, 'state': None}

        retrieved_raid_weekends = await self.api_client.get_clan_capital_raid_seasons(clan_tag=self.clan_tag)
        if not retrieved_raid_weekends or not retrieved_raid_weekends['items']:
            return False
        await self.acquired_connection.executemany('''
            INSERT INTO raid_weekend (clan_tag, start_time, data)
            VALUES ($1, $2, $3)
            ON CONFLICT (clan_tag, start_time)
            DO UPDATE SET data = $3
        ''', [(self.clan_tag, self.of.to_datetime(item['startTime']), json.dumps(item))
              for item
              in retrieved_raid_weekends['items']])

        new_raid = await self.load_raid_weekend()

        await self.raid_weekend_alert(old_raid, new_raid)

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

    async def raid_weekend_alert(self, old_raid: dict, raid: dict) -> None:
        await self.acquired_connection.execute('''
            INSERT INTO activity
                (clan_tag, name, start_time,
                preparation_message_sent, start_message_sent, half_time_remaining_message_sent, end_message_sent)
            VALUES
                ($1, $2, $3, NULL, FALSE, NULL, FALSE)
            ON CONFLICT (clan_tag, name, start_time) DO NOTHING;
        ''', self.clan_tag, 'raid_weekend', self.of.to_datetime(raid['startTime']))
        row = await self.acquired_connection.fetchrow('''
            SELECT
                clan_tag, name, start_time,
                preparation_message_sent, start_message_sent, half_time_remaining_message_sent, end_message_sent
            FROM activity
            WHERE (clan_tag, name, start_time) = ($1, $2, $3)
        ''', self.clan_tag, 'raid_weekend', self.of.to_datetime(raid['startTime']))
        texts = []
        pings = []
        if not row['end_message_sent'] and raid['state'] == 'ended' and old_raid['state'] != raid['state']:
            texts.append(
                f'<b>💬 Рейды закончились</b>\n'
                f'\n'
                f'{self.of.raid_ongoing_or_ended(raid)}'
            )
            pings.append(False)
            await self.set_activity_end_message_sent(
                self.clan_tag, 'raid_weekend', self.of.to_datetime(raid['startTime'])
            )
        elif (not row['start_message_sent'] and old_raid['startTime'] != raid['startTime']
              and raid['state'] == 'ongoing'):
            texts.append(
                f'<b>📣 Рейды начались</b>\n'
                f'\n'
                f'{self.of.raid_ongoing_or_ended(raid)}'
            )
            pings.append(True)
            await self.set_activity_start_message_sent(
                self.clan_tag, 'raid_weekend', self.of.to_datetime(raid['startTime'])
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

    async def load_clan_war_league(self) -> Tuple[Optional[str], Optional[dict]]:
        row = await self.acquired_connection.fetchrow('''
            SELECT season, data
            FROM clan_war_league
            WHERE clan_tag = $1
            ORDER BY season DESC 
        ''', self.clan_tag)
        if row is None:
            return None, None
        return row['season'], json.loads(row['data'])

    async def dump_clan_war_league_wars(self) -> bool:
        old_cwl_season, _ = await self.load_clan_war_league()
        old_cwlws = await self.load_clan_war_league_own_wars() or []

        loaded_clan_war_league_season, loaded_clan_war_league = await self.load_clan_war_league()
        if loaded_clan_war_league is None:
            return False
        ClanWarLeagueWar = namedtuple(
            typename='ClanWarLeagueWar', field_names='clan_tag war_tag season day'
        )
        clan_war_league_wars = [
            ClanWarLeagueWar(
                clan_tag=self.clan_tag,
                war_tag=war_tag,
                season=loaded_clan_war_league_season,
                day=day
            )
            for day, war_tags in enumerate(loaded_clan_war_league['rounds'])
            for war_tag in war_tags['warTags'] if war_tag != '#0'
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
        if old_cwl_season != new_cwl_season:
            old_cwlws = []
        if len(old_cwlws) < len(new_cwlws):
            old_cwlws += [{'startTime': None, 'state': None}] * (len(new_cwlws) - len(old_cwlws))
        for cwl_day, (old_cwlw, new_cwlw) in enumerate(zip(old_cwlws, new_cwlws)):
            await self.clan_war_league_war_alert(old_cwlw, new_cwlw, new_cwl_season, cwl_day)
        return True

    async def load_clan_war_league_own_war(self) -> Tuple[Optional[int], Optional[dict]]:
        clan_war_league_wars = await self.load_clan_war_league_own_wars()
        if clan_war_league_wars is None:
            return None, None
        for day, clan_war_league_war in (list(enumerate(clan_war_league_wars)))[::-1]:
            if self.of.war_state(clan_war_league_war) == 'inWar':
                return day, clan_war_league_war
        for day, clan_war_league_war in (list(enumerate(clan_war_league_wars)))[::-1]:
            if self.of.war_state(clan_war_league_war) == 'preparation':
                return day, clan_war_league_war
        for day, clan_war_league_war in (list(enumerate(clan_war_league_wars)))[::-1]:
            if self.of.war_state(clan_war_league_war) == 'warEnded':
                return day, clan_war_league_war
        for day, clan_war_league_war in enumerate(clan_war_league_wars):
            return day, clan_war_league_war

    async def load_clan_war_league_own_wars(self) -> Optional[list[dict]]:
        season, _ = await self.load_clan_war_league()
        if season is None:
            return None
        rows = await self.acquired_connection.fetch('''
            SELECT data
            FROM clan_war_league_war
            WHERE (clan_tag, season) = ($1, $2) AND $1 IN (data->'clan'->>'tag', data->'opponent'->>'tag')
            ORDER BY day
        ''', self.clan_tag, season)
        clan_war_league_wars = []
        for row in rows:
            clan_war_league_war = json.loads(row['data'])
            if clan_war_league_war['opponent']['tag'] == self.clan_tag:
                clan_war_league_war['clan'], clan_war_league_war['opponent'] = (
                    clan_war_league_war['opponent'], clan_war_league_war['clan'])
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

    async def clan_war_league_war_alert(self, old_cwlw: dict, cwlw: dict, cwl_season: str, cwl_day: int) -> None:
        HOUR = 3600
        await self.acquired_connection.execute('''
            INSERT INTO activity
                (clan_tag, name, start_time,
                preparation_message_sent, start_message_sent, half_time_remaining_message_sent, end_message_sent)
            VALUES
                ($1, $2, $3, FALSE, FALSE, FALSE, FALSE)
            ON CONFLICT (clan_tag, name, start_time) DO NOTHING;
        ''', self.clan_tag, 'clan_war_league_war', self.of.to_datetime(cwlw['startTime']))
        row = await self.acquired_connection.fetchrow('''
            SELECT
                clan_tag, name, start_time,
                preparation_message_sent, start_message_sent, half_time_remaining_message_sent, end_message_sent
            FROM activity
            WHERE (clan_tag, name, start_time) = ($1, $2, $3)
        ''', self.clan_tag, 'clan_war_league_war', self.of.to_datetime(cwlw['startTime']))
        texts = []
        pings = []
        if (not row['end_message_sent'] and self.of.war_state(cwlw) == 'warEnded'
                and self.of.war_state(old_cwlw) != self.of.war_state(cwlw)):
            texts.append(
                f'<b>💬 День ЛВК закончился</b>\n'
                f'\n'
                f'{self.of.cwlw_war_ended(cwlw, cwl_season, cwl_day)}'
            )
            pings.append(False)
            await self.set_activity_end_message_sent(
                self.clan_tag, 'clan_war_league_war', self.of.to_datetime(cwlw['startTime'])
            )
        elif (not row['half_time_remaining_message_sent']
              and self.of.war_state(cwlw) == 'inWar'
              and 8 * HOUR <= (self.of.to_datetime(cwlw['endTime']) - self.of.utc_now()).seconds <= 12 * HOUR):
            texts.append(
                f'<b>📣 До конца дня ЛВК осталось менее 12 часов</b>\n'
                f'\n'
                f'{self.of.cwlw_in_war(cwlw, cwl_season, cwl_day)}'
            )
            pings.append(True)
            await self.set_activity_half_time_remaining_message_sent(
                self.clan_tag, 'clan_war_league_war', self.of.to_datetime(cwlw['startTime'])
            )
        elif (not row['start_message_sent'] and self.of.war_state(cwlw) == 'inWar'
              and self.of.war_state(old_cwlw) != self.of.war_state(cwlw)):
            texts.append(
                f'<b>📣 День ЛВК начался</b>\n'
                f'\n'
                f'{self.of.cwlw_in_war(cwlw, cwl_season, cwl_day)}'
            )
            pings.append(True)
            await self.set_activity_start_message_sent(
                self.clan_tag, 'clan_war_league_war', self.of.to_datetime(cwlw['startTime'])
            )
        elif (not row['preparation_message_sent'] and self.of.war_state(cwlw) == 'preparation'
              and old_cwlw['startTime'] != cwlw['startTime']):
            texts.append(
                f'<b>💬 Подготовка ко дню ЛВК началась</b>\n'
                f'\n'
                f'{self.of.cwlw_preparation(cwlw, cwl_season, cwl_day)}'
            )
            pings.append(False)
            await self.set_activity_preparation_message_sent(
                self.clan_tag, 'clan_war_league_war', self.of.to_datetime(cwlw['startTime'])
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
                    user_ids_to_ping=await self.get_war_member_user_ids(row['chat_id'], cwlw) if ping else None
                )

    async def dump_user(self, chat: Chat, user: User) -> None:
        if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
            await self.acquired_connection.execute('''
                INSERT INTO bot_user
                    (clan_tag, chat_id, user_id,
                    username, first_name, last_name, is_user_in_chat, first_seen, last_seen)
                VALUES 
                    ($1, $2, $3,
                    $4, $5, $6, TRUE, CURRENT_TIMESTAMP(0), CURRENT_TIMESTAMP(0))
                ON CONFLICT (clan_tag, chat_id, user_id) DO
                UPDATE
                SET
                    (username, first_name, last_name, is_user_in_chat, last_seen) = 
                    ($4, $5, $6, TRUE, CURRENT_TIMESTAMP(0))
            ''', self.clan_tag, chat.id, user.id, user.username, user.first_name, user.last_name)
        elif chat.type == ChatType.PRIVATE:
            await self.acquired_connection.execute('''
                INSERT INTO bot_user
                    (clan_tag, chat_id, user_id,
                    username, first_name, last_name, is_user_in_chat, first_seen, last_seen,
                    can_use_bot_without_clan_group,
                    can_ping_group_members,
                    can_link_group_members,
                    can_edit_cw_list,
                    can_send_messages_from_bot)
                VALUES 
                    ($1, $2, $3,
                    $4, $5, $6, TRUE, CURRENT_TIMESTAMP(0), CURRENT_TIMESTAMP(0),
                    FALSE, FALSE, FALSE, FALSE, FALSE)
                ON CONFLICT (clan_tag, chat_id, user_id) DO
                UPDATE
                SET
                    (username, first_name, last_name, is_user_in_chat, last_seen) = 
                    ($4, $5, $6, TRUE, CURRENT_TIMESTAMP(0))
            ''', self.clan_tag, chat.id, user.id, user.username, user.first_name, user.last_name)

    async def undump_user(self, chat: Chat, user: User) -> None:
        await self.acquired_connection.execute('''
            UPDATE bot_user
            SET (username, first_name, last_name, is_user_in_chat, last_seen) = 
                ($4, $5, $6, FALSE, CURRENT_TIMESTAMP(0))
            WHERE (clan_tag, chat_id, user_id) = ($1, $2, $3)
        ''', self.clan_tag, chat.id, user.id, user.username, user.first_name, user.last_name)

    async def dump_chat(self, chat: Chat) -> None:
        if chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
            await self.acquired_connection.execute('''
                INSERT INTO chat (clan_tag, chat_id, type, title)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (clan_tag, chat_id) DO
                UPDATE SET (type, title) = ($3, $4)
            ''', self.clan_tag, chat.id, chat.type, chat.title)
        elif chat.type == ChatType.PRIVATE:
            await self.acquired_connection.execute('''
                INSERT INTO chat (clan_tag, chat_id, type, username, first_name, last_name)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (clan_tag, chat_id) DO
                UPDATE SET (type, username, first_name, last_name) = ($3, $4, $5, $6)
            ''', self.clan_tag, chat.id, chat.type, chat.username, chat.first_name, chat.last_name)

    def load_name(self, player_tag: str) -> str:
        return self.name.get(player_tag, 'UNKNOWN')

    def load_name_and_tag(self, player_tag: str) -> str:
        return self.name_and_tag.get(player_tag, f'UNKNOWN ({player_tag})')

    def load_first_name(self, chat_id: int, user_id: int) -> str:
        return self.first_name.get((chat_id, user_id), 'UNKNOWN')

    def load_full_name(self, chat_id: int, user_id: int) -> str:
        return self.full_name.get((chat_id, user_id), 'UNKNOWN')

    def load_full_name_and_username(self, chat_id: int, user_id: int) -> str:
        return self.full_name_and_username.get((chat_id, user_id), 'UNKNOWN')

    def load_mentioned_first_name_to_html(self, chat_id: int, user_id: int) -> str:
        return (f'<a href="tg://user?id={user_id}">'
                f'{self.of.to_html(self.load_first_name(chat_id, user_id))}</a>')

    def load_mentioned_full_name_to_html(self, chat_id: int, user_id: int) -> str:
        return (f'<a href="tg://user?id={user_id}">'
                f'{self.of.to_html(self.load_full_name(chat_id, user_id))}</a>')

    def load_mentioned_full_name_and_username_to_html(self, chat_id: int, user_id: int) -> str:
        return (f'<a href="tg://user?id={user_id}">'
                f'{self.of.to_html(self.load_full_name_and_username(chat_id, user_id))}</a>')

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
        return row and row['user_id'] == user.id

    async def can_user_use_bot(self, user_id: int) -> bool:
        row = await self.acquired_connection.fetchrow('''
            SELECT clan_tag, chat_id, user_id
            FROM bot_user
            WHERE
                clan_tag = $1
                AND (chat_id IN (SELECT chat_id FROM clan_chat WHERE clan_tag = $1) AND is_user_in_chat
                     OR can_use_bot_without_clan_group)
                AND user_id = $2
        ''', self.clan_tag, user_id)
        return row

    async def can_user_ping_group_members(self, chat_id: int, user_id: int) -> bool:
        row = await self.acquired_connection.fetchrow('''
            SELECT clan_tag, chat_id, user_id
            FROM bot_user
            WHERE (clan_tag, chat_id, user_id) IN (($1, $2, $3), ($1, $3, $3)) AND can_ping_group_members
        ''', self.clan_tag, chat_id, user_id)
        return row

    async def can_user_link_group_members(self, chat_id: int, user_id: int) -> bool:
        row = await self.acquired_connection.fetchrow('''
            SELECT clan_tag, chat_id, user_id
            FROM bot_user
            WHERE (clan_tag, chat_id, user_id) IN (($1, $2, $3), ($1, $3, $3)) AND can_link_group_members
        ''', self.clan_tag, chat_id, user_id)
        return row

    async def can_user_edit_cw_list(self, chat_id: int, user_id: int) -> bool:
        row = await self.acquired_connection.fetchrow('''
            SELECT clan_tag, chat_id, user_id
            FROM bot_user
            WHERE (clan_tag, chat_id, user_id) IN (($1, $2, $3), ($1, $3, $3)) AND can_edit_cw_list
        ''', self.clan_tag, chat_id, user_id)
        return row

    async def can_user_send_messages_from_bot(self, chat_id: int, user_id: int) -> bool:
        row = await self.acquired_connection.fetchrow('''
            SELECT clan_tag, chat_id, user_id
            FROM bot_user
            WHERE (clan_tag, chat_id, user_id) IN (($1, $2, $3), ($1, $3, $3)) AND can_send_messages_from_bot
        ''', self.clan_tag, chat_id, user_id)
        return row

    async def is_player_linked_to_user(self, player_tag: str, chat_id: int, user_id: int) -> bool:
        rows = await self.acquired_connection.fetch('''
            SELECT player_tag
            FROM
                player
                JOIN player_bot_user USING (clan_tag, player_tag)
                JOIN bot_user USING (clan_tag, chat_id, user_id)
            WHERE clan_tag = $1 AND is_player_in_clan AND chat_id = $2 AND user_id = $3 AND is_user_in_chat
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

    async def get_war_member_user_ids(self, chat_id: int, war: dict) -> list[int]:
        war_member_tags = []
        for war_member in war['clan']['members']:
            if len(war_member.get('attacks', [])) < 2:
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
            message_text += (f'\n'
                             f'{', '.join(self.load_mentioned_first_name_to_html(
                                 chat_id, user_id_to_ping) for user_id_to_ping in user_ids_to_ping)}\n')
        log_text = f'Message "{message_text}" was sent to group {chat_title} ({chat_id})'
        await self.bot.send_message(chat_id=chat_id,
                                    text=message_text,
                                    parse_mode=ParseMode.HTML,
                                    reply_markup=None)
        await self.acquired_connection.execute('''
            INSERT INTO action (clan_tag, chat_id, user_id, action_timestamp, description)
            VALUES ($1, $2, $3, CURRENT_TIMESTAMP(0), $4)
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

    async def print_skips(self, message: Message, members: list, ping: bool, attacks_limit: int) -> str:
        if message.chat.type == ChatType.PRIVATE:
            chat_id = await self.get_main_chat_id()
        else:
            chat_id = message.chat.id
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
        members_by_user_to_mention = {}
        unlinked_members = []
        users_by_player = {player_tag: [] for player_tag in [row['player_tag'] for row in rows]}
        for row in rows:
            users_by_player[row['player_tag']].append(row['user_id'])
        for member in members:
            if member.attacks_spent < attacks_limit or member.attacks_spent < member.attacks_limit:
                for user_id in users_by_player.get(member.player_tag, []):
                    if members_by_user_to_mention.get(user_id) is None:
                        members_by_user_to_mention[user_id] = []
                    members_by_user_to_mention[user_id].append(member)
                if users_by_player.get(member.player_tag) is None:
                    unlinked_members.append(member)
        text = ''
        for user_id, players in members_by_user_to_mention.items():
            if ping:
                text += f'{self.load_mentioned_full_name_to_html(chat_id, user_id)} — '
            else:
                text += f'{self.of.to_html(self.load_full_name(chat_id, user_id))} — '
            text += (', '.join([f'{self.of.to_html(self.load_name(player.player_tag))}: '
                                f'{player.attacks_spent} / {player.attacks_limit}'
                                for player in players]) +
                     '\n')
        if len(members_by_user_to_mention) > 0:
            text += '\n'
        for player in unlinked_members:
            text += (f'{self.of.to_html(self.load_name(player.player_tag))}: '
                     f'{player.attacks_spent} / {player.attacks_limit}\n')
        if len(members_by_user_to_mention) + len(unlinked_members) == 0:
            text += f'Список пуст'
        return text
