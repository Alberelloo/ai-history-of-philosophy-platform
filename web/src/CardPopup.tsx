import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { navigate } from "./App";
import { pick, useT } from "./i18n";
import { ScopeToggle, useScope } from "./scope";
import { storage } from "./storage";
import { familyOf, Generated, Icon, Portrait, StatusMark, Switch } from "./ui";

// Карточка сущности рядом с упоминанием: не уводит из текста и не сдвигает главу.
// Каждая строка — утверждение: видно, кто так считает, где прочитать и не сгенерировано ли.

type Row = {
  statement_id: string;
  relation: string;
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

const API = "/api/knowledge/v1";
const MARGIN = 16;

function value(row: Row): string {
  if (row.label) return row.label;
  const v = row.value as { original?: string } | string | null;
  if (v && typeof v === "object" && "original" in v) return String(v.original);
  return v ? String(v) : "";
}

export function CardPopup({ entityId, x, y, onClose }: { entityId: string; x: number; y: number; onClose: () => void }) {
  const t = useT();
  const [stack, setStack] = useState<string[]>([entityId]);
  const [card, setCard] = useState<Card | null>(null);
  const [description, setDescription] = useState<{ text: string; generated: boolean } | null>(null);
  const [notInTextbook, setNotInTextbook] = useState(false);
  const [left, setLeft] = useState(x);
  const box = useRef<HTMLDivElement>(null);
  const current = stack[stack.length - 1];
  const scope = useScope();
  const textbook = storage.currentSource();
  const onlyTextbook = scope.onlyTextbook && Boolean(textbook);

  useEffect(() => setStack([entityId]), [entityId]);

  // Окно не выходит за правый край экрана: иначе появилась бы прокрутка по горизонтали.
  useLayoutEffect(() => {
    const width = box.current?.offsetWidth ?? 0;
    const max = window.scrollX + document.documentElement.clientWidth - width - MARGIN;
    setLeft(Math.max(window.scrollX + MARGIN, Math.min(x, max)));
  }, [x]);

  useEffect(() => {
    let cancelled = false;
    setCard(null);
    setDescription(null);
    // В режиме учебника — только его утверждения, иначе пометка «есть в учебнике».
    const params = new URLSearchParams({ generation: String(scope.generation) });
    if (textbook) params.set(onlyTextbook ? "attributed_to" : "textbook", textbook);
    fetch(`${API}/entities/${current}/card?${params}`)
      .then((r) => r.json())
      .then(async (data: Card) => {
        if (cancelled) return;
        setCard(data);
        if (data.description) {
          setDescription({ text: value(data.description), generated: data.description.generated });
        } else if (data.description_pending) {
          // Разделы уже видны, описание дописывается потоком.
          const response = await fetch(`${API}/entities/${current}/description?generation=${scope.generation}`, {
            method: "POST",
          });
          const reader = response.body!.getReader();
          const decoder = new TextDecoder();
          let buffer = "";
          let text = "";
          for (;;) {
            const { value: chunk, done } = await reader.read();
            if (done || cancelled) break;
            buffer += decoder.decode(chunk, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() ?? "";
            for (const line of lines) {
              if (!line.trim()) continue;
              const event = JSON.parse(line);
              if (event.type === "delta") text += event.text;
              if (event.type === "done") text = event.text;
              if (event.type === "delta" || event.type === "done") setDescription({ text, generated: true });
            }
          }
        }
      })
      .catch(() => !cancelled && setCard(null));
    return () => {
      cancelled = true;
    };
  }, [current, onlyTextbook, scope.generation, textbook]);

  // Фильтр «нет в моём учебнике» не оставляет пустых разделов.
  const sections = (card?.sections ?? [])
    .map((s) => ({ ...s, rows: notInTextbook ? s.rows.filter((r) => r.in_textbook === false) : s.rows }))
    .filter((s) => s.rows.length > 0);
  const family = familyOf(card?.type);
  const typeName = pick(t.family, card?.type);

  return (
    <div
      ref={box}
      className="card-popup pg-popover"
      role="dialog"
      aria-label={t.card.label}
      style={{ left, top: y }}
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
      <div className="pg-entity-head">
        {family === "people" && card ? <Portrait name={card.title} size={56} /> : <span />}
        <div>
          <h3 className="pg-entity-head__name">{card?.title ?? "…"}</h3>
          <div className="pg-entity-head__meta">
            {typeName && (
              <span className="pg-chip" data-family={family}>
                {typeName}
              </span>
            )}
            {card?.dates && <span className="card-dates">{card.dates.original}</span>}
          </div>
        </div>
      </div>
      <div className="card-scope">
        <ScopeToggle textbook={textbook} />
        {textbook && !onlyTextbook && (
          <Switch label={t.scope.notInTextbook} checked={notInTextbook} onChange={setNotInTextbook} />
        )}
      </div>
      {description &&
        (description.generated ? (
          <p className="pg-desc">
            <Generated className="card-description ungrounded">{description.text}</Generated>
          </p>
        ) : (
          <p className="pg-desc card-description">{description.text}</p>
        ))}
      {sections.map((section) => (
        <section key={section.code} className="card-section" data-section={section.code}>
          <h4>{section.title}</h4>
          <ul>
            {section.rows.map((row) => {
              const body = (
                <>
                  <span className="card-row__relation">{row.relation}: </span>
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
                  {row.disputed && (
                    <StatusMark status="disputed">{t.card.disputed(row.disputed_by.join(", "))}</StatusMark>
                  )}
                  {row.in_textbook === true && <span className="badge">{t.scope.inTextbook}</span>}
                  {row.attributed_to.length > 0 && (
                    <span className="card-who"> — {t.card.believes(row.attributed_to.join(", "))}</span>
                  )}
                  {row.evidence.map((e, i) => (
                    <a
                      key={e.paragraph_id}
                      className="citation pg-cite"
                      href={e.link}
                      title={t.card.evidence(i + 1)}
                      aria-label={t.card.evidence(i + 1)}
                      onClick={(ev) => {
                        ev.preventDefault();
                        navigate(e.link);
                      }}
                    >
                      {i + 1}
                    </a>
                  ))}
                </>
              );
              return (
                <li key={row.statement_id} className={row.generated ? "card-row ungrounded" : "card-row"}>
                  {row.generated ? <Generated>{body}</Generated> : body}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
      {card && card.where_to_read.length > 0 && (
        <section className="card-section" data-section="where">
          <h4>{t.card.whereToRead}</h4>
          <ul className="card-where">
            {card.where_to_read.map((w) => (
              <li key={`${w.source_id}-${w.chapter_id}`}>
                <button
                  className="pg-btn pg-btn--ghost pg-btn--sm card-where__chapter"
                  onClick={() => navigate(`/read/${w.source_id}/${w.chapter_id}`)}
                >
                  {w.chapter_title ?? t.card.chapter}
                </button>
                <span className="card-who">
                  {w.source_title ?? t.card.source}, {t.card.mentions(w.count)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {card && card.recipes.length > 0 && (
        <section className="card-section pg-popover__actions" data-section="graph" aria-label={t.card.graph}>
          {card.recipes.map((r) => (
            <button
              key={r.code}
              className="pg-btn pg-btn--secondary pg-btn--sm card-recipe"
              onClick={() => {
                onClose();
                navigate(`/graph/${card.id}?recipe=${r.code}`);
              }}
            >
              <Icon name="graph" small />
              {r.title}
            </button>
          ))}
        </section>
      )}
    </div>
  );
}
