import { useEffect, useRef, useState } from "react";
import { navigate } from "./App";
import { pick, recipeTitle, relationTitle, sectionTitle, useT, whoLabel } from "./i18n";
import { ScopeToggle, useScope } from "./scope";
import { storage } from "./storage";
import {
  familyOf,
  Generated,
  Icon,
  Lifeline,
  PortraitGallery,
  StatusMark,
  Switch,
  type PortraitItem,
} from "./ui";

// Полная карточка в правой панели (docs/design/features/reader-panels.md, 4.5–4.6): галерея
// портретов, линия жизни, переключатели источников, сводка природы знания, описание целиком,
// все разделы с атрибуцией каждой строки, «Где читать» и рецепты графа.

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
  portraits?: PortraitItem[];
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

function believers(t: ReturnType<typeof useT>, row: Row): string[] {
  return row.attributions
    ? [...new Set(row.attributions.map((a) => whoLabel(t, a)))]
    : row.attributed_to;
}

function disputers(t: ReturnType<typeof useT>, row: Row): string[] {
  return row.attributions
    ? row.attributions.filter((a) => a.stance === "disputes").map((a) => whoLabel(t, a))
    : row.disputed_by;
}

// Сводка природы знания (4.5): числа по строкам карточки; нулевые части не показываются.
function natureSummary(card: Card): { verified: number; sourced: number; generated: number } {
  const rows = card.sections.flatMap((s) => s.rows);
  return {
    verified: rows.filter((r) => r.status === "verified").length,
    sourced: rows.filter((r) => r.status !== "verified" && r.evidence.length > 0 && !r.generated)
      .length,
    generated: rows.filter((r) => r.generated).length,
  };
}

