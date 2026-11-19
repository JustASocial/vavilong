"""Мелкие утилиты: размеры, время, временные папки, скачивание по URL."""

from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
import unicodedata
import uuid
from pathlib import Path

import aiohttp

from app.config import settings

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".avif"}
VIDEO_EXT = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".ts"}

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


def human_size(num: float | int | None, lang: str = "ru") -> str:
    if not num:
        return "—"
    num = float(num)
    units = ("Б", "КБ", "МБ", "ГБ") if lang == "ru" else ("B", "KB", "MB", "GB")
    for unit in units:
        if num < 1024 or unit == units[-1]:
            return f"{num:.0f} {unit}" if unit == units[0] else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} {units[-1]}"


def human_duration(seconds: float | int | None) -> str:
    if not seconds:
        return "—"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def short(text: str | None, limit: int = 120) -> str:
    if not text:
        return ""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def safe_filename(name: str, fallback: str = "file") -> str:
    name = unicodedata.normalize("NFKD", name or "")
    name = re.sub(r"[^\w\s.\-()\[\]]", "", name, flags=re.UNICODE).strip()
    name = re.sub(r"\s+", " ", name)
    if not name:
        name = fallback
    return name[:80]


def pick_url(text: str | None) -> str | None:
    if not text:
        return None
    match = URL_RE.search(text)
    return match.group(0).rstrip(").,!?;»\"'") if match else None


def temp_dir() -> Path:
    """Отдельная папка под одну задачу — потом удаляем целиком."""
    path = settings.temp_dir / uuid.uuid4().hex[:12]
    path.mkdir(parents=True, exist_ok=True)
    return path


def cleanup_dir(path: Path | None) -> None:
    if not path:
        return
    shutil.rmtree(path, ignore_errors=True)


def find_file(folder: Path, prefer_largest: bool = True) -> Path | None:
    files = [p for p in folder.rglob("*") if p.is_file() and not p.name.endswith((".part", ".ytdl"))]
    if not files:
        return None
    if prefer_largest:
        return max(files, key=lambda p: p.stat().st_size)
    return files[0]


async def download_url(url: str, dest: Path, timeout: int = 45, max_bytes: int | None = None) -> Path:
    headers = {"User-Agent": UA, "Accept": "*/*"}
    dest.parent.mkdir(parents=True, exist_ok=True)
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            resp.raise_for_status()
            total = 0
            with dest.open("wb") as fh:
                async for chunk in resp.content.iter_chunked(256 * 1024):
                    total += len(chunk)
                    if max_bytes and total > max_bytes:
                        raise ValueError("файл больше допустимого размера")
                    fh.write(chunk)
    return dest


async def run_blocking(func, *args, **kwargs):
    """Выполнить синхронную (CPU/Pillow/OpenCV) функцию в пуле потоков."""
    return await asyncio.to_thread(func, *args, **kwargs)


async def cleanup_temp_dir(path: Path | None, delay: float = 0) -> None:
    if delay:
        await asyncio.sleep(delay)
    cleanup_dir(path)
