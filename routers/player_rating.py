import logging
import math
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
    player_rating_list = auto()
    player_rating_choose = auto()
    player_rating_details = auto()


class PlayerRatingCallbackFactory(CallbackData, prefix='player_rating'):
    output_view: OutputView
    update: bool = False
    season: Optional[str] = None
    player_tag: Optional[str] = None
    eligible_only: bool = True
    page: int = 0
    show_chances: bool = False


PLAYER_RATING_CHOOSE_PAGE_SIZE = 20


async def get_season_toggle_button(
        dm: DatabaseManager, output_view: OutputView, season: str, eligible_only: bool,
        player_tag: Optional[str] = None, show_chances: bool = False
) -> Optional[InlineKeyboardButton]:
    current_season = dm.of.utc_now().strftime('%Y-%m')
    if season == current_season:
        previous_season = dm.of.previous_season(season)
        if await dm.get_player_ratings(previous_season):
            return InlineKeyboardButton(
                text='⬅️ Прошлый месяц',
                callback_data=PlayerRatingCallbackFactory(
                    output_view=output_view, season=previous_season, player_tag=player_tag,
                    eligible_only=eligible_only, show_chances=show_chances
                ).pack()
            )
        return None
    else:
        return InlineKeyboardButton(
            text='➡️ Текущий месяц',
            callback_data=PlayerRatingCallbackFactory(
                output_view=output_view, season=current_season, player_tag=player_tag,
                eligible_only=eligible_only, show_chances=show_chances
            ).pack()
        )


