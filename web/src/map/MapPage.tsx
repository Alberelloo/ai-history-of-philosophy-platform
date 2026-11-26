import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { openCardInPanel } from "../FullCard";
import { useT } from "../i18n";
import { ScopeToggle, setScope, useScope } from "../scope";
import { storage, useStored } from "../storage";
import { Icon, Seg, Switch } from "../ui";
import { DeskScene } from "./DeskScene";
import { downloadSvg } from "./exportSvg";
import { DENSE_MAP } from "./fixture";
import type { GEdge } from "./LinkDetails";
import { MapCanvas } from "./MapCanvas";
import { idleBuild, MapPanel, type BuildState, type LinkView } from "./MapPanel";
import { canvasMeasure, loadMapFonts } from "./measure";
import { loadGlobeFonts } from "./geo/fonts";
import { eraOf, find, index, related, visible } from "./model";
import { OVERVIEW_HEIGHT, Overview, YEAR_BAR_HEIGHT } from "./Overview";
import { KNOWLEDGE_API, ndjson } from "./stream";
import { emptyFilter, parseState, toQuery, type MapData, type MapLink, type MapState, type MapView } from "./types";
import { fetchPlaces, type GeoLayer } from "./geo/api";
import type { GeoPanel, GeoRole, GeoWhereData } from "./geo/GeoList";
import type { GlobeInfo } from "./geo/GlobeView";
import { SPEEDS, useAnnouncer, usePlayback, useReducedMotion, type Speed } from "./geo/playback";
import { globeRoles } from "./geo/selection";
import { clampYear, defaultYear, geoModel, MAX_PERSONS, nearestYear, stayAt, visibleAt } from "./geo/timeline";

// Глобус — ленивый фрагмент (d3-geo, суша Natural Earth): хронология его не грузит.
const GlobeView = lazy(() => import("./geo/GlobeView"));

// Страница графа — синхронологическая карта раздела (openspec/changes/archive/2026-11-18-synchro-map).
// /graph — карта; /graph/<id> — карта с выбранной сущностью. Состояние (выбор, поиск,
// фильтры, линзы) — в параметрах адреса через replaceState: без записи истории на каждую галочку.
// ?fixture=dense — плотный набор без сервиса (проверка вида и раскладки); ?recipe= — рецепт достройки.
// ?via=assistant — вид подобран ассистентом: пометка с перечнем применённого и «Сбросить вид»;
// уходит при ручной смене фильтров и линз.

type Load = { status: "loading" | "ok" | "missing" | "error"; data: MapData | null };
type GeoState = { status: "loading" | "ok" | "error"; data: GeoLayer | null };
// Широкое окно для сцены глобуса: персона видна и после конца окна времени (бледнея),
// поэтому люди, события и связи берутся по прочим фильтрам, а год зажат в окно.
const ALL_TIME = { from: -1e9, to: 1e9 };

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

// Нижний предел высоты карты: в окне 1024×576 карта и панель помещаются без прокрутки страницы.
const MIN_HEIGHT = 300;
// Глобус под шапкой в две строки (1024×576) с рядом года: круг уже мельче, без прокрутки.
const MIN_GLOBE = 220;
// Под обзорной шкалой: её отступ, нижнее поле листа (desk-sheet-body), рамка и полоска стола
const BOTTOM_GAP = 60;

