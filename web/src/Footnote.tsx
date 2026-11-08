import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { Chapter, Footnote } from "./api";
import { useT } from "./i18n";

const URL_RE = /(https?:\/\/[^\s)]+)/g;

// Без флага g: у глобального выражения ``test`` помнит ``lastIndex`` и через раз отвечает «нет».
function hasLink(text: string): boolean {
  return /https?:\/\/[^\s)]+/.test(text);
}

// Фокус на элемент по id (знак ↔ сноска на поле): переход по клавиатуре, 6.1.
function focusById(id: string) {
  document.getElementById(id)?.focus();
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
  // Enter на знаке открыл окно со ссылками: фокус уходит внутрь, как только окно отрисовано.
  const [focusInside, setFocusInside] = useState(false);
  const closeTimer = useRef<number | undefined>(undefined);
  const button = useRef<HTMLButtonElement>(null);
  const popup = useRef<HTMLSpanElement>(null);
  const quietFocus = useRef(false);
  const id = useId();
  const dialog = hasLink(note.text);

  useEffect(() => {
    if (open && focusInside) {
      popup.current?.focus();
      setFocusInside(false);
    }
  }, [open, focusInside]);

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
        onKeyDown={(e) => {
          // Enter переводит фокус на сноску на поле, а не прокручивает к ней по адресу.
          if (e.key === "Enter") {
            e.preventDefault();
            focusById(`fn-${noteId}`);
          }
        }}
      >
        {note.marker}
      </a>
    );
  }

  // Esc в окне: окно закрывается, фокус возвращается на знак и не открывает окно снова.
  const closeToSign = () => {
    window.clearTimeout(closeTimer.current);
    setOpen(false);
    quietFocus.current = true;
    button.current?.focus();
    quietFocus.current = false;
  };

  return (
    <span className="note" onMouseEnter={show} onMouseLeave={hide}>
      <button
        ref={button}
        type="button"
        className="note-ref pg-note-ref"
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onFocus={() => (quietFocus.current ? onActive(noteId) : show())}
        onBlur={hide}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setOpen(false);
          } else if (e.key === "Enter" && dialog) {
            // В тексте сноски ссылки (окно — dialog): Enter переводит фокус внутрь окна.
            e.preventDefault();
            show();
            setFocusInside(true);
          }
        }}
      >
        {note.marker}
      </button>
      {open && (
        <span
          ref={popup}
          role={dialog ? "dialog" : "tooltip"}
          id={id}
          className="note-popup pg-sidenote-pop"
          tabIndex={dialog ? -1 : undefined}
          onFocus={show}
          onBlur={hide}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.stopPropagation();
              closeToSign();
            }
          }}
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
      // Фокус сюда ставит Enter на знаке; Esc или Shift+Tab возвращают его на знак (6.1).
      tabIndex={-1}
      onMouseEnter={() => onActive(noteId)}
      onMouseLeave={() => onActive(null)}
      onFocus={() => onActive(noteId)}
      onBlur={() => onActive(null)}
      onKeyDown={(e) => {
        if (e.key === "Escape" || (e.key === "Tab" && e.shiftKey)) {
          e.preventDefault();
          focusById(`fn-ref-${noteId}`);
        }
      }}
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

// Что стоит на поле сносок в K1: номера страниц и сноски в порядке строк главы.
export type FieldItem =
  | { kind: "page"; key: string; label: string; anchor: string }
  | { kind: "note"; key: string; note: Footnote; noteId: string };

export function fieldItems(chapter: Chapter): FieldItem[] {
  const items: FieldItem[] = [];
  for (const block of chapter.blocks) {
    if (block.type !== "block") continue;
    const per = [
      ...block.pages.map(([at, label]) => ({ offset: at, kind: "page" as const, label, anchor: `${block.id}-${at}` })),
      ...block.notes.map(([at, id]) => ({ offset: at, kind: "note" as const, id })),
    ].sort((a, b) => a.offset - b.offset);
    for (const item of per) {
      if (item.kind === "page") {
        items.push({ kind: "page", key: `pg-${item.anchor}`, label: item.label, anchor: item.anchor });
      } else {
        const note = chapter.footnotes[item.id];
        if (note) items.push({ kind: "note", key: `nt-${item.id}`, note, noteId: item.id });
      }
    }
  }
  return items;
}

