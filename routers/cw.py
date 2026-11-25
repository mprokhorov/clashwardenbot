from contextlib import suppress
from datetime import datetime, UTC
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
from entities import WarMember, BotUser

router = Router()

CW_PAGE_SIZE = 10


class CWMapSide(IntEnum):
    clan = auto()
    opponent = auto()


class CWAttacksSide(IntEnum):
    clan = auto()
    opponent = auto()


class CWListOrder(IntEnum):
    by_trophies = auto()
    by_town_hall_and_heroes = auto()


class CWListStatus(IntEnum):
    set_for_clan_wars = auto()
    not_set_for_clan_wars = auto()


class OutputView(IntEnum):
    cw_info = auto()
    cw_map = auto()
    cw_attacks = auto()
    cw_skips = auto()
    cw_status = auto()
    cw_list = auto()
    cw_info_all = auto()
    cw_map_all = auto()
    cw_attacks_all = auto()
    cw_skips_all = auto()


class CWCallbackFactory(CallbackData, prefix='cw'):
    output_view: OutputView
    update: bool = False
    show_opponent_info: Optional[bool] = None
    cw_map_side: Optional[CWMapSide] = None
    cw_attacks_side: Optional[CWAttacksSide] = None
    player_tag: Optional[str] = None
    is_player_set_for_clan_wars: Optional[bool] = None
    cw_list_order: Optional[CWListOrder] = None
    cw_list_status: Optional[CWListStatus] = None
    show_skips: Optional[bool] = None
    cw_time: Optional[int] = None
    page: Optional[int] = None


def cw_ts_to_datetime(cw_time: Optional[int]) -> Optional[datetime]:
    if cw_time is None:
        return None
    return datetime.fromtimestamp(cw_time, UTC).replace(tzinfo=None)


def datetime_to_ts(dt: datetime) -> int:
    return int(dt.replace(tzinfo=UTC).timestamp())


def cw_display_date(
        dm: DatabaseManager, start_time: Optional[str], end_time: Optional[str], prep_dt: datetime
) -> str:
    if start_time and end_time:
        dt = dm.of.get_event_datetime(dm.of.to_datetime(start_time), dm.of.to_datetime(end_time))
    else:
        dt = prep_dt
    return dm.of.short_date(dt)


async def build_cw_nav_row(
        dm: DatabaseManager,
        output_view: OutputView,
        all_output_view: OutputView,
        cw: dict,
        selected_cw_time: Optional[int],
        **cb_kwargs
) -> list[InlineKeyboardButton]:
    prep_dt = dm.of.to_datetime(cw['preparationStartTime'])
    older, newer = await dm.load_adjacent_clan_wars(prep_dt)
    nav_row = []
    if older is not None:
        nav_row.append(InlineKeyboardButton(
            text=f'⬅️ {cw_display_date(dm, older["startTime"], older["endTime"], older["preparation_start_time"])}',
            callback_data=CWCallbackFactory(
                output_view=output_view,
                cw_time=datetime_to_ts(older['preparation_start_time']),
                **cb_kwargs
            ).pack()
        ))
    if newer is not None:
        nav_row.append(InlineKeyboardButton(
            text=f'➡️ {cw_display_date(dm, newer["startTime"], newer["endTime"], newer["preparation_start_time"])}',
            callback_data=CWCallbackFactory(
                output_view=output_view,
                cw_time=datetime_to_ts(newer['preparation_start_time']),
                **cb_kwargs
            ).pack()
        ))
    nav_row.append(InlineKeyboardButton(
        text='🧾 Все КВ',
        callback_data=CWCallbackFactory(
            output_view=all_output_view,
            cw_time=selected_cw_time,
            page=0,
            **cb_kwargs
        ).pack()
    ))
    return nav_row


