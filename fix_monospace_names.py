"""
Одноразовый скрипт: редактирует залогированные сообщения бота, заменяя
вхождения указанного никнейма на его моноширинную версию (<code>...</code>).

Использование:
  python3.12 fix_monospace_names.py --bot_number 0 --name "ard.man"
  python3.12 fix_monospace_names.py --bot_number 0 --name "ard.man" --all
"""

import argparse
import asyncio
import logging

import asyncpg
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from config import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')


async def run(bot_number: int, target_name: str, edit_all: bool) -> None:
    clan_tag = config.clan_tags[bot_number].get_secret_value()
    pool = await asyncpg.create_pool(
        host=config.postgres_host.get_secret_value(),
        database=config.postgres_database.get_secret_value(),
        user=config.postgres_user.get_secret_value(),
        password=config.postgres_password.get_secret_value(),
    )

    rows = await pool.fetch('''
        SELECT chat_id, message_id, html_text
        FROM bot_message_log
        WHERE clan_tag = $1 AND html_text LIKE $2
        ORDER BY message_id DESC
    ''', clan_tag, f'%{target_name}%')

    if not rows:
        logging.info('Залогированных сообщений с таким именем не найдено.')
        await pool.close()
        return

    logging.info(f'Найдено сообщений: {len(rows)}')
    to_process = rows if edit_all else [rows[0]]
    logging.info(f'Будет обработано: {len(to_process)}')

    monospace_name = f'<code>{target_name}</code>'

    session = AiohttpSession()
    bot = Bot(token=config.telegram_bot_api_tokens[bot_number].get_secret_value(), session=session)

    for i, row in enumerate(to_process):
        old_text = row['html_text']
        if monospace_name in old_text:
            logging.info(f'[{i+1}/{len(to_process)}] message_id={row["message_id"]} уже содержит <code>, пропуск')
            continue
        new_text = old_text.replace(target_name, monospace_name)
        try:
            await bot.edit_message_text(
                chat_id=row['chat_id'],
                message_id=row['message_id'],
                text=new_text,
                parse_mode=ParseMode.HTML,
            )
            await pool.execute('''
                UPDATE bot_message_log SET html_text = $1
                WHERE clan_tag = $2 AND chat_id = $3 AND message_id = $4
            ''', new_text, clan_tag, row['chat_id'], row['message_id'])
            logging.info(f'[{i+1}/{len(to_process)}] Отредактировано message_id={row["message_id"]} '
                         f'в чате {row["chat_id"]}')
        except Exception as e:
            logging.warning(f'[{i+1}/{len(to_process)}] Ошибка для message_id={row["message_id"]}: {e}')
        await asyncio.sleep(0.5)

    await session.close()
    await pool.close()
    logging.info('Готово.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Заменить имя игрока на моноширинное в залогированных сообщениях')
    parser.add_argument('--bot_number', type=int, required=True, help='Номер бота (0, 1, ...)')
    parser.add_argument('--name', type=str, required=True, help='Никнейм для замены (например: ard.man)')
    parser.add_argument('--all', dest='edit_all', action='store_true',
                        help='Редактировать все найденные сообщения (по умолчанию — только самое новое)')
    args = parser.parse_args()
    asyncio.run(run(args.bot_number, args.name, args.edit_all))
