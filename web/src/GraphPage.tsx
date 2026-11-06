import { useEffect, useMemo, useRef, useState } from "react";
import { navigate } from "./App";
import { CardPopup } from "./CardPopup";
import { errorText, pick, recipeTitle, relationTitle, useT, whoLabel } from "./i18n";
import { ScopeToggle, setScope, useScope } from "./scope";
import { storage } from "./storage";
import { familyOf, Generated, Icon, StatusMark, Switch } from "./ui";

// Граф по запросу: сохранённые связи приходят сразу, достроенные моделью — по мере появления.
// Пометка достроенного (пунктир, ромб) задаётся атрибутами SVG; цвета берутся из токенов
// через классы, а при выгрузке изображения подставляются вычисленными значениями.

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
  attributions: { who: string; kind?: string; stance: string; place: string | null }[];
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

// Форма узла по семье сущности: люди — круг, понятия — квадрат, учения — ромб,
// произведения — прямоугольник, история — кольцо. Цвет — токен семьи (классы graph-family-*).
function Shape({ node, x, y }: { node: GNode; x: number; y: number }) {
  const family = familyOf(node.type) ?? "ideas";
  const className = `graph-shape graph-family-${family}`;
  if (family === "people") return <circle className={className} cx={x} cy={y} r={20} />;
  if (family === "ideas") return <rect className={className} x={x - 18} y={y - 18} width={36} height={36} rx={6} />;
  if (family === "texts") return <rect className={className} x={x - 14} y={y - 20} width={28} height={40} rx={4} />;
  if (family === "history")
    return <circle className={`${className} graph-shape--ring`} cx={x} cy={y} r={17} strokeWidth={6} />;
  return <polygon className={className} points={`${x},${y - 22} ${x + 22},${y} ${x},${y + 22} ${x - 22},${y}`} />;
}

// Копия SVG для выгрузки: цвета из CSS-переменных подставляются значениями, чтобы файл
// выглядел так же вне сайта.
function standalone(svg: SVGSVGElement): string {
  const copy = svg.cloneNode(true) as SVGSVGElement;
  const source = svg.querySelectorAll<SVGElement>("*");
  const target = copy.querySelectorAll<SVGElement>("*");
  source.forEach((el, i) => {
    const style = window.getComputedStyle(el);
    const out = target[i];
    ["fill", "stroke", "color", "font-family", "font-size", "font-weight"].forEach((prop) => {
      const value = style.getPropertyValue(prop);
      if (value) out.style.setProperty(prop, value);
    });
  });
  copy.removeAttribute("class");
  return new XMLSerializer().serializeToString(copy);
}

const STROKE_CLASS: Record<string, string> = {
  verified: "graph-stroke-verified",
  sourced: "graph-stroke-sourced",
  generated: "graph-stroke-generated",
};