async def cw_info(
        dm: DatabaseManager, callback_data: Optional[CWCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    if callback_data is not None and callback_data.show_opponent_info is not None:
        show_opponent_info = callback_data.show_opponent_info
    else:
        show_opponent_info = False
    selected_cw_time = callback_data.cw_time if callback_data is not None else None
    text = (
        f'<b>⚔️ Информация о КВ</b>\n'
        f'\n'
    )
    button_row = []
    if show_opponent_info:
        opponent_info_button = InlineKeyboardButton(
            text='🔼 Свернуть',
            callback_data=CWCallbackFactory(
                output_view=OutputView.cw_info, show_opponent_info=False, cw_time=selected_cw_time
            ).pack()
        )
    else:
        opponent_info_button = InlineKeyboardButton(
            text='🔽 Развернуть',
            callback_data=CWCallbackFactory(
                output_view=OutputView.cw_info, show_opponent_info=True, cw_time=selected_cw_time
            ).pack()
        )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWCallbackFactory(
            output_view=OutputView.cw_info, update=True, show_opponent_info=show_opponent_info, cw_time=selected_cw_time
        ).pack()
    )
    cw = await dm.load_clan_war(cw_ts_to_datetime(selected_cw_time))
    if dm.of.state(cw) in ['preparation']:
        war_win_streak = await dm.load_war_win_streak(cw['opponent']['tag'])
        cw_log = await dm.load_clan_war_log(cw['opponent']['tag'])
        text += dm.of.cw_preparation(cw, show_opponent_info, war_win_streak, cw_log)
        button_row.append(opponent_info_button)
        button_row.append(update_button)
    elif dm.of.state(cw) in ['inWar', 'warEnded']:
        war_win_streak = await dm.load_war_win_streak(cw['opponent']['tag'])
        cw_log = await dm.load_clan_war_log(cw['opponent']['tag'])
        text += dm.of.cw_in_war_or_war_ended(cw, show_opponent_info, war_win_streak, cw_log)
        button_row.append(opponent_info_button)
        button_row.append(update_button)
    else:
        text += f'Информация о КВ отсутствует\n'
        button_row.append(update_button)
    button_rows = [button_row]
    if cw is not None:
        button_rows.append(await build_cw_nav_row(
            dm, OutputView.cw_info, OutputView.cw_info_all, cw, selected_cw_time,
            show_opponent_info=show_opponent_info
        ))
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


async def cw_map(
        dm: DatabaseManager, callback_data: Optional[CWCallbackFactory], chat_id: int
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    if callback_data is not None and callback_data.cw_map_side is not None:
        cw_map_side = callback_data.cw_map_side
    else:
        cw_map_side = CWMapSide.opponent
    if callback_data is not None and callback_data.show_skips is not None:
        show_skips = callback_data.show_skips
    else:
        show_skips = False
    selected_cw_time = callback_data.cw_time if callback_data is not None else None
    text = (
        f'<b>🗺️ Карта КВ</b>\n'
        f'\n'
    )
    button_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWCallbackFactory(
            output_view=OutputView.cw_map, update=True, cw_map_side=cw_map_side, show_skips=show_skips,
            cw_time=selected_cw_time
        ).pack()
    )
    clan_side_button = InlineKeyboardButton(
        text='↔️ Карта клана',
        callback_data=CWCallbackFactory(
            output_view=OutputView.cw_map, cw_map_side=CWMapSide.clan, show_skips=show_skips,
            cw_time=selected_cw_time
        ).pack()
    )
    opponent_side_button = InlineKeyboardButton(
        text='↔️ Карта противника',
        callback_data=CWCallbackFactory(
            output_view=OutputView.cw_map, cw_map_side=CWMapSide.opponent, show_skips=show_skips,
            cw_time=selected_cw_time
        ).pack()
    )
    hide_skips_button = InlineKeyboardButton(
        text='🔼 Свернуть',
        callback_data=CWCallbackFactory(
            output_view=OutputView.cw_map, cw_map_side=cw_map_side, show_skips=False,
            cw_time=selected_cw_time
        ).pack()
    )
    show_skips_button = InlineKeyboardButton(
        text='🔽 Развернуть',
        callback_data=CWCallbackFactory(
            output_view=OutputView.cw_map, cw_map_side=cw_map_side, show_skips=True,
            cw_time=selected_cw_time
        ).pack()
    )
    cw = await dm.load_clan_war(cw_ts_to_datetime(selected_cw_time))
    if dm.of.state(cw) in ['preparation']:
        text += (
            f'{dm.of.cw_preparation(cw, False, None, None)}'
            f'\n'
        )
        button_row.append(update_button)
    elif dm.of.state(cw) in ['inWar', 'warEnded']:
        attacks_per_member = cw.get('attacksPerMember', 2)
        clan_map_position_by_player = {member['tag']: member['mapPosition'] for member in cw['clan']['members']}
        opponent_map_position_by_player = {member['tag']: member['mapPosition'] for member in cw['opponent']['members']}
        text += (
            f'{dm.of.cw_in_war_or_war_ended(cw, False, None, None)}'
            f'\n'
        )
        if cw_map_side == CWMapSide.opponent:
            text += 'Карта противника:\n'
            text += dm.of.get_map(
                clan_map_position_by_player, opponent_map_position_by_player, cw['clan'], cw['opponent']
            )
            button_row.append(clan_side_button)
            if show_skips:
                cw_members = []
                for cw_member in cw['clan']['members']:
                    cw_members.append(
                        WarMember(
                            player_tag=cw_member['tag'],
                            attacks_spent=len(cw_member.get('attacks', [])),
                            attacks_limit=attacks_per_member
                        )
                    )
                text += (
                    f'\n'
                    f'\n'
                    f'Не проатаковавшие:'
                    f'\n'
                    f'{await dm.skips(
                        chat_id=chat_id,
                        players=cw_members,
                        ping=False,
                        desired_attacks_spent=attacks_per_member
                    )}'
                )
                button_row.append(hide_skips_button)
            else:
                button_row.append(show_skips_button)
        else:
            text += 'Карта клана:\n'
            text += dm.of.get_map(
                opponent_map_position_by_player, clan_map_position_by_player, cw['opponent'], cw['clan']
            )
            button_row.append(opponent_side_button)

        button_row.append(update_button)
    else:
        text += f'Информация о КВ отсутствует\n'
        button_row.append(update_button)
    button_rows = [button_row]
    if cw is not None:
        button_rows.append(await build_cw_nav_row(
            dm, OutputView.cw_map, OutputView.cw_map_all, cw, selected_cw_time,
            cw_map_side=cw_map_side, show_skips=show_skips
        ))
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


