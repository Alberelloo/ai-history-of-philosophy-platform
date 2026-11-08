import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { navigate } from "./App";
import { pick, recipeTitle, relationTitle, useT } from "./i18n";
import { useScope } from "./scope";
import { storage } from "./storage";
import { familyOf, Generated, Icon, Portrait, StatusMark } from "./ui";

// Компактное окно карточки у упоминания (docs/design/features/reader-panels.md, 4.2–4.4):
// открывается только щелчком, не перекрывает строку упоминания, показывает имя, годы и до двух
// утверждений. Полная карточка — в правой панели (этап 3). Кэш в памяти вкладки, отмена запроса.

type Who = { who: string; kind?: string; stance?: string };
type Row = {
  statement_id: string;
  type?: string;
  relation: string;
  inverse?: boolean;
  attributions?: Who[];
  entity_id: string | null;
  label: string | null;
  value: unknown;
  status: string;
  disputed: boolean;
  disputed_by: string[];
  generated: boolean;
  in_textbook: boolean | null;
  attributed_to: string[];
  evidence: { paragraph_id: string; link: string }[];
};
type Card = {
  id: string;
  type?: string;
  title: string;
  dates: { original: string } | null;
  description: Row | null;
  description_pending: boolean;
  sections: { code: string; title: string; rows: Row[] }[];
  where_to_read: {
    source_id: string;
    source_title: string | null;
    chapter_id: string;
    chapter_title: string | null;
    count: number;
  }[];
  recipes: { code: string; title: string }[];
};

type Props = {
  entityId: string;
  anchor?: HTMLElement;
  // Строка упоминания, по которой щёлкнули (4.3): индекс в getClientRects() упоминания.
  line?: number;
  // Имя из текста упоминания: показывается, пока карточка грузится (S2), вместо «…».
  name?: string;
  // Окно открыто с клавиатуры: фокус переходит на заголовок окна (4.2).
  keyboard?: boolean;
  x?: number;
  y?: number;
  // ``restoreFocus`` — вернуть фокус на упоминание (Esc, «×»); щелчок мимо и уход строки
  // из видимой области фокус не трогают.
  onClose: (opts?: { restoreFocus?: boolean }) => void;
  onOpenFull?: (entityId: string, title: string) => void;
};

export const CARD_POPUP_ID = "card-popup";

const API = "/api/knowledge/v1";
const MARGIN = 16;
const POPOVER_MIN = 320;
// S2: подпись «Загружаем карточку…» появляется, только если загрузка дольше 300 мс (4.7).
const LOADING_DELAY = 300;

// Ответы карточек кэшируются в памяти вкладки: повторное открытие той же карточки — без запроса.
const cache = new Map<string, Card>();
function trimCache(): void {
  while (cache.size > 50) {
    const first = cache.keys().next().value;
    if (first === undefined) break;
    cache.delete(first);
  }
}

// Описание без сохранённого текста: дописывается потоком событий NDJSON (delta/done).
async function streamDescription(
  entityId: string,
  generation: boolean,
  signal: AbortSignal,
  onUpdate: (desc: { text: string; generated: boolean }) => void,
): Promise<void> {
  const response = await fetch(`${API}/entities/${entityId}/description?generation=${generation}`, {
    method: "POST",
    signal,
  });
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let text = "";
  for (;;) {
    const { value: chunk, done } = await reader.read();
    if (done || signal.aborted) break;
    buffer += decoder.decode(chunk, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      if (event.type === "delta") text += event.text;
      if (event.type === "done") text = event.text;
      if (event.type === "delta" || event.type === "done") onUpdate({ text, generated: true });
    }
  }
}

function value(row: Row): string {
  if (row.label) return row.label;
  const v = row.value as { original?: string } | string | null;
  if (v && typeof v === "object" && "original" in v) return String(v.original);
  return v ? String(v) : "";
}

// Первые два предложения описания: граница — `.`, `?`, `!`, за которыми пробел и заглавная.
function twoSentences(text: string): string {
  const re = /[.!?](?=\s+[А-ЯЁA-Z])/g;
  const ends: number[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) && ends.length < 2) ends.push(m.index + 1);
  return ends.length < 2 ? text : text.slice(0, ends[1]).trim();
}

// До двух утверждений: сначала проверенные, затем по источникам, затем остальные;
// сгенерированные — только если других нет.
function topStatements(card: Card): Row[] {
  const rows = card.sections.flatMap((s) => s.rows);
  const by = (pred: (r: Row) => boolean) => rows.filter(pred);
  const verified = by((r) => r.status === "verified");
  const sourced = by((r) => r.status !== "verified" && r.evidence.length > 0);
  const rest = by((r) => r.status !== "verified" && r.evidence.length === 0 && !r.generated);
  const generated = by((r) => r.generated);
  const ordered = [...verified, ...sourced, ...rest];
  return (ordered.length ? ordered : generated).slice(0, 2);
}

