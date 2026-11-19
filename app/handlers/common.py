"""Общие сценарии: редактирование сообщений, сборка и добавление стикера."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    LinkPreviewOptions,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import database as db
from app.config import PACK_MAX_STICKERS
from app.i18n import tr
from app.services import ffmpeg_tools, packs
from app.services.emoji import random_emoji, smart_emoji
from app.services.session import PackDraft, StickerJob, pack_drafts, pending_stickers
from app.states import Flow


async def safe_edit(call: CallbackQuery, text: str, keyboard=None) -> None:
    if not call.message:
        return
    try:
        await call.message.edit_text(
            text,
            reply_markup=keyboard,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        return
    except TelegramBadRequest:
        pass
    try:
        await call.message.edit_caption(caption=text, reply_markup=keyboard)
        return
    except TelegramBadRequest:
        pass
    try:
        await call.message.answer(
            text,
            reply_markup=keyboard,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    except Exception:
        pass


async def convert_job(job: StickerJob, mode: str) -> Path:
    out = job.temp_dir or (job.raw_path.parent if job.raw_path else Path("."))
    if job.kind == "static":
        src = job.raw_path or job.path
        if job.is_frame:
            frame = out / "frame.jpg"
            await ffmpeg_tools.extract_frame(src, frame, max(0.0, job.start) + 0.1)
            src = frame
        focus = job.focus
        if mode == "smart" and focus is None:
            focus = await ffmpeg_tools.detect_focus(src)
        return await ffmpeg_tools.photo_to_sticker(src, out / "sticker.webp", mode, focus)

    focus = job.focus
    if mode == "smart":
        focus = await ffmpeg_tools.detect_focus(job.raw_path or job.path, job.start + 0.2)
    return await ffmpeg_tools.video_to_sticker(
        job.raw_path or job.path,
        out / "sticker.webm",
        start=job.start,
        duration=job.duration,
        mode=mode,
        focus=focus,
        alpha=job.alpha,
    )


async def finalize_job(
    bot: Bot,
    chat_id: int,
    user_id: int,
    job: StickerJob,
    pack: dict[str, Any] | None,
    draft: PackDraft | None,
    emoji_value: str,
) -> dict[str, Any]:
    mode = (pack or {}).get("crop_mode") or (draft.crop_mode if draft else "crop")
    sticker_path = await convert_job(job, mode)

    is_new = pack is None
    if is_new:
        if draft is None:
            raise RuntimeError("no draft")
        name = packs.make_pack_name(draft.title, bot.username or "bot")
        title = draft.title[:64]
        kind = draft.kind
        await packs.create_pack(bot, user_id, name, title, kind, sticker_path, emoji_value)
        pack_id = await db.create_pack(
            user_id, name, title, kind, draft.emoji_mode, draft.crop_mode
        )
    else:
        pack_id = int(pack["id"])
        name = pack["name"]
        title = pack["title"]
        kind = pack["kind"]
        await packs.add_sticker(bot, user_id, name, kind, sticker_path, emoji_value)

    record_id = await db.add_pack_sticker(pack_id, None, None, emoji_value)
    file_info = await packs.refresh_last_sticker(bot, pack_id, record_id)
    count = await db.pack_sticker_count(pack_id)

    if is_new:
        pack_drafts.pop((chat_id, user_id), None)
    pending_stickers.pop((chat_id, user_id), None)
    job.cleanup()

    return {
        "pack_id": pack_id,
        "name": name,
        "title": title,
        "kind": kind,
        "count": count,
        "file_id": (file_info or {}).get("file_id"),
        "is_new": is_new,
    }


async def send_preview(
    bot: Bot,
    chat_id: int,
    job: StickerJob,
    caption: str,
    keyboard=None,
) -> None:
    if job.preview and job.preview.exists():
        try:
            await bot.send_photo(
                chat_id,
                FSInputFile(job.preview, filename="preview.jpg"),
                caption=caption,
                reply_markup=keyboard,
            )
            return
        except Exception:
            pass
    await bot.send_message(chat_id, caption, reply_markup=keyboard)


async def start_emoji_step(
    bot: Bot,
    chat_id: int,
    user_id: int,
    state: Any,
    job: StickerJob,
    pack: dict[str, Any] | None,
    draft: PackDraft | None,
    lang: str,
) -> None:
    from app.keyboards import emoji_confirm_keyboard, emoji_grid

    key = (chat_id, user_id)
    pending_stickers[key] = job
    mode = (pack or {}).get("emoji_mode") or (draft.emoji_mode if draft else "manual")
    used = await db.pack_used_emoji(int(pack["id"])) if pack else set()

    if pack:
        position = await db.pack_sticker_count(int(pack["id"])) + 1
        header = tr(
            lang,
            f"<b>{pack['title']}</b>, стикер {position} из {PACK_MAX_STICKERS}",
            f"<b>{pack['title']}</b>, sticker {position} of {PACK_MAX_STICKERS}",
        )
    else:
        header = tr(
            lang,
            f"<b>{draft.title if draft else 'Новый пак'}</b>, первый стикер",
            f"<b>{draft.title if draft else 'New pack'}</b>, first sticker",
        )

    if mode == "manual":
        await state.set_state(Flow.sticker_emoji)
        await state.update_data(pack_id=pack["id"] if pack else None)
        caption = header + "\n\n" + tr(
            lang,
            "Пришли эмодзи для стикера или выбери вариант ниже. "
            "Эмодзи определяет, по каким запросам стикер находится в поиске.",
            "Send an emoji for the sticker or pick one below. "
            "The emoji decides which searches find the sticker.",
        )
        await send_preview(bot, chat_id, job, caption, emoji_grid(used, lang=lang))
        return

    emoji_value = (
        smart_emoji(job.preview or job.path, used) if mode == "smart" else random_emoji(used)
    )
    job.emoji = emoji_value
    await state.set_state(Flow.pack_media)
    await state.update_data(step="confirm", pack_id=pack["id"] if pack else None)
    mode_label = tr(
        lang,
        "умный подбор" if mode == "smart" else "случайный выбор",
        "smart pick" if mode == "smart" else "random pick",
    )
    caption = (
        f"{header}\n\n"
        + tr(lang, f"Эмодзи: <b>{emoji_value}</b>", f"Emoji: <b>{emoji_value}</b>")
        + f"\n{mode_label}\n\n"
        + tr(lang, "Нажми «Добавить» или выбери другой.", "Press Add or pick another one.")
    )
    await send_preview(bot, chat_id, job, caption, emoji_confirm_keyboard(emoji_value, lang))


async def offer_pack_choice(
    bot: Bot,
    chat_id: int,
    user_id: int,
    state: Any,
    job: StickerJob,
    header: str,
    lang: str,
) -> None:
    key = (chat_id, user_id)
    pending_stickers[key] = job
    user_packs = await db.user_packs(user_id)
    if not user_packs:
        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(
                text=tr(lang, "Создать пак", "Create a pack"), callback_data="newpack"
            )
        )
        await bot.send_message(
            chat_id,
            tr(
                lang,
                "Паков ещё нет. Создай первый, и я сразу положу стикер туда.",
                "You have no packs yet. Create one and the sticker goes straight in.",
            ),
            reply_markup=builder.as_markup(),
        )
        return

    builder = InlineKeyboardBuilder()
    for pack in user_packs:
        kind = tr(lang, "видео", "video") if pack["kind"] == "video" else tr(lang, "фото", "photo")
        builder.button(
            text=f"{pack['title'][:28]} · {pack.get('count', 0)} · {kind}",
            callback_data=f"pk:{pack['id']}:attach",
        )
    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Новый пак", "New pack"), callback_data="newpack"
        )
    )
    await state.set_state(Flow.pack_media)
    await state.update_data(step="choose_pack")
    await bot.send_message(chat_id, header, reply_markup=builder.as_markup())


async def attach_job_to_pack(
    bot: Bot, chat_id: int, user_id: int, state: Any, pack_id: int, lang: str
) -> bool:
    key = (chat_id, user_id)
    job = pending_stickers.get(key)
    if not job:
        await bot.send_message(
            chat_id, tr(lang, "Заготовка устарела, пришли медиа заново.", "Draft expired, send the media again.")
        )
        return False

    pack = await db.get_pack(pack_id)
    if not pack or int(pack["tg_id"]) != user_id:
        await bot.send_message(chat_id, tr(lang, "Пак не найден.", "Pack not found."))
        return False

    count = await db.pack_sticker_count(pack_id)
    if count >= PACK_MAX_STICKERS:
        await bot.send_message(
            chat_id,
            tr(
                lang,
                f"В паке уже {PACK_MAX_STICKERS} стикеров, это максимум Telegram.",
                f"The pack already has {PACK_MAX_STICKERS} stickers, Telegram's maximum.",
            ),
        )
        return False

    if job.kind != pack["kind"]:
        if pack["kind"] == "static" and job.kind == "video":
            job.kind = "static"
            job.is_frame = True
            await bot.send_message(
                chat_id,
                tr(lang, "Это фото-пак, возьму кадр из видео.", "This is a photo pack, I will take a frame."),
            )
        else:
            await bot.send_message(
                chat_id,
                tr(
                    lang,
                    "Это видео-пак, а заготовка — фото. Нужен видео-пак для видео-стикеров.",
                    "This is a video pack and the draft is a photo. Video stickers need a video pack.",
                ),
            )
            return False

    await start_emoji_step(bot, chat_id, user_id, state, job, pack, None, lang)
    return True
