import { MessageSquare, ShieldCheck, Terminal } from "lucide-react";
import type { Translate } from "../App";
import { BOT_URL } from "../telegram";

type Props = {
  t: Translate;
};

const INLINE = [
  { code: "@vavilong_bot <link>", key: "home.inline.quality" },
  { code: "@vavilong_bot <link> 1080p", key: "home.inline.list" },
  { code: "@vavilong_bot <link> +info", key: "home.inline.info" },
];

const LIMITS = [
  { key: "help.limit.file", value: "20 MB" },
  { key: "help.limit.upload", value: "50 MB" },
  { key: "help.limit.static", value: "512 KB" },
  { key: "help.limit.video", value: "256 KB" },
  { key: "help.limit.pack", value: "120" },
];

export function Help({ t }: Props) {
  return (
    <>
      <div className="page-head">
        <h1>{t("help.title")}</h1>
        <p>{t("help.lede")}</p>
      </div>

      <section className="section first">
        <div className="section-head">
          <h2>
            <MessageSquare size={18} strokeWidth={1.8} aria-hidden />
            {t("help.inline.title")}
          </h2>
        </div>
        <div className="syntax">
          {INLINE.map((row) => (
            <div className="syntax-row" key={row.code}>
              <code>{row.code}</code>
              <span>{t(row.key)}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>
            <ShieldCheck size={18} strokeWidth={1.8} aria-hidden />
            {t("help.limits.title")}
          </h2>
        </div>
        <div className="facts">
          {LIMITS.map((limit) => (
            <div className="fact" key={limit.key}>
              <b>{limit.value}</b>
              <span>{t(limit.key)}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="section">
        <div className="section-head">
          <h2>
            <Terminal size={18} strokeWidth={1.8} aria-hidden />
            {t("help.commands.title")}
          </h2>
          <a className="btn secondary" href={BOT_URL} target="_blank" rel="noreferrer">
            {t("studio.openBot")}
          </a>
        </div>
        <div className="card">
          <p className="mono" style={{ color: "var(--ink-2)", lineHeight: 1.9 }}>
            {t("help.commands.text")}
          </p>
        </div>
      </section>
    </>
  );
}
