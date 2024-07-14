from datetime import datetime, timedelta, UTC
from enum import auto, IntEnum
from typing import Optional

from asyncpg import Record

from config import config


class Event(IntEnum):
    CW = auto()
    RW = auto()
    CWL = auto()
    CWLW = auto()
    CG = auto()
    TR = auto()
    LR = auto()
    SE = auto()


class OutputFormatter:
    def __init__(self, utc_to_local_hours: Optional[timedelta] = timedelta(hours=3)):
        self.utc_to_local_hours = utc_to_local_hours

    @staticmethod
    def to_html(text: str) -> str:
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def to_datetime(datetime_data: str) -> datetime:
        return datetime.strptime(datetime_data, '%Y%m%dT%H%M%S.%fZ')

    @staticmethod
    def from_datetime(dt: datetime) -> str:
        return datetime.strftime(dt, '%Y%m%dT%H%M%S.%fZ')

    @staticmethod
    def full_dedent(text: str) -> str:
        return '\n'.join(map(str.lstrip, text.split('\n')))

    @staticmethod
    def season(season_data: str) -> str:
        month_in_russian = {
            '01': 'январь',
            '02': 'февраль',
            '03': 'март',
            '04': 'апрель',
            '05': 'май',
            '06': 'июнь',
            '07': 'июль',
            '08': 'август',
            '09': 'сентябрь',
            '10': 'октябрь',
            '11': 'ноябрь',
            '12': 'декабрь'
        }
        year, month = season_data.split('-')
        return f'{month_in_russian[month]} {year}'

    @staticmethod
    def role(role_data: str) -> str:
        role_in_russian = {
            'leader': 'глава',
            'coLeader': 'соруководитель',
            'admin': 'старейшина',
            'member': 'участник'
        }
        return role_in_russian[role_data]

    @staticmethod
    def district(district_data: str) -> str:
        district_in_russian = {
            'Capital Peak': 'Столичный пик',
            'Barbarian Camp': 'Лагерь варваров',
            'Wizard Valley': 'Долина колдунов',
            'Balloon Lagoon': 'Лагуна шаров',
            'Builder\'s Workshop': 'Мастерская строителя',
            'Dragon Cliffs': 'Драконьи утесы',
            'Golem Quarry': 'Карьер големов',
            'Skeleton Park': 'Парк скелетов',
            'Goblin Mines': 'Гоблинские шахты'
        }
        return district_in_russian[district_data]

    @staticmethod
    def get_capital_gold_emoji() -> str:
        return f'<tg-emoji emoji-id="{config.capital_gold_emoji_id.get_secret_value()}">🟡</tg-emoji>'

    @staticmethod
    def get_raid_medal_emoji() -> str:
        return f'<tg-emoji emoji-id="{config.raid_medal_emoji_id.get_secret_value()}">⚪</tg-emoji>'

    @staticmethod
    def get_town_hall_emoji(town_hall_level: int) -> str:
        return (
            f'<tg-emoji emoji-id="{config.town_hall_emoji_ids[town_hall_level - 1].get_secret_value()}">🛖</tg-emoji>'
        )

    @staticmethod
    def get_builder_hall_emoji(builder_hall_level: int) -> str:
        return (
            f'<tg-emoji emoji-id="{config.builder_hall_emoji_ids[builder_hall_level - 1].get_secret_value()}">'
            f'🛖</tg-emoji>'
        )

    @staticmethod
    def get_barbarian_king_emoji() -> str:
        return (
            f'<tg-emoji emoji-id="{config.home_village_hero_emoji_ids[0].get_secret_value()}">🤴</tg-emoji>'
        )

    @staticmethod
    def get_archer_queen_emoji() -> str:
        return (
            f'<tg-emoji emoji-id="{config.home_village_hero_emoji_ids[1].get_secret_value()}">👸</tg-emoji>'
        )

    @staticmethod
    def get_grand_warden_emoji() -> str:
        return (
            f'<tg-emoji emoji-id="{config.home_village_hero_emoji_ids[2].get_secret_value()}">👴</tg-emoji>'
        )

    @staticmethod
    def get_royal_champion_emoji() -> str:
        return (
            f'<tg-emoji emoji-id="{config.home_village_hero_emoji_ids[3].get_secret_value()}">🙍‍♀️</tg-emoji>'
        )

    @staticmethod
    def get_player_info_with_emoji(
            town_hall_level: int,
            barbarian_king_level: Optional[int] = None,
            archer_queen_level: Optional[int] = None,
            grand_warden_level: Optional[int] = None,
            royal_champion_level: Optional[int] = None
    ) -> str:
        text = f'🛖{town_hall_level}'
        if (barbarian_king_level or 0) > 0:
            text += f' 🤴{barbarian_king_level}'
        if (archer_queen_level or 0) > 0:
            text += f' 👸{archer_queen_level}'
        if (grand_warden_level or 0) > 0:
            text += f' 👴{grand_warden_level}'
        if (royal_champion_level or 0) > 0:
            text += f' 🙍‍♀️{royal_champion_level}'
        return text

    @staticmethod
    def get_player_info_for_callback_text(
            town_hall_level: int,
            barbarian_king_level: Optional[int] = None,
            archer_queen_level: Optional[int] = None,
            grand_warden_level: Optional[int] = None,
            royal_champion_level: Optional[int] = None
    ) -> str:
        text = f'🛖{town_hall_level}'
        hero_levels = [
            (barbarian_king_level or 0),
            (archer_queen_level or 0),
            (grand_warden_level or 0),
            (royal_champion_level or 0)
        ]
        if any(hero_level > 0 for hero_level in hero_levels):
            text += f' 👑 {', '.join(str(hero_level or '–') for hero_level in hero_levels)}'
        return text

    def get_player_info_with_custom_emoji(
            self,
            town_hall_level: int,
            barbarian_king_level: Optional[int] = None,
            archer_queen_level: Optional[int] = None,
            grand_warden_level: Optional[int] = None,
            royal_champion_level: Optional[int] = None
    ) -> str:
        text = f'{self.get_town_hall_emoji(town_hall_level)}{town_hall_level}'
        if (barbarian_king_level or 0) > 0:
            text += f' {self.get_barbarian_king_emoji()}{barbarian_king_level}'
        if (archer_queen_level or 0) > 0:
            text += f' {self.get_archer_queen_emoji()}{archer_queen_level}'
        if (grand_warden_level or 0) > 0:
            text += f' {self.get_grand_warden_emoji()}{grand_warden_level}'
        if (royal_champion_level or 0) > 0:
            text += f' {self.get_royal_champion_emoji()}{royal_champion_level}'
        return text

    def short_datetime(self, datetime_data: datetime) -> str:
        dt_now = datetime.now(UTC) + self.utc_to_local_hours
        dt = datetime_data + self.utc_to_local_hours
        month_in_russian_genitive = {
            1: 'января',
            2: 'февраля',
            3: 'марта',
            4: 'апреля',
            5: 'мая',
            6: 'июня',
            7: 'июля',
            8: 'августа',
            9: 'сентября',
            10: 'октября',
            11: 'ноября',
            12: 'декабря'
        }
        return (
            f'{dt.day} {month_in_russian_genitive[dt.month]}'
            f'{'' if dt_now.year == dt.year else f' {dt.year}'}'
            f' в {dt.hour}:{str(dt.minute).zfill(2)}'
        )

    def shortest_datetime(self, datetime_data: datetime) -> str:
        dt = datetime_data + self.utc_to_local_hours
        dt_now = datetime.now(UTC) + self.utc_to_local_hours
        month_in_russian_genitive = {
            1: 'января',
            2: 'февраля',
            3: 'марта',
            4: 'апреля',
            5: 'мая',
            6: 'июня',
            7: 'июля',
            8: 'августа',
            9: 'сентября',
            10: 'октября',
            11: 'ноября',
            12: 'декабря'
        }
        if (dt.year, dt.month, dt.day) == (dt_now.year, dt_now.month, dt_now.day):
            return f'сегодня в {dt.hour}:{str(dt.minute).zfill(2)}'
        else:
            return f'{dt.day} {month_in_russian_genitive[dt.month]} в {dt.hour}:{str(dt.minute).zfill(2)}'

    @staticmethod
    def get_days_in_russian(days: int) -> str:
        if 0 <= days < 20:
            days_in_russian = [
                '', '1 день', '2 дня', '3 дня', '4 дня',
                '5 дней', '6 дней', '7 дней', '8 дней', '9 дней',
                '10 дней', '11 дней', '12 дней', '13 дней', '14 дней',
                '15 дней', '16 дней', '17 дней', '18 дней', '19 дней'
            ]
            return days_in_russian[days]
        elif 20 <= days < 100:
            word_in_russian = [
                'дней', 'день', 'дня', 'дня', 'дня',
                'дней', 'дней', 'дней', 'дней', 'дней'
            ]
            return f'{days} {word_in_russian[days % 10]}'
        else:
            if days % 100 == 0:
                return f'{days} дней'
            else:
                return f'{days} {OutputFormatter.get_days_in_russian(days % 100).split(' ')[-1]}'

    @staticmethod
    def get_hours_in_russian(hours: int) -> str:
        hours_in_russian = [
            '', '1 час', '2 часа', '3 часа', '4 часа',
            '5 часов', '6 часов', '7 часов', '8 часов', '9 часов',
            '10 часов', '11 часов', '12 часов', '13 часов', '14 часов',
            '15 часов', '16 часов', '17 часов', '18 часов', '19 часов',
            '20 часов', '21 час', '22 часа', '23 часа'
        ]
        return hours_in_russian[hours]

    @staticmethod
    def get_minutes_in_russian(minutes: int) -> str:
        minutes_in_russian = [
            '', '1 минуту', '2 минуты', '3 минуты', '4 минуты',
            '5 минут', '6 минут', '7 минут', '8 минут', '9 минут',
            '10 минут', '11 минут', '12 минут', '13 минут', '14 минут',
            '15 минут', '16 минут', '17 минут', '18 минут', '19 минут',
            '20 минут', '21 минуту', '22 минуты', '23 минуты', '24 минуты',
            '25 минут', '26 минут', '27 минут', '28 минут', '29 минут',
            '30 минут', '31 минуту', '32 минуты', '33 минуты', '34 минуты',
            '35 минут', '36 минут', '37 минут', '38 минут', '39 минут',
            '40 минут', '41 минуту', '42 минуты', '43 минуты', '44 минуты',
            '45 минут', '46 минут', '47 минут', '48 минут', '49 минут',
            '50 минут', '51 минуту', '52 минуты', '53 минуты', '54 минуты',
            '55 минут', '56 минут', '57 минут', '58 минут', '59 минут'
        ]
        return minutes_in_russian[minutes]

    @staticmethod
    def get_seconds_in_russian(seconds: int) -> str:
        seconds_in_russian = [
            '', '1 секунду', '2 секунды', '3 секунды', '4 секунды',
            '5 секунд', '6 секунд', '7 секунд', '8 секунд', '9 секунд',
            '10 секунд', '11 секунд', '12 секунд', '13 секунд', '14 секунд',
            '15 секунд', '16 секунд', '17 секунд', '18 секунд', '19 секунд',
            '20 секунд', '21 секунду', '22 секунды', '23 секунды', '24 секунды',
            '25 секунд', '26 секунд', '27 секунд', '28 секунд', '29 секунд',
            '30 секунд', '31 секунду', '32 секунды', '33 секунды', '34 секунды',
            '35 секунд', '36 секунд', '37 секунд', '38 секунд', '39 секунд',
            '40 секунд', '41 секунду', '42 секунды', '43 секунды', '44 секунды',
            '45 секунд', '46 секунд', '47 секунд', '48 секунд', '49 секунд',
            '50 секунд', '51 секунду', '52 секунды', '53 секунды', '54 секунды',
            '55 секунд', '56 секунд', '57 секунд', '58 секунд', '59 секунд'
        ]
        return seconds_in_russian[seconds]

    def event_datetime(
            self,
            event: Event,
            start_datetime_data: Optional[str],
            end_datetime_data: Optional[str],
            show_datetime: bool,
            dt_event: Optional[datetime] = None
    ) -> str:
        dt_now = datetime.now(UTC).replace(tzinfo=None) + self.utc_to_local_hours
        if not dt_event:
            dt_event_start = self.to_datetime(start_datetime_data) + self.utc_to_local_hours
            dt_event_end = self.to_datetime(end_datetime_data) + self.utc_to_local_hours
            if dt_now < dt_event_start:
                dt_event = dt_event_start
            else:
                dt_event = dt_event_end
        else:
            dt_event_start = None
            dt_event += self.utc_to_local_hours
        dt_diff = abs(dt_event - dt_now)
        days = dt_diff.days
        hours = dt_diff.seconds // 3600
        minutes = (dt_diff.seconds % 3600) // 60
        seconds = dt_diff.seconds % 60

        event_name = {
            Event.CW: 'КВ',
            Event.RW: 'Рейды',
            Event.CWL: 'ЛВК',
            Event.CWLW: 'Война',
            Event.CG: 'ИК'
        }

        event_name_genitive = {
            Event.CW: 'КВ',
            Event.RW: 'рейдов',
            Event.CWL: 'ЛВК',
            Event.CWLW: 'войны',
            Event.CG: 'ИК'
        }

        event_verbs = {
            Event.CW: ('начнётся', 'закончится', 'закончилась'),
            Event.RW: ('начнутся', 'закончатся', 'закончились'),
            Event.CWL: ('начнётся', 'закончится', 'закончилась'),
            Event.CWLW: ('начнётся', 'закончится', 'закончилась'),
            Event.CG: ('начнутся', 'закончатся', 'закончились')
        }

        event_action_name = {
            Event.TR: 'Обновление магазина торговца',
            Event.LR: 'Сброс лиги',
            Event.SE: 'Конец сезона'
        }

        event_action = {
            Event.TR: 'Магазин торговца обновится',
            Event.LR: 'Лига сбросится',
            Event.SE: 'Сезон закончится'
        }

        if days != 0:
            dt_diff_str = self.get_days_in_russian(days)
            if hours != 0:
                dt_diff_str += ' и ' + self.get_hours_in_russian(hours)
        elif hours != 0:
            dt_diff_str = self.get_hours_in_russian(hours)
            if minutes != 0:
                dt_diff_str += ' и ' + self.get_minutes_in_russian(minutes)
        elif minutes != 0:
            dt_diff_str = self.get_minutes_in_russian(minutes)
            if minutes < 10 and seconds != 0:
                dt_diff_str += ' и ' + self.get_seconds_in_russian(seconds)
        elif seconds != 0:
            dt_diff_str = self.get_seconds_in_russian(seconds)
        else:
            dt_diff_str = ''

        output_string = ''
        if dt_event_start:
            if dt_now < dt_event_start:
                if show_datetime:
                    output_string += (
                        'Начало ' + event_name_genitive[event] + ': '
                        + self.short_datetime(dt_event - self.utc_to_local_hours) + ','
                    )
                else:
                    output_string += event_name[event] + ' ' + event_verbs[event][0]
            else:
                if show_datetime:
                    output_string += (
                        'Конец ' + event_name_genitive[event] + ': ' +
                        self.short_datetime(dt_event - self.utc_to_local_hours) + ','
                    )
                else:
                    output_string += (
                        event_name[event] + ' ' +
                        (event_verbs[event][1 if dt_now < dt_event and dt_diff_str != '' else 2])
                    )
        else:
            if show_datetime:
                output_string += (
                    event_action_name[event] + ': ' +
                    self.short_datetime(dt_event - self.utc_to_local_hours) + ','
                )
            else:
                output_string += event_action[event]
        if dt_diff_str == '':
            output_string += ' только что'
        elif dt_now < dt_event:
            output_string += f' через {dt_diff_str}'
        else:
            output_string += f' {dt_diff_str} назад'
        return output_string

    def get_event_datetime(self, dt_start: datetime, dt_end: datetime) -> datetime:
        dt_now = datetime.now(UTC).replace(tzinfo=None) + self.utc_to_local_hours
        if dt_now < dt_start + self.utc_to_local_hours:
            return dt_start
        else:
            return dt_end

    def event_remaining_or_passed(self, dt_data: str) -> str:
        dt_now = datetime.now(UTC).replace(tzinfo=None) + self.utc_to_local_hours
        dt_event = self.to_datetime(dt_data) + self.utc_to_local_hours

        dt_diff = abs(dt_event - dt_now)
        days = dt_diff.days
        hours = dt_diff.seconds // 3600
        minutes = (dt_diff.seconds % 3600) // 60
        seconds = dt_diff.seconds % 60

        if days != 0:
            dt_diff_str = self.get_days_in_russian(days)
        elif hours != 0:
            dt_diff_str = self.get_hours_in_russian(hours)
        elif minutes != 0:
            dt_diff_str = self.get_minutes_in_russian(minutes)
        elif seconds != 0:
            dt_diff_str = self.get_seconds_in_russian(seconds)
        else:
            dt_diff_str = ''

        if dt_now < dt_event:
            return f'через {dt_diff_str}'
        elif dt_now > dt_event:
            return f'{dt_diff_str} назад'
        else:
            return 'только что'

    @staticmethod
    def state(event: Optional[dict]) -> Optional[str]:
        return event['state'] if event else None

    @staticmethod
    def war_result(war: dict) -> str:
        clan_result = (war['clan']['stars'], war['clan']['destructionPercentage'])
        opponent_result = (war['opponent']['stars'], war['opponent']['destructionPercentage'])
        if clan_result > opponent_result:
            return f'🎉 Победа!\n'
        elif clan_result < opponent_result:
            return f'😢 Поражение\n'
        else:
            return f'⚖️ Ничья\n'

    def war_log(self, clan_war_log: dict) -> str:
        text = f'Ход войны противника:\n'
        only_clan_war_log = [
            prev_clan_war
            for prev_clan_war in clan_war_log['items']
            if prev_clan_war.get('attacksPerMember', 0) == 2
        ]
        for prev_clan_war in only_clan_war_log[:10]:
            clan_result = (prev_clan_war['clan']['stars'], prev_clan_war['clan']['destructionPercentage'])
            opponent_result = (prev_clan_war['opponent']['stars'], prev_clan_war['opponent']['destructionPercentage'])
            if clan_result > opponent_result:
                text += '✅ '
            elif clan_result < opponent_result:
                text += '❌ '
            else:
                text += '🟰 '
            text += (
                f'{prev_clan_war['clan']['stars']} ⭐ vs {prev_clan_war['opponent']['stars']} ⭐, '
                f'{prev_clan_war['teamSize']} 🪖 ({self.event_remaining_or_passed(prev_clan_war['endTime'])})\n'
            )
        if len(only_clan_war_log[:10]) == 0:
            text += f'Список пуст\n'
        return text

    def opponent_info(self, war_win_streak: int, clan_war_log: Optional[dict]):
        text = (
            f'\n'
            f'Серия побед противника: {war_win_streak}\n'
            f'\n'
        )
        if clan_war_log is None:
            text += f'Ход войны противника недоступен'
        else:
            text += f'{self.war_log(clan_war_log)}'
        return text

    def war_members(self, war_clan_members: list, clan_map_position_by_player: dict, rows: list[Record]) -> str:
        war_member_info = {
            row['player_tag']: (
                f'{self.to_html(row['player_name'])} {self.get_player_info_with_emoji(
                    row['town_hall_level'],
                    row['barbarian_king_level'],
                    row['archer_queen_level'],
                    row['grand_warden_level'],
                    row['royal_champion_level']
                )}'
            )
            for row in rows
        }
        war_member_lines = [''] * len(clan_map_position_by_player)
        for member in war_clan_members:
            war_member_lines[clan_map_position_by_player[member['tag']] - 1] = (
                f'{clan_map_position_by_player[member['tag']]}. '
                f'{war_member_info.get(member['tag'], self.to_html(member['name']))}'
            )
        text = '\n'.join(war_member_lines)
        return text

    def cw_preparation(
            self, cw: dict,
            show_opponent_info: bool, war_win_streak: Optional[int], clan_war_log: Optional[dict]
    ) -> str:
        text = (
            f'{self.to_html(cw['clan']['name'])} vs {self.to_html(cw['opponent']['name'])}\n'
            f'{cw['teamSize']} 🪖 vs {cw['teamSize']} 🪖\n'
            f'\n'
            f'{self.event_datetime(Event.CW, cw['startTime'], cw['endTime'], False)}\n'
        )
        if show_opponent_info:
            text += self.opponent_info(war_win_streak, clan_war_log)
        return text

    def cw_in_war_or_war_ended(
            self, cw: dict,
            show_opponent_info: bool, war_win_streak: Optional[int], clan_war_log: Optional[dict]
    ) -> str:
        text = (
            f'{self.event_datetime(Event.CW, cw['startTime'], cw['endTime'], True)}\n'
            f'\n'
            f'{self.to_html(cw['clan']['name'])} vs {self.to_html(cw['opponent']['name'])}\n'
            f'{cw['teamSize']} 🪖 vs {cw['teamSize']} 🪖\n'
            f'{cw['clan']['attacks']} 🗡 vs {cw['opponent']['attacks']} 🗡\n'
            f'{cw['clan']['stars']} ⭐ vs {cw['opponent']['stars']} ⭐\n'
            f'{format(cw['clan']['destructionPercentage'], '.2f')}% vs '
            f'{format(cw['opponent']['destructionPercentage'], '.2f')}%\n'
        )
        if self.state(cw) == 'warEnded':
            text += self.war_result(cw)
        if show_opponent_info:
            text += self.opponent_info(war_win_streak, clan_war_log)
        return text

    def cwlw_preparation(
            self, cwlw: dict, cwl_season: str, cwl_day: int,
            show_opponent_info: bool, war_win_streak: Optional[int], clan_war_log: Optional[dict]
    ) -> str:
        text = (
            f'Сезон ЛВК: {self.season(cwl_season)}, день {cwl_day + 1}\n'
            f'{self.to_html(cwlw['clan']['name'])} vs {self.to_html(cwlw['opponent']['name'])}\n'
            f'{cwlw['teamSize']} 🪖 vs {cwlw['teamSize']} 🪖\n'
            f'\n'
            f'{self.event_datetime(Event.CWLW, cwlw['startTime'], cwlw['endTime'], False)}\n'
        )
        if show_opponent_info:
            text += self.opponent_info(war_win_streak, clan_war_log)
        return text

    def cwlw_in_war_or_war_ended(
            self, cwlw: dict, cwl_season: str, cwl_day: int,
            show_opponent_info: bool, war_win_streak: Optional[int], clan_war_log: Optional[dict]
    ) -> str:
        text = (
            f'{self.event_datetime(Event.CWLW, cwlw['startTime'], cwlw['endTime'], True)}\n'
            f'\n'
            f'Сезон ЛВК: {self.season(cwl_season)}, день {cwl_day + 1}\n'
            f'{self.to_html(cwlw['clan']['name'])} vs {self.to_html(cwlw['opponent']['name'])}\n'
            f'{cwlw['teamSize']} 🪖 vs {cwlw['teamSize']} 🪖\n'
            f'{cwlw['clan']['attacks']} 🗡 vs {cwlw['opponent']['attacks']} 🗡\n'
            f'{cwlw['clan']['stars']} ⭐ vs {cwlw['opponent']['stars']} ⭐\n'
            f'{format(cwlw['clan']['destructionPercentage'], '.2f')}% vs '
            f'{format(cwlw['opponent']['destructionPercentage'], '.2f')}%\n'
        )
        if self.state(cwlw) == 'warEnded':
            text += self.war_result(cwlw)
        if show_opponent_info:
            text += self.opponent_info(war_win_streak, clan_war_log)
        return text

    def raids_ongoing_or_ended(self, raids: dict) -> str:
        current_raid_districts = raids['attackLog'][-1]['districts']
        text = (
            f'{self.event_datetime(Event.RW, raids['startTime'], raids['endTime'], True)}\n'
            f'\n'
            f'Завершено рейдов: {len([
                raid for raid in raids['attackLog']
                if all(district['destructionPercent'] == 100 for district in raid['districts'])
            ])} ⚔️\n'
        )
        if self.state(raids) in ['ongoing']:
            text += (
                f'Уничтожено районов в текущем рейде: '
                f'{len([district for district in current_raid_districts if district['destructionPercent'] == 100])} '
                f'/ {len(current_raid_districts)}\n'
            )
        text += (
            f'Сделано атак: {raids['totalAttacks']} / {6 * 50} 🗡️\n'
            f'Получено столичного золота: {raids['capitalTotalLoot']} {self.get_capital_gold_emoji()}\n'
        )
        if self.state(raids) in ['ended']:
            text += (
                f'Награда за 6 атак: {int(raids['offensiveReward']) * 6 + int(raids['defensiveReward'])} '
                f'{self.get_raid_medal_emoji()}\n'
            )
        return text

    def clan_games_ongoing_or_ended(self, cg: dict) -> str:
        text = f'{self.event_datetime(Event.CG, cg['startTime'], cg['endTime'], True)}\n'
        return text

    @staticmethod
    def calculate_next_raid_weekend() -> tuple[datetime, datetime]:
        dt_now = datetime.now(UTC)
        if (dt_now.weekday(), dt_now.hour) < (0, 7):
            dt_end = datetime(year=dt_now.year, month=dt_now.month, day=dt_now.day, hour=7)
            dt_begin = dt_end - timedelta(days=3)
            return dt_begin, dt_end
        else:
            dt_now = datetime.now(UTC)
            dt_friday = dt_now + timedelta(days=4 - dt_now.weekday())
            dt_begin = datetime(year=dt_friday.year, month=dt_friday.month, day=dt_friday.day, hour=7)
            return dt_begin, dt_begin + timedelta(days=3)

    @staticmethod
    def calculate_next_trader_refresh() -> datetime:
        dt_now = datetime.now(UTC)
        if dt_now.weekday() == 1 and dt_now.hour < 8:
            return datetime(year=dt_now.year, month=dt_now.month, day=dt_now.day, hour=8)
        elif dt_now.weekday() == 1 and dt_now.hour >= 8:
            days_until_next_tuesday = 7
            next_tuesday = dt_now + timedelta(days=days_until_next_tuesday)
            return datetime(year=next_tuesday.year, month=next_tuesday.month, day=next_tuesday.day, hour=8)
        else:
            days_until_next_tuesday = (1 - dt_now.weekday() + 7) % 7
            next_tuesday = dt_now + timedelta(days=days_until_next_tuesday)
            return datetime(year=next_tuesday.year, month=next_tuesday.month, day=next_tuesday.day, hour=8)

    @staticmethod
    def calculate_next_clan_games() -> tuple[datetime, datetime]:
        dt_now = datetime.now(UTC)
        if (dt_now.day, dt_now.hour) < (28, 8):
            return (
                datetime(year=dt_now.year, month=dt_now.month, day=22, hour=8),
                datetime(year=dt_now.year, month=dt_now.month, day=28, hour=8)
            )
        else:
            return (
                datetime(
                    year=dt_now.year if dt_now.month < 12 else dt_now.year + 1,
                    month=dt_now.month + 1 if dt_now.month < 12 else 1,
                    day=22,
                    hour=8
                ),
                datetime(
                    year=dt_now.year if dt_now.month < 12 else dt_now.year + 1,
                    month=dt_now.month + 1 if dt_now.month < 12 else 1,
                    day=28,
                    hour=8
                )
            )

    @staticmethod
    def calculate_next_cwl() -> tuple[datetime, datetime]:
        dt_now = datetime.now(UTC)
        if (dt_now.day, dt_now.hour) < (11, 8):
            return (
                datetime(year=dt_now.year, month=dt_now.month, day=1, hour=8),
                datetime(year=dt_now.year, month=dt_now.month, day=11, hour=8)
            )
        else:
            return (
                datetime(
                    year=dt_now.year if dt_now.month < 12 else dt_now.year + 1,
                    month=dt_now.month + 1 if dt_now.month < 12 else 1,
                    day=1,
                    hour=8
                ),
                datetime(
                    year=dt_now.year if dt_now.month < 12 else dt_now.year + 1,
                    month=dt_now.month + 1 if dt_now.month < 12 else 1,
                    day=1,
                    hour=8
                )
            )

    @staticmethod
    def calculate_next_season_end() -> datetime:
        dt_now = datetime.now(UTC)
        if (dt_now.day, dt_now.hour) < (1, 8):
            return datetime(year=dt_now.year, month=dt_now.month, day=1, hour=8)
        else:
            return datetime(
                year=dt_now.year if dt_now.month < 12 else dt_now.year + 1,
                month=dt_now.month + 1 if dt_now.month < 12 else 1,
                day=1,
                hour=8
            )

    @staticmethod
    def calculate_next_league_reset() -> datetime:
        dt_now = datetime.now(UTC)
        last_day_of_month = (dt_now.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        days_after_last_monday = last_day_of_month.weekday() % 7
        last_monday = last_day_of_month - timedelta(days=days_after_last_monday)
        last_monday = datetime(year=last_monday.year, month=last_monday.month, day=last_monday.day, hour=5)
        if dt_now.replace(tzinfo=None) < last_monday:
            return last_monday
        else:
            dt = datetime(
                year=dt_now.year if dt_now.month < 12 else dt_now.year + 1,
                month=dt_now.month + 1 if dt_now.month < 12 else 1,
                day=1,
                hour=0
            )
            last_day_of_month = (dt.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            days_after_last_monday = last_day_of_month.weekday() % 7
            last_monday = last_day_of_month - timedelta(days=days_after_last_monday)
            return datetime(year=last_monday.year, month=last_monday.month, day=last_monday.day, hour=5)

    @staticmethod
    def calculate_map_positions(war_clan_members: list) -> dict:
        map_position = {}
        for member in war_clan_members:
            map_position[member['tag']] = member['mapPosition']
        map_position = {
            item[0]: i + 1
            for i, item in enumerate(sorted(map_position.items(), key=lambda item: item[1]))
        }
        return map_position

    def get_map(
            self,
            clan_map_position_by_player: dict,
            opponent_map_position_by_player: dict,
            clan_data: dict,
            opponent_data: dict
    ) -> str:
        clan_player_name_by_player_tag = {
            clan_member['tag']: clan_member['name']
            for clan_member
            in clan_data['members']
        }
        opponent_member_lines = [''] * len(opponent_map_position_by_player)
        for opponent_member in opponent_data['members']:
            if opponent_member.get('bestOpponentAttack') is not None:
                best_opponent_attack = opponent_member['bestOpponentAttack']
                if best_opponent_attack['stars'] > 0:
                    opponent_member_lines[opponent_map_position_by_player[opponent_member['tag']] - 1] += (
                        f'{opponent_map_position_by_player[opponent_member['tag']]}. '
                        f'{'⭐' * best_opponent_attack['stars']} '
                        f'({best_opponent_attack['destructionPercentage']}%) '
                        f'⬅️ '
                        f'{clan_map_position_by_player[best_opponent_attack['attackerTag']]}. '
                        f'{self.to_html(clan_player_name_by_player_tag[best_opponent_attack['attackerTag']])}'
                    )
                else:
                    opponent_member_lines[opponent_map_position_by_player[opponent_member['tag']] - 1] += (
                        f'{opponent_map_position_by_player[opponent_member['tag']]}. 0%'
                    )
            else:
                opponent_member_lines[opponent_map_position_by_player[opponent_member['tag']] - 1] += (
                    f'{opponent_map_position_by_player[opponent_member['tag']]}. 0%'
                )
        return '\n'.join(opponent_member_lines)

    def get_attacks(
            self,
            clan_map_position_by_player: dict,
            opponent_map_position_by_player: dict,
            clan_data: dict,
            opponent_data: dict,
            desired_attacks_spent: int
    ) -> str:
        opponent_player_name_by_player_tag = {
            opponent_member['tag']: opponent_member['name']
            for opponent_member
            in opponent_data['members']
        }
        cw_member_lines = [''] * len(clan_map_position_by_player)
        for member in clan_data['members']:
            cw_member_lines[clan_map_position_by_player[member['tag']] - 1] += (
                f'{clan_map_position_by_player[member['tag']]}. '
                f'{self.to_html(member['name'])}: {len(member.get('attacks', []))} / {desired_attacks_spent}\n'
            )
            for attack in member.get('attacks', []):
                if attack['stars'] != 0:
                    cw_member_lines[clan_map_position_by_player[member['tag']] - 1] += (
                        f'{'⭐' * attack['stars']} ({attack['destructionPercentage']}%) '
                        f'➡️ {opponent_map_position_by_player[attack['defenderTag']]}. '
                        f'{self.to_html(opponent_player_name_by_player_tag[attack['defenderTag']])}\n'
                    )
                else:
                    cw_member_lines[clan_map_position_by_player[member['tag']] - 1] += (
                        f'{attack['destructionPercentage']}% '
                        f'➡️ {opponent_map_position_by_player[attack['defenderTag']]}. '
                        f'{self.to_html(opponent_player_name_by_player_tag[attack['defenderTag']])}\n'
                    )
        return '\n'.join(cw_member_lines)

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
        average = round(sum(lst) / len(lst), 2)
        return int(average) if int(average) == average else average

    @staticmethod
    def str_sort_key(value: str) -> tuple[str, str]:
        return str.lower(value), value
