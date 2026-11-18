import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { openCardInPanel } from "../FullCard";
import { useT } from "../i18n";
import { ScopeToggle, setScope, useScope } from "../scope";
import { storage, useStored } from "../storage";
import { Icon, Switch } from "../ui";
import { DeskNotes, type DeskQuote, type DeskReading } from "./DeskNotes";
import { DeskScene } from "./DeskScene";
import { downloadSvg } from "./exportSvg";
import { DENSE_MAP } from "./fixture";
import { edgeFromStatement, type GEdge } from "./LinkDetails";
import { MapCanvas } from "./MapCanvas";
import { idleBuild, MapPanel, type BuildState, type LinkView } from "./MapPanel";
import { canvasMeasure, loadMapFonts } from "./measure";
import { find, index, related, visible } from "./model";
import { OVERVIEW_HEIGHT, Overview } from "./Overview";
import { KNOWLEDGE_API, ndjson } from "./stream";
import { parseState, toQuery, type MapData, type MapLink, type MapState } from "./types";

// Страница графа — синхронологическая карта раздела (openspec/changes/synchro-map).
// /graph — карта; /graph/<id> — карта с выбранной сущностью. Состояние (выбор, поиск,
// фильтры, линзы) — в параметрах адреса через replaceState: без записи истории на каждую галочку.
// ?fixture=dense — плотный набор без сервиса (проверка вида и раскладки); ?recipe= — рецепт достройки.

type Load = { status: "loading" | "ok" | "missing" | "error"; data: MapData | null };

// Связи «влияния» между персонами: influenced_by, его подтипы и studied_with (реестр).
const INFLUENCE = new Set([
  "influenced_by",
  "studied_with",
  "borrows",
  "develops",
  "reinterprets",
  "criticizes",
  "defends",
  "synthesizes",
  "written_in_response",
]);

const EMPTY: MapData = { range: [0, 1], truncated: false, limit: 0, people: [], works: [], events: [], eras: [], groups: [], links: [], undated: [] };

const MIN_HEIGHT = 420;
// Под обзорной шкалой: её отступ, нижнее поле листа (desk-sheet-body), рамка и полоска стола
const BOTTOM_GAP = 60;
const READING_MAX = 3;

// Цитата для записки: первая цитата-подтверждение связи влияния выбранной персоны
type QuoteRow = { type?: string; subject?: string; object?: string; evidence?: { quote?: string; lost?: boolean }[] };
function firstQuote(rows: QuoteRow[], sel: string): { quote: string; subject: string; object: string } | null {
  for (const r of rows) {
    if (!r.type || !INFLUENCE.has(r.type) || (r.subject !== sel && r.object !== sel)) continue;
    const ev = (r.evidence ?? []).find((e) => !e.lost && e.quote && e.quote.trim());
    if (ev) return { quote: ev.quote!.trim(), subject: r.subject!, object: r.object! };
  }
  return null;
}

