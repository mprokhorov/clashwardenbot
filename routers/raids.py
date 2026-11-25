from contextlib import suppress
from datetime import datetime, UTC
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

RAIDS_PAGE_SIZE = 10


class OutputView(IntEnum):
    raids_info = auto()
    raids_attacks = auto()
    raids_skips = auto()
    raids_analysis = auto()
    raids_info_all = auto()
    raids_attacks_all = auto()
    raids_skips_all = auto()
    raids_analysis_all = auto()


class RaidsCallbackFactory(CallbackData, prefix='raids'):
    output_view: OutputView
    update: bool = False
    raid_time: Optional[int] = None
    page: Optional[int] = None


def raid_ts_to_datetime(raid_time: Optional[int]) -> Optional[datetime]:
    if raid_time is None:
        return None
    return datetime.fromtimestamp(raid_time, UTC).replace(tzinfo=None)


def datetime_to_ts(dt: datetime) -> int:
    return int(dt.replace(tzinfo=UTC).timestamp())


def raid_range_date(
        dm: DatabaseManager, start_time: Optional[str], end_time: Optional[str], start_dt: datetime
) -> str:
    if start_time and end_time:
        return dm.of.short_date_range(dm.of.to_datetime(start_time), dm.of.to_datetime(end_time))
    return dm.of.short_date(start_dt)


async def build_raids_nav_row(
        dm: DatabaseManager,
        output_view: OutputView,
        all_output_view: OutputView,
        raids: dict,
        selected_raid_time: Optional[int]
) -> list[InlineKeyboardButton]:
    start_dt = dm.of.to_datetime(raids['startTime'])
    older, newer = await dm.load_adjacent_raid_weekends(start_dt)
    nav_row = []
    if older is not None:
        nav_row.append(InlineKeyboardButton(
            text=f'⬅️ {dm.of.short_date(older["start_time"])}',
            callback_data=RaidsCallbackFactory(
                output_view=output_view,
                raid_time=datetime_to_ts(older['start_time'])
            ).pack()
        ))
    if newer is not None:
        nav_row.append(InlineKeyboardButton(
            text=f'➡️ {dm.of.short_date(newer["start_time"])}',
            callback_data=RaidsCallbackFactory(
                output_view=output_view,
                raid_time=datetime_to_ts(newer['start_time'])
            ).pack()
        ))
    nav_row.append(InlineKeyboardButton(
        text='🧾 Все рейды',
        callback_data=RaidsCallbackFactory(
            output_view=all_output_view,
            raid_time=selected_raid_time
        ).pack()
    ))
    return nav_row


