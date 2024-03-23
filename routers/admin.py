import enum
from contextlib import suppress
from typing import Optional, Union, Tuple

from aiogram import Router
from aiogram.enums import ParseMode, ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from magic_filter import F

from database_manager import DatabaseManager

router = Router()


class Action(enum.IntEnum):
    menu = 1
    link = 2
    unlink = 3
    edit_cw_list = 4


class Link(enum.IntEnum):
    select_chat = 1
    select_player_from_unknown = 2
    select_player_from_all = 3
    select_user_from_unknown = 4
    select_user_from_all = 5
    finish = 6


class Unlink(enum.IntEnum):
    select_chat = 1
    select_player = 2
    select_user = 3
    finish = 4


class AdminCallbackFactory(CallbackData, prefix='admin'):
    action: Action
    link: Optional[Link] = None
    unlink: Optional[Unlink] = None
    chat_id: Optional[int] = None
    player_tag: Optional[str] = None
    user_id: Optional[int] = None
    is_player_set_for_clan_wars: Optional[bool] = None


def opposite_folding(folding: Union[Link]) -> Union[Link]:
    if folding == Link.select_player_from_all:
        return Link.select_player_from_unknown
    elif folding == Link.select_player_from_unknown:
        return Link.select_player_from_all
    elif folding == Link.select_user_from_unknown:
        return Link.select_user_from_all
    elif folding == Link.select_user_from_all:
        return Link.select_user_from_unknown


def opposite_folding_text(folding: Union[Link]) -> str:
    if folding in (Link.select_player_from_all, Link.select_user_from_all):
        return '🔼 Свернуть'
    elif folding in (Link.select_player_from_unknown, Link.select_user_from_unknown):
        return '🔽 Развернуть'


async def admin() -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = f'<b>⚙️ Панель управления</b>'
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text='✍🏻 Изменить список участников КВ',
                callback_data=AdminCallbackFactory(action=Action.edit_cw_list).pack()
            )],
            [InlineKeyboardButton(
                text='🔗 Привязать аккаунт к пользователю',
                callback_data=AdminCallbackFactory(action=Action.link, link=Link.select_chat).pack()
            )],
            [InlineKeyboardButton(
                text='⛓️ Отвязать аккаунт от пользователя',
                callback_data=AdminCallbackFactory(action=Action.unlink, unlink=Unlink.select_chat).pack()
            )]
        ]
    )
    return text, ParseMode.HTML, keyboard


async def link_select_chat(
        dm: DatabaseManager,
        callback_data: AdminCallbackFactory,
        chat_id: int,
        user_id: int
) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>🔗 Привязка аккаунта к пользователю</b>\n'
        f'\n'
        f'Выберите чат:'
    )
    rows = await dm.load_groups_where_user_can_link_members(chat_id, user_id)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f'{row['title']}',
                callback_data=AdminCallbackFactory(
                    action=Action.link, link=Link.select_player_from_unknown, chat_id=row['chat_id']
                ).pack()
            )] for row in rows
        ] + [[
            InlineKeyboardButton(text='⬅️ Назад', callback_data=AdminCallbackFactory(
                action=Action.menu
            ).pack()),
            InlineKeyboardButton(text='🔄 Обновить', callback_data=AdminCallbackFactory(
                  action=Action.link, link=callback_data.link
            ).pack())
        ]])
    return text, ParseMode.HTML, keyboard