export function MapPage({ entityId, query }: { entityId?: string; query: URLSearchParams }) {
  const t = useT();
  const scope = useScope();
  const textbook = storage.currentSource();
  const onlyTextbook = scope.onlyTextbook && Boolean(textbook);
  const fixture = query.get("fixture");
  const recipeParam = query.get("recipe");
  const [state, setState] = useState<MapState>(() => {
    const s = parseState(query);
    return entityId ? { ...s, sel: entityId } : s;
  });
  const [load, setLoad] = useState<Load>({ status: "loading", data: null });
  const [extra, setExtra] = useState<MapLink[]>([]);
  const edges = useRef(new Map<string, GEdge>());
  const [link, setLink] = useState<LinkView | null>(null);
  const [build, setBuild] = useState<BuildState>(idleBuild);
  const panelCollapsed = useStored((s) => s.mapPanelCollapsed === true);
  const measure = useMemo(() => canvasMeasure(), []);
  const [fontsVersion, setFontsVersion] = useState(0);
  const chart = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: MIN_HEIGHT });
  const exportRef = useRef<(() => string | null) | null>(null);

  // Переход по ссылке /graph/<id> на уже открытой карте (из карточки) — выбор этой сущности.
  useEffect(() => {
    if (entityId) setState((s) => (s.sel === entityId ? s : { ...s, sel: entityId }));
  }, [entityId]);

  // Данные карты: из сервиса (область — учебник или вся библиотека) или из набора ?fixture=dense.
  useEffect(() => {
    setExtra([]);
    edges.current.clear();
    if (fixture === "dense") {
      setLoad({ status: "ok", data: DENSE_MAP });
      return;
    }
    let live = true;
    setLoad((l) => ({ status: "loading", data: l.data }));
    const params = new URLSearchParams();
    if (textbook) params.set("textbook", textbook);
    if (onlyTextbook) params.set("only_textbook", "true");
    fetch(`${KNOWLEDGE_API}/map${params.toString() ? `?${params}` : ""}`)
      .then(async (r) => {
        if (!live) return;
        if (r.status === 404) return setLoad({ status: "missing", data: null });
        if (!r.ok) return setLoad({ status: "error", data: null });
        setLoad({ status: "ok", data: (await r.json()) as MapData });
      })
      .catch(() => live && setLoad({ status: "error", data: null }));
    return () => {
      live = false;
    };
  }, [fixture, textbook, onlyTextbook]);

  // Шрифты карты: до загрузки ширина подписей меряется по запасному — потом раскладка заново.
  useEffect(() => {
    let live = true;
    loadMapFonts().then(() => {
      if (!live) return;
      measure.clear();
      setFontsVersion((v) => v + 1);
    });
    return () => {
      live = false;
    };
  }, [measure]);

  const data = useMemo<MapData>(() => {
    const base = load.data ?? EMPTY;
    if (!extra.length) return base;
    const known = new Set(base.links.map((l) => l.id));
    return { ...base, links: [...base.links, ...extra.filter((l) => !known.has(l.id))] };
  }, [load.data, extra]);
  const vis = useMemo(() => visible(data, state.filter), [data, state.filter]);
  const rel = useMemo(() => related(data, vis, state.sel), [data, vis, state.sel]);
  const found = state.sel ? find(data, state.sel) : null;
  const selPerson = found?.type === "person" ? found.obj.id : null;

  // Записки на столе: цитата из подтверждений связей выбранной персоны (ответ карты цитат не несёт —
  // берутся утверждения семьи genesis; без сервиса — из рёбер достройки) и её труды «к чтению».
  const [quoteRows, setQuoteRows] = useState<{ id: string; rows: QuoteRow[] } | null>(null);
  useEffect(() => {
    if (!selPerson || fixture) return;
    let live = true;
    fetch(`${KNOWLEDGE_API}/entities/${encodeURIComponent(selPerson)}/statements?family=genesis`)
      .then((r) => (r.ok ? r.json() : []))
      .then((rows: QuoteRow[]) => live && setQuoteRows({ id: selPerson, rows: Array.isArray(rows) ? rows : [] }))
      .catch(() => live && setQuoteRows({ id: selPerson, rows: [] }));
    return () => {
      live = false;
    };
  }, [selPerson, fixture]);
  const deskQuote = useMemo<DeskQuote | null>(() => {
    if (!selPerson) return null;
    const rows: QuoteRow[] = [
      ...(quoteRows?.id === selPerson ? quoteRows.rows : []),
      ...[...edges.current.values()].map((e) => ({ type: e.type, subject: e.subject, object: e.object, evidence: e.evidence })),
      ...(link?.edge ? [{ type: link.edge.type, subject: link.edge.subject, object: link.edge.object, evidence: link.edge.evidence }] : []),
    ];
    const q = firstQuote(rows, selPerson);
    if (!q) return null;
    const people = index(data).people;
    const name = (id: string) => people.get(id)?.short ?? people.get(id)?.label ?? id;
    return { text: t.map.desk.quote(q.quote), source: t.map.desk.quoteSource(name(q.subject), name(q.object)) };
  }, [selPerson, quoteRows, link, data, t, build.added]);
  const deskReading = useMemo<DeskReading[]>(() => {
    if (!selPerson) return [];
    return data.works
      .filter((w) => w.author === selPerson && w.kind === "work")
      .sort((a, b) => b.weight - a.weight || a.year - b.year)
      .slice(0, READING_MAX)
      .sort((a, b) => a.year - b.year)
      .map((w) => ({ title: t.map.desk.quote(w.label), year: w.year }));
  }, [selPerson, data, t]);

  // Адрес: /graph[/<sel>]?параметры; служебные fixture и recipe сохраняются.
  useEffect(() => {
    const q = new URLSearchParams(toQuery({ ...state, sel: null }));
    if (fixture) q.set("fixture", fixture);
    if (recipeParam) q.set("recipe", recipeParam);
    const text = q.toString().replace(/%2C/gi, ",");
    const path = state.sel ? `/graph/${encodeURIComponent(state.sel)}` : "/graph";
    const next = `${path}${text ? `?${text}` : ""}`;
    if (window.location.pathname + window.location.search !== next) window.history.replaceState(window.history.state, "", next);
  }, [state, fixture, recipeParam]);

  // Ширина — по контейнеру карты (сворачивание панели, окно); высота — до низа окна.
  const remeasure = useCallback(() => {
    const el = chart.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const width = Math.round(rect.width);
    const height = Math.max(MIN_HEIGHT, Math.floor(window.innerHeight - (rect.top + window.scrollY) - OVERVIEW_HEIGHT - BOTTOM_GAP));
    setSize((s) => (s.width === width && s.height === height ? s : { width, height }));
  }, []);
  useLayoutEffect(() => {
    remeasure();
  });
  useEffect(() => {
    const el = chart.current;
    if (!el) return;
    const ro = new ResizeObserver(() => remeasure());
    ro.observe(el);
    window.addEventListener("resize", remeasure);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", remeasure);
    };
  }, [remeasure, load.status]);

  const patch = useCallback((p: Partial<MapState>) => setState((s) => ({ ...s, ...p })), []);
  const select = useCallback((id: string | null, resetFilter?: boolean) => {
    setLink(null);
    setBuild(idleBuild());
    setState((s) => ({ ...s, sel: id, ...(resetFilter ? { filter: { ...s.filter, from: undefined, to: undefined, groups: [], roles: [], kinds: [], ekinds: [] } } : {}) }));
  }, []);

  // Esc снимает выбор связи, затем выбор сущности.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if ((e.target as HTMLElement).closest?.(".side-panel, [role='dialog']")) return;
      if (link) setLink(null);
      else if (state.sel) select(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [link, state.sel, select]);

  // Подробности связи: из потока достройки или из утверждений субъекта (семья genesis).
  const openLink = useCallback(
    (id: string) => {
      const l = data.links.find((x) => x.id === id);
      if (!l) return;
      const known = edges.current.get(id);
      if (known) return setLink({ id, edge: known, status: "ready" });
      const ix = index(data).people;
      // Без сервиса (набор ?fixture) — то, что есть в ответе карты: тип и статус, без атрибуций.
      const fallback: GEdge = {
        id,
        subject: l.subject,
        object: l.object,
        type: l.type,
        title: l.type,
        status: l.status,
        generated: l.generated,
        consensus: "",
        qualifiers: {},
        attributions: [],
        evidence: [],
        in_textbook: l.in_textbook,
      };
      if (fixture) return setLink({ id, edge: fallback, status: "ready" });
      setLink({ id, edge: null, status: "loading" });
      fetch(`${KNOWLEDGE_API}/entities/${encodeURIComponent(l.subject)}/statements?family=genesis`)
        .then((r) => (r.ok ? r.json() : []))
        .then((rows: Record<string, unknown>[]) => {
          const raw = rows.find((r) => r.id === id);
          const edge = raw ? { ...edgeFromStatement(raw, (x) => ix.get(x)?.label), in_textbook: l.in_textbook } : fallback;
          setLink((cur) => (cur?.id === id ? { id, edge, status: "ready" } : cur));
        })
        .catch(() => setLink((cur) => (cur?.id === id ? { id, edge: fallback, status: "ready" } : cur)));
    },
    [data, fixture],
  );

  // «Достроить связи»: прежний поток /graph/build по рецепту, подходящему типу выбранного.
  // Рёбра между персонами карты добавляются к связям; достроенные моделью — пунктиром.
  const runBuild = useCallback(
    async (override?: string) => {
      if (!found) return;
      const recipe =
        override ??
        recipeParam ??
        (found.type === "person" || (found.type === "work" && found.obj.kind !== "work") ? "genesis" : "context");
      const people = index(data).people;
      const add = (list: GEdge[]) => {
        const fresh = list.filter((e) => INFLUENCE.has(e.type) && people.has(e.subject) && people.has(e.object) && e.subject !== e.object);
        if (!fresh.length) return;
        fresh.forEach((e) => edges.current.set(e.id, e));
        setExtra((old) => {
          const have = new Set([...data.links.map((l) => l.id), ...old.map((l) => l.id)]);
          const next = fresh
            .filter((e) => !have.has(e.id))
            .map((e) => ({
              id: e.id,
              subject: e.subject,
              object: e.object,
              type: e.type,
              status: (e.status === "verified" || e.status === "sourced" ? e.status : "generated") as MapLink["status"],
              generated: e.generated,
              in_textbook: e.in_textbook,
            }));
          if (next.length) setBuild((b) => ({ ...b, added: b.added + next.length }));
          return next.length ? [...old, ...next] : old;
        });
      };
      setBuild({ ...idleBuild(), running: true });
      try {
        const response = await fetch(`${KNOWLEDGE_API}/graph/build`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            entity_id: found.obj.id,
            recipe,
            depth: null,
            textbook: textbook ?? null,
            only_textbook: onlyTextbook,
            generation: scope.generation,
          }),
        });
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          setBuild((b) => ({
            ...b,
            running: false,
            problem: { kind: body.kind ?? "failed", message: body.error, suggestions: body.suggestions ?? [] },
          }));
          return;
        }
        for await (const event of ndjson(response)) {
          if (event.type === "graph") {
            add((event.edges as GEdge[]) ?? []);
            const notice = (event.notice as string | null) ?? null;
            setBuild((b) => ({ ...b, extension: (event.extension as string) ?? null, notice }));
          } else if (event.type === "edge") {
            add([event.edge as GEdge]);
          } else if (event.type === "notice") {
            setBuild((b) => ({ ...b, extension: event.extension as string, notice: event.message as string }));
          } else if (event.type === "done") {
            setBuild((b) => ({ ...b, running: false }));
          }
        }
        setBuild((b) => ({ ...b, running: false }));
      } catch {
        setBuild((b) => ({ ...b, running: false, problem: { kind: "service_down", suggestions: [] } }));
      }
    },
    [found, recipeParam, data, textbook, onlyTextbook, scope.generation],
  );

  function download() {
    const text = exportRef.current?.();
    if (text) downloadSvg(text, `map${state.sel ? `-${state.sel}` : ""}.svg`);
  }

  const empty =
    load.status === "missing" ||
    (load.status === "ok" && (!data.range || (!data.people.length && !data.works.length && !data.events.length && !data.eras.length)));
  const title = found ? found.obj.label : t.map.title;
  const ready = load.status === "ok" && !empty;

  return (
    <main className="page map-page">
      <DeskScene
        notes={<DeskNotes quote={deskQuote} reading={deskReading} readingTitle={t.map.desk.reading} label={t.map.desk.notes} />}
      >
        <div className="map-sheet">
          <header className="map-head">
            <div className="map-head__main">
              <div className="map-head__eyebrow">{t.map.eyebrow}</div>
              <h1 className="map-head__title">{title}</h1>
            </div>
            <div className="map-head__tools">
              <ScopeToggle textbook={textbook} />
              <Switch label={t.graph.extend} checked={scope.generation} onChange={(value) => setScope({ generation: value })} />
              <button type="button" className="pg-btn pg-btn--ghost pg-btn--sm" onClick={download} disabled={!ready}>
                <Icon name="download" small />
                {t.graph.download}
              </button>
            </div>
          </header>
          {load.status === "error" && (
            <div className="pg-notice pg-notice--danger map-notice" role="alert">
              <Icon name="warning" />
              <div>{t.graph.serviceDown}</div>
            </div>
          )}
          {ready && data.truncated && (
            <div className="pg-notice map-notice" role="status">
              <Icon name="info" />
              <div>{t.map.truncated(data.limit)}</div>
            </div>
          )}
          {ready && state.sel && !found && (
            <div className="pg-notice map-notice" role="status">
              <Icon name="info" />
              <div>{t.map.notOnMap}</div>
              <button type="button" className="pg-btn pg-btn--ghost pg-btn--sm" onClick={() => openCardInPanel(state.sel!, state.sel!)}>
                {t.graph.openCard}
              </button>
            </div>
          )}
          {load.status === "loading" && !load.data && <p className="loading muted">{t.app.loading}</p>}
          {empty && (
            <div className="map-empty">
              <p>{t.map.empty}</p>
              <p className="muted">{t.map.emptyHint}</p>
            </div>
          )}
          {ready && (
            <div className={panelCollapsed ? "map-workspace is-panel-collapsed" : "map-workspace"}>
              <div className="map-chart" ref={chart}>
                {size.width > 0 && (
                  <>
                    <MapCanvas
                      data={data}
                      vis={vis}
                      rel={rel}
                      sel={state.sel}
                      collapsed={state.collapsed}
                      width={size.width}
                      height={size.height}
                      measure={measure}
                      fontsVersion={fontsVersion}
                      linkSel={link?.id ?? null}
                      onSelect={select}
                      onLink={openLink}
                      onLens={(collapsed) => patch({ collapsed })}
                      exportRef={exportRef}
                    />
                    <Overview
                      range={data.range ?? vis.range}
                      win={vis.range}
                      people={data.people}
                      width={size.width}
                      onChange={(from, to) => setState((s) => ({ ...s, filter: { ...s.filter, from, to } }))}
                    />
                  </>
                )}
              </div>
              <MapPanel
                data={data}
                vis={vis}
                rel={rel}
                state={state}
                collapsed={panelCollapsed}
                onCollapse={(c) => storage.setMapPanelCollapsed(c)}
                onState={patch}
                onSelect={select}
                link={link}
                onCloseLink={() => setLink(null)}
                build={build}
                onBuild={runBuild}
                generation={scope.generation}
                onEnableGeneration={() => setScope({ generation: true })}
                onOpenCard={(id, label) => openCardInPanel(id, label)}
              />
            </div>
          )}
        </div>
      </DeskScene>
    </main>
  );
}
