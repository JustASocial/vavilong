"""Стикер-студия: создание паков, добавление стикеров, импорт, экспорт."""

from __future__ import annotations

import io

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import database as db
from app.config import PACK_MAX_STICKERS
from app.handlers.common import (
    attach_job_to_pack,
    finalize_job,
    offer_pack_choice,
    safe_edit,
    send_preview,
    start_emoji_step,
)
from app.i18n import tr
from app.keyboards import (
    confirm_delete_keyboard,
    crop_keyboard,
    emoji_confirm_keyboard,
    emoji_mode_keyboard,
    emoji_grid,
    import_preview_keyboard,
    pack_kind_keyboard,
    pack_view_keyboard,
    packs_list_keyboard,
    trim_keyboard,
)
from app.services import downloader, ffmpeg_tools, intake, packs
from app.services import emoji as emoji_service
from app.services.session import (
    ImportDraft,
    PackDraft,
    StickerJob,
    import_drafts,
    pack_drafts,
    pending_stickers,
)
from app.services.utils import cleanup_dir, human_duration, pick_url, temp_dir
from app.states import Flow

router = Router(name="pack")


def _key(event: Message | CallbackQuery) -> tuple[int, int]:
    chat_id = event.chat.id if isinstance(event, Message) else event.message.chat.id
    return chat_id, event.from_user.id


def _pack_text(pack: dict, count: int, lang: str) -> str:
    kind = tr(lang, "видео", "video") if pack["kind"] == "video" else tr(lang, "фото", "photo")
    emoji_mode = {
        "manual": tr(lang, "вручную", "manual"),
        "random": tr(lang, "рандом", "random"),
        "smart": tr(lang, "умный", "smart"),
    }.get(pack["emoji_mode"], pack["emoji_mode"])
    crop = {
        "crop": tr(lang, "по центру", "center"),
        "fit": tr(lang, "вписать", "fit"),
        "smart": tr(lang, "умный", "smart"),
    }.get(pack["crop_mode"], pack["crop_mode"])

    return tr(
        lang,
        f"<b>{pack['title']}</b>\n\n"
        f"t.me/addstickers/{pack['name']}\n"
        f"Тип: {kind}. Стикеров: <b>{count} из {PACK_MAX_STICKERS}</b>\n"
        f"Эмодзи: {emoji_mode}. Кадрирование: {crop}",
        f"<b>{pack['title']}</b>\n\n"
        f"t.me/addstickers/{pack['name']}\n"
        f"Type: {kind}. Stickers: <b>{count} of {PACK_MAX_STICKERS}</b>\n"
        f"Emoji: {emoji_mode}. Crop: {crop}",
    )


# ------------------------------------------------------------- .tgspack

@router.message(F.document.file_name.regexp(r"(?i)\.tgspack$"))
async def import_pack_file(message: Message, state: FSMContext, bot: Bot, l: str) -> None:
    await state.clear()
    if message.document:
        await _build_archive(bot, message.chat.id, message.from_user.id, message.document, l)


@router.callback_query(F.data == "tgspack:go")
async def import_pack_button(call: CallbackQuery, state: FSMContext, bot: Bot, l: str) -> None:
    await call.answer(tr(l, "Собираю пак", "Building the pack"))
    await state.clear()
    if call.message and call.message.document:
        await _build_archive(
            bot, call.message.chat.id, call.from_user.id, call.message.document, l
        )


async def _build_archive(bot: Bot, chat_id: int, user_id: int, document, lang: str) -> None:
    if document.file_size and document.file_size > 19 * 1024 * 1024:
        await bot.send_message(
            chat_id,
            tr(
                lang,
                "Архив больше 19 МБ: Telegram не даст боту его скачать. Убери часть стикеров.",
                "The archive is over 19 MB: Telegram will not let the bot download it. Remove some stickers.",
            ),
        )
        return

    status = await bot.send_message(
        chat_id,
        tr(lang, "Читаю .tgspack и собираю пак.", "Reading the .tgspack and building the pack."),
    )

    buffer = io.BytesIO()
    try:
        await bot.download(document, destination=buffer)
        title, items = packs.read_archive(buffer.getvalue())
    except packs.ArchiveError as exc:
        await status.edit_text(
            tr(lang, "Архив не подошёл: ", "The archive was rejected: ") + str(exc)
        )
        return
    except Exception:
        await status.edit_text(tr(lang, "Не смог скачать архив.", "Could not download the archive."))
        return

    async def progress(done: int, total: int) -> None:
        try:
            await status.edit_text(
                tr(lang, f"Собираю пак: {done} из {total}", f"Building the pack: {done} of {total}")
            )
        except Exception:
            pass

    try:
        result = await packs.create_pack_from_archive(
            bot, user_id, title, items, on_progress=progress
        )
    except TelegramBadRequest as exc:
        await status.edit_text(
            tr(lang, "Telegram отклонил пак.\n\n", "Telegram rejected the pack.\n\n")
            + f"<code>{str(exc)[:300]}</code>"
        )
        return
    except Exception as exc:  # noqa: BLE001
        await status.edit_text(tr(lang, "Ошибка: ", "Error: ") + str(exc)[:300])
        return

    link = packs.pack_link(result["name"])
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Открыть пак", "Open pack"), callback_data=f"pk:{result['pack_id']}:open"
        ),
        InlineKeyboardButton(text=tr(lang, "В меню", "Back to menu"), callback_data="m:home"),
    )
    await status.edit_text(
        tr(
            lang,
            f"<b>Пак собран.</b>\n\n"
            f"«{result['title']}», стикеров: <b>{result['added']}</b>\n"
            f'<a href="{link}">{link}</a>',
            f"<b>The pack is ready.</b>\n\n"
            f"“{result['title']}”, stickers: <b>{result['added']}</b>\n"
            f'<a href="{link}">{link}</a>',
        ),
        reply_markup=builder.as_markup(),
    )


