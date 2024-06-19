from contextlib import suppress
from enum import auto, IntEnum
from typing import Optional

from aiogram import Router
from aiogram.enums import ParseMode, ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from magic_filter import F

from database_manager import DatabaseManager
from entities import RaidsMember, RaidsAttack

router = Router()


class OutputView(IntEnum):
    raids_info = auto()
    raids_attacks = auto()
    raids_skips = auto()
    raids_analysis = auto()


class RaidsCallbackFactory(CallbackData, prefix='raids'):
    output_view: OutputView
    update: bool = False


async def raids_info(dm: DatabaseManager) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>⚔️ Информация о рейдах</b>\n'
        f'\n'
    )
    button_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=RaidsCallbackFactory(output_view=OutputView.raids_info, update=True).pack()
    )
    raids = await dm.load_raid_weekend()
    if dm.of.state(raids) in ['ongoing', 'ended']:
        text += dm.of.raids_ongoing_or_ended(raids)
        button_row.append(update_button)
    else:
        text += 'Информация о рейдах отсутствует\n'
        button_row.append(update_button)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[button_row])
    return text, ParseMode.HTML, keyboard


async def raids_attacks(dm: DatabaseManager) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>🗡️ Атаки в рейдах</b>\n'
        f'\n'
    )
    button_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=RaidsCallbackFactory(output_view=OutputView.raids_attacks, update=True).pack()
    )
    raids = await dm.load_raid_weekend()
    if dm.of.state(raids) in ['ongoing', 'ended']:
        raids_members = []
        for raids_member in raids['members']:
            raids_members.append(
                RaidsMember(
                    player_tag=raids_member['tag'],
                    attacks_spent=raids_member['attacks'],
                    attacks_limit=raids_member['attackLimit'] + raids_member['bonusAttackLimit'],
                    gold_looted=raids_member['capitalResourcesLooted'])
            )
        if dm.of.state(raids) in ['ended']:
            rows = await dm.acquired_connection.fetch('''
                SELECT player_tag
                FROM player
                WHERE
                    clan_tag = $1
                    AND is_player_in_clan
                    AND (first_seen < $2 OR (SELECT MIN(first_seen) FROM player WHERE clan_tag = $1) > $2)
                    AND NOT (player_tag = any($3::varchar[]))
            ''', dm.clan_tag, dm.of.to_datetime(raids['endTime']), [
                raids_member.player_tag for raids_member in raids_members
            ])
            for row in rows:
                raids_members.append(
                    RaidsMember(player_tag=row['player_tag'], attacks_spent=0, attacks_limit=6, gold_looted=0)
                )
        raids_members.sort(
            key=lambda raids_member_: (-raids_member_.gold_looted, dm.load_name(raids_member_.player_tag))
        )
        text += (
            f'{dm.of.raids_ongoing_or_ended(raids)}'
            f'\n'
        )
        for i, raids_member in enumerate(raids_members):
            text += (
                f'{i + 1}. {dm.of.to_html(dm.load_name(raids_member.player_tag))}: '
                f'{raids_member.gold_looted} {dm.of.get_capital_gold_emoji()} '
                f'({raids_member.attacks_spent} / {raids_member.attacks_limit})\n'
            )
        if len(raids_members) == 0:
            text += f'Список пуст\n'
        button_row.append(update_button)
    else:
        text += 'Информация о рейдах отсутствует\n'
        button_row.append(update_button)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[button_row])
    return text, ParseMode.HTML, keyboard


