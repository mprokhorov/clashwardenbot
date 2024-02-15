from typing import Tuple, Optional

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup
from database_manager import DatabaseManager

router = Router()


async def members(dm: DatabaseManager) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    rows = await dm.req_connection.fetch('''
        SELECT
            player_name, town_hall_level,
            barbarian_king_level, archer_queen_level, grand_warden_level, royal_champion_level
        FROM dev.player
        WHERE clan_tag = $1 AND is_player_in_clan
        ORDER BY
            town_hall_level DESC,
            (barbarian_king_level + archer_queen_level + grand_warden_level + royal_champion_level) DESC
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
        FROM dev.player
        WHERE clan_tag = $1 AND is_player_in_clan
        ORDER BY donations_given DESC
        LIMIT 20
    ''', dm.clan_tag)
    text = (f'<b>🥇 Лучшие жертвователи</b>\n'
            f'\n')
    for i, row in enumerate(rows):
        text += (f'{i + 1}) {dm.of.to_html(row['player_name'])}, {dm.of.role(row['player_role'])} — '
                 f'🪖 {row['donations_given']}\n')
    text += f'\n'
    rows = await dm.req_connection.fetch('''
        SELECT player_name, donations_given
        FROM dev.player
        WHERE clan_tag = $1 AND is_player_in_clan AND player_role = 'admin' AND player_tag NOT IN
            (SELECT player_tag
            FROM dev.player
            WHERE clan_tag = $1 AND is_player_in_clan AND player_role NOT IN ('coLeader', 'leader')
            ORDER BY donations_given DESC
            LIMIT 10)
        ORDER BY donations_given, player_name
    ''', dm.clan_tag)
    text += (f'⬇️ Будут понижены: ' + (
        ', '.join(
            f'{dm.of.to_html(row['player_name'])} — 🪖 {row['donations_given']}'
            for row in rows)) if len(rows) != 0 else '') + (f'\n'
                                                            f'\n')
    rows = await dm.req_connection.fetch('''
        SELECT player_name, donations_given
        FROM dev.player
        WHERE  clan_tag = $1 AND is_player_in_clan AND player_role = 'member' AND player_tag IN
            (SELECT player_tag
            FROM dev.player
            WHERE clan_tag = $1 AND is_player_in_clan AND player_role NOT IN ('coLeader', 'leader')
            ORDER BY donations_given DESC
            LIMIT 10)
        ORDER BY donations_given, player_name
    ''', dm.clan_tag)
    text += (f'⬆️ Будут повышены: ' + (
        ', '.join(
            f'{dm.of.to_html(row['player_name'])} — 🪖 {row['donations_given']}'
            for row in rows)) if len(rows) != 0 else '') + f'\n'
    return text, ParseMode.HTML, None


async def contributions(dm: DatabaseManager) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    rows = await dm.req_connection.fetch('''
        SELECT player_tag, gold_amount, contribution_timestamp
        FROM dev.capital_contribution
        ORDER BY contribution_timestamp DESC
        LIMIT 20
    ''')
    text = (f'<b>🤝 Вклады в столице</b>\n'
            f'\n')
    for i, row in enumerate(rows):
        text += (f'{dm.of.to_html(dm.load_name(row['player_tag']))} — {row['gold_amount']} 🟡 '
                 f'{dm.of.shortest_datetime(row['contribution_timestamp'])}\n')
    if len(rows) == 0:
        text += f'Список пуст'
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
