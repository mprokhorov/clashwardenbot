import hashlib
import json
import secrets
from contextlib import suppress
from datetime import date, timedelta
from enum import auto, IntEnum
from typing import Optional

from aiogram import Router
from aiogram.enums import ChatType, ParseMode
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


class GiveawayAction(IntEnum):
    preview = auto()
    commit = auto()
    draw = auto()
    cancel = auto()


class GiveawayCallbackFactory(CallbackData, prefix='giveaway'):
    action: GiveawayAction
    update: bool = False
    season: Optional[str] = None
    draw_id: Optional[int] = None


GIVEAWAY_TOTAL_TICKETS = 1_000_000


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


def get_giveaway_participants(player_ratings: dict[str, PlayerRating]) -> list[dict]:
    candidates = sorted(
        [r for r in player_ratings.values() if r.win_chance is not None and r.win_chance > 0],
        key=lambda r: (-r.total_points, r.player_tag)
    )
    return [
        {
            'player_tag': r.player_tag,
            'player_name': r.player_name,
            'points': round(r.total_points, 3),
            'tickets': max(1, round(r.win_chance * GIVEAWAY_TOTAL_TICKETS))
        }
        for r in candidates
    ]


def get_ticket_ranges(participants: list[dict]) -> list[tuple[dict, int, int]]:
    ticket_ranges = []
    first_ticket = 0
    for participant in participants:
        ticket_ranges.append((participant, first_ticket, first_ticket + participant['tickets'] - 1))
        first_ticket += participant['tickets']
    return ticket_ranges


def draw_ticket(seed: str, client_seed: str, total_tickets: int) -> tuple[str, int]:
    draw_hash = hashlib.sha256(f'{seed}:{client_seed}'.encode()).hexdigest()
    return draw_hash, int(draw_hash, 16) % total_tickets


