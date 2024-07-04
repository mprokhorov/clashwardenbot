from contextlib import suppress
from enum import auto, IntEnum
from typing import Optional

from aiogram import Router
from aiogram.enums import ParseMode, ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from magic_filter import F

from database_manager import DatabaseManager
from entities import WarMember, ClanWarLeagueClan, ClanWarLeagueMember

router = Router()


class CWLMapSide(IntEnum):
    clan = auto()
    opponent = auto()


class CWLAttacksSide(IntEnum):
    clan = auto()
    opponent = auto()


class OutputView(IntEnum):
    cwl_info_day = auto()
    cwl_info_all_days = auto()
    cwl_attacks_day = auto()
    cwl_attacks_all_days = auto()
    cwl_map_day = auto()
    cwl_map_all_days = auto()
    cwl_skips_day = auto()
    cwl_skips_all_days = auto()
    cwl_clans = auto()


class CWLCallbackFactory(CallbackData, prefix='cwl'):
    output_view: OutputView
    update: bool = False
    show_opponent_info: Optional[bool] = None
    cwl_day: Optional[int] = None
    cwl_map_side: Optional[CWLMapSide] = None
    cwl_attacks_side: Optional[CWLAttacksSide] = None


async def cwl_info(
        dm: DatabaseManager, callback_data: Optional[CWLCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    if callback_data is not None and callback_data.cwl_day is not None:
        cwl_day, cwlw = callback_data.cwl_day, (await dm.load_clan_war_league_own_wars())[callback_data.cwl_day]
    else:
        cwl_day, cwlw = await dm.load_clan_war_league_own_war()
    if callback_data is not None and callback_data.show_opponent_info is not None:
        show_opponent_info = callback_data.show_opponent_info
    else:
        show_opponent_info = False
    text = (
        f'<b>⚔️ Информация об ЛВК</b>\n'
        f'\n'
    )
    button_upper_row = []
    button_lower_row = []
    if show_opponent_info:
        opponent_info_button = InlineKeyboardButton(
            text='🔼 Свернуть',
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_info_day, show_opponent_info=False, cwl_day=cwl_day
            ).pack()
        )
    else:
        opponent_info_button = InlineKeyboardButton(
            text='🔽 Развернуть',
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_info_day, show_opponent_info=True, cwl_day=cwl_day
            ).pack()
        )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_info_day, update=True, show_opponent_info=show_opponent_info, cwl_day=cwl_day
        ).pack()
    )
    cwl_season, _ = await dm.load_clan_war_league()
    if dm.of.state(cwlw) in ['preparation']:
        war_win_streak = await dm.load_war_win_streak(cwlw['opponent']['tag'])
        cw_log = await dm.load_clan_war_log(cwlw['opponent']['tag'])
        text += dm.of.cwlw_preparation(cwlw, cwl_season, cwl_day, show_opponent_info, war_win_streak, cw_log)
        button_upper_row.append(opponent_info_button)
        button_upper_row.append(update_button)
    elif dm.of.state(cwlw) in ['inWar', 'warEnded']:
        war_win_streak = await dm.load_war_win_streak(cwlw['opponent']['tag'])
        cw_log = await dm.load_clan_war_log(cwlw['opponent']['tag'])
        text += dm.of.cwlw_in_war_or_war_ended(cwlw, cwl_season, cwl_day, show_opponent_info, war_win_streak, cw_log)
        button_upper_row.append(opponent_info_button)
        button_upper_row.append(update_button)
    else:
        text += f'Информация об ЛВК отсутствует\n'
        button_upper_row.append(update_button)
    if cwlw is not None:
        previous_cwl_day_button = InlineKeyboardButton(
            text=f'⬅️ День {cwl_day}',
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_info_day, show_opponent_info=show_opponent_info, cwl_day=cwl_day - 1
            ).pack()
        )
        next_cwl_day_button = InlineKeyboardButton(
            text=f'➡️ День {cwl_day + 2}',
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_info_day, show_opponent_info=show_opponent_info, cwl_day=cwl_day + 1
            ).pack()
        )
        all_cwl_days_button = InlineKeyboardButton(
            text='🧾 Все дни',
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_info_all_days, show_opponent_info=show_opponent_info
            ).pack()
        )
        if cwl_day > 0:
            button_lower_row.append(previous_cwl_day_button)
        if cwl_day < len(await dm.load_clan_war_league_own_wars()) - 1:
            button_lower_row.append(next_cwl_day_button)
        button_lower_row.append(all_cwl_days_button)
    button_rows = []
    if len(button_upper_row) > 0:
        button_rows.append(button_upper_row)
    if len(button_lower_row) > 0:
        button_rows.append(button_lower_row)
    if len(button_rows) > 0:
        keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    else:
        keyboard = None
    return text, ParseMode.HTML, keyboard


