"""Старт, меню, помощь, история, отмена."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, LinkPreviewOptions, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import database as db
from app.config import settings
from app.handlers.common import safe_edit
from app.i18n import tr
from app.keyboards import back_menu, main_menu
from app.services import session
from app.services.session import inline_urls
from app.services.utils import short
from app.texts import download_intro, help_text, welcome

router = Router(name="start")

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    l: str,
    bot: Bot,
    command: CommandObject | None = None,
) -> None:
    await state.clear()
    payload = (command.args or "").strip() if command else ""

    if payload.startswith("u_"):
        item = inline_urls.get(payload[2:])
        if item:
            from app.handlers.download import start_from_url

            await start_from_url(
                bot, message.chat.id, message.from_user.id, item["url"], l, 720
            )
            return

    if payload == "app_studio":
        from app.handlers.pack import _begin_new_pack

        await _begin_new_pack(message, state, l)
        return

    await message.answer(
        welcome(l),
        reply_markup=main_menu(l, settings.webapp_url or None),
        link_preview_options=NO_PREVIEW,
    )


@router.message(Command("help"))
async def cmd_help(message: Message, l: str) -> None:
    await message.answer(
        help_text(l),
        reply_markup=back_menu(l),
        link_preview_options=NO_PREVIEW,
    )


@router.callback_query(F.data == "m:home")
async def menu_home(call: CallbackQuery, state: FSMContext, l: str) -> None:
    await state.clear()
    await call.answer()
    await safe_edit(call, welcome(l), main_menu(l, settings.webapp_url or None))


@router.callback_query(F.data == "m:help")
async def menu_help(call: CallbackQuery, l: str) -> None:
    await call.answer()
    await safe_edit(call, help_text(l), back_menu(l))


@router.callback_query(F.data == "m:dl")
async def menu_download(call: CallbackQuery, l: str) -> None:
    await call.answer()
    await safe_edit(call, download_intro(l), back_menu(l))


@router.message(Command("history"))
@router.callback_query(F.data == "m:history")
async def show_history(event: Message | CallbackQuery, l: str) -> None:
    is_call = isinstance(event, CallbackQuery)
    if is_call:
        await event.answer()

    items = await db.recent_downloads(event.from_user.id, limit=10)
    if not items:
        text = tr(l, "История пуста. Скачай что-нибудь.", "History is empty. Download something first.")
        keyboard = back_menu(l)
    else:
        lines = [tr(l, "<b>Последние загрузки</b>", "<b>Recent downloads</b>"), ""]
        builder = InlineKeyboardBuilder()
        for index, item in enumerate(items, start=1):
            labels = {
                "video": tr(l, "видео", "video"),
                "audio": tr(l, "аудио", "audio"),
                "image": tr(l, "фото", "photo"),
                "zip": "ZIP",
            }
            label = labels.get(item.get("kind") or "", tr(l, "файл", "file"))
            title = short(item.get("title") or item.get("url") or "—", 46)
            lines.append(f"{index}. {title} — {label}")
            if item.get("file_id"):
                builder.button(text=f"{index}", callback_data=f"hd:{item['id']}")
        builder.row(
            InlineKeyboardButton(text=tr(l, "В меню", "Back to menu"), callback_data="m:home")
        )
        text = "\n".join(lines) + "\n\n" + tr(
            l,
            "Нажми на номер, чтобы получить файл снова.",
            "Tap a number to receive the file again.",
        )
        keyboard = builder.as_markup()

    if is_call:
        await safe_edit(event, text, keyboard)
    else:
        await event.answer(text, reply_markup=keyboard, link_preview_options=NO_PREVIEW)


@router.callback_query(F.data.startswith("hd:"))
async def resend_from_history(call: CallbackQuery, bot: Bot, l: str) -> None:
    try:
        dl_id = int(call.data.split(":")[1])
    except (IndexError, ValueError):
        await call.answer()
        return

    item = await db.get_download(dl_id, call.from_user.id)
    if not item or not item.get("file_id"):
        await call.answer(tr(l, "Файл недоступен", "File is gone"), show_alert=True)
        return

    await call.answer()
    kind = item.get("kind")
    caption = short(item.get("title") or "", 900)
    try:
        if kind == "audio":
            await bot.send_audio(call.message.chat.id, item["file_id"], caption=caption)
        elif kind == "image":
            await bot.send_photo(call.message.chat.id, item["file_id"], caption=caption)
        else:
            await bot.send_video(
                call.message.chat.id, item["file_id"], caption=caption, supports_streaming=True
            )
    except Exception:
        try:
            await bot.send_document(call.message.chat.id, item["file_id"], caption=caption)
        except Exception:
            await call.answer(
                tr(l, "Telegram не отдал файл", "Telegram refused the file"), show_alert=True
            )


@router.message(Command("stats"))
async def cmd_stats(message: Message, l: str) -> None:
    if settings.admin_ids and message.from_user and message.from_user.id not in settings.admin_ids:
        await message.answer(tr(l, "Команда только для администратора.", "Admins only."))
        return
    users = await db.user_count()
    downloads = await db.downloads_total()
    await message.answer(
        tr(
            l,
            f"<b>Статистика</b>\n\nПользователей: {users}\nСкачиваний: {downloads}",
            f"<b>Statistics</b>\n\nUsers: {users}\nDownloads: {downloads}",
        )
    )


@router.message(Command("cancel"))
@router.callback_query(F.data == "cancel")
async def cmd_cancel(event: Message | CallbackQuery, state: FSMContext, l: str) -> None:
    chat = event.chat if isinstance(event, Message) else event.message.chat
    key = (chat.id, event.from_user.id)
    job = session.pending_stickers.pop(key, None)
    if job:
        job.cleanup()
    session.pack_drafts.pop(key, None)
    await state.clear()

    text = tr(l, "Отменено. Что дальше?", "Cancelled. What next?")
    if isinstance(event, CallbackQuery):
        await event.answer(tr(l, "Отменено", "Cancelled"))
        await safe_edit(event, text, main_menu(l, settings.webapp_url or None))
    else:
        await event.answer(text, reply_markup=main_menu(l, settings.webapp_url or None))
