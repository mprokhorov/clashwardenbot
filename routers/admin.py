import logging
from contextlib import suppress
from typing import Optional

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from magic_filter import F

from database_manager import DatabaseManager

router = Router()


class AdminCallbackFactory(CallbackData, prefix='admin'):
    state: str
    id: Optional[int] = None
    tag: Optional[str] = None
    participates: Optional[bool] = None


async def admin():
    answer = f'<b>⚙️ Панель управления</b>'
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='Привязать аккаунт к пользователю',
                              callback_data=AdminCallbackFactory(state='link_id_collapsed').pack())],
        [InlineKeyboardButton(text='Отвязать аккаунт от пользователя',
                              callback_data=AdminCallbackFactory(state='unlink_id').pack())],
        [InlineKeyboardButton(text='Редактировать статусы участия в КВ',
                              callback_data=AdminCallbackFactory(state='edit_statuses').pack())]
    ])
    return answer, ParseMode.HTML, keyboard


@router.message(Command('admin'))
async def cmd_admin(message: Message, dm: DatabaseManager):
    user_is_admin = await dm.is_admin(message.from_user.id)
    if not user_is_admin:
        await message.reply(text=f'Эту команду могут использовать только соруководители и глава')
    elif message.from_user.id != message.chat.id:
        await message.reply(text=f'Эту команду можно использовать только в личных чатах')
    else:
        answer, parse_mode, reply_markup = await admin()
        reply_from_bot = await message.reply(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)
        await dm.register_message(reply_from_bot.chat.id, reply_from_bot.message_id, message.from_user.id)


@router.callback_query(AdminCallbackFactory.filter(F.state.in_({'admin'})))
async def callback_admin(callback: CallbackQuery, callback_data: AdminCallbackFactory,
                         dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.check_message(callback.message.chat.id,
                                                   callback.message.message_id,
                                                   callback.from_user.id)
    if not user_is_message_owner:
        await callback.answer('Эта кнопка не для вас!')
    else:
        answer, parse_mode, reply_markup = await admin()
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback.answer()


async def admin_link_id_collapsed(dm: DatabaseManager):
    answer = f'<b>⚙️ Привязка аккаунта к пользователю\n\nВыберите пользователя:</b>'
    query = await dm.req_connection.fetch('''
        SELECT id, username, first_name, last_name
        FROM public.telegram_user
        WHERE id NOT IN (SELECT id FROM public.tg_user_coc_account)
        ORDER BY first_name, last_name
    ''')
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=dm.get_full_name_and_username(record['id']),
                                    callback_data=AdminCallbackFactory(
                                        state='link_id_tag_collapsed',
                                        id=record['id']
                                    ).pack())]
        for record in query
    ] + [[
        InlineKeyboardButton(text='⬅️ Назад',
                             callback_data=AdminCallbackFactory(
                                 state='admin'
                             ).pack()),
        InlineKeyboardButton(text='🔽 Развернуть',
                             callback_data=AdminCallbackFactory(
                                 state='link_id_expanded'
                             ).pack()),
        InlineKeyboardButton(text='🔄 Обновить',
                             callback_data=AdminCallbackFactory(
                                 state='link_id_collapsed'
                             ).pack())
    ]])
    return answer, ParseMode.HTML, keyboard


async def admin_link_id_expanded(dm: DatabaseManager):
    answer = f'<b>⚙️ Привязка аккаунта к пользователю\n\nВыберите пользователя:</b>'
    query = await dm.req_connection.fetch('''
        SELECT id, username, first_name, last_name
        FROM public.telegram_user
        ORDER BY first_name, last_name
    ''')
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=dm.get_full_name_and_username(record['id']),
                              callback_data=AdminCallbackFactory(
                                  state='link_id_tag_collapsed',
                                  id=record['id']
                              ).pack())]
        for record in query
    ] + [[
        InlineKeyboardButton(text='⬅️ Назад',
                             callback_data=AdminCallbackFactory(
                                 state='admin'
                             ).pack()),
        InlineKeyboardButton(text='🔄 Обновить',
                             callback_data=AdminCallbackFactory(
                                 state='link_id_expanded'
                             ).pack()),
        InlineKeyboardButton(text='🔼 Свернуть',
                             callback_data=AdminCallbackFactory(
                                 state='link_id_collapsed'
                             ).pack())
    ]])
    return answer, ParseMode.HTML, keyboard


