from contextlib import suppress
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
from entities.game_entities import PlayerRating

router = Router()

PLAYER_RATING_CHOOSE_PAGE_SIZE = 20


class OutputView(IntEnum):
    player_rating_list = auto()
    player_rating_choose = auto()
    player_rating_details = auto()
    player_rating_seasons = auto()


class PlayerRatingCallbackFactory(CallbackData, prefix='player_rating'):
    output_view: OutputView
    update: bool = False
    season: Optional[str] = None
    player_tag: Optional[str] = None
    eligible_only: Optional[bool] = None
    page: int = 0


def get_display_settings(
        player_ratings: dict[str, PlayerRating], callback_data: Optional[PlayerRatingCallbackFactory]
) -> tuple[bool, bool]:
    any_eligible = any(r.is_eligible_for_prize for r in player_ratings.values())
    if callback_data is not None and callback_data.eligible_only is not None:
        eligible_only = callback_data.eligible_only and any_eligible
    else:
        eligible_only = any_eligible
    return eligible_only, any_eligible


def filter_player_ratings(player_ratings: dict[str, PlayerRating], eligible_only: bool) -> dict[str, PlayerRating]:
    if eligible_only:
        return {player_tag: r for player_tag, r in player_ratings.items() if r.is_eligible_for_prize}
    return {player_tag: r for player_tag, r in player_ratings.items() if r.total_points != 0}


async def get_season_buttons_row(
        dm: DatabaseManager, output_view: OutputView, season: str, eligible_only: Optional[bool]
) -> list[InlineKeyboardButton]:
    seasons = await dm.get_player_rating_seasons()
    previous_season = max((s for s in seasons if s < season), default=None)
    next_season = min((s for s in seasons if s > season), default=None)
    season_buttons_row = []
    if previous_season is not None:
        season_buttons_row.append(InlineKeyboardButton(
            text=f'⬅️ {dm.of.season(previous_season, False).capitalize()}',
            callback_data=PlayerRatingCallbackFactory(
                output_view=output_view, season=previous_season, eligible_only=eligible_only
            ).pack()
        ))
    if next_season is not None:
        season_buttons_row.append(InlineKeyboardButton(
            text=f'➡️ {dm.of.season(next_season, False).capitalize()}',
            callback_data=PlayerRatingCallbackFactory(
                output_view=output_view, season=next_season, eligible_only=eligible_only
            ).pack()
        ))
    season_buttons_row.append(InlineKeyboardButton(
        text='🧾 Все сезоны',
        callback_data=PlayerRatingCallbackFactory(
            output_view=OutputView.player_rating_seasons, season=season, eligible_only=eligible_only
        ).pack()
    ))
    return season_buttons_row


def get_requested_season(dm: DatabaseManager, callback_data: Optional[PlayerRatingCallbackFactory]) -> str:
    if callback_data is not None and callback_data.season is not None:
        return callback_data.season
    return dm.of.utc_now().strftime('%Y-%m')


async def player_rating_list(
        dm: DatabaseManager, callback_data: Optional[PlayerRatingCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    if not await dm.load_player_rating_config():
        text = (
            f'<b>💎 Рейтинг игроков</b>\n'
            f'\n'
            f'Рейтинг выключен'
        )
        return text, ParseMode.HTML, None
    season = get_requested_season(dm, callback_data)
    player_ratings = await dm.get_player_ratings(season)
    eligible_only, any_eligible = get_display_settings(player_ratings, callback_data)
    shown_player_ratings = filter_player_ratings(player_ratings, eligible_only)
    title = 'Рейтинг игроков (только допущенные к розыгрышу)' if eligible_only else 'Рейтинг игроков (все игроки)'
    text = (
        f'<b>💎 {title}</b>\n'
        f'\n'
        f'Сезон: {dm.of.season(season, False)}\n'
        f'\n'
    )
    sorted_entries = sorted(shown_player_ratings.items(), key=lambda x: x[1].total_points, reverse=True)
    for i, (player_tag, r) in enumerate(sorted_entries):
        text += f'{i + 1}. {dm.of.to_html(dm.load_name(player_tag))}: {dm.of.format_and_rstrip(r.total_points, 3)} 💎\n'
    if len(sorted_entries) == 0:
        text += f'Список пуст\n'
    details_button = InlineKeyboardButton(
        text='📋 Подробнее',
        callback_data=PlayerRatingCallbackFactory(
            output_view=OutputView.player_rating_choose, season=season, eligible_only=eligible_only
        ).pack()
    )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=PlayerRatingCallbackFactory(
            output_view=OutputView.player_rating_list, season=season, eligible_only=eligible_only, update=True
        ).pack()
    )
    button_upper_row = [details_button]
    if any_eligible:
        button_upper_row.append(InlineKeyboardButton(
            text='🔽 Развернуть' if eligible_only else '🔼 Свернуть',
            callback_data=PlayerRatingCallbackFactory(
                output_view=OutputView.player_rating_list, season=season, eligible_only=not eligible_only
            ).pack()
        ))
    button_upper_row.append(update_button)
    season_buttons_row = await get_season_buttons_row(dm, OutputView.player_rating_list, season, eligible_only)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[button_upper_row, season_buttons_row])
    return text, ParseMode.HTML, keyboard


