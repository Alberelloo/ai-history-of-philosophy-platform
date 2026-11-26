import { useEffect, useRef, useState, type ReactNode } from "react";
import { navigate } from "./App";
import { pick, recipeTitle, relationTitle, sectionTitle, useT, whoLabel } from "./i18n";
import { ScopeToggle, useScope } from "./scope";
import { storage } from "./storage";
import { familyOf, Icon, type LifeDates, PortraitGallery, Switch, type PortraitItem } from "./ui";

// Полная карточка в правой панели (redesign-entity-cards; reader-panels.md, 4.5–4.6). Шаблон
// задаёт сервер (`layout`): у персоны шапка — имя и строка сводки (роль, место, государство,
// годы), без линии жизни и «Где читать»; у остальных — инфобокс и короткие списки. Отбор,
// порядок, свёртку и отметку строк присылает сервер; клиент только показывает. Статус строки —
// метка цветом и формой, словом — только в легенде (одна на карточку).

type Who = { who: string; kind?: string; stance?: string };
type Mark = "verified" | "sourced" | "generated" | "disputed";
type Geo = { lat: number; lon: number };
export type Row = {
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
  qualifiers?: Record<string, unknown>; // механизм «стимулировало» и др. (проверены сервером)
  mark?: Mark;
  inferred?: boolean;
  via?: { entity_id: string; label: string }[];
  note?: string | null;
  geo?: Geo | null;
};
type Section = {
  code: string;
  title: string;
  rows: Row[];
  display?: "facts" | "list" | "inline";
  visible?: number | null;
  inferred?: boolean;
};
type Card = {
  id: string;
  type?: string;
  title: string;
  dates: LifeDates | null;
  description: Row | null;
  description_pending: boolean;
  portraits?: PortraitItem[];
  sections: Section[];
  where_to_read: {
    source_id: string;
    source_title: string | null;
    chapter_id: string;
    chapter_title: string | null;
    count: number;
    // N10: первый абзац главы с упоминанием; «Где читать» ведёт к нему, а не к началу главы.
    first_paragraph_id?: string | null;
  }[];
  recipes: { code: string; title: string }[];
  layout?: "person" | "entity" | "epoch";
  summary?: {
    roles: Row[];
    place: Row | null;
    years: string | null;
    polity: { name: string; name_status: string; year: number } | null;
  } | null;
  geo?: Geo | null;
  legend?: Mark[];
  empty?: boolean;
};

const API = "/api/knowledge/v1";
const MARKS: Mark[] = ["verified", "sourced", "generated", "disputed"];

// Переход по связи в полной карточке (4.6): событие ловит экран чтения и кладёт карточку
// наверх стека панели, поэтому «Назад» подписан «Назад: <прежняя карточка>».
export const OPEN_CARD_EVENT = "philograph:open-card";

export function openCardInPanel(entityId: string, title: string): void {
  window.dispatchEvent(new CustomEvent(OPEN_CARD_EVENT, { detail: { entityId, title } }));
}

// Адрес «Где читать»: к первому абзацу с упоминанием (N10), без него — к началу главы.
export function whereToReadLink(w: { source_id: string; chapter_id: string; first_paragraph_id?: string | null }) {
  const base = `/read/${w.source_id}/${w.chapter_id}`;
  return w.first_paragraph_id ? `${base}#p-${w.first_paragraph_id}` : base;
}

type T = ReturnType<typeof useT>;

function value(t: T, row: Row): string {
  if (row.label) return row.label;
  const v = row.value as { original?: string } | { lat: number; lon: number } | string | null;
  if (v && typeof v === "object" && "original" in v) return String(v.original);
  if (v && typeof v === "object" && "lat" in v && "lon" in v) return `${v.lat}, ${v.lon}`; // координаты места
  if (typeof v === "string" && row.type) {
    // Значение из списка реестра (роль, вид группы, вид события) — по коду.
    const names = (t.onto.values as Record<string, Record<string, string>>)[row.type];
    if (names && names[v]) return names[v];
  }
  return v ? String(v) : "";
}

function markOf(row: Row): Mark {
  return row.mark ?? (row.disputed ? "disputed" : (row.status as Mark));
}

// «Так считает» — только те, кто не возражает: несогласные идут отдельно («не согласны»).
function believers(t: T, row: Row): string[] {
  if (row.attributions) {
    return [...new Set(row.attributions.filter((a) => a.stance !== "disputes").map((a) => whoLabel(t, a)))];
  }
  return row.attributed_to.filter((who) => !row.disputed_by.includes(who));
}

function disputers(t: T, row: Row): string[] {
  return row.attributions
    ? row.attributions.filter((a) => a.stance === "disputes").map((a) => whoLabel(t, a))
    : row.disputed_by;
}

