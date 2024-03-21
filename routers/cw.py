import enum
from collections import namedtuple
from contextlib import suppress
from typing import Optional, Tuple

from aiogram import Router
from aiogram.enums import ParseMode, ChatType
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
    text = \
        (f'<b>📃 Информация о КВ</b>\n'
         f'\n'
         )
    cw = await dm.load_clan_war()
    if cw and dm.of.war_state(cw) == 'preparation':
        text += dm.of.cw_preparation(cw)
    elif cw and dm.of.war_state(cw) in ['inWar', 'warEnded']:
        text += dm.of.cw_in_war_or_ended(cw)
    else:
        text += f'Информация о КВ отсутствует\n'
        return text, ParseMode.HTML, None
    return text, ParseMode.HTML, None


async def cw_attacks(dm: DatabaseManager) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    cw = await dm.load_clan_war()
    text = (
        f'<b>🗡️ Атаки в КВ</b>\n'
        f'\n'
    )
    if cw is None:
        text += f'Информация о КВ отсутствует\n'
        return text, ParseMode.HTML, None
    if dm.of.war_state(cw) in ['preparation']:
        text += (
            f'{dm.of.cw_preparation(cw)}'
            f'\n'
        )
        rows = await dm.acquired_connection.fetch('''
            SELECT player_tag, player_name, town_hall_level,
                   barbarian_king_level, archer_queen_level, grand_warden_level, royal_champion_level
            FROM player
            WHERE clan_tag = $1
        ''', dm.clan_tag)
        cw_member_info = {
            row['player_tag']: (
                f'{dm.of.to_html(row['player_name'])} {dm.of.get_player_info_with_emoji(
                    row['town_hall_level'],
                    row['barbarian_king_level'],
                    row['archer_queen_level'],
                    row['grand_warden_level'],
                    row['royal_champion_level']
                )}'
            )
            for row in rows
        }
        clan_map_position_by_player = {}
        for member in cw['clan']['members']:
            clan_map_position_by_player[member['tag']] = member['mapPosition']
        cw_member_lines = [''] * len(clan_map_position_by_player)
        for member in cw['clan']['members']:
            cw_member_lines[clan_map_position_by_player[member['tag']] - 1] = (
                f'{clan_map_position_by_player[member['tag']]}) '
                f'{cw_member_info.get(member['tag'], dm.of.to_html(member['name']))}\n'
            )
        text += ''.join(cw_member_lines)
    elif dm.of.war_state(cw) in ['inWar', 'warEnded']:
        text += (
            f'{dm.of.cw_in_war_or_ended(cw)}'
            f'\n'
        )
        clan_map_position_by_player = {}
        for member in cw['clan']['members']:
            clan_map_position_by_player[member['tag']] = member['mapPosition']
        opponent_map_position_by_player = {}
        for member in cw['opponent']['members']:
            opponent_map_position_by_player[member['tag']] = member['mapPosition']
        cw_member_lines = [''] * len(clan_map_position_by_player)
        for member in cw['clan']['members']:
            cw_member_lines[clan_map_position_by_player[member['tag']] - 1] += (
                f'{clan_map_position_by_player[member['tag']]}) '
                f'{dm.of.to_html(member['name'])}: {len(member.get('attacks', []))} / 2\n'
            )
            for attack in member.get('attacks', []):
                if attack['stars'] != 0:
                    cw_member_lines[clan_map_position_by_player[member['tag']] - 1] += (
                        f'{'⭐' * attack['stars']} ({attack['destructionPercentage']}%) '
                        f'➡️ {opponent_map_position_by_player[attack['defenderTag']]}\n'
                    )
                else:
                    cw_member_lines[clan_map_position_by_player[member['tag']] - 1] += (
                        f'{attack['destructionPercentage']}% '
                        f'➡️ {opponent_map_position_by_player[attack['defenderTag']]}\n'
                    )
        text += '\n'.join(cw_member_lines)
    else:
        text += f'Информация о КВ отсутствует\n'
    return text, ParseMode.HTML, None


