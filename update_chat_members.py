from pyrogram import Client
from pyrogram.enums import ChatType

from bot.config import config
from database_manager import DatabaseManager

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
    chat_idx = input('Select group chat number: ')
    updated_dialog = group_dialogs[int(chat_idx) - 1]

    dm = DatabaseManager()
    await dm.establish_connections()
    user_data = [(user.user.id, user.user.username, user.user.first_name, user.user.last_name)
                 async for user in app.get_chat_members(updated_dialog.id)
                 if not user.user.is_bot]
    await dm.req_connection.execute('''
        UPDATE public.telegram_user
        SET in_chat = FALSE
    ''')
    await dm.req_connection.executemany('''
        INSERT INTO public.telegram_user
        VALUES ($1, $2, $3, $4, TRUE, CURRENT_TIMESTAMP(0), CURRENT_TIMESTAMP(0))
        ON CONFLICT(id)
        DO UPDATE SET (username, first_name, last_name, in_chat, last_seen) =
                      ($2, $3, $4, TRUE, CURRENT_TIMESTAMP(0))
    ''', user_data)

    await app.stop()


app.run(main())