@router.callback_query(AdminCallbackFactory.filter(F.state.in_({'link_id_collapsed', 'link_id_expanded'})))
async def callback_link_id(callback: CallbackQuery, callback_data: AdminCallbackFactory,
                           dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.check_message(callback.message.chat.id,
                                                   callback.message.message_id,
                                                   callback.from_user.id)
    if not user_is_message_owner:
        await callback.answer('Эта кнопка не для вас!')
    else:
        if callback_data.state == 'link_id_collapsed':
            answer, parse_mode, reply_markup = await admin_link_id_collapsed(dm)
        else:
            answer, parse_mode, reply_markup = await admin_link_id_expanded(dm)
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback.answer()


async def admin_link_tag_collapsed(dm: DatabaseManager, callback_data: AdminCallbackFactory):
    answer = (f'<b>⚙️ Привязка аккаунта к пользователю\n\nВыберите аккаунт, который будет привязан к пользователю '
              f'{dm.get_full_name_and_username(callback_data.id)}:</b>')
    query = await dm.req_connection.fetch('''
        SELECT tag, name
        FROM public.clash_of_clans_account
        WHERE tag NOT IN (SELECT tag FROM public.tg_user_coc_account)
        ORDER BY name
    ''')
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=dm.get_name_and_tag(record['tag']),
                              callback_data=AdminCallbackFactory(
                                  state='link_finish',
                                  id=callback_data.id,
                                  tag=record['tag']
                              ).pack())]
        for record in query
    ] + [[
        InlineKeyboardButton(text='⬅️ Назад',
                             callback_data=AdminCallbackFactory(
                                 state='link_id_collapsed'
                             ).pack()),
        InlineKeyboardButton(text='🔄 Обновить',
                             callback_data=AdminCallbackFactory(
                                 state='link_id_tag_collapsed',
                                 id=callback_data.id
                             ).pack()),
        InlineKeyboardButton(text='🔽 Развернуть',
                             callback_data=AdminCallbackFactory(
                                 state='link_id_tag_expanded',
                                 id=callback_data.id
                             ).pack()),
    ]])
    return answer, ParseMode.HTML, keyboard


async def admin_link_tag_expanded(dm: DatabaseManager, callback_data: AdminCallbackFactory):
    answer = (f'<b>⚙️ Привязка аккаунта к пользователю\n\nВыберите аккаунт, который будет привязан к пользователю '
              f'{dm.get_full_name_and_username(callback_data.id)}:</b>')
    query = await dm.req_connection.fetch('''
        SELECT tag, name
        FROM public.clash_of_clans_account
        ORDER BY name
    ''')
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=dm.get_name_and_tag(record['tag']),
                                    callback_data=AdminCallbackFactory(
                                        state='link_finish',
                                        id=callback_data.id,
                                        tag=record['tag']
                                    ).pack())]
        for record in query
    ] + [[
        InlineKeyboardButton(text='⬅️ Назад',
                             callback_data=AdminCallbackFactory(
                                 state='link_id_collapsed'
                             ).pack()),
        InlineKeyboardButton(text='🔄 Обновить',
                             callback_data=AdminCallbackFactory(
                                 state='link_id_tag_expanded',
                                 id=callback_data.id
                             ).pack()),
        InlineKeyboardButton(text='🔼 Свернуть',
                             callback_data=AdminCallbackFactory(
                                 state='link_id_tag_collapsed',
                                 id=callback_data.id
                             ).pack())
    ]])
    return answer, ParseMode.HTML, keyboard