async def cwl_map(
        dm: DatabaseManager, callback_data: Optional[CWLCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    if callback_data is not None and callback_data.cwl_day is not None:
        cwl_day, cwlw = callback_data.cwl_day, (await dm.load_clan_war_league_own_wars())[callback_data.cwl_day]
    else:
        cwl_day, cwlw = await dm.load_clan_war_league_own_war()
    cwl_season, _ = await dm.load_clan_war_league()
    if callback_data is not None and callback_data.cwl_map_side is not None:
        cwl_map_side = callback_data.cwl_map_side
    else:
        cwl_map_side = CWLAttacksSide.opponent
    text = (
        f'<b>🗺️ Карта ЛВК</b>\n'
        f'\n'
    )
    button_upper_row = []
    button_lower_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_map_day, update=True, cwl_day=cwl_day, cwl_map_side=cwl_map_side
        ).pack()
    )
    clan_side_button = InlineKeyboardButton(
        text='↔️ Карта клана',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_map_day, cwl_day=cwl_day, cwl_map_side=CWLMapSide.clan
        ).pack()
    )
    opponent_side_button = InlineKeyboardButton(
        text='↔️ Карта противника',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_map_day, cwl_day=cwl_day, cwl_map_side=CWLMapSide.opponent
        ).pack()
    )
    if dm.of.state(cwlw) in ['preparation']:
        text += dm.of.cwlw_preparation(cwlw, cwl_season, cwl_day, False, None, None)
        button_upper_row.append(update_button)
    elif dm.of.state(cwlw) in ['inWar', 'warEnded']:
        clan_map_position_by_player = dm.of.calculate_map_positions(cwlw['clan']['members'])
        opponent_map_position_by_player = dm.of.calculate_map_positions(cwlw['opponent']['members'])
        text += (
            f'{dm.of.cwlw_in_war_or_war_ended(cwlw, cwl_season, cwl_day, False, None, None)}'
            f'\n'
        )
        if cwl_map_side == CWLMapSide.opponent:
            text += 'Карта противника:\n'
            text += dm.of.get_map(
                clan_map_position_by_player, opponent_map_position_by_player, cwlw['clan'], cwlw['opponent']
            )
            button_upper_row.append(clan_side_button)
        else:
            text += 'Карта клана:\n'
            text += dm.of.get_map(
                opponent_map_position_by_player, clan_map_position_by_player, cwlw['opponent'], cwlw['clan']
            )
            button_upper_row.append(opponent_side_button)
        button_upper_row.append(update_button)
    else:
        text += f'Информация об ЛВК отсутствует\n'
        button_upper_row.append(update_button)
    if cwlw is not None:
        previous_cwl_day_button = InlineKeyboardButton(
            text=f'⬅️ День {cwl_day}',
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_map_day, cwl_day=cwl_day - 1, cwl_map_side=cwl_map_side
            ).pack()
        )
        next_cwl_day_button = InlineKeyboardButton(
            text=f'➡️ День {cwl_day + 2}',
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_map_day, cwl_day=cwl_day + 1, cwl_map_side=cwl_map_side
            ).pack()
        )
        all_cwl_days_button = InlineKeyboardButton(
            text='🧾 Все дни',
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_map_all_days, cwl_map_side=cwl_map_side
            ).pack()
        )
        if cwl_day > 0:
            button_lower_row.append(previous_cwl_day_button)
        if cwl_day < len(await dm.load_clan_war_league_own_wars()) - 1:
            button_lower_row.append(next_cwl_day_button)
        button_lower_row.append(all_cwl_days_button)
    button_rows = []
    if len(button_upper_row) > 0:
        button_rows.append(button_upper_row)
    if len(button_lower_row) > 0:
        button_rows.append(button_lower_row)
    if len(button_rows) > 0:
        keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    else:
        keyboard = None
    return text, ParseMode.HTML, keyboard


