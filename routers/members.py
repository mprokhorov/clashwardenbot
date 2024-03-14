import enum
from collections import namedtuple
from contextlib import suppress
from textwrap import dedent
from typing import Tuple, Optional

from aiogram import Router
from aiogram.enums import ParseMode, ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import Message, InlineKeyboardMarkup, CallbackQuery, Chat, InlineKeyboardButton
from magic_filter import F

from database_manager import DatabaseManager
from output_formatter.output_formatter import Event

router = Router()


class Action(enum.IntEnum):
    change_members_view = 1


class MembersView(enum.IntEnum):
    members = 1
    users = 2


class MembersCallbackFactory(CallbackData, prefix='members'):
    action: Action
    members_view: Optional[MembersView] = None


async def start_help(dm: DatabaseManager) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    row = await dm.acquired_connection.fetchrow('''
        SELECT clan_name
        FROM clan
        WHERE clan_tag = $1
    ''', dm.clan_tag)
    clan_name = row['clan_name']
    text = f'''
        Привет! Этот бот был создан специально для клана <b>{dm.of.to_html(clan_name)}.</b>
        
        Для использования бота необходимо состоять в Telegram-группе клана.
        
        Список доступных команд:
        /cw_info — 📃 Информация о КВ
        /cw_map — 🗺️ Карта КВ
        /cw_attacks — 🗡️ Атаки в КВ
        /cw_skips — 🙈 Список не проатаковавших в КВ
        /cw_ping — 🔔 Напомнить об атаках в КВ
        /cw_status — ✍🏻 Изменить статус участия в КВ
        /cw_list — 📋 Список участников КВ
        /raids_info — 📃 Информация о рейдах
        /raids_loot — 🟡 Полученное золото в рейдах
        /raids_skips — 🙈 Список не проатаковавших в рейдах
        /raids_ping — 🔔 Напомнить об атаках в рейдах
        /raids_analysis — 📊 Анализ атак в рейдах
        /cwl_info — 📃 Информация о ЛВК
        /cwl_map — 🗺️ Карта ЛВК
        /cwl_attacks — 🗡️ Атаки в ЛВК
        /cwl_skips — 🙈 Список не проатаковавших в ЛВК
        /cwl_ping — 🔔 Напомнить об атаках в ЛВК
        /cwl_clans — 📊 Уровни ТХ кланов в ЛВК
        /player_info — 👤 Аккаунты пользователя
        /members — 👥 Участники клана
        /donations — 🥇 Лучшие жертвователи
        /contributions — 🤝 Вклады в столице
        /events — 📅 События
        /admin — ⚙️ Панель управления
    '''
    return dedent(text), ParseMode.HTML, None


async def members(dm: DatabaseManager) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    rows = await dm.acquired_connection.fetch('''
        SELECT
            player_name, town_hall_level,
            barbarian_king_level, archer_queen_level, grand_warden_level, royal_champion_level
        FROM player
        WHERE clan_tag = $1 AND is_player_in_clan
        ORDER BY
            town_hall_level DESC,
            (barbarian_king_level + archer_queen_level + grand_warden_level + royal_champion_level) DESC,
            player_name
    ''', dm.clan_tag)
    text = (f'<b>👥 Участники клана</b>\n'
            f'\n'
            f'Количество участников: {len(rows)} / 50 👤\n'
            f'\n')
    for i, row in enumerate(rows):
        text += (f'{i + 1}) {dm.of.to_html(row['player_name'])} — '
                 f'{dm.of.get_player_info_for_callback_text(
                     row['town_hall_level'],
                     row['barbarian_king_level'],
                     row['archer_queen_level'],
                     row['grand_warden_level'],
                     row['royal_champion_level'])}\n')
    if len(rows) == 0:
        text += f'Список пуст\n'
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='👥 Показать пользователей',
                             callback_data=MembersCallbackFactory(
                                 action=Action.change_members_view,
                                 members_view=MembersView.users
                             ).pack())
    ]])
    return text, ParseMode.HTML, keyboard