async def link_select_player(
        dm: DatabaseManager,
        callback_data: AdminCallbackFactory
) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>🔗 Привязка аккаунта к пользователю</b>\n'
        f'\n'
        f'Выберите аккаунт:'
    )
    rows = await dm.acquired_connection.fetch('''
        SELECT player_tag, player_name
        FROM player
        WHERE
            clan_tag = $1
            AND is_player_in_clan
            AND ((clan_tag, player_tag) NOT IN (SELECT clan_tag, player_tag FROM player_bot_user WHERE chat_id = $2)
                 OR $3)
        ORDER BY player_name, player_tag
    ''', dm.clan_tag, callback_data.chat_id, callback_data.link == Link.select_player_from_all)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=dm.load_name_and_tag(row['player_tag']), callback_data=AdminCallbackFactory(
                    action=Action.link,
                    link=Link.select_user_from_unknown,
                    chat_id=callback_data.chat_id,
                    player_tag=row['player_tag']
                ).pack())] for row in rows
        ] + [[
            InlineKeyboardButton(
                text='⬅️ Назад', callback_data=AdminCallbackFactory(
                    action=Action.link, link=Link.select_chat
                ).pack()),
            InlineKeyboardButton(
                text='🔄 Обновить', callback_data=AdminCallbackFactory(
                    action=Action.link, link=callback_data.link, chat_id=callback_data.chat_id
                ).pack()),
            InlineKeyboardButton(
                text=opposite_folding_text(callback_data.link), callback_data=AdminCallbackFactory(
                    action=Action.link, link=opposite_folding(callback_data.link), chat_id=callback_data.chat_id
                ).pack()),
        ]])
    return text, ParseMode.HTML, keyboard


async def link_select_user(
        dm: DatabaseManager,
        callback_data: AdminCallbackFactory
) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>🔗 Привязка аккаунта к пользователю</b>\n'
        f'\n'
        f'Выберите пользователя:'
    )
    rows = await dm.acquired_connection.fetch('''
        SELECT user_id, username, first_name, last_name
        FROM bot_user
        WHERE
            (clan_tag, chat_id) = ($1, $2)
            AND is_user_in_chat
            AND ((clan_tag, chat_id, user_id) NOT IN (SELECT clan_tag, chat_id, user_id
                                                      FROM player_bot_user
                                                      WHERE (clan_tag, chat_id) = ($1, $2)) OR $3)
        ORDER BY first_name, last_name, username
    ''', dm.clan_tag, callback_data.chat_id, callback_data.link == Link.select_user_from_all)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=dm.load_full_name_and_username(callback_data.chat_id, row['user_id']),
            callback_data=AdminCallbackFactory(
                action=Action.link,
                link=Link.finish,
                chat_id=callback_data.chat_id,
                player_tag=callback_data.player_tag,
                user_id=row['user_id']
            ).pack())] for row in rows
    ] + [[
        InlineKeyboardButton(
            text='⬅️ Назад',
            callback_data=AdminCallbackFactory(
                action=Action.link,
                link=Link.select_player_from_unknown,
                chat_id=callback_data.chat_id
            ).pack()),
        InlineKeyboardButton(
            text='🔄 Обновить',
            callback_data=AdminCallbackFactory(
                action=Action.link,
                link=callback_data.link,
                chat_id=callback_data.chat_id,
                player_tag=callback_data.player_tag
            ).pack()),
        InlineKeyboardButton(
            text=opposite_folding_text(callback_data.link),
            callback_data=AdminCallbackFactory(
                action=Action.link,
                link=opposite_folding(callback_data.link),
                chat_id=callback_data.chat_id,
                player_tag=callback_data.player_tag
            ).pack()),
    ]])
    return text, ParseMode.HTML, keyboard