// Доступное имя метки: статус, атрибуция, несогласные; у вывода — через что он сделан.
function markName(t: T, row: Row): string {
  const parts = [t.status[markOf(row)]];
  if (row.inferred) {
    const via = (row.via ?? []).map((v) => v.label);
    if (via.length) parts.push(t.card.inferredVia(via.join(", ")));
  } else {
    const who = believers(t, row);
    const against = disputers(t, row);
    if (who.length) parts.push(t.card.believes(who.join(", ")));
    if (against.length) parts.push(t.card.disagree(against.join(", ")));
  }
  // Доступное имя читается как предложения: каждая часть — с заглавной буквы.
  return parts.map(capitalize).join(". ");
}

function capitalize(text: string): string {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

// Подпись инфобокса: человеческая подпись поля («Автор», «Дата»), а не название связи реестра.
function factLabel(t: T, row: Row): string {
  const own = row.type && !row.inverse ? (t.card.facts as Record<string, string>)[row.type] : undefined;
  return own ?? capitalize(relationTitle(t, row.type, Boolean(row.inverse), row.relation));
}

// Метка статуса: форма и цвет по отметке, без текста; нажатие раскрывает подробности строки.
function MarkButton({ row, open, onToggle }: { row: Row; open: boolean; onToggle: () => void }) {
  const t = useT();
  const name = markName(t, row);
  return (
    <button
      type="button"
      className="card-mark"
      data-mark={markOf(row)}
      aria-label={name}
      title={name}
      aria-expanded={open}
      onClick={onToggle}
    >
      <span className="card-mark__shape" aria-hidden="true" />
    </button>
  );
}

function RowDetails({ row, open }: { row: Row; open: boolean }) {
  const t = useT();
  const who = believers(t, row);
  const against = disputers(t, row);
  const via = (row.via ?? []).map((v) => v.label);
  return (
    <span className="card-row__details" hidden={!open}>
      {row.inferred && via.length > 0 && <span>{t.card.inferredVia(via.join(", "))}</span>}
      {who.length > 0 && <span>{t.card.believes(who.join(", "))}</span>}
      {against.length > 0 && <span>{t.card.disagree(against.join(", "))}</span>}
    </span>
  );
}

function Citations({ row }: { row: Row }) {
  const t = useT();
  return (
    <>
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
    </>
  );
}

function RowValue({ row }: { row: Row }) {
  const t = useT();
  return row.entity_id ? (
    <button
      className="pg-btn pg-btn--ghost pg-btn--sm card-row__entity"
      onClick={() => openCardInPanel(row.entity_id!, row.label ?? row.entity_id!)}
    >
      {row.label}
    </button>
  ) : (
    <span className="card-row__value">{value(t, row)}</span>
  );
}

// Строка карточки: значение, механизм (контекст), год труда, метка, ссылки на абзацы.
function CardRow({
  row,
  section,
  as: Tag,
  relation = false,
}: {
  row: Row;
  section: string;
  as: "li" | "span" | "dd";
  relation?: boolean;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  return (
    <Tag
      className="card-row"
      data-mark={markOf(row)}
      data-inferred={row.inferred ? "true" : undefined}
      data-unverified={row.generated ? "true" : undefined}
    >
      {relation && (
        <span className="card-row__relation">{relationTitle(t, row.type, Boolean(row.inverse), row.relation)}: </span>
      )}
      <RowValue row={row} />
      {section === "context" && <Mechanism row={row} />}
      {row.note && <span className="card-row__note"> {row.note}</span>}
      <MarkButton row={row} open={open} onToggle={() => setOpen((v) => !v)} />
      {row.in_textbook === true && <span className="badge">{t.scope.inTextbook}</span>}
      <Citations row={row} />
      <RowDetails row={row} open={open} />
    </Tag>
  );
}

// Раздел по виду показа: инфобокс (подпись — значение), список или строка через запятую;
// сверх `visible` строк — «Показать все (N)».
function CardSection({ section }: { section: Section }) {
  const t = useT();
  const [all, setAll] = useState(false);
  const limit = section.visible ?? null;
  const more = limit !== null && section.rows.length > limit;
  const rows = more && !all ? section.rows.slice(0, limit) : section.rows;
  const display = section.display ?? "list";
  // Подпись связи у строки — только если в разделе связи разные (иначе её говорит заголовок).
  const mixed = new Set(section.rows.map((r) => `${r.type}:${r.inverse ? 1 : 0}`)).size > 1;
  let body: ReactNode;
  if (display === "facts") {
    body = (
      <dl className="card-facts">
        {rows.map((row) => (
          <div key={row.statement_id} className="card-facts__item">
            <dt>{factLabel(t, row)}</dt>
            <CardRow row={row} section={section.code} as="dd" />
          </div>
        ))}
      </dl>
    );
  } else if (display === "inline") {
    body = (
      <p className="card-inline">
        {rows.map((row, i) => (
          <span key={row.statement_id}>
            {i > 0 && ", "}
            <CardRow row={row} section={section.code} as="span" />
          </span>
        ))}
      </p>
    );
  } else {
    body = (
      <ul>
        {rows.map((row) => (
          <CardRow key={row.statement_id} row={row} section={section.code} as="li" relation={mixed} />
        ))}
      </ul>
    );
  }
  return (
    <section className="card-section" data-section={section.code} data-display={display}>
      <h4>
        {sectionTitle(t, section.code, section.title)}
        {section.inferred && (
          <span className="card-section__inferred" data-inferred="">
            {" "}
            {t.card.inferredSection}
          </span>
        )}
      </h4>
      {body}
      {more && (
        <button
          type="button"
          className="pg-btn pg-btn--ghost pg-btn--sm card-more"
          data-card-more=""
          aria-expanded={all}
          onClick={() => setAll((v) => !v)}
        >
          {all ? t.card.collapse : t.card.showAll(section.rows.length)}
        </button>
      )}
    </section>
  );
}

// Современная страна по координатам (правило глобуса, countries.ts) — только запасной путь
// и только с пометкой «ныне …». Модуль границ подгружается по требованию.
function useModernCountry(geo: Geo | null | undefined, skip: boolean): string | null {
  const [name, setName] = useState<string | null>(null);
  const lat = geo?.lat;
  const lon = geo?.lon;
  useEffect(() => {
    setName(null);
    if (skip || lat === undefined || lon === undefined) return;
    let alive = true;
    import("./map/geo/countries")
      .then((m) => {
        if (alive) setName(m.countryAt(lat, lon)?.name ?? null);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [lat, lon, skip]);
  return name;
}

function PersonSummary({ card }: { card: Card }) {
  const t = useT();
  const summary = card.summary;
  const place = summary?.place ?? null;
  const polity = summary?.polity ?? null;
  const modern = useModernCountry(place?.geo, Boolean(polity));
  if (!summary) return null;
  const parts: ReactNode[] = [];
  if (summary.roles.length > 0)
    parts.push(
      <span key="role" data-summary="role">
        {summary.roles.map((r) => value(t, r)).join(", ")}
      </span>,
    );
  if (place)
    parts.push(
      <span key="place" data-summary="place">
        {place.entity_id ? (
          <button
            className="pg-btn pg-btn--ghost pg-btn--sm card-row__entity"
            onClick={() => openCardInPanel(place.entity_id!, place.label ?? place.entity_id!)}
          >
            {place.label}
          </button>
        ) : (
          value(t, place)
        )}
      </span>,
    );
  if (polity)
    parts.push(
      <span key="country" data-summary="country" data-country-kind="historical" title={t.card.polityYear(polity.year)}>
        {polity.name}
      </span>,
    );
  else if (modern)
    parts.push(
      <span key="country" data-summary="country" data-country-kind="modern">
        {t.card.nowCountry(modern)}
      </span>,
    );
  if (summary.years)
    parts.push(
      <span key="years" data-summary="years">
        {summary.years}
      </span>,
    );
  if (parts.length === 0) return null;
  return (
    <p className="card-summary-line" data-card-summary="">
      {parts.map((p, i) => (
        <span key={i}>
          {i > 0 && " · "}
          {p}
        </span>
      ))}
    </p>
  );
}

// Инфобокс места: координаты всегда (тело не пустое при любом исходе поиска страны),
// страна — только когда найдена по координатам.
function PlaceFacts({ geo }: { geo: Geo | null | undefined }) {
  const t = useT();
  const modern = useModernCountry(geo, false);
  if (!geo) return null;
  return (
    <dl className="card-facts card-facts--place">
      <div className="card-facts__item">
        <dt>{t.card.coordinatesLabel}</dt>
        <dd data-card-coordinates="">{t.card.coordinates(geo.lat, geo.lon)}</dd>
      </div>
      {modern && (
        <div className="card-facts__item">
          <dt>{t.card.country}</dt>
          <dd data-card-country="" data-country-kind="modern">
            {t.card.nowCountry(modern)}
          </dd>
        </div>
      )}
    </dl>
  );
}

function Legend({ marks }: { marks: Mark[] }) {
  const t = useT();
  return (
    <ul className="card-legend" data-card-legend="" aria-label={t.card.legendLabel}>
      {MARKS.filter((m) => marks.includes(m)).map((m) => (
        <li key={m} data-legend={m}>
          <span className="card-mark card-mark--static" data-mark={m} aria-hidden="true">
            <span className="card-mark__shape" />
          </span>
          <span className="card-legend__label">{t.status[m]}</span>
          <span className="card-legend__hint"> — {t.card.legend[m]}</span>
        </li>
      ))}
    </ul>
  );
}

export function FullCard({
  entityId,
  title,
  onClose,
  onBack,
  backLabel,
}: {
  entityId: string;
  // Имя, известное до загрузки (из упоминания или строки карточки): голова панели при загрузке.
  title?: string;
  onClose: () => void;
  onBack?: () => void;
  backLabel?: string;
}) {
  const t = useT();
  const [card, setCard] = useState<Card | null>(null);
  const [problem, setProblem] = useState<"not_found" | "failed" | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [notInTextbook, setNotInTextbook] = useState(false);
  const [descOpen, setDescOpen] = useState(false);
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
  }, [entityId, onlyTextbook, scope.generation, textbook, attempt]);

  const family = familyOf(card?.type);
  const typeName = pick(t.family, card?.type);
  const person = card?.layout === "person";
  // «Нет в моём учебнике» не оставляет пустых разделов.
  const sections = (card?.sections ?? [])
    .map((s) => ({ ...s, rows: notInTextbook ? s.rows.filter((r) => r.in_textbook === false) : s.rows }))
    .filter((s) => s.rows.length > 0);
  const legend = card?.legend ?? [];

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
      <div className="pg-panel__body" aria-busy={!card && !problem ? true : undefined}>
        {!card && !problem && (
          <div className="pg-entity-head card-panel__loading">
            <span />
            <div>
              {title && <h3 className="pg-entity-head__name">{title}</h3>}
              <p className="card-loading" role="status">
                {t.card.loading}
              </p>
            </div>
          </div>
        )}
        {problem === "not_found" && (
          <div className="pg-notice pg-notice--danger pg-notice--stacked" role="alert">
            <Icon name="warning" />
            <div>{t.card.notFound}</div>
          </div>
        )}
        {problem === "failed" && (
          <div className="pg-notice pg-notice--danger pg-notice--stacked" role="alert">
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
            {family === "people" && card.type === "person" && (
              <PortraitGallery portraits={card.portraits ?? []} name={card.title} />
            )}
            <div className="pg-entity-head">
              {!person && <span />}
              <div>
                <h3 className="pg-entity-head__name">{card.title}</h3>
                {person ? (
                  <PersonSummary card={card} />
                ) : (
                  <div className="pg-entity-head__meta">
                    {typeName && (
                      <span className="pg-chip" data-family={family}>
                        {typeName}
                      </span>
                    )}
                    {card.dates && <span className="card-dates">{card.dates.original}</span>}
                  </div>
                )}
              </div>
            </div>
            <div className="card-scope">
              <ScopeToggle textbook={textbook} />
              {textbook && !onlyTextbook && (
                <Switch label={t.scope.notInTextbook} checked={notInTextbook} onChange={setNotInTextbook} />
              )}
            </div>
            {legend.length > 0 && <Legend marks={legend} />}
            {card.description && (
              <p className="pg-desc card-description" data-unverified={card.description.generated ? "true" : undefined}>
                {value(t, card.description)}
                {card.description.generated && (
                  <MarkButton row={card.description} open={descOpen} onToggle={() => setDescOpen((v) => !v)} />
                )}
              </p>
            )}
            {card.type === "place" && <PlaceFacts geo={card.geo} />}
            {card.empty && (
              <div className="card-empty" data-card-empty="">
                <p>{t.card.emptyTitle}</p>
                <p className="card-empty__hint">
                  {card.where_to_read.length > 0 ? t.card.emptyWhere : t.card.emptyAsk}
                </p>
              </div>
            )}
            {sections.map((section) => (
              <CardSection key={section.code} section={section} />
            ))}
            {card.where_to_read.length > 0 && (
              <section className="card-section" data-section="where">
                <h4>{t.card.whereToRead}</h4>
                <ul className="card-where">
                  {card.where_to_read.map((w) => (
                    <li key={`${w.source_id}-${w.chapter_id}`}>
                      <button
                        className="pg-btn pg-btn--ghost pg-btn--sm card-where__chapter"
                        data-paragraph={w.first_paragraph_id ?? undefined}
                        onClick={() => navigate(whereToReadLink(w))}
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

// Механизм в строке раздела «Исторический контекст»: подпись значения из списка реестра или
// «механизм не указан» (epoch-context, «Механизм влияния»).
function Mechanism({ row }: { row: Row }) {
  const t = useT();
  const code = typeof row.qualifiers?.mechanism === "string" ? row.qualifiers.mechanism : null;
  const label = code ? (pick(t.onto.qualifiers.mechanism, code) ?? code) : null;
  return (
    <span className={label ? "card-row__mechanism" : "card-row__mechanism is-missing"} data-mechanism={code ?? ""}>
      {" · "}
      {label ?? t.epochs.context.noMechanism}{" "}
    </span>
  );
}
