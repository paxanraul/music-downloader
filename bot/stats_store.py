import asyncio
import json
from pathlib import Path


class StatsStore:
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self.lock = asyncio.Lock()
        self._data = {
            "total_requests": 0,
            "successful_downloads": 0,
            "failed_downloads": 0,
            "unique_users": [],
        }

    async def load(self) -> None:
        if not self.file_path.exists():
            await self._write()
            return
        try:
            raw = await asyncio.to_thread(self.file_path.read_text, "utf-8")
            parsed = json.loads(raw)
            self._data.update(parsed)
            self._data["unique_users"] = self._normalize_users(self._data.get("unique_users"))
        except Exception:
            await self._write()

    @staticmethod
    def _normalize_users(raw_users) -> list[dict]:
        if not isinstance(raw_users, list):
            return []
        normalized: list[dict] = []
        for item in raw_users:
            if isinstance(item, int):
                normalized.append(
                    {
                        "id": item,
                        "name": "Unknown",
                        "username": "",
                    }
                )
                continue
            if isinstance(item, dict) and isinstance(item.get("id"), int):
                normalized.append(
                    {
                        "id": item["id"],
                        "name": str(item.get("name") or "Unknown"),
                        "username": str(item.get("username") or ""),
                    }
                )
        return normalized

    async def register_request(self, user_id: int, name: str, username: str) -> None:
        async with self.lock:
            self._data["total_requests"] += 1
            self._upsert_user(user_id=user_id, name=name, username=username)
            await self._write()

    async def register_user(self, user_id: int, name: str, username: str) -> None:
        async with self.lock:
            self._upsert_user(user_id=user_id, name=name, username=username)
            await self._write()

    def _upsert_user(self, user_id: int, name: str, username: str) -> None:
        users = self._data["unique_users"]
        existing = next((u for u in users if u["id"] == user_id), None)
        if existing:
            existing["name"] = name or existing["name"] or "Unknown"
            existing["username"] = username or existing["username"] or ""
        else:
            users.append(
                {
                    "id": user_id,
                    "name": name or "Unknown",
                    "username": username or "",
                }
            )

    async def register_success(self) -> None:
        async with self.lock:
            self._data["successful_downloads"] += 1
            await self._write()

    async def register_failure(self) -> None:
        async with self.lock:
            self._data["failed_downloads"] += 1
            await self._write()

    def snapshot(self) -> dict:
        users = sorted(self._data["unique_users"], key=lambda u: u["id"])
        return {
            "total_requests": self._data["total_requests"],
            "successful_downloads": self._data["successful_downloads"],
            "failed_downloads": self._data["failed_downloads"],
            "unique_users_count": len(users),
            "users": users,
        }

    async def _write(self) -> None:
        payload = json.dumps(self._data, ensure_ascii=False, indent=2)
        await asyncio.to_thread(self.file_path.write_text, payload, "utf-8")
