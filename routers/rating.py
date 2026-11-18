from contextlib import suppress
from enum import auto, IntEnum
from typing import Optional

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

from database_manager import DatabaseManager
from entities.game_entities import PlayerRating

router = Router()


class OutputView(IntEnum):
    rating_list = auto()
    rating_choose = auto()
    rating_details = auto()
    rating_all_seasons = auto()


class RatingCallbackFactory(CallbackData, prefix='rating'):
    output_view: OutputView
    update: bool = False
    season: Optional[str] = None
    show_all: Optional[bool] = None
    player_tag: Optional[str] = None


def get_shown_ratings(
        player_ratings: dict[str, PlayerRating], show_all: Optional[bool]
) -> tuple[list[PlayerRating], bool, bool]:
    shown_ratings = sorted(
        [r for r in player_ratings.values() if r.is_player_in_family and abs(r.total_points) > 1e-9],
        key=lambda r: (-r.total_points, str.lower(r.player_name), r.player_name)
    )
    has_prize_candidates = any(r.win_chance is not None for r in shown_ratings)
    if show_all is None:
        show_all = not has_prize_candidates
    if not show_all:
        shown_ratings = [r for r in shown_ratings if r.win_chance is not None]
    return shown_ratings, show_all, has_prize_candidates


def get_season_title(dm: DatabaseManager, season: str) -> str:
    return dm.of.season(season, False).capitalize()


async def get_season(dm: DatabaseManager, callback_data: Optional[RatingCallbackFactory]) -> tuple[Optional[str], list[str]]:
    seasons = await dm.get_player_rating_seasons()
    if callback_data is not None and callback_data.season is not None:
        return callback_data.season, seasons
    return (seasons[-1] if len(seasons) > 0 else None), seasons


async def rating_list(
        dm: DatabaseManager, callback_data: Optional[RatingCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>💎 Рейтинг участников клана</b>\n'
        f'\n'
    )
    if not await dm.load_player_rating_config():
        text += f'Рейтинг выключен'
        return text, ParseMode.HTML, None
    season, seasons = await get_season(dm, callback_data)
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=RatingCallbackFactory(output_view=OutputView.rating_list, update=True).pack()
    )
    if season is None:
        text += f'Информация о рейтинге отсутствует\n'
        return text, ParseMode.HTML, InlineKeyboardMarkup(inline_keyboard=[[update_button]])
    player_ratings = await dm.get_player_ratings(season)
    shown_ratings, show_all, has_prize_candidates = get_shown_ratings(
        player_ratings, callback_data.show_all if callback_data is not None else None
    )
    text += (
        f'Сезон: {dm.of.season(season, False)}\n'
        f'\n'
    )
    for i, r in enumerate(shown_ratings):
        text += f'{i + 1}. {dm.of.to_html(r.player_name)}: {dm.of.format_and_rstrip(r.total_points, 3)} 💎'
        if r.win_chance is not None:
            text += f' ({dm.of.format_and_rstrip(r.win_chance * 100, 1)}%)'
        text += '\n'
    if len(shown_ratings) == 0:
        text += f'Список пуст\n'
    button_upper_row = [InlineKeyboardButton(
        text='📋 Подробнее',
        callback_data=RatingCallbackFactory(
            output_view=OutputView.rating_choose, season=season, show_all=show_all
        ).pack()
    )]
    if has_prize_candidates:
        button_upper_row.append(InlineKeyboardButton(
            text='🔼 Свернуть' if show_all else '🔽 Развернуть',
            callback_data=RatingCallbackFactory(
                output_view=OutputView.rating_list, season=season, show_all=not show_all
            ).pack()
        ))
    button_upper_row.append(InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=RatingCallbackFactory(
            output_view=OutputView.rating_list, update=True, season=season, show_all=show_all
        ).pack()
    ))
    button_lower_row = []
    season_index = seasons.index(season) if season in seasons else None
    if season_index is not None and season_index > 0:
        button_lower_row.append(InlineKeyboardButton(
            text=f'⬅️ {get_season_title(dm, seasons[season_index - 1])}',
            callback_data=RatingCallbackFactory(
                output_view=OutputView.rating_list, season=seasons[season_index - 1]
            ).pack()
        ))
    if season_index is not None and season_index < len(seasons) - 1:
        button_lower_row.append(InlineKeyboardButton(
            text=f'➡️ {get_season_title(dm, seasons[season_index + 1])}',
            callback_data=RatingCallbackFactory(
                output_view=OutputView.rating_list, season=seasons[season_index + 1]
            ).pack()
        ))
    button_lower_row.append(InlineKeyboardButton(
        text='🧾 Все сезоны',
        callback_data=RatingCallbackFactory(output_view=OutputView.rating_all_seasons, season=season).pack()
    ))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[button_upper_row, button_lower_row])
    return text, ParseMode.HTML, keyboard