# ------------------------------------------------------------------ список

@router.message(Command("packs"))
@router.callback_query(F.data == "m:packs")
async def show_packs(event: Message | CallbackQuery, l: str) -> None:
    is_call = isinstance(event, CallbackQuery)
    if is_call:
        await event.answer()

    user_packs = await db.user_packs(event.from_user.id)
    if user_packs:
        lines = [tr(l, "<b>Мои стикер-паки</b>", "<b>Your sticker packs</b>"), ""]
        for pack in user_packs:
            kind = tr(l, "видео", "video") if pack["kind"] == "video" else tr(l, "фото", "photo")
            lines.append(f"{pack['title']} — {pack.get('count', 0)} — {kind}")
        text = "\n".join(lines) + "\n\n" + tr(
            l, "Выбери пак ниже или создай новый.", "Pick a pack below or create a new one."
        )
    else:
        text = tr(
            l,
            "<b>Стикер-студия</b>\n\n"
            "Паков пока нет. Создание занимает полминуты: название, тип, режим эмодзи, "
            "кадрирование и первое медиа. Дальше достаточно присылать фото или видео.",
            "<b>Sticker studio</b>\n\n"
            "No packs yet. Creation takes half a minute: name, type, emoji mode, crop mode "
            "and the first media file. After that you only send photos or videos.",
        )

    keyboard = packs_list_keyboard(user_packs, l)
    if is_call:
        await safe_edit(event, text, keyboard)
    else:
        await event.answer(text, reply_markup=keyboard)


# ---------------------------------------------------------------- создание

@router.message(Command("newpack"))
async def cmd_newpack(message: Message, state: FSMContext, l: str) -> None:
    await _begin_new_pack(message, state, l)


@router.callback_query(F.data == "newpack")
async def cb_newpack(call: CallbackQuery, state: FSMContext, l: str) -> None:
    await call.answer()
    await _begin_new_pack(call, state, l)


async def _begin_new_pack(event: Message | CallbackQuery, state: FSMContext, lang: str) -> None:
    key = _key(event)
    old = pending_stickers.pop(key, None)
    if old:
        old.cleanup()
    pack_drafts[key] = PackDraft()
    await state.clear()
    await state.set_state(Flow.pack_title)

    text = tr(
        lang,
        "<b>Новый стикер-пак</b>\n\n"
        "Шаг 1 из 4. Пришли название пака, до 40 символов.",
        "<b>New sticker pack</b>\n\n"
        "Step 1 of 4. Send the pack name, up to 40 characters.",
    )
    if isinstance(event, CallbackQuery):
        await safe_edit(event, text, None)
    else:
        await event.answer(text)


@router.message(Flow.pack_title, F.text)
async def set_pack_title(message: Message, state: FSMContext, l: str) -> None:
    key = _key(message)
    title = " ".join(message.text.split()).strip()
    if not title:
        await message.answer(tr(l, "Название не может быть пустым.", "The name cannot be empty."))
        return
    title = title[:40]

    draft = pack_drafts.get(key) or PackDraft()
    draft.title = title
    pack_drafts[key] = draft

    await state.set_state(Flow.pack_kind)
    await message.answer(
        tr(
            l,
            f"Шаг 2 из 4. Название: <b>{title}</b>\n\n"
            "Фото-пак: WebP, 512×512, до 512 КБ.\n"
            "Видео-пак: WebM, 3 секунды, до 256 КБ.\n\n"
            "Тип фиксируется навсегда: Telegram не разрешает смешивать фото и видео в одном паке.",
            f"Step 2 of 4. Name: <b>{title}</b>\n\n"
            "Photo pack: WebP, 512×512, up to 512 KB.\n"
            "Video pack: WebM, 3 seconds, up to 256 KB.\n\n"
            "The type is permanent: Telegram does not allow mixed photo and video packs.",
        ),
        reply_markup=pack_kind_keyboard(l),
    )


