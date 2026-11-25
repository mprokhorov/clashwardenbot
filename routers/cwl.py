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

CWL_PAGE_SIZE = 10


class CWLMapSide(IntEnum):
    clan = auto()
    opponent = auto()


class CWLAttacksSide(IntEnum):
    clan = auto()
    opponent = auto()


class CWLListOrder(IntEnum):
    by_trophies = auto()
    by_town_hall_and_heroes = auto()


class OutputView(IntEnum):
    cwl_info_day = auto()
    cwl_info_all_days = auto()
    cwl_attacks_day = auto()
    cwl_attacks_all_days = auto()
    cwl_map_day = auto()
    cwl_map_all_days = auto()
    cwl_skips_day = auto()
    cwl_skips_all_days = auto()
    cwl_list = auto()
    cwl_clans = auto()
    cwl_rating_list = auto()
    cwl_rating_choose = auto()
    cwl_rating_details = auto()
    cwl_rating_rules = auto()
    cwl_info_all_seasons = auto()
    cwl_map_all_seasons = auto()
    cwl_attacks_all_seasons = auto()
    cwl_skips_all_seasons = auto()
    cwl_rating_all_seasons = auto()
    cwl_clans_all_seasons = auto()


class CWLCallbackFactory(CallbackData, prefix='cwl'):
    output_view: OutputView
    update: bool = False
    show_opponent_info: Optional[bool] = None
    cwl_day: Optional[int] = None
    cwl_map_side: Optional[CWLMapSide] = None
    cwl_attacks_side: Optional[CWLAttacksSide] = None
    player_tag: Optional[str] = None
    cwl_list_order: Optional[CWLListOrder] = None
    show_skips: Optional[bool] = None
    count_bonus_points: Optional[bool] = None
    cwl_season: Optional[str] = None
    page: Optional[int] = None


def is_double_cwl_month(season: str, seasons: list[str]) -> bool:
    return sum(1 for s in seasons if s[:7] == season[:7]) >= 2


async def resolve_cwl_season(
        dm: DatabaseManager, callback_data: Optional[CWLCallbackFactory]
) -> tuple[Optional[str], list[str], Optional[str]]:
    seasons = await dm.load_clan_war_league_seasons()
    selected_season = callback_data.cwl_season if callback_data is not None else None
    if selected_season is not None:
        return selected_season, seasons, selected_season
    return (seasons[-1] if seasons else None), seasons, None


async def load_cwl_day_and_wars(
        dm: DatabaseManager, cwl_season: Optional[str], requested_day: Optional[int]
) -> tuple[Optional[int], Optional[dict], list[dict]]:
    if cwl_season is None:
        return None, None, []
    cwl_wars = await dm.load_clan_war_league_own_wars(cwl_season) or []
    if not cwl_wars:
        return None, None, []
    if requested_day is not None and 0 <= requested_day < len(cwl_wars):
        return requested_day, cwl_wars[requested_day], cwl_wars
    for state in ['inWar', 'preparation', 'warEnded']:
        for day in range(len(cwl_wars) - 1, -1, -1):
            if dm.of.state(cwl_wars[day]) == state:
                return day, cwl_wars[day], cwl_wars
    return 0, cwl_wars[0], cwl_wars


def build_cwl_season_nav_row(
        dm: DatabaseManager,
        target_view: OutputView,
        all_seasons_view: OutputView,
        cwl_season: Optional[str],
        seasons: list[str],
        selected_season: Optional[str],
        back_cwl_day: Optional[int] = None,
        **cb_kwargs
) -> list[InlineKeyboardButton]:
    if not seasons:
        return []
    nav_row = []
    season_index = seasons.index(cwl_season) if cwl_season in seasons else None
    if season_index is not None and season_index > 0:
        prev_season = seasons[season_index - 1]
        nav_row.append(InlineKeyboardButton(
            text=f'⬅️ {dm.of.short_season(prev_season, is_double_cwl_month(prev_season, seasons))}',
            callback_data=CWLCallbackFactory(
                output_view=target_view,
                cwl_season=prev_season,
                **cb_kwargs
            ).pack()
        ))
    if season_index is not None and season_index < len(seasons) - 1:
        next_season = seasons[season_index + 1]
        nav_row.append(InlineKeyboardButton(
            text=f'➡️ {dm.of.short_season(next_season, is_double_cwl_month(next_season, seasons))}',
            callback_data=CWLCallbackFactory(
                output_view=target_view,
                cwl_season=next_season,
                **cb_kwargs
            ).pack()
        ))
    nav_row.append(InlineKeyboardButton(
        text='🧾 Все сезоны',
        callback_data=CWLCallbackFactory(
            output_view=all_seasons_view,
            cwl_season=selected_season,
            cwl_day=back_cwl_day,
            page=0,
            **cb_kwargs
        ).pack()
    ))
    return nav_row


