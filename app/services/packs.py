"""Высокоуровневые операции со стикер-паками через Bot API."""

from __future__ import annotations

import io
import json
import re
import secrets
import zipfile
from pathlib import Path
from typing import Any, Iterable

from aiogram import Bot
from aiogram.types import BufferedInputFile, FSInputFile, InputSticker

from app.config import PACK_MAX_STICKERS, STICKER_STATIC_MAX
from app.database import pack_sticker_count, get_pack, add_pack_sticker
from app.services import images, session

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "і": "i", "ї": "yi", "є": "ye", "ґ": "g",
}


class ArchiveError(ValueError):
    """Пакет .tgspack не прошёл проверку."""


def read_archive(data: bytes, limit: int = PACK_MAX_STICKERS) -> tuple[str, list[tuple[bytes, str]]]:
    """Разбирает .tgspack из веб-студии: ZIP с pack.json и WebP-стикерами."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ArchiveError("это не ZIP-архив") from exc

    with archive:
        try:
            raw = archive.read("pack.json")
        except KeyError as exc:
            raise ArchiveError("в архиве нет pack.json") from exc
        if len(raw) > 256 * 1024:
            raise ArchiveError("pack.json слишком большой")
        try:
            manifest = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArchiveError("pack.json повреждён") from exc

        if not isinstance(manifest, dict) or manifest.get("format") != "tgspack":
            raise ArchiveError("неизвестный формат архива")

        title = str(manifest.get("title") or "").strip()[:64] or "Vavilong pack"
        items = manifest.get("stickers")
        if not isinstance(items, list) or not items:
            raise ArchiveError("в паке нет стикеров")
        if len(items) > limit:
            raise ArchiveError(f"стикеров больше {limit}")

        stickers: list[tuple[bytes, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("file") or "")
            if not name.startswith("stickers/") or not name.lower().endswith(".webp"):
                continue
            try:
                info = archive.getinfo(name)
                if info.file_size > STICKER_STATIC_MAX:
                    continue
                payload = archive.read(name)
            except (KeyError, zipfile.BadZipFile):
                continue
            if len(payload) < 17 or payload[:4] != b"RIFF" or payload[8:12] != b"WEBP":
                continue
            emoji_value = str(item.get("emoji") or "🎲").strip()[:8] or "🎲"
            stickers.append((payload, emoji_value))

    if not stickers:
        raise ArchiveError("не нашёл ни одного целого WebP")
    return title, stickers


async def create_pack_from_archive(
    bot: Bot,
    user_id: int,
    title: str,
    stickers: list[tuple[bytes, str]],
    on_progress=None,
) -> dict[str, Any]:
    """Создаёт пак из готовых WebP: первая партия до 50, остальное по одному."""
    from app import database as db

    me = await bot.me()
    name = make_pack_name(title, me.username or "bot")
    pack_title = (title or "Vavilong pack")[:64]

    def payload(item: tuple[bytes, str]) -> InputSticker:
        data, emoji_value = item
        return InputSticker(
            sticker=BufferedInputFile(data, filename="sticker.webp"),
            format="static",
            emoji_list=[emoji_value],
        )

    first = stickers[:50]
    await bot.create_new_sticker_set(
        user_id=user_id,
        name=name,
        title=pack_title,
        stickers=[payload(item) for item in first],
    )
    added = len(first)

    for index, item in enumerate(stickers[50:], start=51):
        await bot.add_sticker_to_set(user_id=user_id, name=name, sticker=payload(item))
        added += 1
        if on_progress and index % 10 == 0:
            try:
                await on_progress(added, len(stickers))
            except Exception:
                pass

    try:
        cover = images.build_pack_cover(pack_title)
        await bot.set_sticker_set_thumbnail(
            name=name,
            user_id=user_id,
            thumbnail=BufferedInputFile(cover, filename="cover.png"),
            format="static",
        )
    except Exception:
        pass

    pack_id = await db.create_pack(user_id, name, pack_title, "static", "manual", "crop")

    try:
        final = await bot.get_sticker_set(name)
        for sticker in final.stickers:
            await db.add_pack_sticker(
                pack_id, sticker.file_id, sticker.file_unique_id, sticker.emoji or "🎲"
            )
    except Exception:
        pass

    return {
        "name": name,
        "pack_id": pack_id,
        "title": pack_title,
        "added": added,
        "total": len(stickers),
    }


def slugify(text: str) -> str:
    text = (text or "").lower()
    text = "".join(TRANSLIT.get(ch, ch) for ch in text)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text[:28] or "pack"


def make_pack_name(title: str, bot_username: str) -> str:
    base = slugify(title)
    token = secrets.token_hex(3)
    suffix = f"_by_{bot_username}"
    name = f"{base}_{token}{suffix}"
    return name[:64]


def pack_link(name: str) -> str:
    return f"https://t.me/addstickers/{name}"


async def create_pack(
    bot: Bot,
    user_id: int,
    name: str,
    title: str,
    kind: str,
    sticker_path: Path,
    emoji: str,
) -> None:
    sticker = InputSticker(
        sticker=FSInputFile(sticker_path),
        format=kind,
        emoji_list=[emoji],
    )
    await bot.create_new_sticker_set(
        user_id=user_id, name=name, title=title, stickers=[sticker]
    )
    try:
        cover = images.build_pack_cover(title)
        await bot.set_sticker_set_thumbnail(
            name=name,
            user_id=user_id,
            thumbnail=BufferedInputFile(cover, filename="cover.png"),
            format="static",
        )
    except Exception:
        pass


async def add_sticker(
    bot: Bot, user_id: int, name: str, kind: str, sticker_path: Path, emoji: str
) -> None:
    sticker = InputSticker(
        sticker=FSInputFile(sticker_path),
        format=kind,
        emoji_list=[emoji],
    )
    await bot.add_sticker_to_set(user_id=user_id, name=name, sticker=sticker)


async def refresh_last_sticker(
    bot: Bot, pack_id: int, sticker_record_id: int
) -> dict[str, Any] | None:
    """После добавления забираем настоящие file_id из Telegram — они нужны для inline."""
    from app import database as db

    pack = await get_pack(pack_id)
    if not pack:
        return None
    try:
        sticker_set = await bot.get_sticker_set(pack["name"])
    except Exception:
        return None
    if not sticker_set.stickers:
        return None
    last = sticker_set.stickers[-1]
    await db.set_pack_sticker_file(sticker_record_id, last.file_id, last.file_unique_id)
    return {"file_id": last.file_id, "file_unique_id": last.file_unique_id}


async def get_set_stickers(bot: Bot, name: str) -> list[Any]:
    sticker_set = await bot.get_sticker_set(name)
    return list(sticker_set.stickers)


async def delete_last_sticker(bot: Bot, pack_id: int) -> bool:
    pack = await get_pack(pack_id)
    if not pack:
        return False
    stickers = await get_set_stickers(bot, pack["name"])
    if not stickers:
        return False
    last = stickers[-1]
    await bot.delete_sticker_from_set(last.file_id)
    from app import database as db

    await db.remove_pack_sticker_by_file(last.file_id)
    return True


async def set_cover(bot: Bot, name: str, title: str, theme: str = "midnight") -> None:
    cover = images.build_pack_cover(title, theme)
    await bot.set_sticker_set_thumbnail(
        name=name,
        thumbnail=BufferedInputFile(cover, filename="cover.png"),
        format="static",
    )


async def export_zip(bot: Bot, name: str) -> tuple[bytes, str] | None:
    stickers = await get_set_stickers(bot, name)
    if not stickers:
        return None

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, sticker in enumerate(stickers, start=1):
            try:
                file = await bot.download(sticker.file_id)
                if file is None:
                    continue
                data = file.read() if hasattr(file, "read") else bytes(file)
                ext = "webm" if sticker.is_video else ("tgs" if sticker.is_animated else "webp")
                archive.writestr(f"{index:03d}_{sticker.emoji or 'sticker'}.{ext}", data)
            except Exception:
                continue
        archive.writestr(
            "pack.txt",
            f"{name}\nhttps://t.me/addstickers/{name}\nstickers: {len(stickers)}\n",
        )
    buffer.seek(0)
    return buffer.getvalue(), f"{name}.zip"


async def import_sticker_set(
    bot: Bot,
    user_id: int,
    source_name: str,
    title: str,
    emoji_mode: str,
    crop_mode: str,
    limit: int = PACK_MAX_STICKERS,
    on_progress=None,
) -> dict[str, Any]:
    """Клонирует чужой пак в собственный, сохраняя эмодзи."""
    from app import database as db
    from app.services.intake import download_telegram_file

    source = await bot.get_sticker_set(source_name)
    stickers = [s for s in source.stickers if not s.is_animated][:limit]
    if not stickers:
        raise ValueError("в паке только Lottie-стикеры — такой формат не переношу")

    kind = "video" if any(s.is_video for s in stickers) else "static"
    me = await bot.me()
    new_name = make_pack_name(title or source.title, me.username or "bot")
    pack_title = (title or source.title)[:64]

    added = 0
    for index, sticker in enumerate(stickers, start=1):
        data = await download_telegram_file(bot, sticker.file_id)
        if not data:
            continue
        fmt = "video" if sticker.is_video else "static"
        upload = BufferedInputFile(
            data, filename=f"sticker.{'webm' if fmt == 'video' else 'webp'}"
        )
        emoji_value = sticker.emoji or "🎲"
        payload = InputSticker(sticker=upload, format=fmt, emoji_list=[emoji_value])

        if added == 0:
            await bot.create_new_sticker_set(
                user_id=user_id, name=new_name, title=pack_title, stickers=[payload]
            )
            try:
                cover = images.build_pack_cover(pack_title)
                await bot.set_sticker_set_thumbnail(
                    name=new_name,
                    user_id=user_id,
                    thumbnail=BufferedInputFile(cover, filename="cover.png"),
                    format="static",
                )
            except Exception:
                pass
        else:
            await bot.add_sticker_to_set(user_id=user_id, name=new_name, sticker=payload)

        added += 1
        if on_progress and (index % 5 == 0 or index == len(stickers)):
            try:
                await on_progress(index, len(stickers))
            except Exception:
                pass

    if added == 0:
        raise ValueError("не удалось перенести ни одного стикера")

    pack_id = await db.create_pack(user_id, new_name, pack_title, kind, emoji_mode, crop_mode)

    try:
        final = await bot.get_sticker_set(new_name)
        for sticker in final.stickers:
            await db.add_pack_sticker(
                pack_id, sticker.file_id, sticker.file_unique_id, sticker.emoji or "🎲"
            )
    except Exception:
        pass

    return {
        "name": new_name,
        "pack_id": pack_id,
        "added": added,
        "total": len(stickers),
        "kind": kind,
    }


async def remaining_slots(pack_id: int) -> int:
    count = await pack_sticker_count(pack_id)
    return max(0, PACK_MAX_STICKERS - count)


async def register_sticker(pack_id: int, file_id: str | None, unique: str | None, emoji_value: str) -> int:
    from app import database as db

    record_id = await db.add_pack_sticker(pack_id, file_id, unique, emoji_value)
    return record_id
