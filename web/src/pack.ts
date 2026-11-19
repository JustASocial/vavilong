/**
 * Draft sticker pack kept in IndexedDB and exported as a .tgspack archive.
 *
 * The archive is a plain ZIP (stored entries, no compression — WebP is already
 * compressed) with `pack.json` + `stickers/NNN.webp`. Only our bot understands
 * the extension; Telegram treats it as an ordinary document.
 */

import { useSyncExternalStore } from "react";

export const MAX_STICKERS = 120;
export const MAX_ARCHIVE = 19 * 1024 * 1024;

export type DraftSticker = {
  id: string;
  emoji: string;
  size: number;
  added: number;
  blob: Blob;
};

export type DraftPack = {
  ready: boolean;
  title: string;
  stickers: DraftSticker[];
};

const DB_NAME = "vavilong-pack";
const DB_VERSION = 1;

let draft: DraftPack = { ready: false, title: "", stickers: [] };
let active: IDBDatabase | null = null;
let opening: Promise<IDBDatabase> | null = null;
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

function request<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function database(): Promise<IDBDatabase> {
  if (active) return Promise.resolve(active);
  if (opening) return opening;
  opening = new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains("stickers")) {
        db.createObjectStore("stickers", { keyPath: "id" });
      }
      if (!db.objectStoreNames.contains("meta")) db.createObjectStore("meta");
    };
    req.onsuccess = () => {
      active = req.result;
      resolve(req.result);
    };
    req.onerror = () => reject(req.error);
  });
  return opening;
}

type Meta = { title: string; order: string[] };

async function persistMeta(): Promise<void> {
  try {
    const db = await database();
    const meta: Meta = {
      title: draft.title,
      order: draft.stickers.map((sticker) => sticker.id),
    };
    await request(db.transaction("meta", "readwrite").objectStore("meta").put(meta, "state"));
  } catch {
    /* private mode / quota: the draft still works in memory */
  }
}

async function persistSticker(sticker: DraftSticker): Promise<void> {
  try {
    const db = await database();
    await request(
      db.transaction("stickers", "readwrite").objectStore("stickers").put(sticker),
    );
  } catch {
    /* ignore */
  }
}

let loading: Promise<void> | null = null;

export function loadPack(): Promise<void> {
  if (loading) return loading;
  loading = (async () => {
    try {
      const db = await database();
      const [meta, rows] = await Promise.all([
        request<Meta | undefined>(db.transaction("meta").objectStore("meta").get("state")),
        request<DraftSticker[]>(db.transaction("stickers").objectStore("stickers").getAll()),
      ]);
      const byId = new Map(rows.map((row) => [row.id, row]));
      const ordered: DraftSticker[] = [];
      for (const id of meta?.order ?? []) {
        const row = byId.get(id);
        if (row) {
          ordered.push(row);
          byId.delete(id);
        }
      }
      for (const row of byId.values()) ordered.push(row);
      ordered.sort((a, b) => a.added - b.added);
      draft = {
        ready: true,
        title: meta?.title ?? "",
        stickers: ordered,
      };
    } catch {
      draft = { ...draft, ready: true };
    }
    emit();
  })();
  return loading;
}

