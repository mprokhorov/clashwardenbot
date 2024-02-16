import enum
from collections import namedtuple
from contextlib import suppress
from typing import Optional, Tuple

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from magic_filter import F

from database_manager import DatabaseManager
from output_formatter.output_formatter import Event

router = Router()


class Action(enum.IntEnum):
    cwl_info_day = 1
    cwl_info_days_list = 2
    cwl_attacks_day = 3
    cwl_attacks_days_list = 4


class CWLCallbackFactory(CallbackData, prefix='cwl'):
    action: Action
    cwl_season: Optional[str] = None
    cwl_day: Optional[int] = None


async def cwl_info(dm: DatabaseManager,
                   cwl_day: Optional[int] = None
                   ) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    if cwl_day is None:
        cwl_day, cwlw = await dm.load_clan_war_league_own_war()
    else:
        cwl_day, cwlw = cwl_day, (await dm.load_clan_war_league_own_wars())[cwl_day]
    cwl_season, _ = await dm.load_clan_war_league()
    text = (f'<b>📃 Информация о ЛВК</b>\n'
            f'\n')
    if cwlw is None:
        text += f'Информация о ЛВК отсутствует'
        return text, ParseMode.HTML, None
    if cwlw['state'] == 'preparation':
        text += (f'{dm.of.event_datetime(Event.CWLW, cwlw['startTime'], cwlw['endTime'], True)}\n'
                 f'\n'
                 f'Сезон ЛВК: {dm.of.season(cwl_season)}, день {cwl_day + 1}\n'
                 f'{dm.of.to_html(cwlw['clan']['name'])} vs {dm.of.to_html(cwlw['opponent']['name'])}\n'
                 f'{cwlw['teamSize']} 👤 vs {cwlw['teamSize']} 👤\n')
    elif cwlw['state'] == 'inWar':
        text += (f'{dm.of.event_datetime(Event.CWLW, cwlw['startTime'], cwlw['endTime'], True)}\n'
                 f'\n'
                 f'Сезон ЛВК: {dm.of.season(cwl_season)}, день {cwl_day + 1}\n'
                 f'{dm.of.to_html(cwlw['clan']['name'])} vs {dm.of.to_html(cwlw['opponent']['name'])}\n'
                 f'{cwlw['teamSize']} 👤 vs {cwlw['teamSize']} 👤\n'
                 f'{cwlw['clan']['attacks']} 🗡 vs {cwlw['opponent']['attacks']} 🗡\n'
                 f'{cwlw['clan']['stars']} ⭐ vs {cwlw['opponent']['stars']} ⭐\n'
                 f'{format(cwlw['clan']['destructionPercentage'], '.2f')}% vs '
                 f'{format(cwlw['opponent']['destructionPercentage'], '.2f')}%\n')
    elif cwlw['state'] == 'warEnded':
        text += (f'{dm.of.event_datetime(Event.CWLW, cwlw['startTime'], cwlw['endTime'], True)}\n'
                 f'\n'
                 f'Сезон ЛВК: {dm.of.season(cwl_season)}, день {cwl_day + 1}\n'
                 f'{dm.of.to_html(cwlw['clan']['name'])} vs {dm.of.to_html(cwlw['opponent']['name'])}\n'
                 f'{cwlw['teamSize']} 👤 vs {cwlw['teamSize']} 👤\n'
                 f'{cwlw['clan']['attacks']} 🗡 vs {cwlw['opponent']['attacks']} 🗡\n'
                 f'{cwlw['clan']['stars']} ⭐ vs {cwlw['opponent']['stars']} ⭐\n'
                 f'{format(cwlw['clan']['destructionPercentage'], '.2f')}% vs '
                 f'{format(cwlw['opponent']['destructionPercentage'], '.2f')}%\n')
        if (cwlw['clan']['stars'], cwlw['clan']['destructionPercentage']) > (
                cwlw['opponent']['stars'], cwlw['opponent']['destructionPercentage']):
            text += f'🎉 Победа!'
        elif (cwlw['clan']['stars'], cwlw['clan']['destructionPercentage']) < (
                cwlw['opponent']['stars'], cwlw['opponent']['destructionPercentage']):
            text += f'😢 Поражение'
        else:
            text += f'⚖️ Ничья'
    else:
        text += f'Информация о ЛВК отсутствует\n'
    previous_cwl_day_button = InlineKeyboardButton(
        text='⬅️',
        callback_data=CWLCallbackFactory(
            action=Action.cwl_info_day,
            cwl_day=cwl_day - 1
        ).pack())
    next_cwl_day_button = InlineKeyboardButton(
        text='➡️',
        callback_data=CWLCallbackFactory(
            action=Action.cwl_info_day,
            cwl_day=cwl_day + 1
        ).pack())
    all_cwl_days_button = InlineKeyboardButton(
        text='🧾 Все дни',
        callback_data=CWLCallbackFactory(
            action=Action.cwl_info_days_list,
        ).pack())
    keyboard_row = []
    if cwl_day > 0:
        keyboard_row.append(previous_cwl_day_button)
    if cwl_day < len(await dm.load_clan_war_league_own_wars()) - 1:
        keyboard_row.append(next_cwl_day_button)
    keyboard_row.append(all_cwl_days_button)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[keyboard_row])
    return text, ParseMode.HTML, keyboard