async def player_rating_choose(
        dm: DatabaseManager, callback_data: Optional[PlayerRatingCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    if not await dm.load_player_rating_config():
        text = (
            f'<b>💎 Рейтинг игроков</b>\n'
            f'\n'
            f'Рейтинг выключен'
        )
        return text, ParseMode.HTML, None
    season = get_requested_season(dm, callback_data)
    player_ratings = await dm.get_player_ratings(season)
    eligible_only, any_eligible = get_display_settings(player_ratings, callback_data)
    shown_player_ratings = filter_player_ratings(player_ratings, eligible_only)
    requested_page = callback_data.page if callback_data is not None else 0
    sorted_entries = sorted(shown_player_ratings.items(), key=lambda x: x[1].total_points, reverse=True)
    page_count = max(1, (len(sorted_entries) + PLAYER_RATING_CHOOSE_PAGE_SIZE - 1) // PLAYER_RATING_CHOOSE_PAGE_SIZE)
    page = min(max(requested_page, 0), page_count - 1)
    page_entries = sorted_entries[page * PLAYER_RATING_CHOOSE_PAGE_SIZE:(page + 1) * PLAYER_RATING_CHOOSE_PAGE_SIZE]
    title = 'Рейтинг игроков (только допущенные к розыгрышу)' if eligible_only else 'Рейтинг игроков (все игроки)'
    text = (
        f'<b>💎 {title}</b>\n'
        f'\n'
        f'Сезон: {dm.of.season(season, False)}\n'
        f'\n'
        f'Выберите игрока'
        f'{f" (страница {page + 1} из {page_count})" if page_count > 1 else ""}:'
    )
    if len(sorted_entries) == 0:
        text += f'\nСписок пуст'
    button_rows = [[
        InlineKeyboardButton(
            text=f'{dm.load_name(player_tag)}: {dm.of.format_and_rstrip(r.total_points, 3)} 💎',
            callback_data=PlayerRatingCallbackFactory(
                output_view=OutputView.player_rating_details,
                season=season,
                player_tag=player_tag,
                eligible_only=eligible_only,
                page=page
            ).pack()
        )] for player_tag, r in page_entries
    ]
    if page_count > 1:
        page_row = []
        if page > 0:
            page_row.append(InlineKeyboardButton(
                text='◀️ Предыдущая страница',
                callback_data=PlayerRatingCallbackFactory(
                    output_view=OutputView.player_rating_choose, season=season, eligible_only=eligible_only, page=page - 1
                ).pack()
            ))
        if page < page_count - 1:
            page_row.append(InlineKeyboardButton(
                text='▶️ Следующая страница',
                callback_data=PlayerRatingCallbackFactory(
                    output_view=OutputView.player_rating_choose, season=season, eligible_only=eligible_only, page=page + 1
                ).pack()
            ))
        button_rows.append(page_row)
    back_button = InlineKeyboardButton(
        text='⬅️ Назад',
        callback_data=PlayerRatingCallbackFactory(
            output_view=OutputView.player_rating_list, season=season, eligible_only=eligible_only
        ).pack()
    )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=PlayerRatingCallbackFactory(
            output_view=OutputView.player_rating_choose, season=season, eligible_only=eligible_only, page=page, update=True
        ).pack()
    )
    button_row = [back_button]
    if any_eligible:
        button_row.append(InlineKeyboardButton(
            text='🔽 Развернуть' if eligible_only else '🔼 Свернуть',
            callback_data=PlayerRatingCallbackFactory(
                output_view=OutputView.player_rating_choose, season=season, eligible_only=not eligible_only
            ).pack()
        ))
    button_row.append(update_button)
    button_rows.append(button_row)
    button_rows.append(await get_season_buttons_row(dm, OutputView.player_rating_choose, season, eligible_only))
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


async def player_rating_details(
        dm: DatabaseManager, callback_data: PlayerRatingCallbackFactory
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>💎 Рейтинг игрока {dm.of.to_html(dm.load_name(callback_data.player_tag))}</b>\n'
        f'\n'
    )
    if not await dm.load_player_rating_config():
        text += f'Рейтинг выключен'
        return text, ParseMode.HTML, None
    season = get_requested_season(dm, callback_data)
    back_button = InlineKeyboardButton(
        text='⬅️ Назад',
        callback_data=PlayerRatingCallbackFactory(
            output_view=OutputView.player_rating_choose,
            season=season,
            eligible_only=callback_data.eligible_only,
            page=callback_data.page
        ).pack()
    )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=PlayerRatingCallbackFactory(
            output_view=OutputView.player_rating_details,
            season=season,
            player_tag=callback_data.player_tag,
            eligible_only=callback_data.eligible_only,
            page=callback_data.page,
            update=True
        ).pack()
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[back_button, update_button]])
    player_ratings = await dm.get_player_ratings(season)
    r = player_ratings.get(callback_data.player_tag)
    if r is None:
        text += (
            f'Сезон: {dm.of.season(season, False)}\n'
            f'\n'
            f'Данные о рейтинге игрока отсутствуют'
        )
        return text, ParseMode.HTML, keyboard
    text += (
        f'Сезон: {dm.of.season(season, False)}\n'
        f'\n'
        f'Итого очков: {dm.of.format_and_rstrip(r.total_points, 3)} 💎\n'
        f'\n'
        f'Допуск к розыгрышу: {"✅" if r.is_eligible_for_prize else "❌"}\n'
    )
    if r.cwl_total_wars > 0:
        average_cwl_stars = r.cwl_total_stars / r.cwl_total_wars
        if r.cwl_minimum_wars is not None:
            text += f'Войн ЛВК: {r.cwl_total_wars} ⚔️ / {r.cwl_minimum_wars} ⚔️\n'
            if r.cwl_minimum_average_stars is not None:
                text += (
                    f'Среднее количество звёзд: '
                    f'{dm.of.format_and_rstrip(average_cwl_stars, 1)} ⭐ / '
                    f'{dm.of.format_and_rstrip(r.cwl_minimum_average_stars, 1)} ⭐\n'
                )
        else:
            text += f'Войн ЛВК: {r.cwl_total_wars} ⚔️\n'
        text += (
            f'\n'
            f'Очков за ЛВК: {dm.of.format_and_rstrip(r.total_cwl_points, 3)} 💎 ({r.cwl_total_stars} ⭐)\n'
        )
    if len(r.league_numbers) > 0:
        league_day_counts = {}
        for league_tier in r.league_numbers:
            league_day_counts[league_tier] = league_day_counts.get(league_tier, 0) + 1
        leagues_text = ', '.join(
            f'{dm.of.league_name(league_tier)} — {dm.of.get_days_in_russian(count)}'
            for league_tier, count in league_day_counts.items()
        )
        text += (
            f'\n'
            f'Очков за лигу: {dm.of.format_and_rstrip(r.total_league_points + r.total_place_points, 3)} 💎 '
            f'({dm.of.format_and_rstrip(r.total_league_points, 3)} 💎 + '
            f'{dm.of.format_and_rstrip(r.total_place_points, 3)} 💎)\n'
            f'Дней в лигах: {leagues_text}\n'
        )
        if len(r.leagues_places) > 0:
            places_text = ', '.join(
                f'#{start}' if start == end else f'#{start}-{end}' for start, end in r.leagues_places
            )
            text += f'Места в клане: {places_text}\n'
    if len(r.raids_total_attacks) > 0:
        attacks_text = ', '.join(f'{attacks} 🗡️' for attacks in r.raids_total_attacks)
        gold_text = ', '.join(f'{dm.of.separate_thousands(round(gold))} 🟡' for gold in r.raids_total_gold)
        text += (
            f'\n'
            f'Очков за рейды: {dm.of.format_and_rstrip(r.total_raids_points, 3)} 💎 '
            f'({dm.of.format_and_rstrip(r.total_raids_gold_points, 3)} 💎 + '
            f'{dm.of.format_and_rstrip(r.total_raids_attack_points, 3)} 💎)\n'
            f'Атак: {attacks_text}\n'
            f'Золота: {gold_text}\n'
        )
    if len(r.cw_total_attacks) > 0:
        wars_with_one_attack = sum(1 for attacks in r.cw_total_attacks if attacks == 1)
        wars_without_attacks = sum(1 for attacks in r.cw_total_attacks if attacks == 0)
        text += (
            f'\n'
            f'Штрафы за КВ: {dm.of.format_and_rstrip(r.total_cw_penalty_points, 3)} 💎\n'
            f'Войн с 1 атакой: {wars_with_one_attack} ⚔️, войн без атак: {wars_without_attacks} ⚔️\n'
        )
    return text, ParseMode.HTML, keyboard