async def cw_attacks(
        dm: DatabaseManager, callback_data: Optional[CWCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    if callback_data is not None and callback_data.cw_attacks_side is not None:
        cw_attacks_side = callback_data.cw_attacks_side
    else:
        cw_attacks_side = CWAttacksSide.clan
    selected_cw_time = callback_data.cw_time if callback_data is not None else None
    text = (
        f'<b>🗡️ Атаки в КВ</b>\n'
        f'\n'
    )
    button_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWCallbackFactory(
            output_view=OutputView.cw_attacks, update=True, cw_attacks_side=cw_attacks_side, cw_time=selected_cw_time
        ).pack()
    )
    opponent_attacks_button = InlineKeyboardButton(
        text='↔️ Атаки противника',
        callback_data=CWCallbackFactory(
            output_view=OutputView.cw_attacks, cw_attacks_side=CWAttacksSide.opponent, cw_time=selected_cw_time
        ).pack()
    )
    clan_attacks_button = InlineKeyboardButton(
        text='↔️ Атаки клана',
        callback_data=CWCallbackFactory(
            output_view=OutputView.cw_attacks, cw_attacks_side=CWAttacksSide.clan, cw_time=selected_cw_time
        ).pack()
    )
    cw = await dm.load_clan_war(cw_ts_to_datetime(selected_cw_time))
    if dm.of.state(cw) in ['preparation']:
        if cw_attacks_side == CWAttacksSide.clan:
            rows = await dm.acquired_connection.fetch('''
                SELECT
                    player_tag, player_name,
                    town_hall_level, barbarian_king_level, archer_queen_level, minion_prince_level, grand_warden_level, royal_champion_level, dragon_duke_level
                FROM player
                WHERE clan_tag = $1
            ''', dm.clan_tag)
            clan_map_position_by_player = {member['tag']: member['mapPosition'] for member in cw['clan']['members']}
            text += (
                f'{dm.of.cw_preparation(cw, False, None, None)}'
                f'\n'
                f'Список участников КВ клана:\n'
                f'{dm.of.war_members(cw['clan']['members'], clan_map_position_by_player, rows)}'
            )
            button_row.append(opponent_attacks_button)
        else:
            rows = await dm.acquired_connection.fetch('''
                SELECT
                    player_tag, player_name,
                    town_hall_level, barbarian_king_level, archer_queen_level, minion_prince_level, grand_warden_level, royal_champion_level, dragon_duke_level
                FROM opponent_player
                WHERE clan_tag = $1
            ''', cw['opponent']['tag'])
            opponent_map_position_by_player = {
                member['tag']: member['mapPosition'] for member in cw['opponent']['members']
            }
            text += (
                f'{dm.of.cw_preparation(cw, False, None, None)}'
                f'\n'
                f'Список участников КВ противника:\n'
                f'{dm.of.war_members(cw['opponent']['members'], opponent_map_position_by_player, rows)}'
            )
            button_row.append(clan_attacks_button)
        button_row.append(update_button)
    elif dm.of.state(cw) in ['inWar', 'warEnded']:
        attacks_per_member = cw.get('attacksPerMember', 2)
        clan_map_position_by_player = {member['tag']: member['mapPosition'] for member in cw['clan']['members']}
        opponent_map_position_by_player = {member['tag']: member['mapPosition'] for member in cw['opponent']['members']}
        text += (
            f'{dm.of.cw_in_war_or_war_ended(cw, False, None, None)}'
            f'\n'
        )
        if cw_attacks_side == CWAttacksSide.clan:
            text += (
                f'Атаки клана:\n'
                f'\n'
                f'{dm.of.get_attacks(
                clan_map_position_by_player, opponent_map_position_by_player, cw['clan'], cw['opponent'], attacks_per_member
                )}'
            )
            button_row.append(opponent_attacks_button)
        else:
            text += (
                f'Атаки противника:\n'
                f'\n'
                f'{dm.of.get_attacks(
                opponent_map_position_by_player, clan_map_position_by_player, cw['opponent'], cw['clan'], attacks_per_member
                )}'
            )
            button_row.append(clan_attacks_button)
        button_row.append(update_button)
    else:
        text += f'Информация о КВ отсутствует\n'
        button_row.append(update_button)
    button_rows = [button_row]
    if cw is not None:
        button_rows.append(await build_cw_nav_row(
            dm, OutputView.cw_attacks, OutputView.cw_attacks_all, cw, selected_cw_time,
            cw_attacks_side=cw_attacks_side
        ))
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


