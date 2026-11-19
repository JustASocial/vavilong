import { useEffect, useState } from "react";
import { Boxes, HelpCircle, House, PackagePlus, ScanFace, Send } from "lucide-react";
import { dict, type Lang } from "./i18n";
import { loadPack } from "./pack";
import { BOT_URL, haptic, tg } from "./telegram";
import { Home } from "./screens/Home";
import { Studio } from "./screens/Studio";
import { Builder } from "./screens/Builder";
import { Packs } from "./screens/Packs";
import { Help } from "./screens/Help";

export type Screen = "home" | "studio" | "builder" | "packs" | "help";
export type Translate = (key: string) => string;

const SCREENS: { id: Screen; icon: typeof House; label: string }[] = [
  { id: "home", icon: House, label: "nav.home" },
  { id: "studio", icon: ScanFace, label: "nav.studio" },
  { id: "builder", icon: PackagePlus, label: "nav.builder" },
  { id: "packs", icon: Boxes, label: "nav.packs" },
  { id: "help", icon: HelpCircle, label: "nav.help" },
];

function detectLang(): Lang {
  const stored = localStorage.getItem("vavilong.lang");
  if (stored === "ru" || stored === "en") return stored;
  const code = (tg?.initDataUnsafe?.user?.language_code ?? navigator.language ?? "").toLowerCase();
  return code.startsWith("ru") ? "ru" : "en";
}

function readHash(): Screen {
  const value = window.location.hash.replace("#", "");
  return SCREENS.some((item) => item.id === value) ? (value as Screen) : "home";
}

export function App() {
  const [lang, setLang] = useState<Lang>(detectLang);
  const [screen, setScreen] = useState<Screen>(readHash);

  const t: Translate = (key) => dict[lang][key] ?? key;

  useEffect(() => {
    localStorage.setItem("vavilong.lang", lang);
    document.documentElement.lang = lang;
  }, [lang]);

  useEffect(() => {
    void loadPack();
  }, []);

  useEffect(() => {
    const onHash = () => {
      setScreen(readHash());
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const navigate = (next: Screen) => {
    if (next === screen) {
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    haptic("light");
    window.location.hash = next;
    setScreen(next);
    window.scrollTo({ top: 0 });
  };

  const changeLang = (next: Lang) => {
    if (next === lang) return;
    haptic("light");
    setLang(next);
  };

  return (
    <div className="app">
      <header className="topbar">
        <a
          className="brand"
          href="#home"
          onClick={(event) => {
            event.preventDefault();
            navigate("home");
          }}
          aria-label="Vavilong"
        >
          <span className="brand-mark">
            <Boxes size={18} strokeWidth={1.8} aria-hidden />
          </span>
          <span className="brand-text">
            <b>Vavilong</b>
          </span>
        </a>

        <nav className="tabs" aria-label={t("nav.label")}>
          {SCREENS.map((item) => {
            const Icon = item.icon;
            return (
              <a
                key={item.id}
                href={`#${item.id}`}
                aria-current={screen === item.id ? "page" : undefined}
                onClick={(event) => {
                  event.preventDefault();
                  navigate(item.id);
                }}
              >
                <Icon size={15} strokeWidth={1.8} aria-hidden />
                {t(item.label)}
              </a>
            );
          })}
        </nav>

        <div className="topbar-actions">
          <div className="lang" role="group" aria-label="Language">
            <button type="button" aria-pressed={lang === "ru"} onClick={() => changeLang("ru")}>
              RU
            </button>
            <button type="button" aria-pressed={lang === "en"} onClick={() => changeLang("en")}>
              EN
            </button>
          </div>
          <a
            className="icon-btn"
            href={BOT_URL}
            target="_blank"
            rel="noreferrer"
            aria-label={t("footer.bot")}
            title={t("footer.bot")}
          >
            <Send size={15} strokeWidth={1.8} aria-hidden />
          </a>
        </div>
      </header>

      <main className="shell" key={screen}>
        <div className="screen">
          {screen === "home" && <Home t={t} onNavigate={navigate} />}
          {screen === "studio" && <Studio t={t} lang={lang} onNavigate={navigate} />}
          {screen === "builder" && <Builder t={t} lang={lang} onNavigate={navigate} />}
          {screen === "packs" && <Packs t={t} />}
          {screen === "help" && <Help t={t} />}
        </div>
      </main>
    </div>
  );
}
