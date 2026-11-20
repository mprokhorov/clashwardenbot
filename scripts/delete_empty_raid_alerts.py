"""
One-off script: deletes "Raids ended" alerts about raid weekends without a single attack from all clan chats of all bots.

Alerts are not saved with message ids, but every sent alert is logged in the action table with its chat and time.
Message ids grow with time, so the script finds each alert by a binary search over message dates (via MTProto,
Pyrogram logged in with the bot token) and checks the found message in Telegram before deleting it.

Run from the bot directory as the bot user:
    sudo -u clashwardenbot .venv/bin/python -m scripts.delete_empty_raid_alerts            # dry run, nothing is deleted
    sudo -u clashwardenbot .venv/bin/python -m scripts.delete_empty_raid_alerts --delete   # delete the found messages

--bot_number   process only one bot
"""
import argparse
import asyncio
import re
from datetime import datetime, timedelta, UTC

import asyncpg
from pyrogram import Client
from pyrogram import utils as pyrogram_utils
from pyrogram.errors import FloodWait, RPCError

from config import config

# Pyrogram 2.0.106 knows only the old 32-bit chat ids, newer groups and supergroups (like -1003406349643) have bigger ones
pyrogram_utils.MIN_CHAT_ID = -999999999999
pyrogram_utils.MIN_CHANNEL_ID = -1009999999999

ALERT_TITLE = '💬 Рейды закончились'
NO_ATTACKS_MARK = 'Сделано атак: 0 /'
BATCH_SIZE = 200
SECONDS_BETWEEN_REQUESTS = 1
EMPTY_BATCHES_AT_THE_END = 5
MAX_MESSAGE_ID = 2 ** 26
SEARCH_MARGIN = timedelta(minutes=2)


async def call_with_flood_wait(function, *args, **kwargs):
    while True:
        try:
            result = await function(*args, **kwargs)
            await asyncio.sleep(SECONDS_BETWEEN_REQUESTS)
            return result
        except FloodWait as e:
            print(f'    (Telegram asks to wait {e.value} s)')
            await asyncio.sleep(e.value + 1)


def to_timestamp(dt: datetime) -> float:
    # Pyrogram returns naive local time, the action table stores naive UTC
    return dt.timestamp()


def is_empty_raid_alert(message, bot_id: int, chat_id: int) -> bool:
    return (
        not message.empty and message.from_user is not None and message.from_user.id == bot_id
        and message.chat is not None and message.chat.id == chat_id
        and message.text is not None and message.text.startswith(ALERT_TITLE) and NO_ATTACKS_MARK in message.text
    )


