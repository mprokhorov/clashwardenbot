import asyncio
import json
from collections import namedtuple
from datetime import datetime
from typing import Optional, Tuple

import asyncpg
from aiogram.enums import ChatType
from aiogram.types import Chat, User, Message
from asyncpg import Record

from async_client import AsyncClient
from bot.config import config
from output_formatter import OutputFormatter


class DatabaseManager:
    def __init__(self,
                 clan_tag: str,
                 telegram_bot_api_token: str,
                 telegram_bot_username: str):
        self.api_client = AsyncClient(email=config.clash_of_clans_api_login.get_secret_value(),
                                      password=config.clash_of_clans_api_password.get_secret_value(),
                                      key_name=config.clash_of_clans_api_key_name.get_secret_value(),
                                      key_description=config.clash_of_clans_api_key_description.get_secret_value())
        self.of = OutputFormatter()

        self.cron_connection = None
        self.req_connection = None

        self.telegram_bot_username = telegram_bot_username
        self.telegram_bot_api_token = telegram_bot_api_token
        self.clan_name = None
        self.clan_tag = clan_tag

        self.name = None
        self.name_and_tag = None
        self.full_name = None
        self.full_name_and_username = None

    async def establish_connections(self) -> None:
        self.cron_connection = await asyncpg.connect(host=config.postgres_host.get_secret_value(),
                                                     database=config.postgres_database.get_secret_value(),
                                                     user=config.postgres_user.get_secret_value(),
                                                     password=config.postgres_password.get_secret_value())

        self.req_connection = await asyncpg.connect(host=config.postgres_host.get_secret_value(),
                                                    database=config.postgres_database.get_secret_value(),
                                                    user=config.postgres_user.get_secret_value(),
                                                    password=config.postgres_password.get_secret_value())

    async def frequent_jobs(self) -> None:
        retrieved_clan_members = await self.api_client.get_clan_members(clan_tag=self.clan_tag)
        if retrieved_clan_members is not None:
            rows = await self.cron_connection.fetch('''
                SELECT player_tag
                FROM master.player
                WHERE player.clan_tag = $1 AND is_player_in_clan
            ''', self.clan_tag)
            loaded_clan_member_tags = [row['player_tag'] for row in rows]
            retrieved_clan_member_tags = [clan_member['tag'] for clan_member in retrieved_clan_members['items']]
            left_clan_member_tags = [clan_member_tag
                                     for clan_member_tag
                                     in loaded_clan_member_tags
                                     if clan_member_tag not in retrieved_clan_member_tags]
            joined_clan_member_tags = [clan_member_tag
                                       for clan_member_tag
                                       in retrieved_clan_member_tags
                                       if clan_member_tag not in loaded_clan_member_tags]
            if len(left_clan_member_tags) > 0:
                pass
            if len(joined_clan_member_tags) > 0:
                await self.dump_clan_members()

        await self.dump_clan_war()
        await self.dump_raid_weekends()
        await self.dump_clan_war_league()
        await self.dump_clan_war_league_wars()

        rows = await self.cron_connection.fetch('''
            SELECT player_tag, player_name
            FROM master.player
            WHERE clan_tag = $1 AND is_player_in_clan
        ''', self.clan_tag)
        self.name = {row['player_tag']: row['player_name'] for row in rows}
        self.name_and_tag = {row['player_tag']: f'{row['player_name']} ({row['player_tag']})' for row in rows}

        rows = await self.cron_connection.fetch('''
            SELECT chat_id, user_id, username, first_name, last_name
            FROM master.tg_user
        ''')
        self.full_name = {(row['chat_id'], row['user_id']):
                          row['first_name'] + (f' {row['last_name']}' if row['last_name'] else '')
                          for row in rows}
        self.full_name_and_username = {(row['chat_id'], row['user_id']):
                                       (f'{row['first_name']}'
                                        f' {row['last_name'] or ''}'
                                        f'{(' (@' + row['username'] + ')') if row['username'] else ''}')
                                       for row in rows}

    async def infrequent_jobs(self) -> None:
        await self.frequent_jobs()

        old_contributions = await self.load_capital_contributions()
        await self.dump_clan_members()
        new_contributions = await self.load_capital_contributions()
        for player_tag in old_contributions:
            if new_contributions.get(player_tag) and new_contributions[player_tag] > old_contributions[player_tag]:
                await self.cron_connection.execute('''
                    INSERT INTO master.capital_contribution (clan_tag, player_tag, gold_amount, contribution_timestamp)
                    VALUES ($1, $2, $3, CURRENT_TIMESTAMP(0))
                ''', self.clan_tag, player_tag, new_contributions[player_tag] - old_contributions[player_tag])

    async def dump_clan_members(self) -> None:
        retrieved_clan_members = await self.api_client.get_clan_members(clan_tag=self.clan_tag)
        if retrieved_clan_members is None:
            return
        player_tasks = [self.api_client.get_player(player_tag=clan_member['tag'])
                        for clan_member
                        in retrieved_clan_members['items']]
        retrieved_players = list(await asyncio.gather(*player_tasks))
        rows = []
        for player in retrieved_players:
            player_heroes = player['heroes']
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
            rows.append((self.clan_tag, player['tag'],
                         player['name'], True, False,
                         barbarian_king_level, archer_queen_level,
                         grand_warden_level, royal_champion_level,
                         player['townHallLevel'], player.get('builderHallLevel') or 0,
                         player['trophies'], player.get('builderBaseTrophies') or 0,
                         player['role'], player['clanCapitalContributions'],
                         player['donations'], player['donationsReceived']))

        await self.cron_connection.execute('''
            UPDATE master.player
            SET is_player_in_clan = FALSE
        ''')
        await self.cron_connection.executemany('''
            INSERT INTO master.player
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

    async def load_capital_contributions(self) -> dict:
        rows = await self.cron_connection.fetch('''
            SELECT player_tag, capital_gold_contributed
            FROM master.player
            WHERE is_player_in_clan AND clan_tag = $1
        ''', self.clan_tag)
        return {row['player_tag']: row['capital_gold_contributed'] for row in rows}

    async def dump_clan_war(self) -> None:
        retrieved_clan_war = await self.api_client.get_clan_current_war(clan_tag=self.clan_tag)
        if retrieved_clan_war is None or retrieved_clan_war.get('startTime') is None:
            return

        await self.cron_connection.execute('''
            INSERT INTO master.clan_war (clan_tag, start_time, data)
            VALUES ($1, $2, $3)
            ON CONFLICT (clan_tag, start_time)
            DO UPDATE SET data = $3
        ''', self.clan_tag, datetime.strptime(retrieved_clan_war['startTime'], '%Y%m%dT%H%M%S.%fZ'), json.dumps(retrieved_clan_war))

    async def load_clan_war(self) -> Optional[dict]:
        row = await self.req_connection.fetchrow('''
            SELECT data
            FROM master.clan_war
            WHERE clan_tag = $1
            ORDER BY start_time DESC
        ''', self.clan_tag)
        if row is None:
            return None
        return json.loads(row['data'])

    async def dump_raid_weekends(self) -> None:
        retrieved_raid_weekends = await self.api_client.get_clan_capital_raid_seasons(clan_tag=self.clan_tag)
        if retrieved_raid_weekends is None:
            return
        await self.cron_connection.executemany('''
            INSERT INTO master.raid_weekend (clan_tag, start_time, data)
            VALUES ($1, $2, $3)
            ON CONFLICT (clan_tag, start_time)
            DO UPDATE SET data = $3
        ''', [(self.clan_tag, datetime.strptime(item['startTime'], '%Y%m%dT%H%M%S.%fZ'), json.dumps(item))
              for item
              in retrieved_raid_weekends['items']])

    async def load_raid_weekend(self) -> Optional[dict]:
        row = await self.req_connection.fetchrow('''
            SELECT data
            FROM master.raid_weekend
            WHERE clan_tag = $1
            ORDER BY start_time DESC
        ''', self.clan_tag)
        if row is None:
            return None
        return json.loads(row['data'])

    async def dump_clan_war_league(self) -> None:
        retrieved_clan_war_league = await self.api_client.get_clan_war_league_group(clan_tag=self.clan_tag)
        if retrieved_clan_war_league is None:
            return
        await self.cron_connection.execute('''
            INSERT INTO master.clan_war_league (clan_tag, season, data)
            VALUES ($1, $2, $3)
            ON CONFLICT (clan_tag, season)
            DO UPDATE SET data = $3
        ''', self.clan_tag, retrieved_clan_war_league['season'], json.dumps(retrieved_clan_war_league))

    async def load_clan_war_league(self) -> Tuple[Optional[str], Optional[dict]]:
        row = await self.req_connection.fetchrow('''
            SELECT season, data
            FROM master.clan_war_league
            WHERE clan_tag = $1
            ORDER BY season DESC 
        ''', self.clan_tag)
        if row is None:
            return None, None
        return row['season'], json.loads(row['data'])

    async def dump_clan_war_league_wars(self) -> None:
        loaded_clan_war_league_season, loaded_clan_war_league = await self.load_clan_war_league()
        if loaded_clan_war_league is None:
            return
        ClanWarLeagueWar = namedtuple('ClanWarLeagueWar', 'clan_tag war_tag season day')
        clan_war_league_wars = [ClanWarLeagueWar(clan_tag=self.clan_tag,
                                                 war_tag=war_tag,
                                                 season=loaded_clan_war_league_season,
                                                 day=day)
                                for day, war_tags in enumerate(loaded_clan_war_league['rounds'])
                                for war_tag in war_tags['warTags']]
        clan_war_league_wars_to_retrieve = []
        for clan_war_league_war in clan_war_league_wars:
            row = await self.cron_connection.fetchrow('''
                SELECT clan_tag, war_tag, data->>'state' AS state
                FROM master.clan_war_league_war
                WHERE (clan_tag, war_tag) = ($1, $2) AND data->>'state' = 'warEnded'
            ''', clan_war_league_war.clan_tag, clan_war_league_war.war_tag)
            if row is None:
                clan_war_league_wars_to_retrieve.append(clan_war_league_war)
        clan_war_league_war_tasks = [self.api_client
                                     .get_clan_war_league_war(war_tag=clan_war_league_war_to_retrieve.war_tag)
                                     for clan_war_league_war_to_retrieve in clan_war_league_wars_to_retrieve]
        retrieved_clan_war_league_wars = list(await asyncio.gather(*clan_war_league_war_tasks))
        rows = zip([clan_war_league_war.clan_tag for clan_war_league_war in clan_war_league_wars_to_retrieve],
                   [clan_war_league_war.war_tag for clan_war_league_war in clan_war_league_wars_to_retrieve],
                   [clan_war_league_war.season for clan_war_league_war in clan_war_league_wars_to_retrieve],
                   [clan_war_league_war.day for clan_war_league_war in clan_war_league_wars_to_retrieve],
                   map(json.dumps, retrieved_clan_war_league_wars))
        await self.cron_connection.executemany('''
            INSERT INTO master.clan_war_league_war (clan_tag, war_tag, season, day, data)
            VALUES ($1, $2, $3, $4, $5)
        ''', rows)

    async def load_clan_war_league_own_war(self) -> Tuple[Optional[int], Optional[dict]]:
        clan_war_league_wars = await self.load_clan_war_league_own_wars()
        if clan_war_league_wars is None:
            return None, None
        for day, clan_war_league_war in (list(enumerate(clan_war_league_wars)))[::-1]:
            if clan_war_league_war['state'] == 'inWar':
                return day, clan_war_league_war
        for day, clan_war_league_war in (list(enumerate(clan_war_league_wars)))[::-1]:
            if clan_war_league_war['state'] == 'preparation':
                return day, clan_war_league_war
        for day, clan_war_league_war in (list(enumerate(clan_war_league_wars)))[::-1]:
            if clan_war_league_war['state'] == 'warEnded':
                return day, clan_war_league_war
        for day, clan_war_league_war in enumerate(clan_war_league_wars):
            return day, clan_war_league_war

    async def load_clan_war_league_own_wars(self) -> Optional[list[dict]]:
        season, _ = await self.load_clan_war_league()
        if season is None:
            return None
        rows = await self.req_connection.fetch('''
            SELECT data
            FROM master.clan_war_league_war
            WHERE (clan_tag, season) = ($1, $2) AND $1 IN (data->'clan'->>'tag', data->'opponent'->>'tag')
            ORDER BY day
        ''', self.clan_tag, season)
        if len(rows) == 0:
            raise Exception
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
        rows = await self.req_connection.fetch('''
            SELECT data
            FROM master.clan_war_league_war
            WHERE
                (clan_tag, season) = ($1, $2)
                AND day IN (SELECT MAX(day) FROM master.clan_war_league_war WHERE season = $2)
        ''', self.clan_tag, season)
        if len(rows) == 0:
            raise Exception
        return [json.loads(row['data']) for row in rows]

    async def dump_tg_user(self, chat: Chat, user: User) -> None:
        await self.req_connection.execute('''
            INSERT INTO
                master.tg_user (chat_id, user_id, username, first_name, last_name, is_user_in_chat, first_seen, last_seen)
            VALUES 
                ($1, $2, $3, $4, $5, TRUE, CURRENT_TIMESTAMP(0), CURRENT_TIMESTAMP(0))
            ON CONFLICT (chat_id, user_id) DO
            UPDATE SET (username, first_name, last_name, is_user_in_chat, last_seen) = 
                       ($3, $4, $5, TRUE, CURRENT_TIMESTAMP(0))
        ''', chat.id, user.id, user.username, user.first_name, user.last_name)

    async def undump_tg_user(self, chat: Chat, user: User) -> None:
        await self.req_connection.execute('''
            UPDATE master.tg_user
            SET (username, first_name, last_name, is_user_in_chat, last_seen) = 
                ($3, $4, $5, FALSE, CURRENT_TIMESTAMP(0))
            WHERE (chat_id, user_id) = ($1, $2)
        ''', chat.id, user.id, user.username, user.first_name, user.last_name)

    async def dump_group_chat(self, message: Message) -> None:
        await self.req_connection.execute('''
            INSERT INTO master.chat (chat_id, chat_type, chat_title)
            VALUES ($1, $2, $3)
            ON CONFLICT (chat_id) DO
            UPDATE SET (chat_type, chat_title) = ($2, $3)
        ''', message.chat.id, message.chat.type, message.chat.title)

    async def dump_private_chat(self, message: Message) -> None:
        await self.req_connection.execute('''
            INSERT INTO master.chat (chat_id, chat_type, chat_username, chat_first_name, chat_last_name)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (chat_id) DO
            UPDATE SET (chat_type, chat_username, chat_first_name, chat_last_name) = ($2, $3, $4, $5)
        ''', message.chat.id, message.chat.type, message.chat.username, message.chat.first_name, message.chat.last_name)

    def load_name(self, player_tag: str) -> str:
        return self.name.get(player_tag, 'None')

    def load_name_and_tag(self, player_tag: str) -> str:
        return self.name_and_tag.get(player_tag, f'None {player_tag}')

    def load_full_name(self, chat_id: int, user_id: int) -> str:
        return self.full_name.get((chat_id, user_id), 'None')

    def load_full_name_and_username(self, chat_id: int, user_id: int) -> str:
        return self.full_name_and_username.get((chat_id, user_id), 'None')

    async def dump_message_owner(self, message: Message, user: User) -> None:
        await self.req_connection.execute('''
            INSERT INTO master.message_tg_user (chat_id, message_id, user_id)
            VALUES ($1, $2, $3)
        ''', message.chat.id, message.message_id, user.id)

    async def is_user_message_owner(self, message: Message, user: User) -> bool:
        row = await self.req_connection.fetchrow('''
            SELECT user_id
            FROM master.message_tg_user
            WHERE (chat_id, message_id) = ($1, $2)
        ''', message.chat.id, message.message_id)
        return row.get('user_id') == user.id

    async def can_user_ping_group_members(self, message: Message) -> bool:
        row = await self.req_connection.fetchrow('''
            SELECT can_ping_group_members
            FROM master.tg_user
            WHERE (chat_id, user_id) = ($1, $2)
        ''', message.chat.id, message.from_user.id)
        return row.get('can_ping_group_members', False)

    async def load_groups_where_user_can_link_members(self, user_id: int) -> list[Record]:
        rows = await self.req_connection.fetch('''
            SELECT chat_id, chat_title
            FROM
                master.tg_user
                JOIN master.chat USING (chat_id)
            WHERE user_id = $1 AND can_link_group_members
        ''', user_id)
        return rows

    async def load_groups_where_user_can_edit_cw_list(self, user_id: int) -> list[Record]:
        rows = await self.req_connection.fetch('''
            SELECT chat_id, chat_title
            FROM
                master.tg_user
                JOIN master.chat USING (chat_id)
            WHERE user_id = $1 AND can_edit_cw_list
        ''', user_id)
        return rows

    @staticmethod
    def load_map_positions(war_clan_members: dict) -> dict:
        map_position = {}
        for member in war_clan_members:
            map_position[member['tag']] = member['mapPosition']
        map_position = {item[0]: i + 1
                        for i, item
                        in enumerate(sorted(map_position.items(), key=lambda item: item[1]))}
        return map_position

    async def print_skips(self,
                          message: Message,
                          members: list,
                          ping: bool,
                          attacks_limit: int) -> str:
        if message.chat.type == ChatType.PRIVATE:
            row = await self.req_connection.fetchrow('''
                SELECT chat_id
                FROM master.clan_chat
                WHERE clan_tag = $1 AND is_chat_main
            ''', self.clan_tag)
            chat_id = row['chat_id']
        else:
            chat_id = message.chat.id
        rows = await self.req_connection.fetch('''
            SELECT player_tag, user_id
            FROM
                master.player_tg_user
                JOIN master.player USING (clan_tag, player_tag)
                JOIN master.tg_user USING (chat_id, user_id)
            WHERE player.clan_tag = $1 AND tg_user.chat_id = $2
        ''', self.clan_tag, chat_id)
        members_by_tg_user_to_mention = {}
        unlinked_members = []
        tg_users_by_player = {player_tag: [] for player_tag in [row['player_tag'] for row in rows]}
        for row in rows:
            tg_users_by_player[row['player_tag']].append(row['user_id'])
        for member in members:
            if member.attacks_spent < attacks_limit:
                for tg_user in tg_users_by_player.get(member.player_tag, []):
                    if members_by_tg_user_to_mention.get(tg_user) is None:
                        members_by_tg_user_to_mention[tg_user] = []
                    members_by_tg_user_to_mention[tg_user].append(member)
                if tg_users_by_player.get(member.player_tag) is None:
                    unlinked_members.append(member)
        text = ''
        for tg_user, players in members_by_tg_user_to_mention.items():
            if ping:
                text += f'<a href="tg://user?id={tg_user}">{self.load_full_name(chat_id, tg_user)}</a> — '
            else:
                text += f'{self.load_full_name(chat_id, tg_user)} — '
            text += (', '.join([f'{self.of.to_html(self.load_name(player.player_tag))}: '
                                f'{player.attacks_spent} / {player.attacks_limit}'
                                for player in players]) +
                     '\n')
        if len(members_by_tg_user_to_mention) > 0:
            text += '\n'
        for player in unlinked_members:
            text += (f'{self.of.to_html(self.load_name(player.player_tag))}: '
                     f'{player.attacks_spent} / {player.attacks_limit}\n')
        if len(members_by_tg_user_to_mention) + len(unlinked_members) == 0:
            text += f'Список пуст'
        return text

    @staticmethod
    def attacks_count_to_text(attacks_count: int) -> str:
        if attacks_count == 1:
            return '1 атака'
        if attacks_count == 2:
            return '2 атаки'
        if attacks_count == 3:
            return '3 атаки'
        if attacks_count == 4:
            return '4 атаки'
        if 5 <= attacks_count <= 20:
            return f'{attacks_count} атак'
        else:
            return f'кол-во атак: {attacks_count}'

    @staticmethod
    def avg(lst: list) -> float:
        return round(sum(lst) / len(lst), 2)
