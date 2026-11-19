"""Инлайн-клавиатуры. Без эмодзи: только текст и типографика."""

from __future__ import annotations

import random

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.i18n import tr
from app.services.emoji import EMOJI_POOL, random_emoji
from app.services.utils import human_size


def main_menu(lang: str, webapp_url: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=tr(lang, "Скачать медиа", "Download media"), callback_data="m:dl"),
        InlineKeyboardButton(text=tr(lang, "Стикер-студия", "Sticker studio"), callback_data="m:packs"),
    )
    builder.row(
        InlineKeyboardButton(text=tr(lang, "Цитата в стикер", "Quote sticker"), callback_data="m:quote"),
        InlineKeyboardButton(text=tr(lang, "Текст в стикер", "Text sticker"), callback_data="m:text"),
    )
    builder.row(
        InlineKeyboardButton(text=tr(lang, "История", "History"), callback_data="m:history"),
        InlineKeyboardButton(text=tr(lang, "Настройки", "Settings"), callback_data="m:settings"),
    )
    if webapp_url:
        builder.row(
            InlineKeyboardButton(
                text=tr(lang, "Открыть приложение", "Open the app"),
                web_app=WebAppInfo(url=webapp_url),
            )
        )
    builder.row(InlineKeyboardButton(text=tr(lang, "Помощь", "Help"), callback_data="m:help"))
    return builder.as_markup()


def back_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=tr(lang, "В меню", "Back to menu"), callback_data="m:home")]
        ]
    )


def quality_keyboard(
    token: str,
    options: list[dict],
    lang: str,
    has_audio: bool = True,
    playlist: bool = False,
    subtitles: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for index, option in enumerate(options):
        label = option["label"]
        if option.get("fps") and int(option["fps"]) >= 50:
            label += f"{int(option['fps'])}"
        if option.get("size"):
            label += f" · {human_size(option['size'])}"
        builder.button(text=label, callback_data=f"dl:{token}:q{index}")
    builder.adjust(2)

    audio_row: list[InlineKeyboardButton] = []
    if has_audio:
        audio_row.append(InlineKeyboardButton(text="MP3", callback_data=f"dl:{token}:mp3"))
        audio_row.append(
            InlineKeyboardButton(
                text=tr(lang, "Аудио", "Audio"), callback_data=f"dl:{token}:m4a"
            )
        )
    audio_row.append(
        InlineKeyboardButton(
            text=tr(lang, "Обложка", "Cover"), callback_data=f"dl:{token}:thumb"
        )
    )
    builder.row(*audio_row)

    extra: list[InlineKeyboardButton] = []
    if subtitles:
        extra.append(
            InlineKeyboardButton(
                text=tr(lang, "Субтитры", "Subtitles"), callback_data=f"dl:{token}:subs"
            )
        )
    if playlist:
        extra.append(
            InlineKeyboardButton(
                text=tr(lang, "Первые 10", "First 10"), callback_data=f"dl:{token}:pl"
            )
        )
    extra.append(
        InlineKeyboardButton(
            text=tr(lang, "Лучшее", "Best"), callback_data=f"dl:{token}:best"
        )
    )
    builder.row(*extra)

    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Отмена", "Cancel"), callback_data=f"dl:{token}:cancel"
        )
    )
    return builder.as_markup()


def packs_list_keyboard(packs: list[dict], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for pack in packs:
        kind = tr(lang, "видео", "video") if pack["kind"] == "video" else tr(lang, "фото", "photo")
        builder.button(
            text=f"{pack['title'][:30]} · {pack.get('count', 0)} · {kind}",
            callback_data=f"pk:{pack['id']}:open",
        )
    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(text=tr(lang, "Новый пак", "New pack"), callback_data="newpack")
    )
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Импорт по ссылке", "Import by link"), callback_data="m:import"
        )
    )
    builder.row(
        InlineKeyboardButton(text=tr(lang, "В меню", "Back to menu"), callback_data="m:home")
    )
    return builder.as_markup()


def pack_view_keyboard(pack: dict, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Добавить стикер", "Add sticker"), callback_data=f"pk:{pack['id']}:add"
        ),
        InlineKeyboardButton(
            text=tr(lang, "Удалить последний", "Delete last"), callback_data=f"pk:{pack['id']}:dellast"
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Экспорт ZIP", "Export ZIP"), callback_data=f"pk:{pack['id']}:zip"
        ),
        InlineKeyboardButton(
            text=tr(lang, "Обложка", "Cover"), callback_data=f"pk:{pack['id']}:cover"
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Ссылка", "Link"), callback_data=f"pk:{pack['id']}:link"
        ),
        InlineKeyboardButton(
            text=tr(lang, "Удалить пак", "Delete pack"), callback_data=f"pk:{pack['id']}:delete"
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "К списку", "Back to list"), callback_data="m:packs"
        )
    )
    return builder.as_markup()


def pack_kind_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Фото-пак (WebP)", "Photo pack (WebP)"), callback_data="kind:static"
        ),
        InlineKeyboardButton(
            text=tr(lang, "Видео-пак (WebM)", "Video pack (WebM)"), callback_data="kind:video"
        ),
    )
    builder.row(
        InlineKeyboardButton(text=tr(lang, "Отмена", "Cancel"), callback_data="m:packs")
    )
    return builder.as_markup()


def emoji_mode_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Вручную", "Manual"), callback_data="emode:manual"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Рандом", "Random"), callback_data="emode:random"
        ),
        InlineKeyboardButton(
            text=tr(lang, "Умный", "Smart"), callback_data="emode:smart"
        ),
    )
    builder.row(
        InlineKeyboardButton(text=tr(lang, "Отмена", "Cancel"), callback_data="m:packs")
    )
    return builder.as_markup()


