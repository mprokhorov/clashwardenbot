import logging
import datetime
import re
from datetime import UTC
from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.enums import ParseMode, ChatType
from aiogram.types import TelegramObject, Message, CallbackQuery

from database_manager import DatabaseManager


class MessageMiddleware(BaseMiddleware):
    def __init__(self):
        pass

    async def __call__(self,
                       handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
                       message: Message,
                       data: Dict[str, Any]) -> Any:
        user_info = (f'chat_id={message.chat.id}, '
                     f'user_id={message.from_user.id}, '
                     f'username = {message.from_user.username}, '
                     f'first_name = {message.from_user.first_name}, '
                     f'last_name = {message.from_user.last_name}, '
                     f'text = {message.text}')
        dm: DatabaseManager = data['dm']
        row = await dm.req_connection.fetchrow('''
            SELECT clan_name
            FROM clan
            WHERE clan_tag = $1
        ''', dm.clan_tag)
        clan_name = row['clan_name']
        if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            await dm.dump_chat(message.chat)
            await dm.dump_user(message.chat, message.from_user)
            for new_chat_member in (message.new_chat_members or []):
                await dm.dump_user(message.chat, new_chat_member)
                await dm.load_and_cache_names()
            if message.left_chat_member and not message.left_chat_member.is_bot:
                await dm.undump_user(message.chat, message.left_chat_member)

            row = await dm.req_connection.fetch('''
                SELECT chat_id
                FROM clan_chat
                WHERE clan_tag = $1
            ''', dm.clan_tag)
            if message.chat.id in [row['chat_id'] for row in row]:
                logging.info(f'Message by {{{user_info}}} was propagated')
                return await handler(message, data)
            else:
                pattern = re.compile(r'^/[a-zA-Z0-9_]+' + re.escape((await dm.bot.me()).username) + r'$')
                if message.text and pattern.match(message.text):
                    await message.reply(
                        text=f'Группа не привязана к клану {clan_name}',
                        parse_mode=ParseMode.HTML)
                    logging.info(f'Message by {{{user_info}}} was not propagated')
                    return
                else:
                    logging.info(f'Message by {{{user_info}}} was not propagated')
                    return

        elif message.chat.type == ChatType.PRIVATE:
            await dm.dump_chat(message.chat)
            await dm.dump_user(message.chat, message.from_user)

            user_can_use_bot = await dm.can_user_use_bot(message.from_user.id)
            if user_can_use_bot:
                logging.info(f'Message by {{{user_info}}} was propagated')
                return await handler(message, data)
            else:
                await message.reply(
                    text=f'Вы не состоите в группе клана {clan_name}',
                    parse_mode=ParseMode.HTML)
                logging.info(f'Message by {{{user_info}}} was not propagated')
                return
        else:
            logging.info(f'Message by {{{user_info}}} was not propagated')
            return


class CallbackQueryMiddleware(BaseMiddleware):
    def __init__(self):
        pass

    async def __call__(self,
                       handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
                       callback_query: CallbackQuery,
                       data: Dict[str, Any]) -> Any:
        user_info = (f'chat_id={callback_query.message.chat.id}, '
                     f'user_id={callback_query.from_user.id}, '
                     f'username = {callback_query.from_user.username}, '
                     f'first_name = {callback_query.from_user.first_name}, '
                     f'last_name = {callback_query.from_user.last_name}, '
                     f'data = {callback_query.data}')
        if (datetime.datetime.now(UTC) - callback_query.message.date).days >= 1:
            await callback_query.answer('Сообщение устарело')
            logging.info(f'CallbackQuery by {{{user_info}}} was not propagated')
            return
        else:
            return await handler(callback_query, data)
