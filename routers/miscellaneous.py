from contextlib import suppress
from enum import auto, IntEnum
from typing import Optional

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import Message, InlineKeyboardMarkup, CallbackQuery, InlineKeyboardButton
from magic_filter import F

from bot.commands import bot_cmd_list, get_shown_bot_commands
from database_manager import DatabaseManager
from entities import ClanMember, BotUser
from output_formatter.output_formatter import Event

router = Router()


class MembersView(IntEnum):
    players = auto()
    users = auto()


class ContributionsView(IntEnum):
    players = auto()
    contribuions = auto()


class OutputView(IntEnum):
    player_info = auto()
    members = auto()
    contributions = auto()
    donations = auto()
    events = auto()
    help = auto()


class MiscellaneousCallbackFactory(CallbackData, prefix='members'):
    output_view: OutputView
    update: bool = False
    user_id: Optional[int] = False
    members_view: Optional[MembersView] = None
    contributions_view: Optional[ContributionsView] = None


async def player_info(dm: DatabaseManager, bot_user: BotUser) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    rows = await dm.acquired_connection.fetch('''
        SELECT
            player_name, player.player_tag, is_player_set_for_clan_wars,
            barbarian_king_level, archer_queen_level, grand_warden_level, royal_champion_level,
            town_hall_level, builder_hall_level, home_village_trophies, builder_base_trophies,
            player_role
        FROM
            player
            JOIN player_bot_user
                ON player.clan_tag = player_bot_user.clan_tag
                AND player.player_tag = player_bot_user.player_tag
                AND player.clan_tag = $1
                AND is_player_in_clan
            JOIN bot_user
                ON player_bot_user.clan_tag = bot_user.clan_tag
                AND player_bot_user.chat_id = bot_user.chat_id
                AND player_bot_user.user_id = bot_user.user_id
                AND bot_user.is_user_in_chat
                AND (bot_user.chat_id, bot_user.user_id) = ($2, $3)
        ORDER BY
            town_hall_level DESC,
            (barbarian_king_level + archer_queen_level + grand_warden_level + royal_champion_level) DESC,
            player_name
    ''', dm.clan_tag, bot_user.chat_id, bot_user.user_id)
    if len(rows) > 1:
        text = (
            f'<b>👤 Аккаунты пользователя {dm.load_full_name(bot_user.chat_id, bot_user.user_id)}</b>\n'
            f'\n'
        )
    else:
        text = (
            f'<b>👤 Аккаунт пользователя {dm.load_full_name(bot_user.chat_id, bot_user.user_id)}</b>\n'
            f'\n'
        )
    for row in rows:
        text += (
            f'<b>{dm.of.to_html(row['player_name'])}</b>, {dm.of.role(row['player_role'])}\n'
            f'Статус участия в КВ: {'✅' if row['is_player_set_for_clan_wars'] else '❌'}\n'
            f'{dm.of.get_player_info_with_custom_emoji(
                row['town_hall_level'],
                row['barbarian_king_level'],
                row['archer_queen_level'],
                row['grand_warden_level'],
                row['royal_champion_level']
            )}\n'
            f'\n'
        )
    if len(rows) == 0:
        text += f'Список пуст\n'
    button_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=MiscellaneousCallbackFactory(
            output_view=OutputView.player_info, update=True, user_id=bot_user.user_id
        ).pack()
    )
    button_row.append(update_button)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[button_row])
    return text, ParseMode.HTML, keyboard