def get_default_giveaway_season(seasons: list[str]) -> Optional[str]:
    previous_season = (date.today().replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
    past_seasons = [season for season in seasons if season <= previous_season]
    if len(past_seasons) > 0:
        return past_seasons[-1]
    return seasons[-1] if len(seasons) > 0 else None


async def giveaway_preview(
        dm: DatabaseManager, callback_data: Optional[GiveawayCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>🎲 Розыгрыш призов рейтинга</b>\n'
        f'\n'
    )
    if not await dm.load_player_rating_config():
        text += f'Рейтинг выключен'
        return text, ParseMode.HTML, None
    seasons = await dm.get_player_rating_seasons()
    if callback_data is not None and callback_data.season in seasons:
        season = callback_data.season
    else:
        season = get_default_giveaway_season(seasons)
    if season is None:
        text += f'Информация о рейтинге отсутствует\n'
        return text, ParseMode.HTML, None
    participants = get_giveaway_participants(await dm.get_player_ratings(season))
    total_tickets = sum(participant['tickets'] for participant in participants)
    text += (
        f'Сезон: {dm.of.season(season, False)}\n'
        f'\n'
    )
    if len(participants) > 0:
        text += f'Допущены к розыгрышу:\n'
        for i, participant in enumerate(participants):
            text += (
                f'{i + 1}. {dm.of.to_html(participant['player_name'])}: '
                f'{dm.of.format_and_rstrip(participant['points'], 3)} 💎 '
                f'({dm.of.format_and_rstrip(participant['tickets'] / total_tickets * 100, 1)}%)\n'
            )
        text += (
            f'\n'
            f'После фиксации участников их список и шансы изменить будет нельзя\n'
        )
    else:
        text += f'Допущенных к розыгрышу нет\n'
    button_upper_row = []
    if len(participants) > 0:
        button_upper_row.append(InlineKeyboardButton(
            text='📌 Зафиксировать участников',
            callback_data=GiveawayCallbackFactory(action=GiveawayAction.commit, season=season).pack()
        ))
    button_upper_row.append(InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=GiveawayCallbackFactory(action=GiveawayAction.preview, update=True, season=season).pack()
    ))
    button_lower_row = []
    season_index = seasons.index(season)
    if season_index > 0:
        button_lower_row.append(InlineKeyboardButton(
            text=f'⬅️ {get_season_title(dm, seasons[season_index - 1])}',
            callback_data=GiveawayCallbackFactory(action=GiveawayAction.preview, season=seasons[season_index - 1]).pack()
        ))
    if season_index < len(seasons) - 1:
        button_lower_row.append(InlineKeyboardButton(
            text=f'➡️ {get_season_title(dm, seasons[season_index + 1])}',
            callback_data=GiveawayCallbackFactory(action=GiveawayAction.preview, season=seasons[season_index + 1]).pack()
        ))
    button_rows = [button_upper_row] + ([button_lower_row] if len(button_lower_row) > 0 else [])
    return text, ParseMode.HTML, InlineKeyboardMarkup(inline_keyboard=button_rows)


def giveaway_commitment(dm: DatabaseManager, draw_id: int, season: str, seed_hash: str, participants: list[dict]) -> str:
    total_tickets = sum(participant['tickets'] for participant in participants)
    text = (
        f'<b>🎲 Розыгрыш призов рейтинга №{draw_id}</b>\n'
        f'\n'
        f'Сезон: {dm.of.season(season, False)}\n'
        f'\n'
        f'Участники зафиксированы:\n'
    )
    for i, (participant, first_ticket, last_ticket) in enumerate(get_ticket_ranges(participants)):
        text += (
            f'{i + 1}. {dm.of.to_html(participant['player_name'])}: '
            f'{dm.of.format_and_rstrip(participant['points'], 3)} 💎, '
            f'{dm.of.format_and_rstrip(participant['tickets'] / total_tickets * 100, 1)}%, '
            f'билеты {dm.of.separate_thousands(first_ticket)}–{dm.of.separate_thousands(last_ticket)}\n'
        )
    text += (
        f'\n'
        f'Всего билетов: {dm.of.separate_thousands(total_tickets)}\n'
        f'SHA-256 секретного зерна:\n'
        f'<code>{seed_hash}</code>\n'
        f'\n'
        f'Зерно раскроется после розыгрыша. Выигрышный билет = '
        f'int(SHA-256("зерно:id нажатия кнопки"), 16) mod {total_tickets}. '
        f'id нажатия выдаёт Telegram в момент розыгрыша\n'
    )
    return text


def giveaway_result(dm: DatabaseManager, draw: dict, client_seed: str, draw_hash: str, ticket: int, winner: dict) -> str:
    participants = draw['participants']
    total_tickets = sum(participant['tickets'] for participant in participants)
    _, first_ticket, last_ticket = next(
        ticket_range for ticket_range in get_ticket_ranges(participants)
        if ticket_range[0]['player_tag'] == winner['player_tag']
    )
    return (
        f'<b>🏆 Победитель розыгрыша №{draw['draw_id']}: {dm.of.to_html(winner['player_name'])}</b>\n'
        f'\n'
        f'Сезон: {dm.of.season(draw['season'], False)}\n'
        f'Очки: {dm.of.format_and_rstrip(winner['points'], 3)} 💎\n'
        f'Шанс победы: {dm.of.format_and_rstrip(winner['tickets'] / total_tickets * 100, 1)}%\n'
        f'\n'
        f'<b>Проверка честности</b>\n'
        f'Зерно: <code>{draw['seed']}</code>\n'
        f'Его SHA-256 совпадает с опубликованным до розыгрыша: <code>{draw['seed_hash']}</code>\n'
        f'id нажатия кнопки: <code>{dm.of.to_html(client_seed)}</code>\n'
        f'SHA-256("зерно:id нажатия") = <code>{draw_hash}</code>\n'
        f'Билет = int(хэш, 16) mod {total_tickets} = {dm.of.separate_thousands(ticket)}, '
        f'это билеты {dm.of.separate_thousands(first_ticket)}–{dm.of.separate_thousands(last_ticket)} '
        f'игрока {dm.of.to_html(winner['player_name'])}\n'
    )


@router.message(Command('player_rating_giveaway'))
async def command_player_rating_giveaway(message: Message, dm: DatabaseManager) -> None:
    if message.chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await message.reply(text=f'Эта команда работает только в группах')
    elif not await dm.can_user_run_player_rating_giveaway(message.chat.id, message.from_user.id):
        await message.reply(text=f'У вас нет прав на использование этой команды')
    else:
        text, parse_mode, reply_markup = await giveaway_preview(dm, None)
        reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(GiveawayCallbackFactory.filter())
async def callback_player_rating_giveaway(
        callback_query: CallbackQuery, callback_data: GiveawayCallbackFactory, dm: DatabaseManager
) -> None:
    message = callback_query.message
    user_can_run_giveaway = await dm.can_user_run_player_rating_giveaway(message.chat.id, callback_query.from_user.id)
    user_is_message_owner = await dm.is_user_message_owner(message, callback_query.from_user)
    if callback_data.action == GiveawayAction.preview:
        if not (user_is_message_owner and user_can_run_giveaway) and not callback_data.update:
            await callback_query.answer('Эта кнопка не работает для вас')
            return
        text, parse_mode, reply_markup = await giveaway_preview(dm, callback_data)
        with suppress(TelegramBadRequest):
            await message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback_query.answer('Сообщение обновлено' if callback_data.update else None)

    elif callback_data.action == GiveawayAction.commit:
        if not (user_is_message_owner and user_can_run_giveaway):
            await callback_query.answer('Эта кнопка не работает для вас')
            return
        if callback_data.season not in await dm.get_player_rating_seasons():
            await callback_query.answer('Сезон не найден')
            return
        participants = get_giveaway_participants(await dm.get_player_ratings(callback_data.season))
        if len(participants) == 0:
            await callback_query.answer('Допущенных к розыгрышу нет')
            return
        seed = secrets.token_hex(32)
        seed_hash = hashlib.sha256(seed.encode()).hexdigest()
        draw_id = await dm.create_player_rating_draw(
            callback_data.season, message.chat.id, message.message_id, callback_query.from_user.id,
            seed, seed_hash, participants
        )
        if draw_id is None:
            await callback_query.answer('Участники уже зафиксированы')
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text='🎲 Разыграть',
                callback_data=GiveawayCallbackFactory(action=GiveawayAction.draw, draw_id=draw_id).pack()
            ),
            InlineKeyboardButton(
                text='❌ Отменить',
                callback_data=GiveawayCallbackFactory(action=GiveawayAction.cancel, draw_id=draw_id).pack()
            )
        ]])
        try:
            await message.edit_text(
                text=giveaway_commitment(dm, draw_id, callback_data.season, seed_hash, participants),
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
        except TelegramBadRequest:
            # Without the published commitment the draw could not be verified, so it must not happen
            await dm.cancel_player_rating_draw(draw_id)
            await callback_query.answer('Не удалось опубликовать участников, розыгрыш отменён', show_alert=True)
            return
        await callback_query.answer('Участники зафиксированы')

    else:
        if not user_can_run_giveaway:
            await callback_query.answer('Эта кнопка не работает для вас')
            return
        row = await dm.load_player_rating_draw(callback_data.draw_id, message.chat.id, message.message_id)
        if row is None:
            await callback_query.answer('Розыгрыш не найден')
            return
        if row['drawn_at'] is not None or row['cancelled_at'] is not None:
            await callback_query.answer('Розыгрыш уже проведён или отменён')
            with suppress(TelegramBadRequest):
                await message.edit_reply_markup(reply_markup=None)
            return
        draw = dict(row)
        draw['participants'] = json.loads(draw['participants'])
        if callback_data.action == GiveawayAction.cancel:
            if await dm.cancel_player_rating_draw(draw['draw_id']):
                with suppress(TelegramBadRequest):
                    await message.edit_reply_markup(reply_markup=None)
                await message.reply(text=f'❌ Розыгрыш №{draw['draw_id']} отменён')
                await callback_query.answer()
            else:
                await callback_query.answer('Розыгрыш уже проведён или отменён')
            return
        client_seed = callback_query.id
        total_tickets = sum(participant['tickets'] for participant in draw['participants'])
        draw_hash, ticket = draw_ticket(draw['seed'], client_seed, total_tickets)
        winner = next(
            participant for participant, first_ticket, last_ticket in get_ticket_ranges(draw['participants'])
            if first_ticket <= ticket <= last_ticket
        )
        if not await dm.finish_player_rating_draw(
                draw['draw_id'], client_seed, ticket, winner['player_tag'], callback_query.from_user.id
        ):
            await callback_query.answer('Розыгрыш уже проведён или отменён')
            return
        with suppress(TelegramBadRequest):
            await message.edit_reply_markup(reply_markup=None)
        await message.reply(
            text=giveaway_result(dm, draw, client_seed, draw_hash, ticket, winner), parse_mode=ParseMode.HTML
        )
        await callback_query.answer()


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
    if not user_is_message_owner and not callback_data.update:
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