async def raids_info(
        dm: DatabaseManager, callback_data: Optional[RaidsCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    selected_raid_time = callback_data.raid_time if callback_data is not None else None
    text = (
        f'<b>⚔️ Информация о рейдах</b>\n'
        f'\n'
    )
    button_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=RaidsCallbackFactory(
            output_view=OutputView.raids_info, update=True, raid_time=selected_raid_time
        ).pack()
    )
    raids = await dm.load_raid_weekend(raid_ts_to_datetime(selected_raid_time))
    if dm.of.state(raids) in ['ongoing', 'ended']:
        text += dm.of.raids_ongoing_or_ended(raids)
        button_row.append(update_button)
    else:
        text += 'Информация о рейдах отсутствует\n'
        button_row.append(update_button)
    button_rows = [button_row]
    if raids is not None:
        button_rows.append(await build_raids_nav_row(
            dm, OutputView.raids_info, OutputView.raids_info_all, raids, selected_raid_time
        ))
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


async def raids_attacks(
        dm: DatabaseManager, callback_data: Optional[RaidsCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    selected_raid_time = callback_data.raid_time if callback_data is not None else None
    text = (
        f'<b>🗡️ Атаки в рейдах</b>\n'
        f'\n'
    )
    button_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=RaidsCallbackFactory(
            output_view=OutputView.raids_attacks, update=True, raid_time=selected_raid_time
        ).pack()
    )
    raids = await dm.load_raid_weekend(raid_ts_to_datetime(selected_raid_time))
    if dm.of.state(raids) in ['ongoing', 'ended']:
        raids_members = []
        for raids_member in raids.get('members', []):
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
            key=lambda _raids_member: (
                -_raids_member.gold_looted, dm.of.str_sort_key(dm.load_name(_raids_member.player_tag))
            )
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
    button_rows = [button_row]
    if raids is not None:
        button_rows.append(await build_raids_nav_row(
            dm, OutputView.raids_attacks, OutputView.raids_attacks_all, raids, selected_raid_time
        ))
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


async def raids_skips(
        dm: DatabaseManager, callback_data: Optional[RaidsCallbackFactory], chat_id: int
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    selected_raid_time = callback_data.raid_time if callback_data is not None else None
    text = (
        f'<b>🕒 Не проатаковавшие в рейдах</b>\n'
        f'\n'
    )
    button_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=RaidsCallbackFactory(
            output_view=OutputView.raids_skips, update=True, raid_time=selected_raid_time
        ).pack()
    )
    raids = await dm.load_raid_weekend(raid_ts_to_datetime(selected_raid_time))
    if dm.of.state(raids) in ['ongoing', 'ended']:
        raids_members = []
        for raids_member in raids.get('members', []):
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
        text += await dm.skips(chat_id=chat_id, players=raids_members, ping=False, desired_attacks_spent=6)
        button_row.append(update_button)
    else:
        text += 'Информация о рейдах отсутствует\n'
        button_row.append(update_button)
    button_rows = [button_row]
    if raids is not None:
        button_rows.append(await build_raids_nav_row(
            dm, OutputView.raids_skips, OutputView.raids_skips_all, raids, selected_raid_time
        ))
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


async def raids_ping(dm: DatabaseManager, chat_id: int) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>🔔 Напоминание об атаках в рейдах</b>\n'
        f'\n'
    )
    raids = await dm.load_raid_weekend()
    if dm.of.state(raids) in ['ongoing', 'ended']:
        raids_members = []
        for raids_member in raids.get('members', []):
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
        text += await dm.skips(chat_id=chat_id, players=raids_members, ping=True, desired_attacks_spent=5)
    else:
        text += 'Информация о рейдах отсутствует\n'
    return text, ParseMode.HTML, None


async def raids_analysis(
        dm: DatabaseManager, callback_data: Optional[RaidsCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    selected_raid_time = callback_data.raid_time if callback_data is not None else None
    raids = await dm.load_raid_weekend(raid_ts_to_datetime(selected_raid_time))
    text = (
        f'<b>📊 Анализ атак в рейдах</b>\n'
        f'\n'
    )
    button_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=RaidsCallbackFactory(
            output_view=OutputView.raids_analysis, update=True, raid_time=selected_raid_time
        ).pack()
    )
    if dm.of.state(raids) in ['ongoing', 'ended']:
        text += (
            f'{dm.of.raids_ongoing_or_ended(raids)}'
            f'\n'
        )
        clan_attacks_by_district = {}
        for attack_log in raids.get('attackLog', []):
            for district in attack_log.get('districts', []):
                if district.get('destructionPercent') != 100:
                    continue
                attacks = district.get('attacks', [])
                if not attacks:
                    continue
                attack_count = district['attackCount']
                if attack_count > 1 and len(attacks) > 1:
                    average_destruction = attacks[1]['destructionPercent'] / (attack_count - 1)
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
                key=lambda _district_attack: (_district_attack.attacks_count, -_district_attack.average_destruction)
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
                key=lambda _district_attack: (_district_attack.attacks_count, -_district_attack.average_destruction)
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
    button_rows = [button_row]
    if raids is not None:
        button_rows.append(await build_raids_nav_row(
            dm, OutputView.raids_analysis, OutputView.raids_analysis_all, raids, selected_raid_time
        ))
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


async def raids_all_list(
        dm: DatabaseManager, callback_data: RaidsCallbackFactory
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    view_config = {
        OutputView.raids_info_all: ('⚔️ Информация о рейдах', OutputView.raids_info),
        OutputView.raids_attacks_all: ('🗡️ Атаки в рейдах', OutputView.raids_attacks),
        OutputView.raids_skips_all: ('🕒 Не проатаковавшие в рейдах', OutputView.raids_skips),
        OutputView.raids_analysis_all: ('📊 Анализ атак в рейдах', OutputView.raids_analysis)
    }
    title, target_view = view_config[callback_data.output_view]
    raid_weekends, total, page = await dm.load_raid_weekends_page(
        callback_data.page, RAIDS_PAGE_SIZE, target_time=raid_ts_to_datetime(callback_data.raid_time)
    )
    total_pages = max(1, (total + RAIDS_PAGE_SIZE - 1) // RAIDS_PAGE_SIZE)
    if total == 0:
        text = (
            f'<b>{title}</b>\n'
            f'\n'
            f'Информация о рейдах отсутствует\n'
        )
    elif total_pages > 1:
        text = (
            f'<b>{title}</b>\n'
            f'\n'
            f'Выберите рейды (стр. {page + 1} / {total_pages}):\n'
        )
    else:
        text = (
            f'<b>{title}</b>\n'
            f'\n'
            f'Выберите рейды:\n'
        )
    button_rows = []
    for rw in raid_weekends:
        emoji = '🗡' if rw['state'] == 'ongoing' else '⚔️'
        date_str = raid_range_date(dm, rw['startTime'], rw['endTime'], rw['start_time'])
        total_attacks = rw['total_attacks'] or 0
        if rw['state'] == 'ended' and rw['offensive_reward'] is not None and rw['defensive_reward'] is not None:
            medals = rw['offensive_reward'] * 6 + rw['defensive_reward']
            summary = f'{medals} ⚪ ({total_attacks} 🗡)'
        else:
            summary = f'{total_attacks} 🗡'
        button_rows.append([InlineKeyboardButton(
            text=f'{emoji} {date_str} — {summary}',
            callback_data=RaidsCallbackFactory(
                output_view=target_view,
                raid_time=datetime_to_ts(rw['start_time'])
            ).pack()
        )])
    if total_pages > 1:
        pagination_row = []
        if page > 0:
            pagination_row.append(InlineKeyboardButton(
                text=f'⬅️ Стр. {page}',
                callback_data=RaidsCallbackFactory(
                    output_view=callback_data.output_view,
                    raid_time=callback_data.raid_time,
                    page=page - 1
                ).pack()
            ))
        if page < total_pages - 1:
            pagination_row.append(InlineKeyboardButton(
                text=f'➡️ Стр. {page + 2}',
                callback_data=RaidsCallbackFactory(
                    output_view=callback_data.output_view,
                    raid_time=callback_data.raid_time,
                    page=page + 1
                ).pack()
            ))
        button_rows.append(pagination_row)
    back_button = InlineKeyboardButton(
        text='⬅️ Назад',
        callback_data=RaidsCallbackFactory(
            output_view=target_view,
            raid_time=callback_data.raid_time
        ).pack()
    )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=RaidsCallbackFactory(
            output_view=callback_data.output_view,
            update=True,
            raid_time=callback_data.raid_time,
            page=page
        ).pack()
    )
    button_rows.append([back_button, update_button])
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


@router.message(Command('raids_info'))
async def command_raids_info(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await raids_info(dm, None)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(RaidsCallbackFactory.filter(F.output_view == OutputView.raids_info))
async def callback_raids_info(
        callback_query: CallbackQuery, callback_data: RaidsCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner and not callback_data.update:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await raids_info(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.message(Command('raids_attacks'))
async def command_raids_attacks(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await raids_attacks(dm, None)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(RaidsCallbackFactory.filter(F.output_view == OutputView.raids_attacks))
async def callback_raids_attacks(
        callback_query: CallbackQuery, callback_data: RaidsCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner and not callback_data.update:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await raids_attacks(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.message(Command('raids_skips'))
async def command_raids_skips(message: Message, dm: DatabaseManager) -> None:
    chat_id = await dm.get_group_chat_id(message)
    text, parse_mode, reply_markup = await raids_skips(dm, None, chat_id)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(RaidsCallbackFactory.filter(F.output_view == OutputView.raids_skips))
async def callback_raids_skips(
        callback_query: CallbackQuery, callback_data: RaidsCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner and not callback_data.update:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        chat_id = await dm.get_group_chat_id(callback_query.message)
        text, parse_mode, reply_markup = await raids_skips(dm, callback_data, chat_id)
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
    text, parse_mode, reply_markup = await raids_analysis(dm, None)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(RaidsCallbackFactory.filter(F.output_view == OutputView.raids_analysis))
async def callback_raids_analysis(
        callback_query: CallbackQuery, callback_data: RaidsCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner and not callback_data.update:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await raids_analysis(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.callback_query(RaidsCallbackFactory.filter(F.output_view == OutputView.raids_info_all))
@router.callback_query(RaidsCallbackFactory.filter(F.output_view == OutputView.raids_attacks_all))
@router.callback_query(RaidsCallbackFactory.filter(F.output_view == OutputView.raids_skips_all))
@router.callback_query(RaidsCallbackFactory.filter(F.output_view == OutputView.raids_analysis_all))
async def callback_raids_all_list(
        callback_query: CallbackQuery, callback_data: RaidsCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner and not callback_data.update:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await raids_all_list(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()
