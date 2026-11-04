import { useEffect, useId, useRef, useState } from "react";
import type { Footnote } from "./api";

const URL_RE = /(https?:\/\/[^\s)]+)/g;

function withLinks(text: string) {
  return text.split(URL_RE).map((part, i) =>
    i % 2 === 1 ? (
      <a key={i} href={part} target="_blank" rel="noreferrer">
        {part}
      </a>
    ) : (
      part
    ),
  );
}

// Знак сноски: окно открывается при наведении и с клавиатуры и не закрывается, пока указатель
// на знаке или в самом окне. Текст главы при этом не прокручивается.
export function FootnoteRef({ note }: { note: Footnote }) {
  const [open, setOpen] = useState(false);
  const closeTimer = useRef<number | undefined>(undefined);
  const id = useId();

  const show = () => {
    window.clearTimeout(closeTimer.current);
    setOpen(true);
  };
  const hide = () => {
    window.clearTimeout(closeTimer.current);
    closeTimer.current = window.setTimeout(() => setOpen(false), 200);
  };
  useEffect(() => () => window.clearTimeout(closeTimer.current), []);

  return (
    <span className="note" onMouseEnter={show} onMouseLeave={hide}>
      <button
        type="button"
        className="note-ref"
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onFocus={show}
        onBlur={hide}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
      >
        {note.marker}
      </button>
      {open && (
        <span role="tooltip" id={id} className="note-popup" onFocus={show} onBlur={hide}>
          {withLinks(note.text)}
        </span>
      )}
    </span>
  );
}
