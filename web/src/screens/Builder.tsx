import { useEffect, useState } from "react";
import {
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Download,
  Loader2,
  PackagePlus,
  Plus,
  Send,
  Trash2,
  X,
} from "lucide-react";
import type { Screen, Translate } from "../App";
import { AUTH_ERROR, api } from "../api";
import { EmojiField } from "../components/EmojiField";
import type { Lang } from "../i18n";
import {
  MAX_ARCHIVE,
  MAX_STICKERS,
  buildArchive,
  clearPack,
  formatSize,
  moveSticker,
  packBytes,
  removeSticker,
  setPackTitle,
  setStickerEmoji,
  useDraftPack,
  type DraftSticker,
} from "../pack";
import { notify, openBot } from "../telegram";

type Props = {
  t: Translate;
  lang: Lang;
  onNavigate: (screen: Screen) => void;
};

type Busy = "" | "export" | "send";

function Thumb({ blob, alt = "" }: { blob: Blob; alt?: string }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    const next = URL.createObjectURL(blob);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [blob]);
  return url ? <img src={url} alt={alt} loading="lazy" /> : null;
}

export function Builder({ t, lang, onNavigate }: Props) {
  const draft = useDraftPack();
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState<Busy>("");
  const [status, setStatus] = useState("");
  const [bad, setBad] = useState(false);
  const [auth, setAuth] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);

  const active = draft.stickers.find((sticker) => sticker.id === selected) ?? null;
  const activeIndex = active ? draft.stickers.indexOf(active) : -1;
  const count = draft.stickers.length;
  const total = packBytes();

  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelected(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active]);

  useEffect(() => {
    if (!confirmClear) return;
    const timer = setTimeout(() => setConfirmClear(false), 3500);
    return () => clearTimeout(timer);
  }, [confirmClear]);

  const open = (sticker: DraftSticker) => {
    setSelected(sticker.id);
    notify("success");
  };

  const clearStatus = () => {
    setStatus("");
    setBad(false);
    setAuth(false);
  };

  const download = async () => {
    if (!count || busy) return;
    setBusy("export");
    clearStatus();
    try {
      const archive = await buildArchive(draft);
      const url = URL.createObjectURL(archive.blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = archive.name;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      notify("success");
    } catch {
      setBad(true);
      setStatus(t("builder.failed"));
    } finally {
      setBusy("");
    }
  };

  const send = async () => {
    if (!count || busy) return;
    setBusy("send");
    clearStatus();
    try {
      const archive = await buildArchive(draft);
      if (archive.size > MAX_ARCHIVE) {
        setBad(true);
        setStatus(t("builder.tooBig"));
        return;
      }
      await api.sendPack(archive.blob, draft.title.trim() || "Vavilong pack");
      setStatus(t("builder.sent"));
      notify("success");
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : String(exc);
      setBad(true);
      if (message === AUTH_ERROR) {
        setAuth(true);
        setStatus(t("builder.auth"));
      } else if (message === "size") {
        setStatus(t("builder.tooBig"));
      } else {
        setStatus(t("builder.sendFailed"));
      }
      notify("error");
    } finally {
      setBusy("");
    }
  };

  const clearAll = () => {
    if (!confirmClear) {
      setConfirmClear(true);
      return;
    }
    clearPack();
    setConfirmClear(false);
    setSelected(null);
    notify("warning");
  };

  return (
    <>
      <div className="page-head">
        <h1>{t("builder.title")}</h1>
        <p>
          {count} / {MAX_STICKERS}
        </p>
      </div>

      <section className="section first">
        <div className="builder-bar">
          <label className="field builder-name">
            <span className="field-label">{t("builder.name")}</span>
            <input
              className="text-input"
              value={draft.title}
              maxLength={64}
              placeholder={t("builder.placeholder")}
              onChange={(event) => setPackTitle(event.target.value)}
            />
          </label>
          <button type="button" className="btn secondary" onClick={() => onNavigate("studio")}>
            <Plus size={16} strokeWidth={1.8} aria-hidden />
            {t("builder.add")}
          </button>
        </div>

        <div className="builder-meta">
          <span className="chip mono">
            {count} / {MAX_STICKERS}
          </span>
          <span className="chip mono">{formatSize(total)}</span>
          {count > 0 && (
            <button
              type="button"
              className={`btn ghost${confirmClear ? " danger" : ""}`}
              onClick={clearAll}
            >
              <Trash2 size={15} strokeWidth={1.8} aria-hidden />
              {confirmClear ? t("builder.confirmClear") : t("builder.clear")}
            </button>
          )}
        </div>
      </section>

      {count > 0 ? (
        <section className="section">
          <div className="section-head">
            <h2>{t("builder.stickers")}</h2>
            <p>{t("builder.hint")}</p>
          </div>
          <div className="pack-grid builder-grid">
            {draft.stickers.map((sticker) => (
              <button
                type="button"
                key={sticker.id}
                className="tile"
                onClick={() => open(sticker)}
                aria-label={`${t("builder.edit")}: ${sticker.emoji}`}
              >
                <Thumb blob={sticker.blob} />
                <span className="emoji" aria-hidden>
                  {sticker.emoji}
                </span>
              </button>
            ))}
            {count < MAX_STICKERS && (
              <button
                type="button"
                className="tile placeholder"
                onClick={() => onNavigate("studio")}
                aria-label={t("builder.add")}
              >
                <Plus size={22} strokeWidth={1.7} aria-hidden />
              </button>
            )}
          </div>
        </section>
      ) : (
        <section className="section">
          <div className="builder-empty">
            <PackagePlus size={30} strokeWidth={1.5} aria-hidden />
            <h2>{t("builder.empty.title")}</h2>
            <p>{t("builder.empty.text")}</p>
            <button type="button" className="btn" onClick={() => onNavigate("studio")}>
              <Plus size={16} strokeWidth={1.8} aria-hidden />
              {t("builder.add")}
            </button>
          </div>
        </section>
      )}

      <section className="section">
        <div className="section-head">
          <h2>{t("builder.export")}</h2>
          <p>{t("builder.note")}</p>
        </div>
        <div className="row">
          <button
            type="button"
            className="btn secondary"
            disabled={!count || !draft.ready || busy !== ""}
            onClick={() => void download()}
          >
            {busy === "export" ? (
              <Loader2 size={16} strokeWidth={1.8} className="spin" aria-hidden />
            ) : (
              <Download size={16} strokeWidth={1.7} aria-hidden />
            )}
            {busy === "export" ? t("builder.exporting") : t("builder.download")}
          </button>
          <button
            type="button"
            className="btn"
            disabled={!count || !draft.ready || busy !== ""}
            onClick={() => void send()}
          >
            {busy === "send" ? (
              <Loader2 size={16} strokeWidth={1.8} className="spin" aria-hidden />
            ) : (
              <Send size={16} strokeWidth={1.7} aria-hidden />
            )}
            {busy === "send" ? t("builder.sending") : t("builder.send")}
          </button>
        </div>

        {status && (
          <p className={`status ${bad ? "bad" : ""}`} role="status">
            {status}
          </p>
        )}

        {auth && (
          <button type="button" className="btn secondary" onClick={() => openBot("app_studio")}>
            <Send size={16} strokeWidth={1.7} aria-hidden />
            {t("studio.openBot")}
          </button>
        )}

        {count > 0 && total > MAX_ARCHIVE && (
          <p className="notice">
            <AlertCircle size={16} strokeWidth={1.7} aria-hidden />
            <span>{t("builder.tooBig")}</span>
          </p>
        )}
      </section>

      {active && (
        <div
          className="sheet"
          role="dialog"
          aria-modal="true"
          aria-label={t("builder.edit")}
          onClick={(event) => {
            if (event.target === event.currentTarget) setSelected(null);
          }}
        >
          <div className="sheet-body">
            <div className="controls-head">
              <h3>{t("builder.edit")}</h3>
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
              <Thumb blob={active.blob} />
            </div>

            <div className="field">
              <span className="field-label">{t("studio.emoji")}</span>
              <EmojiField
                lang={lang}
                t={t}
                value={active.emoji}
                title={t("builder.edit")}
                onChange={(char) => setStickerEmoji(active.id, char)}
              />
            </div>

            <div className="row">
              <button
                type="button"
                className="btn secondary"
                disabled={activeIndex <= 0}
                aria-label={t("builder.left")}
                onClick={() => moveSticker(active.id, -1)}
              >
                <ChevronLeft size={16} strokeWidth={1.8} aria-hidden />
              </button>
              <button
                type="button"
                className="btn secondary"
                disabled={activeIndex >= count - 1}
                aria-label={t("builder.right")}
                onClick={() => moveSticker(active.id, 1)}
              >
                <ChevronRight size={16} strokeWidth={1.8} aria-hidden />
              </button>
              <button
                type="button"
                className="btn ghost"
                onClick={() => {
                  removeSticker(active.id);
                  setSelected(null);
                  notify("warning");
                }}
              >
                <Trash2 size={16} strokeWidth={1.8} aria-hidden />
                {t("builder.remove")}
              </button>
            </div>

            <button type="button" className="btn block" onClick={() => setSelected(null)}>
              {t("builder.done")}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
