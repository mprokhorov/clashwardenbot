import argparse
import logging

from aiogram import Dispatcher, Router, Bot
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp.web import run_app
from aiohttp.web_app import Application
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import config
from bot.middlewares import MessageMiddleware
from bot import commands
from database_manager import DatabaseManager
from routers import admin, cw, cwl, members, raids

WEBHOOK_HOST = config.webhook_host.get_secret_value()
WEBHOOK_PATH = config.webhook_path.get_secret_value()
WEBHOOK_URL = f'{WEBHOOK_HOST}{WEBHOOK_PATH}'

WEBAPP_HOST = config.webapp_host.get_secret_value()
WEBAPP_PORT = config.webapp_port.get_secret_value()

router = Router()


@router.startup()
async def on_startup(bot: Bot, webhook_url: str, dm: DatabaseManager):
    await bot.set_webhook(webhook_url)

    await dm.establish_connections()
    await dm.frequent_jobs()
    await dm.infrequent_jobs()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(dm.frequent_jobs, 'cron', minute='5,10,15,20,25,30,35,40,45,50,55')
    scheduler.add_job(dm.infrequent_jobs, 'cron', minute='0')
    scheduler.start()

    await commands.set_cwl_commands(bot)


@router.shutdown()
async def on_shutdown(bot: Bot):
    await bot.delete_webhook()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bot_number")
    args = parser.parse_args()
    bot_number = int(args.bot_number)
    dm = DatabaseManager(clan_tag=config.clan_tags[bot_number].get_secret_value(),
                         telegram_bot_api_token=config.telegram_bot_api_tokens[bot_number].get_secret_value(),
                         telegram_bot_username=config.telegram_bot_usernames[bot_number].get_secret_value())

    bot = Bot(token=dm.telegram_bot_api_token)
    dispatcher = Dispatcher()
    dispatcher['webhook_url'] = WEBHOOK_URL
    dispatcher['dm'] = dm
    dispatcher.message.middleware(MessageMiddleware())
    dispatcher.include_routers(router, cw.router, raids.router, cwl.router, members.router, admin.router)

    app = Application()
    SimpleRequestHandler(dispatcher=dispatcher, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dispatcher, bot=bot)
    run_app(app, host=WEBAPP_HOST, port=int(WEBAPP_PORT))


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO,
                        format='%(filename)s:%(lineno)d #%(levelname)s [%(asctime)s] - %(name)s - %(message)s')
    main()