async def cwl_attacks(dm: DatabaseManager, cwl_day: Optional[int] = None):
    if cwl_day is None:
        cwl_day, cwlw = await dm.load_clan_war_league_own_war()
    else:
        cwl_day, cwlw = cwl_day, (await dm.load_clan_war_league_own_wars())[cwl_day]
    cwl_season, _ = await dm.load_clan_war_league()
    text = (f'<b>🗡️ Атаки в ЛВК</b>\n'
            f'\n')
    if cwlw is None:
        text += f'Информация о ЛВК отсутствует'
        return text, ParseMode.HTML, None
    if cwlw['state'] in ['preparation']:
        text += (f'{dm.of.event_datetime(Event.CWLW, cwlw['startTime'], cwlw['endTime'], True)}\n'
                 f'\n'
                 f'Сезон ЛВК: {dm.of.season(cwl_season)}, день {cwl_day + 1}\n'
                 f'{dm.of.to_html(cwlw['clan']['name'])} vs {dm.of.to_html(cwlw['opponent']['name'])}\n'
                 f'{cwlw['teamSize']} 👤 vs {cwlw['teamSize']} 👤\n'
                 f'\n')
        rows = await dm.req_connection.fetch('''
            SELECT player_tag, player_name, town_hall_level,
                   barbarian_king_level, archer_queen_level, grand_warden_level, royal_champion_level
            FROM master.player
            WHERE clan_tag = $1
        ''', dm.clan_tag)
        cwlw_member_info = {row['player_tag']: (f'{dm.of.to_html(row['player_name'])} — 🛖 {row['town_hall_level']}, '
                                                f'👑 {row['barbarian_king_level']} / {row['archer_queen_level']} / '
                                                f'{row['grand_warden_level']} / {row['royal_champion_level']}')
                            for row in rows}
        clan_map_position_by_player = dm.load_map_positions(cwlw['clan']['members'])
        cwlw_member_lines = [''] * len(clan_map_position_by_player)
        for member in cwlw['clan']['members']:
            cwlw_member_lines[clan_map_position_by_player[member['tag']] - 1] = (
                f'{clan_map_position_by_player[member['tag']]}) '
                f'{cwlw_member_info.get(member['tag']) or dm.of.to_html(member['name'])}\n')
        text += ''.join(cwlw_member_lines)
    elif cwlw['state'] in ['inWar', 'warEnded']:
        text += (f'{dm.of.event_datetime(Event.CWLW, cwlw['startTime'], cwlw['endTime'], True)}\n'
                 f'\n'
                 f'Сезон ЛВК: {dm.of.season(cwl_season)}, день {cwl_day + 1}\n'
                 f'{dm.of.to_html(cwlw['clan']['name'])} vs {dm.of.to_html(cwlw['opponent']['name'])}\n'
                 f'{cwlw['teamSize']} 👤 vs {cwlw['teamSize']} 👤\n'
                 f'\n')
        clan_map_position_by_player = dm.load_map_positions(cwlw['clan']['members'])
        opponent_map_position_by_player = dm.load_map_positions(cwlw['opponent']['members'])
        cwlw_member_lines = [''] * len(clan_map_position_by_player)
        for member in cwlw['clan']['members']:
            cwlw_member_lines[clan_map_position_by_player[member['tag']] - 1] += \
                (f'{clan_map_position_by_player[member['tag']]}) '
                 f'{dm.of.to_html(member['name'])} — {len(member.get('attacks', []))} / 1\n')
            for attack in member.get('attacks', []):
                if attack['stars'] != 0:
                    cwlw_member_lines[clan_map_position_by_player[member['tag']] - 1] += \
                        (f'{'⭐' * attack['stars']} ({attack['destructionPercentage']}%) '
                         f'➡️ {opponent_map_position_by_player[attack['defenderTag']]}\n')
                else:
                    cwlw_member_lines[clan_map_position_by_player[member['tag']] - 1] += \
                        (f'{attack['destructionPercentage']}% '
                         f'➡️ {opponent_map_position_by_player[attack['defenderTag']]}\n')
        text += '\n'.join(cwlw_member_lines)
    else:
        text += f'Информация о ЛВК отсутствует\n'
    previous_cwl_day_button = InlineKeyboardButton(
        text='⬅️',
        callback_data=CWLCallbackFactory(
            action=Action.cwl_attacks_day,
            cwl_day=cwl_day - 1
        ).pack())
    next_cwl_day_button = InlineKeyboardButton(
        text='➡️',
        callback_data=CWLCallbackFactory(
            action=Action.cwl_attacks_day,
            cwl_day=cwl_day + 1
        ).pack())
    all_cwl_days_button = InlineKeyboardButton(
        text='🧾 Все дни',
        callback_data=CWLCallbackFactory(
            action=Action.cwl_attacks_days_list,
        ).pack())
    keyboard_row = []
    if cwl_day > 0:
        keyboard_row.append(previous_cwl_day_button)
    if cwl_day < len(await dm.load_clan_war_league_own_wars()) - 1:
        keyboard_row.append(next_cwl_day_button)
    keyboard_row.append(all_cwl_days_button)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[keyboard_row])
    return text, ParseMode.HTML, keyboard


