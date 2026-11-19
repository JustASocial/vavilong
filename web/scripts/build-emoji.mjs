/**
 * Builds compact emoji tables for the picker from `emojibase-data`.
 *
 * Run with `node scripts/build-emoji.mjs` (also runs before every build).
 * Output: src/data/emoji-{ru,en}.json — one array per emoji:
 *   [char, label, group, keywords, skin variants, order]
 * The `component` group (skin tones, hair) is dropped: tones are applied
 * through the picker's tone selector instead of taking up grid slots.
 */
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const langs = ["ru", "en"];

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

const meta = readJson(path.join(root, "node_modules", "emojibase-data", "meta", "groups.json"));
const groupKey = new Map(Object.entries(meta.groups));

fs.mkdirSync(path.join(root, "src", "data"), { recursive: true });

for (const lang of langs) {
  const source = readJson(path.join(root, "node_modules", "emojibase-data", lang, "data.json"));
  const messages = readJson(path.join(root, "node_modules", "emojibase-data", lang, "messages.json"));

  const titles = new Map(messages.groups.map((group) => [group.key, group.message]));
  const order = new Map(messages.groups.map((group) => [group.key, group.order]));

  const groups = new Map();
  const items = [];
  let index = 0;

  for (const entry of source) {
    index += 1;
    if (entry.group === undefined || entry.group === 2) continue;
    if (!entry.emoji) continue;

    const key = groupKey.get(String(entry.group));
    if (!groups.has(entry.group)) {
      groups.set(entry.group, [
        entry.group,
        titles.get(key) ?? String(entry.group),
        order.get(key) ?? 99,
      ]);
    }

    const skins = Array.isArray(entry.skins)
      ? entry.skins.filter((skin) => skin.emoji).map((skin) => skin.emoji)
      : [];

    items.push([
      entry.emoji,
      entry.label || "",
      entry.group,
      (entry.tags || []).join(" "),
      skins.length === 5 ? skins : [],
      entry.order ?? index,
    ]);
  }

  items.sort((a, b) => a[5] - b[5]);

  const payload = {
    groups: [...groups.values()].sort((a, b) => a[2] - b[2]).map((group) => [group[0], group[1]]),
    items: items.map((item) => item.slice(0, 5)),
  };

  const file = path.join(root, "src", "data", `emoji-${lang}.json`);
  fs.writeFileSync(file, JSON.stringify(payload));
  console.log(`${lang}: ${payload.items.length} emoji, ${payload.groups.length} groups`);
}
