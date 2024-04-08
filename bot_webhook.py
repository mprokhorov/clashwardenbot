import argparse
import logging

from aiogram import Dispatcher, Router, Bot
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp.web import run_app
from aiohttp.web_app import Application

from bot.middlewares import MessageMiddleware, CallbackQueryMiddleware
from config import config
from database_manager import DatabaseManager
from routers import admin, cw, cwl, members, raids

WEBHOOK_HOST = config.webhook_host.get_secret_value()
WEBHOOK_PATH = config.webhook_path.get_secret_value()
WEBHOOK_URL = f'{WEBHOOK_HOST}{WEBHOOK_PATH}'

WEBAPP_HOST = config.webapp_host.get_secret_value()
WEBAPP_PORT = config.webapp_port.get_secret_value()

router = Router()


@router.startup()
async def on_startup(bot: Bot, webhook_url: str, dm: DatabaseManager, bot_number: int):
    await bot.set_webhook(webhook_url)

    await dm.connect_to_pool()
    await dm.infrequent_jobs()

    await dm.start_scheduler(bot_number)


@router.shutdown()
async def on_shutdown(bot: Bot):
    await bot.delete_webhook()


def main():
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

    dispatcher = Dispatcher()
    dispatcher['webhook_url'] = WEBHOOK_URL
    dispatcher['dm'] = dm
    dispatcher['bot_number'] = bot_number
    dispatcher.message.outer_middleware(MessageMiddleware())
    dispatcher.callback_query.outer_middleware(CallbackQueryMiddleware())
    dispatcher.include_routers(router, cw.router, raids.router, cwl.router, members.router, admin.router)

    app = Application()
    SimpleRequestHandler(dispatcher=dispatcher, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dispatcher, bot=bot)
    run_app(app, host=WEBAPP_HOST, port=int(WEBAPP_PORT))


if __name__ == '__main__':
    main()