async def cwl_attacks(
        dm: DatabaseManager, callback_data: Optional[CWLCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    if callback_data is not None and callback_data.cwl_day is not None:
        cwl_day, cwlw = callback_data.cwl_day, (await dm.load_clan_war_league_own_wars())[callback_data.cwl_day]
    else:
        cwl_day, cwlw = await dm.load_clan_war_league_own_war()
    cwl_season, _ = await dm.load_clan_war_league()
    if callback_data is not None and callback_data.cwl_attacks_side is not None:
        cwl_attacks_side = callback_data.cwl_attacks_side
    else:
        cwl_attacks_side = CWLAttacksSide.clan
    text = (
        f'<b>🗡️ Атаки в ЛВК</b>\n'
        f'\n'
    )
    button_upper_row = []
    button_lower_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_attacks_day, update=True, cwl_day=cwl_day, cwl_attacks_side=cwl_attacks_side
        ).pack()
    )
    opponent_attacks_button = InlineKeyboardButton(
        text='↔️ Атаки противника',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_attacks_day, cwl_day=cwl_day, cwl_attacks_side=CWLAttacksSide.opponent
        ).pack()
    )
    clan_attacks_button = InlineKeyboardButton(
        text='↔️ Атаки клана',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_attacks_day, cwl_day=cwl_day, cwl_attacks_side=CWLAttacksSide.clan
        ).pack()
    )
    if dm.of.state(cwlw) in ['preparation']:
        if cwl_attacks_side == CWLAttacksSide.clan:
            rows = await dm.acquired_connection.fetch('''
                SELECT
                    player_tag, player_name,
                    town_hall_level, barbarian_king_level, archer_queen_level, grand_warden_level, royal_champion_level
                FROM player
                WHERE clan_tag = $1
            ''', dm.clan_tag)
            clan_map_position_by_player = dm.of.calculate_map_positions(cwlw['clan']['members'])
            text += (
                f'{dm.of.cwlw_preparation(cwlw, cwl_season, cwl_day, False, None, None)}'
                f'\n'
                f'{dm.of.war_members(cwlw['clan']['members'], clan_map_position_by_player, rows)}'
            )
            button_upper_row.append(opponent_attacks_button)
        else:
            rows = await dm.acquired_connection.fetch('''
                SELECT
                    player_tag, player_name,
                    town_hall_level, barbarian_king_level, archer_queen_level, grand_warden_level, royal_champion_level
                FROM opponent_player
                WHERE clan_tag = $1
            ''', cwlw['opponent']['tag'])
            opponent_map_position_by_player = dm.of.calculate_map_positions(cwlw['opponent']['members'])
            text += (
                f'{dm.of.cwlw_preparation(cwlw, cwl_season, cwl_day, False, None, None)}'
                f'\n'
                f'{dm.of.war_members(cwlw['opponent']['members'], opponent_map_position_by_player, rows)}'
            )
            button_upper_row.append(clan_attacks_button)
        button_upper_row.append(update_button)
    elif dm.of.state(cwlw) in ['inWar', 'warEnded']:
        clan_map_position_by_player = dm.of.calculate_map_positions(cwlw['clan']['members'])
        opponent_map_position_by_player = dm.of.calculate_map_positions(cwlw['opponent']['members'])
        text += (
            f'{dm.of.cwlw_in_war_or_war_ended(cwlw, cwl_season, cwl_day, False, None, None)}'
            f'\n'
        )
        if cwl_attacks_side == CWLAttacksSide.clan:
            text += (
                'Атаки клана:\n'
                '\n'
            )
            text += dm.of.get_attacks(
                clan_map_position_by_player, opponent_map_position_by_player, cwlw['clan'], cwlw['opponent'], 1
            )
            button_upper_row.append(opponent_attacks_button)
        else:
            text += (
                'Атаки противника:\n'
                '\n'
            )
            text += dm.of.get_attacks(
                opponent_map_position_by_player, clan_map_position_by_player, cwlw['opponent'], cwlw['clan'], 1
            )
            button_upper_row.append(clan_attacks_button)
        button_upper_row.append(update_button)
    else:
        text += f'Информация об ЛВК отсутствует\n'
        button_upper_row.append(update_button)
    if cwlw is not None:
        previous_cwl_day_button = InlineKeyboardButton(
            text=f'⬅️ День {cwl_day}',
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_attacks_day, cwl_day=cwl_day - 1, cwl_attacks_side=cwl_attacks_side
            ).pack()
        )
        next_cwl_day_button = InlineKeyboardButton(
            text=f'➡️ День {cwl_day + 2}',
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_attacks_day, cwl_day=cwl_day + 1, cwl_attacks_side=cwl_attacks_side
            ).pack()
        )
        all_cwl_days_button = InlineKeyboardButton(
            text='🧾 Все дни',
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_attacks_all_days, cwl_attacks_side=cwl_attacks_side
            ).pack()
        )
        if cwl_day > 0:
            button_lower_row.append(previous_cwl_day_button)
        if cwl_day < len(await dm.load_clan_war_league_own_wars()) - 1:
            button_lower_row.append(next_cwl_day_button)
        button_lower_row.append(all_cwl_days_button)
    button_rows = []
    if len(button_upper_row) > 0:
        button_rows.append(button_upper_row)
    if len(button_lower_row) > 0:
        button_rows.append(button_lower_row)
    if len(button_rows) > 0:
        keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    else:
        keyboard = None
    return text, ParseMode.HTML, keyboard