async def cw_map(dm: DatabaseManager) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    cw = await dm.load_clan_war()
    text = (f'<b>🗺️ Карта КВ</b>\n'
            f'\n')
    if cw is None:
        text += f'Информация о КВ отсутствует\n'
        return text, ParseMode.HTML, None
    if dm.of.war_state(cw) in ['preparation']:
        text += (
            f'{dm.of.cw_preparation(cw)}'
            f'\n'
        )
        rows = await dm.acquired_connection.fetch('''
            SELECT player_tag, player_name, town_hall_level,
                   barbarian_king_level, archer_queen_level, grand_warden_level, royal_champion_level
            FROM player
            WHERE clan_tag = $1
        ''', dm.clan_tag)
        cw_member_info = {
            row['player_tag']: (
                f'{dm.of.to_html(row['player_name'])} {dm.of.get_player_info_with_emoji(
                    row['town_hall_level'],
                    row['barbarian_king_level'],
                    row['archer_queen_level'],
                    row['grand_warden_level'],
                    row['royal_champion_level']
                )}'
            )
            for row in rows
        }
        clan_map_position_by_player = {}
        for member in cw['clan']['members']:
            clan_map_position_by_player[member['tag']] = member['mapPosition']
        cw_member_lines = [''] * len(clan_map_position_by_player)
        for member in cw['clan']['members']:
            cw_member_lines[clan_map_position_by_player[member['tag']] - 1] = (
                f'{clan_map_position_by_player[member['tag']]}) '
                f'{cw_member_info.get(member['tag'], dm.of.to_html(member['name']))}\n'
            )
        text += ''.join(cw_member_lines)
    elif dm.of.war_state(cw) in ['inWar', 'warEnded']:
        text += (
            f'{dm.of.cw_in_war_or_ended(cw)}'
            f'\n'
        )
        clan_map_position_by_player = {}
        for member in cw['clan']['members']:
            clan_map_position_by_player[member['tag']] = member['mapPosition']
        opponent_map_position_by_player = {}
        for member in cw['opponent']['members']:
            opponent_map_position_by_player[member['tag']] = member['mapPosition']
        opponent_member_lines = [''] * len(clan_map_position_by_player)
        for opponent_member in cw['opponent']['members']:
            if opponent_member.get('bestOpponentAttack'):
                best_opponent_attack = opponent_member['bestOpponentAttack']
                if best_opponent_attack['stars'] > 0:
                    opponent_member_lines[opponent_map_position_by_player[opponent_member['tag']] - 1] += (
                        f'{opponent_map_position_by_player[opponent_member['tag']]}) '
                        f'{'⭐' * best_opponent_attack['stars']} '
                        f'({best_opponent_attack['destructionPercentage']}%) '
                        f'⬅️ '
                        f'{clan_map_position_by_player[best_opponent_attack['attackerTag']]}. '
                        f'{dm.of.to_html(dm.load_name(best_opponent_attack['attackerTag']))}'
                    )
                else:
                    opponent_member_lines[opponent_map_position_by_player[opponent_member['tag']] - 1] += (
                        f'{opponent_map_position_by_player[opponent_member['tag']]}) 0%'
                    )
            else:
                opponent_member_lines[opponent_map_position_by_player[opponent_member['tag']] - 1] += (
                    f'{opponent_map_position_by_player[opponent_member['tag']]}) 0%'
                )
        text += '\n'.join(opponent_member_lines)
    else:
        text += f'Информация о КВ отсутствует\n'
    return text, ParseMode.HTML, None


async def cw_status(
        dm: DatabaseManager,
        message: Optional[Message],
        callback_query: Optional[CallbackQuery],
        callback_data: Optional[CWCallbackFactory]
) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>✍🏻 Изменение статуса участия в КВ</b>\n'
        f'\n'
    )
    if callback_data is not None and callback_data.player_tag is not None:
        await dm.acquired_connection.execute('''
            UPDATE player
            SET is_player_set_for_clan_wars = $1
            WHERE clan_tag = $2 and player_tag = $3
        ''', callback_data.is_player_set_for_clan_wars, dm.clan_tag, callback_data.player_tag)
        description = (
            f'Player {dm.load_name_and_tag(callback_data.player_tag)} '
            f'CW status was set to {callback_data.is_player_set_for_clan_wars}'
        )
        await dm.acquired_connection.execute('''
            INSERT INTO action (clan_tag, chat_id, user_id, action_timestamp, description)
            VALUES ($1, $2, $3, CURRENT_TIMESTAMP(0), $4)
        ''', dm.clan_tag, callback_query.message.chat.id, callback_query.from_user.id, description)
    if (message or callback_query.message).chat.type == ChatType.PRIVATE:
        chat_id = await dm.get_main_chat_id()
    else:
        chat_id = (message or callback_query.message).chat.id
    rows = await dm.acquired_connection.fetch('''
        SELECT
            player_tag, player_name, is_player_set_for_clan_wars,
            town_hall_level, barbarian_king_level, archer_queen_level, grand_warden_level, royal_champion_level
        FROM
            player
            JOIN player_bot_user USING (clan_tag, player_tag)
            JOIN bot_user USING (clan_tag, chat_id, user_id)
        WHERE clan_tag = $1 AND is_player_in_clan AND chat_id = $2 AND user_id = $3 AND is_user_in_chat
        ORDER BY
            town_hall_level DESC,
            (barbarian_king_level + archer_queen_level + grand_warden_level + royal_champion_level) DESC,
            player_name
    ''', dm.clan_tag, chat_id, (message or callback_query).from_user.id)
    if len(rows) == 0:
        text += f'В базе данных нет вашего аккаунта'
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text='🔄 Обновить',
                callback_data=CWCallbackFactory(action=Action.change_cw_status).pack())]
        ])
        return text, ParseMode.HTML, keyboard
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f'{'✅' if row['is_player_set_for_clan_wars'] else '❌'} '
                 f'{dm.load_name(row['player_tag'])} {dm.of.get_player_info_with_emoji(
                     row['town_hall_level'],
                     row['barbarian_king_level'],
                     row['archer_queen_level'],
                     row['grand_warden_level'],
                     row['royal_champion_level'])}',
            callback_data=CWCallbackFactory(
                action=Action.change_cw_status,
                player_tag=row['player_tag'],
                is_player_set_for_clan_wars=not row['is_player_set_for_clan_wars']
            ).pack())] for row in rows
    ] + [[InlineKeyboardButton(
              text='🔄 Обновить',
              callback_data=CWCallbackFactory(action=Action.change_cw_status).pack())]
    ])
    return text, ParseMode.HTML, keyboard


