import asyncio
import logging

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import config
from bot.middlewares import CallbackQueryMiddleware, MessageMiddleware
from bot.commands import commands
from database_manager import DatabaseManager
from routers import admin, cw, cwl, members, raids


async def main():
    logging.basicConfig(level=logging.INFO,
                        format='%(filename)s:%(lineno)d #%(levelname)s [%(asctime)s] - %(name)s - %(message)s')
    bot = Bot(token=config.telegram_bot_api_token.get_secret_value())
    dm = DatabaseManager()
    await dm.establish_connections()
    await dm.update_all_data()
    dp = Dispatcher(dm=dm)
    dp.message.middleware(MessageMiddleware())
    dp.callback_query.middleware(CallbackQueryMiddleware())
    dp.include_routers(cw.router, raids.router, cwl.router, members.router, admin.router)
    scheduler = AsyncIOScheduler()
    scheduler.add_job(dm.update_all_data, 'interval', seconds=60)
    scheduler.start()
    await commands.set_cwl_commands(bot)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info('KeyboardInterrupt')
    except SystemExit:
        logging.info('SystemExit')