async def members_players(dm: DatabaseManager) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    rows = await dm.acquired_connection.fetch('''
        SELECT
            player_name,
            town_hall_level, barbarian_king_level, archer_queen_level, grand_warden_level, royal_champion_level
        FROM player
        WHERE clan_tag = $1 AND is_player_in_clan
        ORDER BY
            town_hall_level DESC,
            (barbarian_king_level + archer_queen_level + grand_warden_level + royal_champion_level) DESC,
            player_name
    ''', dm.clan_tag)
    text = (
        f'<b>🪖 Участники клана</b>\n'
        f'\n'
        f'Количество участников: {len(rows)} / 50\n'
        f'\n'
    )
    for i, row in enumerate(rows):
        text += (
            f'{i + 1}. {dm.of.to_html(row['player_name'])} {dm.of.get_player_info_with_emoji(
                row['town_hall_level'],
                row['barbarian_king_level'],
                row['archer_queen_level'],
                row['grand_warden_level'],
                row['royal_champion_level']
            )}\n')
    if len(rows) == 0:
        text += f'Список пуст\n'
    button_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=MiscellaneousCallbackFactory(
            output_view=OutputView.members, update=True, members_view=MembersView.players
        ).pack()
    )
    users_view_button = InlineKeyboardButton(
        text='👥 Пользователи',
        callback_data=MiscellaneousCallbackFactory(
            output_view=OutputView.members, members_view=MembersView.users
        ).pack()
    )
    button_row.append(users_view_button)
    button_row.append(update_button)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[button_row])
    return text, ParseMode.HTML, keyboard


