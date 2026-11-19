"""Генерация картинок: цитаты, текстовые стикеры, обложки паков."""

from __future__ import annotations

import io
import os
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

WINDOWS_FONTS = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"

BOLD_CANDIDATES = [
    WINDOWS_FONTS / "segoeuib.ttf",
    WINDOWS_FONTS / "arialbd.ttf",
    WINDOWS_FONTS / "calibrib.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
]
REGULAR_CANDIDATES = [
    WINDOWS_FONTS / "segoeui.ttf",
    WINDOWS_FONTS / "arial.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
]
EMOJI_CANDIDATES = [
    WINDOWS_FONTS / "seguiemj.ttf",
    Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"),
    Path("/System/Library/Fonts/Apple Color Emoji.ttc"),
]


def _first(candidates: list[Path]) -> Path | None:
    for path in candidates:
        try:
            if path.exists():
                return path
        except OSError:
            continue
    return None


BOLD_PATH = _first(BOLD_CANDIDATES)
REGULAR_PATH = _first(REGULAR_CANDIDATES)
EMOJI_PATH = _first(EMOJI_CANDIDATES)


class FontBook:
    def __init__(self) -> None:
        self._bold: dict[int, ImageFont.FreeTypeFont] = {}
        self._regular: dict[int, ImageFont.FreeTypeFont] = {}
        self._emoji: dict[int, ImageFont.FreeTypeFont] = {}

    def _load(self, path: Path | None, size: int) -> ImageFont.FreeTypeFont:
        if path is None:
            return ImageFont.load_default()
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            return ImageFont.load_default()

    def bold(self, size: int) -> ImageFont.FreeTypeFont:
        if size not in self._bold:
            self._bold[size] = self._load(BOLD_PATH, size)
        return self._bold[size]

    def regular(self, size: int) -> ImageFont.FreeTypeFont:
        if size not in self._regular:
            self._regular[size] = self._load(REGULAR_PATH, size)
        return self._regular[size]

    def emoji(self, size: int) -> ImageFont.FreeTypeFont:
        if size not in self._emoji:
            self._emoji[size] = self._load(EMOJI_PATH or BOLD_PATH, size)
        return self._emoji[size]


FONTS = FontBook()


def _is_emoji_char(ch: str) -> bool:
    code = ord(ch)
    return (
        0x1F000 <= code <= 0x1FAFF
        or 0x2600 <= code <= 0x27BF
        or 0x2B00 <= code <= 0x2BFF
        or 0x1F1E6 <= code <= 0x1F1FF
        or code in (0xFE0F, 0x20E3)
    )


def _font_for(ch: str, size: int) -> ImageFont.FreeTypeFont:
    return FONTS.emoji(size) if _is_emoji_char(ch) else FONTS.bold(size)


@lru_cache(maxsize=20000)
def _char_width(ch: str, size: int) -> float:
    font = _font_for(ch, size)
    try:
        return float(font.getlength(ch))
    except Exception:
        return float(size * 0.6)


def _text_width(text: str, size: int) -> float:
    return sum(_char_width(ch, size) for ch in text)


def _wrap(text: str, size: int, max_width: float) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        current_w = 0.0
        for word in paragraph.split(" "):
            word_w = _text_width(word, size)
            space_w = _char_width(" ", size)
            if current and current_w + space_w + word_w > max_width:
                lines.append(current)
                current, current_w = "", 0.0
            if word_w > max_width:
                if current:
                    lines.append(current)
                    current, current_w = "", 0.0
                chunk = ""
                chunk_w = 0.0
                for ch in word:
                    cw = _char_width(ch, size)
                    if chunk and chunk_w + cw > max_width:
                        lines.append(chunk)
                        chunk, chunk_w = "", 0.0
                    chunk += ch
                    chunk_w += cw
                current, current_w = chunk, chunk_w
                continue
            if current:
                current += " "
                current_w += space_w
            current += word
            current_w += word_w
        lines.append(current)
    return lines


