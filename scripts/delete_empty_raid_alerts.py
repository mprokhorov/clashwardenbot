"""
One-off script: deletes "Raids ended" alerts about raid weekends without a single attack from all clan chats of all bots.

Alerts are not saved with message ids, but every sent alert is logged in the action table with its chat and time.
Message ids grow with time, so the script finds each alert by a binary search over message dates (via MTProto,
Pyrogram logged in with the bot token) and checks the found message in Telegram before deleting it.

Reading a big chat this way is slow (Telegram lets a bot read history about once in 30 seconds), so found ids are saved
to a file, and ids of a big chat can be taken from a JSON export of the chat made in Telegram Desktop instead.
Deleting is cheap: 100 messages per request, every message is checked in Telegram right before deletion.

Run from the bot directory as the bot user:
    sudo -u clashwardenbot .venv/bin/python -m scripts.delete_empty_raid_alerts                   # dry run, saves found ids
    sudo -u clashwardenbot .venv/bin/python -m scripts.delete_empty_raid_alerts --bot_number=4    # dry run for one bot
    sudo -u clashwardenbot .venv/bin/python -m scripts.delete_empty_raid_alerts --export=/tmp/result.json --bot_number=2
    sudo -u clashwardenbot .venv/bin/python -m scripts.delete_empty_raid_alerts --delete_saved    # delete the saved ids
    sudo -u clashwardenbot .venv/bin/python -m scripts.delete_empty_raid_alerts --delete          # search and delete at once

--ids_file     where found ids are saved (/tmp/empty_raid_alerts.json by default)
"""
import argparse
import asyncio
import json
import math
import os
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
SEARCH_MARGIN = timedelta(minutes=2)
DELETE_BATCH_SIZE = 100
DEFAULT_IDS_FILE = '/tmp/empty_raid_alerts.json'


def bot_client(bot_number: int) -> Client:
    return Client(
        name=f'delete_empty_raid_alerts_{bot_number}',
        api_id=int(config.telegram_api_id.get_secret_value()),
        api_hash=config.telegram_api_hash.get_secret_value(),
        bot_token=config.telegram_bot_api_tokens[bot_number].get_secret_value(),
        in_memory=True,
        no_updates=True
    )


def load_saved_ids(path: str) -> dict:
    # {"<bot number>|<chat id>": [message ids]}
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as file:
        return json.load(file)


def save_ids(path: str, bot_number: int, chat_id: int, message_ids) -> None:
    saved = load_saved_ids(path)
    key = f'{bot_number}|{chat_id}'
    saved[key] = sorted(set(saved.get(key, [])) | set(message_ids))
    with open(path, 'w', encoding='utf-8') as file:
        json.dump(saved, file)


def end_line(text: str) -> str:
    return next((line for line in text.split('\n') if line.startswith('Конец рейдов')), '')


async def delete_alerts(app: Client, chat_id: int, message_ids: list, bot_id: int) -> tuple[list, list, list]:
    # Every message is checked in Telegram right before deletion: author, title and zero attacks
    alerts, skipped, failed = [], [], []
    for i in range(0, len(message_ids), BATCH_SIZE):
        messages = await call_with_flood_wait(app.get_messages, chat_id, message_ids[i:i + BATCH_SIZE])
        for message in messages:
            (alerts if is_empty_raid_alert(message, bot_id, chat_id) else skipped).append(message.id)
    deleted = []
    for i in range(0, len(alerts), DELETE_BATCH_SIZE):
        batch = alerts[i:i + DELETE_BATCH_SIZE]
        try:
            await call_with_flood_wait(app.delete_messages, chat_id, batch)
            deleted += batch
        except RPCError:
            for message_id in batch:
                try:
                    await call_with_flood_wait(app.delete_messages, chat_id, message_id)
                    deleted.append(message_id)
                except RPCError as e:
                    failed.append((message_id, getattr(e, 'ID', str(e))))
    return deleted, skipped, failed