async def player_rating_seasons(
        dm: DatabaseManager, callback_data: PlayerRatingCallbackFactory
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    if not await dm.load_player_rating_config():
        text = (
            f'<b>💎 Рейтинг игроков</b>\n'
            f'\n'
            f'Рейтинг выключен'
        )
        return text, ParseMode.HTML, None
    text = (
        f'<b>💎 Рейтинг игроков</b>\n'
        f'\n'
        f'Выберите сезон:\n'
    )
    seasons = await dm.get_player_rating_seasons()
    button_rows = [[
        InlineKeyboardButton(
            text=dm.of.season(season, False).capitalize(),
            callback_data=PlayerRatingCallbackFactory(
                output_view=OutputView.player_rating_list, season=season, eligible_only=callback_data.eligible_only
            ).pack()
        )] for season in seasons[::-1]
    ]
    if len(seasons) == 0:
        text += f'Список пуст\n'
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=PlayerRatingCallbackFactory(
            output_view=OutputView.player_rating_seasons,
            season=callback_data.season,
            eligible_only=callback_data.eligible_only,
            update=True
        ).pack()
    )
    button_rows.append([update_button])
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


@router.message(Command('player_rating'))
async def command_player_rating(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await player_rating_list(dm, None)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(PlayerRatingCallbackFactory.filter(F.output_view == OutputView.player_rating_list))
async def callback_player_rating_list(
        callback_query: CallbackQuery, callback_data: PlayerRatingCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await player_rating_list(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    if callback_data.update:
        await callback_query.answer('Сообщение обновлено')
    else:
        await callback_query.answer()


@router.callback_query(PlayerRatingCallbackFactory.filter(F.output_view == OutputView.player_rating_choose))
async def callback_player_rating_choose(
        callback_query: CallbackQuery, callback_data: PlayerRatingCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await player_rating_choose(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    if callback_data.update:
        await callback_query.answer('Сообщение обновлено')
    else:
        await callback_query.answer()


@router.callback_query(PlayerRatingCallbackFactory.filter(F.output_view == OutputView.player_rating_details))
async def callback_player_rating_details(
        callback_query: CallbackQuery, callback_data: PlayerRatingCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await player_rating_details(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    if callback_data.update:
        await callback_query.answer('Сообщение обновлено')
    else:
        await callback_query.answer()


@router.callback_query(PlayerRatingCallbackFactory.filter(F.output_view == OutputView.player_rating_seasons))
async def callback_player_rating_seasons(
        callback_query: CallbackQuery, callback_data: PlayerRatingCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await player_rating_seasons(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    if callback_data.update:
        await callback_query.answer('Сообщение обновлено')
    else:
        await callback_query.answer()
