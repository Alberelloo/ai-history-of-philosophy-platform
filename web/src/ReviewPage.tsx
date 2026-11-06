import { useEffect, useState } from "react";
import { errorText, pick, useT } from "./i18n";
import { Icon } from "./ui";

// Страница проверки онтологии для оператора: очередь по приоритету и решения.
// Без входа сервис отвечает 404, как на несуществующую страницу.

type QueueItem = {
  kind: string;
  statement_id?: string;
  item_id?: number;
  proposal_id?: number;
  type?: string;
  score: number;
  warnings?: string[];
  payload?: Record<string, unknown>;
};

type Context = {
  relation: string;
  subject: string;
  object: string | null;
  warnings: string[];
  statement: { id: string; type: string; status: string; consensus: string };
  evidence: { paragraph_text: string; quote: string; highlight: [number, number] | null; link: string }[];
};

const API = "/api/knowledge/v1";
const KINDS = ["", "warning", "lost_evidence", "generated", "ambiguous_link", "duplicate", "proposal"];

async function post(path: string, body?: unknown) {
  return fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

function Highlighted({ text, span }: { text: string; span: [number, number] | null }) {
  if (!span) return <>{text}</>;
  return (
    <>
      {text.slice(0, span[0])}
      <mark>{text.slice(span[0], span[1])}</mark>
      {text.slice(span[1])}
    </>
  );
}


export function ReviewPage() {
  const t = useT();
  const [authorized, setAuthorized] = useState<boolean | null>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<{ kind?: string; text?: string } | null>(null);
  const [kind, setKind] = useState("");
  const [items, setItems] = useState<QueueItem[]>([]);
  const [open, setOpen] = useState<Context | null>(null);
  const [newType, setNewType] = useState("");

  const load = async () => {
    const response = await fetch(`${API}/review/queue${kind ? `?kind=${kind}` : ""}`);
    if (response.status === 404) {
      setAuthorized(false);
      return;
    }
    setAuthorized(true);
    setItems(await response.json());
  };
  useEffect(() => {
    load();
  }, [kind]);

  const login = async () => {
    const response = await post("/operator/login", { password });
    if (response.ok) {
      setError(null);
      load();
    } else {
      const body = await response.json().catch(() => ({}));
      setError({ kind: body.kind, text: body.error });
    }
  };

  const openStatement = async (id: string) => {
    setOpen(await (await fetch(`${API}/review/statements/${id}`)).json());
    setNewType("");
  };

  const decide = async (decision: string, changes?: Record<string, unknown>) => {
    if (!open) return;
    await post(`/review/statements/${open.statement.id}`, { decision, changes });
    setOpen(null);
    load();
  };

  if (authorized === false) {
    return (
      <main className="page page--narrow review">
        <h1 className="page-title">{t.review.title}</h1>
        <form
          className="review-login"
          onSubmit={(e) => {
            e.preventDefault();
            login();
          }}
        >
          <div className={error ? "pg-field pg-field--error" : "pg-field"}>
            <label className="pg-field__label" htmlFor="operator-password">
              {t.review.password}
            </label>
            <div className="pg-field__control">
              <input
                id="operator-password"
                className="pg-input"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            {error && (
              <span className="pg-field__hint" role="alert">
                {error.kind ? errorText(t, error.kind, error.text) : error.text || t.review.loginFailed}
              </span>
            )}
          </div>
          <div className="actions">
            <button className="pg-btn pg-btn--primary" type="submit">
              {t.review.login}
            </button>
          </div>
        </form>
      </main>
    );
  }

  return (
    <main className="page review">
      <header className="page-header">
        <h1 className="page-title">{t.review.title}</h1>
        <div className="pg-field review-kind">
          <label className="pg-field__label" htmlFor="review-kind">
            {t.review.kind}
          </label>
          <div className="pg-field__control select">
            <select id="review-kind" className="pg-input" value={kind} onChange={(e) => setKind(e.target.value)}>
              {KINDS.map((value) => (
                <option key={value} value={value}>
                  {pick(t.review.kinds, value) ?? value}
                </option>
              ))}
            </select>
            <Icon name="chevronDown" small className="select__chevron" />
          </div>
        </div>
      </header>
      {authorized && items.length === 0 && <p className="muted">{t.review.empty}</p>}
      <ol className="review-queue">
        {items.map((item, i) => (
          <li key={i} className="review-item" data-kind={item.kind}>
            <span className="badge">{pick(t.review.kinds, item.kind) ?? item.kind}</span>
            {item.statement_id && (
              <button className="pg-btn pg-btn--ghost pg-btn--sm" onClick={() => openStatement(item.statement_id!)}>
                {item.type} · {item.warnings?.join(", ") || t.review.noWarnings}
              </button>
            )}
            {item.kind === "duplicate" && (
              <>
                <code className="review-payload">{JSON.stringify(item.payload)}</code>
                <button
                  className="pg-btn pg-btn--secondary pg-btn--sm"
                  onClick={() => post(`/review/items/${item.item_id}/duplicate?merge=true`).then(load)}
                >
                  {t.review.merge}
                </button>
                <button
                  className="pg-btn pg-btn--ghost pg-btn--sm"
                  onClick={() => post(`/review/items/${item.item_id}/duplicate?merge=false`).then(load)}
                >
                  {t.review.split}
                </button>
              </>
            )}
            {item.kind === "proposal" && (
              <>
                <code className="review-payload">{JSON.stringify(item.payload)}</code>
                <button
                  className="pg-btn pg-btn--ghost pg-btn--sm"
                  onClick={() => post(`/review/proposals/${item.proposal_id}?accept=false`).then(load)}
                >
                  {t.review.rejectType}
                </button>
              </>
            )}
            {item.kind === "ambiguous_link" && <code className="review-payload">{JSON.stringify(item.payload)}</code>}
          </li>
        ))}
      </ol>
      {open && (
        <section className="review-context" aria-label={t.review.statement}>
          <h2 className="section-title">
            {open.subject} — {open.relation} — {open.object}
          </h2>
          <p className="muted">
            {t.review.state(open.statement.status, open.statement.consensus)}
            {open.warnings.length > 0 && <> {t.review.warnings(open.warnings.join(", "))}</>}
          </p>
          {open.evidence.map((e, i) => (
            <blockquote key={i} className="quote">
              <Highlighted text={e.paragraph_text} span={e.highlight} /> <a href={e.link}>{t.review.paragraph}</a>
            </blockquote>
          ))}
          <div className="actions">
            <button className="pg-btn pg-btn--primary" onClick={() => decide("confirm")}>
              <Icon name="check" small />
              {t.review.confirm}
            </button>
            <input
              className="pg-input review-type"
              aria-label={t.review.newType}
              placeholder={t.review.newType}
              value={newType}
              onChange={(e) => setNewType(e.target.value)}
            />
            <button className="pg-btn pg-btn--secondary" disabled={!newType} onClick={() => decide("edit", { type: newType })}>
              {t.review.changeType}
            </button>
            <button className="pg-btn pg-btn--ghost" onClick={() => decide("reject")}>
              {t.review.reject}
            </button>
          </div>
        </section>
      )}
    </main>
  );
}
