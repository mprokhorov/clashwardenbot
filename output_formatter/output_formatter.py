from datetime import datetime, timedelta, UTC
from enum import Enum
from typing import Optional


class Event(Enum):
    CW = 1
    RW = 2
    CWL = 3
    CWLW = 4


class OutputFormatter:
    def __init__(self,
                 utc_to_local_hours: Optional[timedelta] = timedelta(hours=3)):
        self.utc_to_local_hours = utc_to_local_hours

    def to_html(self, text: str) -> str:
        return (text
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;'))

    def season(self, season_data: str) -> str:
        month_in_russian = {'01': 'январь',
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
                            '12': 'декабрь'}
        year, month = season_data.split('-')
        return f'{month_in_russian[month]} {year} г.'

    def role(self, role_data: str) -> str:
        role_in_russian = {'leader': 'глава',
                           'coLeader': 'соруководитель',
                           'admin': 'старейшина',
                           'member': 'участник'}
        return role_in_russian[role_data]

    def district(self, district_data: str) -> str:
        district_in_russian = {'Capital Peak': 'Столичный пик',
                               'Barbarian Camp': 'Лагерь варваров',
                               'Wizard Valley': 'Долина колдунов',
                               'Balloon Lagoon': 'Лагуна шаров',
                               'Builder\'s Workshop': 'Мастерская строителя',
                               'Dragon Cliffs': 'Драконьи утесы',
                               'Golem Quarry': 'Карьер големов',
                               'Skeleton Park': 'Парк скелетов',
                               'Goblin Mines': 'Гоблинские шахты'}
        return district_in_russian[district_data]

    def short_datetime(self, datetime_data: datetime) -> str:
        dt = datetime_data + self.utc_to_local_hours
        month_in_russian_genitive = {1: 'января',
                                     2: 'февраля',
                                     3: 'марта',
                                     4: 'апреля',
                                     5: 'мая',
                                     6: 'июня',
                                     7: 'июля',
                                     8: 'августа',
                                     9: 'сентября',
                                     0: 'октября',
                                     11: 'ноября',
                                     12: 'декабря'}
        return f'{dt.day} {month_in_russian_genitive[dt.month]} {dt.year}, в {dt.hour}:{str(dt.minute).zfill(2)}'

    def shortest_datetime(self, datetime_data: datetime) -> str:
        dt = datetime_data + self.utc_to_local_hours
        dt_now = datetime.now(UTC) + self.utc_to_local_hours
        month_in_russian_genitive = {1: 'января',
                                     2: 'февраля',
                                     3: 'марта',
                                     4: 'апреля',
                                     5: 'мая',
                                     6: 'июня',
                                     7: 'июля',
                                     8: 'августа',
                                     9: 'сентября',
                                     0: 'октября',
                                     11: 'ноября',
                                     12: 'декабря'}
        if dt.day == dt_now.day:
            return f'сегодня в {dt.hour}:{str(dt.minute).zfill(2)}'
        elif dt.day == (dt_now - timedelta(days=1)).day:
            return f'вчера в {dt.hour}:{str(dt.minute).zfill(2)}'
        else:
            return f'{dt.day} {month_in_russian_genitive[dt.month]} в {dt.hour}:{str(dt.minute).zfill(2)}'

    def event_datetime(self,
                       event: Event,
                       start_datetime_data: str,
                       end_datetime_data: str,
                       show_datetime: bool) -> str:
        dt_now = datetime.now(UTC).replace(tzinfo=None) + self.utc_to_local_hours
        dt_event_start = datetime.strptime(start_datetime_data, '%Y%m%dT%H%M%S.%fZ') + self.utc_to_local_hours
        dt_event_end = datetime.strptime(end_datetime_data, '%Y%m%dT%H%M%S.%fZ') + self.utc_to_local_hours
        if dt_now < dt_event_start:
            dt_event = dt_event_start
        else:
            dt_event = dt_event_end
        dt_diff = abs(dt_event - dt_now)
        days = dt_diff.days
        hours = dt_diff.seconds // 3600
        minutes = (dt_diff.seconds % 3600) // 60

        day_in_russian = ['', '1 день', '2 дня', '3 дня', '4 дня',
                          '5 дней', '6 дней', '7 дней', '8 дней', '9 дней',
                          '10 дней', '11 дней', '12 дней', '13 дней', '14 дней',
                          '15 дней', '16 дней', '17 дней', '18 дней', '19 дней',
                          '20 дней', '21 дней', '22 дня', '23 дня', '24 дня',
                          '25 дней', '26 дней', '27 дней', '28 дней', '29 дней',
                          '30 дней', '31 день', '32 дня', '33 дня', '34 дня']

        hour_in_russian = ['', '1 час', '2 часа', '3 часа', '4 часа',
                           '5 часов', '6 часов', '7 часов', '8 часов', '9 часов',
                           '10 часов', '11 часов', '12 часов', '13 часов', '14 часов',
                           '15 часов', '16 часов', '17 часов', '18 часов', '19 часов',
                           '20 часов', '21 час', '22 часа', '23 часа']

        minute_in_russian = ['', '1 минуту', '2 минуты', '3 минуты', '4 минуты',
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
                             '55 минут', '56 минут', '57 минут', '58 минут', '59 минут']

        event_name = {Event.CW: 'КВ',
                      Event.RW: 'Рейды',
                      Event.CWL: 'ЛВК',
                      Event.CWLW: 'Война'}

        event_name_genitive = {Event.CW: 'КВ',
                               Event.RW: 'рейдов',
                               Event.CWL: 'ЛВК',
                               Event.CWLW: 'войны'}

        event_verbs = {Event.CW: ('начнётся', 'закончится', 'закончилась'),
                       Event.RW: ('начнётся', 'закончится', 'закончилась'),
                       Event.CWL: ('начнутся', 'закончатся', 'закончились'),
                       Event.CWLW: ('начнётся', 'закончится', 'закончилась')}

        output_string = ''
        if dt_now < dt_event_start:
            if show_datetime:
                output_string += ('Начало ' + event_name_genitive[event] + ': ' +
                                  self.short_datetime(dt_event - self.utc_to_local_hours) + ',')
            else:
                output_string += event_name[event] + ' ' + event_verbs[event][0]
        else:
            if show_datetime:
                output_string += ('Конец ' + event_name_genitive[event] + ': ' +
                                  self.short_datetime(dt_event - self.utc_to_local_hours) + ',')
            else:
                output_string += event_name[event] + ' ' + (event_verbs[event][1 if (dt_now < dt_event) else 2])
        output_string += ' '
        if dt_now < dt_event:
            output_string += 'через ' if minutes != 0 or hours != 0 else 'сейчас'
            if days != 0:
                output_string += day_in_russian[days] + ', '
            if hours != 0:
                output_string += hour_in_russian[hours]
            if hours != 0 and minutes != 0:
                output_string += ' и '
            if minutes != 0:
                output_string += minute_in_russian[minutes]
        else:
            if days != 0:
                output_string += day_in_russian[days] + ', '
            if hours != 0:
                output_string += hour_in_russian[hours]
            if hours != 0 and minutes != 0:
                output_string += ' и '
            if minutes != 0:
                output_string += minute_in_russian[minutes]
            output_string += ' назад' if minutes != 0 or hours != 0 else 'сейчас'

        return output_string
