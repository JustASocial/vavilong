"""Цитаты и текстовые стикеры: рендер картинки и отправка в пак."""

from __future__ import annotations

import asyncio
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InputMediaPhoto,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.handlers.common import offer_pack_choice, safe_edit
from app.i18n import tr
from app.services import ffmpeg_tools, images, intake
from app.services.session import quote_tokens
from app.services.utils import short, temp_dir
from app.states import Flow

router = Router(name="quote")

THEME_ORDER = ("midnight", "graphite", "ocean", "sunset", "forest", "paper")

_avatar_cache: dict[int, bytes | None] = {}


def _theme_keyboard(prefix: str, lang: str):
    builder = InlineKeyboardBuilder()
    for key in THEME_ORDER:
        builder.button(
            text=images.theme_label(key, lang), callback_data=f"{prefix}:{key}"
        )
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(text=tr(lang, "Отмена", "Cancel"), callback_data="m:home")
    )
    return builder.as_markup()


def _quote_actions(token: str, lang: str):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "В стикер", "To sticker"), callback_data=f"qt:sticker:{token}"
        ),
        InlineKeyboardButton(
            text=tr(lang, "Другая тема", "Another theme"), callback_data=f"qt:theme:{token}"
        ),
    )
    builder.row(
        InlineKeyboardButton(text=tr(lang, "В меню", "Back to menu"), callback_data="m:home")
    )
    return builder.as_markup()


def _text_actions(token: str, lang: str):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Другая тема", "Another theme"), callback_data=f"tx:theme:{token}"
        ),
        InlineKeyboardButton(
            text=tr(lang, "В пак", "To pack"), callback_data=f"tx:pack:{token}"
        ),
    )
    builder.row(
        InlineKeyboardButton(text=tr(lang, "В меню", "Back to menu"), callback_data="m:home")
    )
    return builder.as_markup()


async def _avatar(bot: Bot, user_id: int) -> bytes | None:
    if user_id in _avatar_cache:
        return _avatar_cache[user_id]
    data: bytes | None = None
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if photos.photos:
            buffer = await bot.download(photos.photos[0][-1].file_id)
            if buffer is not None:
                data = buffer.read() if hasattr(buffer, "read") else bytes(buffer)
    except Exception:
        data = None
    _avatar_cache[user_id] = data
    return data


def _author_of(message: Message) -> tuple[str, str | None, int | None]:
    user = message.from_user
    if user is None:
        return "—", None, None
    name = " ".join(part for part in (user.first_name, user.last_name) if part) or "—"
    return name, user.username, user.id


# ------------------------------------------------------------------ команды

@router.message(Command("quote"))
async def cmd_quote(
    message: Message, state: FSMContext, command: CommandObject, bot: Bot, l: str
) -> None:
    reply = message.reply_to_message
    if reply is not None:
        text = (reply.text or reply.caption or "").strip()
        if not text:
            await message.answer(
                tr(l, "В сообщении нет текста, цитировать нечего.", "That message has no text to quote.")
            )
            return
        name, username, user_id = _author_of(reply)
        avatar = await _avatar(bot, user_id) if user_id else None
        await state.update_data(
            quote_text=text, quote_author=name, quote_username=username, quote_avatar=bool(avatar)
        )
        await state.update_data(quote_avatar_user=user_id)
        await state.set_state(Flow.quote_theme)
        await message.answer(
            tr(
                l,
                f"<b>Цитата</b>\n\n{short(text, 200)}\n\nВыбери тему карточки.",
                f"<b>Quote</b>\n\n{short(text, 200)}\n\nPick a card theme.",
            ),
            reply_markup=_theme_keyboard("qth", l),
        )
        return

    inline_text = (command.args or "").strip()
    if inline_text:
        name, username, user_id = _author_of(message)
        avatar = await _avatar(bot, user_id) if user_id else None
        await state.update_data(
            quote_text=inline_text,
            quote_author=name,
            quote_username=username,
            quote_avatar=bool(avatar),
            quote_avatar_user=user_id,
        )
        await state.set_state(Flow.quote_theme)
        await message.answer(
            tr(l, "Выбери тему карточки.", "Pick a card theme."),
            reply_markup=_theme_keyboard("qth", l),
        )
        return

    await state.set_state(Flow.quote_text)
    await message.answer(
        tr(
            l,
            "<b>Цитата в стикер</b>\n\n"
            "Ответь командой на сообщение, которое нужно превратить в карточку, "
            "или пришли текст следующим сообщением.",
            "<b>Quote sticker</b>\n\n"
            "Reply to the message you want turned into a card, "
            "or send the text as the next message.",
        )
    )


