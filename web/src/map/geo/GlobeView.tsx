import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import { useT } from "../../i18n";
import { monogram } from "../../ui";
import type { Measure } from "../layout";
import { COUNTRY_FILL_FONT, COUNTRY_FILL_ITALIC_FONT, COUNTRY_FONT, COUNTRY_ITALIC_FONT, NAME_FONT } from "./fonts";
import type { GeoLayer } from "./api";
import { arcBetween } from "./arcs";
import { countryName, countryOf } from "./countries";
import {
  layoutCountries,
  layoutMarkers,
  markerOf,
  MAX_PORTRAITS,
  MEDAL,
  EVENT_MARK,
  frameLayout,
  COUNTRY_MIN_LABELS,
  type CountryInput,
  type CountryLabel,
  type Layout,
  type Frame as LFrame,
  type RestLayout,
  type LPlace,
  type Metrics,
  type PersonSlot,
  type Rect,
  round2,
} from "./layout";
import {
  canvasPath,
  centerAttr,
  centerOn,
  degreesPerPixel,
  fmt,
  GRATICULE,
  homeView,
  initialView,
  interpolateCenter,
  isNear,
  MAX_ZOOM,
  projector,
  rotateBy,
  STEP,
  STEP_SHIFT,
  zoomBy,
  ZOOM_STEP,
  type Frame,
  type View,
} from "./projection";
import type { GlobeRoles } from "./selection";
import { opacity, type Scene, type ScenePlace } from "./timeline";
import { labelInputs, PolityStore, type PolityLayer, type PolityState } from "./polities";
import { BORDERS, COUNTRIES, COUNTRY_COUNT, LAND } from "./world";

// Вид «Глобус» карты раздела (openspec/changes/rework-globe-political-map): ортографическая
// проекция d3-geo. Основа — тень, море, сетка 15°, суша, границы государств и береговая
// линия Natural Earth 1:110m — на canvas 2D; поверх — SVG: объём, путь жизни, дуги влияний
// между маркерами, выноски к местам, медальоны персон, значки «+N» и событий, подписи
// персон и стран, латунный обод. Ленивый фрагмент: грузится только при открытии вида.
//
// Движение — только по действию читателя: перетаскивание (короткая инерция), колесо,
// клавиши, поворот к месту из списка (не дольше FOCUS_MS). При уменьшенном движении повороты
// и приближение — сразу. Кадры — requestAnimationFrame, время — performance.now (без Date).
// Во время движения медальоны держат сдвиги последней раскладки (shiftLayout), подписи
// скрыты; в покое раскладка заново (layoutMarkers, layoutCountries). Маркеры дальнего
// полушария и вышедшие за круг или кадр остаются в DOM с data-hidden="true" и не рисуются.
// SVG-фильтров нет: объём — статический радиальный градиент и обод.

const FOCUS_MS = 600;
const INERTIA_MS = 700;
const DRAG_THRESHOLD = 4; // px: меньше — щелчок
const WHEEL_STEP = 100; // px колеса на шаг приближения
const RIM = 16; // поле под обод и деления вокруг круга глобуса
const COUNTRY_PRECISION = 2; // px: площадь и центр видимой части стран (расхождение с точной < 0,01 %)
// px: то же для образований Cliopatria. У их контуров бывают длинные рёбра с редкими
// вершинами: при 2 px передискретизация даёт ошибку площади до 1,5 %, при 0,2 px — ≤ 0,1 %.
const POLITY_PRECISION = 0.2;
const DRAG_PRECISION = 2.5; // px: точность передискретизации путей во время перетаскивания

export type GlobeInfo = { name: string; full: string; portrait?: string | null };

type Props = {
  width: number;
  height: number;
  layer: GeoLayer | null;
  status: "loading" | "ok" | "error";
  scene: Scene | null;
  roles: GlobeRoles;
  year: number;
  summary: string;
  measure: Measure;
  fontsVersion: number; // шрифты загружены — подписи меряются заново
  reduced: boolean;
  focus: { lat: number; lon: number; nonce: number } | null;
  nearest: number | null;
  info: (id: string) => GlobeInfo | null; // имя, полное имя и портрет персоны, название события
  onSelect: (id: string | null) => void; // персона, событие или место; null — снять выбор
  onYearStep: (delta: number) => void;
  onTogglePlay: () => void;
  onRetry: () => void;
  onToChrono: () => void;
  onNearest: () => void;
};

// Вертикальные метрики шрифта — те же, что у прямоугольника текста в браузере
// (fontBoundingBox*); без canvas — с запасом от кегля.
let metricsCanvas: CanvasRenderingContext2D | null | undefined;
const metricsCache = new Map<string, Metrics>(); // ключ — начертание и версия шрифтов
function fontMetrics(font: string, version: number): Metrics {
  const key = `${version}\u0000${font}`;
  const hit = metricsCache.get(key);
  if (hit) return hit;
  if (metricsCanvas === undefined) metricsCanvas = typeof document !== "undefined" ? document.createElement("canvas").getContext("2d") : null;
  const c = metricsCanvas;
  let m: Metrics = { ascent: 15, descent: 5 };
  if (c) {
    c.font = font;
    const t = c.measureText("Ag");
    if (t.fontBoundingBoxAscent) m = { ascent: t.fontBoundingBoxAscent, descent: t.fontBoundingBoxDescent };
  }
  metricsCache.set(key, m);
  return m;
}

