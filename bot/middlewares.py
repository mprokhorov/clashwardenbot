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
        dm: DatabaseManager = data['dm']
        clan_name = await dm.get_clan_name()
        bot_username = (await dm.bot.me()).username
        message_info = MessageMiddleware.get_message_attributes(message)
        if message.from_user.id in dm.blocked_user_ids:
            logging.info(f'Message {{{message_info}}} was not propagated')
            return None

        if message.chat.type in [ChatType.PRIVATE, ChatType.GROUP, ChatType.SUPERGROUP]:
            if not message.from_user.is_bot:
                await dm.dump_chat(message.chat)
                await dm.dump_user(message.chat, message.from_user)
            if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
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
                        if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
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
    def get_message_attributes(message: Message) -> str:
        message_info = []
        message_attribute_names = [
            'chat_id', 'user_id', 'username',
            'first_name', 'last_name', 'forward_origin',
            'reply_to_message', 'entities', 'html_text'
        ]
        message_attributes = [
            message.chat.id, message.from_user.id, message.from_user.username,
            message.from_user.first_name, message.from_user.last_name, message.forward_origin,
            message.reply_to_message, message.entities, message.html_text
        ]
        for message_attribute_name, message_attribute in zip(message_attribute_names, message_attributes):
            if isinstance(message_attribute, Message):
                message_info.append(
                    f'{message_attribute_name} = {{{MessageMiddleware.get_message_attributes(message_attribute)}}}'
                )
            elif message_attribute is not None:
                message_info.append(f'{message_attribute_name} = {message_attribute}')
        return ', '.join(message_info)

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
        callback_query_info = CallbackQueryMiddleware.get_callback_query_attributes(callback_query)
        if (datetime.datetime.now(UTC) - callback_query.message.date).days >= 1:
            await callback_query.answer('Сообщение устарело')
            logging.info(f'CallbackQuery {{{callback_query_info}}} was not propagated')
            return
        else:
            logging.info(f'CallbackQuery {{{callback_query_info}}} was propagated')
            return await handler(callback_query, data)

    @staticmethod
    def get_callback_query_attributes(callback_query: CallbackQuery) -> str:
        callback_query_info = []
        callback_query_attribute_names = [
            'chat_id', 'user_id', 'username',
            'first_name', 'last_name', 'data',
        ]
        callback_query_attributes = [
            callback_query.message.chat.id, callback_query.from_user.id, callback_query.from_user.username,
            callback_query.from_user.first_name, callback_query.from_user.last_name, callback_query.data
        ]
        for callback_query_attribute_name, callback_query_attribute in zip(
                callback_query_attribute_names, callback_query_attributes
        ):
            if callback_query_attribute is not None:
                callback_query_info.append(f'{callback_query_attribute_name} = {callback_query_attribute}')
        return ', '.join(callback_query_info)