@router.callback_query(AdminCallbackFactory.filter(F.state.in_({'link_id_tag_collapsed', 'link_id_tag_expanded'})))
async def callback_link_id_tag(callback: CallbackQuery, callback_data: AdminCallbackFactory,
                               dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.check_message(callback.message.chat.id,
                                                   callback.message.message_id,
                                                   callback.from_user.id)
    if not user_is_message_owner:
        await callback.answer('Эта кнопка не для вас!')
    else:
        if callback_data.state == 'link_id_tag_collapsed':
            answer, parse_mode, reply_markup = await admin_link_tag_collapsed(dm, callback_data)
        else:
            answer, parse_mode, reply_markup = await admin_link_tag_expanded(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback.answer()


async def admin_link_finish(dm: DatabaseManager, callback_data, callback: CallbackQuery):
    query = await dm.req_connection.fetch('''
        SELECT *
        FROM public.tg_user_coc_account
        WHERE id = $1 AND tag = $2
    ''', callback_data.id, callback_data.tag)
    if len(query) == 0:
        await dm.req_connection.execute('''
            INSERT INTO public.tg_user_coc_account
            VALUES ($1, $2)
        ''', callback_data.id, callback_data.tag)
        answer = (f'⚙️ Привязка аккаунта к пользователю\n\nАккаунт {dm.get_name_and_tag(callback_data.tag)} '
                  f'привязан к пользователю '
                  f'{dm.get_full_name_and_username(callback_data.id)}')
        tg_user_id = callback.from_user.id
        description = (f'Bind account {dm.get_name_and_tag(callback_data.tag)} '
                       f'to user {dm.get_full_name_and_username(callback_data.id)}')
        await dm.req_connection.execute('''
            INSERT INTO public.admin_action (tg_user_id, description, date_and_time)
            VALUES ($1, $2, CURRENT_TIMESTAMP(0))
        ''', tg_user_id, description)
    else:
        answer = (f'⚙️ Привязка аккаунта к пользователю\n\nАккаунт {dm.get_name_and_tag(callback_data.tag)} '
                  f'уже был привязан к пользователю '
                  f'{dm.get_full_name_and_username(callback_data.id)}')
        tg_user_id = callback.from_user.id
        description = (f'Account {dm.get_name_and_tag(callback_data.tag)} was already bound '
                       f'to user {dm.get_full_name_and_username(callback_data.id)}')
        await dm.req_connection.execute('''
            INSERT INTO public.admin_action (tg_user_id, description, date_and_time)
            VALUES ($1, $2, CURRENT_TIMESTAMP(0))
        ''', tg_user_id, description)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='⬅️ Назад',
                             callback_data=AdminCallbackFactory(
                                 state='admin'
                             ).pack())
    ]])
    return answer, ParseMode.HTML, keyboard


@router.callback_query(AdminCallbackFactory.filter(F.state == 'link_finish'))
async def callback_link_finish(callback: CallbackQuery, callback_data: AdminCallbackFactory,
                               dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.check_message(callback.message.chat.id,
                                                   callback.message.message_id,
                                                   callback.from_user.id)
    if not user_is_message_owner:
        await callback.answer('Эта кнопка не для вас!')
    else:
        answer, parse_mode, reply_markup = await admin_link_finish(dm, callback_data, callback)
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback.answer()


async def admin_unlink_id(dm: DatabaseManager):
    answer = f'<b>⚙️ Отвязка аккаунта от пользователя\n\nВыберите пользователя:</b>'
    query = await dm.req_connection.fetch('''
        SELECT id, username, first_name, last_name
        FROM public.telegram_user
        WHERE id IN (SELECT id FROM public.tg_user_coc_account)
        ORDER BY first_name, last_name
    ''')
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=dm.get_full_name_and_username(record['id']),
                              callback_data=AdminCallbackFactory(
                                  state='unlink_id_tag',
                                  id=record['id']
                              ).pack())]
        for record in query
    ] + [[
        InlineKeyboardButton(text='⬅️ Назад',
                             callback_data=AdminCallbackFactory(
                                 state='admin'
                             ).pack()),
        InlineKeyboardButton(text='🔄 Обновить',
                             callback_data=AdminCallbackFactory(
                                 state='unlink_id'
                             ).pack())
    ]])
    return answer, ParseMode.HTML, keyboard