export function FullCard({
  entityId,
  onClose,
  onBack,
  backLabel,
}: {
  entityId: string;
  onClose: () => void;
  onBack?: () => void;
  backLabel?: string;
}) {
  const t = useT();
  const [card, setCard] = useState<Card | null>(null);
  const [problem, setProblem] = useState<"not_found" | "failed" | null>(null);
  const [notInTextbook, setNotInTextbook] = useState(false);
  const scope = useScope();
  const textbook = storage.currentSource();
  const onlyTextbook = scope.onlyTextbook && Boolean(textbook);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    abort.current?.abort();
    abort.current = controller;
    setCard(null);
    setProblem(null);
    const params = new URLSearchParams({ generation: String(scope.generation) });
    if (textbook) params.set(onlyTextbook ? "attributed_to" : "textbook", textbook);
    fetch(`${API}/entities/${entityId}/card?${params}`, { signal: controller.signal })
      .then(async (r) => {
        const body = await r.json().catch(() => ({}));
        if (controller.signal.aborted) return;
        if (r.status === 404 && body.kind === "entity_not_found") {
          setProblem("not_found");
          return;
        }
        if (!r.ok) {
          setProblem("failed");
          return;
        }
        setCard(body as Card);
      })
      .catch(() => {
        if (!controller.signal.aborted) setProblem("failed");
      });
    return () => controller.abort();
  }, [entityId, onlyTextbook, scope.generation, textbook]);

  const family = familyOf(card?.type);
  const typeName = pick(t.family, card?.type);
  // «Нет в моём учебнике» не оставляет пустых разделов.
  const sections = (card?.sections ?? [])
    .map((s) => ({ ...s, rows: notInTextbook ? s.rows.filter((r) => r.in_textbook === false) : s.rows }))
    .filter((s) => s.rows.length > 0);
  const summary = card ? natureSummary(card) : null;

  return (
    <>
      <div className="pg-panel__head">
        {onBack && (
          <button className="pg-btn pg-btn--ghost pg-btn--sm" onClick={onBack}>
            <Icon name="arrowLeft" small />
            {backLabel ?? t.card.back}
          </button>
        )}
        <h2 className="pg-panel__title">{t.card.label}</h2>
        <button
          className="pg-btn pg-btn--ghost pg-btn--icon pg-btn--sm"
          aria-label={t.card.close}
          title={t.card.close}
          onClick={onClose}
        >
          <Icon name="close" small />
        </button>
      </div>
      <div className="pg-panel__body">
        {problem === "not_found" && (
          <div className="pg-notice pg-notice--danger" role="alert">
            <Icon name="warning" />
            <div>{t.card.notFound}</div>
          </div>
        )}
        {problem === "failed" && (
          <div className="pg-notice pg-notice--danger" role="alert">
            <Icon name="warning" />
            <div>{t.card.loadFailed}</div>
          </div>
        )}
        {card && (
          <>
            {family === "people" && (
              <PortraitGallery portraits={card.portraits ?? []} name={card.title} />
            )}
            <div className="pg-entity-head">
              {family !== "people" && <span />}
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
            {family === "people" && card.dates && <Lifeline dates={card.dates} />}
            <div className="card-scope">
              <ScopeToggle textbook={textbook} />
              {textbook && !onlyTextbook && (
                <Switch label={t.scope.notInTextbook} checked={notInTextbook} onChange={setNotInTextbook} />
              )}
            </div>
            {summary && (summary.verified || summary.sourced || summary.generated) > 0 && (
              <p className="card-summary">{t.card.summary(summary.verified, summary.sourced, summary.generated)}</p>
            )}
            {card.description &&
              (card.description.generated ? (
                <p className="pg-desc">
                  <Generated className="card-description ungrounded">{value(card.description)}</Generated>
                </p>
              ) : (
                <p className="pg-desc card-description">{value(card.description)}</p>
              ))}
            {sections.map((section) => (
              <section key={section.code} className="card-section" data-section={section.code}>
                <h4>{sectionTitle(t, section.code, section.title)}</h4>
                <ul>
                  {section.rows.map((row) => {
                    const who = believers(t, row);
                    const against = disputers(t, row);
                    return (
                      <li key={row.statement_id} className={row.generated ? "card-row ungrounded" : "card-row"}>
                        <span className="card-row__relation">
                          {relationTitle(t, row.type, Boolean(row.inverse), row.relation)}:{" "}
                        </span>
                        {row.entity_id ? (
                          <button className="pg-btn pg-btn--ghost pg-btn--sm card-row__entity">
                            {row.label}
                          </button>
                        ) : (
                          value(row)
                        )}
                        {row.status === "verified" && <StatusMark status="verified" />}
                        {row.status !== "verified" && row.evidence.length > 0 && !row.generated && (
                          <StatusMark status="sourced" />
                        )}
                        {row.generated && <StatusMark status="generated" />}
                        {row.disputed && (
                          <span className="card-disputed">
                            <StatusMark status="disputed" />
                            {against.length > 0 && (
                              <span className="card-who"> {t.card.disagree(against.join(", "))}</span>
                            )}
                          </span>
                        )}
                        {who.length > 0 && (
                          <span className="card-who"> — {t.card.believes(who.join(", "))}</span>
                        )}
                        {row.in_textbook === true && <span className="badge">{t.scope.inTextbook}</span>}
                        {row.evidence.map((e, i) => (
                          <a
                            key={e.paragraph_id}
                            className="citation pg-cite"
                            href={e.link}
                            aria-label={t.card.evidence(i + 1)}
                            onClick={(ev) => {
                              ev.preventDefault();
                              navigate(e.link);
                            }}
                          >
                            {i + 1}
                          </a>
                        ))}
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))}
            {card.where_to_read.length > 0 && (
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
            {card.recipes.length > 0 && (
              <section className="card-section pg-popover__actions" data-section="graph">
                {card.recipes.map((r) => (
                  <button
                    key={r.code}
                    className="pg-btn pg-btn--secondary pg-btn--sm card-recipe"
                    onClick={() => navigate(`/graph/${card.id}?recipe=${r.code}`)}
                  >
                    <Icon name="graph" small />
                    {recipeTitle(t, r.code, r.title)}
                  </button>
                ))}
              </section>
            )}
          </>
        )}
      </div>
    </>
  );
}
