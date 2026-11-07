import { useEffect, useLayoutEffect, useRef, useState } from "react";
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
  x?: number;
  y?: number;
  onClose: () => void;
  onOpenFull?: (entityId: string) => void;
};

const API = "/api/knowledge/v1";
const MARGIN = 16;
const POPOVER_MIN = 320;

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
  const ordered = verified.length ? verified : sourced.length ? sourced : rest.length ? rest : generated;
  return ordered.slice(0, 2);
}

export function CardPopup({ entityId, anchor, x, y, onClose, onOpenFull }: Props) {
  const t = useT();
  const [stack, setStack] = useState<string[]>([entityId]);
  const [card, setCard] = useState<Card | null>(null);
  const [description, setDescription] = useState<{ text: string; generated: boolean } | null>(null);
  const [problem, setProblem] = useState<"not_found" | "failed" | null>(null);
  const [loading, setLoading] = useState(false);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const abort = useRef<AbortController | null>(null);
  const current = stack[stack.length - 1];
  const scope = useScope();
  const textbook = storage.currentSource();
  const onlyTextbook = scope.onlyTextbook && Boolean(textbook);

  useEffect(() => setStack([entityId]), [entityId]);

  // Загрузка карточки: с кэшем по ключу (id, onlyTextbook, generation, textbook) и отменой.
  useEffect(() => {
    const controller = new AbortController();
    abort.current?.abort();
    abort.current = controller;
    setCard(null);
    setDescription(null);
    setProblem(null);
    setLoading(true);
    const params = new URLSearchParams({ generation: String(scope.generation) });
    if (textbook) params.set(onlyTextbook ? "attributed_to" : "textbook", textbook);
    const key = `${current}|${onlyTextbook}|${scope.generation}|${textbook}`;
    const cached = cache.get(key);
    if (cached) {
      setCard(cached);
      setDescription(
        cached.description
          ? { text: value(cached.description), generated: cached.description.generated }
          : null,
      );
      setLoading(false);
      return;
    }
    fetch(`${API}/entities/${current}/card?${params}`, { signal: controller.signal })
      .then(async (r) => {
        const body = await r.json().catch(() => ({}));
        if (controller.signal.aborted) return;
        if (r.status === 404 && body.kind === "entity_not_found") {
          setProblem("not_found");
          setLoading(false);
          return;
        }
        if (!r.ok) {
          setProblem("failed");
          setLoading(false);
          return;
        }
        const data = body as Card;
        setCard(data);
        if (data.description) {
          setDescription({ text: value(data.description), generated: data.description.generated });
        } else if (data.description_pending) {
          // Разделы уже видны, описание дописывается потоком (entity-cards «Скорость карточки»).
          await streamDescription(current, scope.generation, controller.signal, setDescription);
        }
        cache.set(key, data);
        trimCache();
        setLoading(false);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setProblem("failed");
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [current, onlyTextbook, scope.generation, textbook]);

  // Положение окна (4.3): K1 — правее колонки текста; K2–K4 — под строкой, иначе над ней.
  useLayoutEffect(() => {
    if (!anchor) {
      if (x !== undefined && y !== undefined) setPos({ left: x, top: y });
      return;
    }
    if (!anchor.isConnected) return;
    const el = box.current;
    if (!el) return;
    const r = anchor.getBoundingClientRect();
    const chapter = anchor.closest(".chapter")?.getBoundingClientRect();
    const panel = document.querySelector(".side-panel")?.getBoundingClientRect();
    const rightBoundary = panel?.left ?? window.innerWidth;
    const width = el.offsetWidth;
    const height = el.offsetHeight;
    const layout = document.querySelector(".reader")?.getAttribute("data-layout");
    let left: number;
    let top: number;
    if (layout === "K1") {
      left = (chapter?.right ?? r.right) + MARGIN;
      left = Math.min(left, rightBoundary - MARGIN - Math.max(width, POPOVER_MIN));
      top = r.top - 8;
    } else {
      left = r.left - 24;
      left = Math.max(chapter?.left ?? MARGIN, Math.min(left, rightBoundary - MARGIN - Math.max(width, POPOVER_MIN)));
      if (r.bottom + 8 + height <= window.innerHeight - MARGIN) {
        top = r.bottom + 8;
      } else {
        top = r.top - 8 - height;
      }
    }
    top = Math.max(MARGIN, Math.min(top, window.innerHeight - MARGIN - Math.min(height, window.innerHeight - 2 * MARGIN)));
    setPos({ left: left + window.scrollX, top: top + window.scrollY });
  }, [anchor, x, y, card, problem, loading]);

  const family = familyOf(card?.type);
  const typeName = pick(t.family, card?.type);
  const descriptionText = description?.text;
  const statements = card ? topStatements(card) : [];
  const firstRecipe = card?.recipes[0];

  return (
    <div
      ref={box}
      className="card-popup pg-popover"
      role="dialog"
      aria-modal="false"
      aria-label={t.card.label}
      style={pos ? { left: pos.left, top: pos.top } : undefined}
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
          onClick={onClose}
        >
          <Icon name="close" small />
        </button>
      </div>
      {loading && (
        <div className="pg-entity-head">
          {family === "people" ? <Portrait name="…" size={56} /> : <span />}
          <div>
            <h3 className="pg-entity-head__name">…</h3>
            <p className="card-loading">{t.card.loading}</p>
          </div>
        </div>
      )}
      {problem === "not_found" && (
        <div className="pg-notice pg-notice--danger" role="alert">
          <Icon name="warning" />
          <div>{t.card.notFound}</div>
          <button className="pg-btn pg-btn--secondary pg-btn--sm" onClick={onClose}>
            {t.card.close}
          </button>
        </div>
      )}
      {problem === "failed" && (
        <div className="pg-notice pg-notice--danger" role="alert">
          <Icon name="warning" />
          <div>{t.card.loadFailed}</div>
          <button className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => setStack([...stack])}>
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
              <h3 className="pg-entity-head__name">{card.title}</h3>
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
                      onClick={() => setStack([...stack, row.entity_id!])}
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
          {(!descriptionText && statements.length === 0) && (
            <p className="card-popup__empty">{t.card.empty}</p>
          )}
          <div className="pg-popover__actions">
            {onOpenFull && (
              <button className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => onOpenFull(current)}>
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