def crop_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Кроп по центру", "Center crop"), callback_data="crop:crop"
        ),
        InlineKeyboardButton(
            text=tr(lang, "Вписать целиком", "Fit whole"), callback_data="crop:fit"
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Умный (лицо)", "Smart (face)"), callback_data="crop:smart"
        )
    )
    builder.row(
        InlineKeyboardButton(text=tr(lang, "Отмена", "Cancel"), callback_data="m:packs")
    )
    return builder.as_markup()


def emoji_grid(used: set[str] | None = None, size: int = 16, lang: str = "ru") -> InlineKeyboardMarkup:
    used = used or set()
    builder = InlineKeyboardBuilder()
    suggestions = list(EMOJI_POOL)
    random.shuffle(suggestions)

    picked: list[str] = []
    for value in suggestions:
        if value not in used and value not in picked:
            picked.append(value)
        if len(picked) >= size:
            break

    for value in picked:
        builder.button(text=value, callback_data=f"ep:{value}")
    builder.adjust(8)
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Случайный", "Random"), callback_data="ep:__random__"
        ),
        InlineKeyboardButton(
            text=tr(lang, "Отмена", "Cancel"), callback_data="ep:__cancel__"
        ),
    )
    return builder.as_markup()


def trim_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="−0.5 s", callback_data="tr:left"),
        InlineKeyboardButton(text="+0.5 s", callback_data="tr:right"),
    )
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Кадр из видео", "Frame from video"), callback_data="tr:frame"
        ),
        InlineKeyboardButton(text=tr(lang, "Готово", "Done"), callback_data="tr:ok"),
    )
    builder.row(
        InlineKeyboardButton(text=tr(lang, "Отмена", "Cancel"), callback_data="tr:cancel")
    )
    return builder.as_markup()


def emoji_confirm_keyboard(emoji_value: str, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Добавить", "Add") + f" {emoji_value}", callback_data="ec:ok"
        ),
        InlineKeyboardButton(
            text=tr(lang, "Другой", "Another"), callback_data="ec:again"
        ),
    )
    builder.row(
        InlineKeyboardButton(text=tr(lang, "Отмена", "Cancel"), callback_data="ec:cancel")
    )
    return builder.as_markup()


def theme_keyboard(prefix: str, themes: list[tuple[str, str]], lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key, label in themes:
        builder.button(text=label, callback_data=f"{prefix}:{key}")
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(text=tr(lang, "Отмена", "Cancel"), callback_data="m:home")
    )
    return builder.as_markup()


def quote_result_keyboard(token: str, lang: str) -> InlineKeyboardMarkup:
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


def text_result_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Другая тема", "Another theme"), callback_data="tx:theme"
        ),
        InlineKeyboardButton(
            text=tr(lang, "В пак", "To pack"), callback_data="tx:pack"
        ),
    )
    builder.row(
        InlineKeyboardButton(text=tr(lang, "В меню", "Back to menu"), callback_data="m:home")
    )
    return builder.as_markup()


def import_preview_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Импортировать", "Import"), callback_data="imp:go"
        )
    )
    builder.row(
        InlineKeyboardButton(text=tr(lang, "Отмена", "Cancel"), callback_data="m:packs")
    )
    return builder.as_markup()


def settings_keyboard(settings: dict, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    auto = tr(lang, "вкл", "on") if settings.get("autocompress") else tr(lang, "выкл", "off")
    silent = tr(lang, "вкл", "on") if settings.get("silent") else tr(lang, "выкл", "off")
    crop_label = {
        "crop": tr(lang, "центр", "center"),
        "fit": tr(lang, "вписать", "fit"),
        "smart": tr(lang, "умный", "smart"),
    }.get(settings.get("crop_mode", "crop"), tr(lang, "центр", "center"))
    emoji_label = {
        "manual": tr(lang, "вручную", "manual"),
        "random": tr(lang, "рандом", "random"),
        "smart": tr(lang, "умный", "smart"),
    }.get(settings.get("emoji_mode", "manual"), tr(lang, "вручную", "manual"))
    language = "Русский" if lang == "ru" else "English"

    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Автосжатие", "Auto-compress") + f": {auto}", callback_data="st:auto"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Эмодзи", "Emoji") + f": {emoji_label}", callback_data="st:emoji"
        ),
        InlineKeyboardButton(
            text=tr(lang, "Кадрирование", "Crop") + f": {crop_label}", callback_data="st:crop"
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Язык", "Language") + f": {language}", callback_data="st:lang"
        ),
        InlineKeyboardButton(
            text=tr(lang, "Уведомления", "Notifications") + f": {silent}", callback_data="st:silent"
        ),
    )
    builder.row(
        InlineKeyboardButton(text=tr(lang, "В меню", "Back to menu"), callback_data="m:home")
    )
    return builder.as_markup()


def after_download_keyboard(token: str, can_sticker: bool, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if can_sticker:
        builder.row(
            InlineKeyboardButton(
                text=tr(lang, "В стикер", "To sticker"), callback_data=f"ds:{token}"
            )
        )
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Другое качество", "Other quality"), callback_data=f"dl:{token}:again"
        ),
        InlineKeyboardButton(text=tr(lang, "В меню", "Back to menu"), callback_data="m:home"),
    )
    return builder.as_markup()


def confirm_delete_keyboard(pack_id: int, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=tr(lang, "Удалить", "Delete"), callback_data=f"pk:{pack_id}:confirmdelete"
        ),
        InlineKeyboardButton(text=tr(lang, "Нет", "No"), callback_data=f"pk:{pack_id}:open"),
    )
    return builder.as_markup()
