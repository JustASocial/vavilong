"""Подбор эмодзи: ручной, случайный и «умный» (по содержимому картинки)."""

from __future__ import annotations

import os
import random
from pathlib import Path

# Пул для режима «рандом». Без повторов внутри одного пака.
EMOJI_POOL: list[str] = list(
    "😀 😃 😄 😁 😆 😅 😂 🤣 😊 😇 🙂 😉 😍 🥰 😘 😋 😜 🤪 🤨 🧐 🤓 😎 🥳 😏 "
    "😒 😞 😔 😟 😕 🙁 😣 😖 😫 😩 🥺 😢 😭 😤 😠 😡 🤬 🤯 😳 🥵 🥶 😱 😨 😰 "
    "😥 😓 🤗 🤔 🤭 🤫 🤥 😶 😐 😑 😬 🙄 😯 😦 😧 😮 😲 🥱 😴 🤤 😪 😵 🤐 "
    "🥴 🤢 🤮 🤧 😷 🤒 🤕 🤑 🤠 😈 👿 👻 💀 ☠️ 👽 🤖 🎃 😺 😸 😹 😻 😼 😽 "
    "🙀 😿 😾 👋 🤚 ✋ 🖖 👌 🤌 🤏 ✌️ 🤞 🤟 🤘 🤙 👈 👉 👆 👇 ☝️ 👍 👎 ✊ "
    "👊 🤛 🤜 👏 🙌 👐 🤲 🤝 🙏 💅 💪 🦾 🦿 🦵 🦶 👂 👃 🧠 🫀 🫁 🦷 🦴 👀 "
    "❤️ 🧡 💛 💚 💙 💜 🖤 🤍 🤎 💔 ❣️ 💕 💞 💓 💗 💖 💘 💝 💟 ☮️ ✝️ ☪️ 🕉 "
    "🔥 ✨ 💥 💫 💦 💨 🕳 💬 💭 💤 💢 💯 💡 🔥 🎉 🎊 🎈 🎁 🎀 🏆 🥇 🥈 🥉 "
    "🌈 ☀️ 🌤 ⛅ 🌧 ⛈ 🌩 🌪 ❄️ ☃️ ⛄ 🌊 💧 🫧 🍀 🌿 🌱 🌳 🌴 🌵 🌸 🌺 🌻 🌼 "
    "🍎 🍓 🍒 🍑 🍊 🍋 🍌 🍉 🍇 🥝 🍅 🥑 🥦 🍄 🌰 🍞 🧀 🍕 🍔 🍟 🌮 🍣 🍩 "
    "🍪 🎂 🍰 🍫 🍬 🍭 ☕ 🍵 🍺 🍷 🥂 🧊 🥤 ⚽ 🏀 🏈 🎾 🏐 🎱 🎯 🎮 🕹 🎲 "
    "🧩 🎨 🎬 🎤 🎧 🎼 🎹 🥁 🎸 🎺 🚀 🛸 ✈️ 🚗 🏎 🚲 🛹 🏍 ⛵ 🚁 🗿 🗽 🏰 "
    "💎 🔮 🧿 📿 🪬 🕯 🪄 🔭 🔬 🧪 🧬 💊 🩹 🧲 🔋 💻 🖥 ⌨️ 🖱 💾 📱 ☎️ 📷 "
    "📹 🎥 📺 📻 ⏰ ⌛ ⏳ 🕰 🗓 📌 📍 📎 🔗 📦 📫 💌 📝 📖 📚 🖊 🖋 ✏️ 🖌 "
    "✅ ☑️ ✔️ ❌ ❎ ➕ ➖ ➗ ✖️ ♾ 💲 💰 💳 🧾 🏷 🔑 🗝 🔒 🔓 🛡 ⚙️ 🧰 🪛 🔧 "
    "🚫 ⛔ 💤 ⚠️ ☢️ ☣️ 🔞 💯 🔥".split()
)

