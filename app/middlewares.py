"""Middleware: пользователь из базы и язык интерфейса в каждом апдейте."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app import database as db
from app.i18n import detect_lang

log = logging.getLogger(__name__)


class UserMiddleware(BaseMiddleware):
    """Кладёт в data пользователя (`u`) и язык (`l`).

    Пользователь создаётся при первом апдейте, язык берётся из настроек,
    а если там пусто — из `language_code` Telegram.

    Важно: middleware вешается на конкретные обсерверы (message, callback_query,
    inline_query), а не на `dp.update`. Если подменить апдейт сообщением на
    уровне update, aiogram 3.3x ломается на `update.event_type`.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = getattr(event, "from_user", None)
        if tg_user is None:
            data.setdefault("l", "en")
            return await handler(event, data)

        record = await db.get_user(
            tg_user.id,
            getattr(tg_user, "username", None),
            getattr(tg_user, "first_name", None),
        )
        lang = (record.get("settings") or {}).get("lang") or ""
        if lang not in ("ru", "en"):
            lang = detect_lang(getattr(tg_user, "language_code", None))
            try:
                record = await db.update_settings(tg_user.id, lang=lang)
            except Exception:  # noqa: BLE001
                pass

        data["u"] = record
        data["l"] = lang
        return await handler(event, data)