async def members_users(dm: DatabaseManager, chat_id: int) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    rows = await dm.acquired_connection.fetch('''
        SELECT
            bot_user.user_id, player.player_tag,
            town_hall_level, barbarian_king_level, archer_queen_level, grand_warden_level, royal_champion_level
        FROM
            player_bot_user
            JOIN player ON
                player_bot_user.clan_tag = player.clan_tag
                AND player_bot_user.player_tag = player.player_tag
                AND is_player_in_clan
            JOIN bot_user ON
                player_bot_user.clan_tag = bot_user.clan_tag
                AND player_bot_user.chat_id = bot_user.chat_id
                AND player_bot_user.user_id = bot_user.user_id
                AND is_user_in_chat
        WHERE player.clan_tag = $1 AND bot_user.chat_id = $2
    ''', dm.clan_tag, chat_id)
    players_by_user = {user_id: [] for user_id in [row['user_id'] for row in rows]}
    for row in rows:
        players_by_user[row['user_id']].append(ClanMember(
            row['player_tag'], row['town_hall_level'],
            row['barbarian_king_level'], row['archer_queen_level'],
            row['grand_warden_level'], row['royal_champion_level']
        ))
    rows = await dm.acquired_connection.fetch('''
        SELECT user_id, first_name, last_name
        FROM bot_user
        WHERE clan_tag = $1 AND chat_id = $2 AND is_user_in_chat AND user_id NOT IN (
            SELECT bot_user.user_id
            FROM
                player_bot_user
                JOIN player ON
                    player_bot_user.clan_tag = player.clan_tag
                    AND player_bot_user.player_tag = player.player_tag
                    AND is_player_in_clan
                JOIN bot_user ON
                    player_bot_user.clan_tag = bot_user.clan_tag
                    AND player_bot_user.chat_id = bot_user.chat_id
                    AND player_bot_user.user_id = bot_user.user_id
                    AND is_user_in_chat
            WHERE player.clan_tag = $1 AND bot_user.chat_id = $2
        )
        ORDER BY first_name, last_name
    ''', dm.clan_tag, chat_id)
    users_without_players = [row['user_id'] for row in rows]
    rows = await dm.acquired_connection.fetch('''
        SELECT
            player_tag,
            town_hall_level, barbarian_king_level, archer_queen_level, grand_warden_level, royal_champion_level
        FROM player
        WHERE clan_tag = $1 AND is_player_in_clan AND player.player_tag NOT IN (
            SELECT player.player_tag
            FROM
                player_bot_user
                JOIN player ON
                    player_bot_user.clan_tag = player.clan_tag
                    AND player_bot_user.player_tag = player.player_tag
                    AND is_player_in_clan
                JOIN bot_user ON
                    player_bot_user.clan_tag = bot_user.clan_tag
                    AND player_bot_user.chat_id = bot_user.chat_id
                    AND player_bot_user.user_id = bot_user.user_id
                    AND is_user_in_chat
            WHERE player.clan_tag = $1 AND bot_user.chat_id = $2
        )
        ORDER BY player_name
    ''', dm.clan_tag, chat_id)
    players_without_users = [
        ClanMember(
            row['player_tag'], row['town_hall_level'],
            row['barbarian_king_level'], row['archer_queen_level'],
            row['grand_warden_level'], row['royal_champion_level']
        )
        for row in rows
    ]
    members_number = await dm.acquired_connection.fetchval('''
        SELECT COUNT(*)
        FROM player
        WHERE clan_tag = $1 AND is_player_in_clan
    ''', dm.clan_tag)
    text = (
        f'<b>👥 Участники клана</b>\n'
        f'\n'
        f'Количество участников: {members_number} / 50\n'
        f'\n'
    )
    if len(players_by_user) > 0:
        text += '<b>Аккаунты пользователей:</b>\n'
    for user_id, players in sorted(
            players_by_user.items(),
            key=lambda item: (
                    sum(clan_member.town_hall_level for clan_member in item[1]),
                    sum(clan_member.hero_levels_sum() for clan_member in item[1]),
                    dm.of.str_sort_key(dm.load_full_name(chat_id, item[0]))
            ),
            reverse=True
    ):
        text += (
            f'👤 {dm.of.to_html(dm.load_full_name(chat_id, user_id))}: '
            f'{', '.join(
                f'{dm.of.to_html(dm.load_name(player.player_tag))} '
                f'{dm.of.get_player_info_with_custom_emoji(player.town_hall_level)}'
                for player in sorted(
                    players,
                    key=lambda _player: (
                        _player.town_hall_level,
                        _player.hero_levels_sum(),
                        dm.of.str_sort_key(dm.load_name(_player.player_tag))
                    ),
                    reverse=True
                )
            )}\n'
        )
    if len(players_by_user) > 0:
        text += '\n'
    if len(players_without_users) > 0:
        text += (
            f'<b>Неизвестные аккаунты:</b>\n'
            f'{'\n'.join(
                f'{dm.of.to_html(dm.load_name(player.player_tag))} '
                f'{dm.of.get_player_info_with_custom_emoji(player.town_hall_level)}'
                for player in sorted(
                    players_without_users,
                    key=lambda _player: (
                        _player.town_hall_level,
                        _player.hero_levels_sum(),
                        dm.of.str_sort_key(dm.load_name(_player.player_tag))
                    ),
                    reverse=True
                )
            )}\n'
            f'\n'
        )
    if len(users_without_players) > 0:
        text += (
            f'<b>Неизвестные пользователи:</b>\n'
            f'{'\n'.join(
                '👤 ' + dm.of.to_html(dm.load_full_name(chat_id, user_id))
                for user_id in sorted(
                    users_without_players,
                    key=lambda user_id: dm.of.str_sort_key(dm.load_full_name(chat_id, user_id)))
            )}\n'
        )
    button_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=MiscellaneousCallbackFactory(
            output_view=OutputView.members, update=True, members_view=MembersView.users
        ).pack()
    )
    players_view_button = InlineKeyboardButton(
        text='🪖 Аккаунты',
        callback_data=MiscellaneousCallbackFactory(
            output_view=OutputView.members, members_view=MembersView.players
        ).pack()
    )
    button_row.append(players_view_button)
    button_row.append(update_button)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[button_row])
    return text, ParseMode.HTML, keyboard


