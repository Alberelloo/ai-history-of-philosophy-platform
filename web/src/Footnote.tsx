import { useEffect, useId, useRef, useState } from "react";
import type { Footnote } from "./api";
import { useT } from "./i18n";

const URL_RE = /(https?:\/\/[^\s)]+)/g;

function hasLink(text: string): boolean {
  return URL_RE.test(text);
}

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

// Знак сноски в тексте. В раскладке K1 (``field``) знак — ссылка на сноску на поле; в K2–K4 —
// кнопка, открывающая всплывающее окно при наведении и с клавиатуры (не закрывается, пока
// указатель на знаке или в окне). Наведение/фокус подсвечивает пару знак↔сноска (``onActive``).
export function FootnoteRef({
  note,
  noteId,
  field,
  active,
  onActive,
}: {
  note: Footnote;
  noteId: string;
  field: boolean;
  active: boolean;
  onActive: (id: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const closeTimer = useRef<number | undefined>(undefined);
  const id = useId();

  const show = () => {
    window.clearTimeout(closeTimer.current);
    setOpen(true);
    onActive(noteId);
  };
  const hide = () => {
    window.clearTimeout(closeTimer.current);
    closeTimer.current = window.setTimeout(() => setOpen(false), 200);
    onActive(null);
  };
  useEffect(() => () => window.clearTimeout(closeTimer.current), []);

  if (field) {
    return (
      <a
        className={active ? "note-ref pg-note-ref is-active" : "note-ref pg-note-ref"}
        id={`fn-ref-${noteId}`}
        href={`#fn-${noteId}`}
        aria-describedby={`fn-${noteId}`}
        data-note-id={noteId}
        onMouseEnter={() => onActive(noteId)}
        onMouseLeave={() => onActive(null)}
        onFocus={() => onActive(noteId)}
        onBlur={() => onActive(null)}
      >
        {note.marker}
      </a>
    );
  }

  return (
    <span className="note" onMouseEnter={show} onMouseLeave={hide}>
      <button
        type="button"
        className="note-ref pg-note-ref"
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onFocus={show}
        onBlur={hide}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
      >
        {note.marker}
      </button>
      {open && (
        <span
          role={hasLink(note.text) ? "dialog" : "tooltip"}
          id={id}
          className="note-popup pg-sidenote-pop"
          onFocus={show}
          onBlur={hide}
        >
          {withLinks(note.text)}
        </span>
      )}
    </span>
  );
}

// Сноска на поле (K1): номер и текст; подсветка пары со знаком через ``active``; ``shifted`` —
// каскад сдвинул её ниже своей строки больше чем на 240px.
export function FieldNote({
  note,
  noteId,
  active,
  onActive,
  shifted,
}: {
  note: Footnote;
  noteId: string;
  active: boolean;
  onActive: (id: string | null) => void;
  shifted: boolean;
}) {
  const t = useT();
  return (
    <div
      className={active ? "field-note is-active" : "field-note"}
      id={`fn-${noteId}`}
      data-note-id={noteId}
      onMouseEnter={() => onActive(noteId)}
      onMouseLeave={() => onActive(null)}
      onFocus={() => onActive(noteId)}
      onBlur={() => onActive(null)}
    >
      {shifted && (
        <span className="field-note__up" title={t.reader.noteAbove} aria-hidden="true">
          ↑
        </span>
      )}
      <span className="field-note__marker">{note.marker}</span>
      <span className="field-note__text">{withLinks(note.text)}</span>
    </div>
  );
}