async def cwl_info(
        dm: DatabaseManager, callback_data: Optional[CWLCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    cwl_season, seasons, selected_season = await resolve_cwl_season(dm, callback_data)
    requested_day = callback_data.cwl_day if callback_data is not None else None
    cwl_day, cwlw, cwl_wars = await load_cwl_day_and_wars(dm, cwl_season, requested_day)
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
                output_view=OutputView.cwl_info_day, show_opponent_info=False,
                cwl_day=cwl_day, cwl_season=selected_season
            ).pack()
        )
    else:
        opponent_info_button = InlineKeyboardButton(
            text='🔽 Развернуть',
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_info_day, show_opponent_info=True,
                cwl_day=cwl_day, cwl_season=selected_season
            ).pack()
        )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_info_day, update=True, show_opponent_info=show_opponent_info,
            cwl_day=cwl_day, cwl_season=selected_season
        ).pack()
    )
    show_half = is_double_cwl_month(cwl_season, seasons) if cwl_season is not None else False
    if dm.of.state(cwlw) in ['preparation']:
        war_win_streak = await dm.load_war_win_streak(cwlw['opponent']['tag'])
        cw_log = await dm.load_clan_war_log(cwlw['opponent']['tag'])
        text += dm.of.cwlw_preparation(cwlw, cwl_season, show_half, cwl_day, show_opponent_info, war_win_streak, cw_log)
        button_upper_row.append(opponent_info_button)
        button_upper_row.append(update_button)
    elif dm.of.state(cwlw) in ['inWar', 'warEnded']:
        war_win_streak = await dm.load_war_win_streak(cwlw['opponent']['tag'])
        cw_log = await dm.load_clan_war_log(cwlw['opponent']['tag'])
        text += dm.of.cwlw_in_war_or_war_ended(cwlw, cwl_season, show_half, cwl_day, show_opponent_info, war_win_streak, cw_log)
        button_upper_row.append(opponent_info_button)
        button_upper_row.append(update_button)
    else:
        text += f'Информация об ЛВК отсутствует\n'
        button_upper_row.append(update_button)
    if cwlw is not None:
        previous_cwl_day_button = InlineKeyboardButton(
            text=f'⬅️ День {cwl_day}',
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_info_day, show_opponent_info=show_opponent_info,
                cwl_day=cwl_day - 1, cwl_season=selected_season
            ).pack()
        )
        next_cwl_day_button = InlineKeyboardButton(
            text=f'➡️ День {cwl_day + 2}',
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_info_day, show_opponent_info=show_opponent_info,
                cwl_day=cwl_day + 1, cwl_season=selected_season
            ).pack()
        )
        all_cwl_days_button = InlineKeyboardButton(
            text='🧾 Все дни',
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_info_all_days, show_opponent_info=show_opponent_info,
                cwl_season=selected_season
            ).pack()
        )
        if cwl_day > 0:
            button_lower_row.append(previous_cwl_day_button)
        if cwl_day < len(cwl_wars) - 1:
            button_lower_row.append(next_cwl_day_button)
        button_lower_row.append(all_cwl_days_button)
    season_nav_row = build_cwl_season_nav_row(
        dm, OutputView.cwl_info_day, OutputView.cwl_info_all_seasons,
        cwl_season, seasons, selected_season, back_cwl_day=cwl_day,
        show_opponent_info=show_opponent_info
    )
    button_rows = []
    if len(button_upper_row) > 0:
        button_rows.append(button_upper_row)
    if len(button_lower_row) > 0:
        button_rows.append(button_lower_row)
    if len(season_nav_row) > 0:
        button_rows.append(season_nav_row)
    if len(button_rows) > 0:
        keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    else:
        keyboard = None
    return text, ParseMode.HTML, keyboard


async def cwl_map(
        dm: DatabaseManager, callback_data: Optional[CWLCallbackFactory], chat_id: int
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    cwl_season, seasons, selected_season = await resolve_cwl_season(dm, callback_data)
    requested_day = callback_data.cwl_day if callback_data is not None else None
    cwl_day, cwlw, cwl_wars = await load_cwl_day_and_wars(dm, cwl_season, requested_day)
    if callback_data is not None and callback_data.cwl_map_side is not None:
        cwl_map_side = callback_data.cwl_map_side
    else:
        cwl_map_side = CWLMapSide.opponent
    if callback_data is not None and callback_data.show_skips is not None:
        show_skips = callback_data.show_skips
    else:
        show_skips = False
    text = (
        f'<b>🗺️ Карта ЛВК</b>\n'
        f'\n'
    )
    button_upper_row = []
    button_lower_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_map_day, update=True, cwl_day=cwl_day,
            cwl_map_side=cwl_map_side, show_skips=show_skips, cwl_season=selected_season
        ).pack()
    )
    clan_side_button = InlineKeyboardButton(
        text='↔️ Карта клана',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_map_day, cwl_day=cwl_day,
            cwl_map_side=CWLMapSide.clan, show_skips=show_skips, cwl_season=selected_season
        ).pack()
    )
    opponent_side_button = InlineKeyboardButton(
        text='↔️ Карта противника',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_map_day, cwl_day=cwl_day,
            cwl_map_side=CWLMapSide.opponent, show_skips=show_skips, cwl_season=selected_season
        ).pack()
    )
    hide_skips_button = InlineKeyboardButton(
        text='🔼 Свернуть',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_map_day, cwl_day=cwl_day,
            cwl_map_side=cwl_map_side, show_skips=False, cwl_season=selected_season
        ).pack()
    )
    show_skips_button = InlineKeyboardButton(
        text='🔽 Развернуть',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_map_day, cwl_day=cwl_day,
            cwl_map_side=cwl_map_side, show_skips=True, cwl_season=selected_season
        ).pack()
    )
    show_half = is_double_cwl_month(cwl_season, seasons) if cwl_season is not None else False
    if dm.of.state(cwlw) in ['preparation']:
        text += dm.of.cwlw_preparation(cwlw, cwl_season, show_half, cwl_day, False, None, None)
        button_upper_row.append(update_button)
    elif dm.of.state(cwlw) in ['inWar', 'warEnded']:
        clan_map_position_by_player = dm.of.calculate_map_positions(cwlw['clan']['members'])
        opponent_map_position_by_player = dm.of.calculate_map_positions(cwlw['opponent']['members'])
        text += (
            f'{dm.of.cwlw_in_war_or_war_ended(cwlw, cwl_season, show_half, cwl_day, False, None, None)}'
            f'\n'
        )
        if cwl_map_side == CWLMapSide.opponent:
            text += 'Карта противника:\n'
            text += dm.of.get_map(
                clan_map_position_by_player, opponent_map_position_by_player, cwlw['clan'], cwlw['opponent']
            )
            button_upper_row.append(clan_side_button)
            if show_skips:
                cwlw_members = []
                for cwlw_member in cwlw['clan']['members']:
                    cwlw_members.append(
                        WarMember(
                            player_tag=cwlw_member['tag'], attacks_spent=len(cwlw_member.get('attacks', [])), attacks_limit=1
                        )
                    )
                text += (
                    f'\n'
                    f'\n'
                    f'Не проатаковавшие:'
                    f'\n'
                    f'{await dm.skips(chat_id=chat_id, players=cwlw_members, ping=False, desired_attacks_spent=1)}'
                )
                button_upper_row.append(hide_skips_button)
            else:
                button_upper_row.append(show_skips_button)
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
                output_view=OutputView.cwl_map_day, cwl_day=cwl_day - 1,
                cwl_map_side=cwl_map_side, show_skips=show_skips, cwl_season=selected_season
            ).pack()
        )
        next_cwl_day_button = InlineKeyboardButton(
            text=f'➡️ День {cwl_day + 2}',
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_map_day, cwl_day=cwl_day + 1,
                cwl_map_side=cwl_map_side, show_skips=show_skips, cwl_season=selected_season
            ).pack()
        )
        all_cwl_days_button = InlineKeyboardButton(
            text='🧾 Все дни',
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_map_all_days,
                cwl_map_side=cwl_map_side, show_skips=show_skips, cwl_season=selected_season
            ).pack()
        )
        if cwl_day > 0:
            button_lower_row.append(previous_cwl_day_button)
        if cwl_day < len(cwl_wars) - 1:
            button_lower_row.append(next_cwl_day_button)
        button_lower_row.append(all_cwl_days_button)
    season_nav_row = build_cwl_season_nav_row(
        dm, OutputView.cwl_map_day, OutputView.cwl_map_all_seasons,
        cwl_season, seasons, selected_season, back_cwl_day=cwl_day,
        cwl_map_side=cwl_map_side, show_skips=show_skips
    )
    button_rows = []
    if len(button_upper_row) > 0:
        button_rows.append(button_upper_row)
    if len(button_lower_row) > 0:
        button_rows.append(button_lower_row)
    if len(season_nav_row) > 0:
        button_rows.append(season_nav_row)
    if len(button_rows) > 0:
        keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    else:
        keyboard = None
    return text, ParseMode.HTML, keyboard


