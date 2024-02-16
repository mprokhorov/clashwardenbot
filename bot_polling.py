import argparse
import asyncio
import logging

from aiogram import Bot, Dispatcher
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import config
from bot.middlewares import MessageMiddleware
from bot import commands
from database_manager import DatabaseManager
from routers import admin, cw, cwl, members, raids


async def main():
    logging.basicConfig(level=logging.INFO,
                        format='%(filename)s:%(lineno)d #%(levelname)s [%(asctime)s] - %(name)s - %(message)s')
    parser = argparse.ArgumentParser()
    parser.add_argument("--bot_number")
    args = parser.parse_args()
    bot_number = int(args.bot_number)
    dm = DatabaseManager(clan_tag=config.clan_tags[bot_number].get_secret_value(),
                         telegram_bot_api_token=config.telegram_bot_api_tokens[bot_number].get_secret_value(),
                         telegram_bot_username=config.telegram_bot_usernames[bot_number].get_secret_value())
    await dm.establish_connections()
    await dm.frequent_jobs()
    await dm.infrequent_jobs()

    dp = Dispatcher(dm=dm)
    dp.message.outer_middleware(MessageMiddleware())
    dp.include_routers(cw.router, raids.router, cwl.router, members.router, admin.router)

    scheduler = AsyncIOScheduler()
    job_frequency = 5
    frequent_jobs_minute = ','.join(map(str, [m * job_frequency + bot_number for m in range(1, 60 // job_frequency)]))
    scheduler.add_job(dm.frequent_jobs, 'cron', minute=frequent_jobs_minute)
    infrequent_jobs_minute = str(bot_number)
    scheduler.add_job(dm.infrequent_jobs, 'cron', minute=infrequent_jobs_minute)
    scheduler.start()

    bot = Bot(token=dm.telegram_bot_api_token)
    await commands.set_commands(bot)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info('KeyboardInterrupt')
    except SystemExit:
        logging.info('SystemExit')
