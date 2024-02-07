import logging
from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.enums import ParseMode
from aiogram.types import TelegramObject, Message, CallbackQuery

from bot.config import config
from database_manager import DatabaseManager


class MessageMiddleware(BaseMiddleware):
    def __init__(self):
        self.username_whitelist = []
        self.username_blacklist = []

    async def __call__(self,
                       handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
                       message: Message,
                       data: Dict[str, Any]) -> Any:
        dm: DatabaseManager = data['dm']
        user = message.from_user
        user_info = (f'chat_id={message.chat.id}, '
                     f'user_id={user.id}, '
                     f'username = {user.username}, '
                     f'first_name = {user.first_name}, '
                     f'last_name = {user.last_name}')

        await dm.update_user_in_db(user)

        if message.new_chat_members is not None:
            new_chat_member_list = message.new_chat_members
            for new_chat_member in new_chat_member_list:
                new_chat_member_id = new_chat_member.id
                new_chat_member_first_name = new_chat_member.first_name
                new_chat_member_last_name = new_chat_member.last_name
                if (dm.get_full_name(new_chat_member_id) is not None) and (not new_chat_member.is_bot):
                    await message.answer(
                        text=f'<a href="tg://user?id={new_chat_member.id}">'
                        f'{new_chat_member_first_name + (f' {new_chat_member_last_name}' if new_chat_member_last_name else '')}'
                        f'</a>, с возвращением!',
                        parse_mode=ParseMode.HTML)
                    await dm.update_user_in_db(user)
                elif not new_chat_member.is_bot:
                    await message.answer(
                        text=f'<a href="tg://user?id={new_chat_member.id}">'
                        f'{new_chat_member_first_name + (f' {new_chat_member_last_name}' if new_chat_member_last_name else '')}'
                        f'</a>, добро пожаловать!',
                        parse_mode=ParseMode.HTML)
                    await dm.insert_user_to_db(user)

        if message.left_chat_member is not None:
            if not message.left_chat_member.is_bot:
                await message.reply(
                    text=f'<a href="tg://user?id={message.left_chat_member.id}">'
                    f'{message.left_chat_member.first_name + (f' {message.left_chat_member.last_name}' if message.left_chat_member.last_name else '')}'
                    f'</a>, нам будет тебя не хватать...',
                    parse_mode=ParseMode.HTML)
                await dm.remove_user_from_db(user)

        if message.text is not None and message.text.startswith('/'):
            if message.chat.type in ['group', 'supergroup']:
                if message.chat.id == int(config.telegram_chat_id.get_secret_value()):
                    if user.username in self.username_blacklist:
                        logging.info(f'Message by {{{user_info}}} wasn\'t propagated')
                        return await message.reply(text='Вы находитесь в чёрном списке')
                    else:
                        logging.info(f'Message by {{{user_info}}} was propagated')
                        return await handler(message, data)
                elif message.text.endswith(config.telegram_bot_username.get_secret_value()):
                    if user.username in self.username_blacklist:
                        logging.info(f'Message by {{{user_info}}} wasn\'t propagated')
                        return await message.reply(text='Вы находитесь в чёрном списке')
                    else:
                        logging.info(f'Message by {{{user_info}}} wasn\'t propagated')
                        return await message.reply(text='Бота нельзя использовать в этой группе')
            if message.chat.type in ['private']:
                if user.username in self.username_blacklist:
                    logging.info(f'Message by {{{user_info}}} wasn\'t propagated')
                    return await message.reply(text='Вы находитесь в чёрном списке')
                if user.id in await dm.get_chat_member_id_list() or user.id in self.username_whitelist:
                    logging.info(f'Message by {{{user_info}}} was propagated')
                    return await handler(message, data)


class CallbackQueryMiddleware(BaseMiddleware):
    def __init__(self):
        self.username_whitelist = []
        self.username_blacklist = []

    async def __call__(self,
                       handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
                       callback_query: CallbackQuery,
                       data: Dict[str, Any]) -> Any:
        dm: DatabaseManager = data['dm']
        user = callback_query.from_user
        user_info = (f'chat_id={callback_query.message.chat.id}, '
                     f'user_id={user.id}, '
                     f'username = {user.username}, '
                     f'first_name = {user.first_name}, '
                     f'last_name = {user.last_name}')
        if callback_query.message.chat.type in ['group', 'supergroup']:
            if callback_query.message.chat.id == int(config.telegram_chat_id.get_secret_value()):
                if user.username in self.username_blacklist:
                    logging.info(f'Callback by {{{user_info}}} wasn\'t propagated')
                    return await callback_query.answer(text='Вы находитесь в чёрном списке')
                else:
                    logging.info(f'Callback by {{{user_info}}} was propagated')
                    return await handler(callback_query, data)
            else:
                if user.username in self.username_blacklist:
                    logging.info(f'Callback by {{{user_info}}} wasn\'t propagated')
                    return await callback_query.answer(text='Вы находитесь в чёрном списке')
                else:
                    logging.info(f'Callback by {{{user_info}}} wasn\'t propagated')
                    return await callback_query.answer(text='Бота нельзя использовать в этой группе')
        if callback_query.message.chat.type in ['private']:
            if user.username in self.username_blacklist:
                logging.info(f'Callback by {{{user_info}}} wasn\'t propagated')
                return await callback_query.answer(text='Вы находитесь в чёрном списке')
            if user.id in await dm.get_chat_member_id_list() or user.id in self.username_whitelist:
                logging.info(f'Callback by {{{user_info}}} was propagated')
                return await handler(callback_query, data)
