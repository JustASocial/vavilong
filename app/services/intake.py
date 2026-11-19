"""Приём медиа из Telegram или по ссылке и подготовка «заготовки» стикера."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from aiogram import Bot
from aiogram.types import Message
from PIL import Image

from app.services import downloader, ffmpeg_tools
from app.services.session import StickerJob
from app.services.utils import download_url, safe_filename

MAX_TELEGRAM_DOWNLOAD = 20 * 1024 * 1024  # жёсткий лимит Bot API на getFile
MAX_URL_DOWNLOAD = 200 * 1024 * 1024
MAX_STICKER_VIDEO_SOURCE = 900  # секунд: длиннее — не для стикера


class IntakeError(RuntimeError):
    pass


async def download_telegram_file(bot: Bot, file_id: str) -> bytes | None:
    try:
        buffer = await bot.download(file_id)
    except Exception:
        return None
    if buffer is None:
        return None
    return buffer.read() if hasattr(buffer, "read") else bytes(buffer)


def _image_preview(raw: Path, dest: Path, width: int = 640) -> Path:
    with Image.open(raw) as img:
        img = img.convert("RGB")
        ratio = width / img.width
        img = img.resize((width, max(1, int(img.height * ratio))), Image.LANCZOS)
        img.save(dest, "JPEG", quality=86)
    return dest


async def _make_preview(raw: Path, dest: Path, is_video: bool, at: float = 0.3) -> Path | None:
    try:
        return await ffmpeg_tools.make_thumbnail(raw, dest, at=at, width=640) if is_video else await _image_preview(
            raw, dest
        )
    except Exception:
        return None


async def _classify(
    raw: Path, workdir: Path, source: str, alpha: bool = False
) -> StickerJob:
    ext = raw.suffix.lower()
    is_video = ext in {".webm", ".mp4", ".mov", ".mkv", ".m4v", ".gif"}

    if ext == ".webp" or ext == ".tgs":
        try:
            info = await ffmpeg_tools.probe(raw)
            is_video = bool(info.get("has_video") and info.get("duration"))
        except Exception:
            is_video = False

    if is_video:
        try:
            info = await ffmpeg_tools.probe(raw)
        except Exception as exc:
            raise IntakeError("не смог прочитать видео") from exc
        if not info.get("has_video"):
            raise IntakeError("в файле нет видеодорожки")
        duration = float(info.get("duration") or 0)
        if duration > MAX_STICKER_VIDEO_SOURCE:
            raise IntakeError("видео слишком длинное для стикера (максимум 15 минут)")
        preview = await _make_preview(raw, workdir / "preview.jpg", True, 0.2)
        return StickerJob(
            path=raw,
            raw_path=raw,
            kind="video",
            source=source,
            temp_dir=workdir,
            start=0.0,
            duration=min(3.0, duration) if duration else 3.0,
            preview=preview,
            alpha=alpha or ext == ".gif",
            video_duration=duration,
        )

    try:
        with Image.open(raw) as img:
            img.verify()
    except Exception as exc:
        raise IntakeError("это не похоже на картинку или видео") from exc

    preview = await _make_preview(raw, workdir / "preview.jpg", False)
    return StickerJob(
        path=raw,
        raw_path=raw,
        kind="static",
        source=source,
        temp_dir=workdir,
        preview=preview,
    )


async def build_from_bytes(
    data: bytes,
    workdir: Path,
    filename: str,
    source: str,
    mime: str | None = None,
    alpha: bool = False,
) -> StickerJob:
    ext = Path(filename).suffix.lower()
    if not ext:
        ext = mimetypes.guess_extension(mime or "application/octet-stream") or ".bin"
        if ext == ".jpe":
            ext = ".jpg"
    raw = workdir / f"{safe_filename(Path(filename).stem, 'media')[:40]}{ext}"
    raw.write_bytes(data)
    return await _classify(raw, workdir, source, alpha)


async def build_from_path(path: Path, workdir: Path, source: str = "file") -> StickerJob:
    """Готовый локальный файл (цитата, текст, скачанное видео) → заготовка стикера."""
    if not path.exists():
        raise IntakeError("файл не найден")
    return await _classify(path, workdir, source)


async def build_from_message(bot: Bot, message: Message, workdir: Path) -> StickerJob:
    if message.photo:
        data = await download_telegram_file(bot, message.photo[-1].file_id)
        if not data:
            raise IntakeError("не смог скачать фото из Telegram")
        return await build_from_bytes(data, workdir, "photo.jpg", "photo", "image/jpeg")

    if message.sticker:
        sticker = message.sticker
        if sticker.is_animated:
            raise IntakeError(
                "это анимированный (Lottie) стикер — такой формат я не умею перерисовывать. "
                "Кинь обычный или видео-стикер."
            )
        data = await download_telegram_file(bot, sticker.file_id)
        if not data:
            raise IntakeError("не смог скачать стикер")
        ext = ".webm" if sticker.is_video else ".webp"
        return await build_from_bytes(
            data,
            workdir,
            f"sticker_{sticker.file_unique_id[:10]}{ext}",
            "sticker",
            "video/webm" if sticker.is_video else "image/webp",
            alpha=not sticker.is_video,
        )

    if message.animation:
        animation = message.animation
        if animation.file_size and animation.file_size > MAX_TELEGRAM_DOWNLOAD:
            raise IntakeError("гифка больше 20 МБ — Bot API не даст её скачать")
        data = await download_telegram_file(bot, animation.file_id)
        if not data:
            raise IntakeError("не смог скачать гифку")
        ext = Path(animation.file_name or "anim.mp4").suffix or ".mp4"
        return await build_from_bytes(data, workdir, f"anim{ext}", "gif", "video/mp4", alpha=True)

    if message.video or message.video_note:
        video = message.video or message.video_note
        if video.file_size and video.file_size > MAX_TELEGRAM_DOWNLOAD:
            raise IntakeError(
                "видео больше 20 МБ — Bot API не даст его скачать. "
                "Пришли файл поменьше или ссылку (по ссылке лимита нет)."
            )
        data = await download_telegram_file(bot, video.file_id)
        if not data:
            raise IntakeError("не смог скачать видео")
        return await build_from_bytes(data, workdir, "video.mp4", "video", "video/mp4")

    if message.document:
        document = message.document
        mime = document.mime_type or ""
        ext = Path(document.file_name or "").suffix.lower()
        if not (
            mime.startswith("image")
            or mime.startswith("video")
            or ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".mov", ".webm", ".mkv", ".m4v"}
        ):
            raise IntakeError("поддерживаются фото, видео, гиф и стикеры")
        if document.file_size and document.file_size > MAX_TELEGRAM_DOWNLOAD:
            raise IntakeError("файл больше 20 МБ — Bot API не даст его скачать")
        data = await download_telegram_file(bot, document.file_id)
        if not data:
            raise IntakeError("не смог скачать файл")
        return await build_from_bytes(
            data, workdir, document.file_name or "file", "photo", mime, alpha=ext == ".gif"
        )

    raise IntakeError("не вижу тут медиа")


async def build_from_url(url: str, workdir: Path) -> StickerJob:
    kind = downloader.direct_kind(url)
    if kind is None:
        raise IntakeError("это не прямая ссылка на файл")

    name = Path(url.split("?")[0]).name or "media"
    if not Path(name).suffix:
        name += ".jpg" if kind == "image" else ".mp4"

    raw = workdir / safe_filename(name, "media")
    try:
        await download_url(url, raw, timeout=120)
    except Exception as exc:
        raise IntakeError("не удалось скачать файл по ссылке") from exc

    if raw.stat().st_size > MAX_URL_DOWNLOAD:
        raise IntakeError("файл больше 200 МБ — слишком много")

    return await _classify(raw, workdir, "url", alpha=kind == "gif")


async def build_from_ytdlp(url: str, workdir: Path) -> StickerJob:
    """Любая ссылка, которую понимает yt-dlp → короткий стикер (первые секунды)."""
    info = await downloader.extract(url)
    info = downloader.normalize_info(info)
    duration = float(info.get("duration") or 0)
    if duration and duration > MAX_STICKER_VIDEO_SOURCE:
        raise IntakeError("видео длиннее 15 минут — такое в стикер не поместится")

    progress = downloader.Progress()
    await downloader.download(
        url,
        workdir,
        progress,
        selector="bv*[height<=480]+ba/b[height<=480]/worst",
        playlist_limit=1,
    )
    path = downloader.find_output(workdir)
    if not path:
        raise IntakeError("не удалось скачать видео по ссылке")
    if path.stat().st_size > MAX_URL_DOWNLOAD:
        raise IntakeError("видео получилось слишком большим")
    return await _classify(path, workdir, "url")
