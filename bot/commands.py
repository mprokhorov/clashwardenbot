from aiogram.types import BotCommand

from entities import CommandSettings


def get_shown_bot_commands(
        all_command_settings_list: list[CommandSettings], scopes: list[str], events: list[str]
) -> list[BotCommand]:
    shown_bot_commands = []
    for command_settings in all_command_settings_list:
        scope_allowed = any(scope in command_settings.scopes for scope in scopes)
        events_requirements_met = any(event in command_settings.events for event in events)
        if scope_allowed and (events_requirements_met or len(command_settings.events) == 0 or 'ANY' in events):
            shown_bot_commands.append(BotCommand(
                command=command_settings.command, description=command_settings.description
            ))
    return shown_bot_commands


bot_cmd_list = []
with open(file='bot/commands.txt', mode='r', encoding='utf8') as file:
    for line in file:
        command, description, scopes_data, events_data = map(str.strip, line.split('|'))
        bot_cmd_list.append(CommandSettings(
            command,
            description,
            scopes_data.split(', ') if len(scopes_data) > 0 else [],
            events_data.split(', ') if len(events_data) > 0 else []
        ))
