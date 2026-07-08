import logging

from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.enums import ParseMode
from aiogram.methods import SendMessage, EditMessageText


class MessageLoggingMiddleware(BaseRequestMiddleware):
    def __init__(self, dm):
        self.dm = dm

    async def __call__(self, make_request, bot, method):
        result = await make_request(bot, method)
        if (
            isinstance(method, (SendMessage, EditMessageText))
            and method.parse_mode == ParseMode.HTML
            and method.text
            and self.dm.connection_pool is not None
        ):
            try:
                if isinstance(method, SendMessage):
                    chat_id = int(method.chat_id)
                    message_id = result.message_id
                else:
                    if method.chat_id is None or method.message_id is None:
                        return result
                    chat_id = int(method.chat_id)
                    message_id = method.message_id
                await self.dm.log_bot_message(chat_id, message_id, method.text)
            except Exception as e:
                logging.debug(f'MessageLoggingMiddleware error: {e}')
        return result
