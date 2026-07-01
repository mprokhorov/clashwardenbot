from enum import auto, IntEnum
from typing import Optional

from aiogram import Router
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from magic_filter import F

from database_manager import DatabaseManager
from entities.game_entities import PlayerRatingGiveaway

router = Router()


class OutputView(IntEnum):
    player_rating_giveaway_season_select = auto()
    player_rating_giveaway_result = auto()
    player_rating_giveaway_verify = auto()


class PlayerRatingGiveawayCallbackFactory(CallbackData, prefix='player_rating_giveaway'):
    output_view: OutputView
    season: Optional[str] = None
    giveaway_id: Optional[int] = None


def player_rating_giveaway_season_select_view(
        dm: DatabaseManager, seasons: list[str]
) -> tuple[str, ParseMode, InlineKeyboardMarkup]:
    text = (
        f'<b>🎉 Розыгрыш по рейтингу игроков</b>\n'
        f'\n'
        f'Выберите сезон для розыгрыша:'
    )
    button_rows = [[
        InlineKeyboardButton(
            text=dm.of.season(season, False),
            callback_data=PlayerRatingGiveawayCallbackFactory(
                output_view=OutputView.player_rating_giveaway_result, season=season
            ).pack()
        )
    ] for season in seasons]
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


def player_rating_giveaway_result_text(dm: DatabaseManager, giveaway: PlayerRatingGiveaway) -> str:
    total_weight = sum(entry.weight for entry in giveaway.entries)
    entries_text = '\n'.join(
        f'{dm.load_name(entry.player_tag)}: {dm.of.format_and_rstrip(entry.weight, 3)} 💎 '
        f'({dm.of.format_and_rstrip(entry.weight / total_weight * 100, 1)}%)'
        for entry in sorted(giveaway.entries, key=lambda entry: entry.weight, reverse=True)
    )
    return (
        f'<b>🎉 Розыгрыш по рейтингу игроков</b>\n'
        f'\n'
        f'Сезон: {dm.of.season(giveaway.season, False)}\n'
        f'\n'
        f'Победитель: {dm.load_name(giveaway.winner_player_tag)} 🏆\n'
        f'\n'
        f'Шансы участников (пропорционально набранным очкам):\n'
        f'{entries_text}\n'
        f'\n'
        f'ID розыгрыша: {giveaway.id}\n'
    )


@router.message(Command('player_rating_giveaway'))
async def command_player_rating_giveaway(message: Message, dm: DatabaseManager) -> None:
    if message.chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await message.reply(text='Эта команда работает только в группах')
        return
    user_can_start_giveaway = await dm.can_user_start_player_rating_giveaway(message.chat.id, message.from_user.id)
    if not user_can_start_giveaway:
        await message.reply(text='У вас нет прав на использование этой команды')
        return
    if not await dm.load_player_rating_config():
        await message.reply(text='Рейтинг игроков выключен')
        return
    seasons = await dm.get_player_rating_giveaway_seasons()
    if len(seasons) == 0:
        await message.reply(
            text='Нет ни одного сезона с допущенными к розыгрышу игроками с положительным количеством очков'
        )
        return
    text, parse_mode, reply_markup = player_rating_giveaway_season_select_view(dm, seasons)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(
    PlayerRatingGiveawayCallbackFactory.filter(F.output_view == OutputView.player_rating_giveaway_result)
)
async def callback_player_rating_giveaway_result(
        callback_query: CallbackQuery, callback_data: PlayerRatingGiveawayCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
        return
    giveaway = await dm.run_player_rating_giveaway(
        callback_query.message.chat.id, callback_data.season, callback_query.from_user.id
    )
    if giveaway is None:
        await callback_query.answer('Нет ни одного допущенного к розыгрышу игрока с положительным количеством очков', show_alert=True)
        return
    verify_button = InlineKeyboardButton(
        text='🔍 Проверить честность розыгрыша',
        callback_data=PlayerRatingGiveawayCallbackFactory(
            output_view=OutputView.player_rating_giveaway_verify, giveaway_id=giveaway.id
        ).pack()
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[verify_button]])
    await callback_query.message.edit_text(
        text=player_rating_giveaway_result_text(dm, giveaway), parse_mode=ParseMode.HTML, reply_markup=keyboard
    )
    await callback_query.answer()


@router.callback_query(PlayerRatingGiveawayCallbackFactory.filter(F.output_view == OutputView.player_rating_giveaway_verify))
async def callback_player_rating_giveaway_verify(
        callback_query: CallbackQuery, callback_data: PlayerRatingGiveawayCallbackFactory, dm: DatabaseManager
) -> None:
    giveaway = await dm.load_player_rating_giveaway(callback_data.giveaway_id)
    if giveaway is None:
        await callback_query.answer('Розыгрыш не найден', show_alert=True)
        return
    recomputed_roll, recomputed_winner_player_tag = dm.roll_player_rating_giveaway_winner(
        giveaway.seed, giveaway.entries
    )
    matches = (
        abs(recomputed_roll - giveaway.roll) < 1e-12 and recomputed_winner_player_tag == giveaway.winner_player_tag
    )
    verification_text = (
        f'\n'
        f'<b>🔍 Проверка честности</b>\n'
        f'Seed: <code>{giveaway.seed}</code>\n'
        f'Пересчитанное случайное число: {giveaway.roll:.10f}\n'
        f'Пересчитанный победитель: {dm.load_name(recomputed_winner_player_tag)}\n'
        f'Результат совпадает с сохранённым: {"✅" if matches else "❌"}\n'
    )
    text = player_rating_giveaway_result_text(dm, giveaway) + verification_text
    await callback_query.message.edit_text(text=text, parse_mode=ParseMode.HTML)
    if matches:
        await callback_query.answer('Розыгрыш подтверждён, победитель определён честно')
    else:
        await callback_query.answer('Не удалось подтвердить результат розыгрыша', show_alert=True)
