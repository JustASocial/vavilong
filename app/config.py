"""Конфигурация приложения. Все секреты — в .env, ничего не хардкодим."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _ids(raw: str) -> tuple[int, ...]:
    out: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            out.append(int(chunk))
    return tuple(out)


@dataclass(frozen=True)
class Settings:
    bot_token: str = os.getenv("BOT_TOKEN", "").strip()
    cli_token: str = os.getenv("TG_CLI_TOKEN", "").strip()
    admin_ids: tuple[int, ...] = field(default_factory=lambda: _ids(os.getenv("ADMIN_IDS", "")))

    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "49"))
    max_concurrent_downloads: int = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "2"))
    webapp_url: str = os.getenv("WEBAPP_URL", "").strip()
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "").strip()

    root: Path = ROOT
    data_dir: Path = ROOT / "data"
    temp_dir: Path = ROOT / "data" / "tmp"
    cache_dir: Path = ROOT / "data" / "cache"
    log_dir: Path = ROOT / "data" / "logs"

    cookies_file: Path | None = field(
        default_factory=lambda: (
            ROOT / os.environ["YTDLP_COOKIES"] if os.getenv("YTDLP_COOKIES") else None
        )
    )

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def db_path(self) -> Path:
        return self.data_dir / "bot.sqlite3"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.temp_dir, self.cache_dir, self.log_dir):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()

# Жёсткие лимиты Telegram, менять их нельзя.
STICKER_STATIC_MAX = 512 * 1024         # 512 КБ
STICKER_VIDEO_MAX = 256 * 1024          # 256 КБ
STICKER_SIDE = 512                      # px
STICKER_VIDEO_SECONDS = 3.0
STICKER_VIDEO_FPS = 30
PACK_MAX_STICKERS = 120
