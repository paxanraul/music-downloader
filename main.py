import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher

from config import ADMIN_IDS, TELEGRAM_BOT_TOKEN, YANDEX_MUSIC_TOKEN
from handlers import setup_handlers
from music_service import YandexMusicService
from stats_store import StatsStore

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

STATS_FILE = Path("stats.json")


async def on_startup(bot: Bot) -> None:
    _ = bot
    logger.info("Bot started")


def validate_env() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable")
    if not YANDEX_MUSIC_TOKEN:
        raise RuntimeError("Missing YANDEX_MUSIC_TOKEN environment variable")
    if not ADMIN_IDS:
        logger.warning("ADMIN_IDS is empty, admin commands will be unavailable")


async def main() -> None:
    validate_env()

    stats_store = StatsStore(STATS_FILE)
    await stats_store.load()

    music_service = YandexMusicService(YANDEX_MUSIC_TOKEN)
    await music_service.init()

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    dp = Dispatcher()
    dp.startup.register(on_startup)
    dp.include_router(setup_handlers())

    await dp.start_polling(bot, stats_store=stats_store, music_service=music_service)


if __name__ == "__main__":
    asyncio.run(main())