@router.callback_query(Flow.pack_kind, F.data.startswith("kind:"))
async def set_pack_kind(call: CallbackQuery, state: FSMContext, l: str) -> None:
    key = _key(call)
    draft = pack_drafts.get(key)
    if not draft:
        await call.answer(tr(l, "Сессия истекла", "Session expired"), show_alert=True)
        return
    draft.kind = call.data.split(":")[1]
    await call.answer()
    await state.set_state(Flow.pack_emoji)
    await safe_edit(
        call,
        tr(
            l,
            "Шаг 3 из 4. Как выбирать эмодзи для каждого стикера?\n\n"
            "Вручную: присылаешь эмодзи после каждого медиа.\n"
            "Рандом: бот выбирает случайный, без повторов в паке.\n"
            "Умный: бот смотрит на картинку, лица и цвета, и подбирает сам.",
            "Step 3 of 4. How should each sticker get its emoji?\n\n"
            "Manual: you send the emoji after every media file.\n"
            "Random: the bot picks one, never repeating inside the pack.\n"
            "Smart: the bot reads faces and colours and picks for you.",
        ),
        emoji_mode_keyboard(l),
    )


@router.callback_query(Flow.pack_emoji, F.data.startswith("emode:"))
async def set_pack_emoji(call: CallbackQuery, state: FSMContext, l: str) -> None:
    key = _key(call)
    draft = pack_drafts.get(key)
    if not draft:
        await call.answer(tr(l, "Сессия истекла", "Session expired"), show_alert=True)
        return
    draft.emoji_mode = call.data.split(":")[1]
    await call.answer()
    await state.set_state(Flow.pack_crop)
    await safe_edit(
        call,
        tr(
            l,
            "Шаг 4 из 4. Как вписывать медиа в квадрат 512×512?\n\n"
            "Кроп по центру: заполняет стикер, края обрезаются.\n"
            "Вписать целиком: видно всё, по краям поля.\n"
            "Умный: находит лицо и центрирует на нём.",
            "Step 4 of 4. How should media fill the 512×512 square?\n\n"
            "Center crop: fills the sticker, edges are cut.\n"
            "Fit whole: everything visible, with margins.\n"
            "Smart: finds a face and centres on it.",
        ),
        crop_keyboard(l),
    )


@router.callback_query(Flow.pack_crop, F.data.startswith("crop:"))
async def set_pack_crop(call: CallbackQuery, state: FSMContext, l: str) -> None:
    key = _key(call)
    draft = pack_drafts.get(key)
    if not draft:
        await call.answer(tr(l, "Сессия истекла", "Session expired"), show_alert=True)
        return
    draft.crop_mode = call.data.split(":")[1]
    await call.answer(tr(l, "Готово", "Done"))

    await state.set_state(Flow.pack_media)
    await state.update_data(step="await_media", pack_id=None)

    hint = tr(
        l,
        "видео, гиф или ссылку на видео" if draft.kind == "video" else "фото, стикер или прямую ссылку",
        "a video, GIF or video link" if draft.kind == "video" else "a photo, sticker or direct link",
    )
    await safe_edit(
        call,
        tr(
            l,
            f"Пак «{draft.title}» настроен.\n\nПришли первое {hint}. Сделаю первый стикер.",
            f"Pack “{draft.title}” is ready.\n\nSend the first {hint} and I will build the first sticker.",
        ),
        None,
    )


# ------------------------------------------------------- приём медиа в пак

@router.callback_query(F.data.regexp(r"^pk:\d+:add$"))
async def add_to_pack(call: CallbackQuery, state: FSMContext, l: str) -> None:
    pack_id = int(call.data.split(":")[1])
    pack = await db.get_pack(pack_id)
    if not pack or int(pack["tg_id"]) != call.from_user.id:
        await call.answer(tr(l, "Пак не найден", "Pack not found"), show_alert=True)
        return

    count = await db.pack_sticker_count(pack_id)
    if count >= PACK_MAX_STICKERS:
        await call.answer(
            tr(l, f"Максимум {PACK_MAX_STICKERS} стикеров", f"Maximum {PACK_MAX_STICKERS} stickers"),
            show_alert=True,
        )
        return

    await call.answer()
    await state.set_state(Flow.pack_media)
    await state.update_data(step="await_media", pack_id=pack_id)
    hint = tr(
        l,
        "видео, гиф или ссылку на видео" if pack["kind"] == "video" else "фото, стикер или прямую ссылку",
        "a video, GIF or video link" if pack["kind"] == "video" else "a photo, sticker or direct link",
    )
    await safe_edit(
        call,
        tr(
            l,
            f"<b>{pack['title']}</b>, {count} из {PACK_MAX_STICKERS}\n\n"
            f"Пришли {hint}. Можно несколько сообщений подряд, каждое станет стикером.",
            f"<b>{pack['title']}</b>, {count} of {PACK_MAX_STICKERS}\n\n"
            f"Send {hint}. Multiple messages in a row are fine, each becomes a sticker.",
        ),
        None,
    )


