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
    change_cw_status = 1
    change_cw_list_ordering = 2


class CWListOrderding(enum.IntEnum):
    by_trophies = 1
    by_town_hall_and_heroes = 2


class CWCallbackFactory(CallbackData, prefix='cw'):
    action: Action
    player_tag: Optional[str] = None
    is_player_set_for_clan_wars: Optional[bool] = None
    cw_list_ordering: Optional[CWListOrderding] = None


async def cw_info(dm: DatabaseManager) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    cw = await dm.load_clan_war()
    text = (f'<b>📃 Информация о КВ</b>\n'
            f'\n')
    if cw is None:
        text += f'Информация о КВ отсутствует'
        return text, ParseMode.HTML, None
    if cw['state'] in ['preparation']:
        text += (f'{dm.of.event_datetime(Event.CW, cw['startTime'], cw['endTime'], True)}\n'
                 f'\n'
                 f'{dm.of.to_html(cw['clan']['name'])} vs {dm.of.to_html(cw['opponent']['name'])}\n'
                 f'{cw['teamSize']} 👤 vs {cw['teamSize']} 👤\n')
    elif cw['state'] in ['inWar']:
        text += (f'{dm.of.event_datetime(Event.CW, cw['startTime'], cw['endTime'], True)}\n'
                 f'\n'
                 f'{dm.of.to_html(cw['clan']['name'])} vs {dm.of.to_html(cw['opponent']['name'])}\n'
                 f'{cw['teamSize']} 👤 vs {cw['teamSize']} 👤\n'
                 f'{cw['clan']['attacks']} 🗡 vs {cw['opponent']['attacks']} 🗡\n'
                 f'{cw['clan']['stars']} ⭐ vs {cw['opponent']['stars']} ⭐\n'
                 f'{format(cw['clan']['destructionPercentage'], '.2f')}% vs '
                 f'{format(cw['opponent']['destructionPercentage'], '.2f')}%\n')
    elif cw['state'] in ['warEnded']:
        text += (f'{dm.of.event_datetime(Event.CW, cw['startTime'], cw['endTime'], True)}\n'
                 f'\n'
                 f'{dm.of.to_html(cw['clan']['name'])} vs {dm.of.to_html(cw['opponent']['name'])}\n'
                 f'{cw['teamSize']} 👤 vs {cw['teamSize']} 👤\n'
                 f'{cw['clan']['attacks']} 🗡 vs {cw['opponent']['attacks']} 🗡\n'
                 f'{cw['clan']['stars']} ⭐ vs {cw['opponent']['stars']} ⭐\n'
                 f'{format(cw['clan']['destructionPercentage'], '.2f')}% vs '
                 f'{format(cw['opponent']['destructionPercentage'], '.2f')}%\n')
        if (cw['clan']['stars'], cw['clan']['destructionPercentage']) > (
                cw['opponent']['stars'], cw['opponent']['destructionPercentage']):
            text += f'🎉 Победа!\n'
        elif (cw['clan']['stars'], cw['clan']['destructionPercentage']) < (
                cw['opponent']['stars'], cw['opponent']['destructionPercentage']):
            text += f'😢 Поражение\n'
        else:
            text += f'⚖️ Ничья\n'
    else:
        text += f'Информация о КВ отсутствует\n'
    return text, ParseMode.HTML, None