async def link_finish(
        dm: DatabaseManager,
        callback_data: AdminCallbackFactory,
        callback_query: CallbackQuery
) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    rows = await dm.acquired_connection.fetch('''
        SELECT clan_tag, player_tag, chat_id, user_id
        FROM player_bot_user
        WHERE (clan_tag, player_tag, chat_id, user_id) = ($1, $2, $3, $4)
    ''', dm.clan_tag, callback_data.player_tag, callback_data.chat_id, callback_data.user_id)
    if len(rows) == 0:
        await dm.acquired_connection.execute('''
            INSERT INTO player_bot_user (clan_tag, player_tag, chat_id, user_id)
            VALUES ($1, $2, $3, $4)
        ''', dm.clan_tag, callback_data.player_tag, callback_data.chat_id, callback_data.user_id)
        text = (
            f'<b>🔗 Привязка аккаунта к пользователю</b>\n'
            f'\n'
            f'Аккаунт {dm.of.to_html(dm.load_name_and_tag(callback_data.player_tag))} '
            f'привязан к пользователю '
            f'{dm.of.to_html(dm.load_full_name_and_username(callback_data.chat_id, callback_data.user_id))}\n'
        )
        description = (
            f'Player {dm.load_name_and_tag(callback_data.player_tag)} was linked to user '
            f'{dm.load_full_name_and_username(callback_data.chat_id, callback_data.user_id)}'
        )
    else:
        text = (
            f'<b>🔗 Привязка аккаунта к пользователю</b>\n'
            f'\n'
            f'Аккаунт {dm.of.to_html(dm.load_name_and_tag(callback_data.player_tag))} '
            f'уже был привязан к пользователю '
            f'{dm.of.to_html(dm.load_full_name_and_username(callback_data.chat_id, callback_data.user_id))}\n'
        )
        description = (
            f'Player {dm.load_name_and_tag(callback_data.player_tag)} was already linked '
            f'to user {dm.load_full_name_and_username(callback_data.chat_id, callback_data.user_id)}'
        )

    await dm.acquired_connection.execute('''
        INSERT INTO action (clan_tag, chat_id, user_id, action_timestamp, description)
        VALUES ($1, $2, $3, NOW() AT TIME ZONE 'UTC', $4)
    ''', dm.clan_tag, callback_query.message.chat.id, callback_query.from_user.id, description)

    return text, ParseMode.HTML, None


async def unlink_select_chat(
        dm: DatabaseManager,
        callback_data: AdminCallbackFactory,
        chat_id: int,
        user_id: int
) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>⛓️ Отвязка аккаунта от пользователя</b>\n'
        f'\n'
        f'Выберите чат:'
    )
    rows = await dm.load_groups_where_user_can_link_members(chat_id, user_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f'{row['title']}',
            callback_data=AdminCallbackFactory(
                action=Action.unlink, unlink=Unlink.select_player, chat_id=row['chat_id']
            ).pack())] for row in rows
    ] + [[
        InlineKeyboardButton(
            text='⬅️ Назад', callback_data=AdminCallbackFactory(
                action=Action.menu
            ).pack()),
        InlineKeyboardButton(
            text='🔄 Обновить', callback_data=AdminCallbackFactory(
                action=Action.unlink, unlink=callback_data.unlink
            ).pack())
    ]])
    return text, ParseMode.HTML, keyboard


async def unlink_select_player(
        dm: DatabaseManager,
        callback_data: AdminCallbackFactory,
) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>⛓️ Отвязка аккаунта от пользователя</b>\n'
        f'\n'
        f'Выберите аккаунт:'
    )
    rows = await dm.acquired_connection.fetch('''
        SELECT player_tag, player_name
        FROM player
        WHERE
            (clan_tag, player_tag) IN (
                SELECT clan_tag, player_tag
                FROM
                    player
                    JOIN player_bot_user USING (clan_tag, player_tag)
                    JOIN bot_user USING (clan_tag, chat_id, user_id)
                WHERE clan_tag = $1 AND is_player_in_clan AND chat_id = $2 AND is_user_in_chat)
        ORDER BY player_name, player_tag
    ''', dm.clan_tag, callback_data.chat_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=dm.load_name_and_tag(row['player_tag']),
            callback_data=AdminCallbackFactory(
                action=Action.unlink,
                unlink=Unlink.select_user,
                chat_id=callback_data.chat_id,
                player_tag=row['player_tag']
            ).pack())]
        for row in rows
    ] + [[
        InlineKeyboardButton(
            text='⬅️ Назад',
            callback_data=AdminCallbackFactory(
                action=Action.unlink,
                unlink=Unlink.select_chat
            ).pack()),
        InlineKeyboardButton(
            text='🔄 Обновить',
            callback_data=AdminCallbackFactory(
                action=Action.unlink,
                unlink=callback_data.unlink,
                chat_id=callback_data.chat_id
            ).pack())
    ]])
    return text, ParseMode.HTML, keyboard


