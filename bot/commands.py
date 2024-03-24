from collections import namedtuple

from aiogram.types import BotCommand

BotCMD = namedtuple('BotCMD', 'command description scopes req_event')


def get_shown_bot_commands(all_bot_cmd_list: list[BotCMD], scopes: list[str], events: list[str]) -> list[BotCommand]:
    shown_bot_commands = []
    for bot_cmd in all_bot_cmd_list:
        events_requirements_met = any(event in bot_cmd.req_event for event in events) or not bot_cmd.req_event
        scope_allowed = any(scope in bot_cmd.scopes for scope in scopes)
        if ('ANY' in events or events_requirements_met) and scope_allowed:
            shown_bot_commands.append(BotCommand(command=bot_cmd.command, description=bot_cmd.description))
    return shown_bot_commands


bot_cmd_list = []
with open(file='bot/commands.txt', mode='r', encoding='utf8') as file:
    for line in file:
        command, description, scopes_data, events_data = map(str.strip, line.split('|'))
        bot_cmd_list.append(BotCMD(
            command,
            description,
            scopes_data.split(', ') if scopes_data else [],
            events_data.split(', ') if events_data else []
        ))