// Промежуток каскада и порог «↑» заданы при корневом кегле 16px и растут вместе с ним (9.7).
const CASCADE_GAP = 12;
const SHIFT_MARK = 240;

type Placement = { tops: Record<string, number>; shifted: Record<string, boolean> };

function samePlacement(a: Placement, b: Placement): boolean {
  const keys = Object.keys(b.tops);
  return (
    keys.length === Object.keys(a.tops).length &&
    keys.every((k) => Math.abs((a.tops[k] ?? NaN) - b.tops[k]) < 0.5 && a.shifted[k] === b.shifted[k])
  );
}

// Поле сносок (K1, 6.1): элементы встают верхом на уровне своих строк; при наезде сдвигаются
// вниз каскадом до промежутка 12px. Положения считаются одним проходом сверху вниз после
// отрисовки, после загрузки шрифтов и при изменении размеров колонки текста.
export function MarginCol({
  items,
  noteActive,
  onActive,
}: {
  items: FieldItem[];
  noteActive: string | null;
  onActive: (id: string | null) => void;
}) {
  const root = useRef<HTMLElement>(null);
  const [placement, setPlacement] = useState<Placement>({ tops: {}, shifted: {} });
  // Список пересоздаётся при каждой отрисовке страницы: пересчёт — по составу, не по ссылке.
  const current = useRef(items);
  current.current = items;
  const signature = items.map((item) => item.key).join("|");

  const place = useCallback(() => {
    const col = root.current;
    const article = document.querySelector<HTMLElement>("article.chapter");
    if (!col || !article) return;
    const scale = parseFloat(getComputedStyle(document.documentElement).fontSize) / 16 || 1;
    const colTop = col.getBoundingClientRect().top;
    const next: Placement = { tops: {}, shifted: {} };
    let prevBottom = -Infinity;
    for (const item of current.current) {
      const el = col.querySelector<HTMLElement>(`[data-field-key="${item.key}"]`);
      if (!el) continue;
      const anchor =
        item.kind === "note"
          ? article.querySelector<HTMLElement>(`.note-ref[data-note-id="${item.noteId}"]`)
          : article.querySelector<HTMLElement>(`[data-page-anchor="${item.anchor}"]`);
      const naturalTop = anchor ? anchor.getBoundingClientRect().top - colTop : 0;
      const top = Math.max(naturalTop, prevBottom + CASCADE_GAP * scale);
      next.tops[item.key] = top;
      next.shifted[item.key] = top - naturalTop > SHIFT_MARK * scale;
      prevBottom = top + el.offsetHeight;
    }
    setPlacement((prev) => (samePlacement(prev, next) ? prev : next));
  }, []);

  useLayoutEffect(place, [signature, place]);

  useEffect(() => {
    let alive = true;
    void document.fonts?.ready.then(() => alive && place());
    const article = document.querySelector<HTMLElement>("article.chapter");
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => place());
    if (article) observer?.observe(article);
    return () => {
      alive = false;
      observer?.disconnect();
    };
  }, [place]);

  return (
    <aside className="margin-col" ref={root}>
      {items.map((item) => (
        <div
          key={item.key}
          className={item.kind === "note" ? "field-item" : "field-item field-page"}
          data-field-key={item.key}
          style={{ transform: `translateY(${placement.tops[item.key] ?? 0}px)` }}
        >
          {item.kind === "note" ? (
            <FieldNote
              note={item.note}
              noteId={item.noteId}
              active={noteActive === item.noteId}
              onActive={onActive}
              shifted={placement.shifted[item.key] ?? false}
            />
          ) : (
            <span className="num">{item.label}</span>
          )}
        </div>
      ))}
    </aside>
  );
}