async def contributions(
        dm: DatabaseManager, callback_data: Optional[MiscellaneousCallbackFactory]
) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    if callback_data is not None and callback_data.contributions_view is not None:
        contributions_view = callback_data.contributions_view
    else:
        contributions_view = ContributionsView.players
    if contributions_view == ContributionsView.players:
        text = (
            f'<b>{dm.of.get_capital_gold_emoji()} Вклады в столице (🪖 по игрокам, с начала последних рейдов)</b>\n'
            f'\n'
        )
        raids = await dm.load_raid_weekend()
        if raids is not None:
            rows = await dm.acquired_connection.fetch('''
                SELECT player_tag, SUM(gold_amount) AS sum_gold_amount
                FROM capital_contribution
                WHERE clan_tag = $1 AND contribution_timestamp >= $2
                GROUP BY player_tag
                ORDER BY sum_gold_amount DESC
            ''', dm.clan_tag, dm.of.to_datetime(raids['startTime']))
            if len(rows) > 0:
                for i, row in enumerate(rows):
                    text += (
                        f'{i + 1}. {dm.of.to_html(dm.load_name(row['player_tag']))}: '
                        f'{row['sum_gold_amount']} {dm.of.get_capital_gold_emoji()}\n'
                    )
                val = await dm.acquired_connection.fetchval('''
                    SELECT SUM(gold_amount)
                    FROM capital_contribution
                    WHERE clan_tag = $1 AND contribution_timestamp >= $2
                ''', dm.clan_tag, dm.of.to_datetime(raids['startTime']))
                text += (
                    f'\n'
                    f'Всего вложено с начала последних рейдов: {val} {dm.of.get_capital_gold_emoji()}'
                )
            else:
                text += f'Список пуст\n'
        else:
            text += f'Список пуст\n'
        opposite_view_button = InlineKeyboardButton(
            text='🕒 по времени',
            callback_data=MiscellaneousCallbackFactory(
                output_view=OutputView.contributions, contributions_view=ContributionsView.contribuions
            ).pack()
        )
    else:
        rows = await dm.acquired_connection.fetch('''
            SELECT player_tag, gold_amount, contribution_timestamp
            FROM capital_contribution
            WHERE clan_tag = $1
            ORDER BY contribution_timestamp DESC
            LIMIT 20
        ''', dm.clan_tag)
        text = (
            f'<b>{dm.of.get_capital_gold_emoji()} Вклады в столице (🕒 по времени, 20 последних)</b>\n'
            f'\n'
        )
        for i, row in enumerate(rows):
            text += (
                f'{dm.of.to_html(dm.load_name(row['player_tag']))}: '
                f'{row['gold_amount']} {dm.of.get_capital_gold_emoji()} '
                f'({dm.of.shortest_datetime(row['contribution_timestamp'])})\n'
            )
        if len(rows) == 0:
            text += f'Список пуст\n'
        opposite_view_button = InlineKeyboardButton(
            text='🪖 по игрокам',
            callback_data=MiscellaneousCallbackFactory(
                output_view=OutputView.contributions, contributions_view=ContributionsView.players
            ).pack()
        )
    button_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=MiscellaneousCallbackFactory(
            output_view=OutputView.contributions, update=True, contributions_view=contributions_view
        ).pack()
    )
    button_row.append(opposite_view_button)
    button_row.append(update_button)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[button_row])
    return text, ParseMode.HTML, keyboard


