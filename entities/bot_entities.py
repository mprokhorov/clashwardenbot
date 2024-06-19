from dataclasses import dataclass


@dataclass
class CommandSettings:
    command: str
    description: str
    scopes: list[str]
    events: list[str]


@dataclass
class BotUser:
    chat_id: int
    user_id: int