const COUNTRY_FONTS = [COUNTRY_FONT, COUNTRY_FILL_FONT];
const ITALIC_FONTS = [COUNTRY_ITALIC_FONT, COUNTRY_FILL_ITALIC_FONT];
const COUNTRY_INPUT: CountryInput[] = COUNTRIES.filter((c) => c.id && countryName(c.id)).map((c) => ({ id: c.id!, name: countryName(c.id)!, feature: c.feature }));

// Кольца образований слоя (для data-borders: видимые — хотя бы одна вершина ближе 90°).
const ringsCache = new WeakMap<PolityLayer, [number, number][][]>();
function ringsOf(layer: PolityLayer): [number, number][][] {
  let out = ringsCache.get(layer);
  if (!out) {
    out = [];
    for (const p of layer.polities) {
      const polys = p.geometry.type === "Polygon" ? [p.geometry.coordinates] : p.geometry.coordinates;
      for (const poly of polys) for (const ring of poly) out.push(ring as [number, number][]);
    }
    ringsCache.set(layer, out);
  }
  return out;
}

// Слой образований на год глобуса: хранилище живёт столько же, сколько вид «Глобус».
function usePolities(year: number): PolityState {
  const store = useMemo(() => new PolityStore(), []);
  const [state, setState] = useState<PolityState>(store.state);
  useEffect(() => {
    const off = store.subscribe(setState);
    return () => {
      off();
      store.dispose();
    };
  }, [store]);
  useEffect(() => store.request(year), [store, year]);
  return state;
}

// --- раскладка покоя: чистые шаги (кадр, исходный вид) ---
type RestInput = { scene: Scene | null; nameOf: (id: string) => string | null; measure: Measure; fv: number; frame: Frame; width: number; height: number; obstacles: Rect[]; labels: CountryInput[]; labelPrecision: number };

function anchorsAt(projection: (p: [number, number]) => [number, number] | null, view: View, places: ScenePlace[], width: number, height: number): LPlace[] {
  return places.map((p) => {
    const xy = projection([p.lon, p.lat]);
    const x = xy ? xy[0] : 0;
    const y = xy ? xy[1] : 0;
    return { id: p.id, x, y, visible: !!xy && isNear(view, p) && x >= 0 && y >= 0 && x <= width && y <= height };
  });
}

function markersAt(anchors: LPlace[], lf: LFrame, r: RestInput): Layout {
  return layoutMarkers({
    places: anchors,
    persons: (r.scene?.persons ?? []).map((p) => ({ id: p.id, place: p.place, name: r.nameOf(p.id) })),
    events: (r.scene?.events ?? []).map((e) => ({ id: e.id, place: e.place })),
    frame: lf,
    measure: (text) => r.measure(text, NAME_FONT),
    metrics: fontMetrics(NAME_FONT, r.fv),
    obstacles: r.obstacles,
  });
}

function countriesAt(view: View, lf: LFrame, grid: Layout["grid"], r: RestInput): CountryLabel[] {
  const cp = projector(view, r.frame, r.labelPrecision);
  cp.projection.clipExtent([
    [0, 0],
    [r.width, r.height],
  ]);
  const fontsOf = (list: string[]) => list.map((font) => ({ font, measure: (text: string) => r.measure(text, font), metrics: fontMetrics(font, r.fv) }));
  return layoutCountries(r.labels, cp.path, cp.projection, lf, grid, fontsOf(COUNTRY_FONTS), fontsOf(ITALIC_FONTS));
}

// Исходный вид: homeView (все точки привязки в кадре), затем, пока подписей стран меньше
// COUNTRY_MIN_LABELS, — на шаг ряда дальше, до приближения 1 (правило «Исходное приближение»).
function homeFor(places: ScenePlace[], r: RestInput): View {
  let v = homeView(places, r.frame, r.width, r.height, MEDAL);
  while (v.zoom > 1 + 1e-9) {
    const p = projector(v, r.frame);
    const lf: LFrame = { w: r.width, h: r.height, cx: r.frame.cx, cy: r.frame.cy, R: p.scale };
    const lay = markersAt(anchorsAt(p.projection, v, places, r.width, r.height), lf, r);
    if (countriesAt(v, lf, lay.grid, r).length >= COUNTRY_MIN_LABELS) break;
    v = { ...v, zoom: Math.max(1, Math.round((v.zoom / ZOOM_STEP) * 1e6) / 1e6) };
  }
  return v;
}