// Положение окна по 4.3. Опорный прямоугольник — строка упоминания, по которой щёлкнули.
// Окно никогда не закрывает эту строку: в K1 оно правее колонки текста, в K2–K4 — целиком
// под строкой или над ней.
function placement(
  anchor: HTMLElement,
  line: number,
  el: HTMLElement,
): { left: number; top: number; width?: number; maxHeight?: number } {
  const rects = Array.from(anchor.getClientRects());
  const r = rects[Math.min(line, rects.length - 1)] ?? anchor.getBoundingClientRect();
  const chapter = anchor.closest(".chapter")?.getBoundingClientRect();
  const panelBox = document.querySelector(".side-panel")?.getBoundingClientRect();
  const rightBoundary = panelBox && panelBox.width > 0 ? panelBox.left : window.innerWidth;
  const layout = document.querySelector(".reader")?.getAttribute("data-layout");
  const viewH = window.innerHeight;
  // Естественный размер окна — без ширины и высоты, заданных прошлым расчётом.
  // Переход на время замера выключен: при «уменьшении движения» у всех элементов переход 1ms,
  // и без этого offsetWidth отдавал бы прежнюю ширину, а окно уходило за правый край.
  const saved = [el.style.maxHeight, el.style.width, el.style.transition];
  el.style.transition = "none";
  el.style.maxHeight = "";
  el.style.width = "";
  let width = el.offsetWidth;
  const height = el.offsetHeight;
  [el.style.maxHeight, el.style.width] = saved;
  void el.offsetWidth; // прежние размеры применены без перехода
  el.style.transition = saved[2];
  if (layout === "K1") {
    let left = (chapter?.right ?? r.right) + MARGIN;
    const room = rightBoundary - MARGIN - left;
    let fixedWidth: number | undefined;
    if (room < width) {
      fixedWidth = Math.max(POPOVER_MIN, room);
      width = fixedWidth;
    }
    left = Math.min(left, rightBoundary - MARGIN - width);
    let top = r.top - 8;
    if (top + height > viewH - MARGIN) top = viewH - MARGIN - height;
    top = Math.max(MARGIN, top);
    const maxHeight = height > viewH - 2 * MARGIN ? viewH - 2 * MARGIN : undefined;
    return { left, top, width: fixedWidth, maxHeight };
  }
  let left = r.left - 24;
  left = Math.min(left, rightBoundary - MARGIN - width);
  left = Math.max(chapter?.left ?? MARGIN, left);
  const below = viewH - MARGIN - (r.bottom + 8);
  const above = r.top - 8 - MARGIN;
  if (height <= below) return { left, top: r.bottom + 8 };
  if (height <= above) return { left, top: r.top - 8 - height };
  if (below >= above) return { left, top: r.bottom + 8, maxHeight: Math.max(below, 0) };
  const maxHeight = Math.max(above, 0);
  return { left, top: r.top - 8 - maxHeight, maxHeight };
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])';

function focusables(root: ParentNode): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => el.offsetWidth > 0 || el.offsetHeight > 0,
  );
}

type StackItem = { id: string; name?: string };

