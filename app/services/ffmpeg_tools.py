"""Вся работа с медиа: ffprobe/ffmpeg, нарезка, кроп, сжатие, стикеры."""

from __future__ import annotations

import asyncio
import math
import os
import shutil
from pathlib import Path

from app.config import STICKER_SIDE, STICKER_VIDEO_FPS, STICKER_VIDEO_MAX

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"


class MediaError(RuntimeError):
    pass


async def _run(cmd: list[str], timeout: float = 300) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=getattr(asyncio.subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise MediaError("ffmpeg не успел обработать файл (таймаут)")
    return int(proc.returncode or 0), out, err


async def probe(path: str | Path) -> dict:
    code, out, err = await _run(
        [
            FFPROBE, "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        timeout=60,
    )
    if code != 0:
        raise MediaError(f"ffprobe: {err.decode('utf-8', 'ignore')[-300:]}")

    import json

    data = json.loads(out or b"{}")
    info: dict = {"duration": 0.0, "width": 0, "height": 0, "has_audio": False, "has_video": False, "fps": 0.0}

    fmt = data.get("format") or {}
    try:
        info["duration"] = float(fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        pass

    for stream in data.get("streams") or []:
        kind = stream.get("codec_type")
        if kind == "video" and not info["has_video"]:
            info["has_video"] = True
            info["width"] = int(stream.get("width") or 0)
            info["height"] = int(stream.get("height") or 0)
            rate = stream.get("avg_frame_rate") or "0/1"
            try:
                num, den = rate.split("/")
                info["fps"] = float(num) / float(den) if float(den) else 0.0
            except (ValueError, ZeroDivisionError):
                pass
            if not info["duration"]:
                try:
                    info["duration"] = float(stream.get("duration") or 0.0)
                except (TypeError, ValueError):
                    pass
        elif kind == "audio":
            info["has_audio"] = True

    return info


async def extract_frame(path: str | Path, dest: Path, at: float = 0.0) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    code, _out, err = await _run(
        [
            FFMPEG, "-y", "-ss", f"{max(0.0, at):.2f}", "-i", str(path),
            "-frames:v", "1", "-q:v", "2", str(dest),
        ],
        timeout=90,
    )
    if code != 0 or not dest.exists():
        raise MediaError(f"не удалось вытащить кадр: {err.decode('utf-8', 'ignore')[-200:]}")
    return dest


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def detect_focus_sync(path: str | Path, at: float = 0.5) -> tuple[float, float] | None:
    """Ищем лицо (или центр «массы») — возвращаем нормализованные координаты 0..1."""
    try:
        import cv2

        if str(path).lower().endswith((".mp4", ".webm", ".mkv", ".mov", ".m4v", ".gif")):
            cap = cv2.VideoCapture(str(path))
            try:
                if not cap.isOpened():
                    return None
                cap.set(cv2.CAP_PROP_POS_MSEC, at * 1000)
                ok, frame = cap.read()
                if not ok:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, frame = cap.read()
                if not ok:
                    return None
            finally:
                cap.release()
        else:
            frame = cv2.imread(str(path))

        if frame is None:
            return None

        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        if os.path.exists(cascade_path):
            faces = cv2.CascadeClassifier(cascade_path).detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(24, 24)
            )
            if len(faces) > 0:
                fx, fy, fw, fh = max(faces, key=lambda f: int(f[2]) * int(f[3]))
                return ((fx + fw / 2) / w, (fy + fh / 2) / h)

        # Запасной вариант: центр яркости (грубо, но лучше центра кадра).
        small = cv2.resize(gray, (64, 64))
        moments = cv2.moments(small)
        if moments["m00"]:
            return (moments["m10"] / moments["m00"] / 64, moments["m01"] / moments["m00"] / 64)
    except Exception:
        return None
    return None


async def detect_focus(path: str | Path, at: float = 0.5) -> tuple[float, float] | None:
    return await asyncio.to_thread(detect_focus_sync, path, at)


def _square_box(width: int, height: int, mode: str, focus: tuple[float, float] | None) -> tuple[int, int, int]:
    """Возвращает (side, x, y) для квадратного кропа."""
    side = min(width, height)
    if side <= 0:
        return 1, 0, 0

    cx, cy = width / 2, height / 2
    if mode == "smart" and focus:
        fx, fy = focus
        cx, cy = fx * width, fy * height

    x = int(_clamp(cx - side / 2, 0, width - side))
    y = int(_clamp(cy - side / 2, 0, height - side))
    return side, x, y


def _photo_to_sticker_sync(
    src: str | Path,
    dest: Path,
    mode: str = "crop",
    focus: tuple[float, float] | None = None,
    max_bytes: int = 512 * 1024,
) -> Path:
    from PIL import Image, ImageOps

    with Image.open(src) as img:
        try:
            img.seek(0)
        except EOFError:
            pass
        frame = ImageOps.exif_transpose(img)
        if frame.mode not in ("RGBA", "RGB"):
            frame = frame.convert("RGBA")
        elif frame.mode == "RGB":
            frame = frame.convert("RGBA")

        w, h = frame.size
        if mode == "fit":
            canvas = Image.new("RGBA", (STICKER_SIDE, STICKER_SIDE), (0, 0, 0, 0))
            scale = min(STICKER_SIDE / w, STICKER_SIDE / h)
            new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
            resized = frame.resize(new_size, Image.LANCZOS)
            canvas.paste(resized, ((STICKER_SIDE - new_size[0]) // 2, (STICKER_SIDE - new_size[1]) // 2), resized)
            result = canvas
        else:
            side, x, y = _square_box(w, h, mode, focus)
            result = frame.crop((x, y, x + side, y + side)).resize(
                (STICKER_SIDE, STICKER_SIDE), Image.LANCZOS
            )

    dest.parent.mkdir(parents=True, exist_ok=True)
    quality = 95
    while True:
        result.save(dest, "WEBP", quality=quality, method=6)
        if dest.stat().st_size <= max_bytes or quality <= 60:
            break
        quality -= 10
    return dest


async def photo_to_sticker(
    src: str | Path,
    dest: Path,
    mode: str = "crop",
    focus: tuple[float, float] | None = None,
) -> Path:
    return await asyncio.to_thread(_photo_to_sticker_sync, src, dest, mode, focus)


async def video_to_sticker(
    src: str | Path,
    dest: Path,
    start: float = 0.0,
    duration: float = 3.0,
    mode: str = "crop",
    focus: tuple[float, float] | None = None,
    alpha: bool = False,
    max_bytes: int = STICKER_VIDEO_MAX,
    fps: int = STICKER_VIDEO_FPS,
) -> Path:
    info = await probe(src)
    width, height = info["width"], info["height"]
    if not width or not height:
        raise MediaError("не удалось определить размер видео")

    if mode == "fit":
        vf = (
            f"scale={STICKER_SIDE}:{STICKER_SIDE}:force_original_aspect_ratio=decrease,"
            f"pad={STICKER_SIDE}:{STICKER_SIDE}:(ow-iw)/2:(oh-ih)/2:color=black@0,fps={fps}"
        )
    else:
        side, x, y = _square_box(width, height, mode, focus)
        vf = f"crop={side}:{side}:{x}:{y},scale={STICKER_SIDE}:{STICKER_SIDE},fps={fps}"

    duration = max(0.4, min(duration, 3.0 if info["duration"] <= 0 else min(3.0, info["duration"])))

    dest.parent.mkdir(parents=True, exist_ok=True)
    attempts = [(240, duration), (190, duration), (150, duration), (120, duration), (110, min(duration, 2.5))]
    last_err = ""
    for bitrate, dur in attempts:
        code, _out, err = await _run(
            [
                FFMPEG, "-y",
                "-ss", f"{max(0.0, start):.2f}",
                "-t", f"{dur:.2f}",
                "-i", str(src),
                "-vf", vf,
                "-c:v", "libvpx-vp9",
                "-b:v", f"{bitrate}k",
                "-maxrate", f"{int(bitrate * 1.45)}k",
                "-bufsize", f"{bitrate * 2}k",
                "-an",
                "-pix_fmt", "yuva420p" if alpha else "yuv420p",
                "-row-mt", "1",
                "-deadline", "good",
                "-cpu-used", "3",
                "-f", "webm",
                str(dest),
            ],
            timeout=240,
        )
        if code != 0 or not dest.exists():
            last_err = err.decode("utf-8", "ignore")[-300:]
            continue
        if dest.stat().st_size <= max_bytes:
            return dest

    if not dest.exists():
        raise MediaError(f"не удалось закодировать видео: {last_err}")
    return dest


async def make_thumbnail(src: str | Path, dest: Path, at: float = 1.0, width: int = 480) -> Path | None:
    try:
        await extract_frame(src, dest, at)
        from PIL import Image

        def _resize() -> None:
            with Image.open(dest) as img:
                img = img.convert("RGB")
                ratio = width / img.width
                img = img.resize((width, max(1, int(img.height * ratio))), Image.LANCZOS)
                img.save(dest, "JPEG", quality=86)

        await asyncio.to_thread(_resize)
        return dest
    except Exception:
        return None


async def shrink_video(
    src: str | Path,
    dest: Path,
    max_bytes: int,
    duration: float | None = None,
) -> Path:
    """Пережать видео под лимит Telegram (однопроходный x264 по расчётному битрейту)."""
    info = await probe(src)
    duration = duration or info["duration"] or 0
    if duration <= 0:
        if Path(src).stat().st_size <= max_bytes:
            return Path(src)
        raise MediaError("неизвестна длительность — не могу рассчитать битрейт")

    audio_kbps = 96 if info["has_audio"] else 0
    target_kbps = max(220, int(max_bytes * 8 / duration / 1000) - audio_kbps)
    code = 1
    err = b""
    for factor in (1.0, 0.85, 0.7):
        bitrate = max(180, int(target_kbps * factor))
        cmd = [
            FFMPEG, "-y", "-i", str(src),
            "-c:v", "libx264", "-preset", "veryfast",
            "-b:v", f"{bitrate}k",
            "-maxrate", f"{int(bitrate * 1.3)}k",
            "-bufsize", f"{bitrate * 2}k",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-movflags", "+faststart",
        ]
        if audio_kbps:
            cmd += ["-c:a", "aac", "-b:a", f"{audio_kbps}k"]
        else:
            cmd += ["-an"]
        cmd.append(str(dest))

        code, _out, err = await _run(cmd, timeout=1800)
        if code == 0 and dest.exists() and dest.stat().st_size <= max_bytes:
            return dest

    if code != 0:
        raise MediaError(f"не удалось пережать: {err.decode('utf-8', 'ignore')[-200:]}")
    return dest


def calculate_bitrate(duration: float, max_bytes: int, audio_kbps: int = 96) -> int:
    if duration <= 0:
        return 800
    return max(150, int(max_bytes * 8 / duration / 1000) - audio_kbps)


async def crop_preview_grid(src: str | Path, dest: Path, duration: float) -> Path | None:
    """Превьюшка-полоска из 4 кадров — чтобы удобно выбрать начало для стикера."""
    frames: list[Path] = []
    folder = dest.parent
    points = [0.0, max(0.0, duration * 0.33), max(0.0, duration * 0.66), max(0.0, duration - 0.3)]
    try:
        for idx, point in enumerate(points):
            frame = folder / f"strip_{idx}.jpg"
            await extract_frame(src, frame, point)
            frames.append(frame)

        from PIL import Image

        def _compose() -> None:
            imgs = [Image.open(f).convert("RGB") for f in frames]
            height = 160
            resized = []
            for img in imgs:
                ratio = height / img.height
                resized.append(img.resize((max(1, int(img.width * ratio)), height), Image.LANCZOS))
            total = sum(i.width for i in resized) + 6 * (len(resized) - 1)
            canvas = Image.new("RGB", (total, height), (18, 18, 22))
            x = 0
            for img in resized:
                canvas.paste(img, (x, 0))
                x += img.width + 6
            canvas.save(dest, "JPEG", quality=80)

        await asyncio.to_thread(_compose)
        return dest
    except Exception:
        return None


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def fit_bitrate_for_sticker(duration: float, max_bytes: int = STICKER_VIDEO_MAX) -> int:
    kbps = max_bytes * 8 / max(duration, 0.5) / 1000
    return int(max(80, min(320, math.floor(kbps * 0.8))))