async def cwl_attacks(
        dm: DatabaseManager, callback_data: Optional[CWLCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    cwl_season, seasons, selected_season = await resolve_cwl_season(dm, callback_data)
    requested_day = callback_data.cwl_day if callback_data is not None else None
    cwl_day, cwlw, cwl_wars = await load_cwl_day_and_wars(dm, cwl_season, requested_day)
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
            output_view=OutputView.cwl_attacks_day, update=True, cwl_day=cwl_day,
            cwl_attacks_side=cwl_attacks_side, cwl_season=selected_season
        ).pack()
    )
    opponent_attacks_button = InlineKeyboardButton(
        text='↔️ Атаки противника',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_attacks_day, cwl_day=cwl_day,
            cwl_attacks_side=CWLAttacksSide.opponent, cwl_season=selected_season
        ).pack()
    )
    clan_attacks_button = InlineKeyboardButton(
        text='↔️ Атаки клана',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_attacks_day, cwl_day=cwl_day,
            cwl_attacks_side=CWLAttacksSide.clan, cwl_season=selected_season
        ).pack()
    )
    show_half = is_double_cwl_month(cwl_season, seasons) if cwl_season is not None else False
    if dm.of.state(cwlw) in ['preparation']:
        if cwl_attacks_side == CWLAttacksSide.clan:
            rows = await dm.acquired_connection.fetch('''
                SELECT
                    player_tag, player_name,
                    town_hall_level, barbarian_king_level, archer_queen_level, minion_prince_level, grand_warden_level, royal_champion_level, dragon_duke_level
                FROM player
                WHERE clan_tag = $1
            ''', dm.clan_tag)
            clan_map_position_by_player = dm.of.calculate_map_positions(cwlw['clan']['members'])
            text += (
                f'{dm.of.cwlw_preparation(cwlw, cwl_season, show_half, cwl_day, False, None, None)}'
                f'\n'
                f'Список участников дня ЛВК клана:\n'
                f'{dm.of.war_members(cwlw['clan']['members'], clan_map_position_by_player, rows)}'
            )
            button_upper_row.append(opponent_attacks_button)
        else:
            rows = await dm.acquired_connection.fetch('''
                SELECT
                    player_tag, player_name,
                    town_hall_level, barbarian_king_level, archer_queen_level, minion_prince_level, grand_warden_level, royal_champion_level, dragon_duke_level
                FROM opponent_player
                WHERE clan_tag = $1
            ''', cwlw['opponent']['tag'])
            opponent_map_position_by_player = dm.of.calculate_map_positions(cwlw['opponent']['members'])
            text += (
                f'{dm.of.cwlw_preparation(cwlw, cwl_season, show_half, cwl_day, False, None, None)}'
                f'\n'
                f'Список участников дня ЛВК противника:\n'
                f'{dm.of.war_members(cwlw['opponent']['members'], opponent_map_position_by_player, rows)}'
            )
            button_upper_row.append(clan_attacks_button)
        button_upper_row.append(update_button)
    elif dm.of.state(cwlw) in ['inWar', 'warEnded']:
        clan_map_position_by_player = dm.of.calculate_map_positions(cwlw['clan']['members'])
        opponent_map_position_by_player = dm.of.calculate_map_positions(cwlw['opponent']['members'])
        text += (
            f'{dm.of.cwlw_in_war_or_war_ended(cwlw, cwl_season, show_half, cwl_day, False, None, None)}'
            f'\n'
        )
        if cwl_attacks_side == CWLAttacksSide.clan:
            text += (
                f'Атаки клана:\n'
                f'\n'
                f'{dm.of.get_attacks(
                    clan_map_position_by_player, opponent_map_position_by_player, cwlw['clan'], cwlw['opponent'], 1
                )}'
            )
            button_upper_row.append(opponent_attacks_button)
        else:
            text += (
                f'Атаки противника:\n'
                f'\n'
                f'{dm.of.get_attacks(
                    opponent_map_position_by_player, clan_map_position_by_player, cwlw['opponent'], cwlw['clan'], 1
                )}'
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
                output_view=OutputView.cwl_attacks_day, cwl_day=cwl_day - 1,
                cwl_attacks_side=cwl_attacks_side, cwl_season=selected_season
            ).pack()
        )
        next_cwl_day_button = InlineKeyboardButton(
            text=f'➡️ День {cwl_day + 2}',
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_attacks_day, cwl_day=cwl_day + 1,
                cwl_attacks_side=cwl_attacks_side, cwl_season=selected_season
            ).pack()
        )
        all_cwl_days_button = InlineKeyboardButton(
            text='🧾 Все дни',
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_attacks_all_days,
                cwl_attacks_side=cwl_attacks_side, cwl_season=selected_season
            ).pack()
        )
        if cwl_day > 0:
            button_lower_row.append(previous_cwl_day_button)
        if cwl_day < len(cwl_wars) - 1:
            button_lower_row.append(next_cwl_day_button)
        button_lower_row.append(all_cwl_days_button)
    season_nav_row = build_cwl_season_nav_row(
        dm, OutputView.cwl_attacks_day, OutputView.cwl_attacks_all_seasons,
        cwl_season, seasons, selected_season, back_cwl_day=cwl_day,
        cwl_attacks_side=cwl_attacks_side
    )
    button_rows = []
    if len(button_upper_row) > 0:
        button_rows.append(button_upper_row)
    if len(button_lower_row) > 0:
        button_rows.append(button_lower_row)
    if len(season_nav_row) > 0:
        button_rows.append(season_nav_row)
    if len(button_rows) > 0:
        keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    else:
        keyboard = None
    return text, ParseMode.HTML, keyboard