@router.message(Flow.quote_text, F.text)
async def quote_text(message: Message, state: FSMContext, bot: Bot, l: str) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer(tr(l, "Нужен текст.", "Some text is required."))
        return
    name, username, user_id = _author_of(message)
    avatar = await _avatar(bot, user_id) if user_id else None
    await state.update_data(
        quote_text=text,
        quote_author=name,
        quote_username=username,
        quote_avatar=bool(avatar),
        quote_avatar_user=user_id,
    )
    await state.set_state(Flow.quote_theme)
    await message.answer(
        tr(l, "Выбери тему карточки.", "Pick a card theme."),
        reply_markup=_theme_keyboard("qth", l),
    )


@router.callback_query(Flow.quote_theme, F.data.startswith("qth:"))
async def quote_theme(call: CallbackQuery, state: FSMContext, bot: Bot, l: str) -> None:
    theme = call.data.split(":", 1)[1]
    data = await state.get_data()
    text = data.get("quote_text") or ""
    if not text:
        await call.answer(tr(l, "Текст потерялся", "The text is gone"), show_alert=True)
        return

    await call.answer(tr(l, "Рисую", "Rendering"))
    await state.clear()

    avatar: bytes | None = None
    user_id = data.get("quote_avatar_user")
    if data.get("quote_avatar") and user_id:
        avatar = await _avatar(bot, int(user_id))

    payload = {
        "text": text,
        "author": data.get("quote_author") or "—",
        "username": data.get("quote_username"),
        "theme": theme,
        "avatar_user": user_id if avatar else None,
    }
    image = await asyncio.to_thread(
        images.build_quote,
        text,
        payload["author"],
        payload["username"],
        avatar,
        theme,
        "@vavilong_bot",
        tr(l, "цитата", "quote"),
    )
    workdir = temp_dir()
    path = workdir / "quote.png"
    path.write_bytes(image)
    token = quote_tokens.put({"kind": "quote", **payload, "path": path, "workdir": workdir})

    await bot.send_photo(
        call.message.chat.id,
        BufferedInputFile(image, filename="quote.png"),
        caption=tr(
            l,
            f"Цитата в теме «{images.theme_label(theme, l)}». Можно сразу отправить её в пак.",
            f"Quote in the “{images.theme_label(theme, l)}” theme. You can send it to a pack right away.",
        ),
        reply_markup=_quote_actions(token, l),
    )


@router.callback_query(F.data.startswith("qt:theme:"))
async def quote_change_theme(call: CallbackQuery, l: str) -> None:
    token = call.data.split(":", 2)[2]
    payload = quote_tokens.get(token)
    if not payload:
        await call.answer(tr(l, "Карточка устарела", "The card expired"), show_alert=True)
        return
    await call.answer()
    await safe_edit(
        call,
        tr(l, "Выбери тему карточки.", "Pick a card theme."),
        _theme_keyboard(f"qtt:{token}", l),
    )


@router.callback_query(F.data.startswith("qtt:"))
async def quote_retheme(call: CallbackQuery, bot: Bot, l: str) -> None:
    _, token, theme = call.data.split(":", 2)
    payload = quote_tokens.get(token)
    if not payload:
        await call.answer(tr(l, "Карточка устарела", "The card expired"), show_alert=True)
        return
    await call.answer(tr(l, "Рисую", "Rendering"))

    avatar = None
    if payload.get("avatar_user"):
        avatar = await _avatar(bot, int(payload["avatar_user"]))

    image = await asyncio.to_thread(
        images.build_quote,
        payload["text"],
        payload["author"],
        payload.get("username"),
        avatar,
        theme,
        "@vavilong_bot",
        tr(l, "цитата", "quote"),
    )
    workdir = Path(payload["workdir"])
    path = workdir / f"quote_{theme}.png"
    path.write_bytes(image)
    new_token = quote_tokens.put({"kind": "quote", **payload, "path": path, "workdir": workdir})

    try:
        await call.message.edit_media(
            media=InputMediaPhoto(
                media=BufferedInputFile(image, filename="quote.png"),
                caption=tr(
                    l,
                    f"Цитата в теме «{images.theme_label(theme, l)}».",
                    f"Quote in the “{images.theme_label(theme, l)}” theme.",
                ),
            ),
            reply_markup=_quote_actions(new_token, l),
        )
    except TelegramBadRequest:
        await bot.send_photo(
            call.message.chat.id,
            BufferedInputFile(image, filename="quote.png"),
            caption=tr(
                l,
                f"Цитата в теме «{images.theme_label(theme, l)}».",
                f"Quote in the “{images.theme_label(theme, l)}” theme.",
            ),
            reply_markup=_quote_actions(new_token, l),
        )