@router.callback_query(AdminCallbackFactory.filter(F.state == 'unlink_id'))
async def callback_unlink_id(callback: CallbackQuery, callback_data: AdminCallbackFactory,
                             dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.check_message(callback.message.chat.id,
                                                   callback.message.message_id,
                                                   callback.from_user.id)
    if not user_is_message_owner:
        await callback.answer('Эта кнопка не для вас!')
    else:
        answer, parse_mode, reply_markup = await admin_unlink_id(dm)
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback.answer()


async def admin_unlink_tag(dm: DatabaseManager, callback_data: AdminCallbackFactory):
    answer = (f'<b>⚙️ Отвязка аккаунта от пользователя\n\nВыберите аккаунт, который будет отвязан от пользователя '
              f'{dm.get_full_name_and_username(callback_data.id)}:</b>')
    query = await dm.req_connection.fetch('''
        SELECT tag, name
        FROM
            public.clash_of_clans_account
            JOIN public.tg_user_coc_account USING (tag)
        WHERE id = $1
        ORDER BY name
    ''', callback_data.id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=dm.get_name_and_tag(record['tag']),
                              callback_data=AdminCallbackFactory(
                                  state='unlink_finish',
                                  id=callback_data.id,
                                  tag=record['tag']
                              ).pack())]
        for record in query
    ] + [[
        InlineKeyboardButton(text='⬅️ Назад',
                             callback_data=AdminCallbackFactory(
                                 state='unlink_id'
                             ).pack()),
        InlineKeyboardButton(text='🔄 Обновить',
                             callback_data=AdminCallbackFactory(
                                 state='unlink_id_tag',
                                 id=callback_data.id
                             ).pack())
    ]])
    return answer, ParseMode.HTML, keyboard


@router.callback_query(AdminCallbackFactory.filter(F.state == 'unlink_id_tag'))
async def callback_unlink_id_tag(callback: CallbackQuery, callback_data: AdminCallbackFactory,
                                 dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.check_message(callback.message.chat.id,
                                                   callback.message.message_id,
                                                   callback.from_user.id)
    if not user_is_message_owner:
        await callback.answer('Эта кнопка не для вас!')
    else:
        answer, parse_mode, reply_markup = await admin_unlink_tag(dm, callback_data)
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback.answer()


async def admin_unlink_finish(dm: DatabaseManager, callback_data, callback: CallbackQuery):
    query = await dm.req_connection.fetch('''
        SELECT *
        FROM public.tg_user_coc_account
        WHERE id = $1 AND tag = $2
    ''', callback_data.id, callback_data.tag)
    if len(query) > 0:
        await dm.req_connection.execute('''
            DELETE FROM public.tg_user_coc_account
            WHERE id = $1 AND tag = $2
        ''', callback_data.id, callback_data.tag)
        answer = (f'⚙️ Отвязка аккаунта от пользователя\n\nАккаунт {dm.get_name_and_tag(callback_data.tag)} '
                  f'отвязан от пользователя '
                  f'{dm.get_full_name_and_username(callback_data.id)}')
        tg_user_id = callback.from_user.id
        description = (f'Unbind account {dm.get_name_and_tag(callback_data.tag)} '
                       f'from user {dm.get_full_name_and_username(callback_data.id)}')
        await dm.req_connection.execute('''
            INSERT INTO public.admin_action (tg_user_id, description, date_and_time)
            VALUES ($1, $2, CURRENT_TIMESTAMP(0))
        ''', tg_user_id, description)
    else:
        answer = (f'⚙️ Отвязка аккаунта от пользователя\n\nАккаунт {dm.get_name_and_tag(callback_data.tag)} '
                  f'уже был отвязан от пользователя '
                  f'{dm.get_full_name_and_username(callback_data.id)}')
        tg_user_id = callback.from_user.id
        description = (f'Account {dm.get_name_and_tag(callback_data.tag)} was already unbound '
                       f'from user {dm.get_full_name_and_username(callback_data.id)}')
        await dm.req_connection.execute('''
            INSERT INTO public.admin_action (tg_user_id, description, date_and_time)
            VALUES ($1, $2, CURRENT_TIMESTAMP(0))
        ''', tg_user_id, description)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='⬅️ Назад',
                             callback_data=AdminCallbackFactory(
                                 state='admin'
                             ).pack())
    ]])
    return answer, ParseMode.HTML, keyboard