async def cwl_rating_list(
        dm: DatabaseManager, callback_data: Optional[CWLCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    if callback_data is not None and callback_data.count_bonus_points is not None:
        count_bonus_points = callback_data.count_bonus_points
    else:
        count_bonus_points = True
    text = (
        f'<b>🪙 Рейтинг участников ЛВК ({'с бонусами' if count_bonus_points else 'без бонусов'})</b>\n'
        f'\n'
    )
    if not await dm.load_clan_war_league_rating_config():
        text += f'Рейтинг выключен'
        return text, ParseMode.HTML, None
    cwl_season, seasons, selected_season = await resolve_cwl_season(dm, callback_data)
    cwlws = await dm.load_clan_war_league_own_wars(cwl_season) if cwl_season is not None else None
    if not cwlws:
        text += f'Информация об ЛВК отсутствует\n'
        season_nav_row = build_cwl_season_nav_row(
            dm, OutputView.cwl_rating_list, OutputView.cwl_rating_all_seasons,
            cwl_season, seasons, selected_season, count_bonus_points=count_bonus_points
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[season_nav_row]) if season_nav_row else None
        return text, ParseMode.HTML, keyboard
    show_half = is_double_cwl_month(cwl_season, seasons)
    player_tags = await dm.get_cwl_ratings(cwl_season, cwlws, count_bonus_points)
    text += (
        f'Сезон ЛВК: {dm.of.season(cwl_season, show_half)}\n'
        f'\n'
    )
    details_button = InlineKeyboardButton(
        text='📋 Подробнее',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_rating_choose, count_bonus_points=count_bonus_points, cwl_season=selected_season
        ).pack()
    )
    count_bonus_points_button = InlineKeyboardButton(
        text='🪙 Без бонусов' if count_bonus_points else '🪙 С бонусами',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_rating_list, count_bonus_points=not count_bonus_points, cwl_season=selected_season
        ).pack()
    )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_rating_list, count_bonus_points=count_bonus_points,
            cwl_season=selected_season, update=True
        ).pack()
    )
    rules_button = InlineKeyboardButton(
        text='❓ Правила',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_rating_rules, count_bonus_points=count_bonus_points, cwl_season=selected_season
        ).pack()
    )
    for i, (player_tag, r) in enumerate(sorted(player_tags.items(), key=lambda x: x[1].total_points, reverse=True)):
        text += f'{i + 1}. {dm.of.to_html(dm.load_name(player_tag))}: {dm.of.format_and_rstrip(r.total_points, 3)} 🪙\n'
    if len(player_tags) == 0:
        text += f'Список пуст\n'
    button_rows = [[details_button, count_bonus_points_button, rules_button], [update_button]]
    season_nav_row = build_cwl_season_nav_row(
        dm, OutputView.cwl_rating_list, OutputView.cwl_rating_all_seasons,
        cwl_season, seasons, selected_season, count_bonus_points=count_bonus_points
    )
    if season_nav_row:
        button_rows.append(season_nav_row)
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


async def cwl_rating_choose(
        dm: DatabaseManager, callback_data: Optional[CWLCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    if callback_data is not None and callback_data.count_bonus_points is not None:
        count_bonus_points = callback_data.count_bonus_points
    else:
        count_bonus_points = True
    text = (
        f'<b>🪙 Рейтинг участников ЛВК ({'с бонусами' if count_bonus_points else 'без бонусов'})</b>\n'
        f'\n'
    )
    if not await dm.load_clan_war_league_rating_config():
        text += f'Рейтинг выключен'
        return text, ParseMode.HTML, None
    cwl_season, seasons, selected_season = await resolve_cwl_season(dm, callback_data)
    cwlws = await dm.load_clan_war_league_own_wars(cwl_season) if cwl_season is not None else None
    if not cwlws:
        text += f'Информация об ЛВК отсутствует\n'
        return text, ParseMode.HTML, None
    show_half = is_double_cwl_month(cwl_season, seasons)
    text += (
        f'Сезон ЛВК: {dm.of.season(cwl_season, show_half)}\n'
        f'\n'
        f'Выберите участника ЛВК:'
    )
    player_tags = await dm.get_cwl_ratings(cwl_season, cwlws, count_bonus_points)
    button_rows = [[
        InlineKeyboardButton(
            text=f'{dm.of.bidi_isolate(dm.load_name(player_tag))}: {dm.of.format_and_rstrip(r.total_points, 3)} 🪙\n',
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_rating_details,
                count_bonus_points=count_bonus_points,
                player_tag=player_tag,
                cwl_season=selected_season
            ).pack()
        )] for i, (player_tag, r) in enumerate(sorted(player_tags.items(), key=lambda x: x[1].total_points, reverse=True))
    ]
    back_button = InlineKeyboardButton(
        text='⬅️ Назад',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_rating_list, count_bonus_points=count_bonus_points, cwl_season=selected_season
        ).pack()
    )
    count_bonus_points_button = InlineKeyboardButton(
        text='🪙 Без бонусов' if count_bonus_points else '🪙 С бонусами',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_rating_choose, count_bonus_points=not count_bonus_points, cwl_season=selected_season
        ).pack()
    )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_rating_choose, count_bonus_points=count_bonus_points,
            cwl_season=selected_season, update=True
        ).pack()
    )
    button_rows.append([back_button, count_bonus_points_button, update_button])
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