async def raids_skips(dm: DatabaseManager, chat_id: int) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>🕒 Не проатаковавшие в рейдах</b>\n'
        f'\n'
    )
    button_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=RaidsCallbackFactory(output_view=OutputView.raids_skips, update=True).pack()
    )
    raids = await dm.load_raid_weekend()
    if dm.of.state(raids) in ['ongoing', 'ended']:
        raids_members = []
        for raids_member in raids['members']:
            raids_members.append(
                RaidsMember(
                    player_tag=raids_member['tag'],
                    attacks_spent=raids_member['attacks'],
                    attacks_limit=raids_member['attackLimit'] + raids_member['bonusAttackLimit']
                )
            )
        rows = await dm.acquired_connection.fetch('''
            SELECT player_tag
            FROM player
            WHERE
                clan_tag = $1
                AND is_player_in_clan
                AND (first_seen < $2 OR (SELECT MIN(first_seen) FROM player WHERE clan_tag = $1) > $2)
                AND NOT (player_tag = any($3::varchar[]))
        ''', dm.clan_tag, dm.of.to_datetime(raids['endTime']), [
            raids_member.player_tag for raids_member in raids_members
        ])
        for row in rows:
            raids_members.append(
                RaidsMember(player_tag=row['player_tag'], attacks_spent=0, attacks_limit=6)
            )
        text += (
            f'{dm.of.raids_ongoing_or_ended(raids)}'
            f'\n'
        )
        text += await dm.skips(chat_id=chat_id, players=raids_members, ping=False, attacks_limit=5)
        button_row.append(update_button)
    else:
        text += 'Информация о рейдах отсутствует\n'
        button_row.append(update_button)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[button_row])
    return text, ParseMode.HTML, keyboard


async def raids_ping(dm: DatabaseManager, chat_id: int) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>🔔 Напоминание об атаках в рейдах</b>\n'
        f'\n'
    )
    raids = await dm.load_raid_weekend()
    if dm.of.state(raids) in ['ongoing', 'ended']:
        raids_members = []
        for raids_member in raids['members']:
            raids_members.append(
                RaidsMember(
                    player_tag=raids_member['tag'],
                    attacks_spent=raids_member['attacks'],
                    attacks_limit=raids_member['attackLimit'] + raids_member['bonusAttackLimit']
                )
            )
        rows = await dm.acquired_connection.fetch('''
            SELECT player_tag
            FROM player
            WHERE
                clan_tag = $1
                AND is_player_in_clan
                AND (first_seen < $2 OR (SELECT MIN(first_seen) FROM player WHERE clan_tag = $1) > $2)
                AND NOT (player_tag = any($3::varchar[]))
        ''', dm.clan_tag, dm.of.to_datetime(raids['endTime']), [
            raids_member.player_tag for raids_member in raids_members
        ])
        for row in rows:
            raids_members.append(
                RaidsMember(player_tag=row['player_tag'], attacks_spent=0, attacks_limit=6)
            )
        text += (
            f'{dm.of.raids_ongoing_or_ended(raids)}'
            f'\n'
        )
        text += await dm.skips(chat_id=chat_id, players=raids_members, ping=True, attacks_limit=6)
    else:
        text += 'Информация о рейдах отсутствует\n'
    return text, ParseMode.HTML, None


