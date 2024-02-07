import asyncio
import json
from datetime import datetime
from typing import Optional, Union, Tuple

import asyncpg
from aiogram.types import User

from async_client import AsyncClient
from bot.config import config
from output_formatter import OutputFormatter


class DatabaseManager:
    def __init__(self):
        self.api_client = AsyncClient(email=config.clash_of_clans_api_login.get_secret_value(),
                                      password=config.clash_of_clans_api_password.get_secret_value(),
                                      key_name=config.clash_of_clans_api_key_name.get_secret_value(),
                                      key_description=config.clash_of_clans_api_key_description.get_secret_value())
        self.of = OutputFormatter()
        self.clan_tag = config.clash_of_clans_clan_tag.get_secret_value()

        self.cron_connection = None
        self.req_connection = None

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

    async def frequent_jobs(self):
        retrieved_clan_members = (await self.api_client.get_clan_members(clan_tag=self.clan_tag))['items']
        if retrieved_clan_members is not None:
            dumped_clan_member_tag_list = await self.dump_clan_members()
            retrieved_clan_member_tag_list = [clan_member['tag']
                                              for clan_member
                                              in retrieved_clan_members]
            missing_clan_member_tag_list = [clan_member_tag
                                            for clan_member_tag
                                            in dumped_clan_member_tag_list
                                            if clan_member_tag not in retrieved_clan_member_tag_list]
            new_clan_member_tag_list = [clan_member_tag
                                        for clan_member_tag
                                        in retrieved_clan_member_tag_list
                                        if clan_member_tag not in dumped_clan_member_tag_list]
            if len(missing_clan_member_tag_list) > 0:
                pass
            if len(new_clan_member_tag_list) > 0:
                await self.update_clan_members_and_contributions()

        await self.update_clan_war()

        await self.update_raid_weekends()

        await self.update_clan_war_league()

        await self.update_clan_war_league_wars()

        await self.update_names()

    async def infrequent_jobs(self):
        await self.frequent_jobs()

        await self.update_clan_members_and_contributions()

    async def write_clan_war_to_db(self, clan_war_data: Optional[dict]) -> None:
        if clan_war_data is not None and clan_war_data.get('state') in ['preparation', 'inWar', 'warEnded']:
            await self.cron_connection.execute('''
                INSERT INTO public.clan_war
                VALUES ($1, $2)
                ON CONFLICT (start_time)
                DO UPDATE
                SET data = $2
            ''', datetime.strptime(clan_war_data['startTime'], '%Y%m%dT%H%M%S.%fZ'),
                 json.dumps(clan_war_data))

    async def write_raid_weekends_to_db(self, raid_weekends_data: Optional[dict]) -> None:
        if raid_weekends_data is not None:
            await self.cron_connection.executemany('''
                INSERT INTO public.raid_weekend
                VALUES ($1, $2)
                ON CONFLICT (start_time)
                DO UPDATE
                SET data = $2
            ''', [(datetime.strptime(item['startTime'], '%Y%m%dT%H%M%S.%fZ'), json.dumps(item))
                  for item in raid_weekends_data['items']])

    async def write_clan_war_league_to_db(self, clan_war_league_data: Optional[dict]) -> None:
        if clan_war_league_data is not None:
            await self.cron_connection.execute('''
                INSERT INTO public.clan_war_league
                VALUES ($1, $2)
                ON CONFLICT (season)
                DO UPDATE
                SET data = $2
            ''', clan_war_league_data['season'], json.dumps(clan_war_league_data))

    async def calculate_clan_war_league_war_day(self, dumped_war_tag: str) -> Optional[int]:
        record = await self.cron_connection.fetchrow('''
            SELECT data->'rounds' AS rounds
            FROM public.clan_war_league
            WHERE season = (SELECT MAX(season) FROM public.clan_war_league)
        ''')
        clan_war_league_rounds = json.loads(record['rounds'])
        for day, clan_war_league_round in enumerate(clan_war_league_rounds):
            for war_tag in clan_war_league_round['warTags']:
                if war_tag == dumped_war_tag:
                    return day
        return None

    async def write_clan_war_league_wars_to_db(self, war_tag_list: list[str],
                                               season: str,
                                               clan_war_league_war_data_list: list[Optional[dict]]) -> None:
        war_tag_column = war_tag_list
        season_column = [season] * len(war_tag_list)
        round_number_column = [await self.calculate_clan_war_league_war_day(war_tag)
                               for war_tag
                               in war_tag_list]
        data_columnn = map(json.dumps, clan_war_league_war_data_list)
        retrieved_columns = list(zip(war_tag_column, season_column, round_number_column, data_columnn))
        updated_columns = [(war_tag, season, round_number, data)
                           for war_tag, season, round_number, data in retrieved_columns
                           if (data is not None) and (war_tag != '#0')]
        await self.cron_connection.executemany('''
            INSERT INTO public.clan_war_league_war
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (war_tag) DO
            UPDATE SET data = $4          
        ''', updated_columns)

    async def insert_user_to_db(self, user: User) -> None:
        await self.req_connection.execute('''
            INSERT INTO public.telegram_user
            VALUES ($1, $2, $3, $4, TRUE, CURRENT_TIMESTAMP(0), CURRENT_TIMESTAMP(0))
        ''', user.id, user.username, user.first_name, user.full_name)

    async def update_user_in_db(self, user: User) -> None:
        await self.req_connection.execute('''
            UPDATE public.telegram_user
            SET (username, first_name, last_name, in_chat, last_seen) =
                ($2, $3, $4, TRUE, CURRENT_TIMESTAMP(0))
            WHERE id = $1
        ''', user.id, user.username, user.first_name, user.full_name)

    async def remove_user_from_db(self, user: User) -> None:
        await self.req_connection.execute('''
            UPDATE public.telegram_user
            SET (username, first_name, last_name, in_chat, last_seen) =
                ($2, $3, $4, FALSE, CURRENT_TIMESTAMP(0))
            WHERE id = $1
        ''', user.id, user.username, user.first_name, user.full_name)

    async def write_clan_members_to_db(self, clan_member_data_list: list[Optional[dict]]) -> None:
        clan_member_inserted_data = []
        for player in clan_member_data_list:
            member_heroes = player['heroes']
            barbarian_king_level = 0
            archer_queen_level = 0
            grand_warden_level = 0
            royal_champion_level = 0
            for member_hero in member_heroes:
                if member_hero['name'] == 'Barbarian King':
                    barbarian_king_level = member_hero['level']
                elif member_hero['name'] == 'Archer Queen':
                    archer_queen_level = member_hero['level']
                elif member_hero['name'] == 'Grand Warden':
                    grand_warden_level = member_hero['level']
                elif member_hero['name'] == 'Royal Champion':
                    royal_champion_level = member_hero['level']
            clan_member_inserted_data.append((player['tag'], player['name'],
                                              player['townHallLevel'], player['trophies'],
                                              barbarian_king_level, archer_queen_level,
                                              grand_warden_level, royal_champion_level,
                                              player['builderHallLevel'], player['builderBaseTrophies'],
                                              player['role'], True, player['donations'], player['donationsReceived'],
                                              player['clanCapitalContributions']))

        await self.cron_connection.execute('''
            UPDATE public.clash_of_clans_account
            SET in_clan = FALSE
        ''')

        await self.cron_connection.executemany('''
            INSERT INTO public.clash_of_clans_account 
                (tag, name, town_hall, trophies, barbarian_king, archer_queen, 
                grand_warden, royal_champion, builder_hall, builder_base_trophies, role, in_clan, 
                donations_given, donations_received, first_seen, last_seen, 
                capital_contributions, participates_in_clan_wars)
            VALUES
                ($1, $2, $3, $4, $5, $6,
                $7, $8, $9, $10, $11, $12,
                $13, $14, CURRENT_TIMESTAMP(0), CURRENT_TIMESTAMP(0), 
                $15, FALSE)
            ON CONFLICT (tag) DO UPDATE SET
                (name, town_hall, trophies, barbarian_king, archer_queen,
                grand_warden, royal_champion, builder_hall, builder_base_trophies, role,
                in_clan, donations_given, donations_received, last_seen, capital_contributions) =
                ($2, $3, $4, $5, $6,
                $7, $8, $9, $10, $11,
                $12, $13, $14, CURRENT_TIMESTAMP(0), $15)
        ''', clan_member_inserted_data)

    async def write_contributions_to_db(self, old_contributions: dict, new_contributions: dict):
        for tag in set.intersection(set(old_contributions.keys()), set(new_contributions.keys())):
            old_contribution = old_contributions[tag]
            new_contribution = new_contributions[tag]
            if new_contribution > old_contribution:
                await self.cron_connection.execute('''
                    INSERT INTO public.clan_capital_contribution
                    VALUES ($1, $2, CURRENT_TIMESTAMP(0))
                ''', tag, new_contribution - old_contribution)

    async def clan_war_start_time(self, only_last: bool) -> Union[datetime, list[datetime]]:
        if only_last:
            query = await self.cron_connection.fetch('''
                SELECT start_time
                FROM public.clan_war
                ORDER BY start_time DESC
                LIMIT 1
            ''')
            record = query[0]
            return record['start_time']
        else:
            query = await self.cron_connection.fetch('''
                SELECT start_time
                FROM public.clan_war
                ORDER BY start_time DESC
            ''')
            return [record['start_time'] for record in query]

    async def raid_weekend_start_time(self, only_last: bool) -> Union[datetime, list[datetime]]:
        if only_last:
            query = await self.cron_connection.fetch('''
                SELECT start_time
                FROM public.raid_weekend
                ORDER BY start_time DESC
                LIMIT 1
            ''')
            record = query[0]
            return record['start_time']
        else:
            query = await self.cron_connection.fetch('''
                SELECT start_time
                FROM public.raid_weekend
                ORDER BY start_time DESC
            ''')
            return [record['start_time'] for record in query]

    async def clan_war_league_season(self, only_last: bool) -> Union[str, list[str]]:
        if only_last:
            query = await self.cron_connection.fetch('''
                SELECT season
                FROM public.clan_war_league
                ORDER BY season DESC
                LIMIT 1
            ''')
            record = query[0]
            return record['season']
        else:
            query = await self.cron_connection.fetch('''
                SELECT season
                FROM public.clan_war_league
                ORDER BY season DESC
            ''')
            return [record['season'] for record in query]

    async def clan_war_league_war_tag_list_to_retrieve(self) -> list[str]:
        query = await self.cron_connection.fetch('''
            SELECT war_tag
            FROM public.clan_war_league_war
            WHERE data->>'state' != 'warEnded'
        ''')
        return [record['war_tag'] for record in query]

    async def clan_war_league_war_tag(self) -> list[str]:
        last_clan_war_league_season = await self.clan_war_league_season(only_last=True)
        last_clan_war_league = await self.get_clan_war_league(clan_war_league_season=last_clan_war_league_season)
        war_tag_list = [war_tag
                        for clan_war_league_round in last_clan_war_league['rounds']
                        for war_tag in clan_war_league_round['warTags']]
        return war_tag_list

    async def get_clan_war(self, clan_war_start_time: datetime) -> dict:
        query = await self.cron_connection.fetch('''
            SELECT data
            FROM public.clan_war
            WHERE start_time = $1
        ''', clan_war_start_time)
        record = query[0]
        return json.loads(record['data'])

    async def get_raid_weekend(self, raid_weekend_start_time: datetime) -> dict:
        query = await self.cron_connection.fetch('''
            SELECT data
            FROM public.raid_weekend
            WHERE start_time = $1
        ''', raid_weekend_start_time)
        record = query[0]
        return json.loads(record['data'])

    async def get_clan_war_league(self, clan_war_league_season: str) -> dict:
        query = await self.cron_connection.fetch('''
            SELECT data
            FROM public.clan_war_league
            WHERE season = $1
        ''', clan_war_league_season)
        record = query[0]
        return json.loads(record['data'])

    async def get_clan_war_league_clan_own_war_list(self, season: str,
                                                    only_last: bool) -> Union[list[dict], Tuple[int, dict]]:
        query = await self.cron_connection.fetch('''
            SELECT data
            FROM public.clan_war_league_war
            WHERE season = $1 AND $2 IN (data->'clan'->>'tag', data->'opponent'->>'tag')
            ORDER BY round_number
        ''', season, self.clan_tag)
        clan_war_league_war_list = []
        for record in query:
            clan_war_league_war = json.loads(record['data'])
            if clan_war_league_war['opponent']['tag'] == self.clan_tag:
                clan_war_league_war['clan'], clan_war_league_war['opponent'] = \
                    clan_war_league_war['opponent'], clan_war_league_war['clan']
            clan_war_league_war_list.append(clan_war_league_war)
        if not only_last:
            return clan_war_league_war_list
        else:
            enumerated_reversed_clan_war_league_war_list = (list(enumerate(clan_war_league_war_list)))[::-1]
            for i, clan_war_league_war in enumerated_reversed_clan_war_league_war_list:
                if clan_war_league_war['state'] == 'inWar':
                    return i, clan_war_league_war
            for i, clan_war_league_war in enumerated_reversed_clan_war_league_war_list:
                if clan_war_league_war['state'] == 'preparation':
                    return i, clan_war_league_war
            for i, clan_war_league_war in enumerated_reversed_clan_war_league_war_list:
                if clan_war_league_war['state'] == 'warEnded':
                    return i, clan_war_league_war
            for i, clan_war_league_war in enumerate(clan_war_league_war_list):
                return i, clan_war_league_war

    async def get_cwl_round_amount(self, season: str) -> int:
        record = await self.cron_connection.fetchrow('''
            SELECT COUNT(*) as amount
            FROM public.clan_war_league_war
            WHERE season = $1 AND $2 IN (data->'clan'->>'tag', data->'opponent'->>'tag')
        ''', season, self.clan_tag)
        return record['amount']

    async def dump_contributions(self):
        query = await self.cron_connection.fetch('''
            SELECT tag, capital_contributions
            FROM public.clash_of_clans_account
        ''')
        return {record['tag']: record['capital_contributions'] for record in query}

    async def dump_clan_members(self):
        query = await self.cron_connection.fetch('''
            SELECT tag
            FROM public.clash_of_clans_account
            WHERE in_clan
        ''')
        return [record['tag'] for record in query]

    def get_name_and_tag(self, player_tag: str):
        return self.name_and_tag.get(player_tag)

    def get_name(self, player_tag: str):
        return self.name.get(player_tag)

    def get_full_name_and_username(self, user_id: int):
        return self.full_name_and_username.get(user_id)

    def get_full_name(self, user_id: int):
        return self.full_name.get(user_id)

    async def get_names(self):
        query = await self.cron_connection.fetch('''
            SELECT tag, name
            FROM public.clash_of_clans_account
        ''')
        name = {record['tag']: record['name'] for record in query}
        name_and_tag = {record['tag']: f'{record['name']} ({record['tag']})' for record in query}
        query = await self.cron_connection.fetch('''
            SELECT id, username, first_name, last_name
            FROM public.telegram_user
        ''')
        full_name = {record['id']: record['first_name'] + (f' {record['last_name']}' if record['last_name'] else '')
                     for record in query}
        full_name_and_username = {record['id']: (f'{record['first_name']}'
                                                 f'{record['last_name'] or ''}'
                                                 f'{(' (@' + record['username'] + ')') if record['username'] else ''}')
                                  for record in query}
        return name, name_and_tag, full_name, full_name_and_username

    async def get_chat_member_id_list(self):
        query = await self.cron_connection.fetch('''
            SELECT id
            FROM public.telegram_user
            WHERE in_chat
        ''')
        return [record['id'] for record in query]

    async def update_clan_war(self):
        retrieved_clan_war = await self.api_client.get_clan_current_war(clan_tag=self.clan_tag)
        await self.write_clan_war_to_db(clan_war_data=retrieved_clan_war)

    async def update_clan_war_league(self):
        retrieved_clan_war_league = await self.api_client.get_clan_war_league_group(clan_tag=self.clan_tag)
        await self.write_clan_war_league_to_db(clan_war_league_data=retrieved_clan_war_league)

    async def update_raid_weekends(self):
        retrieved_raid_weekends = await self.api_client.get_clan_capital_raid_seasons(clan_tag=self.clan_tag)
        await self.write_raid_weekends_to_db(raid_weekends_data=retrieved_raid_weekends)

    async def update_clan_war_league_wars(self):
        clan_war_league_war_task_list = [self.api_client.get_clan_war_league_war(war_tag=war_tag)
                                         for war_tag
                                         in await self.clan_war_league_war_tag_list_to_retrieve()]
        retrieved_clan_war_league_war_list = list(await asyncio.gather(*clan_war_league_war_task_list))
        await self.write_clan_war_league_wars_to_db(await self.clan_war_league_war_tag_list_to_retrieve(),
                                                    await self.clan_war_league_season(only_last=True),
                                                    retrieved_clan_war_league_war_list)

    async def update_clan_members_and_contributions(self):
        clan_member_task_list = [self.api_client.get_player(player_tag=clan_member['tag'])
                                 for clan_member
                                 in (await self.api_client.get_clan_members(clan_tag=self.clan_tag))['items']]
        retrieved_clan_members = list(await asyncio.gather(*clan_member_task_list))
        old_contributions = await self.dump_contributions()
        await self.write_clan_members_to_db(clan_member_data_list=retrieved_clan_members)
        new_contributions = await self.dump_contributions()
        await self.write_contributions_to_db(old_contributions, new_contributions)

    async def update_names(self):
        self.name, self.name_and_tag, self.full_name, self.full_name_and_username = await self.get_names()

    async def register_message(self, chat_id: int, message_id: int, user_id: int):
        await self.req_connection.execute('''
            INSERT INTO public.message_user
            VALUES ($1, $2, $3)
        ''', chat_id, message_id, user_id)

    async def check_message(self, chat_id: int, message_id: int, user_id: int):
        query = await self.req_connection.fetch('''
            SELECT user_id
            FROM public.message_user
            WHERE chat_id = $1 AND message_id = $2
        ''', chat_id, message_id)
        if len(query) == 0:
            return False
        else:
            record = query[0]
            return record['user_id'] == user_id

    async def is_admin(self, user_id: int):
        query = await self.req_connection.fetch('''
            SELECT role
            FROM
                public.tg_user_coc_account
                JOIN public.clash_of_clans_account USING (tag)
            WHERE id = $1
        ''', user_id)
        user_roles = [record['role'] for record in query]
        return ('coLeader' in user_roles) or ('leader' in user_roles)

    def get_map_positions(self, war_members_data: dict):
        map_position = {}
        for member in war_members_data:
            map_position[member['tag']] = member['mapPosition']
        map_position = {item[0]: i + 1
                        for i, item
                        in enumerate(sorted(map_position.items(), key=lambda item: item[1]))}
        return map_position