@router.message(Flow.pack_media, F.photo | F.video | F.animation | F.sticker | F.document | F.video_note)
async def pack_media_message(message: Message, state: FSMContext, bot: Bot, l: str) -> None:
    key = _key(message)
    data = await state.get_data()
    pack_id = data.get("pack_id")
    pack = await db.get_pack(int(pack_id)) if pack_id else None
    draft = pack_drafts.get(key)

    if not pack and not draft:
        await message.answer(tr(l, "Начни с /newpack или выбери пак в /packs.", "Start with /newpack or pick a pack in /packs."))
        return

    workdir = temp_dir()
    status = await message.answer(tr(l, "Разбираю медиа.", "Reading the media."))
    try:
        job = await intake.build_from_message(bot, message, workdir)
    except intake.IntakeError as exc:
        cleanup_dir(workdir)
        await status.edit_text(str(exc))
        return
    except Exception:
        cleanup_dir(workdir)
        await status.edit_text(tr(l, "Не смог обработать это медиа.", "Could not process this media."))
        return

    try:
        await status.delete()
    except TelegramBadRequest:
        pass

    expected_kind = pack["kind"] if pack else (draft.kind if draft else "static")
    if job.kind == "video" and expected_kind == "static":
        job.kind = "static"
        job.is_frame = True
        await message.answer(
            tr(l, "Это фото-пак, возьму кадр из видео.", "This is a photo pack, I will take a frame.")
        )
    elif job.kind == "static" and expected_kind == "video":
        cleanup_dir(workdir)
        await message.answer(
            tr(
                l,
                "Это видео-пак, а пришло фото. Пришли видео или гиф до 20 МБ "
                "либо создай фото-пак отдельно.",
                "This is a video pack and a photo arrived. Send a video or GIF under 20 MB, "
                "or create a separate photo pack.",
            )
        )
        return

    job.emoji = None
    pending_stickers[key] = job

    if job.kind == "video" and job.video_duration > 3.2:
        await state.update_data(step="trim", pack_id=pack["id"] if pack else None)
        await _send_trim_ui(bot, message.chat.id, job, lang=l)
        return

    await start_emoji_step(bot, message.chat.id, message.from_user.id, state, job, pack, draft, l)


@router.message(Flow.pack_media, F.text)
async def pack_media_text(message: Message, state: FSMContext, bot: Bot, l: str) -> None:
    key = _key(message)
    url = pick_url(message.text)
    if not url:
        data = await state.get_data()
        if data.get("step") == "choose_pack":
            await message.answer(tr(l, "Выбери пак кнопкой выше.", "Pick a pack with the button above."))
            return
        await message.answer(
            tr(
                l,
                "Жду медиа: фото, видео, гиф, стикер или прямую ссылку на файл.",
                "Waiting for media: a photo, video, GIF, sticker or direct file link.",
            )
        )
        return

    data = await state.get_data()
    pack_id = data.get("pack_id")
    pack = await db.get_pack(int(pack_id)) if pack_id else None
    draft = pack_drafts.get(key)

    sticker_name = downloader.is_sticker_link(url)
    if sticker_name:
        await prepare_import(message, state, sticker_name, l)
        return

    status = await message.answer(tr(l, "Забираю файл по ссылке.", "Fetching the file."))
    workdir = temp_dir()
    try:
        if downloader.direct_kind(url):
            job = await intake.build_from_url(url, workdir)
        else:
            job = await intake.build_from_ytdlp(url, workdir)
    except (intake.IntakeError, downloader.DownloadFailed) as exc:
        cleanup_dir(workdir)
        await status.edit_text(str(exc))
        return
    except Exception:
        cleanup_dir(workdir)
        await status.edit_text(tr(l, "Не получилось скачать файл.", "Failed to download the file."))
        return

    try:
        await status.delete()
    except TelegramBadRequest:
        pass

    expected_kind = pack["kind"] if pack else (draft.kind if draft else "static")
    if job.kind == "video" and expected_kind == "static":
        job.kind = "static"
        job.is_frame = True
        await message.answer(
            tr(l, "Это фото-пак, возьму кадр из видео.", "This is a photo pack, I will take a frame.")
        )

    pending_stickers[key] = job
    if job.kind == "video" and job.video_duration > 3.2:
        await state.update_data(step="trim", pack_id=pack["id"] if pack else None)
        await _send_trim_ui(bot, message.chat.id, job, lang=l)
        return

    await start_emoji_step(bot, message.chat.id, message.from_user.id, state, job, pack, draft, l)


async def _send_trim_ui(
    bot: Bot,
    chat_id: int,
    job: StickerJob,
    lang: str,
    old_message_id: int | None = None,
) -> None:
    if job.raw_path and job.temp_dir:
        preview = job.temp_dir / "trim.jpg"
        try:
            await ffmpeg_tools.extract_frame(job.raw_path, preview, job.start + 0.05)
            job.preview = preview
        except Exception:
            pass

    end = min(job.start + 3.0, job.video_duration or job.start + 3.0)
    caption = tr(
        lang,
        "<b>Нарезка видео</b>\n\n"
        f"Начало: <b>{job.start:.1f} с</b>. Конец: <b>{end:.1f} с</b>\n"
        f"Всего в видео: {human_duration(job.video_duration)}\n\n"
        "В стикер попадёт ровно 3 секунды, или меньше, если ролик короче. "
        "Кнопка «Кадр из видео» превращает ролик в обычный фото-стикер.",
        "<b>Video trim</b>\n\n"
        f"Start: <b>{job.start:.1f} s</b>. End: <b>{end:.1f} s</b>\n"
        f"Video length: {human_duration(job.video_duration)}\n\n"
        "The sticker takes exactly 3 seconds, or less if the clip is shorter. "
        "“Frame from video” turns the clip into a regular photo sticker.",
    )

    if old_message_id:
        try:
            await bot.delete_message(chat_id, old_message_id)
        except Exception:
            pass

    if job.preview and job.preview.exists():
        await bot.send_photo(
            chat_id,
            FSInputFile(job.preview, filename="trim.jpg"),
            caption=caption,
            reply_markup=trim_keyboard(lang),
        )
    else:
        await bot.send_message(chat_id, caption, reply_markup=trim_keyboard(lang))


