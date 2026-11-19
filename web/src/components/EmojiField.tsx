import { useState } from "react";
import type { Translate } from "../App";
import { Emoji } from "../emoji";
import type { Lang } from "../i18n";
import { EmojiPicker } from "./EmojiPicker";

type Props = {
  lang: Lang;
  t: Translate;
  value: string;
  title?: string;
  onChange: (char: string) => void;
};

/** A read-only emoji preview that opens the picker. */
export function EmojiField({ lang, t, value, title, onChange }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button type="button" className="emoji-field" onClick={() => setOpen(true)}>
        <Emoji className="emoji-field-glyph">{value}</Emoji>
        <span className="emoji-field-text">{t("emoji.change")}</span>
      </button>
      {open && (
        <EmojiPicker
          lang={lang}
          t={t}
          value={value}
          title={title}
          onPick={(char) => {
            onChange(char);
            setOpen(false);
          }}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}