def _fit_text(
    text: str,
    max_width: float,
    max_height: float,
    max_size: int,
    min_size: int,
    max_lines: int = 0,
    line_spacing: float = 1.3,
) -> tuple[list[str], int, int]:
    size = max_size
    while size > min_size:
        lines = _wrap(text, size, max_width)
        line_height = int(size * line_spacing)
        if len(lines) * line_height <= max_height and (not max_lines or len(lines) <= max_lines):
            return lines, size, line_height
        size -= 2
    lines = _wrap(text, min_size, max_width)
    line_height = int(min_size * line_spacing)
    limit = max(1, int(max_height // line_height))
    if max_lines:
        limit = min(limit, max_lines)
    if len(lines) > limit:
        lines = lines[:limit]
        if lines:
            last = lines[-1]
            while last and _text_width(last + "…", min_size) > max_width:
                last = last[:-1]
            lines[-1] = last + "…"
    return lines, min_size, line_height


def draw_rich_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    x: float,
    y: float,
    max_width: float,
    max_height: float,
    max_size: int,
    min_size: int,
    color: tuple[int, int, int],
    max_lines: int = 0,
    line_spacing: float = 1.3,
    align: str = "left",
    shadow: tuple[int, int, int, int] | None = None,
    valign: str = "top",
) -> tuple[int, int]:
    lines, size, line_height = _fit_text(
        text, max_width, max_height, max_size, min_size, max_lines, line_spacing
    )
    if valign == "center":
        block = len(lines) * line_height
        y = y + max(0.0, (max_height - block) / 2)
    elif valign == "bottom":
        block = len(lines) * line_height
        y = y + max(0.0, max_height - block)

    ascent, _descent = FONTS.bold(size).getmetrics()
    baseline = y + ascent
    for line in lines:
        width = _text_width(line, size)
        cursor = x + (max_width - width) / 2 if align == "center" else x
        for ch in line:
            font = _font_for(ch, size)
            width_ch = font.getlength(ch)
            emoji = _is_emoji_char(ch)
            if shadow is not None:
                draw.text(
                    (cursor + 2, baseline + 3),
                    ch,
                    font=font,
                    fill=shadow,
                    anchor="ls",
                    embedded_color=emoji,
                )
            try:
                draw.text(
                    (cursor, baseline),
                    ch,
                    font=font,
                    fill=color,
                    anchor="ls",
                    embedded_color=emoji,
                )
            except TypeError:
                draw.text((cursor, baseline), ch, font=font, fill=color, anchor="ls")
            cursor += width_ch
        baseline += line_height
    return len(lines), size


def _hex(color: tuple[int, int, int]) -> tuple[int, int, int]:
    return color


def gradient(
    size: tuple[int, int],
    top: tuple[int, int, int],
    bottom: tuple[int, int, int],
    angle: float = 35.0,
) -> Image.Image:
    import numpy as np

    width, height = size
    y = np.linspace(0, 1, height)[:, None]
    x = np.linspace(0, 1, width)[None, :]
    rad = angle * 3.14159265 / 180
    t = (x * abs(np.cos(rad)) + y * abs(np.sin(rad)))
    t = (t - t.min()) / (t.max() - t.min() + 1e-6)
    arr = np.zeros((height, width, 3), dtype=np.float32)
    for i in range(3):
        arr[:, :, i] = top[i] + (bottom[i] - top[i]) * t
    return Image.fromarray(arr.astype("uint8"), "RGB")


def _blobs(base: Image.Image, color: tuple[int, int, int], count: int = 3) -> Image.Image:
    """Мягкие световые пятна — оживляют градиент."""
    width, height = base.size
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    import random

    rnd = random.Random(width * 31 + height * 17)
    for _ in range(count):
        radius = rnd.randint(width // 6, width // 3)
        cx = rnd.randint(0, width)
        cy = rnd.randint(0, height)
        alpha = rnd.randint(28, 58)
        draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            fill=(*color, alpha),
        )
    layer = layer.filter(ImageFilter.GaussianBlur(radius=width // 18))
    return Image.alpha_composite(base.convert("RGBA"), layer)


THEMES: dict[str, dict] = {
    "midnight": {
        "bg": ((17, 20, 28), (44, 52, 70)),
        "card": (22, 26, 36, 232),
        "text": (238, 242, 250),
        "accent": (138, 170, 220),
        "muted": (150, 160, 180),
        "blob": (104, 132, 178),
        "dark": True,
    },
    "graphite": {
        "bg": ((26, 27, 30), (58, 60, 66)),
        "card": (34, 35, 39, 234),
        "text": (244, 244, 246),
        "accent": (206, 210, 218),
        "muted": (150, 152, 160),
        "blob": (130, 134, 142),
        "dark": True,
    },
    "ocean": {
        "bg": ((9, 38, 48), (20, 84, 96)),
        "card": (12, 44, 54, 230),
        "text": (232, 246, 248),
        "accent": (126, 208, 214),
        "muted": (142, 186, 192),
        "blob": (86, 176, 186),
        "dark": True,
    },
    "sunset": {
        "bg": ((178, 62, 54), (232, 138, 82)),
        "card": (54, 26, 24, 224),
        "text": (255, 245, 238),
        "accent": (255, 196, 140),
        "muted": (232, 190, 175),
        "blob": (255, 214, 156),
        "dark": True,
    },
    "forest": {
        "bg": ((12, 44, 38), (36, 92, 66)),
        "card": (14, 38, 33, 228),
        "text": (232, 250, 240),
        "accent": (128, 226, 172),
        "muted": (150, 196, 174),
        "blob": (86, 200, 140),
        "dark": True,
    },
    "paper": {
        "bg": ((246, 242, 232), (226, 219, 203)),
        "card": (255, 253, 247, 236),
        "text": (38, 34, 28),
        "accent": (168, 96, 56),
        "muted": (128, 116, 100),
        "blob": (255, 255, 255),
        "dark": False,
    },
}

THEME_LABELS: dict[str, tuple[str, str]] = {
    "midnight": ("Полночь", "Midnight"),
    "graphite": ("Графит", "Graphite"),
    "ocean": ("Океан", "Ocean"),
    "sunset": ("Закат", "Sunset"),
    "forest": ("Лес", "Forest"),
    "paper": ("Бумага", "Paper"),
}


def theme_label(key: str, lang: str = "ru") -> str:
    ru, en = THEME_LABELS.get(key, (key, key))
    return ru if lang == "ru" else en


def _rounded_card(size: tuple[int, int], margin: int, radius: int, fill: tuple[int, int, int, int]):
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.rounded_rectangle(
        (margin, margin, size[0] - margin, size[1] - margin),
        radius=radius,
        fill=fill,
        outline=(255, 255, 255, 22),
        width=2,
    )
    return layer


def _circle_avatar(photo_bytes: bytes | None, size: int, accent: tuple[int, int, int]) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    if photo_bytes:
        try:
            img = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
            side = min(img.size)
            img = img.crop(
                (
                    (img.width - side) // 2,
                    (img.height - side) // 2,
                    (img.width + side) // 2,
                    (img.height + side) // 2,
                )
            ).resize((size, size), Image.LANCZOS)
            mask = Image.new("L", (size * 4, size * 4), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, size * 4, size * 4), fill=255)
            mask = mask.resize((size, size), Image.LANCZOS)
            canvas.paste(img, (0, 0), mask)
            return canvas
        except Exception:
            pass
    draw = ImageDraw.Draw(canvas)
    draw.ellipse((0, 0, size - 1, size - 1), fill=accent)
    return canvas


def build_quote(
    text: str,
    author: str,
    username: str | None = None,
    avatar: bytes | None = None,
    theme_name: str = "midnight",
    footer: str = "@vavilong_bot",
    label: str = "цитата",
) -> bytes:
    theme = THEMES.get(theme_name, THEMES["midnight"])
    size = 1024
    base = gradient((size, size), theme["bg"][0], theme["bg"][1], 38)
    base = _blobs(base, theme["blob"], 3)
    base = base.convert("RGBA")
    base = Image.alpha_composite(base, _rounded_card((size, size), 34, 46, theme["card"]))

    draw = ImageDraw.Draw(base)

    # Декоративная кавычка
    try:
        draw.text(
            (size - 190, 60),
            "”",
            font=FONTS.bold(240),
            fill=(*theme["accent"], 46),
            anchor="la",
        )
    except Exception:
        pass

    avatar_size = 116
    avatar_img = _circle_avatar(avatar, avatar_size, theme["accent"])
    ring = Image.new("RGBA", (avatar_size + 10, avatar_size + 10), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse(
        (0, 0, avatar_size + 9, avatar_size + 9), outline=(*theme["accent"], 210), width=4
    )
    base.alpha_composite(avatar_img, (92, 92))
    base.alpha_composite(ring, (87, 87))

    x_text = 232
    draw.text((x_text, 104), author[:32], font=FONTS.bold(44), fill=theme["text"], anchor="la")
    if username:
        draw.text(
            (x_text, 160),
            f"@{username[:28]}",
            font=FONTS.regular(28),
            fill=theme["muted"],
            anchor="la",
        )

    draw.line((92, 236, size - 92, 236), fill=(*theme["muted"], 60), width=2)

    draw_rich_text(
        draw,
        text.strip() or "…",
        x=92,
        y=286,
        max_width=size - 184,
        max_height=size - 286 - 168,
        max_size=62,
        min_size=28,
        color=theme["text"],
        max_lines=12,
        line_spacing=1.28,
        align="left",
        valign="center",
    )

    # Низ карточки
    draw.line((92, size - 128, size - 92, size - 128), fill=(*theme["muted"], 46), width=2)
    draw.text(
        (92, size - 108),
        label,
        font=FONTS.regular(26),
        fill=theme["muted"],
        anchor="la",
    )
    draw.text(
        (size - 92, size - 108),
        footer,
        font=FONTS.bold(28),
        fill=theme["accent"],
        anchor="ra",
    )

    out = io.BytesIO()
    base.convert("RGB").save(out, "PNG")
    return out.getvalue()


def build_text_sticker(text: str, theme_name: str = "graphite") -> bytes:
    theme = THEMES.get(theme_name, THEMES["graphite"])
    side = 512
    base = gradient((side, side), theme["bg"][0], theme["bg"][1], 42)
    base = _blobs(base, theme["blob"], 2).convert("RGBA")

    # Скруглённые углы (прозрачные) — в чате выглядит аккуратнее.
    mask = Image.new("L", (side, side), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, side - 1, side - 1), radius=54, fill=255)
    base.putalpha(mask)

    draw = ImageDraw.Draw(base)

    lines, font_size, line_height = _fit_text(
        text.strip() or "текст",
        max_width=side - 72,
        max_height=side - 96,
        max_size=132,
        min_size=26,
        max_lines=7,
        line_spacing=1.2,
    )
    total_height = len(lines) * line_height
    baseline = (side - total_height) / 2 + FONTS.bold(font_size).getmetrics()[0]
    for line in lines:
        width = _text_width(line, font_size)
        cursor = (side - width) / 2
        for ch in line:
            font = _font_for(ch, font_size)
            emoji = _is_emoji_char(ch)
            try:
                draw.text(
                    (cursor + 2, baseline + 3),
                    ch,
                    font=font,
                    fill=(0, 0, 0, 110),
                    anchor="ls",
                    embedded_color=emoji,
                )
                draw.text(
                    (cursor, baseline),
                    ch,
                    font=font,
                    fill=theme["text"],
                    anchor="ls",
                    embedded_color=emoji,
                )
            except TypeError:
                draw.text((cursor, baseline), ch, font=font, fill=theme["text"], anchor="ls")
            cursor += font.getlength(ch)
        baseline += line_height

    out = io.BytesIO()
    base.save(out, "PNG")
    return out.getvalue()


def build_pack_cover(title: str, theme_name: str = "midnight") -> bytes:
    theme = THEMES.get(theme_name, THEMES["midnight"])
    side = 512
    base = gradient((side, side), theme["bg"][0], theme["bg"][1], 40)
    base = _blobs(base, theme["blob"], 3).convert("RGBA")
    draw = ImageDraw.Draw(base)

    letter = (title.strip()[:1] or "★").upper()
    draw.text(
        (side // 2, 150),
        letter,
        font=FONTS.bold(190),
        fill=(*theme["accent"], 235),
        anchor="mm",
    )
    lines, font_size, line_height = _fit_text(
        title.strip() or "Sticker pack",
        max_width=side - 60,
        max_height=120,
        max_size=54,
        min_size=22,
        max_lines=2,
        line_spacing=1.2,
    )
    baseline = side - 92 - (len(lines) - 1) * line_height
    for line in lines:
        draw.text(
            (side // 2, baseline),
            line,
            font=FONTS.bold(font_size),
            fill=theme["text"],
            anchor="ms",
        )
        baseline += line_height

    out = io.BytesIO()
    base.convert("RGB").save(out, "PNG")
    return out.getvalue()


def save_png(data: bytes, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path