async def cwl_days_list(dm: DatabaseManager,
                        action: Action) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    cwl_season, _ = await dm.load_clan_war_league()
    if action == Action.cwl_info_days_list:
        text = (f'<b>📃 Информация о ЛВК</b>\n'
                f'\n'
                f'Сезон: {dm.of.season(cwl_season)}\n'
                f'\n'
                f'Выберите день:\n')
        button_action = Action.cwl_info_day
    elif action == Action.cwl_attacks_days_list:
        text = (f'<b>🗡️ Атаки в ЛВК</b>\n'
                f'\n'
                f'Сезон: {dm.of.season(cwl_season)}\n'
                f'\n'
                f'Выберите день:\n')
        button_action = Action.cwl_attacks_day
    else:
        raise Exception
    cwl_wars = await dm.load_clan_war_league_own_wars()
    cwl_day_titles = []
    for cwl_war in cwl_wars:
        cwl_clan, cwl_opponent = cwl_war['clan'], cwl_war['opponent']
        if cwl_war['state'] == 'notInWar':
            cwl_day_emoji = ''
        elif cwl_war['state'] == 'warEnded':
            if (cwl_clan['stars'], cwl_clan['destructionPercentage']) > (
                    cwl_opponent['stars'], cwl_opponent['destructionPercentage']):
                cwl_day_emoji = '✅ '
            elif (cwl_clan['stars'], cwl_clan['destructionPercentage']) < (
                    cwl_opponent['stars'], cwl_opponent['destructionPercentage']):
                cwl_day_emoji = '❌ '
            else:
                cwl_day_emoji = '🟰 '
        elif cwl_war['state'] == 'inWar':
            cwl_day_emoji = '🗡 '
        elif cwl_war['state'] == 'preparation':
            cwl_day_emoji = '⚙️ '
        else:
            cwl_day_emoji = '❓ '
        cwl_day_titles.append(f'{cwl_day_emoji}{cwl_clan['name']} vs {cwl_opponent['name']}')
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=cwl_day_title,
            callback_data=CWLCallbackFactory(
                action=button_action,
                cwl_day=i
            ).pack()
        )]
        for i, cwl_day_title in enumerate(cwl_day_titles)
    ])
    return text, ParseMode.HTML, keyboard


async def cwl_skips(dm: DatabaseManager,
                    message: Message,
                    ping: bool) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (f'<b>🙈 Список не проатаковавших в ЛВК</b>\n'
            f'\n')
    cwl_day, cwlw = await dm.load_clan_war_league_own_war()
    if cwlw is None:
        text += 'Информация о ЛВК отсутствует'
        return text, ParseMode.HTML, None
    if cwlw['state'] in ['inWar', 'warEnded']:
        cwl_season, _ = await dm.load_clan_war_league()
        text += (f'Сезон: {dm.of.season(cwl_season)}, день {cwl_day + 1}\n'
                 f'{dm.of.event_datetime(Event.CWLW, cwlw['startTime'], cwlw['endTime'], False)}\n'
                 f'\n')
        CWLWMember = namedtuple(typename='CWLWMember',
                                field_names='player_tag attacks_spent attacks_limit')
        cwlw_members = []
        for cwlw_member in cwlw['clan']['members']:
            cwlw_members.append(
                CWLWMember(player_tag=cwlw_member['tag'],
                           attacks_spent=len(cwlw_member.get('attacks', [])),
                           attacks_limit=1))
        text += await dm.print_skips(message, cwlw_members, ping, 1)
    else:
        text += 'ЛВК сейчас не идёт'
    return text, ParseMode.HTML, None


