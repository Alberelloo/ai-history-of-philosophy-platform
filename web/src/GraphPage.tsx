import { useEffect, useMemo, useRef, useState } from "react";
import { navigate } from "./App";
import { CardPopup } from "./CardPopup";
import { ScopeToggle, setScope, useScope } from "./scope";
import { storage } from "./storage";

// Граф по запросу: сохранённые связи приходят сразу, достроенные моделью — по мере появления.
// Пометка достроенного задаётся атрибутами SVG, а не стилями страницы, поэтому сохраняется
// в выгруженном изображении.

type GNode = { id: string; label: string; type: string; depth: number; year: number | null; dates: string | null };
type GEdge = {
  id: string;
  subject: string;
  object: string;
  type: string;
  title: string;
  status: string;
  generated: boolean;
  pending: boolean;
  consensus: string;
  qualifiers: Record<string, unknown>;
  attributions: { who: string; stance: string; place: string | null }[];
  evidence: { paragraph_id: string; quote: string; link: string }[];
  in_textbook: boolean | null;
};
type Recipe = { code: string; title: string; depth: number };
type State = {
  nodes: Record<string, GNode>;
  edges: GEdge[];
  order: string | null;
  depth: number;
  maxDepth: number;
  truncated: boolean;
  extension: string;
  notice: string | null;
  recipes: Recipe[];
  done: boolean;
};

const API = "/api/knowledge/v1";
const STATUS = { verified: "проверено", sourced: "по источникам", generated: "сгенерировано", rejected: "отклонено" };
const STANCE: Record<string, string> = { asserts: "утверждает", disputes: "оспаривает", mentions: "упоминает" };
const COLORS: Record<string, string> = { person: "#7a3e1d", concept: "#2f5d8a", doctrine: "#4f7a3a", work: "#8a6d2f" };
const STROKE: Record<string, string> = { verified: "#1d1b18", sourced: "#6b655c", generated: "#b07d2c" };

async function* lines(response: Response): AsyncGenerator<Record<string, unknown>> {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n");
    buffer = parts.pop() ?? "";
    for (const line of parts) if (line.trim()) yield JSON.parse(line);
  }
}

function layout(nodes: GNode[], order: string | null): Record<string, { x: number; y: number }> {
  const result: Record<string, { x: number; y: number }> = {};
  if (order === "time") {
    // Слева направо по времени. Ряды чередуются неравномерно, чтобы три узла не вставали
    // на одну прямую и связь не проходила сквозь узел посередине.
    const lanes = [70, 210, 130, 270];
    const sorted = [...nodes].sort((a, b) => (a.year ?? Infinity) - (b.year ?? Infinity));
    sorted.forEach((n, i) => (result[n.id] = { x: 90 + i * 160, y: lanes[i % lanes.length] }));
    return result;
  }
  const columns: Record<number, GNode[]> = {};
  nodes.forEach((n) => (columns[n.depth] ??= []).push(n));
  Object.entries(columns).forEach(([depth, column]) =>
    column.forEach((n, i) => (result[n.id] = { x: 90 + Number(depth) * 190, y: 70 + i * 95 })),
  );
  return result;
}

function Shape({ node, x, y }: { node: GNode; x: number; y: number }) {
  const fill = COLORS[node.type] ?? "#666";
  if (node.type === "person") return <circle cx={x} cy={y} r={20} fill={fill} />;
  if (node.type === "concept") return <rect x={x - 20} y={y - 16} width={40} height={32} rx={6} fill={fill} />;
  return <polygon points={`${x},${y - 22} ${x + 22},${y} ${x},${y + 22} ${x - 22},${y}`} fill={fill} />;
}

