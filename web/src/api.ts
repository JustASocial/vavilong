import { tg } from "./telegram";

export type Sticker = {
  file_id: string;
  emoji: string;
  is_video: boolean;
  is_animated: boolean;
  width: number;
  height: number;
  thumb: string;
  full: string;
};

export type Pack = {
  name: string;
  title: string;
  kind: "static" | "video" | "animated";
  count: number;
  stickers: Sticker[];
};

const AUTH_ERROR = "auth";

function devInitData(): string {
  if (!import.meta.env.DEV) return "";
  return new URLSearchParams(window.location.search).get("init") ?? "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const initData = tg?.initData || devInitData();
  if (!initData) {
    throw new Error(AUTH_ERROR);
  }
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `tma ${initData}`,
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { error?: string } | null;
    throw new Error(body?.error || `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export const api = {
  me: () => request<{ user: { id: number; name: string } }>("/api/me"),
  pack: (name: string) =>
    request<Pack>(`/api/pack?name=${encodeURIComponent(name)}`),
  send: (fileId: string) =>
    request<{ ok: true }>("/api/send", {
      method: "POST",
      body: JSON.stringify({ file_id: fileId }),
    }),
  sticker: (data: string, emoji: string) =>
    request<{ ok: true }>("/api/sticker", {
      method: "POST",
      body: JSON.stringify({ data, emoji }),
    }),
  sendPack: async (blob: Blob, title: string) => {
    const initData = tg?.initData || devInitData();
    if (!initData) throw new Error(AUTH_ERROR);
    const bytes = new TextEncoder().encode(JSON.stringify({ title }));
    let binary = "";
    for (const byte of bytes) binary += String.fromCharCode(byte);
    const meta = btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    const response = await fetch("/api/pack/upload", {
      method: "POST",
      headers: {
        "Content-Type": "application/octet-stream",
        Authorization: `tma ${initData}`,
        "X-Pack-Meta": meta,
      },
      body: blob,
    });
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as { error?: string } | null;
      throw new Error(body?.error || `${response.status} ${response.statusText}`);
    }
    return (await response.json()) as { ok: true };
  },
};

export function packNameFromInput(raw: string): string {
  const value = raw.trim();
  if (!value) return "";
  const match = value.match(/(?:addstickers|addemoji)\/([\w-]+)/i);
  if (match) return match[1];
  const tail = value.split(/[?#]/)[0].split("/").filter(Boolean).pop() ?? value;
  return tail.replace(/[^\w-]/g, "");
}

export { AUTH_ERROR };