async def rating_choose(
        dm: DatabaseManager, callback_data: RatingCallbackFactory
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>💎 Рейтинг участников клана</b>\n'
        f'\n'
    )
    if not await dm.load_player_rating_config():
        text += f'Рейтинг выключен'
        return text, ParseMode.HTML, None
    season = callback_data.season
    player_ratings = await dm.get_player_ratings(season)
    shown_ratings, show_all, has_prize_candidates = get_shown_ratings(player_ratings, callback_data.show_all)
    text += (
        f'Сезон: {dm.of.season(season, False)}\n'
        f'\n'
        f'Выберите участника клана:'
    )
    button_rows = [[
        InlineKeyboardButton(
            text=f'{r.player_name}: {dm.of.format_and_rstrip(r.total_points, 3)} 💎',
            callback_data=RatingCallbackFactory(
                output_view=OutputView.rating_details, season=season, show_all=show_all, player_tag=r.player_tag
            ).pack()
        )] for r in shown_ratings
    ]
    button_row = [InlineKeyboardButton(
        text='⬅️ Назад',
        callback_data=RatingCallbackFactory(output_view=OutputView.rating_list, season=season, show_all=show_all).pack()
    )]
    if has_prize_candidates:
        button_row.append(InlineKeyboardButton(
            text='🔼 Свернуть' if show_all else '🔽 Развернуть',
            callback_data=RatingCallbackFactory(
                output_view=OutputView.rating_choose, season=season, show_all=not show_all
            ).pack()
        ))
    button_row.append(InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=RatingCallbackFactory(
            output_view=OutputView.rating_choose, update=True, season=season, show_all=show_all
        ).pack()
    ))
    button_rows.append(button_row)
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