async def donations(dm: DatabaseManager, chat_id: int) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    rows = await dm.acquired_connection.fetch('''
        SELECT player_name, player_role, donations_given
        FROM player
        WHERE clan_tag = $1 AND is_player_in_clan
        ORDER BY donations_given DESC
        LIMIT 20
    ''', dm.clan_tag)
    text = (
        f'<b>🏅 Лучшие жертвователи (20 лучших)</b>\n'
        f'\n'
    )
    for i, row in enumerate(rows):
        text += (
            f'{i + 1}. {dm.of.to_html(row['player_name'])}, {dm.of.role(row['player_role'])}: '
            f'{row['donations_given']}🏅\n'
        )
    consider_donations = await dm.acquired_connection.fetchval('''
        SELECT consider_donations
        FROM clan_chat
        WHERE (clan_tag, chat_id) = ($1, $2)
    ''', dm.clan_tag, chat_id)
    if consider_donations:
        rows = await dm.acquired_connection.fetch('''
            SELECT player_name, donations_given
            FROM player
            WHERE clan_tag = $1 AND is_player_in_clan AND player_role = 'admin' AND player_tag NOT IN (
                SELECT player_tag
                FROM player
                WHERE clan_tag = $1 AND is_player_in_clan AND player_role NOT IN ('coLeader', 'leader')
                ORDER BY donations_given DESC
                LIMIT 10)
            ORDER BY donations_given, player_name
        ''', dm.clan_tag)
        if len(rows) == 1:
            text += (
                f'\n'
                f'<b>⬇️ Будет понижен</b>\n'
                f'{dm.of.to_html(rows[0]['player_name'])}: {rows[0]['donations_given']}🏅\n'
            )
        elif len(rows) > 1:
            text += (
                f'\n'
                f'<b>⬇️ Будут понижены</b>\n'
                f'{', '.join(f'{dm.of.to_html(row['player_name'])}: {row['donations_given']}🏅' for row in rows)}\n'
            )

        rows = await dm.acquired_connection.fetch('''
            SELECT player_name, donations_given
            FROM player
            WHERE clan_tag = $1 AND is_player_in_clan AND player_role = 'member' AND player_tag IN (
                SELECT player_tag
                FROM player
                WHERE clan_tag = $1 AND is_player_in_clan AND player_role NOT IN ('coLeader', 'leader')
                ORDER BY donations_given DESC
                LIMIT 10)
            ORDER BY donations_given DESC, player_name
        ''', dm.clan_tag)
        if len(rows) == 1:
            text += (
                f'\n'
                f'<b>⬆️ Будет повышен</b>\n'
                f'{dm.of.to_html(rows[0]['player_name'])}: {rows[0]['donations_given']}🏅\n'
            )
        elif len(rows) > 1:
            text += (
                f'\n'
                f'<b>⬆️ Будут повышены</b>\n'
                f'{', '.join(f'{dm.of.to_html(row['player_name'])}: {row['donations_given']}🏅' for row in rows)}\n'
            )
    button_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=MiscellaneousCallbackFactory(
            output_view=OutputView.donations, update=True
        ).pack()
    )
    button_row.append(update_button)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[button_row])
    return text, ParseMode.HTML, keyboard


async def events(dm: DatabaseManager) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>📆 События</b>\n'
        f'\n'
    )
    datetimes_and_lines = [(
        dm.of.get_event_datetime(*dm.of.calculate_next_raid_weekend()),
        f'{dm.of.event_datetime(Event.RW, *map(dm.of.from_datetime, dm.of.calculate_next_raid_weekend()), False)}\n'
    ), (
        dm.of.calculate_next_trader_refresh(),
        f'{dm.of.event_datetime(Event.TR, None, None, False, dm.of.calculate_next_trader_refresh())}\n'
    ), (
        dm.of.get_event_datetime(*dm.of.calculate_next_clan_games()),
        f'{dm.of.event_datetime(Event.CG, *map(dm.of.from_datetime, dm.of.calculate_next_clan_games()), False)}\n'
    ), (
        dm.of.get_event_datetime(*dm.of.calculate_next_cwl()),
        f'{dm.of.event_datetime(Event.CWL, *map(dm.of.from_datetime, dm.of.calculate_next_cwl()), False)}\n'
    ), (
        dm.of.calculate_next_season_end(),
        f'{dm.of.event_datetime(Event.SE, None, None, False, dm.of.calculate_next_season_end())}\n'
    ), (
        dm.of.calculate_next_league_reset(),
        f'{dm.of.event_datetime(Event.LR, None, None, False, dm.of.calculate_next_league_reset())}\n'
    )]
    datetimes_and_lines.sort(key=lambda item: item[0])
    text += '\n'.join(line for datetime, line in datetimes_and_lines)
    button_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=MiscellaneousCallbackFactory(output_view=OutputView.events, update=True).pack()
    )
    button_row.append(update_button)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[button_row])
    return text, ParseMode.HTML, keyboard


async def start(dm: DatabaseManager) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    clan_name = await dm.acquired_connection.fetchval('''
        SELECT clan_name
        FROM clan
        WHERE clan_tag = $1
    ''', dm.clan_tag)
    text = dm.of.full_dedent(f'''
        Привет! Этот бот был создан для участников клана <b>{dm.of.to_html(clan_name)}.</b>
        
        Для использования бота необходимо состоять в Telegram-группе клана.
        
        Список доступных команд:
        {'\n'.join(
            f'/{bot_cmd.command} — {bot_cmd.description}'
            for bot_cmd in get_shown_bot_commands(bot_cmd_list, ['group', 'private'], ['ANY'])
        )}
    ''')
    return text, ParseMode.HTML, None


