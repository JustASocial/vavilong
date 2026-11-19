import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Search, X } from "lucide-react";
import type { Translate } from "../App";
import {
  Emoji,
  TONES,
  loadEmoji,
  readTone,
  toned,
  writeTone,
  type EmojiData,
  type EmojiItem,
} from "../emoji";
import type { Lang } from "../i18n";
import { WireCube } from "./WireCube";

type Props = {
  lang: Lang;
  t: Translate;
  value: string;
  title?: string;
  onPick: (char: string) => void;
  onClose: () => void;
};

const TONE_KEYS = ["emoji.tone.0", "emoji.tone.1", "emoji.tone.2", "emoji.tone.3", "emoji.tone.4", "emoji.tone.5"];

function findGroup(data: EmojiData, value: string): number | null {
  const hit = data.index.find((item) => item.char === value || item.skins.includes(value));
  return hit ? hit.group : null;
}

function matches(item: EmojiItem, query: string): boolean {
  return item.label.includes(query) || item.keywords.includes(query);
}

export function EmojiPicker({ lang, t, value, title, onPick, onClose }: Props) {
  const [data, setData] = useState<EmojiData | null>(null);
  const [failed, setFailed] = useState(false);
  const [query, setQuery] = useState("");
  const [tone, setTone] = useState(readTone);
  const [group, setGroup] = useState<number | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let alive = true;
    loadEmoji(lang)
      .then((next) => {
        if (!alive) return;
        setData(next);
        setGroup(findGroup(next, value) ?? next.groups[0]?.id ?? 0);
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
    };
  }, [lang, value]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    // Focusing on touch opens the on-screen keyboard, which squeezes the sheet;
    // desktop users get the cursor ready instead.
    const fine = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
    if (!fine || window.innerWidth < 800) return;
    const timer = setTimeout(() => searchRef.current?.focus(), 60);
    return () => clearTimeout(timer);
  }, []);

  const pickTone = (next: number) => {
    setTone(next);
    writeTone(next);
  };

  const pickRandom = () => {
    if (!data || data.index.length === 0) return;
    const item = data.index[Math.floor(Math.random() * data.index.length)];
    onPick(toned(item, tone));
  };

  const items = useMemo(() => {
    if (!data) return [];
    const needle = query.trim().toLowerCase();
    if (needle) return data.index.filter((item) => matches(item, needle)).slice(0, 320);
    return data.groups.find((entry) => entry.id === group)?.items ?? [];
  }, [data, group, query]);

  return (
    <div
      className="sheet emoji-sheet"
      role="dialog"
      aria-modal="true"
      aria-label={title ?? t("emoji.title")}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="sheet-body emoji-panel">
        <div className="controls-head">
          <h3>{title ?? t("emoji.title")}</h3>
          <button
            type="button"
            className="emoji-cube"
            aria-label={t("emoji.title")}
            disabled={!data}
            onClick={pickRandom}
          >
            <span className="emoji-cube-body">
              <WireCube size={28} />
            </span>
          </button>
          <button type="button" className="icon-btn emoji-close" aria-label={t("packs.close")} onClick={onClose}>
            <X size={17} strokeWidth={1.8} aria-hidden />
          </button>
        </div>

        <div className="search emoji-search">
          <Search size={15} strokeWidth={1.7} aria-hidden />
          <input
            ref={searchRef}
            value={query}
            placeholder={t("emoji.search")}
            aria-label={t("emoji.search")}
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => setQuery(event.target.value)}
          />
          {query && (
            <button type="button" className="icon-btn" aria-label={t("emoji.clear")} onClick={() => setQuery("")}>
              <X size={14} strokeWidth={1.8} aria-hidden />
            </button>
          )}
        </div>

        <div className="emoji-tones" role="group" aria-label={t("emoji.tone")}>
          {[0, 1, 2, 3, 4, 5].map((index) => (
            <button
              key={index}
              type="button"
              className={`emoji-tone${tone === index ? " active" : ""}`}
              aria-label={t(TONE_KEYS[index])}
              aria-pressed={tone === index}
              title={t(TONE_KEYS[index])}
              onClick={() => pickTone(index)}
            >
              {index === 0 ? "✋" : `✋${TONES[index - 1]}`}
            </button>
          ))}
        </div>

        {!query && data && (
          <div className="emoji-tabs" role="tablist">
            {data.groups.map((entry) => (
              <button
                key={entry.id}
                type="button"
                role="tab"
                aria-selected={group === entry.id}
                className={`emoji-tab${group === entry.id ? " active" : ""}`}
                onClick={() => setGroup(entry.id)}
              >
                {entry.title}
              </button>
            ))}
          </div>
        )}

        <div className="emoji-scroll">
          {failed && <p className="status bad">{t("emoji.failed")}</p>}
          {!failed && !data && (
            <p className="status">
              <Loader2 size={15} strokeWidth={1.8} className="spin" aria-hidden />
              {t("emoji.loading")}
            </p>
          )}
          {data && items.length === 0 && <p className="status">{t("emoji.none")}</p>}
          {data && items.length > 0 && (
            <div className="emoji-grid">
              {items.map((item) => {
                const char = toned(item, tone);
                return (
                  <button
                    key={item.char}
                    type="button"
                    className={`emoji-cell${char === value ? " active" : ""}`}
                    aria-label={item.label}
                    title={item.label}
                    onClick={() => onPick(char)}
                  >
                    <Emoji>{char}</Emoji>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
