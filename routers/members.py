from typing import Tuple, Optional

from aiogram import Router
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup
from database_manager import DatabaseManager

router = Router()


async def members(dm: DatabaseManager) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    rows = await dm.req_connection.fetch('''
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
            f'\n')
    for i, row in enumerate(rows):
        text += (f'{i + 1}) {dm.of.to_html(row['player_name'])} — 🛖 {row['town_hall_level']}, '
                 f'👑 {row['barbarian_king_level']} / {row['archer_queen_level']} / '
                 f'{row['grand_warden_level']} / {row['royal_champion_level']}\n')
    if len(rows) == 0:
        text += f'Список пуст\n'
    return text, ParseMode.HTML, None


async def donations(dm: DatabaseManager) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    rows = await dm.req_connection.fetch('''
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

    rows = await dm.req_connection.fetch('''
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

    rows = await dm.req_connection.fetch('''
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
    rows = await dm.req_connection.fetch('''
        SELECT player_tag, gold_amount, contribution_timestamp
        FROM capital_contribution
        WHERE clan_tag = $1
        ORDER BY contribution_timestamp DESC
        LIMIT 20
    ''', dm.clan_tag)
    text = (f'<b>🤝 Вклады в столице</b>\n'
            f'\n')
    for i, row in enumerate(rows):
        text += (f'{dm.of.to_html(dm.load_name(row['player_tag']))} — {row['gold_amount']} 🟡 '
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
        row = await dm.req_connection.fetchrow('''
            SELECT chat_id
            FROM clan_chat
            WHERE clan_tag = $1 AND is_chat_main
        ''', dm.clan_tag)
        chat_id = row['chat_id'] if row else None
        user_id = message.from_user.id
    else:
        text = (f'<b>📋 Аккаунт пользователя в игре</b>\n'
                f'\n'
                f'Эта команда не работает для вас\n')
        return text, ParseMode.HTML, None
    rows = await dm.req_connection.fetch('''
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
        text = (f'<b>📋 Аккаунты пользователя в игре</b>\n'
                f'\n')
    else:
        text = (f'<b>📋 Аккаунт пользователя в игре</b>\n'
                f'\n')
    for row in rows:
        text += (f'<b>{dm.of.to_html(row['player_name'])} ({row['player_tag']})</b>\n'
                 f'Звание: {dm.of.role(row['player_role'])}\n'
                 f'Статус участия в КВ: {'✅' if row['is_player_set_for_clan_wars'] else '❌'}\n'
                 f'Уровни героев: {row['barbarian_king_level']} / {row['archer_queen_level']} / '
                 f'{row['grand_warden_level']} / {row['royal_champion_level']}\n'
                 f'Родная деревня: {row['town_hall_level']} 🛖 {row['home_village_trophies']} 🏆\n'
                 f'Деревня строителя: {row['builder_hall_level']} 🛖 {row['builder_base_trophies']} 🔨\n'
                 f'\n')
    if len(rows) == 0:
        text += f'Список пуст\n'
    return text, ParseMode.HTML, None


@router.message(Command('members'))
async def cmd_members(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await members(dm)
    await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)


@router.message(Command('donations'))
async def cmd_donations(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await donations(dm)
    await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)


@router.message(Command('contributions'))
async def cmd_contributions(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await contributions(dm)
    await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)


@router.message(Command('player_info'))
async def cmd_player_info(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await player_info(dm, message)
    await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