def read_export(path: str, bot_id: int) -> tuple[int, str, list]:
    # Telegram Desktop export: Chat → ⋮ → Export chat history, format JSON
    with open(path, encoding='utf-8') as file:
        export = json.load(file)
    chat_type = export.get('type', '')
    chat_id = int(f'-100{export["id"]}') if 'supergroup' in chat_type or 'channel' in chat_type else -int(export['id'])
    found = []
    for message in export.get('messages', []):
        if message.get('type') != 'message' or message.get('from_id') != f'user{bot_id}':
            continue
        if 'text_entities' in message:
            text = ''.join(entity.get('text', '') for entity in message['text_entities'])
        elif isinstance(message.get('text'), list):
            text = ''.join(part if isinstance(part, str) else part.get('text', '') for part in message['text'])
        else:
            text = message.get('text') or ''
        if text.startswith(ALERT_TITLE) and NO_ATTACKS_MARK in text:
            found.append((message['id'], message.get('date', '').replace('T', ' ')[:16], end_line(text)))
    return chat_id, export.get('name', ''), found


async def delete_saved(path: str, bot_number_filter) -> None:
    saved = load_saved_ids(path)
    if not saved:
        print(f'No saved ids in {path}, run the dry run or --export first')
        return
    remaining = dict(saved)
    total_deleted, total_skipped, total_failed = 0, 0, 0
    for key, message_ids in sorted(saved.items()):
        bot_number, chat_id = map(int, key.split('|'))
        if bot_number_filter is not None and bot_number != bot_number_filter:
            continue
        async with bot_client(bot_number) as app:
            me = await app.get_me()
            print(f'━━ Bot {bot_number} @{me.username} · chat {chat_id}: {len(message_ids)} saved messages')
            deleted, skipped, failed = await delete_alerts(app, chat_id, message_ids, me.id)
        print(f'   🗑 deleted {len(deleted)}, skipped {len(skipped)} (not an empty raid alert or already deleted), failed {len(failed)}')
        for message_id, error in failed[:10]:
            print(f'      #{message_id}: {error}')
        remaining[key] = [message_id for message_id, _ in failed]
        if not remaining[key]:
            del remaining[key]
        total_deleted, total_skipped, total_failed = total_deleted + len(deleted), total_skipped + len(skipped), total_failed + len(failed)
        print()
    with open(path, 'w', encoding='utf-8') as file:
        json.dump(remaining, file)
    print(f'━━ Summary: deleted {total_deleted}, skipped {total_skipped}, failed {total_failed}')
    if total_failed:
        print('   Bots can delete their own messages older than 48 hours only as admins with "delete messages" right.')
        print('   Failed ids stay in the file, run --delete_saved again after giving the right')


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
        self.batches = {}
        self.requests = 0

    async def batch(self, batch_start: int) -> list:
        # Existing messages with ids batch_start..batch_start + 199 (deleted messages leave gaps), cached
        if batch_start not in self.batches:
            self.requests += 1
            messages = await call_with_flood_wait(
                self.app.get_messages, self.chat_id, list(range(batch_start, batch_start + BATCH_SIZE))
            )
            self.batches[batch_start] = [message for message in messages if not message.empty]
        return self.batches[batch_start]

    async def find_upper_bound(self) -> int:
        # Galloping: batches at 1, 201, 401, 801, 1601, ... until several probes in a row are empty,
        # so the size of the chat is known after a few requests instead of guessing a huge bound
        batch_start, step, empty_probes, upper_bound = 1, BATCH_SIZE, 0, BATCH_SIZE
        while empty_probes < 3:
            if await self.batch(batch_start):
                empty_probes = 0
                upper_bound = batch_start + 2 * step
            else:
                empty_probes += 1
            batch_start += step
            step *= 2
        return upper_bound

    async def first_id_after(self, moment: float, low: int, high: int) -> int:
        # Binary search over batches: the first batch that contains a message sent at or after the moment
        while high - low > BATCH_SIZE:
            middle = (low + high) // 2
            messages = await self.batch((middle // BATCH_SIZE) * BATCH_SIZE + 1)
            if messages and to_timestamp(messages[0].date) < moment:
                low = middle
            else:
                high = middle
        return low

    async def read_forward(self, start_id: int, bot_id: int, moment_to: float = math.inf) -> list:
        # Reads forward until a message newer than the moment, or until the end of the chat
        found = []
        batch_start = max(((start_id - BATCH_SIZE) // BATCH_SIZE) * BATCH_SIZE + 1, 1)
        empty_batches = 0
        while empty_batches < EMPTY_BATCHES_AT_THE_END:
            existing = await self.batch(batch_start)
            found += [message for message in existing if is_empty_raid_alert(message, bot_id, self.chat_id)]
            if existing and to_timestamp(existing[-1].date) > moment_to:
                break
            empty_batches = 0 if existing else empty_batches + 1
            batch_start += BATCH_SIZE
        return found


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--delete', action='store_true')
    parser.add_argument('--delete_saved', action='store_true')
    parser.add_argument('--export')
    parser.add_argument('--chat_id', type=int)
    parser.add_argument('--bot_number', type=int)
    parser.add_argument('--ids_file', default=DEFAULT_IDS_FILE)
    args = parser.parse_args()
    clan_tags = [clan_tag.get_secret_value() for clan_tag in config.clan_tags]

    if args.delete_saved:
        await delete_saved(args.ids_file, args.bot_number)
        return
    if args.export:
        if args.bot_number is None:
            print('--export needs --bot_number of the bot whose messages are in the chat')
            return
        bot_id = int(config.telegram_bot_api_tokens[args.bot_number].get_secret_value().split(':')[0])
        chat_id, chat_name, found = read_export(args.export, bot_id)
        chat_id = args.chat_id or chat_id
        print(f'Chat «{chat_name}» ({chat_id}), bot {args.bot_number}: {len(found)} empty raid alerts in the export')
        for message_id, date, line in found:
            print(f'      ✓  #{message_id:<8} {date}  {line}')
        save_ids(args.ids_file, args.bot_number, chat_id, [message_id for message_id, _, _ in found])
        print(f'\nSaved to {args.ids_file}. Delete everything saved with --delete_saved')
        return

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
        async with bot_client(bot_number) as app:
            me = await app.get_me()
            print(f'━━ Bot {bot_number} @{me.username} · clan {clan_names.get(clan_tag, "?")} ({clan_tag})')
            for (alert_clan_tag, chat_id), moments in sorted(alerts.items()):
                if alert_clan_tag != clan_tag:
                    continue
                print(f'   Chat «{chat_titles.get((clan_tag, chat_id), chat_id)}» ({chat_id}): {len(moments)} alerts in the log')
                scanner = ChatScanner(app, chat_id)
                margin = SEARCH_MARGIN.total_seconds()
                moments_utc = [moment.replace(tzinfo=UTC).timestamp() for moment in moments]
                try:
                    upper_bound = await scanner.find_upper_bound()
                    batch_count = upper_bound // BATCH_SIZE + 1
                    # A small chat is cheaper to read whole than to search every alert in it
                    if batch_count <= len(moments) * math.ceil(math.log2(batch_count + 1)):
                        print(f'   reading the whole chat (about {batch_count * BATCH_SIZE} message ids)...')
                        found_messages = await scanner.read_forward(1, me.id)
                    else:
                        print(f'   searching {len(moments)} alerts among about {batch_count * BATCH_SIZE} message ids...')
                        found_messages, low = [], 1
                        for moment_utc in moments_utc:
                            start_id = await scanner.first_id_after(moment_utc - margin, low, upper_bound)
                            found_messages += await scanner.read_forward(start_id, me.id, moment_utc + margin)
                            low = max(low, start_id - BATCH_SIZE)
                    found = {message.id: message for message in found_messages}
                    missing = [
                        moment.replace(tzinfo=UTC).astimezone().replace(tzinfo=None)
                        for moment, moment_utc in zip(moments, moments_utc)
                        if not any(abs(to_timestamp(message.date) - moment_utc) <= margin for message in found.values())
                    ]
                except Exception as e:
                    # One broken chat must not stop the others
                    print(f'   ⚠️  chat skipped: {getattr(e, "ID", None) or repr(e)}\n')
                    continue
                lines = [(moment, f'      ·  {"—":<9} {moment:%d.%m.%Y %H:%M}  not found in the chat (already deleted?)') for moment in missing]
                for message in found.values():
                    mark = '🗑' if args.delete else '✓'
                    lines.append((message.date, f'      {mark}  #{message.id:<8} {message.date:%d.%m.%Y %H:%M}  {end_line(message.text)}'))
                for _, line in sorted(lines):
                    print(line)
                print(f'   → {len(found)} to delete, {len(missing)} not found ({scanner.requests} requests to Telegram)')
                total_found += len(found)
                total_missing += len(missing)
                if args.delete and found:
                    deleted, _, chat_failed = await delete_alerts(app, chat_id, sorted(found), me.id)
                    total_deleted += len(deleted)
                    failed += [(chat_id, message_id, error) for message_id, error in chat_failed]
                elif found:
                    save_ids(args.ids_file, bot_number, chat_id, list(found))
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
        print(f'   Found ids are saved to {args.ids_file}, delete them with --delete_saved (no second search needed)')


if __name__ == '__main__':
    asyncio.run(main())
