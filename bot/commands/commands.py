from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats


async def set_cw_commands(bot: Bot):
    cw_private_chats_commands = []
    with open('bot/commands/cw/private_chats_commands.txt', 'r', encoding='utf8') as file:
        for line in file:
            command, description = line.strip().split(' - ')
            cw_private_chats_commands.append(BotCommand(command=command, description=description))
    await bot.set_my_commands(
        commands=cw_private_chats_commands,
        scope=BotCommandScopeAllPrivateChats()
    )

    cw_group_chats_commands = []
    with open('bot/commands/cw/group_chats_commands.txt', 'r', encoding='utf8') as file:
        for line in file:
            command, description = line.strip().split(' - ')
            cw_group_chats_commands.append(BotCommand(command=command, description=description))
    await bot.set_my_commands(
        commands=cw_group_chats_commands,
        scope=BotCommandScopeAllGroupChats()
    )


async def set_cwl_commands(bot: Bot):
    cwl_private_chats_commands = []
    with open('bot/commands/cwl/private_chats_commands.txt', 'r', encoding='utf8') as file:
        for line in file:
            command, description = line.strip().split(' - ')
            cwl_private_chats_commands.append(BotCommand(command=command, description=description))
    await bot.set_my_commands(
        commands=cwl_private_chats_commands,
        scope=BotCommandScopeAllPrivateChats()
    )

    cwl_group_chats_commands = []
    with open('bot/commands/cwl/group_chats_commands.txt', 'r', encoding='utf8') as file:
        for line in file:
            command, description = line.strip().split(' - ')
            cwl_group_chats_commands.append(BotCommand(command=command, description=description))
    await bot.set_my_commands(
        commands=cwl_group_chats_commands,
        scope=BotCommandScopeAllGroupChats()
    )
