import asyncio
import logging
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from .config import ADMIN_IDS
from .models import DownloadedTrack
from .music_service import YandexMusicService
from .stats_store import StatsStore

logger = logging.getLogger(__name__)

router = Router()


async def start_command(message: Message, stats_store: StatsStore) -> None:
    if message.from_user:
        await stats_store.register_user(
            user_id=message.from_user.id,
            name=message.from_user.full_name or "Unknown",
            username=message.from_user.username or "",
        )
    text = (
        '<tg-emoji emoji-id="5402356576696688014">👋</tg-emoji> '
        "Привет! Отправь ссылку на трек из Яндекс Музыки и я скину тебе его файлом."
    )
    await message.answer(text, parse_mode="HTML")


async def stats_command(message: Message, stats_store: StatsStore) -> None:
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        await message.answer("Эта команда доступна только админам.")
        return

    snapshot = stats_store.snapshot()
    users = snapshot["users"]
    users_lines = []
    for user in users:
        username = f"@{user['username']}" if user["username"] else "-"
        users_lines.append(f"{user['id']} | {user['name']} | {username}")
    users_block = "\n".join(users_lines) if users_lines else "Пока пусто."

    text = (
        "Статистика:\n"
        f"Всего запросов: {snapshot['total_requests']}\n"
        f"Успешных скачиваний: {snapshot['successful_downloads']}\n"
        f"Ошибок: {snapshot['failed_downloads']}\n"
        f"Уникальных пользователей: {snapshot['unique_users_count']}\n\n"
        "Список пользователей (id | name | username):\n"
        f"{users_block}"
    )
    await message.answer(text)


async def broadcast_command(message: Message, stats_store: StatsStore, bot: Bot) -> None:
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        await message.answer("Эта команда доступна только админам.")
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer("Использование: /broadcast Текст сообщения")
        return

    broadcast_text = parts[1].strip()
    users = stats_store.snapshot()["users"]
    sent_count = 0
    failed_count = 0

    for user in users:
        user_id = user["id"]
        try:
            await bot.send_message(chat_id=user_id, text=broadcast_text)
            sent_count += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(float(exc.retry_after) + 0.5)
            try:
                await bot.send_message(chat_id=user_id, text=broadcast_text)
                sent_count += 1
            except Exception:
                failed_count += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            failed_count += 1
        except Exception:
            failed_count += 1

    await message.answer(
        f"Рассылка завершена.\nОтправлено: {sent_count}\nОшибок: {failed_count}\nВсего в базе: {len(users)}"
    )


async def handle_text(message: Message, stats_store: StatsStore, music_service: YandexMusicService) -> None:
    if not message.text or not message.from_user:
        return

    url = message.text.strip()
    if not music_service.is_track_url(url):
        await message.answer("Пришли корректную ссылку на трек из Яндекс Музыки.")
        return

    await stats_store.register_request(
        user_id=message.from_user.id,
        name=message.from_user.full_name or "Unknown",
        username=message.from_user.username or "",
    )
    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.UPLOAD_DOCUMENT)

    downloaded_track: Optional[DownloadedTrack] = None
    try:
        downloaded_track = await music_service.download_track_from_url(url)
        caption = f"{downloaded_track.artist} - {downloaded_track.title}"
        audio = FSInputFile(path=str(downloaded_track.file_path), filename=downloaded_track.title)
        await message.answer_audio(
            audio=audio,
            title=downloaded_track.title,
            performer=downloaded_track.artist,
            caption=caption,
        )
        await stats_store.register_success()
    except Exception as exc:
        logger.exception("Download failed")
        await stats_store.register_failure()
        await message.answer(f"Ошибка при скачивании: {exc}")
    finally:
        if downloaded_track and downloaded_track.file_path.exists():
            try:
                downloaded_track.file_path.unlink()
            except OSError:
                logger.warning("Could not remove temporary file: %s", downloaded_track.file_path)


def setup_handlers() -> Router:
    router.message.register(start_command, Command("start"))
    router.message.register(stats_command, Command("stats"))
    router.message.register(broadcast_command, Command("broadcast"))
    router.message.register(handle_text, F.text)
    return router
