"""SQLite-слой: пользователи, история скачиваний, стикер-паки."""

from __future__ import annotations

import json
import time
from typing import Any

import aiosqlite

from app.config import settings

_conn: aiosqlite.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id       INTEGER PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    created_at  INTEGER NOT NULL,
    settings    TEXT    NOT NULL DEFAULT '{}',
    downloads   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS downloads (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id          INTEGER NOT NULL,
    url            TEXT,
    title          TEXT,
    kind           TEXT,
    file_id        TEXT,
    file_unique_id TEXT,
    size           INTEGER,
    created_at     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dl_user ON downloads(tg_id, id DESC);

CREATE TABLE IF NOT EXISTS packs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id      INTEGER NOT NULL,
    name       TEXT    NOT NULL UNIQUE,
    title      TEXT    NOT NULL,
    kind       TEXT    NOT NULL,
    emoji_mode TEXT    NOT NULL DEFAULT 'manual',
    crop_mode  TEXT    NOT NULL DEFAULT 'crop',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_packs_user ON packs(tg_id, id DESC);

CREATE TABLE IF NOT EXISTS pack_stickers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    pack_id        INTEGER NOT NULL,
    file_id        TEXT,
    file_unique_id TEXT,
    emoji          TEXT,
    created_at     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ps_pack ON pack_stickers(pack_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_ps_emoji ON pack_stickers(emoji);

CREATE TABLE IF NOT EXISTS inline_cache (
    url        TEXT    NOT NULL,
    height     INTEGER NOT NULL,
    file_id    TEXT    NOT NULL,
    title      TEXT,
    duration   INTEGER,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (url, height)
);
"""

DEFAULT_SETTINGS: dict[str, Any] = {
    "quality": "ask",        # ask | best
    "emoji_mode": "manual",  # manual | random | smart
    "crop_mode": "crop",     # crop | fit | smart
    "autocompress": True,
    "silent": False,
    "lang": "",              # ru | en | "" (определяем по Telegram)
}


async def init() -> None:
    global _conn
    _conn = await aiosqlite.connect(settings.db_path)
    _conn.row_factory = aiosqlite.Row
    await _conn.execute("PRAGMA journal_mode=WAL")
    await _conn.execute("PRAGMA synchronous=NORMAL")
    await _conn.executescript(SCHEMA)
    await _migrate()
    await _conn.commit()


async def _migrate() -> None:
    """Догоняем схему для баз, созданных прошлыми версиями."""
    db = _db()
    rows = await (await db.execute("PRAGMA table_info(packs)")).fetchall()
    columns = {str(row["name"]) for row in rows}
    if "cover_file_id" not in columns:
        await db.execute("ALTER TABLE packs ADD COLUMN cover_file_id TEXT")


async def close() -> None:
    if _conn is not None:
        await _conn.close()


def _db() -> aiosqlite.Connection:
    if _conn is None:
        raise RuntimeError("База не инициализирована: вызовите await db.init()")
    return _conn


# ---------------------------------------------------------------- users

async def get_user(tg_id: int, username: str | None = None, first_name: str | None = None) -> dict[str, Any]:
    db = _db()
    row = await (await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))).fetchone()
    if row is None:
        prefs = json.dumps(DEFAULT_SETTINGS, ensure_ascii=False)
        await db.execute(
            "INSERT OR IGNORE INTO users (tg_id, username, first_name, created_at, settings)"
            " VALUES (?, ?, ?, ?, ?)",
            (tg_id, username, first_name, int(time.time()), prefs),
        )
        await db.commit()
        row = await (await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))).fetchone()
    if row is None:
        return {
            "tg_id": tg_id,
            "username": username,
            "first_name": first_name,
            "downloads": 0,
            "settings": dict(DEFAULT_SETTINGS),
        }

    user = dict(row)
    try:
        prefs = json.loads(user.get("settings") or "{}")
    except json.JSONDecodeError:
        prefs = {}
    user["settings"] = {**DEFAULT_SETTINGS, **prefs}
    if username and username != user.get("username"):
        await db.execute("UPDATE users SET username = ? WHERE tg_id = ?", (username, tg_id))
        await db.commit()
    return user


async def update_settings(tg_id: int, **changes: Any) -> dict[str, Any]:
    user = await get_user(tg_id)
    prefs = {**user["settings"], **changes}
    await _db().execute(
        "UPDATE users SET settings = ? WHERE tg_id = ?",
        (json.dumps(prefs, ensure_ascii=False), tg_id),
    )
    await _db().commit()
    user["settings"] = prefs
    return user


async def bump_downloads(tg_id: int) -> None:
    await _db().execute("UPDATE users SET downloads = downloads + 1 WHERE tg_id = ?", (tg_id,))
    await _db().commit()


async def user_count() -> int:
    row = await (await _db().execute("SELECT COUNT(*) AS c FROM users")).fetchone()
    return int(row["c"]) if row else 0


# ------------------------------------------------------------- downloads

async def add_download(
    tg_id: int,
    url: str | None,
    title: str | None,
    kind: str,
    file_id: str | None = None,
    file_unique_id: str | None = None,
    size: int | None = None,
) -> int:
    db = _db()
    cur = await db.execute(
        """INSERT INTO downloads (tg_id, url, title, kind, file_id, file_unique_id, size, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (tg_id, url, title, kind, file_id, file_unique_id, size, int(time.time())),
    )
    await db.commit()
    return int(cur.lastrowid or 0)


async def recent_downloads(tg_id: int, limit: int = 10) -> list[dict[str, Any]]:
    rows = await (
        await _db().execute(
            "SELECT * FROM downloads WHERE tg_id = ? ORDER BY id DESC LIMIT ?", (tg_id, limit)
        )
    ).fetchall()
    return [dict(r) for r in rows]


async def get_download(dl_id: int, tg_id: int) -> dict[str, Any] | None:
    row = await (
        await _db().execute("SELECT * FROM downloads WHERE id = ? AND tg_id = ?", (dl_id, tg_id))
    ).fetchone()
    return dict(row) if row else None


async def downloads_total() -> int:
    row = await (await _db().execute("SELECT COUNT(*) AS c FROM downloads")).fetchone()
    return int(row["c"]) if row else 0


# ----------------------------------------------------------------- packs

async def create_pack(
    tg_id: int, name: str, title: str, kind: str, emoji_mode: str, crop_mode: str
) -> int:
    db = _db()
    cur = await db.execute(
        """INSERT INTO packs (tg_id, name, title, kind, emoji_mode, crop_mode, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (tg_id, name, title, kind, emoji_mode, crop_mode, int(time.time())),
    )
    await db.commit()
    return int(cur.lastrowid or 0)


async def get_pack(pack_id: int) -> dict[str, Any] | None:
    row = await (await _db().execute("SELECT * FROM packs WHERE id = ?", (pack_id,))).fetchone()
    return dict(row) if row else None


async def pack_by_name(name: str) -> dict[str, Any] | None:
    row = await (await _db().execute("SELECT * FROM packs WHERE name = ?", (name,))).fetchone()
    return dict(row) if row else None


async def user_packs(tg_id: int) -> list[dict[str, Any]]:
    rows = await (
        await _db().execute(
            """SELECT p.*, (SELECT COUNT(*) FROM pack_stickers s WHERE s.pack_id = p.id) AS count
               FROM packs p WHERE p.tg_id = ? ORDER BY p.id DESC""",
            (tg_id,),
        )
    ).fetchall()
    return [dict(r) for r in rows]


async def delete_pack(pack_id: int) -> None:
    db = _db()
    await db.execute("DELETE FROM pack_stickers WHERE pack_id = ?", (pack_id,))
    await db.execute("DELETE FROM packs WHERE id = ?", (pack_id,))
    await db.commit()


async def add_pack_sticker(
    pack_id: int, file_id: str | None, file_unique_id: str | None, emoji: str
) -> int:
    db = _db()
    cur = await db.execute(
        """INSERT INTO pack_stickers (pack_id, file_id, file_unique_id, emoji, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (pack_id, file_id, file_unique_id, emoji, int(time.time())),
    )
    await db.commit()
    return int(cur.lastrowid or 0)


async def set_pack_sticker_file(record_id: int, file_id: str, file_unique_id: str) -> None:
    await _db().execute(
        "UPDATE pack_stickers SET file_id = ?, file_unique_id = ? WHERE id = ?",
        (file_id, file_unique_id, record_id),
    )
    await _db().commit()


async def set_pack_cover(pack_id: int, file_id: str | None) -> None:
    await _db().execute("UPDATE packs SET cover_file_id = ? WHERE id = ?", (file_id, pack_id))
    await _db().commit()


async def pack_sticker_count(pack_id: int) -> int:
    row = await (
        await _db().execute("SELECT COUNT(*) AS c FROM pack_stickers WHERE pack_id = ?", (pack_id,))
    ).fetchone()
    return int(row["c"]) if row else 0


async def pack_stickers(pack_id: int) -> list[dict[str, Any]]:
    rows = await (
        await _db().execute(
            "SELECT * FROM pack_stickers WHERE pack_id = ? ORDER BY id ASC", (pack_id,)
        )
    ).fetchall()
    return [dict(r) for r in rows]


async def pack_used_emoji(pack_id: int) -> set[str]:
    rows = await (
        await _db().execute(
            "SELECT DISTINCT emoji FROM pack_stickers WHERE pack_id = ? AND emoji IS NOT NULL",
            (pack_id,),
        )
    ).fetchall()
    return {str(r["emoji"]) for r in rows if r["emoji"]}


async def remove_pack_sticker_by_file(file_id: str) -> None:
    await _db().execute("DELETE FROM pack_stickers WHERE file_id = ?", (file_id,))
    await _db().commit()


async def search_stickers(query: str, limit: int = 20) -> list[dict[str, Any]]:
    like = f"%{query}%"
    rows = await (
        await _db().execute(
            """SELECT s.*, p.name AS pack_name, p.title AS pack_title
               FROM pack_stickers s JOIN packs p ON p.id = s.pack_id
               WHERE s.emoji LIKE ? OR p.title LIKE ?
               ORDER BY s.id DESC LIMIT ?""",
            (like, like, limit),
        )
    ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------ inline-кэш

async def save_inline_cached(
    url: str,
    height: int,
    file_id: str,
    title: str | None = None,
    duration: int = 0,
) -> None:
    """Запоминаем file_id скачанного видео: в inline его можно отдать мгновенно."""
    if not url or not file_id or height <= 0:
        return
    await _db().execute(
        """INSERT INTO inline_cache (url, height, file_id, title, duration, created_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(url, height) DO UPDATE SET
             file_id = excluded.file_id,
             title = excluded.title,
             duration = excluded.duration,
             created_at = excluded.created_at""",
        (url, int(height), file_id, title, int(duration or 0), int(time.time())),
    )
    await _db().commit()


async def inline_cached(url: str) -> list[dict[str, Any]]:
    rows = await (
        await _db().execute(
            "SELECT * FROM inline_cache WHERE url = ? ORDER BY height DESC", (url,)
        )
    ).fetchall()
    return [dict(r) for r in rows]


async def prune_inline_cache(max_age_days: int = 30) -> None:
    cutoff = int(time.time()) - max_age_days * 86400
    await _db().execute("DELETE FROM inline_cache WHERE created_at < ?", (cutoff,))
    await _db().commit()
