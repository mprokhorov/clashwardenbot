import argparse

import asyncpg
from pyrogram import Client
from pyrogram.enums import ChatType

from bot.config import config

app = Client(name=config.telegram_api_client_name.get_secret_value(),
             api_id=int(config.telegram_api_id.get_secret_value()),
             api_hash=config.telegram_api_hash.get_secret_value())


async def main():
    await app.start()
    dialogs = app.get_dialogs()
    group_dialogs = []
    async for dialog in dialogs:
        if dialog.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
            group_dialogs.append(dialog.chat)
    for i, group_dialog in enumerate(group_dialogs):
        print(f'{i + 1}) {group_dialog.title}')
    chat_idx = input('Enter group chat number: ')
    updated_dialog = group_dialogs[int(chat_idx) - 1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--bot_number")
    args = parser.parse_args()
    bot_number = int(args.bot_number)
    connection = await asyncpg.connect(host=config.postgres_host.get_secret_value(),
                                       database=config.postgres_database.get_secret_value(),
                                       user=config.postgres_user.get_secret_value(),
                                       password=config.postgres_password.get_secret_value(),
                                       server_settings={'search_path': 'public'})
    clan_tag = config.clan_tags[bot_number].get_secret_value()
    user_data = [(clan_tag, updated_dialog.id, user.user.id,
                  user.user.username, user.user.first_name, user.user.last_name)
                 async for user in app.get_chat_members(updated_dialog.id)
                 if not user.user.is_bot]
    await connection.execute('''
        UPDATE bot_user
        SET is_user_in_chat = FALSE
        WHERE (clan_tag, chat_id) = ($1, $2)
    ''', clan_tag, updated_dialog.id)
    await connection.executemany('''
        INSERT INTO bot_user
            (clan_tag, chat_id, user_id, username, first_name, last_name, is_user_in_chat, first_seen, last_seen)
        VALUES
            ($1, $2, $3, $4, $5, $6, TRUE, NULL, CURRENT_TIMESTAMP(0))
        ON CONFLICT
            (clan_tag, chat_id, user_id)
        DO UPDATE
        SET (username, first_name, last_name, is_user_in_chat, last_seen) =  ($4, $5, $6, TRUE, CURRENT_TIMESTAMP(0))
    ''', user_data)
    await app.stop()


app.run(main())