@router.callback_query(Flow.pack_media, F.data.startswith("tr:"))
async def trim_actions(call: CallbackQuery, state: FSMContext, bot: Bot, l: str) -> None:
    key = _key(call)
    job = pending_stickers.get(key)
    if not job:
        await call.answer(tr(l, "Заготовка устарела", "Draft expired"), show_alert=True)
        return

    action = call.data.split(":")[1]
    data = await state.get_data()
    pack_id = data.get("pack_id")
    pack = await db.get_pack(int(pack_id)) if pack_id else None
    draft = pack_drafts.get(key)

    if action == "cancel":
        job.cleanup()
        pending_stickers.pop(key, None)
        await state.clear()
        await call.answer(tr(l, "Отменено", "Cancelled"))
        await safe_edit(
            call,
            tr(l, "Отменено. Что дальше?", "Cancelled. What next?"),
            packs_list_keyboard(await db.user_packs(call.from_user.id), l),
        )
        return

    if action == "left":
        job.start = max(0.0, job.start - 0.5)
    elif action == "right":
        job.start = min(max(0.0, (job.video_duration or 0) - 0.5), job.start + 0.5)
    elif action == "frame":
        job.kind = "static"
        job.is_frame = True
        await call.answer(tr(l, "Беру кадр", "Taking the frame"))
        try:
            await call.message.delete()
        except Exception:
            pass
        await start_emoji_step(bot, call.message.chat.id, call.from_user.id, state, job, pack, draft, l)
        return
    elif action == "ok":
        await call.answer()
        try:
            await call.message.delete()
        except Exception:
            pass
        await start_emoji_step(bot, call.message.chat.id, call.from_user.id, state, job, pack, draft, l)
        return

    await call.answer(f"{job.start:.1f} s")
    await _send_trim_ui(
        bot, call.message.chat.id, job, l, old_message_id=call.message.message_id
    )


# ------------------------------------------------------------- выбор эмодзи

@router.callback_query(Flow.sticker_emoji, F.data.startswith("ep:"))
async def pick_emoji(call: CallbackQuery, state: FSMContext, bot: Bot, l: str) -> None:
    key = _key(call)
    value = call.data[3:]
    job = pending_stickers.get(key)
    if not job:
        await call.answer(tr(l, "Заготовка устарела", "Draft expired"), show_alert=True)
        return

    if value == "__cancel__":
        job.cleanup()
        pending_stickers.pop(key, None)
        await state.clear()
        await call.answer(tr(l, "Отменено", "Cancelled"))
        await safe_edit(call, tr(l, "Отменено. Стикер не добавлен.", "Cancelled. Sticker not added."), None)
        return

    data = await state.get_data()
    pack_id = data.get("pack_id")
    pack = await db.get_pack(int(pack_id)) if pack_id else None
    draft = pack_drafts.get(key)
    used = await db.pack_used_emoji(int(pack_id)) if pack_id else set()

    if value == "__random__":
        value = emoji_service.random_emoji(used)
    elif not emoji_service.is_emoji(value):
        await call.answer(tr(l, "Это не эмодзи", "That is not an emoji"), show_alert=True)
        return

    await call.answer(f"{value}")
    await _add_sticker(call, state, bot, job, pack, draft, value, l)


@router.message(Flow.sticker_emoji, F.text)
async def typed_emoji(message: Message, state: FSMContext, bot: Bot, l: str) -> None:
    key = _key(message)
    value = emoji_service.normalize_emoji(message.text)
    if not emoji_service.is_emoji(value):
        await message.answer(
            tr(
                l,
                "Это не похоже на эмодзи. Пришли один или несколько эмодзи.",
                "That does not look like an emoji. Send one or more emoji.",
            )
        )
        return

    job = pending_stickers.get(key)
    if not job:
        await message.answer(tr(l, "Заготовка устарела, пришли медиа заново.", "Draft expired, send the media again."))
        return

    data = await state.get_data()
    pack_id = data.get("pack_id")
    pack = await db.get_pack(int(pack_id)) if pack_id else None
    draft = pack_drafts.get(key)
    await _add_sticker(message, state, bot, job, pack, draft, value, l)


