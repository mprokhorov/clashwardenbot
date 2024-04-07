import logging
import datetime
from datetime import UTC
from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.enums import ParseMode, ChatType
from aiogram.types import TelegramObject, Message, CallbackQuery

from bot.commands import bot_cmd_list
from database_manager import DatabaseManager


class MessageMiddleware(BaseMiddleware):
    def __init__(self):
        pass

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            message: Message,
            data: Dict[str, Any]
    ) -> Any:
        message_info = (
            f'chat_id={message.chat.id}, '
            f'user_id={message.from_user.id}, '
            f'username = {message.from_user.username}, '
            f'first_name = {message.from_user.first_name}, '
            f'last_name = {message.from_user.last_name}, '
            f'forward_origin = {message.forward_origin}, '
            f'html_text = {message.html_text}, '
            f'entities = {message.entities}'
        )
        dm: DatabaseManager = data['dm']
        clan_name = await dm.get_clan_name()
        bot_username = (await dm.bot.me()).username

        if message.from_user.id in dm.blocked_user_ids:
            logging.info(f'Message {{{message_info}}} was not propagated')
            return None

        if message.chat.type in (ChatType.PRIVATE, ChatType.GROUP, ChatType.SUPERGROUP):
            if not message.from_user.is_bot:
                await dm.dump_chat(message.chat)
                await dm.dump_user(message.chat, message.from_user)
            if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
                for new_chat_member in (message.new_chat_members or []):
                    if not new_chat_member.is_bot:
                        await dm.dump_user(message.chat, new_chat_member)
                        await dm.load_and_cache_names()
                if message.left_chat_member and not message.left_chat_member.is_bot:
                    await dm.undump_user(message.chat, message.left_chat_member)

            bot_commands = [
                entity for entity in message.entities or []
                if entity.type == 'bot_command'
            ]
            if len(bot_commands) == 0:
                logging.info(f'Message {{{message_info}}} was not propagated')
                return None
            else:
                first_command = message.text[bot_commands[0].offset:bot_commands[0].offset + bot_commands[0].length]
                acceptable_commands = [bot_cmd.command for bot_cmd in bot_cmd_list]
                if self.is_command_for_bot(first_command, bot_username) and not message.forward_origin:
                    if self.is_command_valid(first_command, ['start', 'help']):
                        logging.info(f'Message {{{message_info}}} was propagated')
                        return await handler(message, data)
                    elif self.is_command_valid(first_command, acceptable_commands):
                        if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
                            if message.chat.id in await dm.get_chats_linked_to_clan() or not dm.is_privacy_mode_enabled:
                                logging.info(f'Message {{{message_info}}} was propagated')
                                return await handler(message, data)
                            else:
                                await message.reply(
                                    text=f'Группа не привязана к клану {dm.of.to_html(clan_name)}',
                                    parse_mode=ParseMode.HTML
                                )
                                logging.info(f'Message {{{message_info}}} was not propagated')
                                return None
                        elif message.chat.type == ChatType.PRIVATE:
                            if await dm.can_user_use_bot(message.from_user.id) or not dm.is_privacy_mode_enabled:
                                logging.info(f'Message {{{message_info}}} was propagated')
                                return await handler(message, data)
                            else:
                                await message.reply(
                                    text=f'Вы не состоите в группе клана {dm.of.to_html(clan_name)}',
                                    parse_mode=ParseMode.HTML
                                )
                                logging.info(f'Message {{{message_info}}} was not propagated')
                                return None
                        else:
                            logging.info(f'Message {{{message_info}}} was not propagated')
                            return None
                    else:
                        await message.reply(text=f'Такой команды нет', parse_mode=ParseMode.HTML)
                        logging.info(f'Message {{{message_info}}} was not propagated')
                        return None
                else:
                    logging.info(f'Message {{{message_info}}} was not propagated')
                    return None
        else:
            logging.info(f'Message {{{message_info}}} was not propagated')
            return

    @staticmethod
    def is_command_valid(text: str, valid_commands: list[str]) -> bool:
        if len(text.split('@')) == 1:
            return text.lstrip('/') in valid_commands
        bot_command, _ = text.split('@')
        return bot_command.lstrip('/') in valid_commands

    @staticmethod
    def is_command_for_bot(text: str, bot_username: str) -> bool:
        if len(text.split('@')) == 1:
            return True
        else:
            _, username = text.split('@')
            return username == bot_username


class CallbackQueryMiddleware(BaseMiddleware):
    def __init__(self):
        pass

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            callback_query: CallbackQuery,
            data: Dict[str, Any]
    ) -> Any:
        callback_query_info = (
            f'chat_id={callback_query.message.chat.id}, '
            f'user_id={callback_query.from_user.id}, '
            f'username = {callback_query.from_user.username}, '
            f'first_name = {callback_query.from_user.first_name}, '
            f'last_name = {callback_query.from_user.last_name}, '
            f'data = {callback_query.data}'
        )
        if (datetime.datetime.now(UTC) - callback_query.message.date).days >= 1:
            await callback_query.answer('Сообщение устарело')
            logging.info(f'CallbackQuery {{{callback_query_info}}} was not propagated')
            return
        else:
            logging.info(f'CallbackQuery {{{callback_query_info}}} was propagated')
            return await handler(callback_query, data)