async def cwl_map(dm: DatabaseManager) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    cwl_wars = await dm.load_clan_war_league_last_day_wars()
    text = (f'<b>🗺️ Карта ЛВК</b>\n'
            f'\n')
    if cwl_wars is None:
        text += 'Информация о ЛВК отсутствует'
        return text, ParseMode.HTML, None
    cwl_season, _ = await dm.load_clan_war_league()
    cwl_day, _ = await dm.load_clan_war_league_own_war()
    text += (f'Сезон: {dm.of.season(cwl_season)}, день {cwl_day + 1}\n'
             f'\n')
    cwl_clans = []
    for cwl_war in cwl_wars:
        cwl_clans.append(cwl_war['clan'])
        cwl_clans.append(cwl_war['opponent'])
    CWLClan = namedtuple(typename='CWLClan',
                         field_names='clan_name town_halls average_town_hall')
    cwl_clans_to_sort = []
    for cwl_clan in cwl_clans:
        cwl_members = []
        CWLMember = namedtuple(typename='CWLMember', field_names='town_hall_level map_position')
        for cwl_clan_cwl_member in cwl_clan['members']:
            cwl_members.append(CWLMember(town_hall_level=cwl_clan_cwl_member['townhallLevel'],
                                         map_position=cwl_clan_cwl_member['mapPosition']))
        cwl_members.sort(key=lambda cwl_mp: cwl_mp.map_position)
        cwl_clans_to_sort.append(
            CWLClan(clan_name=cwl_clan['name'],
                    town_halls=[cwl_m.town_hall_level for cwl_m in cwl_members],
                    average_town_hall=dm.avg([cwl_m.town_hall_level for cwl_m in cwl_members])))
    cwl_clans_to_sort.sort(key=lambda cwl_c: cwl_c.average_town_hall, reverse=True)
    for cwl_clan in cwl_clans_to_sort:
        text += (f'<b>{dm.of.to_html(cwl_clan.clan_name)}</b>\n'
                 f'ТХ: {', '.join([str(town_hall) for town_hall in cwl_clan.town_halls])} — средний: '
                 f'{cwl_clan.average_town_hall}\n'
                 f'\n')
    return text, ParseMode.HTML, None


@router.message(Command('cwl_info'))
async def command_cwl_info(message: Message, dm: DatabaseManager):
    text, parse_mode, reply_markup = await cwl_info(dm)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(CWLCallbackFactory.filter(F.action == Action.cwl_info_day))
async def callback_cwl_info_day(callback_query: CallbackQuery,
                                callback_data: CWLCallbackFactory,
                                dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cwl_info(dm, callback_data.cwl_day)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await callback_query.answer()


@router.callback_query(CWLCallbackFactory.filter(F.action == Action.cwl_info_days_list))
async def callback_cwl_info_days_list(callback_query: CallbackQuery,
                                      callback_data: CWLCallbackFactory,
                                      dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cwl_days_list(dm, callback_data.action)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await callback_query.answer()


@router.message(Command('cwl_attacks'))
async def command_cwl_attacks(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await cwl_attacks(dm)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(CWLCallbackFactory.filter(F.action == Action.cwl_attacks_day))
async def callback_cwl_attacks_day(callback_query: CallbackQuery,
                                   callback_data: CWLCallbackFactory,
                                   dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cwl_attacks(dm, callback_data.cwl_day)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await callback_query.answer()


@router.callback_query(CWLCallbackFactory.filter(F.action == Action.cwl_attacks_days_list))
async def callback_cwl_attacks_days_list(callback_query: CallbackQuery,
                                         callback_data: CWLCallbackFactory,
                                         dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cwl_days_list(dm, callback_data.action)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await callback_query.answer()


@router.message(Command('cwl_skips'))
async def command_cwl_skips(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await cwl_skips(dm, message, ping=False)
    await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)


@router.message(Command('cwl_ping'))
async def command_cwl_ping(message: Message, dm: DatabaseManager) -> None:
    if not await dm.can_user_ping_group_members(message):
        await message.reply(text=f'Эта команда не работает для вас')
    else:
        text, parse_mode, reply_markup = await cwl_skips(dm, message, ping=True)
        await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)


@router.message(Command('cwl_map'))
async def command_cwl_map(message: Message, dm: DatabaseManager):
    text, parse_mode, reply_markup = await cwl_map(dm)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)