@router.callback_query(Flow.pack_media, F.data.startswith("ec:"))
async def emoji_confirm(call: CallbackQuery, state: FSMContext, bot: Bot, l: str) -> None:
    key = _key(call)
    action = call.data.split(":")[1]
    job = pending_stickers.get(key)
    if not job:
        await call.answer(tr(l, "Заготовка устарела", "Draft expired"), show_alert=True)
        return

    data = await state.get_data()
    pack_id = data.get("pack_id")
    pack = await db.get_pack(int(pack_id)) if pack_id else None
    draft = pack_drafts.get(key)

    if action == "cancel":
        job.cleanup()
        pending_stickers.pop(key, None)
        await state.clear()
        await call.answer(tr(l, "Отменено", "Cancelled"))
        await safe_edit(call, tr(l, "Отменено. Стикер не добавлен.", "Cancelled. Sticker not added."), None)
        return

    if action == "again":
        used = await db.pack_used_emoji(int(pack_id)) if pack_id else set()
        mode = (pack or {}).get("emoji_mode") or (draft.emoji_mode if draft else "random")
        value = (
            emoji_service.smart_emoji(job.preview or job.path, used)
            if mode == "smart"
            else emoji_service.random_emoji(used)
        )
        job.emoji = value
        await call.answer(f"{value}")
        try:
            await call.message.edit_caption(
                caption=tr(l, f"Эмодзи: <b>{value}</b>", f"Emoji: <b>{value}</b>"),
                reply_markup=emoji_confirm_keyboard(value, l),
            )
        except TelegramBadRequest:
            pass
        return

    await call.answer()
    await _add_sticker(call, state, bot, job, pack, draft, job.emoji or "🎲", l)


async def _add_sticker(
    event: Message | CallbackQuery,
    state: FSMContext,
    bot: Bot,
    job: StickerJob,
    pack: dict | None,
    draft: PackDraft | None,
    emoji_value: str,
    lang: str,
) -> None:
    chat_id = event.chat.id if isinstance(event, Message) else event.message.chat.id
    user_id = event.from_user.id

    status = await bot.send_message(
        chat_id,
        tr(lang, "Собираю стикер: режу, жму, перекодирую.", "Building the sticker: trim, scale, encode."),
    )
    try:
        result = await finalize_job(bot, chat_id, user_id, job, pack, draft, emoji_value)
    except TelegramBadRequest as exc:
        await status.edit_text(
            tr(
                lang,
                "Telegram отклонил стикер.\n\n"
                f"<code>{str(exc)[:300]}</code>\n\n"
                "Обычно это размер, битый файл или лимит пака.",
                "Telegram rejected the sticker.\n\n"
                f"<code>{str(exc)[:300]}</code>\n\n"
                "Usually it is size, a broken file or the pack limit.",
            )
        )
        return
    except Exception as exc:  # noqa: BLE001
        await status.edit_text(tr(lang, "Ошибка: ", "Error: ") + str(exc)[:300])
        return

    await state.set_state(Flow.pack_media)
    await state.update_data(step="await_media", pack_id=result["pack_id"])

    if result["file_id"]:
        try:
            await bot.send_sticker(chat_id, result["file_id"])
        except Exception:
            pass

    link = f"https://t.me/addstickers/{result['name']}"
    if result["is_new"]:
        text = tr(
            lang,
            f"Пак «{result['title']}» создан.\n\n"
            f"Стикер 1 из {PACK_MAX_STICKERS}. Эмодзи {emoji_value}\n"
            f'<a href="{link}">{link}</a>\n\n'
            "Присылай ещё медиа или открой пак в /packs.",
            f"Pack “{result['title']}” is created.\n\n"
            f"Sticker 1 of {PACK_MAX_STICKERS}. Emoji {emoji_value}\n"
            f'<a href="{link}">{link}</a>\n\n'
            "Send more media or open the pack in /packs.",
        )
    else:
        text = tr(
            lang,
            f"Добавлено в «{result['title']}».\n\n"
            f"Стикер {result['count']} из {PACK_MAX_STICKERS}. Эмодзи {emoji_value}\n\n"
            "Можно присылать следующее медиа.",
            f"Added to “{result['title']}”.\n\n"
            f"Sticker {result['count']} of {PACK_MAX_STICKERS}. Emoji {emoji_value}\n\n"
            "Send the next media file whenever you are ready.",
        )

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Открыть пак", "Open pack"), callback_data=f"pk:{result['pack_id']}:open"
        ),
        InlineKeyboardButton(text=tr(lang, "В меню", "Back to menu"), callback_data="m:home"),
    )
    try:
        await status.edit_text(text, reply_markup=builder.as_markup())
    except TelegramBadRequest:
        await bot.send_message(chat_id, text, reply_markup=builder.as_markup())


# ------------------------------------------------------------ управление паком