def get_player_rating_pages(player_ratings: dict, page: int) -> tuple[list[tuple], int, int]:
    sorted_entries = sorted(player_ratings.items(), key=lambda x: x[1].total_points, reverse=True)
    page_count = max(1, (len(sorted_entries) + PLAYER_RATING_CHOOSE_PAGE_SIZE - 1) // PLAYER_RATING_CHOOSE_PAGE_SIZE)
    page = min(max(page, 0), page_count - 1)
    page_entries = sorted_entries[page * PLAYER_RATING_CHOOSE_PAGE_SIZE:(page + 1) * PLAYER_RATING_CHOOSE_PAGE_SIZE]
    return page_entries, page, page_count


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
    current_season = dm.of.utc_now().strftime('%Y-%m')
    if callback_data is not None and callback_data.season is not None:
        season = callback_data.season
    else:
        season = current_season
    eligible_only = callback_data.eligible_only if callback_data is not None else True
    show_chances = callback_data.show_chances if callback_data is not None else False
    title = 'Рейтинг игроков (только допущенные к розыгрышу)' if eligible_only else 'Рейтинг игроков (все игроки)'
    text = (
        f'<b>💎 {title}</b>\n'
        f'\n'
    )
    player_ratings = await dm.get_player_ratings(season)
    if eligible_only:
        player_ratings = {player_tag: r for player_tag, r in player_ratings.items() if r.is_eligible_for_prize}
    else:
        player_ratings = {player_tag: r for player_tag, r in player_ratings.items() if r.total_points != 0}
    sorted_entries = sorted(player_ratings.items(), key=lambda x: x[1].total_points, reverse=True)
    if eligible_only and show_chances and len(sorted_entries) > 0:
        points_list = [r.total_points for _, r in sorted_entries]
        mean = sum(points_list) / len(points_list)
        std_dev = math.sqrt(sum((x - mean) ** 2 for x in points_list) / len(points_list)) if len(points_list) > 1 else 1.0
        if std_dev == 0:
            std_dev = 1.0
        weights = {tag: math.exp((r.total_points - mean) / std_dev) for tag, r in sorted_entries}
        total_weight = sum(weights.values())
        chances = {tag: w / total_weight * 100 for tag, w in weights.items()}
    else:
        chances = {}
    text += (
        f'Сезон: {dm.of.season(season, False)}\n'
        f'\n'
    )
    for i, (player_tag, r) in enumerate(sorted_entries):
        chance_str = f' ({dm.of.format_and_rstrip(chances[player_tag], 1)}%)' if chances else ''
        text += f'{i + 1}. {dm.load_name_html(player_tag)}: {dm.of.format_and_rstrip(r.total_points, 3)} 💎{chance_str}\n'
    if len(player_ratings) == 0:
        text += f'Список пуст\n'
    details_button = InlineKeyboardButton(
        text='📋 Подробнее',
        callback_data=PlayerRatingCallbackFactory(
            output_view=OutputView.player_rating_choose, season=season, eligible_only=eligible_only
        ).pack()
    )
    toggle_eligible_only_button = InlineKeyboardButton(
        text='👥 Показать всех' if eligible_only else '✅ Только допущенные',
        callback_data=PlayerRatingCallbackFactory(
            output_view=OutputView.player_rating_list, season=season, eligible_only=not eligible_only
        ).pack()
    )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=PlayerRatingCallbackFactory(
            output_view=OutputView.player_rating_list, season=season, eligible_only=eligible_only,
            show_chances=show_chances, update=True
        ).pack()
    )
    button_upper_row = [details_button, toggle_eligible_only_button]
    bottom_row = [update_button]
    season_toggle_button = await get_season_toggle_button(
        dm, OutputView.player_rating_list, season, eligible_only, show_chances=show_chances
    )
    if season_toggle_button is not None:
        bottom_row.append(season_toggle_button)
    inline_keyboard = [button_upper_row]
    if eligible_only:
        show_chances_button = InlineKeyboardButton(
            text='🎲 Скрыть шансы' if show_chances else '🎲 Показать шансы',
            callback_data=PlayerRatingCallbackFactory(
                output_view=OutputView.player_rating_list, season=season, eligible_only=eligible_only,
                show_chances=not show_chances
            ).pack()
        )
        inline_keyboard.append([show_chances_button])
    inline_keyboard.append(bottom_row)
    keyboard = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
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
    current_season = dm.of.utc_now().strftime('%Y-%m')
    if callback_data is not None and callback_data.season is not None:
        season = callback_data.season
    else:
        season = current_season
    eligible_only = callback_data.eligible_only if callback_data is not None else True
    requested_page = callback_data.page if callback_data is not None else 0
    title = 'Рейтинг игроков (только допущенные к розыгрышу)' if eligible_only else 'Рейтинг игроков (все игроки)'
    text = (
        f'<b>💎 {title}</b>\n'
        f'\n'
    )
    player_ratings = await dm.get_player_ratings(season)
    if eligible_only:
        player_ratings = {player_tag: r for player_tag, r in player_ratings.items() if r.is_eligible_for_prize}
    else:
        player_ratings = {player_tag: r for player_tag, r in player_ratings.items() if r.total_points != 0}
    page_entries, page, page_count = get_player_rating_pages(player_ratings, requested_page)
    text += (
        f'Сезон: {dm.of.season(season, False)}\n'
        f'\n'
        f'Выберите игрока'
        f'{f" (страница {page + 1} из {page_count})" if page_count > 1 else ""}:'
    )
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
    if len(player_ratings) == 0:
        text += f'\nСписок пуст'
    back_button = InlineKeyboardButton(
        text='⬅️ Назад',
        callback_data=PlayerRatingCallbackFactory(
            output_view=OutputView.player_rating_list, season=season, eligible_only=eligible_only
        ).pack()
    )
    toggle_eligible_only_button = InlineKeyboardButton(
        text='👥 Показать всех' if eligible_only else '✅ Только допущенные',
        callback_data=PlayerRatingCallbackFactory(
            output_view=OutputView.player_rating_choose, season=season, eligible_only=not eligible_only
        ).pack()
    )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=PlayerRatingCallbackFactory(
            output_view=OutputView.player_rating_choose, season=season, eligible_only=eligible_only, page=page, update=True
        ).pack()
    )
    bottom_row = [back_button, toggle_eligible_only_button, update_button]
    season_toggle_button = await get_season_toggle_button(dm, OutputView.player_rating_choose, season, eligible_only)
    if season_toggle_button is not None:
        bottom_row.append(season_toggle_button)
    button_rows.append(bottom_row)
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
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


