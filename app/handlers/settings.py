"""Настройки пользователя: язык, эмодзи, кадрирование, сжатие."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import database as db
from app.handlers.common import safe_edit
from app.i18n import tr
from app.keyboards import settings_keyboard
from app.texts import limits

router = Router(name="settings")

CYCLE_EMOJI = {"manual": "random", "random": "smart", "smart": "manual"}
CYCLE_CROP = {"crop": "fit", "fit": "smart", "smart": "crop"}
CYCLE_LANG = {"ru": "en", "en": "ru"}


def _text(settings: dict, lang: str) -> str:
    emoji = {
        "manual": tr(lang, "вручную", "manual"),
        "random": tr(lang, "рандом", "random"),
        "smart": tr(lang, "умный", "smart"),
    }.get(settings.get("emoji_mode", "manual"), tr(lang, "вручную", "manual"))
    crop = {
        "crop": tr(lang, "по центру", "center"),
        "fit": tr(lang, "вписать", "fit"),
        "smart": tr(lang, "умный", "smart"),
    }.get(settings.get("crop_mode", "crop"), tr(lang, "по центру", "center"))
    auto = tr(lang, "включено", "on") if settings.get("autocompress") else tr(lang, "выключено", "off")
    language = "Русский" if lang == "ru" else "English"

    return tr(
        lang,
        "<b>Настройки</b>\n\n"
        f"Язык: <b>{language}</b>\n"
        f"Эмодзи для новых паков: <b>{emoji}</b>\n"
        f"Кадрирование стикеров: <b>{crop}</b>\n"
        f"Автосжатие больших видео: <b>{auto}</b>\n\n"
        f"{limits(lang)}",
        "<b>Settings</b>\n\n"
        f"Language: <b>{language}</b>\n"
        f"Emoji for new packs: <b>{emoji}</b>\n"
        f"Sticker crop: <b>{crop}</b>\n"
        f"Auto-compress large videos: <b>{auto}</b>\n\n"
        f"{limits(lang)}",
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message, u: dict, l: str) -> None:
    await message.answer(_text(u["settings"], l), reply_markup=settings_keyboard(u["settings"], l))


@router.callback_query(F.data == "m:settings")
async def cb_settings(call: CallbackQuery, u: dict, l: str) -> None:
    await call.answer()
    await safe_edit(call, _text(u["settings"], l), settings_keyboard(u["settings"], l))


@router.callback_query(F.data.startswith("st:"))
async def cb_toggle(call: CallbackQuery, u: dict, state: FSMContext, l: str) -> None:
    action = call.data.split(":", 1)[1]
    settings = u["settings"]
    changes: dict = {}
    new_lang = l

    if action == "auto":
        changes["autocompress"] = not settings.get("autocompress", True)
    elif action == "silent":
        changes["silent"] = not settings.get("silent", False)
    elif action == "emoji":
        changes["emoji_mode"] = CYCLE_EMOJI.get(settings.get("emoji_mode", "manual"), "manual")
    elif action == "crop":
        changes["crop_mode"] = CYCLE_CROP.get(settings.get("crop_mode", "crop"), "crop")
    elif action == "lang":
        new_lang = CYCLE_LANG.get(l, "ru")
        changes["lang"] = new_lang
    else:
        await call.answer()
        return

    updated = await db.update_settings(call.from_user.id, **changes)
    u["settings"] = updated["settings"]
    await call.answer(tr(new_lang, "Сохранено", "Saved"))
    await safe_edit(call, _text(u["settings"], new_lang), settings_keyboard(u["settings"], new_lang))
