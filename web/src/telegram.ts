type TelegramWebApp = {
  initData: string;
  initDataUnsafe?: {
    user?: {
      id: number;
      first_name?: string;
      last_name?: string;
      username?: string;
      language_code?: string;
    };
    start_param?: string;
  };
  colorScheme?: "light" | "dark";
  themeParams?: Record<string, string>;
  ready: () => void;
  expand: () => void;
  close: () => void;
  setHeaderColor?: (color: string) => void;
  setBackgroundColor?: (color: string) => void;
  openTelegramLink?: (url: string) => void;
  openLink?: (url: string) => void;
  HapticFeedback?: {
    impactOccurred: (style: "light" | "medium" | "heavy") => void;
    notificationOccurred: (type: "error" | "success" | "warning") => void;
    selectionChanged: () => void;
  };
};

export const tg: TelegramWebApp | undefined = (
  window as unknown as { Telegram?: { WebApp?: TelegramWebApp } }
).Telegram?.WebApp;

export const BOT_USERNAME = "vavilong_bot";
export const BOT_URL = `https://t.me/${BOT_USERNAME}`;

export function initTelegram(): void {
  const forced = new URLSearchParams(window.location.search).get("theme");
  const scheme =
    forced === "dark" || forced === "light"
      ? forced
      : tg?.colorScheme === "light"
        ? "light"
        : "dark";
  document.documentElement.dataset.theme = scheme;
  if (!tg) return;
  const chrome = scheme === "light" ? "#f3f1e9" : "#171717";
  try {
    tg.ready();
    tg.expand();
    tg.setHeaderColor?.(chrome);
    tg.setBackgroundColor?.(chrome);
  } catch {
    /* older clients */
  }
}

export function openBot(start?: string): void {
  const url = start ? `${BOT_URL}?start=${encodeURIComponent(start)}` : BOT_URL;
  if (tg?.openTelegramLink) tg.openTelegramLink(url);
  else window.open(url, "_blank", "noopener");
}

export function haptic(style: "light" | "medium" | "heavy" = "light"): void {
  try {
    tg?.HapticFeedback?.impactOccurred(style);
  } catch {
    /* noop */
  }
}

export function notify(type: "success" | "error" | "warning"): void {
  try {
    tg?.HapticFeedback?.notificationOccurred(type);
  } catch {
    /* noop */
  }
}

export function startParam(): string {
  return tg?.initDataUnsafe?.start_param ?? "";
}

export function userName(): string {
  const user = tg?.initDataUnsafe?.user;
  if (!user) return "";
  return [user.first_name, user.last_name].filter(Boolean).join(" ") || user.username || "";
}
