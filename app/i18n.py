"""Локализация: русский и английский. Никаких эмодзи в интерфейсе."""

from __future__ import annotations

LANGS = ("ru", "en")
LANG_LABELS = {"ru": "Русский", "en": "English"}


def detect_lang(code: str | None) -> str:
    if not code:
        return "en"
    code = code.lower()
    if code.startswith(("ru", "uk", "be", "kk", "ky", "uz")):
        return "ru"
    return "en"


def tr(lang: str, ru: str, en: str, **kwargs) -> str:
    text = ru if lang == "ru" else en
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return text
