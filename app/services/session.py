"""Короткоживущее состояние: токены кнопок, незавершённые стикеры, лимиты."""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class TTLCache:
    def __init__(self, ttl: float = 3600, limit: int = 4000) -> None:
        self.ttl = ttl
        self.limit = limit
        self._data: dict[str, tuple[float, Any]] = {}

    def put(self, value: Any, ttl: float | None = None) -> str:
        self._gc()
        key = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8]
        self._data[key] = (time.monotonic() + (ttl or self.ttl), value)
        return key

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if not item:
            return None
        expires, value = item
        if expires < time.monotonic():
            self._data.pop(key, None)
            return None
        return value

    def pop(self, key: str) -> Any | None:
        item = self._data.pop(key, None)
        return item[1] if item else None

    def _gc(self) -> None:
        now = time.monotonic()
        expired = [k for k, (exp, _) in self._data.items() if exp < now]
        for key in expired:
            self._data.pop(key, None)
        if len(self._data) > self.limit:
            for key in list(self._data)[: len(self._data) - self.limit]:
                self._data.pop(key, None)


# Токен -> {"url": ..., "title": ..., "options": [...]}
download_tokens = TTLCache(ttl=5400)

# Ожидающие подтверждения стикеры: ключ = (chat_id, user_id)
@dataclass
class StickerJob:
    path: Path
    kind: str                      # static | video
    source: str                    # photo | video | gif | sticker | url | text | frame
    temp_dir: Path | None = None
    start: float = 0.0
    duration: float = 3.0
    emoji: str | None = None
    preview: Path | None = None
    is_frame: bool = False
    raw_path: Path | None = None
    alpha: bool = False
    video_duration: float = 0.0
    focus: tuple[float, float] | None = None

    def cleanup(self) -> None:
        from app.services.utils import cleanup_dir

        if self.temp_dir:
            cleanup_dir(self.temp_dir)


pending_stickers: dict[tuple[int, int], StickerJob] = {}

# Черновики паков: ключ = (chat_id, user_id)
@dataclass
class PackDraft:
    title: str = ""
    kind: str = ""
    emoji_mode: str = "manual"
    crop_mode: str = "crop"
    theme: str = "midnight"


pack_drafts: dict[tuple[int, int], PackDraft] = {}

# Импорт чужого пака
@dataclass
class ImportDraft:
    name: str
    title: str
    kind: str
    total: int
    stickers: list[dict] = field(default_factory=list)


import_drafts: dict[tuple[int, int], ImportDraft] = {}

# Последние скачанные файлы (для «повторить»), ключ (chat,user)
last_download: dict[tuple[int, int], dict] = {}

# Токен -> {"path": Path, "kind": "video"|"image", "temp_dir": Path}
media_tokens = TTLCache(ttl=3600)

# Токен -> отрисованная цитата или текстовый стикер
quote_tokens = TTLCache(ttl=3600)

# Токен -> ссылка из inline-режима (для кнопки «открыть в боте»)
inline_urls = TTLCache(ttl=3600)

# Пользовательские мьютексы, чтобы не запускать два тяжёлых процесса сразу.
_user_locks: dict[int, asyncio.Lock] = {}
_global_sem: asyncio.Semaphore | None = None


def user_lock(user_id: int) -> asyncio.Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]


def global_semaphore(limit: int) -> asyncio.Semaphore:
    global _global_sem
    if _global_sem is None:
        _global_sem = asyncio.Semaphore(limit)
    return _global_sem


# Антифлуд: (user_id, action) -> timestamp
_last_action: dict[tuple[int, str], float] = {}


def throttled(user_id: int, action: str, seconds: float) -> bool:
    key = (user_id, action)
    now = time.monotonic()
    last = _last_action.get(key, 0.0)
    if now - last < seconds:
        return True
    _last_action[key] = now
    return False
