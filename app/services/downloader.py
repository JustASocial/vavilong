"""Обёртка над yt-dlp: разбор ссылки, выбор качества, скачивание с прогрессом.

Никаких эмодзи в текстах: интерфейс строится на типографике и подписях.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from app.config import settings
from app.i18n import tr
from app.services.utils import UA, human_duration, human_size, short

try:
    import yt_dlp
    from yt_dlp.utils import DownloadError
except ImportError:  # pragma: no cover
    yt_dlp = None

    class DownloadError(Exception):
        pass


class DownloadFailed(RuntimeError):
    """Ошибка с машинным кодом, чтобы handler показал её на языке пользователя."""

    def __init__(self, message: str = "", code: str = "other", detail: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.detail = detail or message


ERROR_TEXT = {
    "no_ytdlp": (
        "yt-dlp не установлен на сервере",
        "yt-dlp is not installed on the server",
    ),
    "unsupported": (
        "эту ссылку yt-dlp не понимает",
        "yt-dlp does not recognise this link",
    ),
    "cookies": (
        "сайт требует вход. Добавь cookies в data/cookies.txt (см. README)",
        "the site requires a login. Add cookies to data/cookies.txt (see README)",
    ),
    "private": (
        "видео приватное или требует входа",
        "the video is private or requires a login",
    ),
    "unavailable": (
        "контент недоступен: удалён или заблокирован по региону",
        "the content is unavailable: removed or region-blocked",
    ),
    "timeout": (
        "сайт не ответил вовремя, попробуй ещё раз",
        "the site did not answer in time, try again",
    ),
    "geo": (
        "видео заблокировано в регионе сервера",
        "the video is blocked in the server's region",
    ),
    "cancelled": ("скачивание отменено", "download cancelled"),
    "empty": ("пустой ответ от сайта", "the site returned nothing"),
    "no_file": ("файл не появился после скачивания", "no file appeared after the download"),
    "too_big": ("файл больше допустимого размера", "the file is larger than allowed"),
    "other": ("не получилось разобрать ссылку", "could not process the link"),
}

@dataclass
class Progress:
    status: str = "starting"
    downloaded: int = 0
    total: int = 0
    speed: float = 0.0
    eta: int = 0
    fragment: str = ""
    filename: str | None = None
    cancelled: bool = False
    stage: str = ""

    @property
    def percent(self) -> float:
        total = self.total or self.downloaded
        if not total:
            return 0.0
        return min(100.0, self.downloaded / total * 100)


BASE_OPTS: dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "noprogress": True,
    "nocheckcertificate": True,
    "no_color": True,
    "cachedir": False,
    "socket_timeout": 25,
    "retries": 3,
    "fragment_retries": 4,
    "extractor_retries": 2,
    "user_agent": UA,
    "ignoreerrors": False,
    "concurrent_fragment_downloads": 4,
    "restrictfilenames": False,
    "windowsfilenames": True,
}

if settings.cookies_file and settings.cookies_file.exists():
    BASE_OPTS["cookiefile"] = str(settings.cookies_file)


def explain(exc: BaseException | str, lang: str = "ru") -> str:
    """Человеческий текст ошибки на нужном языке."""
    if isinstance(exc, DownloadFailed):
        ru, en = ERROR_TEXT.get(exc.code, ERROR_TEXT["other"])
        text = tr(lang, ru, en)
        if exc.code == "other" and exc.detail:
            return f"{text}: {short(exc.detail, 180)}"
        return text
    return f"{tr(lang, 'ошибка', 'error')}: {short(str(exc), 180)}"


def is_available() -> bool:
    return yt_dlp is not None


def _opts(**extra: Any) -> dict[str, Any]:
    return {**BASE_OPTS, **extra}


# ------------------------------------------------------------------ разбор

def _sync_extract(url: str, playlist: bool = False) -> dict[str, Any]:
    opts = _opts(skip_download=True, noplaylist=not playlist)
    if playlist:
        opts.update({"extract_flat": "in_playlist", "playlistend": 20})
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info is None:
        raise DownloadFailed(code="empty")
    return info


async def extract(url: str, playlist: bool = False, timeout: float | None = None) -> dict[str, Any]:
    if not is_available():
        raise DownloadFailed(code="no_ytdlp")
    try:
        call = asyncio.to_thread(_sync_extract, url, playlist)
        return await asyncio.wait_for(call, timeout=timeout) if timeout else await call
    except asyncio.TimeoutError as exc:
        raise DownloadFailed(code="timeout") from exc
    except DownloadFailed:
        raise
    except DownloadError as exc:
        raise _classify_error(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise _classify_error(str(exc)) from exc


def _classify_error(raw: str) -> DownloadFailed:
    text = re.sub(r"\x1b\[[0-9;]*m", "", raw)
    text = text.replace("ERROR: ", "").strip()
    low = text.lower()
    code = "other"
    if "unsupported url" in low:
        code = "unsupported"
    elif "sign in" in low or ("bot" in low and "confirm" in low):
        code = "cookies"
    elif "private" in low or "login" in low:
        code = "private"
    elif "not available" in low or "unavailable" in low:
        code = "unavailable"
    elif "timed out" in low or "timeout" in low:
        code = "timeout"
    elif "geo" in low and "restrict" in low:
        code = "geo"
    return DownloadFailed(code=code, detail=short(text, 240))


def is_playlist(info: dict[str, Any]) -> bool:
    return info.get("_type") in ("playlist", "multi_video") and bool(info.get("entries"))


def normalize_info(info: dict[str, Any]) -> dict[str, Any]:
    """Для плейлиста берём первую запись как «лицо», но помним, что это список."""
    if not is_playlist(info):
        return info
    entries = [e for e in (info.get("entries") or []) if e]
    base = dict(entries[0]) if entries else {}
    base["_playlist_title"] = info.get("title")
    base["_playlist_count"] = info.get("playlist_count") or len(entries)
    base["_playlist_url"] = info.get("webpage_url") or info.get("url")
    base["_is_playlist"] = True
    return base


def quality_options(info: dict[str, Any]) -> list[dict[str, Any]]:
    """Список доступных качеств: по одному (лучшему) на каждую высоту."""
    formats = [f for f in (info.get("formats") or []) if f.get("vcodec") not in (None, "none")]
    heights: dict[int, dict[str, Any]] = {}
    for fmt in formats:
        height = fmt.get("height")
        if not height:
            continue
        current = heights.get(int(height))
        score = (
            1 if fmt.get("acodec") not in (None, "none") else 0,
            1 if fmt.get("ext") == "mp4" else 0,
            fmt.get("tbr") or 0,
        )
        if current is None or score > current["_score"]:
            heights[int(height)] = {**fmt, "_score": score}

    options: list[dict[str, Any]] = []
    for height in sorted(heights, reverse=True)[:7]:
        fmt = heights[height]
        size = fmt.get("filesize") or fmt.get("filesize_approx") or 0
        options.append(
            {
                "height": height,
                "label": f"{height}p",
                "ext": fmt.get("ext") or "mp4",
                "size": int(size) if size else None,
                "fps": fmt.get("fps"),
                "selector": (
                    f"bv*[height={height}]+ba/bv*[height<={height}]+ba/"
                    f"b[height<={height}]/b"
                ),
            }
        )
    return options


def best_selector() -> str:
    return "bv*+ba/b"


def audio_selector() -> str:
    return "bestaudio/best"


def build_caption(info: dict[str, Any], url: str, lang: str = "ru") -> str:
    title = info.get("title") or tr(lang, "Без названия", "Untitled")
    uploader = info.get("uploader") or info.get("channel") or info.get("creator") or "—"
    duration = info.get("duration")
    views = info.get("view_count")
    likes = info.get("like_count")
    date = info.get("upload_date")
    extractor = (
        info.get("extractor_key") or info.get("extractor") or urlparse(url).netloc
    ).lower()

    lines = [f"<b>{_esc(short(title, 180))}</b>"]
    meta = [_esc(short(uploader, 60))]
    if duration:
        meta.append(human_duration(duration))
    if views:
        meta.append(
            tr(lang, f"{_compact(views)} просмотров", f"{_compact(views)} views")
        )
    if likes:
        meta.append(tr(lang, f"{_compact(likes)} лайков", f"{_compact(likes)} likes"))
    lines.append(" · ".join(meta))

    if date and len(str(date)) == 8:
        lines.append(f"{date[:4]}-{date[4:6]}-{date[6:]}")

    if info.get("_is_playlist"):
        lines.append(
            tr(
                lang,
                f"Плейлист: <b>{_esc(short(str(info.get('_playlist_title')), 80))}</b>"
                f" · {info.get('_playlist_count')} файлов",
                f"Playlist: <b>{_esc(short(str(info.get('_playlist_title')), 80))}</b>"
                f" · {info.get('_playlist_count')} files",
            )
        )

    if info.get("description"):
        lines.append(f"\n<i>{_esc(short(info['description'], 280))}</i>")

    lines.append(f"\n<i>{_esc(extractor)}</i>")
    return "\n".join(lines)


def info_caption(info: dict[str, Any], lang: str = "ru") -> str:
    """Короткая строка «просмотры · лайки · дата» для inline-режима."""
    parts: list[str] = []
    uploader = info.get("uploader") or info.get("channel") or info.get("creator")
    if uploader:
        parts.append(short(uploader, 32))
    if info.get("view_count"):
        parts.append(
            tr(
                lang,
                f"{_compact(info['view_count'])} просмотров",
                f"{_compact(info['view_count'])} views",
            )
        )
    if info.get("like_count"):
        parts.append(
            tr(
                lang,
                f"{_compact(info['like_count'])} лайков",
                f"{_compact(info['like_count'])} likes",
            )
        )
    date = str(info.get("upload_date") or "")
    if len(date) == 8:
        parts.append(f"{date[:4]}-{date[4:6]}-{date[6:]}")
    if info.get("duration"):
        parts.append(human_duration(info["duration"]))
    return " · ".join(parts)


def _esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _compact(num: int | float) -> str:
    num = int(num)
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.1f}B"
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    if num >= 1_000:
        return f"{num / 1_000:.1f}K"
    return str(num)


# --------------------------------------------------------------- скачивание

def _sync_download(
    url: str,
    outdir: Path,
    progress: Progress,
    selector: str = "",
    audio_format: str = "",
    playlist_limit: int = 0,
    subtitles: bool = False,
) -> dict[str, Any]:
    def hook(data: dict[str, Any]) -> None:
        if progress.cancelled:
            raise DownloadFailed(code="cancelled")

        status = data.get("status")
        if status == "downloading":
            progress.status = "downloading"
            progress.downloaded = int(data.get("downloaded_bytes") or 0)
            progress.total = int(
                data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            )
            progress.speed = float(data.get("speed") or 0)
            progress.eta = int(data.get("eta") or 0)
            if data.get("filename"):
                progress.filename = data["filename"]
        elif status == "finished":
            progress.status = "processing"
            if data.get("filename"):
                progress.filename = data["filename"]

    opts = _opts(
        outtmpl=str(outdir / "%(title).70B [%(id)s].%(ext)s"),
        progress_hooks=[hook],
        noplaylist=not playlist_limit,
    )
    if playlist_limit:
        opts["playlistend"] = playlist_limit

    if audio_format:
        opts["format"] = audio_selector()
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": audio_format,
                "preferredquality": "192",
            }
        ]
    else:
        opts["format"] = selector or best_selector()
        opts["merge_output_format"] = "mp4"

    if subtitles:
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = True
        opts["subtitleslangs"] = ["ru", "en"]
        opts["subtitlesformat"] = "srt/best"

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info is None:
            raise DownloadFailed(code="empty")
        return info


async def download(
    url: str,
    outdir: Path,
    progress: Progress,
    selector: str = "",
    audio_format: str = "",
    playlist_limit: int = 0,
    subtitles: bool = False,
) -> dict[str, Any]:
    if not is_available():
        raise DownloadFailed(code="no_ytdlp")
    try:
        return await asyncio.to_thread(
            _sync_download,
            url,
            outdir,
            progress,
            selector,
            audio_format,
            playlist_limit,
            subtitles,
        )
    except DownloadFailed:
        raise
    except DownloadError as exc:
        raise _classify_error(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        if progress.cancelled:
            raise DownloadFailed(code="cancelled") from exc
        raise _classify_error(str(exc)) from exc


async def download_subtitles(url: str, outdir: Path, lang: str = "ru") -> Path | None:
    """Тянет субтитры (ru первым, потом en) и возвращает один файл."""
    if not is_available():
        raise DownloadFailed(code="no_ytdlp")

    def run() -> None:
        opts = _opts(
            skip_download=True,
            writesubtitles=True,
            writeautomaticsub=True,
            subtitleslangs=["ru", "en"],
            subtitlesformat="srt/best",
            outtmpl=str(outdir / "subs.%(ext)s"),
        )
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

    try:
        await asyncio.to_thread(run)
    except DownloadError as exc:
        raise _classify_error(str(exc)) from exc

    files = [p for p in outdir.rglob("*") if p.suffix.lower() in (".srt", ".vtt")]
    if not files:
        return None
    files.sort(key=lambda p: (0 if ".ru." in p.name else 1, p.stat().st_size))
    return files[0]


def find_output(folder: Path, audio_format: str = "") -> Path | None:
    files = [
        p
        for p in folder.rglob("*")
        if p.is_file()
        and not p.name.endswith(
            (".part", ".ytdl", ".json", ".description", ".vtt", ".srt", ".ass")
        )
    ]
    if not files:
        return None
    if audio_format:
        preferred = [p for p in files if p.suffix.lower() == f".{audio_format}"]
        if preferred:
            return max(preferred, key=lambda p: p.stat().st_size)
    return max(files, key=lambda p: p.stat().st_size)


def render_progress(p: Progress, title: str = "", lang: str = "ru") -> str:
    if p.status == "processing":
        return (
            f"<b>{tr(lang, 'Обрабатываю файл', 'Processing the file')}</b>\n"
            f"{_esc(short(title, 80))}"
        )
    if p.status == "starting":
        return f"<b>{tr(lang, 'Готовлюсь к скачиванию', 'Preparing the download')}</b>"

    percent = p.percent
    filled = int(percent / 5)
    bar = "█" * filled + "░" * (20 - filled)
    lines = [f"<b>{percent:.0f}%</b>  <code>{bar}</code>"]
    detail = []
    if p.total:
        detail.append(f"{human_size(p.downloaded, lang)} / {human_size(p.total, lang)}")
    elif p.downloaded:
        detail.append(human_size(p.downloaded, lang))
    if p.speed:
        detail.append(
            f"{human_size(p.speed, lang)}{tr(lang, '/с', '/s')}"
        )
    if p.eta:
        detail.append(
            tr(lang, f"осталось {human_duration(p.eta)}", f"{human_duration(p.eta)} left")
        )
    if detail:
        lines.append(" · ".join(detail))
    return "\n".join(lines)


def progress_bar(percent: float, width: int = 18) -> str:
    percent = max(0.0, min(100.0, percent))
    filled = int(percent / 100 * width)
    return "█" * filled + "░" * (width - filled)


def direct_kind(url: str) -> str | None:
    """Быстрая проверка: это прямая ссылка на файл, а не страница."""
    path = urlparse(url).path.lower()
    ext = Path(path).suffix
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".avif"}:
        return "image"
    if ext == ".gif":
        return "gif"
    if ext in {".mp4", ".mov", ".webm", ".mkv", ".m4v"}:
        return "video"
    if ext in {".mp3", ".m4a", ".ogg", ".opus", ".flac", ".wav"}:
        return "audio"
    return None


def is_sticker_link(url: str) -> str | None:
    match = re.search(r"(?:t\.me|telegram\.me)/(?:addstickers|addemoji)/([\w-]+)", url)
    return match.group(1) if match else None


class ProgressReporter:
    """Раз в N секунд отдаёт снапшот прогресса в колбэк."""

    def __init__(
        self,
        progress: Progress,
        callback: Callable[[Progress], Any],
        interval: float = 3.0,
    ) -> None:
        self.progress = progress
        self.callback = callback
        self.interval = interval
        self._task: asyncio.Task | None = None

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            try:
                await self.callback(self.progress)
            except Exception:
                pass

    async def __aenter__(self) -> "ProgressReporter":
        self._task = asyncio.create_task(self._loop())
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


@dataclass
class DownloadResult:
    path: Path | None = None
    title: str = ""
    duration: float = 0
    width: int = 0
    height: int = 0
    info: dict[str, Any] = field(default_factory=dict)
    audio_path: Path | None = None
    subtitle_path: Path | None = None
    size: int = 0
    elapsed: float = 0


async def full_download(
    url: str,
    outdir: Path,
    progress: Progress,
    selector: str = "",
    audio_format: str = "",
    playlist_limit: int = 0,
    subtitles: bool = False,
) -> DownloadResult:
    started = time.monotonic()
    info = await download(
        url, outdir, progress, selector, audio_format, playlist_limit, subtitles
    )
    path = find_output(outdir, audio_format)
    if path is None:
        raise DownloadFailed(code="no_file")

    from app.services import ffmpeg_tools

    meta = (
        await ffmpeg_tools.probe(path)
        if path.suffix.lower() not in (".mp3", ".m4a", ".opus")
        else {}
    )
    subtitle = next(
        iter([p for p in outdir.rglob("*") if p.suffix.lower() in (".srt", ".vtt")]),
        None,
    )

    return DownloadResult(
        path=path,
        title=info.get("title") or path.stem,
        duration=float(info.get("duration") or meta.get("duration") or 0),
        width=int(meta.get("width") or info.get("width") or 0),
        height=int(meta.get("height") or info.get("height") or 0),
        info=info,
        subtitle_path=subtitle,
        size=path.stat().st_size if path.exists() else 0,
        elapsed=time.monotonic() - started,
    )


# ------------------------------------------------------------------- inline

INLINE_DEFAULT_HEIGHT = 720
INLINE_FALLBACK_HEIGHTS = (720, 480, 360, 240, 144)


def progressive_formats(info: dict[str, Any]) -> list[dict[str, Any]]:
    """Форматы, которые Telegram сможет проиграть напрямую: видео + звук в одном файле."""
    out = []
    for fmt in info.get("formats") or []:
        if fmt.get("vcodec") in (None, "none"):
            continue
        if fmt.get("acodec") in (None, "none"):
            continue
        if not fmt.get("url"):
            continue
        if (fmt.get("protocol") or "").startswith(("mhtml", "dash")):
            continue
        out.append(fmt)
    return out


def _height(fmt: dict[str, Any]) -> int:
    try:
        return int(fmt.get("height") or 0)
    except (TypeError, ValueError):
        return 0


def pick_inline_format(
    info: dict[str, Any], wanted: int
) -> tuple[dict[str, Any] | None, int]:
    """Лучший progressive-формат не выше wanted. Возвращает (формат, фактическая высота)."""
    formats = progressive_formats(info)

    if not formats:
        direct = info.get("url")
        ext = str(info.get("ext") or "").lower()
        if direct and ext in {"mp4", "m4v", "webm", "mov"}:
            formats = [
                {
                    "url": direct,
                    "ext": ext,
                    "height": int(info.get("height") or 0),
                    "width": int(info.get("width") or 0),
                    "tbr": 0,
                    "format_id": "direct",
                }
            ]

    if not formats:
        return None, 0

    exact = [f for f in formats if _height(f) == wanted]
    if exact:
        best = max(exact, key=lambda f: (f.get("tbr") or 0, f.get("filesize") or 0))
        return best, wanted

    lower = [f for f in formats if 0 < _height(f) < wanted]
    if lower:
        closest = max(_height(f) for f in lower)
        pool = [f for f in lower if _height(f) == closest]
        return max(pool, key=lambda f: (f.get("tbr") or 0, f.get("filesize") or 0)), closest

    unknown = [f for f in formats if not _height(f)]
    if unknown:
        # Прямая ссылка на файл: размеры не пришли, показываем запрошенное качество.
        return max(unknown, key=lambda f: (f.get("tbr") or 0, f.get("filesize") or 0)), wanted

    smallest = min(formats, key=lambda f: _height(f) or 9999)
    return smallest, _height(smallest)


def inline_heights_available(info: dict[str, Any]) -> list[int]:
    heights = {_height(f) for f in progressive_formats(info)}
    return sorted({h for h in heights if h}, reverse=True)


def thumbnail_url(info: dict[str, Any]) -> str | None:
    thumbnails = info.get("thumbnails") or []
    for thumb in reversed(thumbnails):
        url = thumb.get("url")
        if url:
            return url
    return info.get("thumbnail")


def inline_result_id(info: dict[str, Any], height: int) -> str:
    raw = f"{info.get('id') or info.get('webpage_url') or ''}-{height}"
    return re.sub(r"[^A-Za-z0-9_-]", "", raw)[:60] or f"r{height}"