@router.callback_query(AdminCallbackFactory.filter(F.state == 'unlink_finish'))
async def callback_link_finish(callback: CallbackQuery, callback_data: AdminCallbackFactory,
                               dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.check_message(callback.message.chat.id,
                                                   callback.message.message_id,
                                                   callback.from_user.id)
    if not user_is_message_owner:
        await callback.answer('Эта кнопка не для вас!')
    else:
        answer, parse_mode, reply_markup = await admin_unlink_finish(dm, callback_data, callback)
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback.answer()


async def edit_statuses(dm: DatabaseManager, callback_data: AdminCallbackFactory, callback: CallbackQuery):
    if callback_data.tag is not None:
        await dm.req_connection.execute('''
            UPDATE public.clash_of_clans_account
            SET participates_in_clan_wars = $2
            WHERE tag = $1
        ''', callback_data.tag, callback_data.participates)
        tg_user_id = callback.from_user.id
        description = (f'{dm.get_name_and_tag(callback_data.tag)} '
                       f'status was updated to {callback_data.participates}')
        await dm.req_connection.execute('''
            INSERT INTO public.admin_action (tg_user_id, description, date_and_time)
            VALUES ($1, $2, CURRENT_TIMESTAMP(0))
        ''', tg_user_id, description)

    answer = f'<b>⚙️ Редактирование статусов участия в КВ\n\nВыберите аккаунт:</b>'
    query = await dm.req_connection.fetch('''
        SELECT 
            tag, name, participates_in_clan_wars, 
            town_hall, barbarian_king, archer_queen, grand_warden, royal_champion
        FROM public.clash_of_clans_account
        WHERE in_clan
        ORDER BY town_hall DESC, (barbarian_king + archer_queen + grand_warden + royal_champion) DESC, name
    ''')
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f'{'✅' if record['participates_in_clan_wars'] else '❌'} '
                                   f'{dm.get_name(record['tag'])} — '
                                   f'🛖 {record['town_hall']}, '
                                   f'👑 {record['barbarian_king']} / {record['archer_queen']} / '
                                   f'{record['grand_warden']} / {record['royal_champion']}',
                              callback_data=AdminCallbackFactory(
                                  state='edit_statuses',
                                  tag=record['tag'],
                                  participates=not record['participates_in_clan_wars']
                              ).pack())]
        for record in query
    ] + [
        [InlineKeyboardButton(text='⬅️ Назад',
                              callback_data=AdminCallbackFactory(
                                  state='admin'
                              ).pack())]
    ])
    return answer, ParseMode.HTML, keyboard


@router.callback_query(AdminCallbackFactory.filter(F.state.in_({'edit_statuses'})))
async def callback_edit_statuses(callback: CallbackQuery, callback_data: AdminCallbackFactory,
                                 dm: DatabaseManager) -> None:
    user_is_message_owner = await dm.check_message(callback.message.chat.id,
                                                   callback.message.message_id,
                                                   callback.from_user.id)
    if not user_is_message_owner:
        await callback.answer('Эта кнопка не для вас!')
    else:
        answer, parse_mode, reply_markup = await edit_statuses(dm, callback_data, callback)
        with suppress(TelegramBadRequest):
            await callback.message.edit_text(text=answer, parse_mode=parse_mode, reply_markup=reply_markup)
        await callback.answer()


@router.message()
async def unhandled_message(message: Message, dm: DatabaseManager):
    logging.info(message)
