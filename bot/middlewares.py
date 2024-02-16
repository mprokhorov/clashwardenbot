import logging
from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.enums import ParseMode, ChatType
from aiogram.types import TelegramObject, Message

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
                     f'last_name = {message.from_user.last_name}')
        dm: DatabaseManager = data['dm']
        row = await dm.req_connection.fetchrow('''
            SELECT clan_name
            FROM clan
            WHERE clan_tag = $1
        ''', dm.clan_tag)
        clan_name = row['clan_name']
        if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            await dm.dump_group_chat(message)
            await dm.dump_tg_user(message.chat, message.from_user)

            for new_chat_member in (message.new_chat_members or []):
                await dm.dump_tg_user(message.chat, new_chat_member)
            if message.left_chat_member and not message.left_chat_member.is_bot:
                await dm.undump_tg_user(message.chat, message.left_chat_member)

            row = await dm.req_connection.fetch('''
                SELECT chat_id
                FROM clan_chat
                WHERE clan_tag = $1
            ''', dm.clan_tag)
            if message.chat.id in [row['chat_id'] for row in row]:
                logging.info(f'Message by {{{user_info}}} was propagated')
                return await handler(message, data)
            else:
                if message.text and message.text.startswith('/') and message.text.endswith(f'@{dm.telegram_bot_username}'):
                    await message.reply(
                        text=f'Группа не привязана к клану {clan_name}',
                        parse_mode=ParseMode.HTML)
                    logging.info(f'Message by {{{user_info}}} was not propagated')
                    return
                else:
                    logging.info(f'Message by {{{user_info}}} was not propagated')
                    return

        elif message.chat.type == ChatType.PRIVATE:
            await dm.dump_private_chat(message)
            await dm.dump_tg_user(message.chat, message.from_user)
            row = await dm.req_connection.fetchrow('''
                SELECT user_id
                FROM bot_user
                WHERE
                    clan_tag = $1
                    AND chat_id in (SELECT chat_id FROM clan_chat WHERE clan_tag = $1)
                    AND is_user_in_chat AND user_id = $2
                    OR can_use_bot_without_clan_group
            ''', dm.clan_tag, message.from_user.id)
            if row is not None:
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