export function CardPopup({ entityId, anchor, line = 0, name, keyboard, x, y, onClose, onOpenFull }: Props) {
  const t = useT();
  const [stack, setStack] = useState<StackItem[]>([{ id: entityId, name }]);
  const [attempt, setAttempt] = useState(0);
  const [card, setCard] = useState<Card | null>(null);
  const [description, setDescription] = useState<{ text: string; generated: boolean } | null>(null);
  const [problem, setProblem] = useState<"not_found" | "failed" | null>(null);
  const [loading, setLoading] = useState(false);
  const [slow, setSlow] = useState(false);
  const [pos, setPos] = useState<{ left: number; top: number; width?: number; maxHeight?: number } | null>(
    null,
  );
  const [relayout, setRelayout] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const abort = useRef<AbortController | null>(null);
  const top = stack[stack.length - 1];
  const current = top.id;
  const scope = useScope();
  const textbook = storage.currentSource();
  const onlyTextbook = scope.onlyTextbook && Boolean(textbook);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => setStack([{ id: entityId, name }]), [entityId, name]);

  // Загрузка карточки: с кэшем по ключу (id, onlyTextbook, generation, textbook) и отменой.
  useEffect(() => {
    const controller = new AbortController();
    abort.current?.abort();
    abort.current = controller;
    setCard(null);
    setDescription(null);
    setProblem(null);
    setLoading(true);
    setSlow(false);
    const timer = window.setTimeout(() => setSlow(true), LOADING_DELAY);
    const params = new URLSearchParams({ generation: String(scope.generation) });
    if (textbook) params.set(onlyTextbook ? "attributed_to" : "textbook", textbook);
    const key = `${current}|${onlyTextbook}|${scope.generation}|${textbook}`;
    const cached = cache.get(key);
    if (cached) {
      window.clearTimeout(timer);
      setCard(cached);
      setDescription(
        cached.description
          ? { text: value(cached.description), generated: cached.description.generated }
          : null,
      );
      setLoading(false);
      return;
    }
    const finish = () => {
      window.clearTimeout(timer);
      setLoading(false);
    };
    fetch(`${API}/entities/${current}/card?${params}`, { signal: controller.signal })
      .then(async (r) => {
        const body = await r.json().catch(() => ({}));
        if (controller.signal.aborted) return;
        if (r.status === 404 && body.kind === "entity_not_found") {
          setProblem("not_found");
          finish();
          return;
        }
        if (!r.ok) {
          setProblem("failed");
          finish();
          return;
        }
        const data = body as Card;
        finish();
        setCard(data);
        if (data.description) {
          setDescription({ text: value(data.description), generated: data.description.generated });
        } else if (data.description_pending) {
          // Разделы уже видны, описание дописывается потоком (entity-cards «Скорость карточки»).
          await streamDescription(current, scope.generation, controller.signal, setDescription).catch(
            () => undefined,
          );
        }
        if (controller.signal.aborted) return;
        cache.set(key, data);
        trimCache();
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setProblem("failed");
          finish();
        }
      });
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [current, onlyTextbook, scope.generation, textbook, attempt]);

  // Положение окна (4.3) пересчитывается при смене содержимого, ширины окна и колонок.
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    if (!anchor) {
      if (x !== undefined && y !== undefined) setPos({ left: x, top: y });
      return;
    }
    if (!anchor.isConnected) return;
    const p = placement(anchor, line, el);
    setPos({ ...p, left: p.left + window.scrollX, top: p.top + window.scrollY });
  }, [anchor, line, x, y, card, problem, loading, slow, description, relayout]);

  useEffect(() => {
    if (!anchor) return;
    const bump = () => setRelayout((n) => n + 1);
    window.addEventListener("resize", bump);
    const chapter = anchor.closest(".chapter");
    const observer = typeof ResizeObserver !== "undefined" && chapter ? new ResizeObserver(bump) : null;
    if (observer && chapter) observer.observe(chapter);
    // И само окно: первое наблюдение приходит после раскладки, поэтому окно «загружается» (S2)
    // встаёт по окончательной ширине колонок и не выходит за правый край.
    if (observer && box.current) observer.observe(box.current);
    // Прокрутка окно не закрывает; строка целиком ушла из видимой области — окно закрывается
    // без возврата фокуса.
    const onScroll = () => {
      const rects = Array.from(anchor.getClientRects());
      const r = rects[Math.min(line, rects.length - 1)];
      if (!r || r.bottom < 0 || r.top > window.innerHeight) closeRef.current();
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("resize", bump);
      window.removeEventListener("scroll", onScroll);
      observer?.disconnect();
    };
  }, [anchor, line]);

  // Esc закрывает окно и возвращает фокус на упоминание; щелчок мимо окна — закрывает.
  // Щелчок по самому упоминанию обрабатывает страница (повторный щелчок закрывает окно).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      const active = document.activeElement;
      const inside = box.current?.contains(active) || (anchor && anchor === active) || active === document.body;
      if (!inside) return;
      e.preventDefault();
      closeRef.current({ restoreFocus: Boolean(anchor) });
    };
    const onDown = (e: PointerEvent) => {
      const target = e.target as Node | null;
      if (!target || box.current?.contains(target) || anchor?.contains(target)) return;
      closeRef.current();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown, true);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown, true);
    };
  }, [anchor]);

  // Открыто с клавиатуры: фокус на заголовок окна (4.2, 10.4).
  useEffect(() => {
    if (!keyboard) return;
    const active = document.activeElement;
    if (active && box.current?.contains(active) && active !== document.body) return;
    heading.current?.focus({ preventScroll: true });
  }, [keyboard, current, card, loading]);

  // Tab из последнего элемента окна закрывает его, фокус — на следующий элемент после
  // упоминания; Shift+Tab из первого — на упоминание, окно остаётся открытым.
  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "Tab" || !anchor || !box.current) return;
    const inside = focusables(box.current);
    const first = inside[0];
    const last = inside[inside.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || active === heading.current)) {
      e.preventDefault();
      anchor.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      const all = focusables(document).filter((el) => !box.current?.contains(el));
      const next = all[all.indexOf(anchor) + 1];
      closeRef.current();
      next?.focus();
    }
  };

  const family = familyOf(card?.type);
  const typeName = pick(t.family, card?.type);
  const descriptionText = description?.text;
  const statements = card ? topStatements(card) : [];
  const firstRecipe = card?.recipes[0];
  const waitingName = top.name?.trim();

  return (
    <div
      ref={box}
      id={CARD_POPUP_ID}
      className="card-popup pg-popover"
      role="dialog"
      aria-modal="false"
      aria-label={t.card.label}
      aria-busy={loading || undefined}
      data-state={loading ? "loading" : problem ?? "ready"}
      onKeyDown={onKeyDown}
      style={
        pos
          ? { left: pos.left, top: pos.top, width: pos.width, maxHeight: pos.maxHeight }
          : { visibility: "hidden" }
      }
    >
      <div className="card-popup__bar">
        {stack.length > 1 && (
          <button className="pg-btn pg-btn--ghost pg-btn--sm" onClick={() => setStack(stack.slice(0, -1))}>
            <Icon name="arrowLeft" small />
            {t.card.back}
          </button>
        )}
        <button
          className="pg-btn pg-btn--ghost pg-btn--icon pg-btn--sm card-popup__close"
          aria-label={t.card.close}
          title={t.card.close}
          onClick={() => onClose({ restoreFocus: true })}
        >
          <Icon name="close" small />
        </button>
      </div>
      {loading && (
        <div className="pg-entity-head card-popup__loading">
          <span />
          <div>
            {waitingName && (
              <h3 className="pg-entity-head__name" ref={heading} tabIndex={-1}>
                {waitingName}
              </h3>
            )}
            {slow && (
              <p className="card-loading" role="status">
                {t.card.loading}
              </p>
            )}
          </div>
        </div>
      )}
      {problem === "not_found" && (
        <div className="pg-notice pg-notice--danger" role="alert">
          <Icon name="warning" />
          <div>{t.card.notFound}</div>
          <button className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => onClose({ restoreFocus: true })}>
            {t.card.close}
          </button>
        </div>
      )}
      {problem === "failed" && (
        <div className="pg-notice pg-notice--danger" role="alert">
          <Icon name="warning" />
          <div>{t.card.loadFailed}</div>
          <button className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => setAttempt((n) => n + 1)}>
            <Icon name="retry" small />
            {t.card.retry}
          </button>
        </div>
      )}
      {card && (
        <>
          <div className="pg-entity-head">
            {family === "people" ? <Portrait name={card.title} size={56} /> : <span />}
            <div>
              <h3 className="pg-entity-head__name" ref={heading} tabIndex={-1}>
                {card.title}
              </h3>
              <div className="pg-entity-head__meta">
                {typeName && (
                  <span className="pg-chip" data-family={family}>
                    {typeName}
                  </span>
                )}
                {card.dates && <span className="card-dates">{card.dates.original}</span>}
              </div>
            </div>
          </div>
          {descriptionText &&
            (description?.generated ? (
              <p className="pg-desc">
                <Generated className="card-description ungrounded">{twoSentences(descriptionText)}</Generated>
              </p>
            ) : (
              <p className="pg-desc card-description">{twoSentences(descriptionText)}</p>
            ))}
          {statements.length > 0 && (
            <ul className="card-popup__facts">
              {statements.map((row) => (
                <li key={row.statement_id} className={row.generated ? "card-row ungrounded" : "card-row"}>
                  <span className="card-row__relation">
                    {relationTitle(t, row.type, Boolean(row.inverse), row.relation)}:{" "}
                  </span>
                  {row.entity_id ? (
                    <button
                      className="pg-btn pg-btn--ghost pg-btn--sm card-row__entity"
                      onClick={() => setStack([...stack, { id: row.entity_id!, name: row.label ?? undefined }])}
                    >
                      {row.label}
                    </button>
                  ) : (
                    value(row)
                  )}
                  {row.status === "verified" && <StatusMark status="verified" iconOnly />}
                  {row.generated && <StatusMark status="generated" iconOnly />}
                  {row.disputed && <StatusMark status="disputed" iconOnly />}
                </li>
              ))}
            </ul>
          )}
          {!descriptionText && statements.length === 0 && <p className="card-popup__empty">{t.card.empty}</p>}
          <div className="pg-popover__actions">
            {onOpenFull && (
              <button
                className="pg-btn pg-btn--secondary pg-btn--sm"
                onClick={() => onOpenFull(current, card?.title ?? current)}
              >
                <Icon name="expand" small />
                {t.card.open}
              </button>
            )}
            {firstRecipe && (
              <button
                className="pg-btn pg-btn--ghost pg-btn--sm card-recipe"
                onClick={() => {
                  onClose();
                  navigate(`/graph/${current}?recipe=${firstRecipe.code}`);
                }}
              >
                <Icon name="graph" small />
                {recipeTitle(t, firstRecipe.code, firstRecipe.title)}
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