async def users(dm: DatabaseManager, chat: Chat) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    if chat.type == ChatType.PRIVATE:
        chat_id = await dm.get_main_chat_id()
    else:
        chat_id = chat.id
    rows = await dm.acquired_connection.fetch('''
        SELECT
            bot_user.user_id,
            player.player_tag, town_hall_level,
            barbarian_king_level, archer_queen_level, grand_warden_level, royal_champion_level
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
    ''', dm.clan_tag, chat_id)
    players_by_user = {user_id: [] for user_id in [row['user_id'] for row in rows]}
    ClanMember = namedtuple(
        typename='ClanMember',
        field_names='player_tag town_hall_level '
                    'barbarian_king_level archer_queen_level grand_warden_level royal_champion_level')
    for row in rows:
        players_by_user[row['user_id']].append(ClanMember(
            row['player_tag'], row['town_hall_level'],
            row['barbarian_king_level'], row['archer_queen_level'],
            row['grand_warden_level'], row['royal_champion_level']
        ))
    rows = await dm.acquired_connection.fetch('''
        SELECT user_id, first_name, last_name
        FROM bot_user
        WHERE clan_tag = $1 AND chat_id = $2 AND is_user_in_chat AND user_id NOT IN (
            SELECT bot_user.user_id
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
        )
        ORDER BY first_name, last_name
    ''', dm.clan_tag, chat_id)
    users_without_players = [row['user_id'] for row in rows]
    rows = await dm.acquired_connection.fetch('''
        SELECT player_tag
        FROM player
        WHERE clan_tag = $1 AND is_player_in_clan AND player.player_tag NOT IN (
            SELECT player.player_tag
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
        )
        ORDER BY player_name
    ''', dm.clan_tag, chat_id)
    players_without_users = [row['player_tag'] for row in rows]
    members_number = await dm.acquired_connection.fetchval('''
        SELECT COUNT(*)
        FROM player
        WHERE clan_tag = $1 AND is_player_in_clan
    ''', dm.clan_tag)
    text = (
        f'<b>👥 Участники клана</b>\n'
        f'\n'
        f'Количество участников: {members_number} / 50 👤\n'
        f'\n'
    )
    if len(players_by_user) > 0:
        text += '<b>Аккаунты пользователей:</b>\n'
    for user_id, players in sorted(
            players_by_user.items(),
            key=lambda item: sum(value.town_hall_level for value in item[1]),
            reverse=True
    ):
        text += (
            f'👤 {dm.of.to_html(dm.load_full_name(chat_id, user_id))} — '
            f'{', '.join('🪖 ' + dm.of.to_html(dm.load_name(player.player_tag)) for player in players)}\n'
        )
    if len(players_by_user) > 0:
        text += '\n'
    if len(players_without_users) > 0:
        text += (
            f'<b>Неизвестные аккаунты:</b>\n'
            f'{'\n'.join('🪖 ' + dm.of.to_html(dm.load_name(player_tag)) for player_tag in players_without_users)}\n'
            f'\n'
        )
    if len(users_without_players) > 0:
        text += (
            f'<b>Неизвестные пользователи:</b>\n'
            f'{'\n'.join(
                '👤 ' + dm.of.to_html(dm.load_full_name(chat_id, user_id)) for user_id in users_without_players
            )}\n'
        )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text='👥 Показать игроков',
            callback_data=MembersCallbackFactory(
                action=Action.change_members_view, members_view=MembersView.members
            ).pack()
        )
    ]])
    return text, ParseMode.HTML, keyboard