async def cw_skips(
        dm: DatabaseManager, callback_data: Optional[CWCallbackFactory], chat_id: int
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    selected_cw_time = callback_data.cw_time if callback_data is not None else None
    text = (
        f'<b>🕒 Не проатаковавшие в КВ</b>\n'
        f'\n'
    )
    button_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWCallbackFactory(
            output_view=OutputView.cw_skips, update=True, cw_time=selected_cw_time
        ).pack()
    )
    cw = await dm.load_clan_war(cw_ts_to_datetime(selected_cw_time))
    if dm.of.state(cw) in ['preparation']:
        text += dm.of.cw_preparation(cw, False, None, None)
        button_row.append(update_button)
    elif dm.of.state(cw) in ['inWar', 'warEnded']:
        attacks_per_member = cw.get('attacksPerMember', 2)
        cw_members = []
        for cw_member in cw['clan']['members']:
            cw_members.append(
                WarMember(
                    player_tag=cw_member['tag'],
                    attacks_spent=len(cw_member.get('attacks', [])),
                    attacks_limit=attacks_per_member
                )
            )
        text += (
            f'{dm.of.cw_in_war_or_war_ended(cw, False, None, None)}'
            f'\n'
            f'{await dm.skips(
                chat_id=chat_id,
                players=cw_members,
                ping=False,
                desired_attacks_spent=attacks_per_member
            )}'
        )
        button_row.append(update_button)
    else:
        text += 'Информация о КВ отсутствует'
        button_row.append(update_button)
    button_rows = [button_row]
    if cw is not None:
        button_rows.append(await build_cw_nav_row(
            dm, OutputView.cw_skips, OutputView.cw_skips_all, cw, selected_cw_time
        ))
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


