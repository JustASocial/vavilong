import { useEffect, useState } from "react";
import {
  AlertCircle,
  Boxes,
  Copy,
  ExternalLink,
  Image as ImageIcon,
  Loader2,
  Search,
  Send,
  Video,
  X,
} from "lucide-react";
import type { Translate } from "../App";
import { AUTH_ERROR, api, packNameFromInput, type Pack, type Sticker } from "../api";
import { notify, tg } from "../telegram";

type Props = {
  t: Translate;
};

function stickerLabel(sticker: Sticker): string {
  if (sticker.is_video) return "video";
  if (sticker.is_animated) return "animated";
  return "static";
}

export function Packs({ t }: Props) {
  const [value, setValue] = useState("");
  const [loading, setLoading] = useState(false);
  const [pack, setPack] = useState<Pack | null>(null);
  const [error, setError] = useState("");
  const [auth, setAuth] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [sent, setSent] = useState(false);
  const [copied, setCopied] = useState(false);

  const active = selected === null ? null : pack?.stickers[selected] ?? null;

  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelected(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active]);

  const load = async () => {
    const name = packNameFromInput(value);
    if (!name) {
      setError(t("packs.hint"));
      return;
    }

    setLoading(true);
    setError("");
    setAuth(false);
    setPack(null);
    setSelected(null);
    try {
      const data = await api.pack(name);
      if (!data.stickers.length) {
        setError(t("packs.empty"));
      } else {
        setPack(data);
      }
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : String(exc);
      if (message === AUTH_ERROR) {
        setAuth(true);
      } else {
        setError(t("packs.error"));
      }
    } finally {
      setLoading(false);
    }
  };

  const send = async () => {
    if (!active) return;
    try {
      await api.send(active.file_id);
      setSent(true);
      notify("success");
      setTimeout(() => setSent(false), 2200);
    } catch {
      notify("error");
    }
  };

  const copy = async () => {
    if (!pack) return;
    const link = `https://t.me/addstickers/${pack.name}`;
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      notify("success");
      setTimeout(() => setCopied(false), 2200);
    } catch {
      notify("error");
    }
  };

  const openInTelegram = () => {
    if (!pack) return;
    const link = `https://t.me/addstickers/${pack.name}`;
    if (tg?.openTelegramLink) tg.openTelegramLink(link);
    else window.open(link, "_blank", "noopener");
  };

  return (
    <>
      <div className="page-head">
        <h1>{t("packs.title")}</h1>
        <p>{t("packs.lede")}</p>
      </div>

      <section className="section first">
        <form
          className="row"
          onSubmit={(event) => {
            event.preventDefault();
            void load();
          }}
        >
          <label className="search">
            <Search size={18} strokeWidth={1.7} aria-hidden />
            <span className="sr-only">{t("packs.placeholder")}</span>
            <input
              id="pack-input"
              placeholder={t("packs.placeholder")}
              value={value}
              autoComplete="off"
              spellCheck={false}
              onChange={(event) => setValue(event.target.value)}
            />
          </label>
          <button type="submit" className="btn" disabled={loading || !value.trim()}>
            {loading ? (
              <Loader2 size={16} strokeWidth={1.8} className="spin" aria-hidden />
            ) : (
              <Search size={16} strokeWidth={1.8} aria-hidden />
            )}
            {t("packs.load")}
          </button>
        </form>

        {auth && (
          <div className="notice" role="status" style={{ marginTop: "var(--s-3)" }}>
            <AlertCircle size={16} strokeWidth={1.7} aria-hidden />
            <span>{t("packs.auth")}</span>
          </div>
        )}
        {error && (
          <div className="notice" role="status" style={{ marginTop: "var(--s-3)" }}>
            <AlertCircle size={16} strokeWidth={1.7} aria-hidden />
            <span>{error}</span>
          </div>
        )}
      </section>

      {loading && !pack && (
        <section className="section">
          <p className="muted small">{t("packs.loading")}</p>
          <div className="pack-grid">
            {Array.from({ length: 12 }).map((_, index) => (
              <div className="skeleton" key={index} />
            ))}
          </div>
        </section>
      )}

      {pack && (
        <section className="section">
          <div className="pack-head">
            <div>
              <h2>{pack.title}</h2>
              <div className="pack-meta">
                <span className="mono">{pack.name}</span>
                <span>
                  {pack.count} {t("packs.count")}
                </span>
                <span>
                  {pack.kind === "video" ? (
                    <>
                      <Video size={13} strokeWidth={1.8} aria-hidden /> {t("packs.video")}
                    </>
                  ) : pack.kind === "animated" ? (
                    t("packs.animated")
                  ) : (
                    <>
                      <ImageIcon size={13} strokeWidth={1.8} aria-hidden /> {t("packs.static")}
                    </>
                  )}
                </span>
              </div>
            </div>
            <div className="row">
              <button type="button" className="btn secondary" onClick={copy}>
                <Copy size={16} strokeWidth={1.7} aria-hidden />
                {copied ? t("packs.copied") : t("packs.copy")}
              </button>
              <button type="button" className="btn secondary" onClick={openInTelegram}>
                <ExternalLink size={16} strokeWidth={1.7} aria-hidden />
                {t("packs.open")}
              </button>
            </div>
          </div>

          <div className="pack-grid">
            {pack.stickers.map((sticker, index) => (
              <button
                type="button"
                key={sticker.file_id}
                className="tile"
                onClick={() => {
                  setSelected(index);
                  setSent(false);
                }}
                aria-label={`${stickerLabel(sticker)} ${sticker.emoji}`}
              >
                <img src={sticker.thumb} alt="" loading="lazy" />
                <span className="emoji" aria-hidden>
                  {sticker.emoji}
                </span>
              </button>
            ))}
          </div>
        </section>
      )}

      {active && (
        <div
          className="sheet"
          role="dialog"
          aria-modal="true"
          aria-label={pack?.title ?? ""}
          onClick={(event) => {
            if (event.target === event.currentTarget) setSelected(null);
          }}
        >
          <div className="sheet-body">
            <div className="controls-head">
              <h3>{pack?.title}</h3>
              <button
                type="button"
                className="icon-btn"
                aria-label={t("packs.close")}
                onClick={() => setSelected(null)}
              >
                <X size={17} strokeWidth={1.8} aria-hidden />
              </button>
            </div>

            <div className="sheet-media">
              {active.is_video ? (
                <video src={active.full} autoPlay loop muted playsInline />
              ) : (
                <img src={active.full} alt="" />
              )}
            </div>

            <div className="kv">
              <div>
                <span>{t("packs.count")}</span>
                <b>
                  {active.width} × {active.height}
                </b>
              </div>
              <div>
                <span>{t("packs.send")}</span>
                <b>{active.is_video ? t("packs.video") : t("packs.static")}</b>
              </div>
            </div>

            <div className="row">
              <button type="button" className="btn" onClick={() => void send()}>
                <Send size={16} strokeWidth={1.7} aria-hidden />
                {sent ? t("packs.sent") : t("packs.send")}
              </button>
              <button
                type="button"
                className="btn secondary"
                onClick={() => setSelected(null)}
              >
                {t("packs.close")}
              </button>
            </div>
          </div>
        </div>
      )}

      {!pack && !loading && !auth && (
        <section className="section">
          <div className="notice">
            <Boxes size={16} strokeWidth={1.7} aria-hidden />
            <span>{t("packs.first")}</span>
          </div>
        </section>
      )}
    </>
  );
}
