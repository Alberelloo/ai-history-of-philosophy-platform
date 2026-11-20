import { useCallback, useEffect, useState } from "react";
import { ApiError, knowledgeApi } from "./api";
import { errorText, pick, useT } from "./i18n";
import { PortraitsReview } from "./PortraitsReview";
import { Icon, Seg } from "./ui";

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

const KINDS = ["", "warning", "lost_evidence", "generated", "ambiguous_link", "duplicate", "proposal"];
type ReviewTab = "statements" | "portraits";

// Ошибка запроса для показа: код сервиса (переводится) и текст; сбой сети — «сервис недоступен».
function problemOf(e: unknown): { kind?: string; text?: string } {
  return e instanceof ApiError ? { kind: e.kind, text: e.message } : { kind: "service_down" };
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
  const [tab, setTab] = useState<ReviewTab>("statements");

  const load = useCallback(async () => {
    try {
      const queue = await knowledgeApi.reviewQueue<QueueItem[]>(kind);
      setAuthorized(true);
      setItems(queue);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setAuthorized(false);
        return;
      }
      setAuthorized(true);
      setItems([]);
      setError(problemOf(e));
    }
  }, [kind]);
  useEffect(() => {
    load();
  }, [load]);

  const login = async () => {
    try {
      await knowledgeApi.login(password);
      setError(null);
      load();
    } catch (e) {
      setError(e instanceof ApiError ? { kind: e.details.kind as string | undefined, text: e.details.error as string | undefined } : {});
    }
  };

  const openStatement = async (id: string) => {
    try {
      setOpen(await knowledgeApi.reviewStatement<Context>(id));
      setError(null);
    } catch (e) {
      setError(problemOf(e));
    }
    setNewType("");
  };

  // Действие оператора и перечитывание очереди; ошибка действия — над очередью.
  const act = async (run: () => Promise<unknown>) => {
    try {
      await run();
    } catch (e) {
      setError(problemOf(e));
    }
    load();
  };

  const decide = async (decision: string, changes?: Record<string, unknown>) => {
    if (!open) return;
    const id = open.statement.id;
    setOpen(null);
    await act(() => knowledgeApi.decide(id, decision, changes));
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
        <Seg<ReviewTab>
          label={t.review.tab}
          value={tab}
          onChange={setTab}
          items={[
            { value: "statements", label: t.review.statements },
            { value: "portraits", label: t.review.portraits },
          ]}
        />
      </header>
      {tab === "statements" ? (
        <>
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
          {error && (
            <div className="pg-notice pg-notice--danger" role="alert">
              <Icon name="warning" />
              <div>{errorText(t, error.kind, error.text)}</div>
            </div>
          )}
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
                  onClick={() => act(() => knowledgeApi.duplicate(item.item_id!, true))}
                >
                  {t.review.merge}
                </button>
                <button
                  className="pg-btn pg-btn--ghost pg-btn--sm"
                  onClick={() => act(() => knowledgeApi.duplicate(item.item_id!, false))}
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
                  onClick={() => act(() => knowledgeApi.proposal(item.proposal_id!, false))}
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
        </>
      ) : (
        <PortraitsReview />
      )}
    </main>
  );
}
