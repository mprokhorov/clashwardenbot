from datetime import datetime, timedelta, UTC
from enum import Enum
from typing import Optional, Tuple

from config import config


class Event(Enum):
    CW = 1
    RW = 2
    CWL = 3
    CWLW = 4
    CG = 5
    TR = 6
    LR = 7
    SE = 8


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
    def get_capital_gold_emoji():
        return f'<tg-emoji emoji-id="{config.capital_gold_emoji_id.get_secret_value()}">🟡</tg-emoji>'

    @staticmethod
    def get_raid_medal_emoji():
        return f'<tg-emoji emoji-id="{config.raid_medal_emoji_id.get_secret_value()}">⚪</tg-emoji>'

    @staticmethod
    def get_town_hall_emoji(town_hall_level: int):
        return (
            f'<tg-emoji emoji-id="{config.town_hall_emoji_ids[town_hall_level - 1].get_secret_value()}">🛖</tg-emoji>'
        )

    @staticmethod
    def get_builder_hall_emoji(builder_hall_level: int):
        return (
            f'<tg-emoji emoji-id="{config.builder_hall_emoji_ids[builder_hall_level - 1].get_secret_value()}">'
            f'🛖</tg-emoji>'
        )

    @staticmethod
    def get_barbarian_king_emoji():
        return (
            f'<tg-emoji emoji-id="{config.home_village_hero_emoji_ids[0].get_secret_value()}">🤴</tg-emoji>'
        )

    @staticmethod
    def get_archer_queen_emoji():
        return (
            f'<tg-emoji emoji-id="{config.home_village_hero_emoji_ids[1].get_secret_value()}">👸</tg-emoji>'
        )

    @staticmethod
    def get_grand_warden_emoji():
        return (
            f'<tg-emoji emoji-id="{config.home_village_hero_emoji_ids[2].get_secret_value()}">👴</tg-emoji>'
        )

    @staticmethod
    def get_royal_champion_emoji():
        return (
            f'<tg-emoji emoji-id="{config.home_village_hero_emoji_ids[3].get_secret_value()}">🙍‍♀️</tg-emoji>'
        )

    @staticmethod
    def get_player_info_with_emoji(
            town_hall_level: int,
            barbarian_king_level: int,
            archer_queen_level: int,
            grand_warden_level: int,
            royal_champion_level: int
    ) -> str:
        text = f'🛖{town_hall_level}'
        if barbarian_king_level > 0:
            text += f' 🤴{barbarian_king_level}'
        if archer_queen_level > 0:
            text += f' 👸{archer_queen_level}'
        if grand_warden_level > 0:
            text += f' 👴{grand_warden_level}'
        if royal_champion_level > 0:
            text += f' 🙍‍♀️{royal_champion_level}'
        return text

    @staticmethod
    def get_player_info_for_callback_text(
            town_hall_level: int,
            barbarian_king_level: int,
            archer_queen_level: int,
            grand_warden_level: int,
            royal_champion_level: int
    ) -> str:
        text = f'🛖{town_hall_level}'
        hero_levels = [barbarian_king_level, archer_queen_level, grand_warden_level, royal_champion_level]
        if any(hero_levels):
            text += f' 👑 {', '.join(str(hero_level or '–') for hero_level in hero_levels)}'
        return text

    def get_player_info_with_custom_emoji(
            self,
            town_hall_level: int,
            barbarian_king_level: int,
            archer_queen_level: int,
            grand_warden_level: int,
            royal_champion_level: int
    ) -> str:
        text = f'{self.get_town_hall_emoji(town_hall_level)}{town_hall_level}'
        if barbarian_king_level > 0:
            text += f' {self.get_barbarian_king_emoji()}{barbarian_king_level}'
        if archer_queen_level > 0:
            text += f' {self.get_archer_queen_emoji()}{archer_queen_level}'
        if grand_warden_level > 0:
            text += f' {self.get_grand_warden_emoji()}{grand_warden_level}'
        if royal_champion_level > 0:
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
        if dt.day == dt_now.day:
            return f'сегодня в {dt.hour}:{str(dt.minute).zfill(2)}'
        else:
            return f'{dt.day} {month_in_russian_genitive[dt.month]} в {dt.hour}:{str(dt.minute).zfill(2)}'

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

        day_in_russian = [
            '', '1 день', '2 дня', '3 дня', '4 дня',
            '5 дней', '6 дней', '7 дней', '8 дней', '9 дней',
            '10 дней', '11 дней', '12 дней', '13 дней', '14 дней',
            '15 дней', '16 дней', '17 дней', '18 дней', '19 дней',
            '20 дней', '21 дней', '22 дня', '23 дня', '24 дня',
            '25 дней', '26 дней', '27 дней', '28 дней', '29 дней',
            '30 дней', '31 день', '32 дня', '33 дня', '34 дня'
        ]

        hour_in_russian = [
            '', '1 час', '2 часа', '3 часа', '4 часа',
            '5 часов', '6 часов', '7 часов', '8 часов', '9 часов',
            '10 часов', '11 часов', '12 часов', '13 часов', '14 часов',
            '15 часов', '16 часов', '17 часов', '18 часов', '19 часов',
            '20 часов', '21 час', '22 часа', '23 часа'
        ]

        minute_in_russian = [
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

        second_in_russian = [
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
            dt_diff_str = day_in_russian[days]
            if hours != 0:
                dt_diff_str += ' и ' + hour_in_russian[hours]
        elif hours != 0:
            dt_diff_str = hour_in_russian[hours]
            if minutes != 0:
                dt_diff_str += ' и ' + minute_in_russian[minutes]
        elif minutes != 0:
            dt_diff_str = minute_in_russian[minutes]
            if minutes < 10 and seconds != 0:
                dt_diff_str += ' и ' + second_in_russian[seconds]
        elif seconds != 0:
            dt_diff_str = second_in_russian[seconds]
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

    def cw_preparation(self, cw: dict) -> str:
        text = (
            f'{self.to_html(cw['clan']['name'])} vs {self.to_html(cw['opponent']['name'])}\n'
            f'{cw['teamSize']} 🪖 vs {cw['teamSize']} 🪖\n'
            f'\n'
            f'{self.event_datetime(Event.CW, cw['startTime'], cw['endTime'], False)}\n'
        )
        return text

    def cw_in_war_or_ended(self, cw: dict) -> str:
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
        return text

    def cwlw_preparation(self, cwlw: dict, cwl_season: str, cwl_day: int) -> str:
        text = (
            f'Сезон ЛВК: {self.season(cwl_season)}, день {cwl_day + 1}\n'
            f'{self.to_html(cwlw['clan']['name'])} vs {self.to_html(cwlw['opponent']['name'])}\n'
            f'{cwlw['teamSize']} 🪖 vs {cwlw['teamSize']} 🪖\n'
            f'\n'
            f'{self.event_datetime(Event.CW, cwlw['startTime'], cwlw['endTime'], False)}\n'
        )
        return text

    def cwlw_in_war_or_ended(self, cwlw: dict, cwl_season: str, cwl_day: int) -> str:
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
        return text

    def raid_ongoing_or_ended(self, raid: dict) -> str:
        districts_count = 9
        text = (
            f'{self.event_datetime(Event.RW, raid['startTime'], raid['endTime'], True)}\n'
            f'\n'
            f'Получено столичного золота: {raid['capitalTotalLoot']} {self.get_capital_gold_emoji()}\n'
            f'Завершено рейдов: {raid['enemyDistrictsDestroyed'] // districts_count} ⚔️\n'
            f'Сделано атак: {raid['totalAttacks']} / 300 🗡️\n'
        )
        if raid.get('offensiveReward') and raid.get('defensiveReward'):
            text += (
                f'Награда за 6 атак: {int(raid['offensiveReward']) * 6 + int(raid['defensiveReward'])} '
                f'{self.get_raid_medal_emoji()}\n'
            )
        return text

    def clan_games_ongoing_or_ended(self, cg: dict) -> str:
        text = f'{self.event_datetime(Event.CG, cg['startTime'], cg['endTime'], True)}\n'
        return text

    @staticmethod
    def calculate_next_raid_weekend() -> Tuple[datetime, datetime]:
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
    def calculate_next_clan_games() -> Tuple[datetime, datetime]:
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
    def calculate_next_cwl() -> Tuple[datetime, datetime]:
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
                day=dt_now.day,
                hour=dt_now.hour
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