async def unlink_select_user(
        dm: DatabaseManager,
        callback_data: AdminCallbackFactory
) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>⛓️ Отвязка аккаунта от пользователя</b>\n'
        f'\n'
        f'Выберите пользователя:'
    )
    rows = await dm.acquired_connection.fetch('''
        SELECT user_id, username, first_name, last_name
        FROM bot_user
        WHERE
            (clan_tag, chat_id, user_id) IN (
                SELECT clan_tag, chat_id, user_id
                FROM player_bot_user
                WHERE (clan_tag, player_tag) = ($1, $2)
            )
    ''', dm.clan_tag, callback_data.player_tag)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=dm.load_full_name_and_username(callback_data.chat_id, row['user_id']),
            callback_data=AdminCallbackFactory(
                action=Action.unlink,
                unlink=Unlink.finish,
                chat_id=callback_data.chat_id,
                player_tag=callback_data.player_tag,
                user_id=row['user_id']
            ).pack())] for row in rows
    ] + [[
        InlineKeyboardButton(
            text='⬅️ Назад',
            callback_data=AdminCallbackFactory(
                action=Action.unlink,
                unlink=Unlink.select_player,
                chat_id=callback_data.chat_id
            ).pack()),
        InlineKeyboardButton(
            text='🔄 Обновить',
            callback_data=AdminCallbackFactory(
                action=Action.unlink,
                unlink=callback_data.unlink,
                chat_id=callback_data.chat_id,
                player_tag=callback_data.player_tag
            ).pack())
    ]])
    return text, ParseMode.HTML, keyboard


async def unlink_finish(
    dm: DatabaseManager,
    callback_data: AdminCallbackFactory,
    callback_query: CallbackQuery
) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    rows = await dm.acquired_connection.fetch('''
        SELECT clan_tag, player_tag, chat_id, user_id
        FROM player_bot_user
        WHERE (clan_tag, player_tag, chat_id, user_id) = ($1, $2, $3, $4)
    ''', dm.clan_tag, callback_data.player_tag, callback_data.chat_id, callback_data.user_id)
    if len(rows) == 0:
        text = (
            f'<b>⛓️ Отвязка аккаунта от пользователя</b>\n'
            f'\n'
            f'Аккаунт {dm.of.to_html(dm.load_name_and_tag(callback_data.player_tag))} '
            f'не был привязан к пользователю '
            f'{dm.of.to_html(dm.load_full_name_and_username(callback_data.chat_id, callback_data.user_id))}\n'
        )
        description = (
            f'Player {dm.load_name_and_tag(callback_data.player_tag)} '
            f'wasn\'t linked to user '
            f'{dm.load_full_name_and_username(callback_data.chat_id, callback_data.user_id)}'
        )
    else:
        await dm.acquired_connection.execute('''
            DELETE FROM player_bot_user
            WHERE (clan_tag, player_tag, chat_id, user_id) = ($1, $2, $3, $4)
        ''', dm.clan_tag, callback_data.player_tag, callback_data.chat_id, callback_data.user_id)
        text = (
            f'<b>⛓️ Отвязка аккаунта от пользователя</b>\n'
            f'\n'
            f'Аккаунт {dm.of.to_html(dm.load_name_and_tag(callback_data.player_tag))} '
            f'был отвязан от пользователя '
            f'{dm.of.to_html(dm.load_full_name_and_username(callback_data.chat_id, callback_data.user_id))}\n'
        )
        description = (
            f'Player {dm.load_name_and_tag(callback_data.player_tag)} '
            f'was unlinked '
            f'from user {dm.load_full_name_and_username(callback_data.chat_id, callback_data.user_id)}'
        )

    await dm.acquired_connection.execute('''
        INSERT INTO action (clan_tag, chat_id, user_id, action_timestamp, description)
        VALUES ($1, $2, $3, NOW() AT TIME ZONE 'UTC', $4)
    ''', dm.clan_tag, callback_query.message.chat.id, callback_query.from_user.id, description)

    return text, ParseMode.HTML, None