@router.callback_query(F.data.regexp(r"^pk:\d+:[a-z]+$"))
async def pack_actions(call: CallbackQuery, state: FSMContext, bot: Bot, l: str) -> None:
    _, raw_id, action = call.data.split(":")
    pack_id = int(raw_id)
    pack = await db.get_pack(pack_id)
    if not pack or int(pack["tg_id"]) != call.from_user.id:
        await call.answer(tr(l, "Пак не найден", "Pack not found"), show_alert=True)
        return

    if action == "attach":
        await call.answer()
        if await attach_job_to_pack(bot, call.message.chat.id, call.from_user.id, state, pack_id, l):
            try:
                await call.message.delete()
            except Exception:
                pass
        return

    if action == "open":
        await call.answer()
        count = await db.pack_sticker_count(pack_id)
        stickers = await db.pack_stickers(pack_id)
        sample = next((s for s in reversed(stickers) if s.get("file_id")), None)
        if sample:
            try:
                await bot.send_sticker(call.message.chat.id, sample["file_id"])
            except Exception:
                pass
        await safe_edit(call, _pack_text(pack, count, l), pack_view_keyboard(pack, l))
        return

    if action == "dellast":
        await call.answer(tr(l, "Удаляю", "Deleting"))
        try:
            removed = await packs.delete_last_sticker(bot, pack_id)
        except Exception:
            removed = False
        count = await db.pack_sticker_count(pack_id)
        suffix = (
            tr(l, "\n\nПоследний стикер удалён.", "\n\nThe last sticker is deleted.")
            if removed
            else tr(l, "\n\nВ паке нечего удалять.", "\n\nThere is nothing to delete.")
        )
        await safe_edit(call, _pack_text(pack, count, l) + suffix, pack_view_keyboard(pack, l))
        return

    if action == "zip":
        await call.answer(tr(l, "Собираю архив", "Building the archive"))
        stickers = await packs.get_set_stickers(bot, pack["name"])
        if not stickers:
            await call.answer(tr(l, "В паке нет стикеров", "The pack is empty"), show_alert=True)
            return
        status = await bot.send_message(
            call.message.chat.id,
            tr(l, f"Скачиваю {len(stickers)} стикеров.", f"Downloading {len(stickers)} stickers."),
        )
        try:
            result = await packs.export_zip(bot, pack["name"])
        except Exception:
            result = None
        if not result:
            await status.edit_text(tr(l, "Не получилось собрать архив.", "Could not build the archive."))
            return
        data, filename = result
        if len(data) > 49 * 1024 * 1024:
            await status.edit_text(
                tr(l, "Архив больше 50 МБ, Telegram не пропустит.", "The archive is over 50 MB, Telegram will refuse it.")
            )
            return
        await status.delete()
        from aiogram.types import BufferedInputFile

        await bot.send_document(
            call.message.chat.id,
            BufferedInputFile(data, filename=filename),
            caption=tr(
                l,
                f"{pack['title']}, {len(stickers)} стикеров",
                f"{pack['title']}, {len(stickers)} stickers",
            ),
        )
        return

    if action == "cover":
        await call.answer(tr(l, "Рисую обложку", "Drawing the cover"))
        try:
            await packs.set_cover(bot, pack["name"], pack["title"])
        except Exception:
            await call.answer(tr(l, "Не смог обновить обложку", "Could not update the cover"), show_alert=True)
            return
        count = await db.pack_sticker_count(pack_id)
        await safe_edit(
            call,
            _pack_text(pack, count, l)
            + tr(l, "\n\nОбложка обновлена.", "\n\nCover updated."),
            pack_view_keyboard(pack, l),
        )
        return

    if action == "link":
        link = f"https://t.me/addstickers/{pack['name']}"
        await call.answer()
        await bot.send_message(
            call.message.chat.id,
            f"<b>{pack['title']}</b>\n<code>{link}</code>",
        )
        return

    if action == "delete":
        await call.answer()
        await safe_edit(
            call,
            tr(
                l,
                f"Удалить пак «{pack['title']}»?\n\n"
                "Стикеры исчезнут у всех, кто его добавил. Отменить нельзя.",
                f"Delete the pack “{pack['title']}”?\n\n"
                "The stickers disappear for everyone who added it. This cannot be undone.",
            ),
            confirm_delete_keyboard(pack_id, l),
        )
        return

    if action == "confirmdelete":
        await call.answer()
        try:
            await bot.delete_sticker_set(pack["name"])
        except Exception:
            pass
        await db.delete_pack(pack_id)
        await safe_edit(
            call,
            tr(l, f"Пак «{pack['title']}» удалён.", f"Pack “{pack['title']}” deleted."),
            packs_list_keyboard(await db.user_packs(call.from_user.id), l),
        )
        return

    await call.answer()


# ----------------------------------------------------------------- импорт