async def donations(dm: DatabaseManager) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    rows = await dm.acquired_connection.fetch('''
        SELECT player_name, player_role, donations_given
        FROM player
        WHERE clan_tag = $1 AND is_player_in_clan
        ORDER BY donations_given DESC
        LIMIT 20
    ''', dm.clan_tag)
    text = (f'<b>🥇 Лучшие жертвователи</b>\n'
            f'\n')
    for i, row in enumerate(rows):
        text += (f'{i + 1}) {dm.of.to_html(row['player_name'])}, {dm.of.role(row['player_role'])} — '
                 f'🪖 {row['donations_given']}\n')

    rows = await dm.acquired_connection.fetch('''
        SELECT player_name, donations_given
        FROM player
        WHERE clan_tag = $1 AND is_player_in_clan AND player_role = 'admin' AND player_tag NOT IN
            (SELECT player_tag
            FROM player
            WHERE clan_tag = $1 AND is_player_in_clan AND player_role NOT IN ('coLeader', 'leader')
            ORDER BY donations_given DESC
            LIMIT 10)
        ORDER BY donations_given, player_name
    ''', dm.clan_tag)
    if len(rows) == 1:
        text += (f'\n'
                 f'⬇️ Будет понижен: {dm.of.to_html(rows[0]['player_name'])} — 🪖 {rows[0]['donations_given']}\n')
    elif len(rows) > 1:
        text += (f'\n'
                 f'⬇️ Будут понижены: {', '.join(f'{dm.of.to_html(row['player_name'])} — 🪖 {row['donations_given']}'
                                                 for row in rows)}\n')

    rows = await dm.acquired_connection.fetch('''
        SELECT player_name, donations_given
        FROM player
        WHERE clan_tag = $1 AND is_player_in_clan AND player_role = 'member' AND player_tag IN
            (SELECT player_tag
            FROM player
            WHERE clan_tag = $1 AND is_player_in_clan AND player_role NOT IN ('coLeader', 'leader')
            ORDER BY donations_given DESC
            LIMIT 10)
        ORDER BY donations_given, player_name
    ''', dm.clan_tag)
    if len(rows) == 1:
        text += (f'\n'
                 f'⬇️ Будет повышен: {dm.of.to_html(rows[0]['player_name'])} — 🪖 {rows[0]['donations_given']}\n')
    elif len(rows) > 1:
        text += (f'\n'
                 f'⬇️ Будут повышены: {', '.join(f'{dm.of.to_html(row['player_name'])} — 🪖 {row['donations_given']}'
                                                 for row in rows)}\n')
    return text, ParseMode.HTML, None


async def contributions(dm: DatabaseManager) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    rows = await dm.acquired_connection.fetch('''
        SELECT player_tag, gold_amount, contribution_timestamp
        FROM capital_contribution
        WHERE clan_tag = $1
        ORDER BY contribution_timestamp DESC
        LIMIT 20
    ''', dm.clan_tag)
    text = (f'<b>🤝 Вклады в столице</b>\n'
            f'\n')
    for i, row in enumerate(rows):
        text += (f'{dm.of.to_html(dm.load_name(row['player_tag']))} — '
                 f'{row['gold_amount']} {dm.of.get_capital_gold_emoji()} '
                 f'{dm.of.shortest_datetime(row['contribution_timestamp'])}\n')
    if len(rows) == 0:
        text += f'Список пуст'
    return text, ParseMode.HTML, None