export function MapPage({ entityId, query }: { entityId?: string; query: URLSearchParams }) {
  const t = useT();
  const scope = useScope();
  const textbook = storage.currentSource();
  const onlyTextbook = scope.onlyTextbook && Boolean(textbook);
  const fixture = query.get("fixture");
  const recipeParam = query.get("recipe");
  const [fromAssistant, setFromAssistant] = useState(query.get("via") === "assistant");
  const [state, setState] = useState<MapState>(() => {
    // Ссылка ассистента поиска не несёт: дописанный в неё текст в поле поиска не показываем.
    const s = { ...parseState(query), ...(query.get("via") === "assistant" ? { q: "" } : {}) };
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
  const widths = useRef<number[]>([]);
  const exportRef = useRef<(() => string | null) | null>(null);
  const globe = state.view === "globe";
  const globeRef = useRef(globe);
  globeRef.current = globe;
  const [geo, setGeo] = useState<GeoState>({ status: "loading", data: null });
  const [geoRetry, setGeoRetry] = useState(0);
  const geoDone = useRef<string | null>(null);
  const [focus, setFocus] = useState<{ lat: number; lon: number; nonce: number } | null>(null);
  // Страна места — ленивый модуль (словарь стран не в основном бандле): грузится с видом «Глобус».
  const [countryOf, setCountryOf] = useState<((p: { id: string; lat: number; lon: number }) => { name: string } | null) | null>(null);
  const reduced = useReducedMotion();

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

  // Слой мест — только в виде «Глобус» и один раз на область (учебник, «только учебник»):
  // обратное переключение и повторный вход его не перезапрашивают. Ошибка — состояние вида.
  useEffect(() => {
    if (!globe) return;
    const want = `${fixture ?? ""}|${textbook ?? ""}|${onlyTextbook}|${geoRetry}`;
    if (geoDone.current === want) return;
    const ctl = new AbortController();
    setGeo({ status: "loading", data: null });
    import("./geo/countries").then(
      (m) => setCountryOf(() => m.countryOf),
      () => undefined,
    );
    const got: Promise<GeoLayer | null> =
      fixture === "dense"
        ? import("./geo/geoFixture").then((m) => m.DENSE_GEO, () => null)
        : fetchPlaces(textbook ?? null, onlyTextbook, ctl.signal);
    got.then((layer) => {
      if (ctl.signal.aborted) return;
      if (layer) geoDone.current = want;
      setGeo(layer ? { status: "ok", data: layer } : { status: "error", data: null });
    });
    return () => ctl.abort();
  }, [globe, fixture, textbook, onlyTextbook, geoRetry]);

  // Шрифты карты: до загрузки ширина подписей меряется по запасному — потом раскладка заново.
  useEffect(() => {
    let live = true;
    Promise.all([loadMapFonts(), loadGlobeFonts()]).then(() => {
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
  // Эпохи фильтра, которых нет на карте (неизвестные и без датировки), отбрасываются —
  // адрес заменяется без них.
  useEffect(() => {
    if (load.status !== "ok" || !load.data) return;
    const eras = new Set(load.data.eras.map((e) => e.id));
    setState((s) => {
      const kept = s.filter.epochs.filter((id) => eras.has(id));
      return kept.length === s.filter.epochs.length ? s : { ...s, filter: { ...s.filter, epochs: kept } };
    });
  }, [load]);
  const vis = useMemo(() => visible(data, state.filter), [data, state.filter]);
  const rel = useMemo(
    () => related(data, vis, state.sel, state.filter.verified),
    [data, vis, state.sel, state.filter.verified],
  );
  const found = state.sel ? find(data, state.sel) : null;

  // --- глобус: сцена на год T ---
  const gvis = useMemo(() => (globe ? visible(data, { ...state.filter, ...ALL_TIME }) : null), [globe, data, state.filter]);
  const grel = useMemo(
    () => (gvis ? related(data, gvis, state.sel, state.filter.verified) : null),
    [data, gvis, state.sel, state.filter.verified],
  );
  const win = vis.range;
  const selPerson = found?.type === "person" ? found.obj : null;
  const year = clampYear(state.t ?? defaultYear(gvis?.people ?? vis.people, selPerson, win), win);
  const winRef = useRef(win);
  winRef.current = win;
  const setYear = useCallback((y: number) => setState((s) => ({ ...s, t: clampYear(y, winRef.current) })), []);
  const playback = usePlayback(win, year, setYear, reduced);
  const model = geo.status === "ok" && geo.data ? geoModel(geo.data) : null;
  const input = useMemo(() => (gvis ? { people: gvis.people, events: gvis.events, links: gvis.links } : null), [gvis]);
  const scene = useMemo(() => (model && input ? visibleAt(model, input, year) : null), [model, input, year]);
  const placeSel = model && state.sel ? (model.places.get(state.sel) ?? null) : null;
  const roles = useMemo(() => globeRoles(model, scene, placeSel ? null : grel, placeSel?.id ?? null), [model, scene, grel, placeSel]);
  const nearest = model && input && scene && !scene.places.length ? nearestYear(model, input, year, win) : null;
  const peopleNow = scene ? scene.places.reduce((n, p) => n + p.people.length, 0) : 0;
  const placesNow = scene?.places.length ?? 0;
  const said = useAnnouncer(t.geo.announce(year, placesNow, peopleNow), year, playback.playing, scene != null);
  const info = useMemo(() => {
    const ix = new Map<string, GlobeInfo>();
    for (const p of data.people) ix.set(p.id, { name: p.short || p.label, full: p.label, portrait: p.portrait ?? null });
    for (const e of data.events) ix.set(e.id, { name: e.label, full: e.label });
    return (id: string) => ix.get(id) ?? null;
  }, [data]);
  const country = useCallback(
    (placeId: string) => {
      const g = model?.places.get(placeId);
      return g && countryOf ? (countryOf(g)?.name ?? null) : null;
    },
    [model, countryOf],
  );
  // «Где в <год> году»: место выбранной персоны или события в сцене года T.
  let where: GeoWhereData | null = null;
  if (model && scene && found?.type === "person") {
    const sp = scene.persons.find((p) => p.id === found.obj.id);
    const stay = sp ? stayAt(found.obj, model.byEntity.get(found.obj.id) ?? [], year) : null;
    const g = sp ? model.places.get(sp.place) : null;
    if (sp && stay && g) {
      const role: GeoRole = stay.row.role == null ? "none" : stay.row.role;
      where = { year, place: g.label, country: countryOf ? country(g.id) : undefined, role, from: stay.from, to: stay.to, after: stay.after };
    }
  } else if (model && scene && found?.type === "event") {
    const se = scene.events.find((e) => e.id === found.obj.id);
    const g = se ? model.places.get(se.place) : null;
    if (se && g) where = { year, place: g.label, country: countryOf ? country(g.id) : undefined, role: "event", from: found.obj.year, to: found.obj.year, after: false };
  }
  const geoPanel: GeoPanel | undefined = globe
    ? {
        year,
        status: geo.status,
        scene,
        unplaced: model && gvis ? model.unplaced.filter((id) => gvis.people.some((p) => p.id === id) || gvis.events.some((e) => e.id === id)) : [],
        place: placeSel,
        noPlace: Boolean(model && found && found.type !== "era" && found.type !== "group" && !model.byEntity.has(found.obj.id)),
        country: countryOf ? country : null,
        where,
        maxPersons: MAX_PERSONS,
        onPlace: (id) => {
          const g = model?.places.get(id);
          if (!g) return;
          select(id);
          setFocus((f) => ({ lat: g.lat, lon: g.lon, nonce: (f?.nonce ?? 0) + 1 }));
        },
      }
    : undefined;

  // Адрес: /graph[/<sel>]?параметры; служебные fixture и recipe сохраняются. Во время
  // проигрывания год в адрес не пишется на каждом шаге — только по остановке.
  useEffect(() => {
    if (playback.playing) return;
    const q = new URLSearchParams(toQuery({ ...state, sel: null }));
    if (fromAssistant) q.set("via", "assistant");
    if (fixture) q.set("fixture", fixture);
    if (recipeParam) q.set("recipe", recipeParam);
    const text = q.toString().replace(/%2C/gi, ",");
    const path = state.sel ? `/graph/${encodeURIComponent(state.sel)}` : "/graph";
    const next = `${path}${text ? `?${text}` : ""}`;
    if (window.location.pathname + window.location.search !== next) window.history.replaceState(window.history.state, "", next);
  }, [state, fixture, recipeParam, fromAssistant, playback.playing]);

  // Ширина — по контейнеру карты (сворачивание панели, окно); высота — до низа окна.
  const remeasure = useCallback(() => {
    const el = chart.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const width = Math.round(rect.width);
    const height = Math.max(globeRef.current ? MIN_GLOBE : MIN_HEIGHT, Math.floor(window.innerHeight - (rect.top + window.scrollY) - OVERVIEW_HEIGHT - (globeRef.current ? YEAR_BAR_HEIGHT : 0) - BOTTOM_GAP));
    // Защита от качелей: ширина карты меняет высоту страницы, высота — полосу прокрутки,
    // полоса — снова ширину. Возврат к ширине позапрошлого замера не принимаем.
    const prev = widths.current;
    if (prev.length === 2 && width === prev[0] && width !== prev[1]) return;
    setSize((s) => {
      if (s.width === width && s.height === height) return s;
      if (s.width !== width) widths.current = [s.width, width];
      return { width, height };
    });
  }, []);
  useLayoutEffect(() => {
    remeasure();
  }, [remeasure, load.status, panelCollapsed, state.view]);
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
  }, [remeasure, load.status, state.view]);

  // Ручная смена фильтров или линз снимает пометку ассистента: вид уже не его.
  const patch = useCallback((p: Partial<MapState>) => {
    if (p.filter || p.collapsed) setFromAssistant(false);
    setState((s) => ({ ...s, ...p }));
  }, []);
  const resetView = useCallback(() => {
    setFromAssistant(false);
    setState((s) => ({ ...s, filter: emptyFilter(), collapsed: [] }));
  }, []);
  const select = useCallback((id: string | null, resetFilter?: boolean) => {
    setLink(null);
    setBuild(idleBuild());
    if (resetFilter) setFromAssistant(false);
    setState((s) => ({ ...s, sel: id, ...(resetFilter ? { filter: { ...s.filter, from: undefined, to: undefined, groups: [], roles: [], kinds: [], ekinds: [], epochs: [] } } : {}) }));
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
      // Связь в виде ребра графа: подписи атрибуций и закрытые по региону источники — на сервере.
      const q = textbook ? `?textbook=${encodeURIComponent(textbook)}` : "";
      fetch(`${KNOWLEDGE_API}/graph/edges/${encodeURIComponent(id)}${q}`)
        .then((r) => (r.ok ? (r.json() as Promise<GEdge>) : null))
        .then((got) => {
          const edge = got ?? fallback;
          setLink((cur) => (cur?.id === id ? { id, edge, status: "ready" } : cur));
        })
        .catch(() => setLink((cur) => (cur?.id === id ? { id, edge: fallback, status: "ready" } : cur)));
    },
    [data, fixture, textbook],
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

  // Смена вида: выбор, поиск, фильтры и окно остаются; проигрывание останавливается.
  function switchView(v: MapView) {
    playback.stop();
    setState((s) => (s.view === v ? s : { ...s, view: v }));
  }

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
      <DeskScene>
        <div className="map-sheet">
          <header className="map-head">
            <div className="map-head__main">
              <div className="map-head__eyebrow">{t.map.eyebrow}</div>
              <div className="map-head__titlerow">
                <h1 className="map-head__title">{title}</h1>
                <Seg<MapView>
                  className="map-view-switch"
                  label={t.geo.viewLabel}
                  items={[
                    { value: "chrono", label: t.geo.viewChrono, icon: "timeline", iconOnly: true },
                    { value: "globe", label: t.geo.viewGlobe, icon: "globe", iconOnly: true },
                  ]}
                  value={state.view}
                  onChange={switchView}
                />
              </div>
            </div>
            <div className="map-head__tools">
              <ScopeToggle textbook={textbook} />
              <Switch label={t.graph.extend} checked={scope.generation} onChange={(value) => setScope({ generation: value })} />
              {!globe && (
                <button type="button" className="pg-btn pg-btn--ghost pg-btn--sm" onClick={download} disabled={!ready}>
                  <Icon name="download" small />
                  {t.graph.download}
                </button>
              )}
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
          {ready && state.sel && !found && !placeSel && !(globe && geo.status === "loading") && (
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
                {size.width > 0 && globe && (
                  <>
                    <Suspense fallback={<div className="geo-stage" style={{ width: size.width, height: size.height }} aria-busy="true" />}>
                      <GlobeView
                        width={size.width}
                        height={size.height}
                        layer={geo.data}
                        status={geo.status}
                        scene={scene}
                        roles={roles}
                        year={year}
                        summary={t.geo.summary(year, placesNow, peopleNow)}
                        measure={measure}
                        fontsVersion={fontsVersion}
                        reduced={reduced}
                        focus={focus}
                        nearest={nearest}
                        info={info}
                        onSelect={(id) => select(id)}
                        onYearStep={(d) => setYear(year + d)}
                        onTogglePlay={playback.toggle}
                        onRetry={() => setGeoRetry((n) => n + 1)}
                        onToChrono={() => switchView("chrono")}
                        onNearest={() => nearest != null && setYear(nearest)}
                      />
                    </Suspense>
                    <Overview
                      range={data.range ?? vis.range}
                      win={vis.range}
                      people={data.people}
                      width={size.width}
                      onChange={(from, to) => {
                        setFromAssistant(false);
                        setState((s) => ({ ...s, filter: { ...s.filter, from, to } }));
                      }}
                      year={{
                        value: year,
                        era: eraOf(data.eras, year)?.label ?? null,
                        playing: playback.playing,
                        speed: playback.speed,
                        speeds: SPEEDS,
                        onChange: setYear,
                        onToggle: playback.toggle,
                        onSpeed: (v) => playback.setSpeed(v as Speed),
                      }}
                    />
                    <p className="geo-live" aria-live="polite" data-geo-live>
                      {said}
                    </p>
                  </>
                )}
                {size.width > 0 && !globe && (
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
                      onChange={(from, to) => {
                        setFromAssistant(false);
                        setState((s) => ({ ...s, filter: { ...s.filter, from, to } }));
                      }}
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
                onResetView={fromAssistant ? resetView : undefined}
                onSelect={select}
                link={link}
                onCloseLink={() => setLink(null)}
                build={build}
                onBuild={runBuild}
                generation={scope.generation}
                onEnableGeneration={() => setScope({ generation: true })}
                onOpenCard={(id, label) => openCardInPanel(id, label)}
                geo={geoPanel}
              />
            </div>
          )}
        </div>
      </DeskScene>
    </main>
  );
}
