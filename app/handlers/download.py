"""Скачивание по ссылкам: карточка с качествами, прогресс, отправка файла."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    LinkPreviewOptions,
    Message,
)

from app import database as db
from app.config import settings
from app.handlers.common import offer_pack_choice
from app.i18n import tr
from app.keyboards import after_download_keyboard, main_menu, quality_keyboard
from app.services import downloader, ffmpeg_tools, intake
from app.services.session import (
    download_tokens,
    global_semaphore,
    media_tokens,
    throttled,
    user_lock,
)
from app.services.utils import (
    cleanup_dir,
    download_url,
    human_duration,
    human_size,
    pick_url,
    short,
    temp_dir,
)

router = Router(name="download")

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


# --------------------------------------------------------------- карточка

async def _thumb_path(url: str | None) -> Path | None:
    if not url:
        return None
    cache = settings.cache_dir / "thumbs"
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / (hashlib.md5(url.encode("utf-8")).hexdigest()[:16] + ".jpg")
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    try:
        await download_url(url, dest, timeout=25, max_bytes=6 * 1024 * 1024)
        return dest
    except Exception:
        return None


def _payload(info: dict, url: str, lang: str) -> dict:
    options = downloader.quality_options(info)
    formats = info.get("formats") or []
    has_audio = any(f.get("acodec") not in (None, "none") for f in formats) or not formats
    return {
        "url": url,
        "canonical": info.get("webpage_url") or url,
        "lang": lang,
        "title": info.get("title") or tr(lang, "Без названия", "Untitled"),
        "options": options,
        "playlist": bool(info.get("_is_playlist")),
        "playlist_count": info.get("_playlist_count") or 1,
        "has_audio": has_audio,
        "subtitles": bool(info.get("subtitles") or info.get("automatic_captions")),
        "thumb": info.get("thumbnail") or downloader.thumbnail_url(info),
        "duration": info.get("duration") or 0,
        "caption": downloader.build_caption(info, url, lang)[:1000],
    }


async def _render_card(bot: Bot, chat_id: int, payload: dict, lang: str = "ru") -> None:
    token = download_tokens.put(payload)
    payload["token"] = token
    caption = payload.get("caption") or f"<b>{short(payload.get('title'), 120)}</b>"
    keyboard = quality_keyboard(
        token,
        payload["options"],
        lang,
        has_audio=payload.get("has_audio", True),
        playlist=payload.get("playlist", False),
        subtitles=payload.get("subtitles", False),
    )

    thumb = await _thumb_path(payload.get("thumb"))
    if thumb and thumb.exists():
        try:
            await bot.send_photo(
                chat_id,
                FSInputFile(thumb, filename="thumb.jpg"),
                caption=caption,
                reply_markup=keyboard,
            )
            return
        except TelegramBadRequest:
            pass

    await bot.send_message(
        chat_id, caption, reply_markup=keyboard, link_preview_options=NO_PREVIEW
    )


async def show_card(bot: Bot, chat_id: int, info: dict, url: str, lang: str = "ru") -> None:
    await _render_card(bot, chat_id, _payload(info, url, lang), lang)


async def start_from_url(
    bot: Bot,
    chat_id: int,
    user_id: int,
    url: str,
    lang: str = "ru",
    height: int = 720,
) -> None:
    """Скачать и отправить ссылку сразу, без карточки качеств (deep link из inline)."""
    status = await bot.send_message(tr(lang, "Разбираю ссылку.", "Reading the link."))
    try:
        info = await downloader.extract(url)
    except downloader.DownloadFailed as exc:
        await status.edit_text(downloader.explain(exc, lang))
        return

    if downloader.is_playlist(info):
        info = downloader.normalize_info(info)
    try:
        await status.delete()
    except TelegramBadRequest:
        pass

    payload = _payload(info, url, lang)
    options = payload["options"]
    option = next((item for item in options if item["height"] <= height), None)
    if option is None and options:
        option = min(options, key=lambda item: item["height"])

    await _download_and_send(
        bot,
        chat_id,
        user_id,
        payload,
        lang,
        option["selector"] if option else downloader.best_selector(),
        "",
        0,
        option["label"] if option else "",
    )


# ------------------------------------------------------------ вход по ссылке

@router.message(F.text.regexp(r"https?://"))
async def on_link(message: Message, bot: Bot, state: FSMContext, u: dict, l: str) -> None:
    url = pick_url(message.text)
    if not url:
        return

    sticker_name = downloader.is_sticker_link(url)
    if sticker_name:
        from app.handlers.pack import prepare_import

        await prepare_import(message, state, sticker_name, l)
        return

    if throttled(message.from_user.id, "link", 2.0):
        await message.answer(tr(l, "Секунду, доразберу предыдущую ссылку.", "One moment, still reading the previous link."))
        return

    kind = downloader.direct_kind(url)
    if kind in ("image", "gif"):
        await _handle_direct_image(message, url, kind, l)
        return
    if kind in ("video", "audio"):
        await _handle_direct_file(message, url, kind, l)
        return

    status = await message.answer(tr(l, "Разбираю ссылку.", "Reading the link."))
    try:
        info = await downloader.extract(url)
    except downloader.DownloadFailed as exc:
        await status.edit_text(downloader.explain(exc, l))
        return

    if downloader.is_playlist(info):
        info = downloader.normalize_info(info)

    try:
        await status.delete()
    except TelegramBadRequest:
        pass

    await show_card(bot, message.chat.id, info, url, l)


async def _handle_direct_image(message: Message, url: str, kind: str, lang: str) -> None:
    workdir = temp_dir()
    try:
        job = await intake.build_from_url(url, workdir)
    except intake.IntakeError as exc:
        cleanup_dir(workdir)
        await message.answer(short(str(exc), 300))
        return

    path = job.raw_path or job.path
    token = media_tokens.put(
        {"path": path, "kind": "image", "temp_dir": workdir, "title": url}
    )
    keyboard = after_download_keyboard(token, True, lang)
    try:
        if kind == "gif":
            await message.answer_animation(
                FSInputFile(path, filename=path.name),
                caption=short(url, 80),
                reply_markup=keyboard,
            )
        else:
            await message.answer_photo(
                FSInputFile(path, filename=path.name),
                caption=short(url, 80),
                reply_markup=keyboard,
            )
    except TelegramBadRequest:
        await message.answer_document(
            FSInputFile(path, filename=path.name),
            caption=short(url, 200),
            reply_markup=keyboard,
        )

    await db.add_download(
        message.from_user.id, url, path.name, "image", None, None, path.stat().st_size
    )
    await db.bump_downloads(message.from_user.id)
    asyncio.create_task(_delayed_cleanup(workdir))


async def _handle_direct_file(message: Message, url: str, kind: str, lang: str) -> None:
    status = await message.answer(tr(lang, "Скачиваю файл по ссылке.", "Downloading the file."))
    workdir = temp_dir()
    ext = Path(url.split("?")[0]).suffix or (".mp4" if kind == "video" else ".mp3")
    dest = workdir / f"direct{ext}"
    try:
        await download_url(url, dest, timeout=300, max_bytes=settings.max_upload_bytes + 1)
    except ValueError:
        cleanup_dir(workdir)
        await status.edit_text(
            tr(
                lang,
                f"Файл больше {settings.max_upload_mb} МБ, Telegram не пропустит его без сжатия.",
                f"The file is over {settings.max_upload_mb} MB, Telegram will refuse it without compression.",
            )
        )
        return
    except Exception:
        cleanup_dir(workdir)
        await status.edit_text(
            tr(lang, "Не удалось скачать файл по ссылке.", "Could not download the file.")
        )
        return

    size = dest.stat().st_size
    token = media_tokens.put(
        {"path": dest, "kind": kind, "temp_dir": workdir, "title": url}
    )
    keyboard = after_download_keyboard(token, kind == "video", lang)
    try:
        if kind == "audio":
            sent = await message.answer_audio(
                FSInputFile(dest, filename=dest.name),
                caption=short(url, 200),
                reply_markup=keyboard,
            )
            await db.add_download(
                message.from_user.id,
                url,
                dest.name,
                "audio",
                sent.audio.file_id if sent.audio else None,
                sent.audio.file_unique_id if sent.audio else None,
                size,
            )
        else:
            info = await ffmpeg_tools.probe(dest)
            sent = await message.answer_video(
                FSInputFile(dest, filename=dest.name),
                caption=f"{short(url, 120)}\n{human_size(size, lang)}",
                duration=int(info.get("duration") or 0),
                width=info.get("width") or 0,
                height=info.get("height") or 0,
                supports_streaming=True,
                reply_markup=keyboard,
            )
            await db.add_download(
                message.from_user.id,
                url,
                dest.name,
                "video",
                sent.video.file_id if sent.video else None,
                sent.video.file_unique_id if sent.video else None,
                size,
            )
    except TelegramBadRequest:
        await message.answer_document(
            FSInputFile(dest, filename=dest.name), caption=short(url, 200)
        )
    finally:
        try:
            await status.delete()
        except Exception:
            pass
        await db.bump_downloads(message.from_user.id)
        asyncio.create_task(_delayed_cleanup(workdir))


async def _delayed_cleanup(path: Path, delay: float = 3600) -> None:
    await asyncio.sleep(delay)
    cleanup_dir(path)


# ---------------------------------------------------------------- кнопки dl

@router.callback_query(F.data.startswith("dl:"))
async def on_download(call: CallbackQuery, bot: Bot, u: dict, l: str) -> None:
    parts = call.data.split(":")
    if len(parts) < 3:
        await call.answer()
        return

    token, action = parts[1], parts[2]
    payload = download_tokens.get(token)
    if not payload:
        await call.answer(
            tr(l, "Кнопка устарела, пришли ссылку заново", "This button expired, send the link again"),
            show_alert=True,
        )
        return
    payload["token"] = token
    lang = payload.get("lang") or l

    if action == "cancel":
        await call.answer(tr(lang, "Отменено", "Cancelled"))
        try:
            await call.message.delete()
        except Exception:
            pass
        return

    if action == "again":
        await call.answer()
        await _render_card(bot, call.message.chat.id, payload, lang)
        return

    if action == "thumb":
        await call.answer()
        thumb = await _thumb_path(payload.get("thumb"))
        if not thumb:
            await call.answer(tr(lang, "Обложки нет", "No cover"), show_alert=True)
            return
        await bot.send_photo(
            call.message.chat.id,
            FSInputFile(thumb, filename="cover.jpg"),
            caption=short(payload.get("title"), 200),
        )
        return

    if action == "subs":
        await _send_subtitles(call, bot, payload, lang)
        return

    if action == "best":
        await _start(call, bot, u, payload, lang, selector=downloader.best_selector())
        return

    if action == "mp3":
        await _start(call, bot, u, payload, lang, audio_format="mp3")
        return

    if action == "m4a":
        await _start(call, bot, u, payload, lang, audio_format="m4a")
        return

    if action == "pl":
        await _start(
            call,
            bot,
            u,
            payload,
            lang,
            selector=downloader.best_selector(),
            playlist_limit=10,
        )
        return

    if action.startswith("q"):
        try:
            option = payload["options"][int(action[1:])]
        except (ValueError, IndexError):
            await call.answer(tr(lang, "Нет такого качества", "No such quality"), show_alert=True)
            return
        await _start(
            call,
            bot,
            u,
            payload,
            lang,
            selector=option["selector"],
            quality_label=option["label"],
        )
        return

    await call.answer()


async def _start(
    call: CallbackQuery,
    bot: Bot,
    u: dict,
    payload: dict,
    lang: str,
    selector: str = "",
    audio_format: str = "",
    playlist_limit: int = 0,
    quality_label: str = "",
) -> None:
    user_id = call.from_user.id
    if throttled(user_id, "download", 3.0):
        await call.answer(tr(lang, "Не так быстро", "Not so fast"))
        return

    lock = user_lock(user_id)
    if lock.locked():
        await call.answer(
            tr(lang, "Уже качаю, дождись окончания", "Already downloading, wait for it"),
            show_alert=True,
        )
        return

    await call.answer(tr(lang, "Поехали", "Starting"))
    await _download_and_send(
        bot,
        call.message.chat.id,
        user_id,
        payload,
        lang,
        selector,
        audio_format,
        playlist_limit,
        quality_label,
    )


async def _download_and_send(
    bot: Bot,
    chat_id: int,
    user_id: int,
    payload: dict,
    lang: str,
    selector: str,
    audio_format: str,
    playlist_limit: int,
    quality_label: str,
) -> None:
    workdir = temp_dir()
    progress = downloader.Progress()
    status = await bot.send_message(
        chat_id, tr(lang, "Готовлюсь к скачиванию.", "Preparing the download.")
    )
    semaphore = global_semaphore(settings.max_concurrent_downloads)
    lock = user_lock(user_id)

    async def update(p: downloader.Progress) -> None:
        try:
            await status.edit_text(
                downloader.render_progress(p, payload.get("title", ""), lang)
            )
        except Exception:
            pass

    try:
        async with lock, semaphore:
            async with downloader.ProgressReporter(progress, update, 3.0):
                result = await downloader.full_download(
                    payload["url"],
                    workdir,
                    progress,
                    selector=selector,
                    audio_format=audio_format,
                    playlist_limit=playlist_limit,
                )
        try:
            await status.edit_text(
                tr(lang, "Отправляю в Telegram.", "Sending to Telegram.")
            )
        except Exception:
            pass
    except downloader.DownloadFailed as exc:
        cleanup_dir(workdir)
        await status.edit_text(downloader.explain(exc, lang))
        return
    except Exception as exc:  # noqa: BLE001
        cleanup_dir(workdir)
        await status.edit_text(
            tr(lang, "Ошибка: ", "Error: ") + short(str(exc), 250)
        )
        return

    try:
        if audio_format:
            await _send_audio(
                bot, chat_id, user_id, payload, lang, result, workdir, audio_format
            )
        elif playlist_limit:
            await _send_playlist(
                bot, chat_id, user_id, payload, lang, workdir, playlist_limit
            )
        else:
            await _send_video(
                bot, chat_id, user_id, payload, lang, result, workdir, quality_label
            )
        await db.bump_downloads(user_id)
    except TelegramBadRequest as exc:
        await bot.send_message(
            chat_id,
            tr(lang, "Telegram не принял файл: ", "Telegram refused the file: ")
            + short(str(exc), 250),
        )
    finally:
        try:
            await status.delete()
        except Exception:
            pass
        asyncio.create_task(_delayed_cleanup(workdir))


async def _send_subtitles(
    call: CallbackQuery, bot: Bot, payload: dict, lang: str
) -> None:
    await call.answer(tr(lang, "Ищу субтитры", "Looking for subtitles"))
    workdir = temp_dir()
    try:
        path = await downloader.download_subtitles(payload["url"], workdir, lang)
    except Exception:
        path = None
    if not path:
        cleanup_dir(workdir)
        await call.answer(tr(lang, "Субтитров нет", "No subtitles"), show_alert=True)
        return
    data = path.read_bytes()
    await bot.send_document(
        call.message.chat.id,
        BufferedInputFile(data, filename=path.name),
        caption=short(payload.get("title"), 100),
    )
    cleanup_dir(workdir)


async def _send_audio(
    bot: Bot,
    chat_id: int,
    user_id: int,
    payload: dict,
    lang: str,
    result: downloader.DownloadResult,
    workdir: Path,
    audio_format: str,
) -> None:
    if not result.path or not result.path.exists():
        await bot.send_message(chat_id, tr(lang, "Аудио не появилось.", "The audio did not appear."))
        return

    token = media_tokens.put(
        {"path": result.path, "kind": "audio", "temp_dir": workdir, "title": result.title}
    )
    message = await bot.send_audio(
        chat_id,
        FSInputFile(result.path, filename=result.path.name),
        title=short(result.title, 60),
        duration=int(result.duration or 0),
        caption=(
            f"<b>{short(result.title, 120)}</b>\n"
            f"{human_size(result.size, lang)} · {audio_format.upper()}"
        ),
        reply_markup=after_download_keyboard(token, False, lang),
    )
    if message.audio:
        await db.add_download(
            user_id,
            payload.get("url"),
            result.title,
            "audio",
            message.audio.file_id,
            message.audio.file_unique_id,
            result.size,
        )


async def _send_video(
    bot: Bot,
    chat_id: int,
    user_id: int,
    payload: dict,
    lang: str,
    result: downloader.DownloadResult,
    workdir: Path,
    quality_label: str,
) -> None:
    path = result.path
    if not path or not path.exists():
        await bot.send_message(
            chat_id, tr(lang, "Файл не появился после скачивания.", "No file appeared after the download.")
        )
        return

    size = path.stat().st_size
    max_bytes = settings.max_upload_bytes

    if size > max_bytes:
        autocompress = True
        try:
            user = await db.get_user(user_id)
            autocompress = user["settings"].get("autocompress", True)
        except Exception:
            pass

        if not autocompress:
            await bot.send_message(
                chat_id,
                tr(
                    lang,
                    f"Файл {human_size(size, lang)} больше лимита {settings.max_upload_mb} МБ.\n"
                    "Включи автосжатие в /settings или выбери качество ниже.",
                    f"The file is {human_size(size, lang)}, over the {settings.max_upload_mb} MB limit.\n"
                    "Enable auto-compress in /settings or pick a lower quality.",
                ),
            )
            return

        await bot.send_message(
            chat_id,
            tr(
                lang,
                f"Файл {human_size(size, lang)}, сжимаю под лимит.",
                f"The file is {human_size(size, lang)}, compressing it under the limit.",
            ),
        )
        try:
            compressed = workdir / f"compressed{path.suffix}"
            path = await ffmpeg_tools.shrink_video(
                path, compressed, max_bytes - 1024 * 1024, result.duration
            )
            size = path.stat().st_size
        except Exception:
            await bot.send_message(
                chat_id,
                tr(lang, "Не удалось сжать файл. Выбери качество ниже.", "Could not compress the file. Pick a lower quality."),
            )
            return

    info = await ffmpeg_tools.probe(path)
    duration = int(result.duration or info.get("duration") or 0)
    thumb = await ffmpeg_tools.make_thumbnail(
        path, workdir / "thumb.jpg", at=min(2.0, max(0.3, duration / 3)), width=320
    )

    token = media_tokens.put(
        {"path": path, "kind": "video", "temp_dir": workdir, "title": result.title}
    )
    caption = (
        f"<b>{short(result.title, 160)}</b>\n"
        f"{quality_label or tr(lang, 'лучшее', 'best')} · "
        f"{human_size(size, lang)} · {human_duration(duration)}"
    )

    try:
        message = await bot.send_video(
            chat_id,
            FSInputFile(path, filename=path.name),
            caption=caption,
            duration=duration,
            width=info.get("width") or 0,
            height=info.get("height") or 0,
            supports_streaming=True,
            thumbnail=FSInputFile(thumb) if thumb else None,
            reply_markup=after_download_keyboard(token, True, lang),
        )
        if message.video:
            await db.add_download(
                user_id,
                payload.get("url"),
                result.title,
                "video",
                message.video.file_id,
                message.video.file_unique_id,
                size,
            )
            try:
                for key in {payload.get("url") or "", payload.get("canonical") or ""}:
                    await db.save_inline_cached(
                        key,
                        int(info.get("height") or 0),
                        message.video.file_id,
                        result.title,
                        duration,
                    )
            except Exception:
                pass
        return
    except TelegramBadRequest:
        pass

    message = await bot.send_document(
        chat_id,
        FSInputFile(path, filename=path.name),
        caption=caption,
        reply_markup=after_download_keyboard(token, False, lang),
    )
    if message.document:
        await db.add_download(
            user_id,
            payload.get("url"),
            result.title,
            "video",
            message.document.file_id,
            message.document.file_unique_id,
            size,
        )


async def _send_playlist(
    bot: Bot,
    chat_id: int,
    user_id: int,
    payload: dict,
    lang: str,
    workdir: Path,
    limit: int,
) -> None:
    files = sorted(
        [
            p
            for p in workdir.rglob("*")
            if p.is_file()
            and p.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov", ".mp3", ".m4a")
        ],
        key=lambda p: p.name,
    )[:limit]

    if not files:
        await bot.send_message(
            chat_id, tr(lang, "В плейлисте ничего не скачалось.", "Nothing from the playlist was downloaded.")
        )
        return

    await bot.send_message(
        chat_id,
        tr(
            lang,
            f"Плейлист: отправляю {len(files)} файлов.",
            f"Playlist: sending {len(files)} files.",
        ),
    )
    for index, path in enumerate(files, start=1):
        if path.stat().st_size > settings.max_upload_bytes:
            await bot.send_message(
                chat_id,
                tr(
                    lang,
                    f"{index}. {short(path.name, 60)} больше лимита, пропустил",
                    f"{index}. {short(path.name, 60)} is over the limit, skipped",
                ),
            )
            continue
        caption = f"{index}/{len(files)} · {short(payload.get('title'), 60)}"
        try:
            if path.suffix.lower() in (".mp3", ".m4a"):
                await bot.send_audio(
                    chat_id, FSInputFile(path, filename=path.name), caption=caption
                )
            else:
                await bot.send_video(
                    chat_id,
                    FSInputFile(path, filename=path.name),
                    caption=caption,
                    supports_streaming=True,
                )
        except TelegramBadRequest:
            try:
                await bot.send_document(
                    chat_id, FSInputFile(path, filename=path.name), caption=caption
                )
            except Exception:
                continue


# ------------------------------------------------------------ «в стикер»

@router.callback_query(F.data.startswith("ds:"))
async def downloaded_to_sticker(
    call: CallbackQuery, bot: Bot, state: FSMContext, l: str
) -> None:
    payload = media_tokens.pop(call.data.split(":", 1)[1])
    if not payload:
        await call.answer(tr(l, "Файл уже удалён", "The file is already gone"), show_alert=True)
        return

    try:
        job = await intake.build_from_path(payload["path"], payload["temp_dir"])
    except Exception:
        await call.answer(
            tr(l, "Не смог подготовить стикер", "Could not prepare the sticker"), show_alert=True
        )
        return

    await call.answer()
    await offer_pack_choice(
        bot,
        call.message.chat.id,
        call.from_user.id,
        state,
        job,
        header=tr(
            l,
            f"Куда добавить «{short(payload.get('title'), 40)}»?",
            f"Where should “{short(payload.get('title'), 40)}” go?",
        ),
        lang=l,
    )


# ------------------------------------------------------- подсказка-заглушка

@router.message(F.text)
async def text_without_url(message: Message, l: str) -> None:
    if (message.text or "").startswith("/"):
        return
    await message.answer(
        tr(
            l,
            "Пришли ссылку на видео или фото, либо выбери раздел в меню.",
            "Send a link to a video or photo, or pick a section in the menu.",
        ),
        reply_markup=main_menu(l),
        link_preview_options=NO_PREVIEW,
    )
