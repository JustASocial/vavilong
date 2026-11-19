"""Точка сборки: бот, диспетчер, роутеры, запуск polling."""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
import os
import shutil
import sys
import time
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    ErrorEvent,
    LinkPreviewOptions,
    MenuButtonCommands,
    MenuButtonWebApp,
    WebAppInfo,
)

from app import database as db
from app.config import settings
from app.middlewares import UserMiddleware
from app.services import downloader, ffmpeg_tools

log = logging.getLogger("vavilong")


def setup_logging() -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(console)

    file = logging.handlers.RotatingFileHandler(
        settings.log_dir / "bot.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(file)

    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


def cleanup_temp() -> None:
    """Подчищаем хвосты прошлого запуска: папки в data/tmp."""
    root = settings.temp_dir
    if not root.exists():
        return
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except OSError:
                pass


async def set_commands(bot: Bot) -> None:
    ru = [
        BotCommand(command="start", description="Меню и начало работы"),
        BotCommand(command="packs", description="Мои стикер-паки"),
        BotCommand(command="newpack", description="Создать стикер-пак"),
        BotCommand(command="import", description="Скопировать чужой пак"),
        BotCommand(command="quote", description="Цитата в стикер"),
        BotCommand(command="text", description="Текст в стикер"),
        BotCommand(command="history", description="Последние загрузки"),
        BotCommand(command="settings", description="Язык и параметры"),
        BotCommand(command="cancel", description="Прервать действие"),
        BotCommand(command="help", description="Как всё работает"),
    ]
    en = [
        BotCommand(command="start", description="Menu and first steps"),
        BotCommand(command="packs", description="Your sticker packs"),
        BotCommand(command="newpack", description="Create a sticker pack"),
        BotCommand(command="import", description="Copy someone else's pack"),
        BotCommand(command="quote", description="Quote as a sticker"),
        BotCommand(command="text", description="Text as a sticker"),
        BotCommand(command="history", description="Recent downloads"),
        BotCommand(command="settings", description="Language and defaults"),
        BotCommand(command="cancel", description="Abort the current step"),
        BotCommand(command="help", description="How it all works"),
    ]
    try:
        await bot.set_my_commands(en)
        await bot.set_my_commands(ru, language_code="ru")
    except TelegramBadRequest:
        log.warning("Не удалось обновить список команд")


async def set_menu_button(bot: Bot) -> None:
    try:
        if settings.webapp_url:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="App", web_app=WebAppInfo(url=settings.webapp_url)
                )
            )
        else:
            await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except Exception:
        pass


async def on_error(event: ErrorEvent) -> bool:
    log.exception("Ошибка при обработке апдейта", exc_info=event.exception)
    update = event.update
    message = update.message or (update.callback_query.message if update.callback_query else None)
    if message is not None:
        try:
            await message.answer(
                "Что-то сломалось на моей стороне. Попробуй ещё раз или пришли другую ссылку.\n"
                "Something broke on my side. Try again or send another link."
            )
        except Exception:
            pass
    return True


async def stop_after(seconds: int, dp: Dispatcher) -> None:
    """Мягко останавливаем polling, когда облачный раннер выдал своё окно времени."""
    await asyncio.sleep(seconds)
    log.info("RUN_SECONDS=%s истёк, останавливаю polling", seconds)
    try:
        await dp.stop_polling()
    except Exception:
        log.exception("Не удалось остановить polling")


async def start_health(port: int):
    """HTTP-пинг для хостингов, которым нужен живой порт (Render, Fly и т.п.)."""
    from aiohttp import web

    started = time.monotonic()

    async def ok(_request):
        return web.json_response({"ok": True, "uptime": round(time.monotonic() - started)})

    application = web.Application()
    application.router.add_get("/", ok)
    application.router.add_get("/health", ok)
    runner = web.AppRunner(application)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("Health-сервер слушает порт %s", port)
    return runner


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(UserMiddleware())

    from app.handlers import download, inline, pack, quote, settings as settings_handlers, start

    dp.include_router(start.router)
    dp.include_router(settings_handlers.router)
    dp.include_router(quote.router)
    dp.include_router(pack.router)
    dp.include_router(inline.router)
    dp.include_router(download.router)

    dp.errors.register(on_error)
    dp.shutdown.register(close_db)
    return dp


async def close_db(**_kwargs) -> None:
    await db.close()


async def main() -> None:
    setup_logging()
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN не задан в .env")

    if not ffmpeg_tools.ffmpeg_available():
        log.warning("ffmpeg/ffprobe не найдены в PATH: стикеры и сжатие не будут работать")
    if not downloader.is_available():
        log.warning("yt-dlp не установлен: скачивание по ссылкам не будет работать")

    cleanup_temp()
    await db.init()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            link_preview=LinkPreviewOptions(is_disabled=True),
        ),
    )
    dp = build_dispatcher()

    await set_commands(bot)
    await set_menu_button(bot)

    me = await bot.get_me()
    log.info("Запуск @%s (%s)", me.username, me.id)

    health = None
    background: list[asyncio.Task] = []

    port = int(os.getenv("PORT", "0") or 0)
    if port > 0:
        try:
            health = await start_health(port)
        except Exception:
            log.exception("Health-сервер не поднялся на порту %s", port)

    run_seconds = int(os.getenv("RUN_SECONDS", "0") or 0)
    if run_seconds > 0:
        background.append(asyncio.create_task(stop_after(run_seconds, dp)))

    # Не сбрасываем очередь: после паузы апдейты должны дообработаться.
    try:
        await bot.delete_webhook()
    except Exception:
        pass

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        for task in background:
            task.cancel()
        if health is not None:
            await health.cleanup()
        await bot.session.close()
        log.info("Остановлено")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