async def cw_all_list(
        dm: DatabaseManager, callback_data: CWCallbackFactory
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    view_config = {
        OutputView.cw_info_all: ('⚔️ Информация о КВ', OutputView.cw_info),
        OutputView.cw_map_all: ('🗺️ Карта КВ', OutputView.cw_map),
        OutputView.cw_attacks_all: ('🗡️ Атаки в КВ', OutputView.cw_attacks),
        OutputView.cw_skips_all: ('🕒 Не проатаковавшие в КВ', OutputView.cw_skips)
    }
    title, target_view = view_config[callback_data.output_view]
    page = callback_data.page or 0
    wars, total = await dm.load_clan_wars_page(page, CW_PAGE_SIZE)
    total_pages = max(1, (total + CW_PAGE_SIZE - 1) // CW_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    preserved_kwargs = {
        'show_opponent_info': callback_data.show_opponent_info,
        'cw_map_side': callback_data.cw_map_side,
        'cw_attacks_side': callback_data.cw_attacks_side,
        'show_skips': callback_data.show_skips
    }
    if total == 0:
        text = (
            f'<b>{title}</b>\n'
            f'\n'
            f'Информация о КВ отсутствует\n'
        )
    elif total_pages > 1:
        text = (
            f'<b>{title}</b>\n'
            f'\n'
            f'Выберите КВ (стр. {page + 1} / {total_pages}):\n'
        )
    else:
        text = (
            f'<b>{title}</b>\n'
            f'\n'
            f'Выберите КВ:\n'
        )
    button_rows = []
    for war in wars:
        emoji = dm.of.war_state_emoji(
            war['state'], war['clan_stars'], war['clan_destruction'],
            war['opponent_stars'], war['opponent_destruction']
        )
        date_str = cw_display_date(dm, war['startTime'], war['endTime'], war['preparation_start_time'])
        opponent_name = dm.of.bidi_isolate(war['opponent_name'] or '—')
        if war['state'] in ['inWar', 'warEnded'] and war['clan_stars'] is not None and war['opponent_stars'] is not None:
            score_str = f' ({war["clan_stars"]}–{war["opponent_stars"]} ⭐)'
        else:
            score_str = ''
        button_rows.append([InlineKeyboardButton(
            text=f'{emoji} {date_str} — {opponent_name}{score_str}'.strip(),
            callback_data=CWCallbackFactory(
                output_view=target_view,
                cw_time=datetime_to_ts(war['preparation_start_time']),
                **preserved_kwargs
            ).pack()
        )])
    if total_pages > 1:
        pagination_row = []
        if page > 0:
            pagination_row.append(InlineKeyboardButton(
                text=f'⬅️ Стр. {page}',
                callback_data=CWCallbackFactory(
                    output_view=callback_data.output_view,
                    cw_time=callback_data.cw_time,
                    page=page - 1,
                    **preserved_kwargs
                ).pack()
            ))
        if page < total_pages - 1:
            pagination_row.append(InlineKeyboardButton(
                text=f'➡️ Стр. {page + 2}',
                callback_data=CWCallbackFactory(
                    output_view=callback_data.output_view,
                    cw_time=callback_data.cw_time,
                    page=page + 1,
                    **preserved_kwargs
                ).pack()
            ))
        button_rows.append(pagination_row)
    back_button = InlineKeyboardButton(
        text='⬅️ Назад',
        callback_data=CWCallbackFactory(
            output_view=target_view,
            cw_time=callback_data.cw_time,
            **preserved_kwargs
        ).pack()
    )
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWCallbackFactory(
            output_view=callback_data.output_view,
            update=True,
            cw_time=callback_data.cw_time,
            page=page,
            **preserved_kwargs
        ).pack()
    )
    button_rows.append([back_button, update_button])
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


async def cw_ping(dm: DatabaseManager, chat_id: int) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>🔔 Напоминание об атаках в КВ</b>\n'
        f'\n'
    )
    cw = await dm.load_clan_war()
    if dm.of.state(cw) in ['preparation']:
        text += dm.of.cw_preparation(cw, False, None, None)
    elif dm.of.state(cw) in ['inWar', 'warEnded']:
        attacks_per_member = cw.get('attacksPerMember', 2)
        cw_members = []
        for cw_member in cw['clan']['members']:
            cw_members.append(
                WarMember(
                    player_tag=cw_member['tag'],
                    attacks_spent=len(cw_member.get('attacks', [])),
                    attacks_limit=attacks_per_member
                )
            )
        text += (
            f'{dm.of.cw_in_war_or_war_ended(cw, False, None, None)}'
            f'\n'
            f'{await dm.skips(
                chat_id=chat_id,
                players=cw_members,
                ping=True,
                desired_attacks_spent=attacks_per_member
            )}'
        )
    else:
        text += 'Информация о КВ отсутствует'
    return text, ParseMode.HTML, None


