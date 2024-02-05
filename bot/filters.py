from aiogram.filters import BaseFilter
from aiogram.types import Message


class NewChatMembersFilter(BaseFilter):
    def __init__(self):
        pass

    async def __call__(self, message: Message) -> bool:
        return message.new_chat_members is not None
