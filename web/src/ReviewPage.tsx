import { useEffect, useState } from "react";

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
const KINDS: [string, string][] = [
  ["", "Все"],
  ["warning", "Предупреждения"],
  ["lost_evidence", "Утраченные подтверждения"],
  ["generated", "Сгенерированные"],
  ["ambiguous_link", "Неоднозначные привязки"],
  ["duplicate", "Кандидаты в дубли"],
  ["proposal", "Предложенные типы"],
];

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
  const [authorized, setAuthorized] = useState<boolean | null>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
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
    } else setError((await response.json()).error ?? "Не удалось войти");
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
      <main className="review">
        <h1>Проверка онтологии</h1>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            login();
          }}
        >
          <input
            type="password"
            aria-label="Пароль оператора"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button className="primary" type="submit">
            Войти
          </button>
        </form>
        {error && <p role="alert">{error}</p>}
      </main>
    );
  }

  return (
    <main className="review">
      <h1>Проверка онтологии</h1>
      <label>
        Вид{" "}
        <select aria-label="Вид элементов" value={kind} onChange={(e) => setKind(e.target.value)}>
          {KINDS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <ol className="review-queue">
        {items.map((item, i) => (
          <li key={i} className="review-item" data-kind={item.kind}>
            <span className="badge muted">{item.kind}</span>{" "}
            {item.statement_id && (
              <button className="link" onClick={() => openStatement(item.statement_id!)}>
                {item.type} · {item.warnings?.join(", ") || "без предупреждений"}
              </button>
            )}
            {item.kind === "duplicate" && (
              <>
                {JSON.stringify(item.payload)}{" "}
                <button onClick={() => post(`/review/items/${item.item_id}/duplicate?merge=true`).then(load)}>
                  Слить
                </button>{" "}
                <button onClick={() => post(`/review/items/${item.item_id}/duplicate?merge=false`).then(load)}>
                  Развести
                </button>
              </>
            )}
            {item.kind === "proposal" && (
              <>
                {JSON.stringify(item.payload)}{" "}
                <button onClick={() => post(`/review/proposals/${item.proposal_id}?accept=false`).then(load)}>
                  Отклонить тип
                </button>
              </>
            )}
            {item.kind === "ambiguous_link" && <>{JSON.stringify(item.payload)}</>}
          </li>
        ))}
      </ol>
      {open && (
        <section className="review-context" aria-label="Утверждение">
          <h2>
            {open.subject} — {open.relation} — {open.object}
          </h2>
          <p>
            Статус: {open.statement.status}. Согласие: {open.statement.consensus}.
            {open.warnings.length > 0 && <> Предупреждения: {open.warnings.join(", ")}.</>}
          </p>
          {open.evidence.map((e, i) => (
            <blockquote key={i}>
              <Highlighted text={e.paragraph_text} span={e.highlight} />{" "}
              <a href={e.link}>абзац в библиотеке</a>
            </blockquote>
          ))}
          <div className="assistant-actions">
            <button className="primary" onClick={() => decide("confirm")}>
              Подтвердить
            </button>
            <input aria-label="Новый тип связи" value={newType} onChange={(e) => setNewType(e.target.value)} />
            <button disabled={!newType} onClick={() => decide("edit", { type: newType })}>
              Изменить тип
            </button>
            <button onClick={() => decide("reject")}>Отклонить</button>
          </div>
        </section>
      )}
    </main>
  );
}