async def cw_status(
        dm: DatabaseManager, callback_data: Optional[CWCallbackFactory], bot_user: BotUser, chat_id: int
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>📝 Изменение статуса участия в КВ</b>\n'
        f'\n'
    )
    button_rows = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWCallbackFactory(output_view=OutputView.cw_status, update=True).pack()
    )
    if callback_data is not None and callback_data.player_tag is not None:
        await dm.acquired_connection.execute('''
            UPDATE player
            SET is_player_set_for_clan_wars = $1
            WHERE clan_tag = $2 and player_tag = $3
        ''', callback_data.is_player_set_for_clan_wars, dm.clan_tag, callback_data.player_tag)
        description = (
            f'Player {dm.load_name_and_tag(callback_data.player_tag)} '
            f'CW status was set to {callback_data.is_player_set_for_clan_wars}'
        )
        await dm.acquired_connection.execute('''
            INSERT INTO action (clan_tag, chat_id, user_id, action_timestamp, description)
            VALUES ($1, $2, $3, NOW() AT TIME ZONE 'UTC', $4)
        ''', dm.clan_tag, bot_user.chat_id, bot_user.user_id, description)
    rows = await dm.acquired_connection.fetch('''
        SELECT
            player_tag, player_name, is_player_set_for_clan_wars,
            town_hall_level, barbarian_king_level, archer_queen_level,
            minion_prince_level, grand_warden_level, royal_champion_level, dragon_duke_level
        FROM
            player
            JOIN player_bot_user USING (clan_tag, player_tag)
            JOIN bot_user USING (clan_tag, chat_id, user_id)
        WHERE clan_tag = $1 AND is_player_in_clan AND chat_id = $2 AND user_id = $3 AND is_user_in_chat
        ORDER BY
            town_hall_level DESC, (barbarian_king_level + archer_queen_level + 
            minion_prince_level + grand_warden_level + royal_champion_level + dragon_duke_level) DESC,
            player_name
    ''', dm.clan_tag, chat_id, bot_user.user_id)
    if len(rows) == 0:
        text += f'В базе данных нет вашего аккаунта'
        button_rows.append([update_button])
    else:
        text += f'Нажмите на аккаунт, статус которого хотите изменить:'
        for row in rows:
            player_button = InlineKeyboardButton(
                text=f'{'✅' if row['is_player_set_for_clan_wars'] else '❌'} '
                     f'{dm.of.to_html(dm.load_name(row['player_tag']))} {dm.of.get_player_info_with_emoji(
                         row['town_hall_level'],
                         row['barbarian_king_level'],
                         row['archer_queen_level'],
                         row['minion_prince_level'],
                         row['grand_warden_level'],
                         row['royal_champion_level'],
                         row['dragon_duke_level'])}',
                callback_data=CWCallbackFactory(
                    output_view=OutputView.cw_status,
                    player_tag=row['player_tag'],
                    is_player_set_for_clan_wars=not row['is_player_set_for_clan_wars']
                ).pack()
            )
            button_rows.append([player_button])
        button_rows.append([update_button])
    keyboard = InlineKeyboardMarkup(inline_keyboard=button_rows)
    return text, ParseMode.HTML, keyboard