async def help_(dm: DatabaseManager) -> tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    clan_name = await dm.acquired_connection.fetchval('''
        SELECT clan_name
        FROM clan
        WHERE clan_tag = $1
    ''', dm.clan_tag)
    text = dm.of.full_dedent(f'''
        Этот бот был создан для участников клана <b>{dm.of.to_html(clan_name)}.</b>
        
        Для использования бота необходимо состоять в Telegram-группе клана.
        
        Список доступных команд:
        {'\n'.join(
            f'/{bot_cmd.command} — {bot_cmd.description}'
            for bot_cmd in get_shown_bot_commands(bot_cmd_list, ['group', 'private'], ['ANY'])
        )}
    ''')
    button_row = []
    update_button = InlineKeyboardButton(
        text='🔄 Обновить',
        callback_data=MiscellaneousCallbackFactory(output_view=OutputView.help, update=True).pack()
    )
    button_row.append(update_button)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[button_row])
    return text, ParseMode.HTML, keyboard


@router.message(Command('player_info'))
async def command_player_info(message: Message, dm: DatabaseManager) -> None:
    if message.reply_to_message is not None:
        user_id = message.reply_to_message.from_user.id
    else:
        user_id = message.from_user.id
    chat_id = await dm.get_group_chat_id(message)
    text, parse_mode, reply_markup = await player_info(dm, BotUser(chat_id, user_id))
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(MiscellaneousCallbackFactory.filter(F.output_view == OutputView.player_info))
async def callback_player_info(
        callback_query: CallbackQuery, callback_data: MiscellaneousCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        chat_id = await dm.get_group_chat_id(callback_query.message)
        text, parse_mode, reply_markup = await player_info(dm, BotUser(chat_id, callback_data.user_id))
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.message(Command('members'))
async def command_members(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await members_players(dm)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(MiscellaneousCallbackFactory.filter(F.output_view == OutputView.members))
async def callback_members(
        callback_query: CallbackQuery, callback_data: MiscellaneousCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        if callback_data.members_view == MembersView.users:
            chat_id = await dm.get_group_chat_id(callback_query.message)
            text, parse_mode, reply_markup = await members_users(dm, chat_id)
        else:
            text, parse_mode, reply_markup = await members_players(dm)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.message(Command('contributions'))
async def command_contributions(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await contributions(dm, None)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(MiscellaneousCallbackFactory.filter(F.output_view == OutputView.contributions))
async def callback_contributions(
        callback_query: CallbackQuery, callback_data: MiscellaneousCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await contributions(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.message(Command('donations'))
async def command_donations(message: Message, dm: DatabaseManager) -> None:
    chat_id = await dm.get_group_chat_id(message)
    text, parse_mode, reply_markup = await donations(dm, chat_id)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(MiscellaneousCallbackFactory.filter(F.output_view == OutputView.donations))
async def callback_donations(
        callback_query: CallbackQuery, callback_data: MiscellaneousCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        chat_id = await dm.get_group_chat_id(callback_query.message)
        text, parse_mode, reply_markup = await donations(dm, chat_id)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.message(Command('events'))
async def command_events(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await events(dm)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(MiscellaneousCallbackFactory.filter(F.output_view == OutputView.events))
async def callback_events(
        callback_query: CallbackQuery, callback_data: MiscellaneousCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await events(dm)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()


@router.message(Command('help'))
async def command_help(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await help_(dm)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(MiscellaneousCallbackFactory.filter(F.output_view == OutputView.help))
async def callback_help(
        callback_query: CallbackQuery, callback_data: MiscellaneousCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    if not user_is_message_owner:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await help_(dm)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        if callback_data.update:
            await callback_query.answer('Сообщение обновлено')
        else:
            await callback_query.answer()

@router.message(Command('start'))
async def command_start(message: Message, dm: DatabaseManager) -> None:
    text, parse_mode, reply_markup = await start(dm)
    reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
    await dm.dump_message_owner(reply_from_bot, message.from_user)
