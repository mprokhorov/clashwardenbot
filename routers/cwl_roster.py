import logging
from enum import auto, IntEnum
from typing import Optional

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from magic_filter import F

from database_manager import DatabaseManager

router = Router()


class OutputView(IntEnum):
    cwl_roster_list = auto()
    cwl_roster_choose = auto()
    cwl_roster_details = auto()
    cwl_roster_toggle = auto()


class CWLRosterCallbackFactory(CallbackData, prefix='cwl_roster'):
    output_view: OutputView
    update: bool = False
    player_tag: Optional[str] = None
    page: int = 0


CWL_ROSTER_CHOOSE_PAGE_SIZE = 20


def get_season(dm: DatabaseManager) -> str:
    return dm.of.utc_now().strftime('%Y-%m')


def get_candidate_pages(candidates: dict, page: int) -> tuple[list[tuple], int, int]:
    sorted_entries = sorted(candidates.items(), key=lambda x: x[1].strength, reverse=True)
    page_count = max(1, (len(sorted_entries) + CWL_ROSTER_CHOOSE_PAGE_SIZE - 1) // CWL_ROSTER_CHOOSE_PAGE_SIZE)
    page = min(max(page, 0), page_count - 1)
    page_entries = sorted_entries[page * CWL_ROSTER_CHOOSE_PAGE_SIZE:(page + 1) * CWL_ROSTER_CHOOSE_PAGE_SIZE]
    return page_entries, page, page_count


async def cwl_roster_list(
        dm: DatabaseManager, callback_data: Optional[CWLRosterCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    season = get_season(dm)
    text = (
        f'<b>🗓️ Составы ЛВК</b>\n'
        f'\n'
    )
    roster_clan_tags = await dm.get_cwl_roster_clan_tags()
    if len(roster_clan_tags) == 0:
        text += f'Ни один клан семейства не настроен для ЛВК\n'
        return text, ParseMode.HTML, None
    candidates = await dm.get_cwl_roster_candidates(season)
    rosters, extra_player_tags = await dm.get_cwl_rosters(season)
    included_amount = sum(candidate.is_included for candidate in candidates.values())
    roster_size = dm.CWL_ROSTER_SIZE + dm.CWL_ROSTER_SUBSTITUTES
    text += (
        f'Сезон: {dm.of.season(season, False)}\n'
        f'Участников: {included_amount}\n'
        f'Составов: {len(rosters)} '
        f'(по {dm.CWL_ROSTER_SIZE} + {dm.CWL_ROSTER_SUBSTITUTES} замены)\n'
        f'\n'
    )
    if len(rosters) == 0:
        text += (
            f'Участников не хватает даже на один состав: '
            f'нужно минимум {roster_size}\n'
            f'\n'
        )
    for roster in rosters:
        war_league = f' — {roster.war_league_name}' if roster.war_league_name is not None else ''
        text += f'<b>{dm.of.to_html(dm.clan_name[roster.clan_tag])}{war_league}</b>\n'
        for i, player_tag in enumerate(roster.members):
            text += (
                f'{i + 1}. {dm.load_name_html(player_tag)} '
                f'(ТХ{candidates[player_tag].town_hall_level})\n'
            )
        if len(roster.substitutes) > 0:
            text += f'Замены: ' + ', '.join(
                f'{dm.load_name_html(player_tag)} (ТХ{candidates[player_tag].town_hall_level})'
                for player_tag in roster.substitutes
            ) + '\n'
        text += '\n'
    if len(extra_player_tags) > 0:
        text += (
            f'<b>Не попали в составы ({len(extra_player_tags)})</b>\n' +
            ', '.join(
                f'{dm.load_name_html(player_tag)} (ТХ{candidates[player_tag].town_hall_level})'
                for player_tag in extra_player_tags
            ) + '\n'
        )
    members_button = InlineKeyboardButton(
        text='📋 Участники',
        callback_data=CWLRosterCallbackFactory(output_view=OutputView.cwl_roster_choose).pack()
    )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWLRosterCallbackFactory(output_view=OutputView.cwl_roster_list, update=True).pack()
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[members_button, update_button]])
    return text, ParseMode.HTML, keyboard


async def cwl_roster_choose(
        dm: DatabaseManager, callback_data: Optional[CWLRosterCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    season = get_season(dm)
    text = (
        f'<b>🗓️ Участники ЛВК</b>\n'
        f'\n'
    )
    candidates = await dm.get_cwl_roster_candidates(season)
    if len(candidates) == 0:
        text += f'Список пуст\n'
        return text, ParseMode.HTML, None
    included_amount = sum(candidate.is_included for candidate in candidates.values())
    page = callback_data.page if callback_data is not None else 0
    page_entries, page, page_count = get_candidate_pages(candidates, page)
    text += (
        f'Сезон: {dm.of.season(season, False)}\n'
        f'Участников: {included_amount} из {len(candidates)}\n'
        f'\n'
        f'Нажмите на игрока, чтобы добавить его в список или убрать из него:'
    )
    button_rows = [[
        InlineKeyboardButton(
            text=(
                f'{'✅' if candidate.is_included else '❌'} {dm.load_name(player_tag)}: '
                f'ТХ{candidate.town_hall_level}, {dm.of.format_and_rstrip(candidate.strength, 2)}'
            ),
            callback_data=CWLRosterCallbackFactory(
                output_view=OutputView.cwl_roster_toggle, player_tag=player_tag, page=page
            ).pack()
        )] for player_tag, candidate in page_entries
    ]
    navigation_row = []
    if page > 0:
        navigation_row.append(InlineKeyboardButton(
            text='⬅️ Назад',
            callback_data=CWLRosterCallbackFactory(
                output_view=OutputView.cwl_roster_choose, page=page - 1
            ).pack()
        ))
    if page < page_count - 1:
        navigation_row.append(InlineKeyboardButton(
            text='➡️ Вперёд',
            callback_data=CWLRosterCallbackFactory(
                output_view=OutputView.cwl_roster_choose, page=page + 1
            ).pack()
        ))
    if len(navigation_row) > 0:
        button_rows.append(navigation_row)
    button_rows.append([
        InlineKeyboardButton(
            text='⬅️ К составам',
            callback_data=CWLRosterCallbackFactory(output_view=OutputView.cwl_roster_list).pack()
        ),
        InlineKeyboardButton(
            text='🔄 Обновить',
            callback_data=CWLRosterCallbackFactory(
                output_view=OutputView.cwl_roster_choose, page=page, update=True
            ).pack()
        )
    ])
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


async def cwl_roster_details(
        dm: DatabaseManager, callback_data: CWLRosterCallbackFactory
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    season = get_season(dm)
    candidates = await dm.get_cwl_roster_candidates(season)
    candidate = candidates.get(callback_data.player_tag)
    text = (
        f'<b>🗓️ Оценка игрока {dm.load_name_html(callback_data.player_tag)}</b>\n'
        f'\n'
    )
    if candidate is None:
        text += f'Игрок не найден среди участников кланов семейства\n'
        return text, ParseMode.HTML, None
    text += (
        f'Сезон: {dm.of.season(season, False)}\n'
        f'В списке: {'✅' if candidate.is_included else '❌'}\n'
        f'\n'
        f'Оценка: {dm.of.format_and_rstrip(candidate.strength, 3)}\n'
        f'Потенциал: {dm.of.format_and_rstrip(candidate.potential, 3)}\n'
        f'Ратуша: {candidate.town_hall_level}\n'
        f'Герои: {dm.of.format_and_rstrip(candidate.hero_levels_progress * 100, 1)}%\n'
        f'Снаряжение: {dm.of.format_and_rstrip(candidate.hero_equipment_progress * 100, 1)}%\n'
    )
    if candidate.cwl_attacks > 0:
        text += (
            f'\n'
            f'Атак в прошлом ЛВК: {candidate.cwl_attacks} ⚔️\n'
            f'Среднее количество звёзд: '
            f'{dm.of.format_and_rstrip(candidate.cwl_average_new_stars, 2)} ⭐\n'
        )
    else:
        text += (
            f'\n'
            f'Атак в прошлом ЛВК нет, оценка только по прокачке\n'
        )
    back_button = InlineKeyboardButton(
        text='⬅️ Назад',
        callback_data=CWLRosterCallbackFactory(
            output_view=OutputView.cwl_roster_choose, page=callback_data.page
        ).pack()
    )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWLRosterCallbackFactory(
            output_view=OutputView.cwl_roster_details, player_tag=callback_data.player_tag,
            page=callback_data.page, update=True
        ).pack()
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[back_button, update_button]])
    return text, ParseMode.HTML, keyboard


@router.message(Command('cwl_roster'))
async def command_cwl_roster(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await cwl_roster_list(dm, None)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(CWLRosterCallbackFactory.filter(F.output_view == OutputView.cwl_roster_list))
async def callback_cwl_roster_list(
        callback_query: CallbackQuery, callback_data: CWLRosterCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = callback_data.update or await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cwl_roster_list(dm, callback_data)
        try:
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        except TelegramBadRequest as e:
            logging.info(f'cwl_roster edit_text failed: {e}')
    if callback_data.update:
        await callback_query.answer('Сообщение обновлено')
    else:
        await callback_query.answer()


@router.callback_query(CWLRosterCallbackFactory.filter(F.output_view == OutputView.cwl_roster_choose))
async def callback_cwl_roster_choose(
        callback_query: CallbackQuery, callback_data: CWLRosterCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = callback_data.update or await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cwl_roster_choose(dm, callback_data)
        try:
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        except TelegramBadRequest as e:
            logging.info(f'cwl_roster edit_text failed: {e}')
    if callback_data.update:
        await callback_query.answer('Сообщение обновлено')
    else:
        await callback_query.answer()


@router.callback_query(CWLRosterCallbackFactory.filter(F.output_view == OutputView.cwl_roster_details))
async def callback_cwl_roster_details(
        callback_query: CallbackQuery, callback_data: CWLRosterCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = callback_data.update or await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cwl_roster_details(dm, callback_data)
        try:
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        except TelegramBadRequest as e:
            logging.info(f'cwl_roster edit_text failed: {e}')
    if callback_data.update:
        await callback_query.answer('Сообщение обновлено')
    else:
        await callback_query.answer()


@router.callback_query(CWLRosterCallbackFactory.filter(F.output_view == OutputView.cwl_roster_toggle))
async def callback_cwl_roster_toggle(
        callback_query: CallbackQuery, callback_data: CWLRosterCallbackFactory, dm: DatabaseManager
) -> None:
    if not await dm.is_user_message_owner(callback_query.message, callback_query.from_user):
        await callback_query.answer('Эта кнопка не работает для вас')
        return
    chat_id = await dm.get_group_chat_id(callback_query.message)
    if not await dm.can_user_edit_cw_list(chat_id, callback_query.from_user.id):
        await callback_query.answer('Вы не можете изменять список участников ЛВК')
        return
    season = get_season(dm)
    candidates = await dm.get_cwl_roster_candidates(season)
    candidate = candidates.get(callback_data.player_tag)
    if candidate is None:
        await callback_query.answer('Игрок не найден')
        return
    await dm.set_cwl_roster_member(season, callback_data.player_tag, not candidate.is_included)
    text, parse_mode, reply_markup = await cwl_roster_choose(dm, callback_data)
    try:
        await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        logging.info(f'cwl_roster edit_text failed: {e}')
    if candidate.is_included:
        await callback_query.answer(f'{dm.load_name(callback_data.player_tag)} убран из списка')
    else:
        await callback_query.answer(f'{dm.load_name(callback_data.player_tag)} добавлен в список')