async def cw_list(
        dm: DatabaseManager, callback_data: Optional[CWCallbackFactory]
) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    cw_list_ordering = callback_data.cw_list_ordering or CWListOrderding.by_trophies
    if cw_list_ordering == CWListOrderding.by_town_hall_and_heroes:
        rows = await dm.acquired_connection.fetch('''
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
        text = (
            f'<b>📋 Список участников КВ (⬇️ по ТХ и героям)</b>\n'
            f'\n'
        )
        opposite_ordering_button_text = '⬇️ по трофеям'
        opposite_ordering = CWListOrderding.by_trophies
    else:
        rows = await dm.acquired_connection.fetch('''
            SELECT
                player_name, town_hall_level,
                barbarian_king_level, archer_queen_level, grand_warden_level, royal_champion_level
            FROM player
            WHERE clan_tag = $1 AND player.is_player_in_clan AND is_player_set_for_clan_wars
            ORDER BY home_village_trophies DESC
        ''', dm.clan_tag)
        text = (
            f'<b>📋 Список участников КВ (⬇️ по трофеям)</b>\n'
            f'\n'
        )
        opposite_ordering_button_text = '⬇️ по ТХ и героям'
        opposite_ordering = CWListOrderding.by_town_hall_and_heroes
    keyboard = None
    if len(rows) > 0:
        for i, row in enumerate(rows):
            text += (f'{i + 1}) {dm.of.to_html(row['player_name'])} {dm.of.get_player_info_with_emoji(
                row['town_hall_level'],
                row['barbarian_king_level'],
                row['archer_queen_level'],
                row['grand_warden_level'],
                row['royal_champion_level']
            )}\n')
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=opposite_ordering_button_text,
                callback_data=CWCallbackFactory(
                    action=Action.change_cw_list_ordering, cw_list_ordering=opposite_ordering
                ).pack())
        ]])
    else:
        text += 'Список пуст\n'
    return text, ParseMode.HTML, keyboard


async def cw_skips(
        dm: DatabaseManager, message: Message, ping: bool
) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>🙈 Список не проатаковавших в КВ</b>\n'
        f'\n'
    )
    cw = await dm.load_clan_war()
    if cw is None:
        text += 'Информация о КВ отсутствует'
        return text, ParseMode.HTML, None
    if dm.of.war_state(cw) in ['inWar', 'warEnded']:
        text += (
            f'{dm.of.event_datetime(Event.CW, cw['startTime'], cw['endTime'], False)}\n'
            f'\n'
        )
        CWMember = namedtuple(typename='CWMember', field_names='player_tag attacks_spent attacks_limit')
        cw_members = []
        for cw_member in cw['clan']['members']:
            cw_members.append(
                CWMember(player_tag=cw_member['tag'], attacks_spent=len(cw_member.get('attacks', [])), attacks_limit=2)
            )
        text += await dm.print_skips(message, cw_members, ping, attacks_limit=2)
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


@router.message(Command('cw_map'))
async def command_cw_map(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await cw_map(dm)
    await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)


@router.message(Command('cw_status'))
async def command_cw_status(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await cw_status(dm, message, callback_query=None, callback_data=None)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(CWCallbackFactory.filter(F.action == Action.change_cw_status))
async def callback_cw_status(
        callback_query: CallbackQuery, callback_data: CWCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    player_is_linked_to_user = await dm.is_player_linked_to_user(
        callback_data.player_tag, callback_query.message.chat.id, callback_query.from_user.id
    )
    if not user_is_message_owner or (callback_data.player_tag and not player_is_linked_to_user):
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cw_status(
            dm, message=None, callback_query=callback_query, callback_data=callback_data
        )
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback_query.answer()


@router.message(Command('cw_list'))
async def command_cw_list(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await cw_list(dm, callback_data=None)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(CWCallbackFactory.filter(F.action == Action.change_cw_list_ordering))
async def callback_cw_list(
        callback_query: CallbackQuery, callback_data: CWCallbackFactory, dm: DatabaseManager) -> None:
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
    user_can_ping_group_members = await dm.can_user_ping_group_members(message.chat.id, message.from_user.id)
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply(text=f'Эта команда работает только в группах')
    elif not user_can_ping_group_members:
        await message.reply(text=f'Эта команда не работает для вас')
    else:
        text, parse_mode, reply_markup = await cw_skips(dm, message, ping=True)
        await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