export default function GlobeView(props: Props) {
  const { width, height, layer, status, scene, roles, measure, reduced } = props;
  const t = useT();
  const svg = useRef<SVGSVGElement>(null);
  const frame: Frame = useMemo(() => {
    const radius = Math.max(40, Math.min(width, height) / 2 - RIM);
    return { cx: width / 2, cy: height / 2, radius };
  }, [width, height]);

  const info = props.info;
  const nameOf = useCallback((id: string) => info(id)?.name || null, [info]); // без имени — без подписи, не id
  // Наложенные на вид элементы ([data-geo-overlay]: подпись источника, «Клавиши» и подсказка
  // к ним, сообщения состояний) — препятствия раскладки. Прямоугольники меряются после
  // отрисовки (шрифты, размер окна, раскрытая подсказка); null — ещё не мерили.
  const stage = useRef<HTMLDivElement>(null);
  const [overlays, setOverlays] = useState<Rect[] | null>(null);
  useLayoutEffect(() => {
    const st = stage.current;
    if (!st) return;
    const o = st.getBoundingClientRect();
    const next: Rect[] = [];
    for (const el of st.querySelectorAll<HTMLElement>("[data-geo-overlay]")) {
      const b = el.getBoundingClientRect();
      if (b.width > 0 && b.height > 0) next.push({ kind: "rect", x0: round2(b.left - o.left), y0: round2(b.top - o.top), x1: round2(b.right - o.left), y1: round2(b.bottom - o.top) });
    }
    setOverlays((old) => (old && JSON.stringify(old) === JSON.stringify(next) ? old : next));
  });
  const obstacles = useMemo(() => overlays ?? [], [overlays]);
  // Исторический режим — когда нарисован слой образований года; иначе современная карта.
  const polity = usePolities(props.year);
  const historical = polity.mode === "historical" && polity.layer ? polity.layer : null;
  const labels = historical ? labelInputs(historical) : COUNTRY_INPUT;
  const restIn: RestInput = { scene, nameOf, measure, fv: props.fontsVersion, frame, width, height, obstacles, labels, labelPrecision: historical ? POLITY_PRECISION : COUNTRY_PRECISION };

  // Исходный вид — из мест первого показа слоя (после загрузки шрифтов: от них зависят
  // подписи стран, а значит и приближение); «0» возвращает к нему для года T и размера сейчас.
  const home = useRef<View | null>(null);
  const homeLayer = useRef<GeoLayer | null>(null);
  // Исходный вид — после первого ответа слоя образований: приближение подбирается по тем
  // подписям, что будут на карте, и не зависит от порядка ответов /map/places и /map/polities.
  if (scene && layer && props.fontsVersion > 0 && overlays && polity.mode !== "pending" && homeLayer.current !== layer) {
    homeLayer.current = layer;
    home.current = homeFor(scene.places, restIn);
  }
  const [view, setView] = useState<View>(() => home.current ?? initialView([]));
  const viewRef = useRef(view);
  viewRef.current = view;
  const appliedHome = useRef<View | null>(null);
  useEffect(() => {
    if (home.current && appliedHome.current !== home.current) {
      appliedHome.current = home.current;
      setView(home.current);
    }
  });

  // Анимации (поворот к месту, инерция) — одна за раз; любое действие читателя её снимает.
  // Пока глобус тянут (и по инерции), путь грубее, раскладка не пересчитывается: кадр легче.
  const [moving, setMoving] = useState(false);
  const anim = useRef(0);
  const cancel = useCallback(() => {
    if (anim.current) cancelAnimationFrame(anim.current);
    anim.current = 0;
    setMoving(false);
  }, []);
  useEffect(() => cancel, [cancel]);

  const apply = useCallback(
    (next: View) => {
      cancel();
      setView(next);
    },
    [cancel],
  );

  // Поворот к месту из списка: плавно не дольше FOCUS_MS, при уменьшенном движении — сразу.
  const focusNonce = props.focus?.nonce;
  useEffect(() => {
    const f = props.focus;
    if (!f) return;
    const target = centerOn(viewRef.current, f);
    if (reduced) return apply(target);
    cancel();
    const lerp = interpolateCenter(viewRef.current, target);
    const t0 = performance.now();
    setMoving(true); // кадры поворота — сдвиги раскладки, полная — в покое
    const tick = () => {
      const k = Math.min(1, (performance.now() - t0) / FOCUS_MS);
      const e = k < 0.5 ? 4 * k * k * k : 1 - (-2 * k + 2) ** 3 / 2;
      setView(k >= 1 ? target : lerp(e));
      anim.current = k >= 1 ? 0 : requestAnimationFrame(tick);
      if (!anim.current) setMoving(false);
    };
    anim.current = requestAnimationFrame(tick);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusNonce]);

  // Колесо — приближение; слушатель не пассивный: страница под глобусом не прокручивается.
  useEffect(() => {
    const el = svg.current;
    if (!el) return;
    let acc = 0;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      acc += e.deltaY;
      const steps = acc <= -WHEEL_STEP / 2 ? 1 : acc >= WHEEL_STEP / 2 ? -1 : 0;
      if (!steps) return;
      acc = 0;
      apply(zoomBy(viewRef.current, steps));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [apply]);

  // Подсказка: что под указателем; при перетаскивании скрыта.
  const [tip, setTip] = useState<{ text: string; x: number; y: number } | null>(null);

  // Перетаскивание: поворот по пикселям, кадр — не чаще раза за requestAnimationFrame.
  const drag = useRef<{ id: number; x: number; y: number; start: View; moved: boolean; samples: [number, number, number][] } | null>(null);
  const pending = useRef<View | null>(null);
  const pr = useMemo(() => projector(view, frame, moving ? DRAG_PRECISION : undefined), [view, frame, moving]);
  const onPointerDown = (e: ReactPointerEvent<SVGSVGElement>) => {
    if (e.button !== 0) return;
    cancel();
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, start: viewRef.current, moved: false, samples: [[e.clientX, e.clientY, performance.now()]] };
  };
  const onPointerMove = (e: ReactPointerEvent<SVGSVGElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
    if (!d.moved) {
      d.moved = true;
      setMoving(true);
      setTip(null);
      svg.current?.setPointerCapture?.(e.pointerId);
    }
    d.samples.push([e.clientX, e.clientY, performance.now()]);
    if (d.samples.length > 5) d.samples.shift();
    const k = degreesPerPixel(projector(d.start, frame));
    pending.current = rotateBy(d.start, -dx * k, dy * k);
    if (!anim.current)
      anim.current = requestAnimationFrame(() => {
        anim.current = 0;
        if (pending.current) setView(pending.current);
        pending.current = null;
      });
  };
  const onPointerUp = (e: ReactPointerEvent<SVGSVGElement>) => {
    const d = drag.current;
    drag.current = null;
    if (!d || d.id !== e.pointerId) return;
    if (!d.moved) return click(e.target as Element);
    if (pending.current) {
      setView(pending.current);
      viewRef.current = pending.current;
      pending.current = null;
    }
    const still = () => setMoving(false);
    if (reduced) return still(); // без инерции
    const [a, b] = [d.samples[0], d.samples[d.samples.length - 1]];
    const dt = b[2] - a[2];
    if (dt <= 0 || dt > 120) return still();
    const k = degreesPerPixel(projector(viewRef.current, frame));
    let vLon = (-(b[0] - a[0]) * k) / dt; // градусов в мс
    let vLat = ((b[1] - a[1]) * k) / dt;
    if (Math.hypot(vLon, vLat) < 0.01) return still();
    const t0 = performance.now();
    let last = t0;
    cancel();
    setMoving(true);
    const tick = () => {
      const now = performance.now();
      const step = now - last;
      last = now;
      const decay = Math.pow(0.9, step / 16);
      vLon *= decay;
      vLat *= decay;
      const next = rotateBy(viewRef.current, vLon * step, vLat * step);
      viewRef.current = next;
      setView(next);
      anim.current = now - t0 < INERTIA_MS && Math.hypot(vLon, vLat) > 0.002 ? requestAnimationFrame(tick) : 0;
      if (!anim.current) still();
    };
    anim.current = requestAnimationFrame(tick);
  };

  const onKeyDown = (e: KeyboardEvent<SVGSVGElement>) => {
    const step = e.shiftKey ? STEP_SHIFT : STEP;
    const v = viewRef.current;
    let next: View | null = null;
    if (e.key === "ArrowRight") next = rotateBy(v, step, 0);
    else if (e.key === "ArrowLeft") next = rotateBy(v, -step, 0);
    else if (e.key === "ArrowUp") next = rotateBy(v, 0, step);
    else if (e.key === "ArrowDown") next = rotateBy(v, 0, -step);
    else if (e.key === "+" || e.key === "=") next = zoomBy(v, 1);
    else if (e.key === "-" || e.key === "_" || e.key === "−") next = zoomBy(v, -1);
    else if (e.key === "0") next = scene ? homeFor(scene.places, restIn) : initialView([]); // по местам года T и размеру сейчас
    else if (e.key === "PageUp") props.onYearStep(10);
    else if (e.key === "PageDown") props.onYearStep(-10);
    else if (e.key === "]") props.onYearStep(1);
    else if (e.key === "[") props.onYearStep(-1);
    else if (e.key === " ") props.onTogglePlay();
    else return;
    e.preventDefault();
    if (next) apply(next);
  };

  const [keysOpen, setKeysOpen] = useState(false);
  const [failed, setFailed] = useState<Set<string>>(() => new Set());

  // --- раскладка ---
  const R = pr.scale;
  const lf: LFrame = { w: width, h: height, cx: frame.cx, cy: frame.cy, R };
  const places = useMemo(() => scene?.places ?? [], [scene]);
  const rest = useRef<RestLayout | null>(null);
  const { anchors, lay, countries } = useMemo(() => {
    const r: RestInput = { scene, nameOf, measure, fv: props.fontsVersion, frame, width, height, obstacles, labels, labelPrecision: historical ? POLITY_PRECISION : COUNTRY_PRECISION };
    const anchors = anchorsAt(pr.projection, view, places, width, height);
    const lf: LFrame = { w: width, h: height, cx: frame.cx, cy: frame.cy, R: pr.scale };
    const got = frameLayout(rest.current, scene, moving, anchors, lf, () => markersAt(anchors, lf, r), obstacles);
    rest.current = got.rest;
    const lay = got.layout;
    if (moving) return { anchors, lay, countries: [] as CountryLabel[] };
    return { anchors, lay, countries: countriesAt(view, lf, lay.grid, r) };
    // fontsVersion: шрифты загрузились — ширины подписей меряются заново.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [places, pr, view, frame, width, height, moving, scene, nameOf, measure, props.fontsVersion, obstacles, labels]);
  const anchorOf = new Map(anchors.map((a) => [a.id, a]));
  const slotOf = new Map<string, PersonSlot>(lay.persons.map((s) => [s.id, s]));
  const personOf = new Map((scene?.persons ?? []).map((p) => [p.id, p]));
  const eventOf = new Map((scene?.events ?? []).map((e) => [e.id, e]));
  const placeOf = new Map(places.map((p) => [p.id, p]));

  // Портреты — только у нарисованных медальонов, не больше MAX_PORTRAITS (по порядку раскладки),
  // и только после исходного вида: до него раскладка временная (вид по умолчанию, шрифты не
  // загружены), и портреты грузились бы для медальонов, которых в итоге не будет.
  const homed = home.current !== null && (view === home.current || appliedHome.current === home.current);
  const portraitFor = new Map<string, string>();
  for (const s of homed ? lay.persons : []) {
    if (portraitFor.size >= MAX_PORTRAITS) break;
    const url = !s.hidden && !s.packed ? props.info(s.id)?.portrait : null;
    if (url && !failed.has(s.id)) portraitFor.set(s.id, url);
  }

  const where = (placeId: string) => {
    const p = placeOf.get(placeId);
    if (!p) return "";
    return t.geo.placeWithCountry(p.label, countryOf(p)?.name ?? null);
  };
  const showTip = (target: Element, x: number, y: number) => {
    const el = target.closest?.("[data-geo-person],[data-geo-name],[data-geo-event]");
    if (!el || drag.current?.moved) return setTip(null);
    const id = el.getAttribute("data-geo-person") ?? el.getAttribute("data-geo-name") ?? el.getAttribute("data-geo-event")!;
    const place = personOf.get(id)?.place ?? eventOf.get(id)?.place;
    if (!place) return setTip(null);
    const name = props.info(id)?.name;
    if (!name) return setTip(null);
    const text = `${name} — ${where(place)}`;
    setTip((old) => (old && old.text === text ? old : { text, x, y }));
  };

  // Щелчок: медальон, подпись или значок события — выбор сущности; значок «+N» одного места —
  // выбор места, нескольких — приближение вдвое к их середине (на пределе — первое место);
  // поле — снять выбор.
  function click(target: Element) {
    const el = target.closest?.("[data-geo-person],[data-geo-name],[data-geo-event],[data-geo-more]");
    if (!el) return props.onSelect(null);
    const more = el.getAttribute("data-places");
    if (el.hasAttribute("data-geo-more") && more != null) {
      const ids = more.split(" ").filter(Boolean);
      if (ids.length <= 1 || viewRef.current.zoom >= MAX_ZOOM - 1e-9) return props.onSelect(ids[0] ?? null);
      const pts = ids.map((id) => placeOf.get(id)).filter((p): p is NonNullable<typeof p> => !!p);
      const mid = initialView(pts);
      return apply({ lon: mid.lon, lat: mid.lat, zoom: Math.min(MAX_ZOOM, viewRef.current.zoom * 2) });
    }
    props.onSelect(el.getAttribute("data-geo-person") ?? el.getAttribute("data-geo-name") ?? el.getAttribute("data-geo-event"));
  }

  // --- основа на canvas ---
  // Тень, море, сетка, суша, границы, береговая линия. Цвета — токены, прочитанные из CSS
  // (getComputedStyle), литералов нет.
  const base = useRef<HTMLCanvasElement>(null);
  useLayoutEffect(() => {
    const c = base.current;
    const ctx = c?.getContext("2d");
    if (!c || !ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const w = Math.round(width * dpr);
    const h = Math.round(height * dpr);
    if (c.width !== w || c.height !== h) {
      c.width = w;
      c.height = h;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const css = getComputedStyle(c);
    const color = (name: string) => css.getPropertyValue(name).trim();
    const R0 = pr.scale;
    // Тень под глобусом: эллипс с радиальным затуханием.
    ctx.save();
    ctx.translate(frame.cx + R0 * 0.04, frame.cy + R0 * 0.98);
    ctx.scale(1, 0.09);
    const g = ctx.createRadialGradient(0, 0, 0, 0, 0, R0 * 0.8);
    g.addColorStop(0, color("--globe-coast"));
    g.addColorStop(1, "transparent");
    ctx.globalAlpha = 0.22;
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(0, 0, R0 * 0.8, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
    const path = canvasPath(pr, ctx);
    ctx.beginPath();
    path({ type: "Sphere" });
    ctx.fillStyle = color("--globe-sea");
    ctx.fill();
    ctx.beginPath();
    path(GRATICULE);
    ctx.strokeStyle = color("--globe-graticule");
    ctx.lineWidth = 0.8;
    ctx.lineCap = "round";
    ctx.setLineDash([0.6, 3.2]);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    path(LAND);
    ctx.fillStyle = color("--globe-land");
    ctx.fill();
    ctx.beginPath();
    if (historical) for (const p of historical.polities) path(p.geometry);
    else path(BORDERS);
    ctx.strokeStyle = color("--globe-border");
    ctx.lineWidth = 0.6;
    ctx.lineJoin = "round";
    ctx.stroke();
    ctx.beginPath();
    path(LAND);
    ctx.strokeStyle = color("--globe-coast");
    ctx.lineWidth = 0.75;
    ctx.stroke();
    // Линии границ на видимом полушарии: хотя бы одна вершина ближе 90° к центру.
    const v = { lon: -pr.projection.rotate()[0], lat: -pr.projection.rotate()[1], zoom: 1 };
    const lines = historical ? ringsOf(historical) : BORDERS.coordinates;
    const seen = lines.filter((line) => line.some(([lon, lat]) => isNear(v, { lon, lat }))).length;
    c.dataset.borders = String(seen);
    c.dataset.countries = String(COUNTRY_COUNT);
    c.dataset.mapMode = historical ? "historical" : "modern";
    if (historical) {
      c.dataset.polityFrom = String(historical.valid_from);
      c.dataset.polityTo = String(historical.valid_to);
      c.dataset.polities = String(historical.polities.length);
    } else {
      delete c.dataset.polityFrom;
      delete c.dataset.polityTo;
      delete c.dataset.polities;
    }
    c.dataset.drawn = "true";
  }, [pr, frame, width, height, historical]);

  const sphere = pr.path({ type: "Sphere" }) ?? "";
  const links = scene?.links ?? [];
  const trail =
    roles.trail.length > 1
      ? pr.path({ type: "LineString", coordinates: roles.trail.map((g) => [g.lon, g.lat]) })
      : null;
  const dim = roles.active;
  const busy = status === "loading";
  // слой разложен по шрифтам и препятствиям; первый ответ слоя образований получен
  const ready = !busy && polity.mode !== "pending" && (status !== "ok" || (props.fontsVersion > 0 && overlays !== null));
  const empty = status === "ok" && (layer?.places.length ?? 0) === 0;
  const nobody = status === "ok" && !empty && places.length === 0;

  // Выноски: от сдвинутого больше чем на MEDAL/2 маркера к точке привязки его места.
  const leaders: { key: string; x1: number; y1: number; x2: number; y2: number; place: string }[] = [];
  const lead = (key: string, x: number, y: number, placeId: string) => {
    const a = anchorOf.get(placeId);
    if (a && a.visible && Math.hypot(x - a.x, y - a.y) > MEDAL / 2) leaders.push({ key, x1: x, y1: y, x2: a.x, y2: a.y, place: placeId });
  };
  lay.persons.forEach((s) => !s.hidden && !s.packed && lead(`p:${s.id}`, s.x, s.y, s.place));
  lay.badges.forEach((b, i) => !b.hidden && b.places.forEach((pl) => lead(`b:${i}:${pl}`, b.x, b.y, pl)));
  lay.events.forEach((e) => !e.hidden && lead(`e:${e.id}`, e.x, e.y, e.place));
  const anchorsShown = [...new Set(leaders.map((l) => l.place))];

  // Деления латунного обода — через 10°, крупные через 30° (неподвижны, как меридианное кольцо).
  const ticks = useMemo(() => {
    const out: string[] = [];
    const r0 = frame.radius * view.zoom + 5;
    for (let a = 0; a < 360; a += 10) {
      const rad = (a * Math.PI) / 180;
      const len = a % 30 === 0 ? 6 : 3;
      const x1 = frame.cx + Math.cos(rad) * r0;
      const y1 = frame.cy + Math.sin(rad) * r0;
      const x2 = frame.cx + Math.cos(rad) * (r0 + len);
      const y2 = frame.cy + Math.sin(rad) * (r0 + len);
      out.push(`M${x1.toFixed(1)},${y1.toFixed(1)}L${x2.toFixed(1)},${y2.toFixed(1)}`);
    }
    return out.join("");
  }, [frame, view.zoom]);

  const cls = (base: string, role: string | undefined, extra: string[] = []) =>
    [base, role ? `is-on map-role-${role}` : "", ...extra].filter(Boolean).join(" ");

  return (
    <div ref={stage} className="geo-stage" style={{ width, height }}>
      <canvas ref={base} className="geo-land" data-geo-land="" style={{ width, height }} aria-hidden="true" />
      <svg
        ref={svg}
        className="geo-globe"
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="application"
        aria-roledescription={t.geo.roledescription}
        aria-label={props.summary}
        aria-describedby="geo-keys-hint"
        aria-busy={!ready}
        tabIndex={0}
        data-year={props.year}
        data-center={centerAttr(view)}
        data-zoom={fmt(view.zoom)}
        onPointerDown={onPointerDown}
        onPointerMove={(e) => {
          onPointerMove(e);
          if (!drag.current?.moved) showTip(e.target as Element, e.nativeEvent.offsetX, e.nativeEvent.offsetY);
        }}
        onPointerUp={onPointerUp}
        onPointerLeave={() => setTip(null)}
        onPointerCancel={() => (drag.current = null)}
        onKeyDown={onKeyDown}
      >
        <defs>
          <radialGradient id="geo-shade" cx="38%" cy="32%" r="72%">
            <stop className="geo-shade__light" offset="0%" />
            <stop className="geo-shade__mid" offset="55%" />
            <stop className="geo-shade__dark" offset="100%" />
          </radialGradient>
        </defs>
        <path className="geo-shade" d={sphere} aria-hidden="true" />
        <g className="geo-countries" aria-hidden="true">
          {countries.map((c) =>
            historical ? (
              <text
                key={c.id}
                className={dim ? "geo-country geo-polity is-dim" : "geo-country geo-polity"}
                data-geo-polity={c.id}
                data-name-status={c.italic ? "original" : "ru"}
                data-area={c.area}
                data-span={c.span}
                x={c.x}
                y={c.y}
                textAnchor="middle"
                data-fill={c.fill ? "true" : undefined}
                style={{ font: (c.italic ? ITALIC_FONTS : COUNTRY_FONTS)[c.font] }}
              >
                {c.italic && <title>{t.geo.untranslated(c.text)}</title>}
                {c.text}
              </text>
            ) : (
              <text key={c.id} className={dim ? "geo-country is-dim" : "geo-country"} data-geo-country={c.id} data-area={c.area} data-span={c.span} x={c.x} y={c.y} textAnchor="middle" data-fill={c.fill ? "true" : undefined} style={{ font: COUNTRY_FONTS[c.font] }}>
                {c.text}
              </text>
            ),
          )}
        </g>
        <g className="geo-links" aria-hidden="true">
          {trail && <path className="geo-trail map-role-self" d={trail} />}
          {links.map((l) => {
            const a = markerOf(lay, slotOf, l.from);
            const b = markerOf(lay, slotOf, l.to);
            const same = a && b && Math.hypot(a.x - b.x, a.y - b.y) < 0.5;
            const arc = a && b && !same ? arcBetween(a, b, lf) : null;
            const role = roles.links.get(l.id);
            return (
              <g
                key={l.id}
                className={cls("geo-link", role, l.link.generated ? ["is-generated"] : [])}
                data-geo-link={l.id}
                data-from={l.from}
                data-to={l.to}
                data-status={l.link.status}
                data-generated={l.link.generated ? "true" : "false"}
                data-age={l.age}
                data-hidden={arc ? "false" : "true"}
                data-role={role}
                data-dim={dim && !role ? "true" : undefined}
                style={{ opacity: opacity(l.age) }}
              >
                {arc && <path className="geo-link__arc" d={arc.d} />}
                {arc && <path className="geo-link__arrow" d={arc.arrow} />}
              </g>
            );
          })}
        </g>
        <g className="geo-leaders" aria-hidden="true">
          {leaders.map((l) => (
            <line key={l.key} className="geo-leader" x1={l.x1} y1={l.y1} x2={l.x2} y2={l.y2} />
          ))}
          {anchorsShown.map((id) => {
            const a = anchorOf.get(id)!;
            return <circle key={id} className="geo-anchor" data-geo-anchor={id} cx={a.x} cy={a.y} r={1.75} />;
          })}
        </g>
        <g className="geo-events" aria-hidden="true">
          {lay.events.map((e) => {
            const se = eventOf.get(e.id);
            const role = roles.events.get(e.id);
            const r = EVENT_MARK / 2;
            return (
              <g
                key={e.id}
                className={cls("geo-event", role, se?.generated ? ["is-unverified"] : [])}
                data-geo-event={e.id}
                data-place={e.place}
                data-age={se?.age ?? 0}
                data-unverified={se?.generated ? "true" : "false"}
                data-hidden={e.hidden ? "true" : "false"}
                data-x={e.x}
                data-y={e.y}
                data-role={role}
                data-dim={dim && !role ? "true" : undefined}
                transform={e.hidden ? undefined : `translate(${e.x},${e.y})`}
                style={{ opacity: opacity(se?.age ?? 0) }}
              >
                {!e.hidden && <path className="geo-event__mark" d={`M0,${-r}L${r},0L0,${r}L${-r},0Z`} />}
              </g>
            );
          })}
        </g>
        <g className="geo-persons" aria-hidden="true">
          {lay.persons.map((s, i) => {
            const sp = personOf.get(s.id);
            const role = roles.persons.get(s.id);
            const drawn = !s.hidden && !s.packed;
            const info = props.info(s.id);
            const url = portraitFor.get(s.id);
            const r = MEDAL / 2;
            return (
              <g
                key={s.id}
                className={cls("geo-medal", role, sp?.generated ? ["is-unverified"] : [])}
                data-geo-person={s.id}
                data-place={s.place}
                data-age={sp?.age ?? 0}
                data-unverified={sp?.generated ? "true" : "false"}
                data-hidden={s.hidden ? "true" : "false"}
                data-packed={s.packed ? "true" : "false"}
                data-x={s.x}
                data-y={s.y}
                data-role={role}
                data-dim={dim && !role ? "true" : undefined}
                transform={drawn ? `translate(${s.x},${s.y})` : undefined}
                style={{ opacity: opacity(sp?.age ?? 0) }}
              >
                {drawn && (
                  <>
                    <circle className="geo-medal__disc" r={r} />
                    {url ? (
                      <>
                        <clipPath id={`geo-clip-${i}`}>
                          <circle r={r - 1.5} />
                        </clipPath>
                        <image
                          href={url}
                          x={-r}
                          y={-r}
                          width={r * 2}
                          height={r * 2}
                          preserveAspectRatio="xMidYMid slice"
                          clipPath={`url(#geo-clip-${i})`}
                          onError={() => setFailed((f) => new Set(f).add(s.id))}
                        />
                      </>
                    ) : (
                      <text className="geo-medal__mono" y={3.5}>
                        {monogram(info?.full || info?.name || "")}
                      </text>
                    )}
                    <circle className="geo-medal__ring" r={r} />
                  </>
                )}
              </g>
            );
          })}
          {lay.badges.map((b, i) => (
            <g
              key={`more-${i}`}
              className="geo-more"
              data-geo-more=""
              data-places={b.places.join(" ")}
              data-count={b.count}
              data-hidden={b.hidden ? "true" : "false"}
              data-x={b.x}
              data-y={b.y}
              transform={b.hidden ? undefined : `translate(${b.x},${b.y})`}
            >
              {!b.hidden && (
                <>
                  <circle className="geo-more__disc" r={MEDAL / 2} />
                  <text className="geo-more__count" y={3.5}>
                    +{b.count}
                  </text>
                </>
              )}
            </g>
          ))}
        </g>
        <g className="geo-names" aria-hidden="true">
          {lay.persons.map((s) =>
            s.label && !s.hidden && !s.packed ? (
              <text
                key={s.id}
                className={roles.persons.get(s.id) ? `geo-name is-on map-role-${roles.persons.get(s.id)}` : dim ? "geo-name is-dim" : "geo-name"}
                data-geo-name={s.id}
                x={s.label.x}
                y={s.label.y}
                textAnchor={s.label.anchor}
                style={{ font: NAME_FONT }}
              >
                {nameOf(s.id)}
              </text>
            ) : null,
          )}
        </g>
        <circle className="geo-rim" cx={frame.cx} cy={frame.cy} r={R + 2.5} aria-hidden="true" />
        <circle className="geo-rim__inner" cx={frame.cx} cy={frame.cy} r={R} aria-hidden="true" />
        <path className="geo-rim__ticks" d={ticks} aria-hidden="true" />
      </svg>

      {tip && (
        <div className="geo-tip" data-geo-tip="" aria-hidden="true" style={{ left: tip.x + 14, top: tip.y + 14 }}>
          {tip.text}
        </div>
      )}
      {historical ? (
        <div className="geo-coast geo-coast--historical" data-geo-overlay="coast" data-geo-source="historical">
          <p>
            {t.geo.historicalBorders}{" "}
            {historical.source.url ? (
              <a href={historical.source.url} target="_blank" rel="noopener noreferrer">
                {historical.source.title}
              </a>
            ) : (
              historical.source.title
            )}{" "}
            ({historical.source.publisher}): {historical.source.authors.join(", ")}, {historical.source.version},{" "}
            {historical.source.license_url ? (
              <a href={historical.source.license_url} target="_blank" rel="noopener noreferrer">
                {historical.source.license}
              </a>
            ) : (
              historical.source.license
            )}
          </p>
          <p>{t.geo.historicalNote}</p>
        </div>
      ) : (
        <p className="geo-coast" data-geo-overlay="coast" data-geo-source="modern">
          {t.geo.coast}
        </p>
      )}
      {polity.error && (
        <p className="geo-polities-note" data-geo-overlay="polities-note" data-geo-polities-note="" role="status">
          {t.geo.politiesError}
        </p>
      )}
      <div className="geo-keys">
        <button type="button" className="pg-btn pg-btn--ghost pg-btn--sm" aria-expanded={keysOpen} aria-controls="geo-keys-hint" data-geo-overlay="keys" onClick={() => setKeysOpen((o) => !o)}>
          {t.geo.keys}
        </button>
        <p id="geo-keys-hint" className="geo-keys__hint" data-geo-overlay="keys-hint" hidden={!keysOpen}>
          {t.geo.keysHint}
        </p>
      </div>
      {busy && (
        <p className="geo-state geo-state--loading" data-geo-overlay="state" role="status">
          {t.geo.loading}
        </p>
      )}
      {status === "error" && (
        <div className="geo-state pg-notice pg-notice--danger pg-notice--stacked" data-geo-overlay="state" role="alert">
          <div>
            <strong>{t.geo.error}</strong>
            <p>{t.geo.errorHint}</p>
          </div>
          <button type="button" className="pg-btn pg-btn--secondary pg-btn--sm" onClick={props.onRetry}>
            {t.geo.retry}
          </button>
        </div>
      )}
      {empty && (
        <div className="geo-state" data-geo-overlay="state">
          <strong>{t.geo.empty}</strong>
          <p>{t.geo.emptyHint}</p>
          <button type="button" className="pg-btn pg-btn--secondary pg-btn--sm" onClick={props.onToChrono}>
            {t.geo.toChrono}
          </button>
        </div>
      )}
      {nobody && (
        <div className="geo-state" data-geo-overlay="state" role="status">
          <strong>{t.geo.nobody(props.year)}</strong>
          {props.nearest != null && (
            <button type="button" className="pg-btn pg-btn--secondary pg-btn--sm" onClick={props.onNearest}>
              {t.geo.nearest}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
