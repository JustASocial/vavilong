import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Boxes,
  Info,
  List,
  Pause,
  Play,
  ScanFace,
  Send,
} from "lucide-react";
import type { Screen, Translate } from "../App";
import { BOT_URL } from "../telegram";

type Props = {
  t: Translate;
  onNavigate: (screen: Screen) => void;
};

const DEMO_SRC = "/media/demo.mp4";
const DEMO_POSTER = "/media/demo.jpg";

const INLINE = [
  { code: "@vavilong_bot <link>", key: "home.inline.quality", icon: Info },
  { code: "@vavilong_bot <link> 1080p", key: "home.inline.list", icon: List },
  { code: "@vavilong_bot <link> +info", key: "home.inline.info", icon: Info },
];

function clock(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0:06";
  const total = Math.round(value);
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function Home({ t, onNavigate }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(true);
  const [progress, setProgress] = useState(0);
  const [duration, setDuration] = useState(6);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onTime = () =>
      setProgress(video.duration ? (video.currentTime / video.duration) * 100 : 0);
    const onMeta = () => setDuration(video.duration || 6);

    video.addEventListener("play", onPlay);
    video.addEventListener("pause", onPause);
    video.addEventListener("timeupdate", onTime);
    video.addEventListener("loadedmetadata", onMeta);
    video.addEventListener("seeked", onTime);

    return () => {
      video.removeEventListener("play", onPlay);
      video.removeEventListener("pause", onPause);
      video.removeEventListener("timeupdate", onTime);
      video.removeEventListener("loadedmetadata", onMeta);
      video.removeEventListener("seeked", onTime);
    };
  }, []);

  const toggle = () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) void video.play();
    else video.pause();
  };

  return (
    <>
      <h1 className="sr-only">Vavilong</h1>

      <div className="home-grid">
        <article className="video-card">
          <div className="video-frame">
            <video
              ref={videoRef}
              src={DEMO_SRC}
              poster={DEMO_POSTER}
              autoPlay
              muted
              loop
              playsInline
              preload="metadata"
              onClick={toggle}
            />
            <span className="video-tag">MP4 · 720p</span>
            <button
              type="button"
              className="video-play"
              onClick={toggle}
              aria-label={playing ? t("video.pause") : t("video.play")}
            >
              {playing ? (
                <Pause size={16} strokeWidth={2} fill="currentColor" aria-hidden />
              ) : (
                <Play size={16} strokeWidth={0} fill="currentColor" aria-hidden />
              )}
            </button>
            <span className="video-time">{clock(duration)}</span>
            <div className="video-progress" aria-hidden>
              <i style={{ width: `${progress}%` }} />
            </div>
          </div>
          <div className="video-meta">
            <b>{t("home.demo.title")}</b>
            <span>{t("home.demo.note")}</span>
          </div>
        </article>

        <div className="quick">
          <button type="button" className="quick-item" onClick={() => onNavigate("studio")}>
            <span className="qi">
              <ScanFace size={18} strokeWidth={1.8} aria-hidden />
            </span>
            <span className="qt">
              <b>{t("nav.studio")}</b>
              <small>{t("home.quick.studio")}</small>
            </span>
            <ArrowRight size={16} strokeWidth={1.8} aria-hidden />
          </button>

          <button type="button" className="quick-item" onClick={() => onNavigate("packs")}>
            <span className="qi">
              <Boxes size={18} strokeWidth={1.8} aria-hidden />
            </span>
            <span className="qt">
              <b>{t("nav.packs")}</b>
              <small>{t("home.quick.packs")}</small>
            </span>
            <ArrowRight size={16} strokeWidth={1.8} aria-hidden />
          </button>

          <a className="quick-item" href={BOT_URL} target="_blank" rel="noreferrer">
            <span className="qi">
              <Send size={18} strokeWidth={1.8} aria-hidden />
            </span>
            <span className="qt">
              <b>{t("footer.bot")}</b>
              <small>{t("home.quick.bot")}</small>
            </span>
            <ArrowRight size={16} strokeWidth={1.8} aria-hidden />
          </a>
        </div>
      </div>

      <section className="section">
        <div className="section-head">
          <h2>{t("home.inline.title")}</h2>
          <p>{t("home.inline.lede")}</p>
        </div>
        <div className="syntax">
          {INLINE.map((row) => {
            const Icon = row.icon;
            return (
              <div className="syntax-row" key={row.code}>
                <code>{row.code}</code>
                <span>
                  <Icon size={13} strokeWidth={1.8} aria-hidden /> {t(row.key)}
                </span>
              </div>
            );
          })}
        </div>
      </section>
    </>
  );
}