async def cw_attacks(dm: DatabaseManager) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    cw = await dm.load_clan_war()
    text = (f'<b>🗡️ Атаки в КВ</b>\n'
            f'\n')
    if cw is None:
        text += f'Информация о КВ отсутствует\n'
        return text, ParseMode.HTML, None
    if cw['state'] in ['preparation']:
        text += (f'{dm.of.event_datetime(Event.CW, cw['startTime'], cw['endTime'], True)}\n'
                 f'\n'
                 f'{dm.of.to_html(cw['clan']['name'])} vs {dm.of.to_html(cw['opponent']['name'])}\n'
                 f'{cw['teamSize']} 👤 vs {cw['teamSize']} 👤\n'
                 f'\n')
        rows = await dm.req_connection.fetch('''
            SELECT player_tag, player_name, town_hall_level,
                   barbarian_king_level, archer_queen_level, grand_warden_level, royal_champion_level
            FROM player
            WHERE clan_tag = $1 -- AND is_player_in_clan
        ''', dm.clan_tag)
        cw_member_info = {row['player_tag']: (f'{dm.of.to_html(row['player_name'])} — 🛖 {row['town_hall_level']}, '
                                              f'👑 {row['barbarian_king_level']} / {row['archer_queen_level']} / '
                                              f'{row['grand_warden_level']} / {row['royal_champion_level']}')
                          for row in rows}
        clan_map_position_by_player = {}
        for member in cw['clan']['members']:
            clan_map_position_by_player[member['tag']] = member['mapPosition']
        cw_member_lines = [''] * len(clan_map_position_by_player)
        for member in cw['clan']['members']:
            cw_member_lines[clan_map_position_by_player[member['tag']] - 1] = (
                f'{clan_map_position_by_player[member['tag']]}) '
                f'{cw_member_info.get(member['tag'], dm.of.to_html(member['name']))}\n')
        text += ''.join(cw_member_lines)
    elif cw['state'] in ['inWar', 'warEnded']:
        text += (f'{dm.of.event_datetime(Event.CW, cw['startTime'], cw['endTime'], True)}\n'
                 f'\n'
                 f'{dm.of.to_html(cw['clan']['name'])} vs {dm.of.to_html(cw['opponent']['name'])}\n'
                 f'{cw['teamSize']} 👤 vs {cw['teamSize']} 👤\n'
                 f'\n')
        clan_map_position_by_player = {}
        for member in cw['clan']['members']:
            clan_map_position_by_player[member['tag']] = member['mapPosition']
        opponent_map_position_by_player = {}
        for member in cw['opponent']['members']:
            opponent_map_position_by_player[member['tag']] = member['mapPosition']
        cw_member_lines = [''] * len(clan_map_position_by_player)
        for member in cw['clan']['members']:
            len(member.get('attacks', []))
            cw_member_lines[clan_map_position_by_player[member['tag']] - 1] += \
                (f'{clan_map_position_by_player[member['tag']]}) '
                 f'{dm.of.to_html(member['name'])} — {len(member.get('attacks', []))} / 2\n')
            for attack in member.get('attacks', []):
                if attack['stars'] != 0:
                    cw_member_lines[clan_map_position_by_player[member['tag']] - 1] += \
                        (f'{'⭐' * attack['stars']} ({attack['destructionPercentage']}%) '
                         f'➡️ {opponent_map_position_by_player[attack['defenderTag']]}\n')
                else:
                    cw_member_lines[clan_map_position_by_player[member['tag']] - 1] += \
                        (f'{attack['destructionPercentage']}% '
                         f'➡️ {opponent_map_position_by_player[attack['defenderTag']]}\n')
        text += '\n'.join(cw_member_lines)
    else:
        text += f'Информация о КВ отсутствует\n'
    return text, ParseMode.HTML, None


async def cw_status(dm: DatabaseManager,
                    message: Optional[Message],
                    callback_query: Optional[CallbackQuery],
                    callback_data: Optional[CWCallbackFactory]
                    ) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (f'<b>✍🏻 Изменение статуса участия в КВ</b>\n'
            f'\n')
    if callback_data is not None and callback_data.player_tag is not None:
        await dm.req_connection.execute('''
            UPDATE player
            SET is_player_set_for_clan_wars = $1
            WHERE clan_tag = $2 and player_tag = $3
        ''', callback_data.is_player_set_for_clan_wars, dm.clan_tag, callback_data.player_tag)
    if message is not None:
        user_id = message.from_user.id
    elif callback_query is not None:
        user_id = callback_query.from_user.id
    else:
        raise Exception
    rows = await dm.req_connection.fetch('''
        SELECT DISTINCT
            player_tag, player_name, is_player_set_for_clan_wars,
            town_hall_level, barbarian_king_level, archer_queen_level, grand_warden_level, royal_champion_level
        FROM
            player
            JOIN player_bot_user USING (clan_tag, player_tag)
            JOIN bot_user USING (clan_tag, chat_id, user_id)
        WHERE clan_tag = $1 AND is_player_in_clan AND user_id = $2 AND is_user_in_chat
        ORDER BY
            town_hall_level DESC,
            (barbarian_king_level + archer_queen_level + grand_warden_level + royal_champion_level) DESC,
            player_name
    ''', dm.clan_tag, user_id)
    if len(rows) == 0:
        text += f'В базе данных нет вашего аккаунта'
        return text, ParseMode.HTML, None
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f'{'✅' if row['is_player_set_for_clan_wars'] else '❌'} '
                 f'{dm.load_name(row['player_tag'])} — 🛖 {row['town_hall_level']}, '
                 f'👑 {row['barbarian_king_level']} / {row['archer_queen_level']} / '
                 f'{row['grand_warden_level']} / {row['royal_champion_level']}',
            callback_data=CWCallbackFactory(
                action=Action.change_cw_status,
                player_tag=row['player_tag'],
                is_player_set_for_clan_wars=not row['is_player_set_for_clan_wars']
            ).pack())]
        for row in rows
    ] + [[InlineKeyboardButton(
              text='🔄 Обновить',
              callback_data=CWCallbackFactory(
                  action=Action.change_cw_status
              ).pack())]])
    return text, ParseMode.HTML, keyboard