async def cwl_skips(
        dm: DatabaseManager, chat_id: int, callback_data: Optional[CWLCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    if callback_data is not None and callback_data.cwl_day is not None:
        cwl_day, cwlw = callback_data.cwl_day, (await dm.load_clan_war_league_own_wars())[callback_data.cwl_day]
    else:
        cwl_day, cwlw = await dm.load_clan_war_league_own_war()
    text = (
        f'<b>🕒 Не проатаковавшие в ЛВК</b>\n'
        f'\n'
    )
    button_upper_row = []
    button_lower_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWLCallbackFactory(output_view=OutputView.cwl_skips_day, update=True, cwl_day=cwl_day).pack()
    )
    cwl_season, _ = await dm.load_clan_war_league()
    if dm.of.state(cwlw) in ['preparation']:
        text += dm.of.cwlw_preparation(cwlw, cwl_season, cwl_day, False, None, None)
        button_upper_row.append(update_button)
    elif dm.of.state(cwlw) in ['inWar', 'warEnded']:
        cwl_season, _ = await dm.load_clan_war_league()
        cwlw_members = []
        for cwlw_member in cwlw['clan']['members']:
            cwlw_members.append(
                WarMember(
                    player_tag=cwlw_member['tag'], attacks_spent=len(cwlw_member.get('attacks', [])), attacks_limit=1
                )
            )
        text += (
            f'{dm.of.cwlw_in_war_or_war_ended(cwlw, cwl_season, cwl_day, False, None, None)}'
            f'\n'
            f'{await dm.skips(chat_id=chat_id, players=cwlw_members, ping=False, desired_attacks_spent=1)}'
        )
        button_upper_row.append(update_button)
    else:
        text += f'Информация об ЛВК отсутствует\n'
        button_upper_row.append(update_button)
    if cwlw is not None:
        previous_cwl_day_button = InlineKeyboardButton(
            text=f'⬅️ День {cwl_day}',
            callback_data=CWLCallbackFactory(output_view=OutputView.cwl_skips_day, cwl_day=cwl_day - 1).pack()
        )
        next_cwl_day_button = InlineKeyboardButton(
            text=f'➡️ День {cwl_day + 2}',
            callback_data=CWLCallbackFactory(output_view=OutputView.cwl_skips_day, cwl_day=cwl_day + 1).pack()
        )
        all_cwl_days_button = InlineKeyboardButton(
            text='🧾 Все дни',
            callback_data=CWLCallbackFactory(output_view=OutputView.cwl_skips_all_days).pack()
        )
        if cwl_day > 0:
            button_lower_row.append(previous_cwl_day_button)
        if cwl_day < len(await dm.load_clan_war_league_own_wars()) - 1:
            button_lower_row.append(next_cwl_day_button)
        button_lower_row.append(all_cwl_days_button)
    button_rows = []
    if len(button_upper_row) > 0:
        button_rows.append(button_upper_row)
    if len(button_lower_row) > 0:
        button_rows.append(button_lower_row)
    if len(button_rows) > 0:
        keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    else:
        keyboard = None
    return text, ParseMode.HTML, keyboard


async def cwl_ping(dm: DatabaseManager, chat_id: int) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>🔔 Напоминание об атаках в ЛВК</b>\n'
        f'\n'
    )
    cwl_day, cwlw = await dm.load_clan_war_league_own_war()
    cwl_season, _ = await dm.load_clan_war_league()
    if dm.of.state(cwlw) in ['preparation']:
        text += dm.of.cwlw_preparation(cwlw, cwl_season, cwl_day, False, None, None)
    elif dm.of.state(cwlw) in ['inWar', 'warEnded']:
        cwl_season, _ = await dm.load_clan_war_league()
        cwlw_members = []
        for cwlw_member in cwlw['clan']['members']:
            cwlw_members.append(
                WarMember(
                    player_tag=cwlw_member['tag'], attacks_spent=len(cwlw_member.get('attacks', [])), attacks_limit=1
                )
            )
        text += (
            f'{dm.of.cwlw_in_war_or_war_ended(cwlw, cwl_season, cwl_day, False, None, None)}'
            f'\n'
            f'{await dm.skips(chat_id=chat_id, players=cwlw_members, ping=True, desired_attacks_spent=1)}'
        )
    else:
        text += 'Информация об ЛВК отсутствует'
    return text, ParseMode.HTML, None


