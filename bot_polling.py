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

    dm = DatabaseManager()
    await dm.establish_connections()
    await dm.frequent_jobs()
    await dm.infrequent_jobs()

    dp = Dispatcher(dm=dm)
    dp.message.middleware(MessageMiddleware())
    dp.callback_query.middleware(CallbackQueryMiddleware())
    dp.include_routers(cw.router, raids.router, cwl.router, members.router, admin.router)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(dm.frequent_jobs, 'cron', minute='5,10,15,20,25,30,35,40,45,50,55')
    scheduler.add_job(dm.infrequent_jobs, 'cron', minute='0')
    scheduler.start()

    bot = Bot(token=config.telegram_bot_api_token.get_secret_value())
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