async def cwl_rating_details(
        dm: DatabaseManager, callback_data: Optional[CWLCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    if callback_data is not None and callback_data.count_bonus_points is not None:
        count_bonus_points = callback_data.count_bonus_points
    else:
        count_bonus_points = True
    text = (
        f'<b>🪙 Рейтинг игрока {dm.of.to_html(dm.load_name(callback_data.player_tag))} ({'с бонусами' if count_bonus_points else 'без бонусов'})</b>\n'
        f'\n'
    )
    if not await dm.load_clan_war_league_rating_config():
        text += f'Рейтинг выключен'
        return text, ParseMode.HTML, None
    cwl_season, seasons, selected_season = await resolve_cwl_season(dm, callback_data)
    cwlws = await dm.load_clan_war_league_own_wars(cwl_season) if cwl_season is not None else None
    if not cwlws:
        text += f'Информация об ЛВК отсутствует\n'
        return text, ParseMode.HTML, None
    show_half = is_double_cwl_month(cwl_season, seasons)
    wars_ended = sum(dm.of.state(cwlw) == 'warEnded' for cwlw in cwlws)
    player_tags = await dm.get_cwl_ratings(cwl_season, cwlws, count_bonus_points)
    back_button = InlineKeyboardButton(
        text='⬅️ Назад',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_rating_choose, count_bonus_points=count_bonus_points, cwl_season=selected_season
        ).pack()
    )
    count_bonus_points_button = InlineKeyboardButton(
        text='🪙 Без бонусов' if count_bonus_points else '🪙 С бонусами',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_rating_details, player_tag=callback_data.player_tag,
            count_bonus_points=not count_bonus_points, cwl_season=selected_season
        ).pack()
    )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_rating_details,
            player_tag=callback_data.player_tag,
            count_bonus_points=count_bonus_points,
            cwl_season=selected_season,
            update=True
        ).pack()
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[back_button, count_bonus_points_button, update_button]])
    r = player_tags.get(callback_data.player_tag)
    if r is None:
        text += f'Информация об игроке отсутствует\n'
        return text, ParseMode.HTML, keyboard
    text += (
        f'Сезон ЛВК: {dm.of.season(cwl_season, show_half)}\n'
        f'\n'
        f'Итого баллов: {dm.of.format_and_rstrip(r.total_points, 3)} 🪙\n\n'
    )
    if len(r.attack_new_stars) > 0:
        text += (
            f'Награды за атаки: {dm.of.format_and_rstrip(
                r.total_attack_new_stars_points +
                r.total_attack_destruction_percentage_points +
                r.total_attack_map_position_points, 3
            )} 🪙\n'
            f'{dm.of.format_and_rstrip(r.total_attack_new_stars_points, 3)} 🪙 '
            f'({', '.join(map(lambda x: f'{x} ⭐', r.attack_new_stars))})\n'
            f'{dm.of.format_and_rstrip(r.total_attack_destruction_percentage_points, 3)} 🪙 '
            f'({', '.join(map(lambda x: f'{x}%', r.attack_destruction_percentage))})\n'
            f'{dm.of.format_and_rstrip(r.total_attack_map_position_points, 3)} 🪙 '
            f'({', '.join(map(lambda x: f'#{x}', r.attack_map_position))})\n\n'
        )
    if r.total_attack_skips_points != 0:
        text += (
            f'Штраф за пропуски: {dm.of.format_and_rstrip(r.total_attack_skips_points, 3)} 🪙 '
            f'({dm.of.skips_count_to_text(wars_ended - len(r.attack_new_stars))})\n\n'
        )
    if len(r.defense_stars) > 0:
        text += (
            f'Награды за оборону: {dm.of.format_and_rstrip(
                r.total_defense_stars_points +
                r.total_defense_destruction_percentage_points, 3
            )} 🪙\n'
            f'{dm.of.format_and_rstrip(r.total_defense_stars_points, 3)} 🪙 '
            f'({', '.join(map(lambda x: f'{x} ⭐', r.defense_stars))})\n'
            f'{dm.of.format_and_rstrip(r.total_defense_destruction_percentage_points, 3)} 🪙 '
            f'({', '.join(map(lambda x: f'{x}%', r.defense_destruction_percentage))})\n\n'
        )
    if r.total_bonus_points != 0:
        text += f'Бонусы: {dm.of.format_and_rstrip(r.total_bonus_points, 3)} 🪙'
    return text, ParseMode.HTML, keyboard


async def cwl_rating_rules(
        dm: DatabaseManager, callback_data: Optional[CWLCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    selected_season = callback_data.cwl_season if callback_data is not None else None
    count_bonus_points = callback_data.count_bonus_points if callback_data is not None else None
    text = f'<b>🪙 Правила рейтинга участников ЛВК</b>\n'
    if not await dm.load_clan_war_league_rating_config():
        text += (
            f'\n'
            f'Рейтинг выключен'
        )
        return text, ParseMode.HTML, None
    text += dm.of.full_dedent(f'''
        <b>Награды за атаки:</b>
        За атаку на 3 звезды даётся {dm.of.points_count_to_text(dm.cwl_rating_config.attack_stars_points[3])}, на 2 звезды — {dm.of.points_count_to_text(dm.cwl_rating_config.attack_stars_points[2])}, на 1 звезду — {dm.of.points_count_to_text(dm.cwl_rating_config.attack_stars_points[1])}, за 0 звезд или пропуск атаки — {dm.of.points_count_to_text(dm.cwl_rating_config.attack_stars_points[0])}. При этом количество звёзд определяется как разница между результатом атаки и последней атакой (в случае, если игрок атаковал уже атакованную базу). Также за каждую атаку начисляются баллы по формуле: [процент разрушения] * {dm.of.points_count_to_text(dm.cwl_rating_config.attack_destruction_points)}. Вне зависимости от результата атаки начисляются баллы по формуле: (31 - [номер места противника на карте]) * {dm.of.points_count_to_text(dm.cwl_rating_config.attack_map_position_points)}.
        
        <b>Штрафы за пропуски:</b>
        За неучастие в раундах ЛВК штрафы начисляются в зависимости от количества пропусков: 0 пропусков — {dm.of.points_count_to_text(dm.cwl_rating_config.attack_skip_points[0])}, 1 пропуск — {dm.of.points_count_to_text(dm.cwl_rating_config.attack_skip_points[1])}, 2 пропуска — {dm.of.points_count_to_text(dm.cwl_rating_config.attack_skip_points[2])}, 3 пропуска — {dm.of.points_count_to_text(dm.cwl_rating_config.attack_skip_points[3])}, 4 пропуска — {dm.of.points_count_to_text(dm.cwl_rating_config.attack_skip_points[4])}, 5 пропусков — {dm.of.points_count_to_text(dm.cwl_rating_config.attack_skip_points[5])}, 6 пропусков — {dm.of.points_count_to_text(dm.cwl_rating_config.attack_skip_points[6])}, 7 пропусков — {dm.of.points_count_to_text(dm.cwl_rating_config.attack_skip_points[7])}.
        
        <b>Награды за оборону:</b>
        Если базу игрока атаковали на 0 звёзд, ему начисляется {dm.of.points_count_to_text(dm.cwl_rating_config.defense_stars_points[0])}, на 1 звезду — {dm.of.points_count_to_text(dm.cwl_rating_config.defense_stars_points[1])}, на 2 звезды — {dm.of.points_count_to_text(dm.cwl_rating_config.defense_stars_points[2])}. Также (в случае, если базу игрока атаковали) начисляются бонусы по формуле: (100 - [процент разрушения]) * {dm.of.points_count_to_text(dm.cwl_rating_config.defense_destruction_points)}.
        ''')
    back_button = InlineKeyboardButton(
        text='⬅️ Назад',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_rating_list, count_bonus_points=count_bonus_points, cwl_season=selected_season
        ).pack()
    )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_rating_rules, count_bonus_points=count_bonus_points,
            cwl_season=selected_season, update=True
        ).pack()
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[back_button, update_button]])
    return text, ParseMode.HTML, keyboard