async def player_rating_details(
        dm: DatabaseManager, callback_data: PlayerRatingCallbackFactory
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>💎 Рейтинг игрока {dm.load_name_html(callback_data.player_tag)}</b>\n'
        f'\n'
    )
    if not await dm.load_player_rating_config():
        text += f'Рейтинг выключен'
        return text, ParseMode.HTML, None
    current_season = dm.of.utc_now().strftime('%Y-%m')
    if callback_data.season is not None:
        season = callback_data.season
    else:
        season = current_season
    player_ratings = await dm.get_player_ratings(season)
    r = player_ratings[callback_data.player_tag]
    text += (
        f'Сезон: {dm.of.season(season, False)}\n'
        f'\n'
        f'Итого очков: {dm.of.format_and_rstrip(r.total_points, 3)} 💎\n'
        f'Допуск к розыгрышу: {"✅" if r.is_eligible_for_prize else "❌"}\n'
        f'\n'
    )
    if r.cwl_total_wars > 0:
        average_cwl_stars = r.cwl_total_stars / r.cwl_total_wars
        if r.cwl_minimum_wars is not None and r.cwl_minimum_average_stars is not None:
            text += (
                f'Войн ЛВК: {r.cwl_total_wars} ⚔️ / {r.cwl_minimum_wars} ⚔️\n'
                f'Среднее количество звёзд: '
                f'{dm.of.format_and_rstrip(average_cwl_stars, 1)} ⭐ / '
                f'{dm.of.format_and_rstrip(r.cwl_minimum_average_stars, 1)} ⭐\n'
            )
        else:
            text += f'Войн ЛВК: {r.cwl_total_wars} ⚔️\n'
        text += (
            f'\n'
            f'Очков за ЛВК: {dm.of.format_and_rstrip(r.total_cwl_points, 3)} 💎 ({r.cwl_total_stars} ⭐)\n'
            f'\n'
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
        text += f'\n'
    if len(r.raids_total_attacks) > 0:
        attacks_text = ', '.join(f'{attacks} 🗡️' for attacks in r.raids_total_attacks)
        gold_text = ', '.join(f'{dm.of.separate_thousands(round(gold))} 🟡' for gold in r.raids_total_gold)
        text += (
            f'Очков за рейды: {dm.of.format_and_rstrip(r.total_raids_points, 3)} 💎 '
            f'({dm.of.format_and_rstrip(r.total_raids_gold_points, 3)} 💎 + '
            f'{dm.of.format_and_rstrip(r.total_raids_attack_points, 3)} 💎)\n'
            f'Атак: {attacks_text}\n'
            f'Золота: {gold_text}\n'
            f'\n'
        )
    if len(r.cw_total_attacks) > 0:
        wars_with_one_attack = sum(1 for attacks in r.cw_total_attacks if attacks == 1)
        wars_without_attacks = sum(1 for attacks in r.cw_total_attacks if attacks == 0)
        text += (
            f'Штрафы за КВ: {dm.of.format_and_rstrip(r.total_cw_penalty_points, 3)} 💎\n'
            f'Войн с 1 атакой: {wars_with_one_attack} ⚔️, войн без атак: {wars_without_attacks} ⚔️\n'
        )
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
    bottom_row = [back_button, update_button]
    season_toggle_button = await get_season_toggle_button(
        dm, OutputView.player_rating_details, season, callback_data.eligible_only, player_tag=callback_data.player_tag
    )
    if season_toggle_button is not None:
        bottom_row.append(season_toggle_button)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[bottom_row])
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
    user_is_message_owner = callback_data.update or await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await player_rating_list(dm, callback_data)
        try:
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        except TelegramBadRequest as e:
            logging.info(f'player_rating edit_text failed: {e}')
    if callback_data.update:
        await callback_query.answer('Сообщение обновлено')
    else:
        await callback_query.answer()


@router.callback_query(PlayerRatingCallbackFactory.filter(F.output_view == OutputView.player_rating_choose))
async def callback_player_rating_choose(
        callback_query: CallbackQuery, callback_data: PlayerRatingCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = callback_data.update or await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await player_rating_choose(dm, callback_data)
        try:
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        except TelegramBadRequest as e:
            logging.info(f'player_rating edit_text failed: {e}')
    if callback_data.update:
        await callback_query.answer('Сообщение обновлено')
    else:
        await callback_query.answer()


@router.callback_query(PlayerRatingCallbackFactory.filter(F.output_view == OutputView.player_rating_details))
async def callback_player_rating_details(
        callback_query: CallbackQuery, callback_data: PlayerRatingCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = callback_data.update or await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await player_rating_details(dm, callback_data)
        try:
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        except TelegramBadRequest as e:
            logging.info(f'player_rating edit_text failed: {e}')
    if callback_data.update:
        await callback_query.answer('Сообщение обновлено')
    else:
        await callback_query.answer()