export function GraphPage({ entityId, query }: { entityId: string; query: URLSearchParams }) {
  const scope = useScope();
  const textbook = storage.currentSource();
  const [recipe, setRecipe] = useState(query.get("recipe") ?? "genesis");
  const [depth, setDepth] = useState<number | null>(query.get("depth") ? Number(query.get("depth")) : null);
  const [state, setState] = useState<State | null>(null);
  const [problem, setProblem] = useState<{ message: string; suggestions: Recipe[] } | null>(null);
  const [selected, setSelected] = useState<{ edge?: string; node?: string }>({});
  const [card, setCard] = useState<{ id: string; x: number; y: number } | null>(null);
  const [notInTextbook, setNotInTextbook] = useState(false);
  const svg = useRef<SVGSVGElement>(null);
  const onlyTextbook = scope.onlyTextbook && Boolean(textbook);

  async function load(start: string, startDepth: number | null, merge: boolean) {
    const response = await fetch(`${API}/graph/build`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        entity_id: start,
        recipe,
        depth: startDepth,
        textbook: textbook ?? null,
        only_textbook: onlyTextbook,
        generation: merge ? false : scope.generation,
      }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      setProblem({ message: body.error ?? "Не удалось построить граф", suggestions: body.suggestions ?? [] });
      return;
    }
    for await (const event of lines(response)) {
      if (event.type === "graph") {
        const nodes = Object.fromEntries((event.nodes as GNode[]).map((n) => [n.id, n]));
        setState((old) =>
          merge && old
            ? {
                ...old,
                nodes: { ...nodes, ...old.nodes },
                edges: [...old.edges, ...(event.edges as GEdge[]).filter((e) => !old.edges.some((o) => o.id === e.id))],
              }
            : {
                nodes,
                edges: event.edges as GEdge[],
                order: (event.recipe as { order: string | null }).order,
                depth: event.depth as number,
                maxDepth: event.max_depth as number,
                truncated: event.truncated as boolean,
                extension: event.extension as string,
                notice: (event.notice as string | null) ?? null,
                recipes: event.recipes as Recipe[],
                done: false,
              },
        );
      } else if (event.type === "edge") {
        setState((old) =>
          old && {
            ...old,
            edges: [...old.edges, event.edge as GEdge],
            nodes: { ...old.nodes, ...Object.fromEntries((event.nodes as GNode[]).map((n) => [n.id, n])) },
          },
        );
      } else if (event.type === "notice") {
        setState((old) => old && { ...old, extension: event.extension as string, notice: event.message as string });
      } else if (event.type === "done") {
        setState((old) => old && (merge ? old : { ...old, done: true }));
      }
    }
  }

  useEffect(() => {
    setState(null);
    setProblem(null);
    setSelected({});
    window.history.replaceState(null, "", `/graph/${entityId}?recipe=${recipe}${depth ? `&depth=${depth}` : ""}`);
    load(entityId, depth, false).catch(() => setProblem({ message: "Сервис знаний недоступен", suggestions: [] }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityId, recipe, depth, onlyTextbook, scope.generation]);

  const visible = useMemo(() => {
    if (!state) return { nodes: [] as GNode[], edges: [] as GEdge[] };
    const edges = notInTextbook ? state.edges.filter((e) => e.in_textbook === false) : state.edges;
    const used = new Set([entityId, ...edges.flatMap((e) => [e.subject, e.object])]);
    return { nodes: Object.values(state.nodes).filter((n) => used.has(n.id)), edges };
  }, [state, notInTextbook, entityId]);
  const positions = useMemo(() => layout(visible.nodes, state?.order ?? null), [visible, state?.order]);
  const width = Math.max(480, ...Object.values(positions).map((p) => p.x + 110));
  const height = Math.max(260, ...Object.values(positions).map((p) => p.y + 90));
  const label = (id: string) => state?.nodes[id]?.label ?? "…";
  // Дуги с изгибом в разные стороны: связи одного узла не сливаются в одну линию,
  // у каждой своя ручка посередине.
  const curves = visible.edges.flatMap((e, index) => {
    const a = positions[e.subject];
    const b = positions[e.object];
    if (!a || !b) return [];
    const length = Math.hypot(b.x - a.x, b.y - a.y) || 1;
    const bend = (index % 2 ? 1 : -1) * (0.18 + (index % 3) * 0.06) * length;
    const c = {
      x: (a.x + b.x) / 2 - ((b.y - a.y) / length) * bend,
      y: (a.y + b.y) / 2 + ((b.x - a.x) / length) * bend,
    };
    return [
      {
        e,
        d: `M${a.x},${a.y} Q${c.x},${c.y} ${b.x},${b.y}`,
        mid: { x: (a.x + 2 * c.x + b.x) / 4, y: (a.y + 2 * c.y + b.y) / 4 },
        stroke: STROKE[e.status] ?? "#6b655c",
        name: `${label(e.subject)} — ${e.title} — ${label(e.object)}`,
      },
    ];
  });
  const edge = state?.edges.find((e) => e.id === selected.edge);
  const node = selected.node ? state?.nodes[selected.node] : undefined;
  const start = state?.nodes[entityId];

  function download() {
    if (!svg.current) return;
    const text = new XMLSerializer().serializeToString(svg.current);
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([text], { type: "image/svg+xml" }));
    link.download = `graph-${recipe}.svg`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  return (
    <div className="graph-page">
      <header className="graph-header">
        <button className="link" onClick={() => navigate(textbook ? `/read/${textbook}` : "/")}>
          ← К чтению
        </button>
        <h1>{start ? `${state?.recipes.find((r) => r.code === recipe)?.title ?? "Граф"}: ${start.label}` : "Граф"}</h1>
      </header>
      <div className="graph-controls">
        <label>
          Рецепт{" "}
          <select aria-label="Рецепт" value={recipe} onChange={(e) => (setDepth(null), setRecipe(e.target.value))}>
            {(state?.recipes ?? [{ code: recipe, title: recipe, depth: 1 }]).map((r) => (
              <option key={r.code} value={r.code}>
                {r.title}
              </option>
            ))}
          </select>
        </label>
        {state && (
          <span className="graph-depth">
            Глубина {state.depth} из {state.maxDepth}{" "}
            <button disabled={state.depth <= 1} onClick={() => setDepth(state.depth - 1)}>
              Мельче
            </button>{" "}
            <button disabled={state.depth >= state.maxDepth} onClick={() => setDepth(state.depth + 1)}>
              Глубже
            </button>
          </span>
        )}
        <ScopeToggle textbook={textbook} />
        <label>
          <input type="checkbox" checked={scope.generation} onChange={(e) => setScope({ generation: e.target.checked })} />
          Достраивать моделью
        </label>
        <label>
          <input
            type="checkbox"
            checked={notInTextbook}
            disabled={!textbook || onlyTextbook}
            onChange={(e) => setNotInTextbook(e.target.checked)}
          />
          Нет в моём учебнике
        </label>
        <button onClick={download} disabled={!state}>
          Сохранить изображение
        </button>
      </div>
      {problem && (
        <div className="graph-problem" role="alert">
          {problem.message}
          {problem.suggestions.map((r) => (
            <button key={r.code} className="link" onClick={() => setRecipe(r.code)}>
              {r.title}
            </button>
          ))}
        </div>
      )}
      {state?.notice && (
        <p className="notice" role="status">
          {state.notice}
          {state.extension === "scope" && (
            <button className="link" onClick={() => setScope({ onlyTextbook: false })}>
              Показать все источники
            </button>
          )}
        </p>
      )}
      {state?.truncated && <p className="notice">Показана часть графа: раскройте узел, чтобы увидеть его связи.</p>}
      {state && state.extension === "pending" && !state.done && <p className="loading">Достраиваю недостающие связи…</p>}
      {state?.done && visible.edges.length === 0 && (
        <div className="graph-empty">
          <p>Связей пока нет.</p>
          {state.extension === "disabled" && (
            <button className="link" onClick={() => setScope({ generation: true })}>
              Включить достройку моделью
            </button>
          )}
          {state.recipes
            .filter((r) => r.code !== recipe)
            .map((r) => (
              <button key={r.code} className="link" onClick={() => setRecipe(r.code)}>
                Попробовать: {r.title}
              </button>
            ))}
        </div>
      )}
      {state && visible.edges.length > 0 && (
        <svg
          ref={svg}
          xmlns="http://www.w3.org/2000/svg"
          className="graph"
          width={width}
          height={height + 30}
          viewBox={`0 0 ${width} ${height + 30}`}
          role="img"
          aria-label="Граф связей"
        >
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="30" refY="5" markerWidth="7" markerHeight="7" orient="auto">
              <path d="M0,0 L10,5 L0,10 z" fill="#6b655c" />
            </marker>
          </defs>
          <rect width="100%" height="100%" fill="#fbf9f4" />
          {/* Линии — только рисунок; нажимаются ручки в верхнем слое. */}
          {curves.map(({ e, d, stroke }) => (
            <path
              key={e.id}
              className="graph-line"
              data-generated={e.generated ? "true" : "false"}
              d={d}
              fill="none"
              stroke={stroke}
              strokeWidth={e.id === selected.edge ? 3 : 1.6}
              strokeDasharray={e.generated ? "6 4" : undefined}
              markerEnd="url(#arrow)"
            />
          ))}
          {visible.nodes.map((n) => {
            const p = positions[n.id];
            return (
              <g
                key={n.id}
                className="graph-node"
                data-node={n.id}
                data-type={n.type}
                data-x={p.x}
                role="button"
                aria-label={n.label}
                tabIndex={0}
                onClick={() => setSelected({ node: n.id })}
                onKeyDown={(k) => k.key === "Enter" && setSelected({ node: n.id })}
              >
                <Shape node={n} x={p.x} y={p.y} />
                <text x={p.x} y={p.y + 38} textAnchor="middle" fontSize="13" fill="#1d1b18">
                  {n.label}
                </text>
                {n.dates && (
                  <text x={p.x} y={p.y + 53} textAnchor="middle" fontSize="11" fill="#6b655c">
                    {n.dates}
                  </text>
                )}
              </g>
            );
          })}
          {/* Ручки связей поверх линий и узлов: любую связь можно нажать. */}
          {curves.map(({ e, mid, stroke, name }) => (
            <g
              key={e.id}
              className="graph-edge"
              data-edge={e.id}
              data-status={e.status}
              data-generated={e.generated ? "true" : "false"}
              role="button"
              aria-label={name}
              tabIndex={0}
              onClick={() => setSelected({ edge: e.id })}
              onKeyDown={(k) => k.key === "Enter" && setSelected({ edge: e.id })}
            >
              <circle cx={mid.x} cy={mid.y} r={9} fill="#fff" stroke={stroke} />
              <text x={mid.x} y={mid.y + 4} fill={e.generated ? "#b07d2c" : stroke} fontSize="11" textAnchor="middle">
                {e.generated ? "◇" : "•"}
                <title>{e.generated ? `${name}: достроено моделью, не подтверждено источниками` : name}</title>
              </text>
            </g>
          ))}
          <text x={12} y={height + 18} fontSize="11" fill="#6b655c">
            ◇ и пунктир — достроено моделью, не подтверждено источниками
          </text>
        </svg>
      )}
      {edge && (
        <aside className="graph-details" role="region" aria-label="Связь">
          <h2>
            {label(edge.subject)} — {edge.title} — {label(edge.object)}
          </h2>
          <p>
            Статус: {STATUS[edge.status as keyof typeof STATUS] ?? edge.status}
            {edge.consensus === "disputed" && <span className="badge muted">спорно</span>}
            {edge.in_textbook === true && <span className="badge muted">есть в учебнике</span>}
            {edge.in_textbook === false && <span className="badge muted">нет в учебнике</span>}
          </p>
          {edge.generated && (
            <p className="card-description ungrounded">
              <span className="ungrounded-mark" role="img" aria-label="Сгенерировано">
                ◇
              </span>
              Связь достроена моделью и не подтверждена источниками.
            </p>
          )}
          {Object.keys(edge.qualifiers).length > 0 && (
            <p>
              {Object.entries(edge.qualifiers)
                .map(([k, v]) => `${k}: ${String(v)}`)
                .join("; ")}
            </p>
          )}
          {edge.attributions.length > 0 && (
            <ul className="graph-who">
              {edge.attributions.map((a, i) => (
                <li key={i}>
                  так считает: {a.who} ({STANCE[a.stance] ?? a.stance}
                  {a.place ? `, ${a.place}` : ""})
                </li>
              ))}
            </ul>
          )}
          {edge.evidence.map((ev) => (
            <blockquote key={ev.paragraph_id} className="selection-context">
              «{ev.quote}»{" "}
              <a
                className="citation"
                href={ev.link}
                onClick={(x) => {
                  x.preventDefault();
                  navigate(ev.link);
                }}
              >
                [абзац]
              </a>
            </blockquote>
          ))}
        </aside>
      )}
      {node && (
        <aside className="graph-details" role="region" aria-label="Узел">
          <h2>{node.label}</h2>
          <button
            className="link"
            onClick={(e) => setCard({ id: node.id, x: e.pageX, y: e.pageY + 12 })}
          >
            Открыть карточку
          </button>{" "}
          <button className="link" onClick={() => load(node.id, 1, true)}>
            Раскрыть связи
          </button>
        </aside>
      )}
      {card && <CardPopup entityId={card.id} x={card.x} y={card.y} onClose={() => setCard(null)} />}
    </div>
  );
}