async def edit_cw_list(
        dm: DatabaseManager,
        callback_query: Optional[CallbackQuery],
        callback_data: Optional[AdminCallbackFactory]
) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    text = (
        f'<b>✍🏻 Изменение списка участников КВ</b>\n'
        f'\n'
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
        ''', dm.clan_tag, callback_query.message.chat.id, callback_query.from_user.id, description)
    rows = await dm.acquired_connection.fetch('''
        SELECT
            player_tag, is_player_set_for_clan_wars,
            town_hall_level, barbarian_king_level, archer_queen_level, grand_warden_level, royal_champion_level
        FROM player
        WHERE clan_tag = $1 AND is_player_in_clan
        ORDER BY
            town_hall_level DESC,
            (barbarian_king_level + archer_queen_level + grand_warden_level + royal_champion_level) DESC,
            player_name
    ''', dm.clan_tag)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f'{'✅' if row['is_player_set_for_clan_wars'] else '❌'} '
                 f'{dm.load_name(row['player_tag'])} {dm.of.get_player_info_for_callback_text(
                     row['town_hall_level'],
                     row['barbarian_king_level'],
                     row['archer_queen_level'],
                     row['grand_warden_level'],
                     row['royal_champion_level']
                 )}',
            callback_data=AdminCallbackFactory(
                action=Action.edit_cw_list,
                player_tag=row['player_tag'],
                is_player_set_for_clan_wars=not row['is_player_set_for_clan_wars']
            ).pack())] for row in rows
    ] + [[
        InlineKeyboardButton(
            text='⬅️ Назад',
            callback_data=AdminCallbackFactory(action=Action.menu).pack()),
        InlineKeyboardButton(
            text='🔄 Обновить',
            callback_data=AdminCallbackFactory(action=Action.edit_cw_list).pack())
    ]])
    return text, ParseMode.HTML, keyboard


async def alert(
        dm: DatabaseManager,
        chat_id: int,
        message: Message,
        ping: bool
) -> Tuple[str, ParseMode, Optional[InlineKeyboardMarkup]]:
    row = await dm.acquired_connection.fetchrow('''
        SELECT title
        FROM chat
        WHERE (clan_tag, chat_id) = ($1, $2)
    ''', dm.clan_tag, chat_id)
    chat_title = row['title']
    if ping:
        text = (
            f'<b>✍🏻 Отправка сообщения всем пользователям в группах</b>\n'
            f'\n'
        )
        if message.html_text.removeprefix('/alert').removeprefix('/ping').lstrip(' '):
            message_text = (
                f'<b>📣 Оповещение</b>\n'
                f'\n'
                f'{message.html_text.removeprefix('/alert').removeprefix('/ping').lstrip(' ')}\n'
            )
        else:
            message_text = f'<b>📣 Оповещение</b>'
        await dm.send_message_to_chat(
            user_id=message.from_user.id,
            chat_id=chat_id,
            message_text=message_text,
            user_ids_to_ping=await dm.get_clan_member_user_ids(chat_id)
        )
        text += f'Сообщение отправлено всем пользователям в группе {chat_title}\n'
    else:
        text = (
            f'<b>✍🏻 Отправка сообщения в группы</b>\n'
            f'\n'
        )
        if message.html_text.removeprefix('/alert').removeprefix('/ping').lstrip(' '):
            message_text = (
                f'<b>💬 Сообщение</b>\n'
                f'\n'
                f'{message.html_text.removeprefix('/alert').removeprefix('/ping').lstrip(' ')}\n'
            )
        else:
            message_text = f'<b>💬 Сообщение</b>'
        await dm.send_message_to_chat(
            user_id=message.from_user.id,
            chat_id=chat_id,
            message_text=message_text,
            user_ids_to_ping=None
        )
        text += f'Сообщение отправлено в группу {chat_title}\n'
    return text, ParseMode.HTML, None


@router.message(Command('admin'))
async def command_admin(message: Message, dm: DatabaseManager) -> None:
    can_user_link_members = await dm.can_user_link_group_members(message.chat.id, message.from_user.id)
    can_user_edit_cw_list = await dm.can_user_edit_cw_list(message.chat.id, message.from_user.id)
    if message.chat.type != ChatType.PRIVATE:
        await message.reply(text=f'Эта команда работает только в диалоге с ботом')
    elif not can_user_link_members and not can_user_edit_cw_list:
        await message.reply(text=f'Эта команда не работает для вас')
    else:
        text, parse_mode, reply_markup = await admin()
        reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.callback_query(AdminCallbackFactory.filter(F.action == Action.menu))
async def callback_admin(
        callback_query: CallbackQuery, callback_data: AdminCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    can_user_link_members = await dm.can_user_link_group_members(
        callback_query.message.chat.id, callback_query.from_user.id
    )
    can_user_edit_cw_list = await dm.can_user_edit_cw_list(callback_query.message.chat.id, callback_query.from_user.id)
    if not user_is_message_owner or (not can_user_link_members and not can_user_edit_cw_list):
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await admin()
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback_query.answer()


@router.callback_query(AdminCallbackFactory.filter((F.action == Action.link) & (F.link == Link.select_chat)))
async def callback_link_select_chat(
        callback_query: CallbackQuery, callback_data: AdminCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    can_user_link_members = await dm.can_user_link_group_members(
        callback_query.message.chat.id, callback_query.from_user.id
    )
    if not user_is_message_owner or not can_user_link_members:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await link_select_chat(
            dm, callback_data, callback_query.message.chat.id, callback_query.from_user.id
        )
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback_query.answer()


@router.callback_query(
    AdminCallbackFactory.filter((F.action == Action.link) & (F.link == Link.select_player_from_unknown))
)
@router.callback_query(
    AdminCallbackFactory.filter((F.action == Action.link) & (F.link == Link.select_player_from_all))
)
async def callback_link_select_player(
        callback_query: CallbackQuery, callback_data: AdminCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    can_user_link_members = await dm.can_user_link_group_members(
        callback_query.message.chat.id, callback_query.from_user.id
    )
    if not user_is_message_owner or not can_user_link_members:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await link_select_player(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback_query.answer()


@router.callback_query(
    AdminCallbackFactory.filter((F.action == Action.link) & (F.link == Link.select_user_from_unknown))
)
@router.callback_query(
    AdminCallbackFactory.filter((F.action == Action.link) & (F.link == Link.select_user_from_all))
)
async def callback_link_select_user(
        callback_query: CallbackQuery, callback_data: AdminCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    can_user_link_members = await dm.can_user_link_group_members(
        callback_query.message.chat.id, callback_query.from_user.id
    )
    if not user_is_message_owner or not can_user_link_members:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await link_select_user(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback_query.answer()


@router.callback_query(AdminCallbackFactory.filter((F.action == Action.link) & (F.link == Link.finish)))
async def callback_link_finish(
        callback_query: CallbackQuery, callback_data: AdminCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    can_user_link_members = await dm.can_user_link_group_members(
        callback_query.message.chat.id, callback_query.from_user.id
    )
    if not user_is_message_owner or not can_user_link_members:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await link_finish(dm, callback_data, callback_query)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback_query.answer()


@router.callback_query(AdminCallbackFactory.filter((F.action == Action.unlink) & (F.unlink == Unlink.select_chat)))
async def callback_unlink_select_chat(
        callback_query: CallbackQuery, callback_data: AdminCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    can_user_unlink_members = await dm.can_user_link_group_members(
        callback_query.message.chat.id, callback_query.from_user.id
    )
    if not user_is_message_owner or not can_user_unlink_members:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await unlink_select_chat(
            dm, callback_data, callback_query.message.chat.id, callback_query.from_user.id
        )
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback_query.answer()


@router.callback_query(
    AdminCallbackFactory.filter((F.action == Action.unlink) & (F.unlink == Unlink.select_player))
)
async def callback_unlink_select_player(
        callback_query: CallbackQuery, callback_data: AdminCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    can_user_unlink_members = await dm.can_user_link_group_members(
        callback_query.message.chat.id, callback_query.from_user.id
    )
    if not user_is_message_owner or not can_user_unlink_members:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await unlink_select_player(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback_query.answer()


@router.callback_query(
    AdminCallbackFactory.filter((F.action == Action.unlink) & (F.unlink == Unlink.select_user))
)
async def callback_unlink_select_user(
        callback_query: CallbackQuery, callback_data: AdminCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    can_user_unlink_members = await dm.can_user_link_group_members(
        callback_query.message.chat.id, callback_query.from_user.id
    )
    if not user_is_message_owner or not can_user_unlink_members:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await unlink_select_user(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback_query.answer()


@router.callback_query(AdminCallbackFactory.filter((F.action == Action.unlink) & (F.unlink == Unlink.finish)))
async def callback_unlink_finish(
        callback_query: CallbackQuery, callback_data: AdminCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    can_user_unlink_members = await dm.can_user_link_group_members(
        callback_query.message.chat.id, callback_query.from_user.id
    )
    if not user_is_message_owner or not can_user_unlink_members:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await unlink_finish(dm, callback_data, callback_query)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback_query.answer()


@router.callback_query(AdminCallbackFactory.filter(F.action == Action.edit_cw_list))
async def callback_edit_cw_list(
        callback_query: CallbackQuery, callback_data: AdminCallbackFactory, dm: DatabaseManager
) -> None:
    user_is_message_owner = await dm.is_user_message_owner(callback_query.message, callback_query.from_user)
    can_user_edit_cw_list = await dm.can_user_edit_cw_list(callback_query.message.chat.id, callback_query.from_user.id)
    if not user_is_message_owner or not can_user_edit_cw_list:
        await callback_query.answer('Эта кнопка не работает для вас')
    else:
        text, parse_mode, reply_markup = await edit_cw_list(dm, callback_query, callback_data)
        with suppress(TelegramBadRequest):
            await callback_query.message.edit_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback_query.answer()


@router.message(Command('alert'))
async def command_alert(message: Message, dm: DatabaseManager) -> None:
    user_can_send_messages_from_bot = await dm.can_user_send_messages_from_bot(message.chat.id, message.from_user.id)
    if message.chat.type != ChatType.PRIVATE:
        await message.reply(text=f'Эта команда работает только в диалоге с ботом')
    elif not user_can_send_messages_from_bot:
        await message.reply(text=f'Эта команда не работает для вас')
    else:
        text, parse_mode, reply_markup = await alert(dm, await dm.get_main_chat_id(), message, ping=False)
        reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await dm.dump_message_owner(reply_from_bot, message.from_user)


@router.message(Command('ping'))
async def command_ping(message: Message, dm: DatabaseManager) -> None:
    user_can_send_messages_from_bot = await dm.can_user_send_messages_from_bot(message.chat.id, message.from_user.id)
    if message.chat.type != ChatType.PRIVATE:
        await message.reply(text=f'Эта команда работает только в диалоге с ботом')
    elif not user_can_send_messages_from_bot:
        await message.reply(text=f'Эта команда не работает для вас')
    else:
        text, parse_mode, reply_markup = await alert(dm, await dm.get_main_chat_id(), message, ping=True)
        reply_from_bot = await message.reply(text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        await dm.dump_message_owner(reply_from_bot, message.from_user)
