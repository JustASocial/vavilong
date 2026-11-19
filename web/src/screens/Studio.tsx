import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import {
  Download,
  ImageUp,
  Loader2,
  Maximize2,
  MoveVertical,
  PackagePlus,
  RotateCcw,
  Scan,
  Send,
  ShieldCheck,
} from "lucide-react";
import type { Screen, Translate } from "../App";
import { AUTH_ERROR, api } from "../api";
import { EmojiField } from "../components/EmojiField";
import { Emoji } from "../emoji";
import type { Lang } from "../i18n";
import { MAX_STICKERS, addSticker, firstCharacter, useDraftPack } from "../pack";
import { notify, openBot } from "../telegram";

type Props = {
  t: Translate;
  lang: Lang;
  onNavigate: (screen: Screen) => void;
};

type Mode = "fill" | "fit" | "top";
type Kind = "image" | "video" | "";

type Artifact = {
  blob: Blob;
  url: string;
  size: number;
};

const CANVAS = 512;
const MAX_BYTES = 512 * 1024;
const QUALITIES = [0.86, 0.78, 0.7, 0.62, 0.54, 0.46, 0.38];

const MODES: { id: Mode; key: string; icon: typeof Scan }[] = [
  { id: "fill", key: "studio.mode.fill", icon: Maximize2 },
  { id: "fit", key: "studio.mode.fit", icon: Scan },
  { id: "top", key: "studio.mode.top", icon: MoveVertical },
];

function canvasToBlob(canvas: HTMLCanvasElement, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, "image/webp", quality));
}

function kilobytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(0)} KB`;
}

async function toBase64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
  }
  return btoa(binary);
}

export function Studio({ t, lang, onNavigate }: Props) {
  const draft = useDraftPack();
  const [kind, setKind] = useState<Kind>("");
  const [srcUrl, setSrcUrl] = useState("");
  const [mode, setMode] = useState<Mode>("fill");
  const [zoom, setZoom] = useState(1);
  const [radius, setRadius] = useState(64);
  const [duration, setDuration] = useState(0);
  const [time, setTime] = useState(0);
  const [ready, setReady] = useState(false);
  const [name, setName] = useState("");
  const [emoji, setEmoji] = useState("🙂");
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [packed, setPacked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [status, setStatus] = useState("");
  const [bad, setBad] = useState(false);
  const [auth, setAuth] = useState(false);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const urlRef = useRef("");
  const artifactRef = useRef<Artifact | null>(null);

  const paint = useCallback(() => {
    const canvas = canvasRef.current;
    const media = kind === "video" ? videoRef.current : imageRef.current;
    if (!canvas || !media) return;

    const width =
      kind === "video"
        ? (media as HTMLVideoElement).videoWidth
        : (media as HTMLImageElement).naturalWidth;
    const height =
      kind === "video"
        ? (media as HTMLVideoElement).videoHeight
        : (media as HTMLImageElement).naturalHeight;
    if (!width || !height) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.clearRect(0, 0, CANVAS, CANVAS);
    const base =
      mode === "fit"
        ? Math.min(CANVAS / width, CANVAS / height)
        : Math.max(CANVAS / width, CANVAS / height);
    const scale = base * zoom;
    const drawW = width * scale;
    const drawH = height * scale;
    const drawX = (CANVAS - drawW) / 2;
    const drawY = mode === "top" ? 0 : (CANVAS - drawH) / 2;

    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(media, drawX, drawY, drawW, drawH);

    if (radius > 0) {
      ctx.globalCompositeOperation = "destination-in";
      ctx.beginPath();
      const outer = 0;
      const size = CANVAS;
      const r = Math.min(radius, size / 2);
      ctx.moveTo(outer + r, outer);
      ctx.arcTo(outer + size, outer, outer + size, outer + size, r);
      ctx.arcTo(outer + size, outer + size, outer, outer + size, r);
      ctx.arcTo(outer, outer + size, outer, outer, r);
      ctx.arcTo(outer, outer, outer + size, outer, r);
      ctx.closePath();
      ctx.fill();
      ctx.globalCompositeOperation = "source-over";
    }
  }, [kind, mode, zoom, radius]);

  useEffect(() => {
    if (ready) paint();
  }, [paint, ready]);

  useEffect(() => {
    return () => {
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      if (artifactRef.current) URL.revokeObjectURL(artifactRef.current.url);
    };
  }, []);

  const clearArtifact = () => {
    if (artifactRef.current) URL.revokeObjectURL(artifactRef.current.url);
    artifactRef.current = null;
    setArtifact(null);
    setSent(false);
    setPacked(false);
  };

  const clearStatus = () => {
    setStatus("");
    setBad(false);
    setAuth(false);
  };

  const reset = () => {
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = "";
    clearArtifact();
    clearStatus();
    setKind("");
    setSrcUrl("");
    setReady(false);
    setDuration(0);
    setTime(0);
    setName("");
    setZoom(1);
    setMode("fill");
    setRadius(64);
    setEmoji("🙂");
    if (inputRef.current) inputRef.current.value = "";
  };

  const load = (file: File) => {
    const isVideo = file.type.startsWith("video/");
    const isImage = file.type.startsWith("image/");
    if (!isVideo && !isImage) {
      notify("error");
      return;
    }

    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    const url = URL.createObjectURL(file);
    urlRef.current = url;
    clearArtifact();
    clearStatus();
    setName(file.name);
    setReady(false);
    setDuration(0);
    setTime(0);
    setKind(isVideo ? "video" : "image");
    setSrcUrl(url);

    if (isImage) {
      const image = new Image();
      image.onload = () => {
        imageRef.current = image;
        setReady(true);
      };
      image.onerror = () => notify("error");
      image.src = url;
    }
  };

  const onVideoMeta = () => {
    const video = videoRef.current;
    if (!video) return;
    const total = Number.isFinite(video.duration) ? video.duration : 0;
    setDuration(total);
    const target = total ? Math.min(2, total / 2) : 0;
    setTime(target);
    try {
      video.currentTime = target;
    } catch {
      setReady(true);
    }
  };

  const onVideoSeeked = () => {
    setReady(true);
    paint();
  };

  useEffect(() => {
    const video = videoRef.current;
    if (kind !== "video" || !video || !ready) return;
    if (Math.abs(video.currentTime - time) > 0.06) {
      try {
        video.currentTime = time;
      } catch {
        /* seeking can fail while metadata loads */
      }
    }
  }, [kind, time, ready]);

  const build = async () => {
    const canvas = canvasRef.current;
    if (!canvas || !ready || busy) return;

    setBusy(true);
    clearStatus();
    try {
      let blob: Blob | null = null;
      for (const quality of QUALITIES) {
        blob = await canvasToBlob(canvas, quality);
        if (blob && blob.size <= MAX_BYTES) break;
      }
      if (!blob) throw new Error("empty");
      if (blob.size > MAX_BYTES) {
        setBad(true);
        setStatus(t("studio.tooBig"));
        return;
      }

      clearArtifact();
      const next: Artifact = { blob, url: URL.createObjectURL(blob), size: blob.size };
      artifactRef.current = next;
      setArtifact(next);
      setSent(false);
      notify("success");
    } catch {
      setBad(true);
      setStatus(t("studio.failed"));
    } finally {
      setBusy(false);
    }
  };

  const download = () => {
    if (!artifact) return;
    const link = document.createElement("a");
    link.href = artifact.url;
    link.download = "vavilong-sticker.webp";
    link.click();
    notify("success");
  };

  const send = async () => {
    if (!artifact || sending) return;
    setSending(true);
    clearStatus();
    try {
      const data = await toBase64(artifact.blob);
      await api.sticker(data, firstCharacter(emoji) || "🙂");
      setSent(true);
      setStatus(t("studio.sentOk"));
      notify("success");
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : String(exc);
      setBad(true);
      if (message === AUTH_ERROR) {
        setAuth(true);
        setStatus(t("studio.auth"));
      } else {
        setStatus(t("studio.sendFailed"));
      }
      notify("error");
    } finally {
      setSending(false);
    }
  };

  const addToPack = async () => {
    if (!artifact) return;
    if (draft.stickers.length >= MAX_STICKERS) {
      setBad(true);
      setStatus(t("studio.packFull"));
      return;
    }
    const ok = await addSticker(artifact.blob, firstCharacter(emoji) || "🙂");
    if (!ok) {
      setBad(true);
      setStatus(t("studio.packFull"));
      return;
    }
    setPacked(true);
    notify("success");
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    const file = event.dataTransfer.files?.[0];
    if (file) load(file);
  };

  return (
    <>
      <div className="page-head">
        <h1>{t("studio.title")}</h1>
        <p>{t("studio.lede")}</p>
      </div>

      <div className="studio">
        <div className="stage-wrap">
          <div className="stage" onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
            <canvas ref={canvasRef} width={CANVAS} height={CANVAS} />
            {!ready && (
              <div className="stage-empty">
                <ImageUp size={30} strokeWidth={1.5} aria-hidden />
                <h3>{t("studio.empty.title")}</h3>
                <p>{t("studio.empty.text")}</p>
                <button type="button" className="drop" onClick={() => inputRef.current?.click()}>
                  {t("studio.choose")}
                </button>
              </div>
            )}
          </div>
          <div className="stage-bar">
            <span className="mono">
              {ready
                ? `${kind === "video" ? t("studio.video") : t("studio.image")} · ${name}`
                : t("studio.formats")}
            </span>
          </div>
        </div>

        <input
          ref={inputRef}
          type="file"
          accept="image/*,video/mp4,video/webm"
          className="sr-only"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) load(file);
          }}
        />

        <div className="controls">
          <div className="controls-head">
            <h2>{t("studio.controls")}</h2>
            <span className="chip mono">512 × 512</span>
          </div>

          <div className="row">
            <button
              type="button"
              className="btn secondary"
              onClick={() => inputRef.current?.click()}
            >
              <ImageUp size={16} strokeWidth={1.7} aria-hidden />
              {ready ? t("studio.replace") : t("studio.choose")}
            </button>
            {ready && (
              <button type="button" className="btn ghost" onClick={reset}>
                <RotateCcw size={16} strokeWidth={1.7} aria-hidden />
                {t("studio.reset")}
              </button>
            )}
          </div>

          <div className="field">
            <span className="field-label">{t("studio.mode")}</span>
            <div className="segmented" role="group" aria-label={t("studio.mode")}>
              {MODES.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.id}
                    type="button"
                    aria-pressed={mode === item.id}
                    onClick={() => {
                      setMode(item.id);
                      clearArtifact();
                      clearStatus();
                    }}
                  >
                    <Icon size={16} strokeWidth={1.7} aria-hidden />
                    {t(item.key)}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="field">
            <label htmlFor="zoom">
              {t("studio.zoom")} <span className="mono">{zoom.toFixed(2)}×</span>
            </label>
            <input
              id="zoom"
              type="range"
              min={1}
              max={2.5}
              step={0.01}
              value={zoom}
              onChange={(event) => {
                setZoom(Number(event.target.value));
                clearArtifact();
                clearStatus();
              }}
            />
          </div>

          <div className="field">
            <label htmlFor="radius">
              {t("studio.radius")} <span className="mono">{radius}px</span>
            </label>
            <input
              id="radius"
              type="range"
              min={0}
              max={160}
              step={4}
              value={radius}
              onChange={(event) => {
                setRadius(Number(event.target.value));
                clearArtifact();
                clearStatus();
              }}
            />
          </div>

          {kind === "video" && duration > 0 && (
            <div className="field">
              <label htmlFor="frame">
                {t("studio.frame")} <span className="mono">{time.toFixed(2)} s</span>
              </label>
              <input
                id="frame"
                type="range"
                min={0}
                max={Math.max(0, duration - 0.05)}
                step={0.05}
                value={Math.min(time, Math.max(0, duration - 0.05))}
                onChange={(event) => {
                  setTime(Number(event.target.value));
                  clearArtifact();
                  clearStatus();
                }}
              />
            </div>
          )}

          <div className="field">
            <span className="field-label">
              {t("studio.emoji")} <span className="mono">{t("studio.emoji.hint")}</span>
            </span>
            <EmojiField lang={lang} t={t} value={emoji} onChange={setEmoji} />
          </div>

          <button
            type="button"
            className="btn block"
            disabled={!ready || busy}
            onClick={() => void build()}
          >
            {busy ? (
              <Loader2 size={16} strokeWidth={1.8} className="spin" aria-hidden />
            ) : (
              <Scan size={16} strokeWidth={1.8} aria-hidden />
            )}
            {busy ? t("studio.building") : t("studio.build")}
          </button>

          {artifact && (
            <div className="export-box">
              <div className="export-meta">
                <span className="chip accent mono">{kilobytes(artifact.size)}</span>
                <span className="mono">WebP · 512 × 512</span>
                <span className="chip mono">
                  <Emoji>{firstCharacter(emoji) || "🙂"}</Emoji>
                </span>
              </div>
              <div className="row">
                <button type="button" className="btn secondary" onClick={download}>
                  <Download size={16} strokeWidth={1.7} aria-hidden />
                  {t("studio.download")}
                </button>
                <button
                  type="button"
                  className="btn"
                  disabled={sending}
                  onClick={() => void send()}
                >
                  {sending ? (
                    <Loader2 size={16} strokeWidth={1.8} className="spin" aria-hidden />
                  ) : (
                    <Send size={16} strokeWidth={1.7} aria-hidden />
                  )}
                  {sending ? t("studio.sending") : sent ? t("studio.sent") : t("studio.send")}
                </button>
              </div>
              <button
                type="button"
                className="btn secondary"
                onClick={() => void addToPack()}
              >
                <PackagePlus size={16} strokeWidth={1.7} aria-hidden />
                {packed ? t("studio.packed") : t("studio.toPack")}
                {draft.stickers.length > 0 ? (
                  <span className="mono">
                    {draft.stickers.length} / {MAX_STICKERS}
                  </span>
                ) : null}
              </button>
              {packed && (
                <button
                  type="button"
                  className="btn ghost"
                  onClick={() => onNavigate("builder")}
                >
                  {t("studio.openPack")}
                </button>
              )}
            </div>
          )}

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

          <p className="notice">
            <ShieldCheck size={16} strokeWidth={1.7} aria-hidden />
            <span>{t("studio.note")}</span>
          </p>
        </div>
      </div>

      {kind === "video" && srcUrl && (
        <video
          ref={videoRef}
          src={srcUrl}
          className="sr-only"
          muted
          playsInline
          preload="auto"
          onLoadedMetadata={onVideoMeta}
          onSeeked={onVideoSeeked}
        />
      )}
    </>
  );
}