async def player_info(dm: DatabaseManager,
                      message: Message) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        if message.reply_to_message:
            chat_id = message.chat.id
            user_id = message.reply_to_message.from_user.id
        else:
            chat_id = message.chat.id
            user_id = message.from_user.id
    elif message.chat.type == ChatType.PRIVATE:
        chat_id = await dm.get_main_chat_id()
        user_id = message.from_user.id
    else:
        text = (f'<b>📋 Аккаунт пользователя</b>\n'
                f'\n'
                f'Эта команда не работает для вас\n')
        return text, ParseMode.HTML, None
    rows = await dm.acquired_connection.fetch('''
        SELECT
            player_name, player.player_tag, is_player_set_for_clan_wars,
            barbarian_king_level, archer_queen_level, grand_warden_level, royal_champion_level,
            town_hall_level, builder_hall_level, home_village_trophies, builder_base_trophies,
            player_role
        FROM
            player
            JOIN player_bot_user
                ON player.clan_tag = player_bot_user.clan_tag
                AND player.player_tag = player_bot_user.player_tag
                AND player.clan_tag = $1
                AND is_player_in_clan
            JOIN bot_user
                ON player_bot_user.clan_tag = bot_user.clan_tag
                AND player_bot_user.chat_id = bot_user.chat_id
                AND player_bot_user.user_id = bot_user.user_id
                AND bot_user.is_user_in_chat
                AND (bot_user.chat_id, bot_user.user_id) = ($2, $3)
        ORDER BY
            town_hall_level DESC,
            (barbarian_king_level + archer_queen_level + grand_warden_level + royal_champion_level) DESC,
            player_name
    ''', dm.clan_tag, chat_id, user_id)
    if len(rows) > 1:
        text = (f'<b>📋 Аккаунты пользователя</b>\n'
                f'\n')
    else:
        text = (f'<b>📋 Аккаунт пользователя</b>\n'
                f'\n')
    for row in rows:
        text += (f'<b>{dm.of.to_html(row['player_name'])}</b>, {dm.of.role(row['player_role'])}\n'
                 f'Статус участия в КВ: {'✅' if row['is_player_set_for_clan_wars'] else '❌'}\n'
                 f'{dm.of.get_player_info_with_custom_emoji(
                     row['town_hall_level'],
                     row['barbarian_king_level'],
                     row['archer_queen_level'],
                     row['grand_warden_level'],
                     row['royal_champion_level']
                 )}\n'
                 f'\n')
    if len(rows) == 0:
        text += f'Список пуст\n'
    return text, ParseMode.HTML, None


async def events(dm: DatabaseManager) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (f'<b>📅 События</b>\n'
            f'\n')
    datetimes_and_lines = [(
        dm.of.get_next_trader_refresh(),
        f'{dm.of.event_datetime(Event.TR, None, None, False, dm.of.get_next_trader_refresh())}\n'
        f'\n'
    ), (
        dm.of.get_next_season_end(),
        f'{dm.of.event_datetime(Event.SE, None, None, False, dm.of.get_next_season_end())}\n'
        f'\n'
    ), (
        dm.of.get_event_datetime(*dm.of.get_next_cwl()),
        f'{dm.of.event_datetime(Event.CWL, *map(dm.of.from_datetime, dm.of.get_next_cwl()), False)}\n'
        f'\n'
    ), (
        dm.of.get_event_datetime(*dm.of.get_next_clan_games()),
        f'{dm.of.event_datetime(Event.CG, *map(dm.of.from_datetime, dm.of.get_next_clan_games()), False)}\n'
        f'\n'
    ), (
        dm.of.get_next_league_reset(),
        f'{dm.of.event_datetime(Event.LR, None, None, False, dm.of.get_next_league_reset())}\n'
        f'\n'
    ), (
        dm.of.get_event_datetime(*dm.of.get_next_raid_weekend()),
        f'{dm.of.event_datetime(Event.RW, *map(dm.of.from_datetime, dm.of.get_next_raid_weekend()), False)}\n'
        f'\n'
    )]
    datetimes_and_lines.sort(key=lambda item: item[0])
    text += ''.join(line for datetime, line in datetimes_and_lines)
    return text, ParseMode.HTML, None


@router.message(Command('start'))
@router.message(Command('help'))
async def commands_start_help(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await start_help(dm)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.message(Command('members'))
async def command_members(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await members(dm)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(MembersCallbackFactory.filter(F.action == Action.change_members_view))
async def callback_members(callback_query: CallbackQuery,
                           callback_data: MembersCallbackFactory,
                           dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        if callback_data.members_view == MembersView.users:
            text, parse_mode, reply_markup = await users(dm, callback_query.message.chat)
        else:
            text, parse_mode, reply_markup = await members(dm)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback_query.answer()


@router.message(Command('donations'))
async def command_donations(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await donations(dm)
    await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)


@router.message(Command('contributions'))
async def command_contributions(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await contributions(dm)
    await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)


@router.message(Command('player_info'))
async def command_player_info(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await player_info(dm, message)
    await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)


@router.message(Command('events'))
async def command_events(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await events(dm)
    await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
