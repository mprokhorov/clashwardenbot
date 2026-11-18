"""
One-off script: wraps player names from the non_clickable_player_name table in <code> in old bot messages of a clan
chat, so that Telegram stops treating names like "ard.man" as links.

Bots can not search chat history, so the script reads messages by id via MTProto (Pyrogram logged in with the bot
token), from the newest to the oldest, and edits only messages sent by the bot itself.

Run from the bot directory as the bot user, for example:
    sudo -u clashwardenbot .venv/bin/python -m scripts.make_names_non_clickable --bot_number=1 --mode=latest --dry_run
    sudo -u clashwardenbot .venv/bin/python -m scripts.make_names_non_clickable --bot_number=1 --mode=all

--mode=latest  edit only the newest message found (a test run)
--mode=all     edit all messages found
--dry_run      only show what would be edited
--chat_id      chat to process (the main chat of the clan by default)
"""
import argparse
import asyncio
import html
import re

import asyncpg
from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait, MessageNotModified

from config import config

BATCH_SIZE = 200
SECONDS_BETWEEN_BATCHES = 1
SECONDS_BETWEEN_EDITS = 3
EMPTY_BATCHES_AFTER_LAST_KNOWN_MESSAGE = 5
SKIPPED_TAGS = {'code', 'pre', 'a'}


def make_names_non_clickable(html_text: str, names: set[str]) -> str:
    # Names are matched in both escaping styles, with and without escaped quotes
    escaped_names = {html.escape(name, quote=quote) for name in names for quote in [False, True]}
    pattern = re.compile(
        r'(?<![\w.@/])(?:' + '|'.join(re.escape(name) for name in sorted(escaped_names, key=len, reverse=True)) + r')(?![\w])'
    )
    parts = re.split(r'(<[^>]*>)', html_text)
    skipped_depth = 0
    for i, part in enumerate(parts):
        if part.startswith('<'):
            tag = re.match(r'<\s*(/?)\s*([a-zA-Z-]+)', part)
            if tag and tag.group(2).lower() in SKIPPED_TAGS:
                skipped_depth += -1 if tag.group(1) else 1
        elif skipped_depth == 0 and part:
            parts[i] = pattern.sub(lambda match: f'<code>{match.group(0)}</code>', part)
    return ''.join(parts)


async def call_with_flood_wait(function, *args, **kwargs):
    while True:
        try:
            return await function(*args, **kwargs)
        except FloodWait as e:
            print(f'FloodWait: waiting {e.value} s')
            await asyncio.sleep(e.value + 1)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--bot_number', type=int, required=True)
    parser.add_argument('--mode', choices=['latest', 'all'], required=True)
    parser.add_argument('--dry_run', action='store_true')
    parser.add_argument('--chat_id', type=int)
    args = parser.parse_args()
    clan_tag = config.clan_tags[args.bot_number].get_secret_value()

    connection = await asyncpg.connect(
        host=config.postgres_host.get_secret_value(),
        database=config.postgres_database.get_secret_value(),
        user=config.postgres_user.get_secret_value(),
        password=config.postgres_password.get_secret_value(),
        server_settings={'search_path': config.postgres_schema.get_secret_value()}
    )
    names = {row['player_name'] for row in await connection.fetch('SELECT player_name FROM non_clickable_player_name')}
    chat_id = args.chat_id or await connection.fetchval('SELECT main_chat_id FROM clan WHERE clan_tag = $1', clan_tag)
    last_known_message_id = await connection.fetchval(
        'SELECT MAX(message_id) FROM message_bot_user WHERE (clan_tag, chat_id) = ($1, $2)', clan_tag, chat_id
    ) or 0
    await connection.close()
    if not names:
        print('Table non_clickable_player_name is empty')
        return
    print(f'Chat {chat_id}, names: {", ".join(sorted(names))}')

    app = Client(
        name='make_names_non_clickable',
        api_id=int(config.telegram_api_id.get_secret_value()),
        api_hash=config.telegram_api_hash.get_secret_value(),
        bot_token=config.telegram_bot_api_tokens[args.bot_number].get_secret_value(),
        in_memory=True,
        no_updates=True
    )
    async with app:
        me = await app.get_me()
        # The newest message id is unknown to a bot, so the scan starts a little above the newest known bot reply
        # and goes further up while messages are found
        top_message_id = last_known_message_id
        while True:
            message_ids = list(range(top_message_id + 1, top_message_id + 1 + BATCH_SIZE))
            messages = await call_with_flood_wait(app.get_messages, chat_id, message_ids)
            await asyncio.sleep(SECONDS_BETWEEN_BATCHES)
            if all(message.empty for message in messages):
                break
            top_message_id += BATCH_SIZE
        top_message_id += BATCH_SIZE * EMPTY_BATCHES_AFTER_LAST_KNOWN_MESSAGE
        print(f'Scanning messages {top_message_id}..1')

        edited_count = 0
        for batch_end in range(top_message_id, 0, -BATCH_SIZE):
            message_ids = list(range(batch_end, max(batch_end - BATCH_SIZE, 0), -1))
            messages = await call_with_flood_wait(app.get_messages, chat_id, message_ids)
            await asyncio.sleep(SECONDS_BETWEEN_BATCHES)
            for message in messages:
                if message.empty or message.from_user is None or message.from_user.id != me.id or not message.text:
                    continue
                if message.chat is None or message.chat.id != chat_id:
                    continue
                if not any(name in message.text for name in names):
                    continue
                new_html = make_names_non_clickable(message.text.html, names)
                if new_html == message.text.html:
                    continue
                print(f'\n#{message.id} {message.date:%Y-%m-%d %H:%M}\n  before: {message.text.html[:300]!r}\n  after:  {new_html[:300]!r}')
                if not args.dry_run:
                    try:
                        await call_with_flood_wait(
                            app.edit_message_text, chat_id, message.id, new_html,
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True,
                            reply_markup=message.reply_markup
                        )
                    except MessageNotModified:
                        pass
                    await asyncio.sleep(SECONDS_BETWEEN_EDITS)
                edited_count += 1
                if args.mode == 'latest':
                    break
            if args.mode == 'latest' and edited_count > 0:
                break
            if batch_end % (BATCH_SIZE * 50) < BATCH_SIZE:
                print(f'... message {batch_end}, found {edited_count}')
        print(f'\n{"Would edit" if args.dry_run else "Edited"}: {edited_count}')


if __name__ == '__main__':
    asyncio.run(main())
