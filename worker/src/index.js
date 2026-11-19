/**
 * Vavilong Tools — Cloudflare Worker.
 *
 * Serves the built Mini App (assets) and a small API that talks to Telegram:
 *   GET  /api/me                  — who is calling (verified initData)
 *   GET  /api/pack?name=…         — sticker set with signed preview URLs
 *   GET  /api/file?fid=…&exp=…&sig=… — proxy of a Telegram file (signed)
 *   POST /api/send                — send a sticker to the caller's chat
 *   POST /api/sticker             — upload a freshly built WebP sticker and send it
 *   POST /api/pack/upload         — upload a .tgspack archive for the bot to build
 *
 * The bot token never reaches the browser: every Telegram request happens here.
 * All dates are unix seconds.
 */

const TG = "https://api.telegram.org";
const FILE_TTL = 6 * 3600;
const AUTH_TTL = 24 * 3600;
const MAX_STICKERS = 120;
const STICKER_BYTES = 512 * 1024;
const PACK_BYTES = 19 * 1024 * 1024;

const encoder = new TextEncoder();

const MIME = {
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
  webp: "image/webp",
  gif: "image/gif",
  tgs: "application/x-tgsticker",
  webm: "video/webm",
  mp4: "video/mp4",
};

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function fail(error, status = 400) {
  return json({ error }, status);
}

