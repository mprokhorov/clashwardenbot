import argparse
import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler

# Parse bot_number early so the log file is open before any other imports.
# This ensures import errors are also captured in the log file.
_pre = argparse.ArgumentParser(add_help=False)
_pre.add_argument('--bot_number', type=int, default=0)
_bot_number = _pre.parse_known_args()[0].bot_number

logging.basicConfig(
    level=logging.INFO,
    format='%(filename)s:%(lineno)d #%(levelname)s [%(asctime)s] - %(name)s - %(message)s',
    handlers=[
        RotatingFileHandler(f'bot_polling_{_bot_number}.log', maxBytes=8 * 1024 * 1024, backupCount=1),
        logging.StreamHandler(),
    ]
)


def _excepthook(exc_type, exc_value, exc_tb):
    logging.critical('Unhandled exception', exc_info=(exc_type, exc_value, exc_tb))
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _excepthook


from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

from bot.middlewares import MessageMiddleware, CallbackQueryMiddleware
from bot.session_middleware import MessageLoggingMiddleware
from config import config
from database_manager import DatabaseManager
from routers import admin, cw, cwl, miscellaneous, player_rating, player_rating_giveaway, raids


async def main() -> None:
    session = AiohttpSession()
    bot = Bot(token=config.telegram_bot_api_tokens[_bot_number].get_secret_value(), session=session)

    dm = DatabaseManager(clan_tag=config.clan_tags[_bot_number].get_secret_value(), bot=bot)
    session.middleware(MessageLoggingMiddleware(dm))
    await dm.connect_to_pool()
    await dm.infrequent_jobs()

    dp = Dispatcher(dm=dm)
    dp.message.outer_middleware(MessageMiddleware())
    dp.callback_query.outer_middleware(CallbackQueryMiddleware())
    dp.include_routers(
        cw.router, raids.router, cwl.router, player_rating.router, player_rating_giveaway.router,
        miscellaneous.router, admin.router
    )

    await dm.start_scheduler(_bot_number)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info('KeyboardInterrupt')
    except SystemExit:
        logging.info('SystemExit')
    except Exception:
        logging.exception('Unhandled exception')
        sys.exit(1)