async def prepare_import(message: Message, state: FSMContext, source_name: str, lang: str) -> None:
    key = _key(message)
    try:
        sticker_set = await message.bot.get_sticker_set(source_name)
    except TelegramBadRequest:
        await message.answer(tr(lang, "Такой пак не найден.", "That pack was not found."))
        return

    if sticker_set.stickers and all(s.is_animated for s in sticker_set.stickers):
        await message.answer(
            tr(
                lang,
                "Это анимированный пак в формате Lottie. Telegram не даёт ботам пересобирать такие. "
                "Фото- и видео-паки переношу без проблем.",
                "This is an animated Lottie pack. Telegram does not let bots rebuild those. "
                "Photo and video packs import without trouble.",
            )
        )
        return

    kind = "video" if any(s.is_video for s in sticker_set.stickers) else "static"
    import_drafts[key] = ImportDraft(
        name=source_name,
        title=sticker_set.title,
        kind=kind,
        total=len(sticker_set.stickers),
    )
    await state.set_state(Flow.import_confirm)

    caption = tr(
        lang,
        f"<b>{sticker_set.title}</b>\n\n"
        f"Стикеров: <b>{len(sticker_set.stickers)}</b>. "
        f"Тип: {'видео' if kind == 'video' else 'фото'}\n\n"
        "Сделаю личную копию со всеми эмодзи. Оригинал не тронется.",
        f"<b>{sticker_set.title}</b>\n\n"
        f"Stickers: <b>{len(sticker_set.stickers)}</b>. "
        f"Type: {'video' if kind == 'video' else 'photo'}\n\n"
        "I will build a private copy with every emoji. The original stays untouched.",
    )
    if sticker_set.stickers:
        try:
            await message.answer_sticker(sticker_set.stickers[0].file_id)
        except Exception:
            pass
    await message.answer(caption, reply_markup=import_preview_keyboard(lang))


@router.message(Command("import"))
async def cmd_import(message: Message, state: FSMContext, l: str) -> None:
    parts = (message.text or "").split(maxsplit=1)
    value = parts[1].strip() if len(parts) > 1 else ""
    name = downloader.is_sticker_link(value) or (value if value and "/" not in value else None)
    if name:
        await prepare_import(message, state, name, l)
        return
    await state.set_state(Flow.import_confirm)
    await message.answer(
        tr(
            l,
            "Пришли ссылку на пак, например <code>https://t.me/addstickers/Cats</code>. "
            "Сделаю копию с теми же эмодзи.",
            "Send a pack link, for example <code>https://t.me/addstickers/Cats</code>. "
            "I will copy it with the same emoji.",
        )
    )


@router.callback_query(F.data == "m:import")
async def cb_import(call: CallbackQuery, state: FSMContext, l: str) -> None:
    await call.answer()
    await state.set_state(Flow.import_confirm)
    await safe_edit(
        call,
        tr(
            l,
            "Пришли ссылку на пак: <code>https://t.me/addstickers/…</code>",
            "Send a pack link: <code>https://t.me/addstickers/…</code>",
        ),
        None,
    )


@router.message(Flow.import_confirm, F.text)
async def import_link(message: Message, state: FSMContext, l: str) -> None:
    value = pick_url(message.text) or message.text.strip()
    name = downloader.is_sticker_link(value) or (
        value if " " not in value and "/" not in value else None
    )
    if not name:
        await message.answer(
            tr(
                l,
                "Это не похоже на ссылку на пак. Пример: https://t.me/addstickers/Cats",
                "That does not look like a pack link. Example: https://t.me/addstickers/Cats",
            )
        )
        return
    await prepare_import(message, state, name, l)


@router.callback_query(F.data == "imp:go")
async def do_import(call: CallbackQuery, state: FSMContext, bot: Bot, u: dict, l: str) -> None:
    key = _key(call)
    draft = import_drafts.get(key)
    if not draft:
        await call.answer(tr(l, "Ссылка устарела", "Link expired"), show_alert=True)
        return

    await call.answer()
    status = await bot.send_message(
        call.message.chat.id,
        tr(l, f"Переношу «{draft.title}»: 0 из {draft.total}", f"Importing “{draft.title}”: 0 of {draft.total}"),
    )

    async def progress(done: int, total: int) -> None:
        try:
            await status.edit_text(
                tr(l, f"Переношу «{draft.title}»: {done} из {total}", f"Importing “{draft.title}”: {done} of {total}")
            )
        except Exception:
            pass

    try:
        result = await packs.import_sticker_set(
            bot,
            call.from_user.id,
            draft.name,
            f"{draft.title} · copy"[:64],
            u["settings"].get("emoji_mode", "random"),
            u["settings"].get("crop_mode", "crop"),
            on_progress=progress,
        )
    except Exception as exc:  # noqa: BLE001
        await status.edit_text(tr(l, "Импорт не удался: ", "Import failed: ") + str(exc)[:250])
        return

    import_drafts.pop(key, None)
    await state.clear()
    link = f"https://t.me/addstickers/{result['name']}"
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=tr(l, "Открыть пак", "Open pack"), callback_data=f"pk:{result['pack_id']}:open"
        ),
        InlineKeyboardButton(text=tr(l, "В меню", "Back to menu"), callback_data="m:home"),
    )
    await status.edit_text(
        tr(
            l,
            f"<b>Копия готова.</b>\n\n"
            f"Перенесено: <b>{result['added']}</b> из {result['total']}\n"
            f'<a href="{link}">{link}</a>',
            f"<b>The copy is ready.</b>\n\n"
            f"Imported: <b>{result['added']}</b> of {result['total']}\n"
            f'<a href="{link}">{link}</a>',
        ),
        reply_markup=builder.as_markup(),
    )