async def cwl_skips(
        dm: DatabaseManager, chat_id: int, callback_data: Optional[CWLCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    cwl_season, seasons, selected_season = await resolve_cwl_season(dm, callback_data)
    requested_day = callback_data.cwl_day if callback_data is not None else None
    cwl_day, cwlw, cwl_wars = await load_cwl_day_and_wars(dm, cwl_season, requested_day)
    text = (
        f'<b>🕒 Не проатаковавшие в ЛВК</b>\n'
        f'\n'
    )
    button_upper_row = []
    button_lower_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_skips_day, update=True, cwl_day=cwl_day, cwl_season=selected_season
        ).pack()
    )
    show_half = is_double_cwl_month(cwl_season, seasons) if cwl_season is not None else False
    if dm.of.state(cwlw) in ['preparation']:
        text += dm.of.cwlw_preparation(cwlw, cwl_season, show_half, cwl_day, False, None, None)
        button_upper_row.append(update_button)
    elif dm.of.state(cwlw) in ['inWar', 'warEnded']:
        cwlw_members = []
        for cwlw_member in cwlw['clan']['members']:
            cwlw_members.append(
                WarMember(
                    player_tag=cwlw_member['tag'], attacks_spent=len(cwlw_member.get('attacks', [])), attacks_limit=1
                )
            )
        text += (
            f'{dm.of.cwlw_in_war_or_war_ended(cwlw, cwl_season, show_half, cwl_day, False, None, None)}'
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
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_skips_day, cwl_day=cwl_day - 1, cwl_season=selected_season
            ).pack()
        )
        next_cwl_day_button = InlineKeyboardButton(
            text=f'➡️ День {cwl_day + 2}',
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_skips_day, cwl_day=cwl_day + 1, cwl_season=selected_season
            ).pack()
        )
        all_cwl_days_button = InlineKeyboardButton(
            text='🧾 Все дни',
            callback_data=CWLCallbackFactory(
                output_view=OutputView.cwl_skips_all_days, cwl_season=selected_season
            ).pack()
        )
        if cwl_day > 0:
            button_lower_row.append(previous_cwl_day_button)
        if cwl_day < len(cwl_wars) - 1:
            button_lower_row.append(next_cwl_day_button)
        button_lower_row.append(all_cwl_days_button)
    season_nav_row = build_cwl_season_nav_row(
        dm, OutputView.cwl_skips_day, OutputView.cwl_skips_all_seasons,
        cwl_season, seasons, selected_season, back_cwl_day=cwl_day
    )
    button_rows = []
    if len(button_upper_row) > 0:
        button_rows.append(button_upper_row)
    if len(button_lower_row) > 0:
        button_rows.append(button_lower_row)
    if len(season_nav_row) > 0:
        button_rows.append(season_nav_row)
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
        text += dm.of.cwlw_preparation(cwlw, cwl_season, await dm.get_season_cwl_amount(cwl_season) == 2, cwl_day, False, None, None)
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
            f'{dm.of.cwlw_in_war_or_war_ended(cwlw, cwl_season, await dm.get_season_cwl_amount(cwl_season) == 2, cwl_day, False, None, None)}'
            f'\n'
            f'{await dm.skips(chat_id=chat_id, players=cwlw_members, ping=True, desired_attacks_spent=1)}'
        )
    else:
        text += 'Информация об ЛВК отсутствует'
    return text, ParseMode.HTML, None


async def cwl_list(
        dm: DatabaseManager, callback_data: Optional[CWLCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    if callback_data is not None and callback_data.cwl_list_order is not None:
        cwl_list_order = callback_data.cwl_list_order
    else:
        cwl_list_order = CWLListOrder.by_town_hall_and_heroes
    button_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_list, update=True, cwl_list_order=cwl_list_order
        ).pack()
    )
    order_by_town_hall_and_heroes_button = InlineKeyboardButton(
        text='⬇️ По ТХ и героям',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_list, cwl_list_order=CWLListOrder.by_town_hall_and_heroes
        ).pack()
    )
    order_by_trophies_button = InlineKeyboardButton(
        text='⬇️ По трофеям',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_list, cwl_list_order=CWLListOrder.by_trophies
        ).pack()
    )
    if cwl_list_order == CWLListOrder.by_town_hall_and_heroes:
        rows = await dm.acquired_connection.fetch('''
            SELECT
                player_name,
                town_hall_level, barbarian_king_level, archer_queen_level, minion_prince_level, grand_warden_level, royal_champion_level, dragon_duke_level
            FROM player
            WHERE clan_tag = $1 AND player.is_player_in_clan AND is_player_set_for_clan_war_league
            ORDER BY
                town_hall_level DESC,
                (barbarian_king_level + archer_queen_level + minion_prince_level + grand_warden_level + royal_champion_level + dragon_duke_level) DESC,
                player_name
        ''', dm.clan_tag)
        text = (
            f'<b>📋 Список участников ЛВК (⬇️ по ТХ и героям)</b>\n'
            f'\n'
        )
        button_row.append(order_by_trophies_button)
    else:
        rows = await dm.acquired_connection.fetch('''
            SELECT
                player_name,
                town_hall_level, barbarian_king_level, archer_queen_level, minion_prince_level, grand_warden_level, royal_champion_level, dragon_duke_level
            FROM player
            WHERE clan_tag = $1 AND player.is_player_in_clan AND is_player_set_for_clan_war_league
            ORDER BY home_village_trophies DESC
        ''', dm.clan_tag)
        text = (
            f'<b>📋 Список участников ЛВК (⬇️ по трофеям)</b>\n'
            f'\n'
        )
        button_row.append(order_by_town_hall_and_heroes_button)
    button_row.append(update_button)
    if len(rows) > 0:
        for i, row in enumerate(rows):
            text += (f'{i + 1}. {dm.of.to_html(row['player_name'])} {dm.of.get_player_info_with_emoji(
                row['town_hall_level'],
                row['barbarian_king_level'],
                row['archer_queen_level'],
                row['minion_prince_level'],
                row['grand_warden_level'],
                row['royal_champion_level'],
                row['dragon_duke_level']
            )}\n')
    else:
        text += 'Список пуст\n'
    keyboard = InlineKeyboardMarkup(inline_keyboard=[button_row])
    return text, ParseMode.HTML, keyboard