async def raids_analysis(dm: DatabaseManager) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    raids = await dm.load_raid_weekend()
    text = (
        f'<b>📊 Анализ атак в рейдах</b>\n'
        f'\n'
    )
    button_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=RaidsCallbackFactory(output_view=OutputView.raids_analysis, update=True).pack()
    )
    if dm.of.state(raids) in ['ongoing', 'ended']:
        text += (
            f'{dm.of.raids_ongoing_or_ended(raids)}'
            f'\n'
        )
        clan_attacks_by_district = {}
        for attack_log in raids['attackLog']:
            for district in attack_log['districts']:
                if district['destructionPercent'] != 100:
                    continue
                attack_count = district['attackCount']
                if attack_count > 1:
                    average_destruction = district['attacks'][1]['destructionPercent'] / (attack_count - 1)
                else:
                    average_destruction = 100.0
                if district['name'] not in clan_attacks_by_district.keys():
                    clan_attacks_by_district[district['name']] = []
                clan_attacks_by_district[district['name']].append(
                    RaidsAttack(attack_count, average_destruction, district)
                )

        for district_name, district_attacks in clan_attacks_by_district.items():
            text += f'<b>{dm.of.district(district_name)}</b>\n'
            district_best_by_destruction = sorted(
                district_attacks,
                key=lambda district_attack_: (district_attack_.attacks_count, -district_attack_.average_destruction)
            )[0].district
            text += (
                f'👍 Лучшее уничтожение '
                f'({dm.of.attacks_count_to_text(len(district_best_by_destruction['attacks']))})\n'
            )
            for district_attack in district_best_by_destruction['attacks'][::-1]:
                if district_attack['stars'] == 0:
                    text += (
                        f'{dm.of.to_html(district_attack['attacker']['name'])}: '
                        f'{district_attack['destructionPercent']}%\n'
                    )
                else:
                    text += (
                        f'{dm.of.to_html(district_attack['attacker']['name'])}: '
                        f'{'⭐' * district_attack['stars']} ({district_attack['destructionPercent']}%)\n'
                    )
            district_worst_by_destruction = sorted(
                district_attacks,
                key=lambda district_attack_: (district_attack_.attacks_count, -district_attack_.average_destruction)
            )[-1].district
            text += (
                f'👎 Худшее уничтожение '
                f'({dm.of.attacks_count_to_text(len(district_worst_by_destruction['attacks']))})\n'
            )
            for district_attack in district_worst_by_destruction['attacks'][::-1]:
                if district_attack['stars'] == 0:
                    text += (
                        f'{dm.of.to_html(district_attack['attacker']['name'])}: '
                        f'{district_attack['destructionPercent']}%\n'
                    )
                else:
                    text += (
                        f'{dm.of.to_html(district_attack['attacker']['name'])}: '
                        f'{'⭐' * district_attack['stars']} ({district_attack['destructionPercent']}%)\n'
                    )
            text += f'\n'
        if len(clan_attacks_by_district) == 0:
            text += f'Список пуст\n'
        button_row.append(update_button)
    else:
        text += 'Информация о рейдах отсутствует\n'
        button_row.append(update_button)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[button_row])
    return text, ParseMode.HTML, keyboard


@router.message(Command('raids_info'))
async def command_raids_info(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await raids_info(dm)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(RaidsCallbackFactory.filter(F.output_view == OutputView.raids_info))
async def callback_raids_info(
        callback_query: CallbackQuery, callback_data: RaidsCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await raids_info(dm)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.message(Command('raids_attacks'))
async def command_raids_attacks(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await raids_attacks(dm)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(RaidsCallbackFactory.filter(F.output_view == OutputView.raids_attacks))
async def callback_raids_attacks(
        callback_query: CallbackQuery, callback_data: RaidsCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await raids_attacks(dm)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.message(Command('raids_skips'))
async def command_raids_skips(message: Message, dm: DatabaseManager) -> None:
    chat_id = await dm.get_group_chat_id(message)
    text, parse_mode, reply_markup = await raids_skips(dm, chat_id)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(RaidsCallbackFactory.filter(F.output_view == OutputView.raids_skips))
async def callback_raids_skips(
        callback_query: CallbackQuery, callback_data: RaidsCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        chat_id = await dm.get_group_chat_id(callback_query.message)
        text, parse_mode, reply_markup = await raids_skips(dm, chat_id)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.message(Command('raids_ping'))
async def command_raids_ping(message: Message, dm: DatabaseManager) -> None:
    user_can_ping_group_members = await dm.can_user_ping_group_members(message.chat.id, message.from_user.id)
    if message.chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await message.reply(text=f'Эта команда работает только в группах')
    elif not user_can_ping_group_members:
        await message.reply(text=f'У вас нет прав на использование этой команды')
    else:
        chat_id = await dm.get_group_chat_id(message)
        text, parse_mode, reply_markup = await raids_ping(dm, chat_id)
        await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)


@router.message(Command('raids_analysis'))
async def command_raids_analysis(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await raids_analysis(dm)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(RaidsCallbackFactory.filter(F.output_view == OutputView.raids_analysis))
async def callback_raids_analysis(
        callback_query: CallbackQuery, callback_data: RaidsCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await raids_analysis(dm)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()
