/**
 * Emoji rendering and the picker's data layer.
 *
 * Glyphs come from a self-hosted Noto Color Emoji subset so Windows shows
 * Android-style emoji; on Apple devices the platform's own Apple Color Emoji
 * wins because it comes first in the font stack. Every glyph is wrapped in
 * `.emoji`, which is what carries that stack.
 */
import type { ReactNode } from "react";
import type { Lang } from "./i18n";

type RawItem = [string, string, number, string, string[]];
type RawData = { groups: [number, string][]; items: RawItem[] };

export type EmojiItem = {
  char: string;
  label: string;
  group: number;
  keywords: string;
  skins: string[];
};

export type EmojiGroup = {
  id: number;
  title: string;
  items: EmojiItem[];
};

export type EmojiData = {
  groups: EmojiGroup[];
  index: EmojiItem[];
};

const loaders: Record<Lang, () => Promise<unknown>> = {
  ru: () => import("./data/emoji-ru.json"),
  en: () => import("./data/emoji-en.json"),
};

const cache = new Map<Lang, Promise<EmojiData>>();

export function loadEmoji(lang: Lang): Promise<EmojiData> {
  const cached = cache.get(lang);
  if (cached) return cached;
  const task = loaders[lang]()
    .then((module) => {
      const raw = (module as { default: RawData }).default;
      const groups: EmojiGroup[] = raw.groups.map(([id, title]) => ({
        id,
        title,
        items: [],
      }));
      const byId = new Map(groups.map((group) => [group.id, group]));
      const index: EmojiItem[] = [];
      for (const [char, label, group, keywords, skins] of raw.items) {
        const item: EmojiItem = { char, label, group, keywords, skins };
        byId.get(group)?.items.push(item);
        index.push(item);
      }
      return { groups: groups.filter((group) => group.items.length > 0), index };
    })
    .catch((error) => {
      cache.delete(lang);
      throw error;
    });
  cache.set(lang, task);
  return task;
}

/** The char for a base emoji at skin tone 0–5 (0 = the author's default). */
export function toned(item: EmojiItem, tone: number): string {
  return tone > 0 && item.skins[tone - 1] ? item.skins[tone - 1] : item.char;
}

export function Emoji({
  children,
  className = "",
  title,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span className={`emoji${className ? ` ${className}` : ""}`} translate="no" title={title}>
      {children}
    </span>
  );
}

export const TONES = ["🏻", "🏼", "🏽", "🏾", "🏿"] as const;

const TONE_KEY = "vavilong.tone";

export function readTone(): number {
  const raw = Number(localStorage.getItem(TONE_KEY));
  return Number.isInteger(raw) && raw >= 0 && raw <= 5 ? raw : 0;
}

export function writeTone(tone: number): void {
  try {
    localStorage.setItem(TONE_KEY, String(tone));
  } catch {
    /* private mode */
  }
}