async def cwl_clans(dm: DatabaseManager) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    cwl_wars = await dm.load_clan_war_league_last_day_wars()
    text = (
        f'<b>📶 Уровни ТХ кланов в ЛВК</b>\n'
        f'\n'
    )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWLCallbackFactory(output_view=OutputView.cwl_clans, update=True).pack()
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[update_button]])
    if cwl_wars is None:
        text += 'Информация об ЛВК отсутствует'
        return text, ParseMode.HTML, keyboard
    cwl_season, _ = await dm.load_clan_war_league()
    cwl_day, _ = await dm.load_clan_war_league_own_war()
    text += (
        f'Сезон: {dm.of.season(cwl_season)}\n'
        f'\n'
    )
    cwl_clan_list = []
    for cwl_war in cwl_wars:
        cwl_clan_list.append(cwl_war['clan'])
        cwl_clan_list.append(cwl_war['opponent'])
    cwl_clans_to_sort = []
    for cwl_clan in cwl_clan_list:
        cwl_members = []
        for cwl_clan_cwl_member in cwl_clan['members']:
            cwl_members.append(ClanWarLeagueMember(
                    town_hall_level=cwl_clan_cwl_member['townhallLevel'],
                    map_position=cwl_clan_cwl_member['mapPosition']
                )
            )
        cwl_members.sort(key=lambda cwl_member: cwl_member.map_position)
        cwl_clans_to_sort.append(
            ClanWarLeagueClan(
                clan_name=cwl_clan['name'],
                town_hall_levels=[cwl_m.town_hall_level for cwl_m in cwl_members],
                average_town_hall_level=dm.of.avg([cwl_m.town_hall_level for cwl_m in cwl_members])
            )
        )
    cwl_clans_to_sort.sort(key=lambda _cwl_clan: _cwl_clan.average_town_hall_level, reverse=True)
    for cwl_clan in cwl_clans_to_sort:
        text += (
            f'<b>{dm.of.to_html(cwl_clan.clan_name)}</b>\n'
            f'Уровни ТХ: {', '.join([str(town_hall_level) for town_hall_level in cwl_clan.town_hall_levels])}\n'
            f'Средний уровень ТХ: '
            f'{dm.of.get_town_hall_emoji(int(round(cwl_clan.average_town_hall_level)))} '
            f'{cwl_clan.average_town_hall_level}\n'
            f'\n'
        )
    return text, ParseMode.HTML, keyboard