function hex(buffer) {
  return [...new Uint8Array(buffer)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function b64url(buffer) {
  let text = "";
  for (const byte of new Uint8Array(buffer)) text += String.fromCharCode(byte);
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function hmac(keyBytes, message) {
  const key = await crypto.subtle.importKey(
    "raw",
    keyBytes,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return crypto.subtle.sign("HMAC", key, encoder.encode(message));
}

/** Telegram Mini Apps initData verification. Returns the user or null. */
export async function verifyInitData(initData, botToken) {
  if (!initData || !botToken) return null;

  let params;
  try {
    params = new URLSearchParams(initData);
  } catch {
    return null;
  }

  const hash = params.get("hash");
  if (!hash) return null;
  params.delete("hash");

  const pairs = [...params.entries()]
    .map(([key, value]) => `${key}=${value}`)
    .sort();

  // secret = HMAC_SHA256(key="WebAppData", msg=bot_token)
  const secret = await hmac(encoder.encode("WebAppData"), botToken);
  const signature = hex(await hmac(new Uint8Array(secret), pairs.join("\n")));
  if (!safeEqual(signature, hash)) return null;

  const authDate = Number(params.get("auth_date") || 0);
  const now = Math.floor(Date.now() / 1000);
  if (!authDate || Math.abs(now - authDate) > AUTH_TTL) return null;

  try {
    const user = JSON.parse(params.get("user") || "null");
    if (!user || typeof user.id !== "number") return null;
    return user;
  } catch {
    return null;
  }
}

async function fileSignature(botToken, fileId, exp) {
  const digest = await hmac(encoder.encode(botToken), `${fileId}.${exp}`);
  return b64url(digest);
}

async function signedFile(botToken, fileId, base) {
  const exp = Math.floor(Date.now() / 1000) + FILE_TTL;
  const sig = await fileSignature(botToken, fileId, exp);
  const query = `fid=${encodeURIComponent(fileId)}&exp=${exp}&sig=${sig}`;
  return `${base}/api/file?${query}`;
}

async function telegram(botToken, method, payload) {
  const response = await fetch(`${TG}/bot${botToken}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload ?? {}),
  });
  const body = await response.json().catch(() => null);
  if (!body || body.ok !== true) {
    const description = body?.description || `Telegram ${method} failed`;
    const error = new Error(description);
    error.status = response.status;
    throw error;
  }
  return body.result;
}

async function telegramForm(botToken, method, form) {
  const response = await fetch(`${TG}/bot${botToken}/${method}`, {
    method: "POST",
    body: form,
  });
  const body = await response.json().catch(() => null);
  if (!body || body.ok !== true) {
    throw new Error(body?.description || `Telegram ${method} failed`);
  }
  return body.result;
}

function packName(raw) {
  const value = (raw || "").trim();
  const match = value.match(/(?:addstickers|addemoji)\/([\w-]+)/i);
  if (match) return match[1];
  return value.replace(/[^\w-]/g, "").slice(0, 64);
}

function originOf(request) {
  const url = new URL(request.url);
  return `${url.protocol}//${url.host}`;
}

async function handleMe(request, env) {
  const user = await verifyInitData(
    request.headers.get("authorization")?.replace(/^tma\s+/i, "") || "",
    env.BOT_TOKEN,
  );
  if (!user) return fail("auth", 401);
  const name =
    [user.first_name, user.last_name].filter(Boolean).join(" ") ||
    user.username ||
    "Telegram";
  return json({ user: { id: user.id, name, username: user.username || null } });
}

async function handlePack(request, env) {
  const user = await verifyInitData(
    request.headers.get("authorization")?.replace(/^tma\s+/i, "") || "",
    env.BOT_TOKEN,
  );
  if (!user) return fail("auth", 401);

  const url = new URL(request.url);
  const name = packName(url.searchParams.get("name") || "");
  if (!name) return fail("name", 400);

  let set;
  try {
    set = await telegram(env.BOT_TOKEN, "getStickerSet", { name });
  } catch (exc) {
    return fail(exc.message || "not_found", 404);
  }

  if (!set || !Array.isArray(set.stickers)) return fail("not_found", 404);

  const anySticker = set.stickers[0] || {};
  const isVideo = Boolean(set.is_video ?? anySticker.is_video);
  const isAnimated = Boolean(set.is_animated ?? anySticker.is_animated);

  const base = originOf(request);
  const stickers = await Promise.all(
    set.stickers.slice(0, MAX_STICKERS).map(async (sticker) => {
      const previewId =
        sticker.thumbnail?.file_id || sticker.thumb?.file_id || sticker.file_id;
      // .tgs cannot be shown in an <img>; the webp thumbnail is the best preview.
      const fullId = sticker.is_animated ? previewId : sticker.file_id;
      return {
        file_id: sticker.file_id,
        emoji: sticker.emoji || "",
        is_video: Boolean(sticker.is_video),
        is_animated: Boolean(sticker.is_animated),
        width: sticker.width || 512,
        height: sticker.height || 512,
        thumb: await signedFile(env.BOT_TOKEN, previewId, base),
        full: await signedFile(env.BOT_TOKEN, fullId, base),
      };
    }),
  );

  return json({
    name: set.name,
    title: set.title,
    kind: isVideo ? "video" : isAnimated ? "animated" : "static",
    count: set.stickers.length,
    stickers,
  });
}

async function handleFile(request, env) {
  const url = new URL(request.url);
  const fileId = url.searchParams.get("fid") || "";
  const exp = Number(url.searchParams.get("exp") || 0);
  const sig = url.searchParams.get("sig") || "";

  if (!fileId || !exp || !sig) return fail("bad_request", 400);
  if (exp < Math.floor(Date.now() / 1000)) return fail("expired", 410);

  const expected = await fileSignature(env.BOT_TOKEN, fileId, exp);
  if (!safeEqual(expected, sig)) return fail("forbidden", 403);

  let file;
  try {
    file = await telegram(env.BOT_TOKEN, "getFile", { file_id: fileId });
  } catch (exc) {
    return fail(exc.message || "not_found", 404);
  }

  const upstream = await fetch(
    `${TG}/file/bot${env.BOT_TOKEN}/${file.file_path}`,
    { cf: { cacheTtl: FILE_TTL, cacheEverything: true } },
  );
  if (!upstream.ok || !upstream.body) {
    return fail("upstream", 502);
  }

  const ext = (file.file_path.split(".").pop() || "").toLowerCase();
  const headers = new Headers();
  headers.set("content-type", MIME[ext] || "application/octet-stream");
  headers.set("cache-control", `private, max-age=${FILE_TTL}, immutable`);
  const length = upstream.headers.get("content-length");
  if (length) headers.set("content-length", length);

  return new Response(upstream.body, { status: 200, headers });
}

async function handleSend(request, env) {
  if (request.method !== "POST") return fail("method", 405);
  const user = await verifyInitData(
    request.headers.get("authorization")?.replace(/^tma\s+/i, "") || "",
    env.BOT_TOKEN,
  );
  if (!user) return fail("auth", 401);

  let body;
  try {
    body = await request.json();
  } catch {
    return fail("json", 400);
  }

  const fileId = typeof body?.file_id === "string" ? body.file_id : "";
  if (!fileId) return fail("file_id", 400);

  try {
    await telegram(env.BOT_TOKEN, "sendSticker", {
      chat_id: user.id,
      sticker: fileId,
    });
    return json({ ok: true });
  } catch (exc) {
    // A sticker from someone else's set may refuse a plain file_id.
    // Re-upload the bytes once, then send the fresh file_id.
    try {
      const file = await telegram(env.BOT_TOKEN, "getFile", { file_id: fileId });
      const media = await fetch(`${TG}/file/bot${env.BOT_TOKEN}/${file.file_path}`);
      if (!media.ok) throw new Error("download failed");
      const blob = await media.blob();
      const form = new FormData();
      form.set("chat_id", String(user.id));
      form.set("sticker", blob, file.file_path.split("/").pop() || "sticker.webp");
      await telegramForm(env.BOT_TOKEN, "sendSticker", form);
      return json({ ok: true });
    } catch {
      return fail(exc.message || "send_failed", 502);
    }
  }
}

/** Upload a pack archive built in the Mini App; the bot offers a button to import it. */
async function handlePackUpload(request, env) {
  if (request.method !== "POST") return fail("method", 405);
  const user = await verifyInitData(
    request.headers.get("authorization")?.replace(/^tma\s+/i, "") || "",
    env.BOT_TOKEN,
  );
  if (!user) return fail("auth", 401);

  const declared = Number(request.headers.get("content-length") || 0);
  if (declared > PACK_BYTES) return fail("size", 413);

  const data = await request.arrayBuffer();
  if (!data.byteLength) return fail("empty", 400);
  if (data.byteLength > PACK_BYTES) return fail("size", 413);

  // ZIP magic: PK\x03\x04.
  const head = new Uint8Array(data, 0, Math.min(4, data.byteLength));
  if (head[0] !== 0x50 || head[1] !== 0x4b || head[2] !== 0x03 || head[3] !== 0x04) {
    return fail("format", 415);
  }

  const meta = decodeMeta(request.headers.get("x-pack-meta"));
  const title = String(meta.title || "Vavilong pack").slice(0, 64);

  const form = new FormData();
  form.set("chat_id", String(user.id));
  form.set(
    "document",
    new Blob([data], { type: "application/octet-stream" }),
    "vavilong-pack.tgspack",
  );
  form.set("caption", title);
  form.set(
    "reply_markup",
    JSON.stringify({
      inline_keyboard: [
        [{ text: "Собрать пак · Build pack", callback_data: "tgspack:go" }],
      ],
    }),
  );

  try {
    await telegramForm(env.BOT_TOKEN, "sendDocument", form);
    return json({ ok: true });
  } catch (exc) {
    return fail(exc.message || "send_failed", 502);
  }
}

function decodeMeta(raw) {
  if (!raw) return {};
  try {
    const padded = raw.replace(/-/g, "+").replace(/_/g, "/");
    const binary = atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
    const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
    return JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return {};
  }
}

/** Upload a sticker built in the Mini App and send it to the caller. */
async function handleSticker(request, env) {
  if (request.method !== "POST") return fail("method", 405);
  const user = await verifyInitData(
    request.headers.get("authorization")?.replace(/^tma\s+/i, "") || "",
    env.BOT_TOKEN,
  );
  if (!user) return fail("auth", 401);

  let body;
  try {
    body = await request.json();
  } catch {
    return fail("json", 400);
  }

  const data = typeof body?.data === "string" ? body.data : "";
  if (!data) return fail("data", 400);

  let bytes;
  try {
    bytes = Uint8Array.from(atob(data), (char) => char.charCodeAt(0));
  } catch {
    return fail("base64", 400);
  }
  if (bytes.length < 17) return fail("empty", 400);
  if (bytes.length > STICKER_BYTES) return fail("size", 413);

  // Static Telegram stickers are WebP; reject anything else before uploading.
  const isWebp =
    bytes[0] === 0x52 &&
    bytes[1] === 0x49 &&
    bytes[2] === 0x46 &&
    bytes[3] === 0x46 &&
    bytes[8] === 0x57 &&
    bytes[9] === 0x45 &&
    bytes[10] === 0x42 &&
    bytes[11] === 0x50;
  if (!isWebp) return fail("format", 415);

  const emoji =
    (typeof body?.emoji === "string" ? body.emoji : "").trim().slice(0, 8) || "🙂";

  const form = new FormData();
  form.set("chat_id", String(user.id));
  form.set("emoji", emoji);
  form.set("sticker", new Blob([bytes], { type: "image/webp" }), "sticker.webp");

  try {
    await telegramForm(env.BOT_TOKEN, "sendSticker", form);
    return json({ ok: true });
  } catch (exc) {
    return fail(exc.message || "send_failed", 502);
  }
}

export default {
  async fetch(request, env) {    const url = new URL(request.url);

    if (url.pathname.startsWith("/api/")) {
      try {
        if (url.pathname === "/api/me") return await handleMe(request, env);
        if (url.pathname === "/api/pack") return await handlePack(request, env);
        if (url.pathname === "/api/file") return await handleFile(request, env);
        if (url.pathname === "/api/send") return await handleSend(request, env);
        if (url.pathname === "/api/sticker") return await handleSticker(request, env);
        if (url.pathname === "/api/pack/upload") return await handlePackUpload(request, env);
        return fail("not_found", 404);
      } catch (exc) {
        return fail(exc?.message || "server", 500);
      }
    }

    if (env.ASSETS) {
      return env.ASSETS.fetch(request);
    }
    return new Response("Not found", { status: 404 });
  },
};
