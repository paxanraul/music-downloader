import logging
import os
from typing import Set

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def parse_admin_ids(raw_value: str) -> Set[int]:
    result: Set[int] = set()
    for item in raw_value.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            result.add(int(value))
        except ValueError:
            logger.warning("Skipping invalid ADMIN_IDS value: %s", value)
    return result


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
YANDEX_MUSIC_TOKEN = os.getenv("YANDEX_MUSIC_TOKEN")
ADMIN_IDS = parse_admin_ids(os.getenv("ADMIN_IDS", ""))
