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

// Положение окна сноски относительно ``span.note`` (в px): верх, лево, ширина и высота, если
// окно пришлось сузить или ограничить с прокруткой.
type PopupPlace = { top: number; left: number; width?: number; maxHeight?: number; above: boolean };

const NOTE_GAP = 8; // от строки знака до окна
const NOTE_MARGIN = 16; // от краёв окна браузера, правой панели и полоски

function samePlace(a: PopupPlace, b: PopupPlace): boolean {
  return (
    a.above === b.above &&
    Math.abs(a.top - b.top) < 0.5 &&
    Math.abs(a.left - b.left) < 0.5 &&
    a.width === b.width &&
    a.maxHeight === b.maxHeight
  );
}

function popupPlace(sign: HTMLElement, pop: HTMLElement, host: HTMLElement): PopupPlace {
  // Строка знака — высота строки абзаца вокруг середины знака (сам знак ниже строки).
  const signBox = sign.getBoundingClientRect();
  const block = sign.closest<HTMLElement>("p, blockquote, li") ?? host;
  const lineHeight = parseFloat(getComputedStyle(block).lineHeight) || signBox.height * 1.6;
  const middle = (signBox.top + signBox.bottom) / 2;
  const lineTop = Math.min(signBox.top, middle - lineHeight / 2);
  const lineBottom = Math.max(signBox.bottom, middle + lineHeight / 2);
  // Правая граница: левый край развёрнутой панели или полоски, иначе край окна.
  const panel = document.querySelector<HTMLElement>(".side-panel, .side-panel__strip");
  const panelBox = panel?.getBoundingClientRect();
  const right = (panelBox && panelBox.width > 0 ? panelBox.left : window.innerWidth) - NOTE_MARGIN;
  const column = sign.closest<HTMLElement>("article.chapter")?.getBoundingClientRect();
  const left0 = Math.max(column?.left ?? NOTE_MARGIN, NOTE_MARGIN);
  // Естественный размер окна: без прошлых ограничений и без перехода (при «уменьшении
  // движения» переход 1ms, и замер отдал бы прежний размер).
  const saved = [pop.style.width, pop.style.maxHeight, pop.style.transition];
  pop.style.transition = "none";
  pop.style.width = "";
  pop.style.maxHeight = "";
  let width = pop.offsetWidth;
  let height = pop.offsetHeight;
  [pop.style.width, pop.style.maxHeight] = saved;
  void pop.offsetWidth;
  pop.style.transition = saved[2];
  let fixedWidth: number | undefined;
  if (width > right - left0) {
    fixedWidth = Math.max(right - left0, 0);
    width = fixedWidth;
    // Уже окно — выше: высота по суженной ширине.
    pop.style.transition = "none";
    pop.style.width = `${fixedWidth}px`;
    pop.style.maxHeight = "";
    height = pop.offsetHeight;
    [pop.style.width, pop.style.maxHeight] = saved;
    void pop.offsetWidth;
    pop.style.transition = saved[2];
  }
  let left = Math.min(signBox.left, right - width);
  left = Math.max(left, left0);
  const viewH = window.innerHeight;
  let top: number;
  let maxHeight: number | undefined;
  let above = false;
  const below = viewH - NOTE_MARGIN - (lineBottom + NOTE_GAP);
  const over = lineTop - NOTE_GAP - NOTE_MARGIN;
  if (height <= below) {
    top = lineBottom + NOTE_GAP;
  } else if (height <= over) {
    top = lineTop - NOTE_GAP - height;
    above = true;
  } else if (below >= over) {
    top = lineBottom + NOTE_GAP;
    maxHeight = Math.max(below, 0);
  } else {
    maxHeight = Math.max(over, 0);
    top = lineTop - NOTE_GAP - maxHeight;
    above = true;
  }
  // Координаты окна — от начала ``span.note`` (его первой строки).
  const origin = host.getClientRects()[0] ?? host.getBoundingClientRect();
  return { top: top - origin.top, left: left - origin.left, width: fixedWidth, maxHeight, above };
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

  // Положение окна (4.3, 6.2): под строкой знака; не помещается — над ней; не помещается и там —
  // на большей стороне с прокруткой. Справа окно не заходит под правую панель или полоску,
  // слева — не левее колонки текста. Строку знака окно не закрывает никогда.
  const [place, setPlace] = useState<PopupPlace | null>(null);
  useLayoutEffect(() => {
    if (!open || field) {
      setPlace(null);
      return;
    }
    const compute = () => {
      const sign = button.current;
      const pop = popup.current;
      const host = sign?.parentElement;
      if (!sign || !pop || !host) return;
      const next = popupPlace(sign, pop, host);
      setPlace((prev) => (prev && samePlace(prev, next) ? prev : next));
    };
    compute();
    window.addEventListener("resize", compute);
    window.addEventListener("scroll", compute, { passive: true });
    return () => {
      window.removeEventListener("resize", compute);
      window.removeEventListener("scroll", compute);
    };
  }, [open, field]);

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
          className={place?.above ? "note-popup pg-sidenote-pop note-popup--above" : "note-popup pg-sidenote-pop"}
          style={place ? { top: place.top, left: place.left, width: place.width, maxHeight: place.maxHeight } : undefined}
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
