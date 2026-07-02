"""
Импортирует сообщения бота из JSON-экспорта Telegram-чата в bot_message_log.
После этого fix_monospace_names.py сможет отредактировать их.

Экспорт делается через Telegram Desktop:
  Чат → ⋮ → Export chat history → Format: JSON

Использование:
  python3.12 import_chat_export.py --bot_number 0 --file result.json
"""

import argparse
import asyncio
import html
import json
import logging

import asyncpg
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

from config import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')


def export_chat_id_to_bot_api(export_id: int, chat_type: str) -> int:
    """Конвертирует chat id из экспорта в Bot API формат."""
    if 'supergroup' in chat_type or 'channel' in chat_type:
        return int(f'-100{export_id}')
    if 'group' in chat_type:
        return -export_id
    return export_id


def entities_to_html(text_field) -> str:
    """
    Реконструирует HTML из поля text экспорта.
    text_field — строка или список (строки и объекты с type/text).
    """
    if isinstance(text_field, str):
        return html.escape(text_field)

    parts = []
    for item in text_field:
        if isinstance(item, str):
            parts.append(html.escape(item))
            continue
        entity_type = item.get('type', '')
        entity_text = html.escape(item.get('text', ''))
        if entity_type == 'bold':
            parts.append(f'<b>{entity_text}</b>')
        elif entity_type == 'italic':
            parts.append(f'<i>{entity_text}</i>')
        elif entity_type == 'underline':
            parts.append(f'<u>{entity_text}</u>')
        elif entity_type == 'strikethrough':
            parts.append(f'<s>{entity_text}</s>')
        elif entity_type == 'code':
            parts.append(f'<code>{entity_text}</code>')
        elif entity_type == 'pre':
            parts.append(f'<pre>{entity_text}</pre>')
        elif entity_type == 'spoiler':
            parts.append(f'<tg-spoiler>{entity_text}</tg-spoiler>')
        elif entity_type == 'text_link':
            href = html.escape(item.get('href', ''), quote=True)
            parts.append(f'<a href="{href}">{entity_text}</a>')
        elif entity_type == 'mention_name':
            user_id = item.get('user_id', '')
            parts.append(f'<a href="tg://user?id={user_id}">{entity_text}</a>')
        else:
            parts.append(entity_text)
    return ''.join(parts)


async def run(bot_number: int, export_file: str) -> None:
    clan_tag = config.clan_tags[bot_number].get_secret_value()

    session = AiohttpSession()
    bot = Bot(token=config.telegram_bot_api_tokens[bot_number].get_secret_value(), session=session)
    bot_info = await bot.get_me()
    bot_user_id = bot_info.id
    logging.info(f'Бот: @{bot_info.username} (id={bot_user_id})')
    await session.close()

    with open(export_file, encoding='utf-8') as f:
        export = json.load(f)

    chat_type = export.get('type', '')
    export_chat_id = export.get('id', 0)
    chat_id = export_chat_id_to_bot_api(export_chat_id, chat_type)
    logging.info(f'Чат из экспорта: id={export_chat_id}, type="{chat_type}" → Bot API chat_id={chat_id}')

    messages = export.get('messages', [])
    bot_from_id = f'user{bot_user_id}'

    pool = await asyncpg.create_pool(
        host=config.postgres_host.get_secret_value(),
        database=config.postgres_database.get_secret_value(),
        user=config.postgres_user.get_secret_value(),
        password=config.postgres_password.get_secret_value(),
    )

    inserted = 0
    skipped = 0
    for msg in messages:
        if msg.get('type') != 'message':
            continue
        if msg.get('from_id') != bot_from_id:
            continue
        text_field = msg.get('text')
        if not text_field:
            continue
        html_text = entities_to_html(text_field)
        if not html_text.strip():
            continue
        message_id = int(msg['id'])
        try:
            await pool.execute('''
                INSERT INTO bot_message_log (clan_tag, chat_id, message_id, html_text)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (clan_tag, chat_id, message_id)
                DO UPDATE SET html_text = EXCLUDED.html_text
            ''', clan_tag, chat_id, message_id, html_text)
            inserted += 1
        except Exception as e:
            logging.warning(f'Ошибка при вставке message_id={message_id}: {e}')
            skipped += 1

    await pool.close()
    logging.info(f'Готово. Вставлено/обновлено: {inserted}, пропущено с ошибкой: {skipped}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Импорт сообщений бота из JSON-экспорта чата')
    parser.add_argument('--bot_number', type=int, required=True, help='Номер бота (0, 1, ...)')
    parser.add_argument('--file', type=str, required=True, help='Путь к result.json из экспорта Telegram')
    args = parser.parse_args()
    asyncio.run(run(args.bot_number, args.file))