export function GraphPage({ entityId, query }: { entityId: string; query: URLSearchParams }) {
  const t = useT();
  const scope = useScope();
  const textbook = storage.currentSource();
  const [recipe, setRecipe] = useState(query.get("recipe") ?? "genesis");
  const [depth, setDepth] = useState<number | null>(query.get("depth") ? Number(query.get("depth")) : null);
  const [state, setState] = useState<State | null>(null);
  const [problem, setProblem] = useState<{ kind?: string; message?: string; suggestions: Recipe[] } | null>(null);
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
      setProblem({ kind: body.kind ?? "failed", message: body.error, suggestions: body.suggestions ?? [] });
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
    load(entityId, depth, false).catch(() => setProblem({ kind: "service_down", suggestions: [] }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityId, recipe, depth, onlyTextbook, scope.generation]);

  const visible = useMemo(() => {
    if (!state) return { nodes: [] as GNode[], edges: [] as GEdge[] };
    const edges = notInTextbook ? state.edges.filter((e) => e.in_textbook === false) : state.edges;
    const used = new Set([entityId, ...edges.flatMap((e) => [e.subject, e.object])]);
    return { nodes: Object.values(state.nodes).filter((n) => used.has(n.id)), edges };
  }, [state, notInTextbook, entityId]);
  const positions = useMemo(() => layout(visible.nodes, state?.order ?? null), [visible, state?.order]);
  // Ширина холста с запасом под подпись узла: длинное название не обрезается краем.
  const width = Math.max(
    480,
    ...visible.nodes.map((n) => (positions[n.id]?.x ?? 0) + Math.max(110, n.label.length * 4 + 24)),
  );
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
        stroke: STROKE_CLASS[e.status] ?? "graph-stroke-sourced",
        // У ребра графа направление всегда «субъект → объект»: прямая подпись связи.
        name: `${label(e.subject)} — ${relationTitle(t, e.type, false, e.title)} — ${label(e.object)}`,
      },
    ];
  });
  const edge = state?.edges.find((e) => e.id === selected.edge);
  const node = selected.node ? state?.nodes[selected.node] : undefined;
  const start = state?.nodes[entityId];
  const currentRecipe = recipeTitle(t, recipe, state?.recipes.find((r) => r.code === recipe)?.title);
  const notice = state?.notice ? (pick(t.graph.notices, state.extension) ?? state.notice) : null;

  function download() {
    if (!svg.current) return;
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([standalone(svg.current)], { type: "image/svg+xml" }));
    link.download = `graph-${recipe}.svg`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  return (
    <main className="page graph-page">
      <header className="page-header graph-header">
        <h1 className="page-title">{start ? t.graph.heading(currentRecipe, start.label) : t.graph.title}</h1>
      </header>
      <div className="graph-controls">
        <div className="pg-field graph-recipe">
          <label className="pg-field__label" htmlFor="graph-recipe">
            {t.graph.recipe}
          </label>
          <div className="pg-field__control select">
            <select
              id="graph-recipe"
              className="pg-input"
              value={recipe}
              onChange={(e) => (setDepth(null), setRecipe(e.target.value))}
            >
              {(state?.recipes ?? [{ code: recipe, title: recipe, depth: 1 }]).map((r) => (
                <option key={r.code} value={r.code}>
                  {recipeTitle(t, r.code, r.title)}
                </option>
              ))}
            </select>
            <Icon name="chevronDown" small className="select__chevron" />
          </div>
        </div>
        {state && (
          <div className="graph-depth">
            <span className="graph-depth__label">{t.graph.depth(state.depth, state.maxDepth)}</span>
            <button
              className="pg-btn pg-btn--secondary pg-btn--sm"
              disabled={state.depth <= 1}
              onClick={() => setDepth(state.depth - 1)}
            >
              <Icon name="minus" small />
              {t.graph.shallower}
            </button>
            <button
              className="pg-btn pg-btn--secondary pg-btn--sm"
              disabled={state.depth >= state.maxDepth}
              onClick={() => setDepth(state.depth + 1)}
            >
              <Icon name="plus" small />
              {t.graph.deeper}
            </button>
          </div>
        )}
        <div className="graph-switches">
          <ScopeToggle textbook={textbook} />
          <Switch label={t.graph.extend} checked={scope.generation} onChange={(value) => setScope({ generation: value })} />
          <Switch
            label={t.scope.notInTextbook}
            checked={notInTextbook}
            disabled={!textbook || onlyTextbook}
            onChange={setNotInTextbook}
          />
        </div>
        <button className="pg-btn pg-btn--ghost pg-btn--sm graph-download" onClick={download} disabled={!state}>
          <Icon name="download" small />
          {t.graph.download}
        </button>
      </div>
      {problem && (
        <div className="graph-problem pg-notice pg-notice--danger" role="alert">
          <Icon name="warning" />
          <div>
            {problem.kind === "service_down"
              ? t.graph.serviceDown
              : problem.kind === "failed"
                ? t.graph.failed
                : errorText(t, problem.kind, problem.message)}
            {problem.suggestions.length > 0 && (
              <div className="actions">
                {problem.suggestions.map((r) => (
                  <button key={r.code} className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => setRecipe(r.code)}>
                    {recipeTitle(t, r.code, r.title)}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
      {notice && (
        <div className="notice pg-notice" role="status">
          <Icon name="info" />
          <div>{notice}</div>
          {state?.extension === "scope" && (
            <button className="pg-btn pg-btn--ghost pg-btn--sm" onClick={() => setScope({ onlyTextbook: false })}>
              {t.graph.showAll}
            </button>
          )}
        </div>
      )}
      {state?.truncated && (
        <div className="notice pg-notice">
          <Icon name="info" />
          <div>{t.graph.truncated}</div>
        </div>
      )}
      {state && state.extension === "pending" && !state.done && <p className="loading muted">{t.graph.extending}</p>}
      {state?.done && visible.edges.length === 0 && (
        <div className="graph-empty">
          <p>{t.graph.empty}</p>
          <div className="actions">
            {state.extension === "disabled" && (
              <button className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => setScope({ generation: true })}>
                {t.graph.enableExtension}
              </button>
            )}
            {state.recipes
              .filter((r) => r.code !== recipe)
              .map((r) => (
                <button key={r.code} className="pg-btn pg-btn--ghost pg-btn--sm" onClick={() => setRecipe(r.code)}>
                  {t.graph.tryRecipe(recipeTitle(t, r.code, r.title))}
                </button>
              ))}
          </div>
        </div>
      )}
      <div className="graph-layout">
        {state && visible.edges.length > 0 && (
          <div className="graph-canvas">
            <svg
              ref={svg}
              xmlns="http://www.w3.org/2000/svg"
              className="graph"
              width={width}
              height={height + 30}
              viewBox={`0 0 ${width} ${height + 30}`}
              role="img"
              aria-label={t.graph.image}
            >
              <defs>
                <marker id="arrow" viewBox="0 0 10 10" refX="30" refY="5" markerWidth="7" markerHeight="7" orient="auto">
                  <path className="graph-arrow" d="M0,0 L10,5 L0,10 z" />
                </marker>
              </defs>
              <rect className="graph-paper" width="100%" height="100%" />
              {/* Линии — только рисунок; нажимаются ручки в верхнем слое. */}
              {curves.map(({ e, d, stroke }) => (
                <path
                  key={e.id}
                  className={`graph-line ${stroke}`}
                  data-generated={e.generated ? "true" : "false"}
                  d={d}
                  fill="none"
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
                    className={n.id === selected.node ? "graph-node is-selected" : "graph-node"}
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
                    <text className="graph-label" x={p.x} y={p.y + 40} textAnchor="middle">
                      {n.label}
                    </text>
                    {n.dates && (
                      <text className="graph-dates" x={p.x} y={p.y + 55} textAnchor="middle">
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
                  className={`graph-edge ${stroke}`}
                  data-edge={e.id}
                  data-status={e.status}
                  data-generated={e.generated ? "true" : "false"}
                  role="button"
                  aria-label={name}
                  tabIndex={0}
                  onClick={() => setSelected({ edge: e.id })}
                  onKeyDown={(k) => k.key === "Enter" && setSelected({ edge: e.id })}
                >
                  <circle className="graph-handle" cx={mid.x} cy={mid.y} r={9} />
                  <text className="graph-handle__mark" x={mid.x} y={mid.y + 4} fontSize="11" textAnchor="middle">
                    {e.generated ? "◇" : "•"}
                    <title>{e.generated ? t.graph.generatedEdge(name) : name}</title>
                  </text>
                </g>
              ))}
              <text className="graph-legend" x={12} y={height + 18}>
                ◇ {t.graph.legend}
              </text>
            </svg>
          </div>
        )}
        {edge && (
          <aside className="graph-details" role="region" aria-label={t.graph.edge}>
            <h2 className="section-title">
              {label(edge.subject)} — {relationTitle(t, edge.type, false, edge.title)} — {label(edge.object)}
            </h2>
            <p className="graph-details__status">
              <span className="muted">{t.graph.statusLabel}:</span>{" "}
              {edge.status === "verified" || edge.status === "sourced" || edge.status === "generated" ? (
                <StatusMark status={edge.status} />
              ) : (
                (pick(t.status, edge.status) ?? edge.status)
              )}
              {edge.consensus === "disputed" && <StatusMark status="disputed" />}
              {edge.in_textbook === true && <span className="badge">{t.scope.inTextbook}</span>}
              {edge.in_textbook === false && <span className="badge">{t.scope.notInTextbookMark}</span>}
            </p>
            {edge.generated && (
              <p className="pg-desc">
                <Generated className="card-description ungrounded">{t.graph.generatedNote}</Generated>
              </p>
            )}
            {Object.keys(edge.qualifiers).length > 0 && (
              <p className="muted">
                {Object.entries(edge.qualifiers)
                  .map(([k, v]) => `${k}: ${String(v)}`)
                  .join("; ")}
              </p>
            )}
            {edge.attributions.length > 0 && (
              <ul className="graph-who">
                {edge.attributions.map((a, i) => (
                  <li key={i}>
                    {t.card.believes(whoLabel(t, a))} ({pick(t.graph.stance, a.stance) ?? a.stance}
                    {a.place ? `, ${a.place}` : ""})
                  </li>
                ))}
              </ul>
            )}
            {edge.evidence.map((ev, i) => (
              <blockquote key={ev.paragraph_id} className="selection-context">
                «{ev.quote}»
                <a
                  className="citation pg-cite"
                  href={ev.link}
                  title={t.card.evidence(i + 1)}
                  onClick={(x) => {
                    x.preventDefault();
                    navigate(ev.link);
                  }}
                >
                  {i + 1}
                </a>
              </blockquote>
            ))}
          </aside>
        )}
        {node && (
          <aside className="graph-details" role="region" aria-label={t.graph.node}>
            <h2 className="section-title graph-details__name">{node.label}</h2>
            <div className="actions">
              <button
                className="pg-btn pg-btn--secondary pg-btn--sm"
                onClick={(e) => setCard({ id: node.id, x: e.pageX, y: e.pageY + 12 })}
              >
                <Icon name="expand" small />
                {t.graph.openCard}
              </button>
              <button className="pg-btn pg-btn--ghost pg-btn--sm" onClick={() => load(node.id, 1, true)}>
                <Icon name="graph" small />
                {t.graph.expand}
              </button>
            </div>
          </aside>
        )}
      </div>
      {card && <CardPopup entityId={card.id} x={card.x} y={card.y} onClose={() => setCard(null)} />}
    </main>
  );
}