async def rating_details(
        dm: DatabaseManager, callback_data: RatingCallbackFactory
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    season = callback_data.season
    back_button = InlineKeyboardButton(
        text='⬅️ Назад',
        callback_data=RatingCallbackFactory(
            output_view=OutputView.rating_choose, season=season, show_all=callback_data.show_all
        ).pack()
    )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=RatingCallbackFactory(
            output_view=OutputView.rating_details,
            update=True,
            season=season,
            show_all=callback_data.show_all,
            player_tag=callback_data.player_tag
        ).pack()
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[back_button, update_button]])
    if not await dm.load_player_rating_config():
        text = (
            f'<b>💎 Рейтинг игрока</b>\n'
            f'\n'
            f'Рейтинг выключен'
        )
        return text, ParseMode.HTML, None
    player_ratings = await dm.get_player_ratings(season)
    r = player_ratings.get(callback_data.player_tag)
    if r is None:
        text = (
            f'<b>💎 Рейтинг игрока</b>\n'
            f'\n'
            f'Информация об игроке отсутствует\n'
        )
        return text, ParseMode.HTML, keyboard
    f = dm.of.format_and_rstrip
    text = (
        f'<b>💎 Рейтинг игрока {dm.of.to_html(r.player_name)}</b>\n'
        f'\n'
        f'Сезон: {dm.of.season(season, False)}\n'
        f'\n'
        f'Итого очков: {f(r.total_points, 3)} 💎\n'
    )
    if r.win_chance is not None:
        text += f'Шанс выигрыша: {f(r.win_chance * 100, 1)}%\n'
    text += (
        f'\n'
        f'Допуск к розыгрышу: {'✅' if r.is_eligible_for_prize else '❌'}\n'
    )
    if r.cwl_required_wars is not None:
        text += f'Войн ЛВК: {r.cwl_wars} ⚔️ / {r.cwl_required_wars} ⚔️\n'
    else:
        text += f'Войн ЛВК: {r.cwl_wars} ⚔️\n'
    if r.cwl_average_stars() is not None:
        text += f'Среднее количество звёзд: {f(r.cwl_average_stars(), 2)} ⭐'
        if r.cwl_required_average_stars is not None:
            text += f' / {f(r.cwl_required_average_stars, 2)} ⭐'
        text += '\n'
    text += (
        f'\n'
        f'Очков за ЛВК: {f(r.cwl_points, 3)} 💎'
    )
    if len(r.cwl_stars) > 0:
        text += f' ({' + '.join(f'{cwl_stars} ⭐' for cwl_stars in r.cwl_stars)})'
    text += '\n'
    text += (
        f'\n'
        f'Очков за лигу: {f(r.league_tier_points + r.league_place_points, 3)} 💎 '
        f'({f(r.league_tier_points, 3)} 💎 + {f(r.league_place_points, 3)} 💎)\n'
    )
    if len(r.league_days) > 0:
        text += f'Дней в лигах: {', '.join(
            f'{dm.of.league_tier(league_tier)} — {dm.of.get_days_in_russian(days)}'
            for league_tier, days in sorted(r.league_days.items(), reverse=True)
        )}\n'
    if len(r.league_places) > 0:
        text += f'Места в клане: {', '.join(f'#{f(place, 1)}' for place in r.league_places)}\n'
    if len(r.raids_attacks) > 0:
        text += (
            f'\n'
            f'Очков за рейды: {f(r.raids_attacks_points + r.raids_gold_points, 3)} 💎 '
            f'({f(r.raids_attacks_points, 3)} 💎 + {f(r.raids_gold_points, 3)} 💎)\n'
            f'Атак: {', '.join(f'{raids_attacks} 🗡️' for raids_attacks in r.raids_attacks)}\n'
            f'Золота: {', '.join(
                f'{dm.of.separate_thousands(round(raids_gold))} {dm.of.get_capital_gold_emoji()}'
                for raids_gold in r.raids_gold
            )}\n'
        )
    if len(r.cw_attacks) > 0 and r.cw_points != 0:
        text += (
            f'\n'
            f'Штрафы за КВ: {f(r.cw_points, 3)} 💎\n'
            f'Войн с 1 атакой: {r.cw_attacks.count(1)} ⚔️, войн без атак: {r.cw_attacks.count(0)} ⚔️\n'
        )
    return text, ParseMode.HTML, keyboard


async def rating_all_seasons(
        dm: DatabaseManager, callback_data: RatingCallbackFactory
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>💎 Рейтинг участников клана</b>\n'
        f'\n'
        f'Выберите сезон:\n'
    )
    seasons = await dm.get_player_rating_seasons()
    button_rows = [[InlineKeyboardButton(
        text=get_season_title(dm, season),
        callback_data=RatingCallbackFactory(output_view=OutputView.rating_list, season=season).pack()
    )] for season in seasons]
    button_rows.append([InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=RatingCallbackFactory(
            output_view=OutputView.rating_all_seasons, update=True, season=callback_data.season
        ).pack()
    )])
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


@router.message(Command('rating'))
async def command_rating(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await rating_list(dm, None)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(RatingCallbackFactory.filter())
async def callback_rating(
        callback_query: CallbackQuery, callback_data: RatingCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        if callback_data.output_view == OutputView.rating_list:
            text, parse_mode, reply_markup = await rating_list(dm, callback_data)
        elif callback_data.output_view == OutputView.rating_choose:
            text, parse_mode, reply_markup = await rating_choose(dm, callback_data)
        elif callback_data.output_view == OutputView.rating_details:
            text, parse_mode, reply_markup = await rating_details(dm, callback_data)
        else:
            text, parse_mode, reply_markup = await rating_all_seasons(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    if callback_data.update:
        await callback_query.answer('Сообщение обновлено')
    else:
        await callback_query.answer()
