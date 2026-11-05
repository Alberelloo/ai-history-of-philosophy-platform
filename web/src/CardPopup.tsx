import { useEffect, useState } from "react";
import { navigate } from "./App";
import { ScopeToggle, useScope } from "./scope";
import { storage } from "./storage";

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

function value(row: Row): string {
  if (row.label) return row.label;
  const v = row.value as { original?: string } | string | null;
  if (v && typeof v === "object" && "original" in v) return String(v.original);
  return v ? String(v) : "";
}

export function CardPopup({ entityId, x, y, onClose }: { entityId: string; x: number; y: number; onClose: () => void }) {
  const [stack, setStack] = useState<string[]>([entityId]);
  const [card, setCard] = useState<Card | null>(null);
  const [description, setDescription] = useState<{ text: string; generated: boolean } | null>(null);
  const [notInTextbook, setNotInTextbook] = useState(false);
  const current = stack[stack.length - 1];
  const scope = useScope();
  const textbook = storage.currentSource();
  const onlyTextbook = scope.onlyTextbook && Boolean(textbook);

  useEffect(() => setStack([entityId]), [entityId]);

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

  return (
    <div className="card-popup" role="dialog" aria-label="Карточка" style={{ left: x, top: y }}>
      <header>
        {stack.length > 1 && (
          <button className="link" onClick={() => setStack(stack.slice(0, -1))}>
            ← Назад
          </button>
        )}
        <h3>{card?.title ?? "…"}</h3>
        <button className="link" aria-label="Закрыть карточку" onClick={onClose}>
          ✕
        </button>
      </header>
      {card?.dates && <p className="card-dates">{card.dates.original}</p>}
      <div className="card-scope">
        <ScopeToggle textbook={textbook} />
        {textbook && !onlyTextbook && (
          <label>
            <input type="checkbox" checked={notInTextbook} onChange={(e) => setNotInTextbook(e.target.checked)} />
            Нет в моём учебнике
          </label>
        )}
      </div>
      {description && (
        <p className={description.generated ? "card-description ungrounded" : "card-description"}>
          {description.generated && (
            <span className="ungrounded-mark" role="img" aria-label="Сгенерировано">
              ◇
            </span>
          )}
          {description.text}
        </p>
      )}
      {sections.map((section) => (
        <section key={section.code} className="card-section" data-section={section.code}>
          <h4>{section.title}</h4>
          <ul>
            {section.rows.map((row) => (
              <li key={row.statement_id} className={row.generated ? "card-row ungrounded" : "card-row"}>
                {row.generated && (
                  <span className="ungrounded-mark" role="img" aria-label="Сгенерировано">
                    ◇
                  </span>
                )}
                {row.relation}:{" "}
                {row.entity_id ? (
                  <button className="link" onClick={() => setStack([...stack, row.entity_id!])}>
                    {row.label}
                  </button>
                ) : (
                  value(row)
                )}
                {row.disputed && <span className="badge muted">спорно: {row.disputed_by.join(", ")}</span>}
                {row.in_textbook === true && <span className="badge muted">есть в учебнике</span>}
                {row.attributed_to.length > 0 && (
                  <span className="card-who"> — так считает: {row.attributed_to.join(", ")}</span>
                )}
                {row.evidence.map((e) => (
                  <a
                    key={e.paragraph_id}
                    className="citation"
                    href={e.link}
                    onClick={(ev) => {
                      ev.preventDefault();
                      navigate(e.link);
                    }}
                  >
                    [абзац]
                  </a>
                ))}
              </li>
            ))}
          </ul>
        </section>
      ))}
      {card && card.recipes.length > 0 && (
        <section className="card-section" data-section="graph">
          <h4>Граф</h4>
          {card.recipes.map((r) => (
            <button
              key={r.code}
              className="link card-recipe"
              onClick={() => {
                onClose();
                navigate(`/graph/${card.id}?recipe=${r.code}`);
              }}
            >
              {r.title}
            </button>
          ))}
        </section>
      )}
      {card && card.where_to_read.length > 0 && (
        <section className="card-section" data-section="where">
          <h4>Где читать</h4>
          <ul>
            {card.where_to_read.map((w) => (
              <li key={`${w.source_id}-${w.chapter_id}`}>
                <button className="link" onClick={() => navigate(`/read/${w.source_id}/${w.chapter_id}`)}>
                  {w.chapter_title ?? "Глава"}
                </button>
                <span className="card-who">
                  {" "}
                  — {w.source_title ?? "источник"}, упоминаний: {w.count}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
