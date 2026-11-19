"""Локальная самопроверка без Telegram: рендер, стикеры, разбор inline-запросов.

Запуск: python -m tools.selftest
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.config import STICKER_STATIC_MAX, STICKER_VIDEO_MAX, settings
from app.handlers.inline import parse_query
from app.services import ffmpeg_tools, images


def check(condition: bool, message: str) -> None:
    print(("  ok   " if condition else "  FAIL ") + message)


async def main() -> None:
    out = settings.temp_dir / "selftest"
    out.mkdir(parents=True, exist_ok=True)
    print(f"Папка проверки: {out}")

    print("\n[1] Inline-разбор")
    cases = [
        ("https://youtu.be/abc", None, [720], False),
        ("https://youtu.be/abc 1080p", None, [1080], False),
        ("https://youtu.be/abc +info", None, [720], True),
        ("https://youtu.be/abc 480p +info", None, [480], True),
        ("https://youtu.be/abc [144p,360p,720p]", None, [144, 360, 720], False),
        ("смотри https://youtu.be/abc?t=10 1080p инфо", None, [1080], True),
    ]
    for raw, _unused, heights, want_info in cases:
        url, parsed, info = parse_query(raw)
        check(url is not None, f"ссылка найдена: {raw}")
        check(parsed == heights, f"качества {parsed} == {heights}")
        check(info is want_info, f"+info {info} == {want_info}")

    print("\n[2] Карточка-цитата")
    quote = images.build_quote(
        "Дизайн — это не то, как выглядит, а то, как работает.",
        "Vavilong",
        "vavilong",
        None,
        "midnight",
        "@vavilong_bot",
        "цитата",
    )
    quote_path = out / "quote.png"
    quote_path.write_bytes(quote)
    check(quote_path.stat().st_size > 10_000, f"цитата отрисована ({quote_path.stat().st_size} Б)")

    print("\n[3] Текстовый стикер")
    for theme in ("graphite", "ocean", "paper"):
        raw = images.build_text_sticker("Привет, мир", theme)
        path = out / f"text_{theme}.png"
        path.write_bytes(raw)
        check(path.stat().st_size > 5_000, f"тема {theme} ({path.stat().st_size} Б)")

    print("\n[4] Фото-стикер")
    sticker = await ffmpeg_tools.photo_to_sticker(quote_path, out / "quote.webp", "crop")
    size = sticker.stat().st_size
    check(size <= STICKER_STATIC_MAX, f"webp {size} Б <= {STICKER_STATIC_MAX} Б")

    print("\n[5] Видео-стикер")
    source = out / "sample.mp4"
    code, _out, err = await ffmpeg_tools._run(
        [
            ffmpeg_tools.FFMPEG, "-y",
            "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25:duration=5",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(source),
        ],
        timeout=120,
    )
    check(code == 0 and source.exists(), "тестовое видео создано")
    if source.exists():
        video_sticker = await ffmpeg_tools.video_to_sticker(
            source, out / "sample.webm", start=0.5, duration=3.0, mode="smart"
        )
        vsize = video_sticker.stat().st_size
        check(vsize <= STICKER_VIDEO_MAX, f"webm {vsize} Б <= {STICKER_VIDEO_MAX} Б")
        info = await ffmpeg_tools.probe(video_sticker)
        check(info.get("width") == 512 and info.get("height") == 512, "размер 512x512")
        check(1.5 <= (info.get("duration") or 0) <= 3.2, f"длительность {info.get('duration')}")

    print("\n[6] Сжатие видео под лимит")
    target = 3 * 1024 * 1024
    small = await ffmpeg_tools.shrink_video(source, out / "small.mp4", target)
    check(small.stat().st_size <= target, f"{small.stat().st_size} Б <= {target} Б")

    print("\nГотово.")


if __name__ == "__main__":
    asyncio.run(main())