export function subscribePack(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function snapshot(): DraftPack {
  return draft;
}

export function useDraftPack(): DraftPack {
  return useSyncExternalStore(subscribePack, snapshot, snapshot);
}

export function setPackTitle(title: string): void {
  draft = { ...draft, title: title.slice(0, 64) };
  emit();
  void persistMeta();
}

export async function addSticker(blob: Blob, emoji: string): Promise<boolean> {
  await loadPack();
  if (draft.stickers.length >= MAX_STICKERS) return false;
  const sticker: DraftSticker = {
    id:
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `s-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    emoji: emoji || "🙂",
    size: blob.size,
    added: Date.now(),
    blob,
  };
  draft = { ...draft, stickers: [...draft.stickers, sticker] };
  emit();
  void persistSticker(sticker);
  void persistMeta();
  return true;
}

export function removeSticker(id: string): void {
  draft = { ...draft, stickers: draft.stickers.filter((sticker) => sticker.id !== id) };
  emit();
  void persistMeta();
  void database()
    .then((db) => request(db.transaction("stickers", "readwrite").objectStore("stickers").delete(id)))
    .catch(() => undefined);
}

export function setStickerEmoji(id: string, emoji: string): void {
  const stickers = draft.stickers.map((sticker) =>
    sticker.id === id ? { ...sticker, emoji: emoji || "🙂" } : sticker,
  );
  draft = { ...draft, stickers };
  emit();
  const changed = stickers.find((sticker) => sticker.id === id);
  if (changed) void persistSticker(changed);
}

export function moveSticker(id: string, delta: -1 | 1): void {
  const index = draft.stickers.findIndex((sticker) => sticker.id === id);
  const target = index + delta;
  if (index < 0 || target < 0 || target >= draft.stickers.length) return;
  const stickers = [...draft.stickers];
  [stickers[index], stickers[target]] = [stickers[target], stickers[index]];
  draft = { ...draft, stickers };
  emit();
  void persistMeta();
}

export function clearPack(): void {
  draft = { ...draft, title: "", stickers: [] };
  emit();
  void database()
    .then(async (db) => {
      await request(db.transaction("stickers", "readwrite").objectStore("stickers").clear());
      await request(db.transaction("meta", "readwrite").objectStore("meta").delete("state"));
    })
    .catch(() => undefined);
}

export function packBytes(): number {
  return draft.stickers.reduce((total, sticker) => total + sticker.size, 0);
}

export function firstCharacter(value: string): string {
  const clean = value.trim();
  if (!clean) return "";
  const Segmenter = (
    Intl as unknown as {
      Segmenter?: new (
        locale: string,
        options: object,
      ) => { segment: (input: string) => Iterable<{ segment: string }> };
    }
  ).Segmenter;
  if (typeof Segmenter === "function") {
    const segments = new Segmenter("en", { granularity: "grapheme" }).segment(clean);
    for (const item of segments) return item.segment;
  }
  return Array.from(clean)[0] ?? "";
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function slugify(value: string): string {
  const map: Record<string, string> = {
    а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "e", ж: "zh", з: "z",
    и: "i", й: "y", к: "k", л: "l", м: "m", н: "n", о: "o", п: "p", р: "r",
    с: "s", т: "t", у: "u", ф: "f", х: "h", ц: "c", ч: "ch", ш: "sh", щ: "sch",
    ъ: "", ы: "y", ь: "", э: "e", ю: "yu", я: "ya",
  };
  const text = value
    .toLowerCase()
    .split("")
    .map((char) => map[char] ?? char)
    .join("")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return text.slice(0, 40) || "pack";
}

/* ------------------------------------------------------------------- ZIP */

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let index = 0; index < 256; index += 1) {
    let value = index;
    for (let bit = 0; bit < 8; bit += 1) {
      value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
    }
    table[index] = value >>> 0;
  }
  return table;
})();

function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (let index = 0; index < bytes.length; index += 1) {
    crc = CRC_TABLE[(crc ^ bytes[index]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

const encoder = new TextEncoder();

function dosStamp(): { time: number; date: number } {
  const now = new Date();
  return {
    time: (now.getHours() << 11) | (now.getMinutes() << 5) | (now.getSeconds() >> 1),
    date: ((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate(),
  };
}

export type Archive = { blob: Blob; name: string; size: number };

export async function buildArchive(pack: DraftPack = draft): Promise<Archive> {
  const files: { name: string; data: Uint8Array<ArrayBuffer> }[] = [];
  const manifest = {
    format: "tgspack",
    version: 1,
    title: pack.title.trim() || "Vavilong pack",
    created_at: new Date().toISOString(),
    count: pack.stickers.length,
    stickers: [] as { file: string; emoji: string }[],
  };

  for (let index = 0; index < pack.stickers.length; index += 1) {
    const sticker = pack.stickers[index];
    const file = `stickers/${String(index + 1).padStart(3, "0")}.webp`;
    manifest.stickers.push({ file, emoji: sticker.emoji });
    files.push({ name: file, data: new Uint8Array(await sticker.blob.arrayBuffer()) });
  }
  files.unshift({ name: "pack.json", data: encoder.encode(JSON.stringify(manifest, null, 2)) });

  const stamp = dosStamp();
  const chunks: BlobPart[] = [];
  const central: Uint8Array<ArrayBuffer>[] = [];
  let offset = 0;

  for (const file of files) {
    const name = encoder.encode(file.name);
    const crc = crc32(file.data);

    const local = new Uint8Array(30 + name.length);
    const localView = new DataView(local.buffer);
    localView.setUint32(0, 0x04034b50, true);
    localView.setUint16(4, 20, true);
    localView.setUint16(6, 0x0800, true);
    localView.setUint16(8, 0, true);
    localView.setUint16(10, stamp.time, true);
    localView.setUint16(12, stamp.date, true);
    localView.setUint32(14, crc, true);
    localView.setUint32(18, file.data.length, true);
    localView.setUint32(22, file.data.length, true);
    localView.setUint16(26, name.length, true);
    localView.setUint16(28, 0, true);
    local.set(name, 30);
    chunks.push(local, file.data);

    const entry = new Uint8Array(46 + name.length);
    const entryView = new DataView(entry.buffer);
    entryView.setUint32(0, 0x02014b50, true);
    entryView.setUint16(4, 20, true);
    entryView.setUint16(6, 20, true);
    entryView.setUint16(8, 0x0800, true);
    entryView.setUint16(10, 0, true);
    entryView.setUint16(12, stamp.time, true);
    entryView.setUint16(14, stamp.date, true);
    entryView.setUint32(16, crc, true);
    entryView.setUint32(20, file.data.length, true);
    entryView.setUint32(24, file.data.length, true);
    entryView.setUint16(28, name.length, true);
    entryView.setUint32(42, offset, true);
    entry.set(name, 46);
    central.push(entry);

    offset += local.length + file.data.length;
  }

  const centralSize = central.reduce((total, entry) => total + entry.length, 0);
  const end = new Uint8Array(22);
  const endView = new DataView(end.buffer);
  endView.setUint32(0, 0x06054b50, true);
  endView.setUint16(8, files.length, true);
  endView.setUint16(10, files.length, true);
  endView.setUint32(12, centralSize, true);
  endView.setUint32(16, offset, true);

  const blob = new Blob([...chunks, ...central, end], { type: "application/octet-stream" });
  return { blob, name: `${slugify(pack.title)}.tgspack`, size: blob.size };
}