@router.callback_query(F.data.startswith("qt:sticker:"))
async def quote_to_sticker(
    call: CallbackQuery, bot: Bot, state: FSMContext, l: str
) -> None:
    token = call.data.split(":", 2)[2]
    payload = quote_tokens.get(token)
    if not payload:
        await call.answer(tr(l, "Карточка устарела", "The card expired"), show_alert=True)
        return

    try:
        job = await intake.build_from_path(
            Path(payload["path"]), Path(payload["workdir"]), source="quote"
        )
    except Exception:
        await call.answer(tr(l, "Не смог открыть карточку", "Could not open the card"), show_alert=True)
        return

    await call.answer()
    await offer_pack_choice(
        bot,
        call.message.chat.id,
        call.from_user.id,
        state,
        job,
        header=tr(l, "Куда добавить цитату?", "Where should the quote go?"),
        lang=l,
    )


# ------------------------------------------------------------ текст-стикер

@router.message(Command("text"))
async def cmd_text(
    message: Message, state: FSMContext, command: CommandObject, l: str
) -> None:
    inline_text = (command.args or "").strip()
    if inline_text:
        await state.update_data(text_value=inline_text)
        await state.set_state(Flow.text_theme)
        await message.answer(
            tr(l, "Выбери фон стикера.", "Pick the sticker background."),
            reply_markup=_theme_keyboard("txth", l),
        )
        return

    await state.set_state(Flow.text_sticker)
    await message.answer(
        tr(
            l,
            "<b>Текст в стикер</b>\n\nПришли текст, до 300 символов. Шрифт подберётся сам.",
            "<b>Text sticker</b>\n\nSend the text, up to 300 characters. The font size adapts.",
        )
    )


@router.message(Flow.text_sticker, F.text)
async def text_value(message: Message, state: FSMContext, l: str) -> None:
    value = (message.text or "").strip()
    if not value:
        await message.answer(tr(l, "Нужен текст.", "Some text is required."))
        return
    await state.update_data(text_value=value[:300])
    await state.set_state(Flow.text_theme)
    await message.answer(
        tr(l, "Выбери фон стикера.", "Pick the sticker background."),
        reply_markup=_theme_keyboard("txth", l),
    )


async def _render_text(text: str, theme: str, workdir: Path) -> tuple[Path, Path, str]:
    raw = await asyncio.to_thread(images.build_text_sticker, text, theme)
    png = workdir / "text.png"
    png.write_bytes(raw)
    sticker = await ffmpeg_tools.photo_to_sticker(png, workdir / "text.webp", "fit")
    return png, sticker, theme


@router.callback_query(Flow.text_theme, F.data.startswith("txth:"))
async def text_theme(call: CallbackQuery, state: FSMContext, bot: Bot, l: str) -> None:
    theme = call.data.split(":", 1)[1]
    data = await state.get_data()
    text = data.get("text_value") or ""
    if not text:
        await call.answer(tr(l, "Текст потерялся", "The text is gone"), show_alert=True)
        return

    await call.answer(tr(l, "Рисую", "Rendering"))
    workdir = temp_dir()
    try:
        png, sticker, _theme = await _render_text(text, theme, workdir)
    except Exception:
        await call.answer(tr(l, "Не смог отрисовать", "Could not render"), show_alert=True)
        return

    token = quote_tokens.put(
        {"kind": "text", "text": text, "theme": theme, "path": str(png), "sticker": str(sticker), "workdir": str(workdir)}
    )
    await state.clear()

    try:
        await bot.send_sticker(
            call.message.chat.id, FSInputFile(sticker, filename="text.webp")
        )
    except TelegramBadRequest:
        await bot.send_photo(
            call.message.chat.id, FSInputFile(png, filename="text.png")
        )

    await bot.send_message(
        call.message.chat.id,
        tr(
            l,
            f"Текстовый стикер в теме «{images.theme_label(theme, l)}».",
            f"Text sticker in the “{images.theme_label(theme, l)}” theme.",
        ),
        reply_markup=_text_actions(token, l),
    )


