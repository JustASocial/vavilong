"""Inline-режим: @bot <ссылка> [качество] [+info] без лишнего текста."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from aiogram import Bot, Router
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultAudio,
    InlineQueryResultCachedVideo,
    InlineQueryResultPhoto,
    InlineQueryResultVideo,
    InputTextMessageContent,
)

from app import database as db
from app.config import settings
from app.i18n import tr
from app.services import downloader
from app.services.session import inline_urls
from app.services.utils import human_duration, pick_url, short

router = Router(name="inline")

CACHE_TTL = 300.0
CACHE_LIMIT = 200
_info_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_locks: dict[str, asyncio.Lock] = {}

MAX_RESULTS = 6


# ------------------------------------------------------------------- парсинг

def parse_query(raw: str) -> tuple[str | None, list[int], bool]:
    """Возвращает (ссылка, список желаемых высот, нужна ли инфа)."""
    text = (raw or "").strip()
    url = pick_url(text)
    if not url:
        return None, [], False

    rest = text.replace(url, " ")
    want_info = bool(re.search(r"\+\s*(info|инфо)\b|(^|\s)(info|инфо)(\s|$)", rest, re.I))

    heights: list[int] = []
    bracket = re.search(r"\[([^\]]+)\]", rest)
    if bracket:
        for value in re.findall(r"(\d{2,4})", bracket.group(1)):
            height = int(value)
            if 144 <= height <= 2160 and height not in heights:
                heights.append(height)
    else:
        match = re.search(r"\b(\d{3,4})\s*p\b", rest, re.I)
        if match:
            height = int(match.group(1))
            if 144 <= height <= 2160:
                heights.append(height)

    if not heights:
        heights = [downloader.INLINE_DEFAULT_HEIGHT]
    return url, heights, want_info


async def get_info(url: str) -> dict[str, Any]:
    now = time.monotonic()
    cached = _info_cache.get(url)
    if cached and cached[0] > now:
        return cached[1]

    lock = _locks.setdefault(url, asyncio.Lock())
    async with lock:
        cached = _info_cache.get(url)
        if cached and cached[0] > now:
            return cached[1]

        info = await downloader.extract(url, timeout=9.0)
        if downloader.is_playlist(info):
            info = downloader.normalize_info(info)

        _info_cache[url] = (now + CACHE_TTL, info)
        if len(_info_cache) > CACHE_LIMIT:
            oldest = min(_info_cache, key=lambda key: _info_cache[key][0])
            _info_cache.pop(oldest, None)
        return info


# ------------------------------------------------------------------ разметка

def _thumb(info: dict[str, Any]) -> str | None:
    url = downloader.thumbnail_url(info)
    if not url:
        return None
    return url.replace("http://", "https://", 1)


def _mime(fmt: dict[str, Any]) -> str:
    ext = str(fmt.get("ext") or "mp4").lower()
    return {
        "mp4": "video/mp4",
        "m4v": "video/mp4",
        "webm": "video/webm",
        "mov": "video/quicktime",
        "mkv": "video/x-matroska",
    }.get(ext, "video/mp4")


def _poster() -> str | None:
    base = (settings.public_base_url or "").rstrip("/")
    return f"{base}/poster.jpg" if base else None


def _video_result(
    info: dict[str, Any],
    fmt: dict[str, Any],
    height: int,
    lang: str,
    want_info: bool,
) -> InlineQueryResultVideo | None:
    video_url = str(fmt.get("url") or "")
    if not video_url.startswith("http"):
        return None
    thumb = _thumb(info) or _poster()
    if not thumb:
        return None

    title_text = short(str(info.get("title") or tr(lang, "Видео", "Video")), 48)
    duration = int(fmt.get("duration") or info.get("duration") or 0)
    description = downloader.info_caption(info, lang)

    caption = None
    if want_info:
        caption = (
            f"<b>{short(str(info.get('title') or ''), 120)}</b>\n"
            f"{description}"
        )

    return InlineQueryResultVideo(
        id=downloader.inline_result_id(info, height),
        video_url=video_url.replace("http://", "https://", 1),
        mime_type=_mime(fmt),
        thumbnail_url=thumb,
        title=f"{height}p · {title_text}",
        description=description or tr(lang, "Видео", "Video"),
        video_width=int(fmt.get("width") or 0) or None,
        video_height=int(fmt.get("height") or 0) or None,
        video_duration=duration or None,
        caption=caption,
        parse_mode="HTML" if caption else None,
    )


def _photo_result(info: dict[str, Any], lang: str) -> InlineQueryResultPhoto | None:
    url = info.get("url") or _thumb(info)
    if not url or not str(url).startswith("http"):
        return None
    thumb = _thumb(info) or url or _poster()
    return InlineQueryResultPhoto(
        id="photo",
        photo_url=str(url),
        thumbnail_url=thumb,
        title=short(str(info.get("title") or tr(lang, "Фото", "Photo")), 48),
        description=downloader.info_caption(info, lang),
        caption=short(str(info.get("title") or ""), 200) or None,
    )


def _audio_result(info: dict[str, Any], lang: str) -> InlineQueryResultAudio | None:
    url = info.get("url")
    if not url or not str(url).startswith("http"):
        return None
    return InlineQueryResultAudio(
        id="audio",
        audio_url=str(url),
        title=short(str(info.get("title") or tr(lang, "Аудио", "Audio")), 64),
        performer=short(str(info.get("uploader") or info.get("artist") or ""), 64) or None,
        audio_duration=int(info.get("duration") or 0) or None,
    )


def _open_in_bot(bot: Bot, url: str, info: dict[str, Any], lang: str, note: str):
    token = inline_urls.put({"url": url, "title": info.get("title") or url})
    link = f"https://t.me/{bot.username}?start=u_{token}"
    title_text = short(str(info.get("title") or tr(lang, "Открыть в боте", "Open in the bot")), 48)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr(lang, "Открыть в боте", "Open in the bot"), url=link
                )
            ]
        ]
    )
    return InlineQueryResultArticle(
        id="bot",
        title=title_text,
        description=note,
        input_message_content=InputTextMessageContent(
            message_text=tr(
                lang,
                f"<b>{short(str(info.get('title') or ''), 120)}</b>\n\n"
                "Прямая ссылка не подошла для inline. Открой бота и получи файл там.",
                f"<b>{short(str(info.get('title') or ''), 120)}</b>\n\n"
                "The direct link did not work for inline. Open the bot and get the file there.",
            ),
            parse_mode="HTML",
        ),
        reply_markup=keyboard,
    )


def _cached_result(
    row: dict, info: dict, lang: str, want_info: bool
) -> InlineQueryResultCachedVideo:
    height = int(row.get("height") or 0)
    title_text = short(str(row.get("title") or info.get("title") or tr(lang, "Видео", "Video")), 48)
    caption = None
    if want_info:
        caption = (
            f"<b>{short(str(info.get('title') or ''), 120)}</b>\n"
            f"{downloader.info_caption(info, lang)}"
        )
    return InlineQueryResultCachedVideo(
        id=f"c{height}",
        video_file_id=str(row["file_id"]),
        title=f"{height}p · {title_text}",
        description=downloader.info_caption(info, lang) or tr(lang, "Видео", "Video"),
        caption=caption,
        parse_mode="HTML" if caption else None,
    )


def _help_results(lang: str) -> list[InlineQueryResultArticle]:
    examples = [
        (
            "720",
            tr(lang, "Ссылка на видео", "A video link"),
            tr(
                lang,
                "@vavilong_bot <ссылка> — видео в 720p",
                "@vavilong_bot <link> — video in 720p",
            ),
        ),
        (
            "1080",
            tr(lang, "Своё качество", "Custom quality"),
            tr(
                lang,
                "@vavilong_bot <ссылка> 1080p",
                "@vavilong_bot <link> 1080p",
            ),
        ),
        (
            "list",
            tr(lang, "Список качеств", "Quality list"),
            "@vavilong_bot <link> [360p,480p,720p]",
        ),
        (
            "info",
            tr(lang, "+info", "+info"),
            tr(
                lang,
                "@vavilong_bot <ссылка> 720p +info — просмотры и лайки",
                "@vavilong_bot <link> 720p +info — views and likes",
            ),
        ),
    ]
    results = []
    for key, title, description in examples:
        results.append(
            InlineQueryResultArticle(
                id=f"h{key}",
                title=title,
                description=description,
                input_message_content=InputTextMessageContent(
                    message_text=f"{title}\n{description}"
                ),
            )
        )
    return results


def _error_result(exc: BaseException, lang: str, url: str | None = None):
    return InlineQueryResultArticle(
        id="err",
        title=tr(lang, "Не получилось", "Could not process the link"),
        description=downloader.explain(exc, lang),
        input_message_content=InputTextMessageContent(
            message_text=downloader.explain(exc, lang)
        ),
    )


# -------------------------------------------------------------------- хендлер

@router.inline_query()
async def on_inline(query: InlineQuery, bot: Bot, l: str) -> None:
    raw = query.query or ""
    url, heights, want_info = parse_query(raw)

    if not url:
        await query.answer(
            _help_results(l), cache_time=60, is_personal=True
        )
        return

    try:
        info = await get_info(url)
    except downloader.DownloadFailed as exc:
        results = [_error_result(exc, l)]
        if exc.code in ("timeout",):
            token = inline_urls.put({"url": url, "title": url})
            results.append(
                InlineQueryResultArticle(
                    id="later",
                    title=tr(l, "Открыть в боте", "Open in the bot"),
                    description=tr(
                        l,
                        "Сайт отвечает медленно — бот докачает в чате",
                        "The site is slow — the bot will finish in the chat",
                    ),
                    input_message_content=InputTextMessageContent(
                        message_text=tr(l, "Открываю в боте.", "Opening in the bot.")
                    ),
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text=tr(l, "Открыть", "Open"),
                                    url=f"https://t.me/{bot.username}?start=u_{token}",
                                )
                            ]
                        ]
                    ),
                )
            )
        await query.answer(results, cache_time=5, is_personal=True)
        return
    except Exception:  # noqa: BLE001
        await query.answer(
            [_error_result("unknown", l)], cache_time=5, is_personal=True
        )
        return

    results: list[Any] = []
    seen: set[str] = set()

    for height in heights:
        fmt, actual = downloader.pick_inline_format(info, height)
        if not fmt:
            continue
        key = f"{fmt.get('format_id')}-{actual}"
        if key in seen:
            continue
        seen.add(key)
        item = _video_result(info, fmt, actual, l, want_info)
        if item:
            results.append(item)

    if not results:
        cached = await db.inline_cached(url)
        canonical = str(info.get("webpage_url") or "")
        if not cached and canonical and canonical != url:
            cached = await db.inline_cached(canonical)
        if cached:
            wanted = heights[0]
            chosen = next((row for row in cached if int(row["height"]) == wanted), None)
            if chosen is None:
                lower = [row for row in cached if int(row["height"]) <= wanted]
                chosen = lower[0] if lower else cached[-1]
            item = _cached_result(chosen, info, l, want_info)
            if item:
                results.append(item)
        if not results:
            photo = _photo_result(info, l)
            audio = _audio_result(info, l)
            if photo:
                results.append(photo)
            elif audio:
                results.append(audio)
            else:
                results.append(
                    _open_in_bot(
                        bot,
                        url,
                        info,
                        l,
                        tr(
                            l,
                            "Сайт отдаёт видео и звук раздельно. Первый раз — через бота, "
                            "дальше inline отдаст файл мгновенно.",
                            "This site serves video and audio separately. First time goes "
                            "through the bot, after that inline is instant.",
                        ),
                    )
                )

    if len(results) < MAX_RESULTS:
        available = downloader.inline_heights_available(info)
        if want_info and results:
            description = downloader.info_caption(info, l)
            if description:
                first = results[0]
                extra = InlineQueryResultArticle(
                    id="details",
                    title=tr(l, "Информация", "Information"),
                    description=description,
                    input_message_content=InputTextMessageContent(
                        message_text=(
                            f"<b>{short(str(info.get('title') or ''), 120)}</b>\n"
                            f"{description}"
                        ),
                        parse_mode="HTML",
                    ),
                )
                results.append(extra)
        elif available and len(available) > 1:
            token = inline_urls.put({"url": url, "title": info.get("title") or url})
            results.append(
                InlineQueryResultArticle(
                    id="open",
                    title=tr(l, "Открыть в боте", "Open in the bot"),
                    description=tr(
                        l,
                        "Все качества, MP3, обложка и субтитры",
                        "Every quality, MP3, cover and subtitles",
                    ),
                    input_message_content=InputTextMessageContent(
                        message_text=short(str(info.get("title") or url), 200)
                    ),
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text=tr(l, "Открыть", "Open"),
                                    url=f"https://t.me/{bot.username}?start=u_{token}",
                                )
                            ]
                        ]
                    ),
                )
            )

    await query.answer(results[:MAX_RESULTS], cache_time=30, is_personal=True)