async def cwl_clans(
        dm: DatabaseManager, callback_data: Optional[CWLCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    cwl_season, seasons, selected_season = await resolve_cwl_season(dm, callback_data)
    cwl_wars = await dm.load_clan_war_league_last_day_wars(cwl_season) if cwl_season is not None else None
    text = (
        f'<b>📶 Уровни ТХ кланов в ЛВК</b>\n'
        f'\n'
    )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWLCallbackFactory(
            output_view=OutputView.cwl_clans, update=True, cwl_season=selected_season
        ).pack()
    )
    button_rows = [[update_button]]
    season_nav_row = build_cwl_season_nav_row(
        dm, OutputView.cwl_clans, OutputView.cwl_clans_all_seasons,
        cwl_season, seasons, selected_season
    )
    if season_nav_row:
        button_rows.append(season_nav_row)
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    if cwl_wars is None:
        text += 'Информация об ЛВК отсутствует'
        return text, ParseMode.HTML, keyboard
    show_half = is_double_cwl_month(cwl_season, seasons)
    text += (
        f'Сезон: {dm.of.season(cwl_season, show_half)}\n'
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
            cwl_members.append(
                ClanWarLeagueMember(
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
    cwl_season, seasons, selected_season = await resolve_cwl_season(dm, callback_data)
    view_config = {
        OutputView.cwl_info_all_days: ('⚔️ Информация об ЛВК', OutputView.cwl_info_day, OutputView.cwl_info_all_seasons),
        OutputView.cwl_map_all_days: ('🗺️ Карта ЛВК', OutputView.cwl_map_day, OutputView.cwl_map_all_seasons),
        OutputView.cwl_attacks_all_days: ('🗡️ Атаки в ЛВК', OutputView.cwl_attacks_day, OutputView.cwl_attacks_all_seasons),
        OutputView.cwl_skips_all_days: ('🕒 Не проатаковавшие в ЛВК', OutputView.cwl_skips_day, OutputView.cwl_skips_all_seasons)
    }
    title, button_output_view, all_seasons_view = view_config[callback_data.output_view]
    show_half = is_double_cwl_month(cwl_season, seasons) if cwl_season is not None else False
    if cwl_season is None:
        text = (
            f'<b>{title}</b>\n'
            f'\n'
            f'Информация об ЛВК отсутствует\n'
        )
        cwl_wars = []
    else:
        text = (
            f'<b>{title}</b>\n'
            f'\n'
            f'Сезон: {dm.of.season(cwl_season, show_half)}\n'
            f'\n'
            f'Выберите день:\n'
        )
        cwl_wars = await dm.load_clan_war_league_own_wars(cwl_season) or []
    preserved_kwargs = {
        'show_opponent_info': callback_data.show_opponent_info,
        'cwl_map_side': callback_data.cwl_map_side,
        'cwl_attacks_side': callback_data.cwl_attacks_side,
        'show_skips': callback_data.show_skips
    }
    cwl_day_titles = []
    for cwl_day, cwl_war in enumerate(cwl_wars):
        cwl_clan, cwl_opponent = cwl_war['clan'], cwl_war['opponent']
        emoji = dm.of.war_state_emoji(
            dm.of.state(cwl_war),
            cwl_clan.get('stars'), cwl_clan.get('destructionPercentage'),
            cwl_opponent.get('stars'), cwl_opponent.get('destructionPercentage')
        )
        cwl_day_emoji_and_number = f'{emoji} {cwl_day + 1}. ' if emoji else ''
        cwl_day_titles.append(
            f'{cwl_day_emoji_and_number}{dm.of.bidi_isolate(cwl_clan['name'])} vs {dm.of.bidi_isolate(cwl_opponent['name'])}'
        )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWLCallbackFactory(
            output_view=callback_data.output_view,
            update=True,
            cwl_season=selected_season,
            **preserved_kwargs
        ).pack()
    )
    button_rows = [[InlineKeyboardButton(
        text=cwl_day_title,
        callback_data=CWLCallbackFactory(
            output_view=button_output_view,
            cwl_day=i,
            cwl_season=selected_season,
            **preserved_kwargs
        ).pack()
    )] for i, cwl_day_title in enumerate(cwl_day_titles)]
    season_nav_row = build_cwl_season_nav_row(
        dm, callback_data.output_view, all_seasons_view,
        cwl_season, seasons, selected_season,
        **preserved_kwargs
    )
    if season_nav_row:
        button_rows.append(season_nav_row)
    button_rows.append([update_button])
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


async def cwl_seasons_list(
        dm: DatabaseManager, callback_data: CWLCallbackFactory
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    view_config = {
        OutputView.cwl_info_all_seasons: ('⚔️ Информация об ЛВК', OutputView.cwl_info_day),
        OutputView.cwl_map_all_seasons: ('🗺️ Карта ЛВК', OutputView.cwl_map_day),
        OutputView.cwl_attacks_all_seasons: ('🗡️ Атаки в ЛВК', OutputView.cwl_attacks_day),
        OutputView.cwl_skips_all_seasons: ('🕒 Не проатаковавшие в ЛВК', OutputView.cwl_skips_day),
        OutputView.cwl_rating_all_seasons: ('🪙 Рейтинг участников ЛВК', OutputView.cwl_rating_list),
        OutputView.cwl_clans_all_seasons: ('📶 Уровни ТХ кланов в ЛВК', OutputView.cwl_clans)
    }
    title, target_view = view_config[callback_data.output_view]
    seasons = await dm.load_clan_war_league_seasons()
    seasons_desc = list(reversed(seasons))
    total = len(seasons_desc)
    total_pages = max(1, (total + CWL_PAGE_SIZE - 1) // CWL_PAGE_SIZE)
    page = max(0, min(callback_data.page or 0, total_pages - 1))
    page_seasons = seasons_desc[page * CWL_PAGE_SIZE:(page + 1) * CWL_PAGE_SIZE]
    preserved_kwargs = {
        'show_opponent_info': callback_data.show_opponent_info,
        'cwl_map_side': callback_data.cwl_map_side,
        'cwl_attacks_side': callback_data.cwl_attacks_side,
        'show_skips': callback_data.show_skips,
        'count_bonus_points': callback_data.count_bonus_points
    }
    if total == 0:
        text = (
            f'<b>{title}</b>\n'
            f'\n'
            f'Информация об ЛВК отсутствует\n'
        )
    elif total_pages > 1:
        text = (
            f'<b>{title}</b>\n'
            f'\n'
            f'Выберите сезон (стр. {page + 1} / {total_pages}):\n'
        )
    else:
        text = (
            f'<b>{title}</b>\n'
            f'\n'
            f'Выберите сезон:\n'
        )
    button_rows = [[InlineKeyboardButton(
        text=dm.of.season(season, is_double_cwl_month(season, seasons)).capitalize(),
        callback_data=CWLCallbackFactory(
            output_view=target_view,
            cwl_season=season,
            **preserved_kwargs
        ).pack()
    )] for season in page_seasons]
    if total_pages > 1:
        pagination_row = []
        if page > 0:
            pagination_row.append(InlineKeyboardButton(
                text=f'⬅️ Стр. {page}',
                callback_data=CWLCallbackFactory(
                    output_view=callback_data.output_view,
                    cwl_season=callback_data.cwl_season,
                    cwl_day=callback_data.cwl_day,
                    page=page - 1,
                    **preserved_kwargs
                ).pack()
            ))
        if page < total_pages - 1:
            pagination_row.append(InlineKeyboardButton(
                text=f'➡️ Стр. {page + 2}',
                callback_data=CWLCallbackFactory(
                    output_view=callback_data.output_view,
                    cwl_season=callback_data.cwl_season,
                    cwl_day=callback_data.cwl_day,
                    page=page + 1,
                    **preserved_kwargs
                ).pack()
            ))
        button_rows.append(pagination_row)
    back_button = InlineKeyboardButton(
        text='⬅️ Назад',
        callback_data=CWLCallbackFactory(
            output_view=target_view,
            cwl_season=callback_data.cwl_season,
            cwl_day=callback_data.cwl_day,
            **preserved_kwargs
        ).pack()
    )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWLCallbackFactory(
            output_view=callback_data.output_view,
            update=True,
            cwl_season=callback_data.cwl_season,
            cwl_day=callback_data.cwl_day,
            page=page,
            **preserved_kwargs
        ).pack()
    )
    button_rows.append([back_button, update_button])
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
    if not user_is_message_owner and not callback_data.update:
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
    chat_id = await dm.get_group_chat_id(message)
    text, parse_mode, reply_markup = await cwl_map(dm, None, chat_id)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(CWLCallbackFactory.filter(F.output_view == OutputView.cwl_map_day))
async def callback_cwl_map(
        callback_query: CallbackQuery, callback_data: CWLCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner and not callback_data.update:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        chat_id = await dm.get_group_chat_id(callback_query.message)
        text, parse_mode, reply_markup = await cwl_map(dm, callback_data, chat_id)
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
    if not user_is_message_owner and not callback_data.update:
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
    if not user_is_message_owner and not callback_data.update:
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
    if not user_is_message_owner and not callback_data.update:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cwl_days_list(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.callback_query(CWLCallbackFactory.filter(F.output_view == OutputView.cwl_info_all_seasons))
@router.callback_query(CWLCallbackFactory.filter(F.output_view == OutputView.cwl_map_all_seasons))
@router.callback_query(CWLCallbackFactory.filter(F.output_view == OutputView.cwl_attacks_all_seasons))
@router.callback_query(CWLCallbackFactory.filter(F.output_view == OutputView.cwl_skips_all_seasons))
@router.callback_query(CWLCallbackFactory.filter(F.output_view == OutputView.cwl_rating_all_seasons))
@router.callback_query(CWLCallbackFactory.filter(F.output_view == OutputView.cwl_clans_all_seasons))
async def callback_cwl_all_seasons_list(
        callback_query: CallbackQuery, callback_data: CWLCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner and not callback_data.update:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cwl_seasons_list(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.message(Command('cwl_rating'))
async def command_cwl_rating(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await cwl_rating_list(dm, None)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(CWLCallbackFactory.filter(F.output_view == OutputView.cwl_rating_list))
async def callback_cwl_rating_list(
        callback_query: CallbackQuery, callback_data: CWLCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner and not callback_data.update:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cwl_rating_list(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.callback_query(CWLCallbackFactory.filter(F.output_view == OutputView.cwl_rating_choose))
async def callback_cwl_rating_choose(
        callback_query: CallbackQuery, callback_data: CWLCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner and not callback_data.update:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cwl_rating_choose(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.callback_query(CWLCallbackFactory.filter(F.output_view == OutputView.cwl_rating_details))
async def callback_cwl_rating_details(
        callback_query: CallbackQuery, callback_data: CWLCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner and not callback_data.update:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cwl_rating_details(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.callback_query(CWLCallbackFactory.filter(F.output_view == OutputView.cwl_rating_rules))
async def callback_cwl_rating_rules(
        callback_query: CallbackQuery, callback_data: CWLCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner and not callback_data.update:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cwl_rating_rules(dm, callback_data)
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


@router.message(Command('cwl_list'))
async def command_cwl_list(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await cwl_list(dm, callback_data=None)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(CWLCallbackFactory.filter(F.output_view == OutputView.cwl_list))
async def callback_cwl_list(
        callback_query: CallbackQuery, callback_data: CWLCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner and not callback_data.update:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cwl_list(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.message(Command('cwl_clans'))
async def command_cwl_clans(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await cwl_clans(dm, None)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(CWLCallbackFactory.filter(F.output_view == OutputView.cwl_clans))
async def callback_cwl_clans(
        callback_query: CallbackQuery, callback_data: CWLCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner and not callback_data.update:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cwl_clans(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()