class ChatScanner:
    def __init__(self, app: Client, chat_id: int):
        self.app = app
        self.chat_id = chat_id
        self.first_messages = {}

    async def get_batch(self, first_id: int) -> list:
        return await call_with_flood_wait(self.app.get_messages, self.chat_id, list(range(first_id, first_id + BATCH_SIZE)))

    async def first_message_from(self, message_id: int):
        # The first existing message with id >= message_id (deleted messages leave gaps)
        batch_start = (message_id // BATCH_SIZE) * BATCH_SIZE + 1
        if batch_start not in self.first_messages:
            messages = [message for message in await self.get_batch(batch_start) if not message.empty]
            self.first_messages[batch_start] = messages[0] if messages else None
        return self.first_messages[batch_start]

    async def first_id_after(self, moment: float, low: int, high: int) -> int:
        # Binary search over batches: the first batch that contains a message sent at or after the moment
        while high - low > BATCH_SIZE:
            middle = (low + high) // 2
            message = await self.first_message_from(middle)
            if message is not None and to_timestamp(message.date) < moment:
                low = middle
            else:
                high = middle
        return low

    async def find_alerts(self, start_id: int, moment_to: float, bot_id: int) -> list:
        # Reads forward until a message newer than the moment, or until the end of the chat
        found = []
        batch_start = max(start_id - BATCH_SIZE, 1)
        empty_batches = 0
        while empty_batches < EMPTY_BATCHES_AT_THE_END:
            messages = await self.get_batch(batch_start)
            existing = [message for message in messages if not message.empty]
            found += [message for message in existing if is_empty_raid_alert(message, bot_id, self.chat_id)]
            if existing and to_timestamp(existing[-1].date) > moment_to:
                break
            empty_batches = 0 if existing else empty_batches + 1
            batch_start += BATCH_SIZE
        return found


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--delete', action='store_true')
    parser.add_argument('--bot_number', type=int)
    args = parser.parse_args()
    clan_tags = [clan_tag.get_secret_value() for clan_tag in config.clan_tags]

    connection = await asyncpg.connect(
        host=config.postgres_host.get_secret_value(),
        database=config.postgres_database.get_secret_value(),
        user=config.postgres_user.get_secret_value(),
        password=config.postgres_password.get_secret_value(),
        server_settings={'search_path': config.postgres_schema.get_secret_value()}
    )
    rows = await connection.fetch('''
        SELECT clan_tag, action_timestamp, description
        FROM action
        WHERE description LIKE $1 AND description LIKE $2
        ORDER BY clan_tag, action_timestamp
    ''', f'Message "<b>{ALERT_TITLE}</b>%', f'%{NO_ATTACKS_MARK}%')
    alerts = {}
    for row in rows:
        chat_match = re.search(r'\((-?\d+)\)$', row['description'])
        if chat_match:
            alerts.setdefault((row['clan_tag'], int(chat_match.group(1))), []).append(row['action_timestamp'])
    clan_names = {row['clan_tag']: row['clan_name'] for row in await connection.fetch('SELECT clan_tag, clan_name FROM clan')}
    chat_titles = {(row['clan_tag'], row['chat_id']): row['title'] for row in await connection.fetch('SELECT clan_tag, chat_id, title FROM chat')}
    await connection.close()

    print(f'{"Deleting" if args.delete else "Dry run, nothing is deleted"}. Alerts about raids without attacks in the log: {len(rows)}\n')
    total_found, total_deleted, total_missing, failed = 0, 0, 0, []
    for clan_tag in sorted({clan_tag for clan_tag, _ in alerts}):
        if clan_tag not in clan_tags:
            print(f'Clan {clan_tag} is not in CLAN_TAGS, skipped\n')
            continue
        bot_number = clan_tags.index(clan_tag)
        if args.bot_number is not None and bot_number != args.bot_number:
            continue
        app = Client(
            name=f'delete_empty_raid_alerts_{bot_number}',
            api_id=int(config.telegram_api_id.get_secret_value()),
            api_hash=config.telegram_api_hash.get_secret_value(),
            bot_token=config.telegram_bot_api_tokens[bot_number].get_secret_value(),
            in_memory=True,
            no_updates=True
        )
        async with app:
            me = await app.get_me()
            print(f'━━ Bot {bot_number} @{me.username} · clan {clan_names.get(clan_tag, "?")} ({clan_tag})')
            for (alert_clan_tag, chat_id), moments in sorted(alerts.items()):
                if alert_clan_tag != clan_tag:
                    continue
                print(f'   Chat «{chat_titles.get((clan_tag, chat_id), chat_id)}» ({chat_id}): {len(moments)} alerts in the log')
                scanner = ChatScanner(app, chat_id)
                found = {}
                missing = []
                low = 1
                try:
                    for moment in moments:
                        moment_utc = moment.replace(tzinfo=UTC).timestamp()
                        start_id = await scanner.first_id_after(moment_utc - SEARCH_MARGIN.total_seconds(), low, MAX_MESSAGE_ID)
                        messages = await scanner.find_alerts(start_id, moment_utc + SEARCH_MARGIN.total_seconds(), me.id)
                        if not messages:
                            missing.append(moment.replace(tzinfo=UTC).astimezone().replace(tzinfo=None))
                        for message in messages:
                            found[message.id] = message
                        low = max(low, start_id - BATCH_SIZE)
                except Exception as e:
                    # One broken chat must not stop the others
                    print(f'   ⚠️  chat skipped: {getattr(e, "ID", None) or repr(e)}\n')
                    continue
                lines = [(moment, f'      ·  {"—":<9} {moment:%d.%m.%Y %H:%M}  not found in the chat (already deleted?)') for moment in missing]
                for message in found.values():
                    end_line = next((line for line in message.text.split('\n') if line.startswith('Конец рейдов')), '')
                    mark = '🗑' if args.delete else '✓'
                    lines.append((message.date, f'      {mark}  #{message.id:<8} {message.date:%d.%m.%Y %H:%M}  {end_line}'))
                for _, line in sorted(lines):
                    print(line)
                print(f'   → {len(found)} to delete, {len(missing)} not found')
                total_found += len(found)
                total_missing += len(missing)
                if args.delete and found:
                    for message_id in sorted(found):
                        try:
                            await call_with_flood_wait(app.delete_messages, chat_id, message_id)
                            total_deleted += 1
                        except RPCError as e:
                            failed.append((chat_id, message_id, getattr(e, 'ID', str(e))))
                print()

    print('━━ Summary')
    print(f'   Found in Telegram: {total_found}, not found: {total_missing}')
    if args.delete:
        print(f'   Deleted: {total_deleted}, failed: {len(failed)}')
        for chat_id, message_id, error in failed[:20]:
            print(f'      chat {chat_id}, message #{message_id}: {error}')
        if failed:
            print('   Bots can delete their own messages older than 48 hours only as admins with "delete messages" right')
    elif total_found:
        print('   Run again with --delete to delete them')


if __name__ == '__main__':
    asyncio.run(main())