async def cwl_days_list(
        dm: DatabaseManager, callback_data: CWLCallbackFactory
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    cwl_season, _ = await dm.load_clan_war_league()
    if callback_data.output_view == OutputView.cwl_info_all_days:
        text = (
            f'<b>⚔️ Информация об ЛВК</b>\n'
            f'\n'
            f'Сезон: {dm.of.season(cwl_season)}\n'
            f'\n'
            f'Выберите день:\n'
        )
        button_output_view = OutputView.cwl_info_day
    elif callback_data.output_view == OutputView.cwl_map_all_days:
        text = (
            f'<b>🗺️ Карта ЛВК</b>\n'
            f'\n'
            f'Сезон: {dm.of.season(cwl_season)}\n'
            f'\n'
            f'Выберите день:\n'
        )
        button_output_view = OutputView.cwl_map_day
    elif callback_data.output_view == OutputView.cwl_attacks_all_days:
        text = (
            f'<b>🗡️ Атаки в ЛВК</b>\n'
            f'\n'
            f'Сезон: {dm.of.season(cwl_season)}\n'
            f'\n'
            f'Выберите день:\n'
        )
        button_output_view = OutputView.cwl_attacks_day
    else:
        text = (
            f'<b>🕒 Не проатаковавшие в ЛВК</b>\n'
            f'\n'
            f'Сезон: {dm.of.season(cwl_season)}\n'
            f'\n'
            f'Выберите день:\n'
        )
        button_output_view = OutputView.cwl_skips_day
    cwl_wars = await dm.load_clan_war_league_own_wars()
    cwl_day_titles = []
    for cwl_day, cwl_war in enumerate(cwl_wars):
        cwl_clan, cwl_opponent = cwl_war['clan'], cwl_war['opponent']
        if dm.of.state(cwl_war) == 'notInWar':
            cwl_day_emoji_and_number = ''
        elif dm.of.state(cwl_war) == 'warEnded':
            clan_result = (cwl_clan['stars'], cwl_clan['destructionPercentage'])
            opponent_result = (cwl_opponent['stars'], cwl_opponent['destructionPercentage'])
            if clan_result > opponent_result:
                cwl_day_emoji_and_number = f'✅ {cwl_day + 1}. '
            elif clan_result < opponent_result:
                cwl_day_emoji_and_number = f'❌ {cwl_day + 1}. '
            else:
                cwl_day_emoji_and_number = f'🟰 {cwl_day + 1}. '
        elif dm.of.state(cwl_war) == 'inWar':
            cwl_day_emoji_and_number = f'🗡 {cwl_day + 1}. '
        elif dm.of.state(cwl_war) == 'preparation':
            cwl_day_emoji_and_number = f'⚙️ {cwl_day + 1}. '
        else:
            cwl_day_emoji_and_number = f'❓ {cwl_day + 1}. '
        cwl_day_titles.append(f'{cwl_day_emoji_and_number}{cwl_clan['name']} vs {cwl_opponent['name']}')
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWLCallbackFactory(
            output_view=callback_data.output_view,
            update=True,
            show_opponent_info=callback_data.show_opponent_info,
            cwl_map_side=callback_data.cwl_map_side,
            cwl_attacks_side=callback_data.cwl_attacks_side
        ).pack()
    )
    button_rows = [[InlineKeyboardButton(
        text=cwl_day_title,
        callback_data=CWLCallbackFactory(
            output_view=button_output_view,
            cwl_day=i,
            show_opponent_info=callback_data.show_opponent_info,
            cwl_map_side=callback_data.cwl_map_side,
            cwl_attacks_side=callback_data.cwl_attacks_side
        ).pack()
    )] for i, cwl_day_title in enumerate(cwl_day_titles)]
    button_rows.append([update_button])
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