async def cw_list(
        dm: DatabaseManager, callback_data: Optional[CWCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    if callback_data is not None and callback_data.cw_list_order is not None:
        cw_list_order = callback_data.cw_list_order
    else:
        cw_list_order = CWListOrder.by_trophies
    if callback_data is not None and callback_data.cw_list_status is not None:
        cw_list_status = callback_data.cw_list_status
    else:
        cw_list_status = CWListStatus.set_for_clan_wars
    button_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=CWCallbackFactory(
            output_view=OutputView.cw_list,
            update=True,
            cw_list_order=cw_list_order,
            cw_list_status=cw_list_status
        ).pack()
    )
    order_by_town_hall_and_heroes_button = InlineKeyboardButton(
        text='⬇️ По ТХ и героям',
        callback_data=CWCallbackFactory(
            output_view=OutputView.cw_list,
            cw_list_order=CWListOrder.by_town_hall_and_heroes,
            cw_list_status=callback_data.cw_list_status if callback_data else None
        ).pack()
    )
    order_by_trophies_button = InlineKeyboardButton(
        text='⬇️ По лиге и трофеям',
        callback_data=CWCallbackFactory(
            output_view=OutputView.cw_list,
            cw_list_order=CWListOrder.by_trophies,
            cw_list_status=callback_data.cw_list_status if callback_data else None
        ).pack()
    )
    not_set_for_clan_wars_button = InlineKeyboardButton(
        text='❌ Не участвующие в КВ',
        callback_data=CWCallbackFactory(
            output_view=OutputView.cw_list,
            cw_list_order=callback_data.cw_list_order if callback_data else None,
            cw_list_status=CWListStatus.not_set_for_clan_wars
        ).pack()
    )
    set_for_clan_wars_button = InlineKeyboardButton(
        text='✅ Участвующие в КВ',
        callback_data=CWCallbackFactory(
            output_view=OutputView.cw_list,
            cw_list_order=callback_data.cw_list_order if callback_data else None,
            cw_list_status=CWListStatus.set_for_clan_wars
        ).pack()
    )
    if cw_list_order == CWListOrder.by_trophies:
        if cw_list_status == CWListStatus.not_set_for_clan_wars:
            rows = await dm.acquired_connection.fetch('''
                SELECT
                    player_name,
                    town_hall_level, barbarian_king_level, archer_queen_level, minion_prince_level, grand_warden_level, royal_champion_level, dragon_duke_level
                FROM player
                WHERE clan_tag = $1 AND player.is_player_in_clan AND NOT is_player_set_for_clan_wars
                ORDER BY player.home_village_league_tier DESC, home_village_trophies DESC
            ''', dm.clan_tag)
            text = (
                f'<b>📋 Список не участвующих в КВ (⬇️ по лиге и трофеям)</b>\n'
                f'\n'
            )
            button_row.append(order_by_town_hall_and_heroes_button)
            button_row.append(set_for_clan_wars_button)
        else:
            rows = await dm.acquired_connection.fetch('''
                SELECT
                    player_name,
                    town_hall_level, barbarian_king_level, archer_queen_level, minion_prince_level, grand_warden_level, royal_champion_level, dragon_duke_level
                FROM player
                WHERE clan_tag = $1 AND player.is_player_in_clan AND is_player_set_for_clan_wars
                ORDER BY player.home_village_league_tier DESC, home_village_trophies DESC
            ''', dm.clan_tag)
            text = (
                f'<b>📋 Список участников КВ (⬇️ по лиге и трофеям)</b>\n'
                f'\n'
            )
            button_row.append(order_by_town_hall_and_heroes_button)
            button_row.append(not_set_for_clan_wars_button)
    else:
        if cw_list_status == CWListStatus.not_set_for_clan_wars:
            rows = await dm.acquired_connection.fetch('''
                SELECT
                    player_name,
                    town_hall_level, barbarian_king_level, archer_queen_level, minion_prince_level, grand_warden_level, royal_champion_level, dragon_duke_level
                FROM player
                WHERE clan_tag = $1 AND player.is_player_in_clan AND NOT is_player_set_for_clan_wars
                ORDER BY
                    town_hall_level DESC,
                    (barbarian_king_level + archer_queen_level + minion_prince_level + grand_warden_level + royal_champion_level + dragon_duke_level) DESC,
                    player_name
            ''', dm.clan_tag)
            text = (
                f'<b>📋 Список не участвующих в КВ (⬇️ по ТХ и героям)</b>\n'
                f'\n'
            )
            button_row.append(order_by_trophies_button)
            button_row.append(set_for_clan_wars_button)
        else:
            rows = await dm.acquired_connection.fetch('''
                SELECT
                    player_name,
                    town_hall_level, barbarian_king_level, archer_queen_level, minion_prince_level, grand_warden_level, royal_champion_level, dragon_duke_level
                FROM player
                WHERE clan_tag = $1 AND player.is_player_in_clan AND is_player_set_for_clan_wars
                ORDER BY
                    town_hall_level DESC,
                    (barbarian_king_level + archer_queen_level + minion_prince_level + grand_warden_level + royal_champion_level + dragon_duke_level) DESC,
                    player_name
            ''', dm.clan_tag)
            text = (
                f'<b>📋 Список участников КВ (⬇️ по ТХ и героям)</b>\n'
                f'\n'
            )
            button_row.append(order_by_trophies_button)
            button_row.append(not_set_for_clan_wars_button)
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
    keyboard = InlineKeyboardMarkup(inline_keyboard=[button_row, [update_button]])
    return text, ParseMode.HTML, keyboard


@router.message(Command('cw_info'))
async def command_cw_info(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await cw_info(dm, None)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(CWCallbackFactory.filter(F.output_view == OutputView.cw_info))
async def callback_cw_info(
        callback_query: CallbackQuery, callback_data: CWCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner and not callback_data.update:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cw_info(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.message(Command('cw_map'))
async def command_cw_map(message: Message, dm: DatabaseManager) -> None:
    chat_id = await dm.get_group_chat_id(message)
    text, parse_mode, reply_markup = await cw_map(dm, None, chat_id)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(CWCallbackFactory.filter(F.output_view == OutputView.cw_map))
async def callback_cw_map(
        callback_query: CallbackQuery, callback_data: CWCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner and not callback_data.update:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        chat_id = await dm.get_group_chat_id(callback_query.message)
        text, parse_mode, reply_markup = await cw_map(dm, callback_data, chat_id)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.message(Command('cw_attacks'))
async def command_cw_attacks(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await cw_attacks(dm, callback_data=None)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(CWCallbackFactory.filter(F.output_view == OutputView.cw_attacks))
async def callback_cw_attacks(
        callback_query: CallbackQuery, callback_data: CWCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner and not callback_data.update:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cw_attacks(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.message(Command('cw_skips'))
async def command_cw_skips(message: Message, dm: DatabaseManager) -> None:
    chat_id = await dm.get_group_chat_id(message)
    text, parse_mode, reply_markup = await cw_skips(dm, None, chat_id)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(CWCallbackFactory.filter(F.output_view == OutputView.cw_skips))
async def callback_cw_skips(
        callback_query: CallbackQuery, callback_data: CWCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner and not callback_data.update:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        chat_id = await dm.get_group_chat_id(callback_query.message)
        text, parse_mode, reply_markup = await cw_skips(dm, callback_data, chat_id)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.callback_query(CWCallbackFactory.filter(F.output_view == OutputView.cw_info_all))
@router.callback_query(CWCallbackFactory.filter(F.output_view == OutputView.cw_map_all))
@router.callback_query(CWCallbackFactory.filter(F.output_view == OutputView.cw_attacks_all))
@router.callback_query(CWCallbackFactory.filter(F.output_view == OutputView.cw_skips_all))
async def callback_cw_all_list(
        callback_query: CallbackQuery, callback_data: CWCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner and not callback_data.update:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cw_all_list(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.message(Command('cw_ping'))
async def command_cw_ping(message: Message, dm: DatabaseManager) -> None:
    user_can_ping_group_members = await dm.can_user_ping_group_members(message.chat.id, message.from_user.id)
    if message.chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        await message.reply(text=f'Эта команда работает только в группах')
    elif not user_can_ping_group_members:
        await message.reply(text=f'У вас нет прав на использование этой команды')
    else:
        chat_id = await dm.get_group_chat_id(message)
        text, parse_mode, reply_markup = await cw_ping(dm, chat_id)
        await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)


@router.message(Command('cw_status'))
async def command_cw_status(message: Message, dm: DatabaseManager) -> None:
    chat_id = await dm.get_group_chat_id(message)
    text, parse_mode, reply_markup = await cw_status(dm, None, BotUser(message.chat.id, message.from_user.id), chat_id)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(CWCallbackFactory.filter(F.output_view == OutputView.cw_status))
async def callback_cw_status(
        callback_query: CallbackQuery, callback_data: CWCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    chat_id = await dm.get_group_chat_id(callback_query.message)
    player_is_linked_to_user = await dm.is_player_linked_to_user(
        callback_data.player_tag, chat_id, callback_query.from_user.id
    )
    if (not user_is_message_owner and not callback_data.update) or (callback_data.player_tag and not player_is_linked_to_user):
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        bot_user = await dm.get_message_owner(callback_query.message)
        text, parse_mode, reply_markup = await cw_status(dm, callback_data, bot_user, chat_id)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.message(Command('cw_list'))
async def command_cw_list(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await cw_list(dm, callback_data=None)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(CWCallbackFactory.filter(F.output_view == OutputView.cw_list))
async def callback_cw_list(
        callback_query: CallbackQuery, callback_data: CWCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner and not callback_data.update:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await cw_list(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()