# Тематические наборы для «умного» режима.
BUCKETS: dict[str, list[str]] = {
    "face": ["😀", "😎", "😍", "🤪", "🙃", "😇", "🤗", "😏", "🥳", "😌", "🤭", "🫠"],
    "colorful": ["🔥", "🌈", "✨", "🎉", "💫", "🦄", "🎨", "💥", "🌟", "🍭"],
    "dark": ["🌚", "🖤", "🌙", "👻", "🕶️", "🦇", "🖤", "💀", "🌑", "🕯️"],
    "bright": ["☀️", "😊", "🌞", "💛", "🤍", "🌟", "🌻", "🍋", "✨", "🕊️"],
    "green": ["🌿", "🍀", "🐸", "🥝", "💚", "🌱", "🌵", "🪴", "🥦", "🍃"],
    "blue": ["💙", "🌊", "🐳", "🧊", "🩵", "🐬", "💧", "🌐", "❄️", "🫧"],
    "red": ["❤️", "🍓", "🌹", "🔥", "🍎", "🌶️", "🍒", "🎈", "💋", "🫀"],
    "mono": ["📓", "🖤", "🌫️", "🗿", "◾", "🩶", "📷", "🎞️", "🪨", "🌑"],
    "text": ["📝", "💬", "🔤", "📄", "✍️", "📰", "📚", "🗒️", "💭", "🖋️"],
    "food": ["🍕", "🍔", "🍟", "🍣", "🍩", "🍪", "🍰", "🍫", "🥑", "🍜"],
    "animal": ["🐱", "🐶", "🦊", "🐻", "🐼", "🐨", "🦁", "🐯", "🐸", "🐧"],
}


def random_emoji(used: set[str] | None = None) -> str:
    used = used or set()
    free = [e for e in EMOJI_POOL if e not in used]
    return random.choice(free or EMOJI_POOL)


def is_emoji(text: str) -> bool:
    """Грубая, но практичная проверка: в строке есть эмодзи-символы и нет букв."""
    text = text.strip()
    if not text or len(text) > 16:
        return False
    has_emoji = False
    for ch in text:
        code = ord(ch)
        if ch.isalpha() and code < 0x2000:
            return False
        if (
            0x1F000 <= code <= 0x1FAFF
            or 0x2600 <= code <= 0x27BF
            or 0x2B00 <= code <= 0x2BFF
            or 0xFE00 <= code <= 0xFE0F
            or 0x1F1E6 <= code <= 0x1F1FF
            or code in (0x200D, 0x20E3)
        ):
            has_emoji = True
    return has_emoji


def normalize_emoji(text: str) -> str:
    """Оставляем только эмодзи, максимум 3 кластера (Telegram разрешает несколько)."""
    return "".join(ch for ch in text.strip() if not ch.isspace())[:16]


def smart_emoji(path: str | Path, used: set[str] | None = None) -> str:
    """
    «Умный» подбор по картинке: лица, насыщенность, яркость, доминирующий цвет,
    плотность краёв (похоже на текст). Всё локально, без внешних API.
    """
    used = used or set()
    bucket = "mono"
    try:
        import cv2
        import numpy as np

        image = cv2.imread(str(path))
        if image is None:
            return random_emoji(used)

        h, w = image.shape[:2]
        scale = 160 / max(h, w) if max(h, w) > 160 else 1.0
        small = cv2.resize(image, (max(1, int(w * scale)), max(1, int(h * scale))))

        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        h_mean = float(hsv[:, :, 0].mean())
        s_mean = float(hsv[:, :, 1].mean())
        v_mean = float(hsv[:, :, 2].mean())
        edges = cv2.Canny(gray, 70, 160)
        edge_density = float((edges > 0).mean())

        faces = []
        cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        if os.path.exists(cascade_path):
            cascade = cv2.CascadeClassifier(cascade_path)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(20, 20))

        if len(faces) > 0:
            bucket = "face"
        elif edge_density > 0.16:
            bucket = "text"
        elif s_mean < 28:
            bucket = "mono"
        elif v_mean < 62:
            bucket = "dark"
        elif v_mean > 196 and s_mean < 90:
            bucket = "bright"
        elif s_mean > 140 and v_mean > 110:
            bucket = "colorful"
        elif 40 <= h_mean <= 95:          # зелёный (OpenCV: H 0..179)
            bucket = "green"
        elif 96 <= h_mean <= 135:         # синий
            bucket = "blue"
        elif h_mean <= 15 or h_mean >= 165:  # красный
            bucket = "red"
    except Exception:
        return random_emoji(used)

    pool = BUCKETS.get(bucket, EMOJI_POOL)
    free = [e for e in pool if e not in used]
    return random.choice(free or [e for e in EMOJI_POOL if e not in used] or EMOJI_POOL)


def emoji_hint(mode: str) -> str:
    return {
        "manual": "✍️ ты выбираешь эмодзи для каждого стикера",
        "random": "🎲 бот кидает случайный эмодзи без повторов",
        "smart": "🧠 бот смотрит на картинку и подбирает эмодзи сам",
    }.get(mode, mode)