@router.message(Command('cwl_info'))
async def command_cwl_info(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await cwl_info(dm, None)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(CWLCallbackFactory.filter(F.output_view == OutputView.cwl_info_day))
async def callback_cwl_info(
        callback_query: CallbackQuery, callback_data: CWLCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cwl_info(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    if callback_data.update:
        await callback_query.answer('Сообщение обновлено')
    else:
        await callback_query.answer()


@router.message(Command('cwl_map'))
async def command_cwl_map(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await cwl_map(dm, None)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(CWLCallbackFactory.filter(F.output_view == OutputView.cwl_map_day))
async def callback_cwl_map(
        callback_query: CallbackQuery, callback_data: CWLCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cwl_map(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    if callback_data.update:
        await callback_query.answer('Сообщение обновлено')
    else:
        await callback_query.answer()


@router.message(Command('cwl_attacks'))
async def command_cwl_attacks(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await cwl_attacks(dm, None)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(CWLCallbackFactory.filter(F.output_view == OutputView.cwl_attacks_day))
async def callback_cwl_attacks(
        callback_query: CallbackQuery, callback_data: CWLCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cwl_attacks(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    if callback_data.update:
        await callback_query.answer('Сообщение обновлено')
    else:
        await callback_query.answer()


@router.message(Command('cwl_skips'))
async def command_cwl_skips(message: Message, dm: DatabaseManager) -> None:
    chat_id = await dm.get_group_chat_id(message)
    text, parse_mode, reply_markup = await cwl_skips(dm, chat_id, None)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(CWLCallbackFactory.filter(F.output_view == OutputView.cwl_skips_day))
async def callback_cwl_skips(
        callback_query: CallbackQuery, callback_data: CWLCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        chat_id = await dm.get_group_chat_id(callback_query.message)
        text, parse_mode, reply_markup = await cwl_skips(dm, chat_id, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    if callback_data.update:
        await callback_query.answer('Сообщение обновлено')
    else:
        await callback_query.answer()


@router.callback_query(CWLCallbackFactory.filter(F.output_view == OutputView.cwl_info_all_days))
@router.callback_query(CWLCallbackFactory.filter(F.output_view == OutputView.cwl_map_all_days))
@router.callback_query(CWLCallbackFactory.filter(F.output_view == OutputView.cwl_attacks_all_days))
@router.callback_query(CWLCallbackFactory.filter(F.output_view == OutputView.cwl_skips_all_days))
async def callback_cwl_all_days_list(
        callback_query: CallbackQuery, callback_data: CWLCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cwl_days_list(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    if callback_data.update:
        await callback_query.answer('Сообщение обновлено')
    else:
        await callback_query.answer()


@router.message(Command('cwl_ping'))
async def command_cwl_ping(message: Message, dm: DatabaseManager) -> None:
    user_can_ping_group_members = await dm.can_user_ping_group_members(message.chat.id, message.from_user.id)
    if message.chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await message.reply(text=f'Эта команда работает только в группах')
    elif not user_can_ping_group_members:
        await message.reply(text=f'У вас нет прав на использование этой команды')
    else:
        chat_id = await dm.get_group_chat_id(message)
        text, parse_mode, reply_markup = await cwl_ping(dm, chat_id)
        await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)


@router.message(Command('cwl_clans'))
async def command_cwl_clans(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await cwl_clans(dm)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(CWLCallbackFactory.filter(F.output_view == OutputView.cwl_clans))
async def callback_cwl_clans(
        callback_query: CallbackQuery, callback_data: CWLCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cwl_clans(dm)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    if callback_data.update:
        await callback_query.answer('Сообщение обновлено')
    else:
        await callback_query.answer()