@router.callback_query(F.data.startswith("tx:theme:"))
async def text_change_theme(call: CallbackQuery, l: str) -> None:
    token = call.data.split(":", 2)[2]
    payload = quote_tokens.get(token)
    if not payload:
        await call.answer(tr(l, "Стикер устарел", "The sticker expired"), show_alert=True)
        return
    await call.answer()
    await safe_edit(
        call,
        tr(l, "Выбери фон стикера.", "Pick the sticker background."),
        _theme_keyboard(f"txtt:{token}", l),
    )


@router.callback_query(F.data.startswith("txtt:"))
async def text_retheme(call: CallbackQuery, bot: Bot, l: str) -> None:
    _, token, theme = call.data.split(":", 2)
    payload = quote_tokens.get(token)
    if not payload:
        await call.answer(tr(l, "Стикер устарел", "The sticker expired"), show_alert=True)
        return
    await call.answer(tr(l, "Рисую", "Rendering"))

    workdir = Path(payload["workdir"])
    png, sticker, _theme = await _render_text(payload["text"], theme, workdir)
    new_token = quote_tokens.put(
        {
            "kind": "text",
            "text": payload["text"],
            "theme": theme,
            "path": str(png),
            "sticker": str(sticker),
            "workdir": str(workdir),
        }
    )
    try:
        await bot.send_sticker(
            call.message.chat.id, FSInputFile(sticker, filename="text.webp")
        )
    except TelegramBadRequest:
        pass
    await bot.send_message(
        call.message.chat.id,
        tr(
            l,
            f"Тема «{images.theme_label(theme, l)}».",
            f"Theme “{images.theme_label(theme, l)}”.",
        ),
        reply_markup=_text_actions(new_token, l),
    )


@router.callback_query(F.data.startswith("tx:pack:"))
async def text_to_pack(
    call: CallbackQuery, bot: Bot, state: FSMContext, l: str
) -> None:
    token = call.data.split(":", 2)[2]
    payload = quote_tokens.get(token)
    if not payload:
        await call.answer(tr(l, "Стикер устарел", "The sticker expired"), show_alert=True)
        return

    workdir = Path(payload["workdir"])
    path = Path(payload.get("sticker") or payload["path"])
    try:
        job = await intake.build_from_path(path, workdir, source="text")
    except Exception:
        await call.answer(tr(l, "Не смог открыть стикер", "Could not open the sticker"), show_alert=True)
        return

    await call.answer()
    await offer_pack_choice(
        bot,
        call.message.chat.id,
        call.from_user.id,
        state,
        job,
        header=tr(l, "Куда добавить стикер?", "Where should the sticker go?"),
        lang=l,
    )


# ------------------------------------------------------------- вход из меню

@router.callback_query(F.data == "m:quote")
async def menu_quote(call: CallbackQuery, state: FSMContext, l: str) -> None:
    await call.answer()
    await state.set_state(Flow.quote_text)
    await safe_edit(
        call,
        tr(
            l,
            "<b>Цитата в стикер</b>\n\n"
            "Ответь командой /quote на сообщение или пришли текст следующим сообщением.",
            "<b>Quote sticker</b>\n\n"
            "Reply with /quote to a message, or send the text as the next message.",
        ),
        None,
    )


@router.callback_query(F.data == "m:text")
async def menu_text(call: CallbackQuery, state: FSMContext, l: str) -> None:
    await call.answer()
    await state.set_state(Flow.text_sticker)
    await safe_edit(
        call,
        tr(
            l,
            "<b>Текст в стикер</b>\n\nПришли текст, до 300 символов.",
            "<b>Text sticker</b>\n\nSend the text, up to 300 characters.",
        ),
        None,
    )
