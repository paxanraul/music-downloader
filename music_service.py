import asyncio
import logging
import re
import tempfile
import time
from pathlib import Path
from typing import Optional

import requests
from requests.exceptions import ChunkedEncodingError, ConnectionError, Timeout
from yandex_music import Client
from yandex_music.exceptions import NetworkError, TimedOutError

from models import DownloadedTrack

logger = logging.getLogger(__name__)

TRACK_URL_RE = re.compile(
    r"(?:https?://)?(?:music\.)?yandex\.(?:ru|com)/(?:album/\d+/track/|track/)(\d+)"
)


class YandexMusicService:
    def __init__(self, token: str) -> None:
        self.token = token
        self.client: Optional[Client] = None
        self.lock = asyncio.Lock()

    async def init(self, force: bool = False) -> None:
        async with self.lock:
            if self.client is None or force:
                self.client = await asyncio.to_thread(Client(self.token).init)

    @staticmethod
    def is_track_url(url: str) -> bool:
        return bool(TRACK_URL_RE.search(url))

    @staticmethod
    def _extract_track_id(url: str) -> Optional[str]:
        match = TRACK_URL_RE.search(url)
        return match.group(1) if match else None

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        if isinstance(exc, (NetworkError, TimedOutError, ChunkedEncodingError, ConnectionError, Timeout)):
            return True
        text = str(exc).lower()
        markers = (
            "server disconnected",
            "serverdisconnectederror",
            "connection reset",
            "timed out",
            "connection broken",
            "temporarily unavailable",
        )
        return any(marker in text for marker in markers)

    async def _run_with_retries(self, operation_name: str, func, *args):
        max_attempts = 4
        for attempt in range(1, max_attempts + 1):
            try:
                return await asyncio.to_thread(func, *args)
            except Exception as exc:
                if not self._is_retryable_error(exc) or attempt == max_attempts:
                    raise
                logger.warning(
                    "Retrying '%s' after error (%s/%s): %s",
                    operation_name,
                    attempt,
                    max_attempts,
                    exc,
                )
                await self.init(force=True)
                await asyncio.sleep(1.2 * attempt)

    async def download_track_from_url(self, url: str) -> DownloadedTrack:
        if self.client is None:
            raise RuntimeError("Yandex client is not initialized")

        track_id = self._extract_track_id(url)
        if not track_id:
            raise ValueError("Не удалось определить track_id из ссылки.")

        track = await self._run_with_retries("get_track", self._get_track, track_id)
        if track is None:
            raise ValueError("Трек не найден.")

        download_url = await self._run_with_retries("get_download_url", self._get_best_download_url, track)
        if not download_url:
            raise ValueError("Не удалось получить ссылку на скачивание (нужен валидный токен Яндекс Музыки).")

        tmp_dir = Path(tempfile.gettempdir())
        safe_title = re.sub(r"[^\w\s.-]", "_", track.title).strip() or f"track_{track.id}"
        file_path = tmp_dir / f"{safe_title}_{track.id}"

        await asyncio.to_thread(self._download_file, download_url, file_path)

        artist = ", ".join(a.name for a in (track.artists or [])) or "Unknown artist"
        return DownloadedTrack(file_path=file_path, title=track.title, artist=artist)

    def _get_track(self, track_id: str):
        tracks = self.client.tracks([track_id])
        return tracks[0] if tracks else None

    @staticmethod
    def _get_best_download_url(track) -> Optional[str]:
        infos = track.get_download_info(get_direct_links=False)
        mp3_infos = [i for i in infos if i.codec == "mp3"]
        if not mp3_infos:
            return None
        best = max(mp3_infos, key=lambda i: i.bitrate_in_kbps or 0)
        return best.get_direct_link()

    @staticmethod
    def _download_file(url: str, destination: Path) -> None:
        max_attempts = 4
        backoff_seconds = 1.5

        for attempt in range(1, max_attempts + 1):
            try:
                with requests.get(
                    url,
                    stream=True,
                    timeout=(10, 120),
                    headers={"User-Agent": "Mozilla/5.0"},
                ) as resp:
                    resp.raise_for_status()
                    with destination.open("wb") as file_obj:
                        for chunk in resp.iter_content(chunk_size=1024 * 128):
                            if chunk:
                                file_obj.write(chunk)
                return
            except (ChunkedEncodingError, ConnectionError, Timeout) as exc:
                if destination.exists():
                    destination.unlink(missing_ok=True)
                if attempt == max_attempts:
                    raise RuntimeError("Сеть нестабильна: не удалось скачать трек после нескольких попыток.") from exc
                sleep_for = backoff_seconds * attempt
                logger.warning("Download attempt %s/%s failed: %s", attempt, max_attempts, exc)
                time.sleep(sleep_for)
