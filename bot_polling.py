import argparse
import asyncio
import logging

from aiogram import Bot, Dispatcher

from bot.middlewares import MessageMiddleware, CallbackQueryMiddleware
from config import config
from database_manager import DatabaseManager
from routers import admin, cw, cwl, members, raids


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bot_number")
    args = parser.parse_args()
    bot_number = int(args.bot_number)

    logging.basicConfig(
        level=logging.INFO,
        format='%(filename)s:%(lineno)d #%(levelname)s [%(asctime)s] - %(name)s - %(message)s',
        handlers=[
            logging.FileHandler(f'bot_polling ({bot_number}).log', 'w'),
            logging.StreamHandler()
        ]
    )

    bot = Bot(token=config.telegram_bot_api_tokens[bot_number].get_secret_value())

    dm = DatabaseManager(clan_tag=config.clan_tags[bot_number].get_secret_value(), bot=bot)
    await dm.connect_to_pool()
    await dm.frequent_jobs()
    await dm.infrequent_jobs()

    dp = Dispatcher(dm=dm)
    dp.message.outer_middleware(MessageMiddleware())
    dp.callback_query.outer_middleware(CallbackQueryMiddleware())
    dp.include_routers(cw.router, raids.router, cwl.router, members.router, admin.router)

    await dm.start_scheduler(bot_number)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info('KeyboardInterrupt')
    except SystemExit:
        logging.info('SystemExit')
