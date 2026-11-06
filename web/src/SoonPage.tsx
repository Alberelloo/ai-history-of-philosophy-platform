import { useState, type FormEvent } from "react";
import { navigate } from "./App";
import { pick, useT } from "./i18n";
import { Icon, type IconName } from "./ui";

// Разделы продукта, которые видны в боковой панели сразу, но ещё не работают
// (docs/product/vision.md, «Сценарии» и «Объём»). Страница говорит, что раздел будет делать,
// для какого сценария и в каком он состоянии. Выдуманных данных нет.

export type SoonCode =
  | "assistant"
  | "graph"
  | "reference"
  | "epochs"
  | "compare"
  | "route"
  | "materials"
  | "collections";

export const SOON: { code: SoonCode; icon: IconName; group: "explore" | "mine"; status: "progress" | "later" }[] = [
  { code: "assistant", icon: "chat", group: "explore", status: "progress" },
  { code: "graph", icon: "graph", group: "explore", status: "progress" },
  { code: "reference", icon: "index", group: "explore", status: "progress" },
  { code: "epochs", icon: "timeline", group: "explore", status: "progress" },
  { code: "compare", icon: "scales", group: "explore", status: "later" },
  { code: "route", icon: "route", group: "explore", status: "later" },
  { code: "materials", icon: "upload", group: "mine", status: "later" },
  { code: "collections", icon: "share", group: "mine", status: "later" },
];

type Found = { id: string; type: string; names: { text: string; kind: string; lang: string }[] };

// Граф по сущности уже работает: поиск по имени ведёт на него.
function EntitySearch() {
  const t = useT();
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<Found[] | null>(null);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    fetch(`/api/knowledge/v1/entities?name=${encodeURIComponent(query.trim())}`)
      .then((r) => (r.ok ? r.json() : []))
      .then((items: Found[]) => setFound(items))
      .catch(() => setFound([]));
  };
  const name = (e: Found) => (e.names.find((n) => n.kind === "primary") ?? e.names[0])?.text ?? e.id;
  return (
    <form className="soon__search" onSubmit={submit} role="search">
      <div className="pg-field">
        <label className="pg-field__label" htmlFor="soon-entity">
          {t.soon.findEntity}
        </label>
        <div className="soon__search-row">
          <div className="pg-field__control">
            <Icon name="search" />
            <input
              id="soon-entity"
              className="pg-input"
              type="search"
              placeholder={t.soon.findPlaceholder}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <button className="pg-btn pg-btn--secondary" type="submit">
            {t.soon.find}
          </button>
        </div>
      </div>
      {found && found.length === 0 && <p className="muted">{t.soon.nothingFound}</p>}
      {found && found.length > 0 && (
        <ul className="soon__found">
          {found.map((e) => (
            <li key={e.id}>
              <a
                href={`/graph/${e.id}`}
                onClick={(ev) => {
                  ev.preventDefault();
                  navigate(`/graph/${e.id}`);
                }}
              >
                {name(e)}
              </a>
              <span className="muted"> · {pick(t.family, e.type) ?? e.type}</span>
            </li>
          ))}
        </ul>
      )}
    </form>
  );
}

export function SoonPage({ code }: { code: string }) {
  const t = useT();
  const item = SOON.find((s) => s.code === code);
  if (!item) {
    return (
      <main className="page page--narrow">
        <div className="pg-notice" role="status">
          <Icon name="info" />
          <div>{t.errors.generic}</div>
        </div>
      </main>
    );
  }
  const text = t.soon.sections[item.code];
  return (
    <main className="page page--narrow soon">
      <header className="page-header">
        <div>
          <p className="soon__status">
            <span className={item.status === "progress" ? "badge badge--accent" : "badge"}>
              {item.status === "progress" ? t.soon.inProgress : t.soon.later}
            </span>
            <span className="soon__scenario">
              {t.soon.scenario} {text.scenario}
            </span>
          </p>
          <h1 className="page-title">
            <Icon name={item.icon} className="soon__icon" />
            {text.title}
          </h1>
          <p className="page-lead">{text.what}</p>
        </div>
      </header>
      <section className="soon__now" aria-label={t.soon.now}>
        <h2 className="section-title">{t.soon.now}</h2>
        <p>{text.now}</p>
        {item.code === "graph" && <EntitySearch />}
        {item.code === "assistant" && (
          <div className="actions">
            <button className="pg-btn pg-btn--secondary" onClick={() => navigate("/read")}>
              <Icon name="book" />
              {t.soon.goReading}
            </button>
          </div>
        )}
      </section>
    </main>
  );
}