async def cw_list(dm: DatabaseManager,
                  callback_data: Optional[CWCallbackFactory]
                  ) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    cw_list_ordering = getattr(callback_data, 'cw_list_ordering', CWListOrderding.by_trophies)
    if cw_list_ordering == CWListOrderding.by_trophies:
        rows = await dm.req_connection.fetch('''
            SELECT
                player_name, town_hall_level,
                barbarian_king_level, archer_queen_level, grand_warden_level, royal_champion_level
            FROM player
            WHERE clan_tag = $1 AND player.is_player_in_clan AND is_player_set_for_clan_wars
            ORDER BY home_village_trophies DESC
        ''', dm.clan_tag)
        text = (f'<b>📋 Список участников КВ (⬇️ по трофеям)</b>\n'
                f'\n')
        opposite_ordering_button_text = '⬇️ по ТХ и героям'
        opposite_ordering = CWListOrderding.by_town_hall_and_heroes
    elif cw_list_ordering == CWListOrderding.by_town_hall_and_heroes:
        rows = await dm.req_connection.fetch('''
            SELECT
                player_name, town_hall_level,
                barbarian_king_level, archer_queen_level, grand_warden_level, royal_champion_level
            FROM player
            WHERE clan_tag = $1 AND player.is_player_in_clan AND is_player_set_for_clan_wars
            ORDER BY
                town_hall_level DESC,
                (barbarian_king_level + archer_queen_level + grand_warden_level + royal_champion_level) DESC,
                player_name
        ''', dm.clan_tag)
        text = (f'<b>📋 Список участников КВ (⬇️ по ТХ и героям)</b>\n'
                f'\n')
        opposite_ordering_button_text = '⬇️ по трофеям'
        opposite_ordering = CWListOrderding.by_trophies
    else:
        raise Exception
    keyboard = None
    if len(rows) > 0:
        for i, row in enumerate(rows):
            text += (f'{i + 1}) {dm.of.to_html(row['player_name'])} — 🛖 {row['town_hall_level']}, '
                     f'👑 {row['barbarian_king_level']} / {row['archer_queen_level']} / '
                     f'{row['grand_warden_level']} / {row['royal_champion_level']}\n')
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=opposite_ordering_button_text,
                                 callback_data=CWCallbackFactory(
                                     action=Action.change_cw_list_ordering,
                                     cw_list_ordering=opposite_ordering
                                 ).pack())
        ]])
    else:
        text += 'Список пуст\n'
    return text, ParseMode.HTML, keyboard


async def cw_skips(dm: DatabaseManager,
                   message: Message,
                   ping: bool) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (f'<b>🙈 Список не проатаковавших в КВ</b>\n'
            f'\n')
    cw = await dm.load_clan_war()
    if cw is None:
        text += 'Информация о КВ отсутствует'
        return text, ParseMode.HTML, None
    if cw['state'] in ['inWar', 'warEnded']:
        cwl_season, _ = await dm.load_clan_war_league()
        text += (f'{dm.of.event_datetime(Event.CW, cw['startTime'], cw['endTime'], False)}\n'
                 f'\n')
        CWMember = namedtuple(typename='CWMember',
                              field_names='player_tag attacks_spent attacks_limit')
        cw_members = []
        for cw_member in cw['clan']['members']:
            cw_members.append(
                CWMember(player_tag=cw_member['tag'],
                         attacks_spent=len(cw_member.get('attacks', [])),
                         attacks_limit=2))
        text += await dm.print_skips(message, cw_members, ping, 2)
    else:
        text += 'КВ сейчас не идёт'
    return text, ParseMode.HTML, None


@router.message(Command('cw_info'))
async def command_cw_info(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await cw_info(dm)
    await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)


@router.message(Command('cw_attacks'))
async def command_cw_attacks(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await cw_attacks(dm)
    await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)


@router.message(Command('cw_status'))
async def command_cw_status(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await cw_status(dm, message, None, None)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(CWCallbackFactory.filter(F.action == Action.change_cw_status))
async def callback_cw_status(callback_query: CallbackQuery,
                             callback_data: CWCallbackFactory,
                             dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cw_status(dm, None, callback_query, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback_query.answer()


@router.message(Command('cw_list'))
async def command_cw_list(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await cw_list(dm, None)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(CWCallbackFactory.filter(F.action == Action.change_cw_list_ordering))
async def callback_cw_list(callback_query: CallbackQuery,
                           callback_data: CWCallbackFactory,
                           dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cw_list(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback_query.answer()


@router.message(Command('cw_skips'))
async def command_cw_skips(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await cw_skips(dm, message, ping=False)
    await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)


@router.message(Command('cw_ping'))
async def command_cw_ping(message: Message, dm: DatabaseManager) -> None:
    if not await dm.can_user_ping_group_members(message):
        await message.reply(text=f'Эта команда не работает для вас')
    else:
        text, parse_mode, reply_markup = await cw_skips(dm, message, ping=True)
        await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
