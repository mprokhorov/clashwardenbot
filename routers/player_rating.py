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


async def get_season_toggle_button(
        dm: DatabaseManager, output_view: OutputView, season: str, player_tag: Optional[str] = None
) -> Optional[InlineKeyboardButton]:
    current_season = dm.of.utc_now().strftime('%Y-%m')
    if season == current_season:
        previous_season = dm.of.previous_season(season)
        if await dm.get_player_ratings(previous_season):
            return InlineKeyboardButton(
                text='⬅️ Прошлый месяц',
                callback_data=PlayerRatingCallbackFactory(
                    output_view=output_view, season=previous_season, player_tag=player_tag
                ).pack()
            )
        return None
    else:
        return InlineKeyboardButton(
            text='➡️ Текущий месяц',
            callback_data=PlayerRatingCallbackFactory(
                output_view=output_view, season=current_season, player_tag=player_tag
            ).pack()
        )


async def player_rating_list(
        dm: DatabaseManager, callback_data: Optional[PlayerRatingCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>💎 Рейтинг игроков (только допущенные к розыгрышу)</b>\n'
        f'\n'
    )
    if not await dm.load_player_rating_config():
        text += f'Рейтинг выключен'
        return text, ParseMode.HTML, None
    current_season = dm.of.utc_now().strftime('%Y-%m')
    if callback_data is not None and callback_data.season is not None:
        season = callback_data.season
    else:
        season = current_season
    player_ratings = await dm.get_player_ratings(season)
    player_ratings = {player_tag: r for player_tag, r in player_ratings.items() if r.is_eligible_for_prize}
    text += (
        f'Сезон: {dm.of.season(season, False)}\n'
        f'\n'
    )
    for i, (player_tag, r) in enumerate(sorted(player_ratings.items(), key=lambda x: x[1].total_points, reverse=True)):
        text += f'{i + 1}. {dm.load_name(player_tag)}: {dm.of.format_and_rstrip(r.total_points, 3)} 💎\n'
    if len(player_ratings) == 0:
        text += f'Список пуст\n'
    details_button = InlineKeyboardButton(
        text='📋 Подробнее',
        callback_data=PlayerRatingCallbackFactory(output_view=OutputView.player_rating_choose, season=season).pack()
    )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=PlayerRatingCallbackFactory(output_view=OutputView.player_rating_list, season=season, update=True).pack()
    )
    button_upper_row = [details_button]
    season_toggle_button = await get_season_toggle_button(dm, OutputView.player_rating_list, season)
    if season_toggle_button is not None:
        button_upper_row.append(season_toggle_button)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[button_upper_row, [update_button]])
    return text, ParseMode.HTML, keyboard


async def player_rating_choose(
        dm: DatabaseManager, callback_data: Optional[PlayerRatingCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>💎 Рейтинг игроков (все игроки)</b>\n'
        f'\n'
    )
    if not await dm.load_player_rating_config():
        text += f'Рейтинг выключен'
        return text, ParseMode.HTML, None
    current_season = dm.of.utc_now().strftime('%Y-%m')
    if callback_data is not None and callback_data.season is not None:
        season = callback_data.season
    else:
        season = current_season
    player_ratings = await dm.get_player_ratings(season)
    text += (
        f'Сезон: {dm.of.season(season, False)}\n'
        f'\n'
        f'Выберите игрока:'
    )
    button_rows = [[
        InlineKeyboardButton(
            text=f'{dm.load_name(player_tag)}: {dm.of.format_and_rstrip(r.total_points, 3)} 💎',
            callback_data=PlayerRatingCallbackFactory(
                output_view=OutputView.player_rating_details, season=season, player_tag=player_tag
            ).pack()
        )] for player_tag, r in sorted(player_ratings.items(), key=lambda x: x[1].total_points, reverse=True)
    ]
    back_button = InlineKeyboardButton(
        text='⬅️ Назад',
        callback_data=PlayerRatingCallbackFactory(output_view=OutputView.player_rating_list, season=season).pack()
    )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=PlayerRatingCallbackFactory(output_view=OutputView.player_rating_choose, season=season, update=True).pack()
    )
    bottom_row = [back_button, update_button]
    season_toggle_button = await get_season_toggle_button(dm, OutputView.player_rating_choose, season)
    if season_toggle_button is not None:
        bottom_row.append(season_toggle_button)
    button_rows.append(bottom_row)
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


async def player_rating_details(
        dm: DatabaseManager, callback_data: PlayerRatingCallbackFactory
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>💎 Рейтинг игрока {dm.load_name(callback_data.player_tag)}</b>\n'
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
        f'\n'
    )
    if r.cwl_total_wars > 0:
        cwl_config = dm.player_rating_config.get(r.cwl_clan_tag)
        text += f'Допуск к розыгрышу: {"✅" if r.is_eligible_for_prize else "❌"}\n'
        average_cwl_stars = r.cwl_total_stars / r.cwl_total_wars
        if cwl_config is not None:
            bracket = min(r.town_hall_difference, len(cwl_config.minimum_average_cwl_stars) - 1)
            text += (
                f'Войн ЛВК: {r.cwl_total_wars} ⚔️ / {cwl_config.minimum_cwl_wars} ⚔️\n'
                f'Среднее количество звёзд: '
                f'{dm.of.format_and_rstrip(average_cwl_stars, 1)} ⭐ / '
                f'{dm.of.format_and_rstrip(cwl_config.minimum_average_cwl_stars[bracket], 1)} ⭐\n'
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
            places_text = ', '.join(f'#{dm.of.format_and_rstrip(place, 1)}' for place in r.leagues_places)
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
        callback_data=PlayerRatingCallbackFactory(output_view=OutputView.player_rating_choose, season=season).pack()
    )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=PlayerRatingCallbackFactory(
            output_view=OutputView.player_rating_details,
            season=season,
            player_tag=callback_data.player_tag,
            update=True
        ).pack()
    )
    bottom_row = [back_button, update_button]
    season_toggle_button = await get_season_toggle_button(
        dm, OutputView.player_rating_details, season, player_tag=callback_data.player_tag
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
