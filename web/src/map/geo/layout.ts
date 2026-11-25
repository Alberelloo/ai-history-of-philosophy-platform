// Раскладка глобуса (rework-globe-political-map): медальоны персон, значки «+N», значки
// событий, подписи персон и подписи стран без наложений. Чистые функции без DOM: экранные
// точки привязки мест считает вызывающий (проекция), ширину текста — внедряемый measure.
//
// Геометрия пересечений одна на всё (раскладка, подписи стран, юнит-тесты): маркеры — круги,
// текст — прямоугольник с полем LABEL_PAD; пересечение — глубина больше TOUCH.
//
// Порядок раскладки задаёт сцена (timeline.ts): персоны по рангу внутри места, затем по
// порядку мест; события — после персон; значки «+N» — после событий. Кандидаты позиции —
// точка привязки и кольца k = 1…RINGS по 6k позиций на расстоянии k·STEP, от верхней по
// часовой стрелке.

import { geoCentroid, geoContains, geoDistance, type GeoPath, type GeoProjection } from "d3-geo";
import type { Feature, MultiPolygon, Polygon } from "geojson";
import { MAX_PERSONS } from "./timeline";

export const MEDAL = 26;
export const MEDAL_GAP = 4;
export const STEP = MEDAL + MEDAL_GAP; // шаг колец: не меньше MEDAL — соседние круги не пересекаются
export const RINGS = 3;
export const MAX_SHIFT = RINGS * STEP;
export const EVENT_MARK = 10;
export const TOUCH = 0.5;
export const MAX_FAILS = 6;
export { MAX_PERSONS }; // предел медальонов в DOM живёт в timeline.ts (без d3): его читает панель
export const MAX_PORTRAITS = 60;
export const LABEL_PAD = 1.5;
export const NAME_GAP = 4;
export const TEXT_GAP = 2; // px: запас раскладки у текста сверх геометрии пересечений
export const COUNTRY_MIN_AREA = 1500;
export const MAX_COUNTRY_LABELS = 24;
export const COUNTRY_MIN_LABELS = 5; // меньше — добор (layoutCountries)

export type Circle = { kind: "circle"; x: number; y: number; r: number };
export type Rect = { kind: "rect"; x0: number; y0: number; x1: number; y1: number };
export type Shape = Circle | Rect;

export const round2 = (x: number): number => {
  const r = Math.round(x * 100) / 100;
  return r === 0 ? 0 : r;
};

function rectDistance(c: Circle, r: Rect): number {
  const dx = Math.max(r.x0 - c.x, 0, c.x - r.x1);
  const dy = Math.max(r.y0 - c.y, 0, c.y - r.y1);
  return Math.hypot(dx, dy);
}

export function overlaps(a: Shape, b: Shape): boolean {
  if (a.kind === "circle" && b.kind === "circle") return Math.hypot(a.x - b.x, a.y - b.y) < a.r + b.r - TOUCH;
  if (a.kind === "circle" && b.kind === "rect") {
    const inside = a.x >= b.x0 && a.x <= b.x1 && a.y >= b.y0 && a.y <= b.y1;
    return inside || rectDistance(a, b) < a.r - TOUCH;
  }
  if (a.kind === "rect" && b.kind === "circle") return overlaps(b, a);
  const ra = a as Rect;
  const rb = b as Rect;
  return Math.min(ra.x1, rb.x1) - Math.max(ra.x0, rb.x0) > TOUCH && Math.min(ra.y1, rb.y1) - Math.max(ra.y0, rb.y0) > TOUCH;
}

const grow = (r: Rect, d: number): Rect => ({ kind: "rect", x0: r.x0 - d, y0: r.y0 - d, x1: r.x1 + d, y1: r.y1 + d });

const box = (s: Shape): [number, number, number, number] =>
  s.kind === "circle" ? [s.x - s.r, s.y - s.r, s.x + s.r, s.y + s.r] : [s.x0, s.y0, s.x1, s.y1];

// Сетка-индекс положенных фигур: проверка пересечения — только с соседями по ячейкам.
// Ключ ячейки — число (без строк: раскладка зовёт hits десятки тысяч раз).
const cellKey = (i: number, j: number): number => (i + 32768) * 65536 + (j + 32768);
export class Grid {
  private cells = new Map<number, Shape[]>();
  readonly shapes: Shape[] = [];
  constructor(private size = 40) {}
  add(s: Shape): void {
    this.shapes.push(s);
    const [x0, y0, x1, y1] = box(s);
    const z = this.size;
    for (let i = Math.floor(x0 / z); i <= Math.floor(x1 / z); i++)
      for (let j = Math.floor(y0 / z); j <= Math.floor(y1 / z); j++) {
        const k = cellKey(i, j);
        const list = this.cells.get(k);
        if (list) list.push(s);
        else this.cells.set(k, [s]);
      }
  }
  // Проверка с запасом TEXT_GAP у текста: ширина, измеренная раскладкой, может расходиться
  // с отрисованной на доли пикселя (округление, кернинг) — ноль наложений держится и тогда.
  hits(s: Shape): boolean {
    const [x0, y0, x1, y1] = box(s);
    const z = this.size;
    const q = s.kind === "rect" ? grow(s, TEXT_GAP) : s;
    for (let i = Math.floor((x0 - TEXT_GAP) / z); i <= Math.floor((x1 + TEXT_GAP) / z); i++)
      for (let j = Math.floor((y0 - TEXT_GAP) / z); j <= Math.floor((y1 + TEXT_GAP) / z); j++) {
        const list = this.cells.get(cellKey(i, j));
        if (list)
          for (const o of list) if (overlaps(q, s.kind === "rect" || o.kind !== "rect" ? o : grow(o, TEXT_GAP))) return true;
      }
    return false;
  }
}

// Кадр: прямоугольник вида и круг глобуса (центр и радиус — масштаб проекции).
export type Frame = { w: number; h: number; cx: number; cy: number; R: number };

export const inCircle = (f: Frame, x: number, y: number): boolean => Math.hypot(x - f.cx, y - f.cy) <= f.R;
export function inFrame(f: Frame, s: Shape): boolean {
  const [x0, y0, x1, y1] = box(s);
  return x0 >= 0 && y0 >= 0 && x1 <= f.w && y1 <= f.h;
}

// Сдвиги кандидатов: точка привязки, затем кольца.
export const OFFSETS: [number, number][] = (() => {
  const out: [number, number][] = [[0, 0]];
  for (let k = 1; k <= RINGS; k++)
    for (let j = 0; j < 6 * k; j++) {
      const a = -Math.PI / 2 + (2 * Math.PI * j) / (6 * k);
      out.push([k * STEP * Math.cos(a), k * STEP * Math.sin(a)]);
    }
  return out;
})();

export type Metrics = { ascent: number; descent: number };
export type Measure = (text: string) => number;

export type LPlace = { id: string; x: number; y: number; visible: boolean };
export type LPerson = { id: string; place: string; name: string | null }; // null — без подписи
export type LEvent = { id: string; place: string };

export type NameLabel = { x: number; y: number; anchor: "start" | "end" | "middle"; rect: Rect };
export type PersonSlot = {
  id: string;
  place: string;
  x: number;
  y: number;
  dx: number; // сдвиг от точки привязки (для кадров перетаскивания)
  dy: number;
  hidden: boolean;
  packed: boolean;
  label: NameLabel | null;
  badge: number | null; // индекс значка, куда свёрнута персона
};
export type EventSlot = { id: string; place: string; x: number; y: number; dx: number; dy: number; hidden: boolean };
export type Badge = { places: string[]; x: number; y: number; dx: number; dy: number; hidden: boolean; count: number; persons: string[] };
export type Layout = { persons: PersonSlot[]; events: EventSlot[]; badges: Badge[]; grid: Grid };

function nameOptions(x: number, y: number, r: number, tw: number, m: Metrics): NameLabel[] {
  const mk = (tx: number, base: number, anchor: NameLabel["anchor"]): NameLabel => {
    const x0 = anchor === "start" ? tx : anchor === "end" ? tx - tw : tx - tw / 2;
    return { x: round2(tx), y: round2(base), anchor, rect: { kind: "rect", x0: x0 - LABEL_PAD, y0: base - m.ascent - LABEL_PAD, x1: x0 + tw + LABEL_PAD, y1: base + m.descent + LABEL_PAD } };
  };
  const mid = y + (m.ascent - m.descent) / 2;
  return [
    mk(x + r + NAME_GAP, mid, "start"),
    mk(x - r - NAME_GAP, mid, "end"),
    mk(x, y - r - NAME_GAP - m.descent, "middle"),
    mk(x, y + r + NAME_GAP + m.ascent, "middle"),
  ];
}

// Первая свободная позиция круга радиуса r у точки привязки (и подписи, если она нужна).
function search(
  grid: Grid,
  f: Frame,
  at: LPlace,
  r: number,
  name: { tw: number; m: Metrics } | null,
): { x: number; y: number; label: NameLabel | null } | null {
  for (const [ox, oy] of OFFSETS) {
    const x = round2(at.x + ox);
    const y = round2(at.y + oy);
    const c: Circle = { kind: "circle", x, y, r };
    if (!inCircle(f, x, y) || !inFrame(f, c) || grid.hits(c)) continue;
    if (!name) return { x, y, label: null };
    const label = nameOptions(x, y, r, name.tw, name.m).find((o) => inFrame(f, o.rect) && !grid.hits(o.rect)) ?? null;
    if (label) return { x, y, label };
  }
  return null;
}

export type LayoutInput = {
  places: LPlace[]; // в порядке сцены; x, y — проекция координат места
  persons: LPerson[]; // в порядке раскладки (ранг в месте, порядок мест)
  events: LEvent[];
  frame: Frame;
  measure: Measure;
  metrics: Metrics;
  maxPersons?: number;
};

export function layoutMarkers(inp: LayoutInput): Layout {
  const f = inp.frame;
  const grid = new Grid();
  const places = new Map(inp.places.map((p) => [p.id, p]));
  const R = MEDAL / 2;
  const limit = inp.maxPersons ?? MAX_PERSONS;
  const dom = inp.persons.slice(0, limit);
  const fails = new Map<string, number>();
  const persons: PersonSlot[] = [];
  const drawnOrder: PersonSlot[] = [];
  for (const p of dom) {
    const at = places.get(p.place);
    const slot: PersonSlot = { id: p.id, place: p.place, x: at ? round2(at.x) : 0, y: at ? round2(at.y) : 0, dx: 0, dy: 0, hidden: false, packed: false, label: null, badge: null };
    persons.push(slot);
    if (!at || !at.visible) {
      slot.hidden = true;
      continue;
    }
    if ((fails.get(p.place) ?? 0) >= MAX_FAILS) {
      slot.packed = true;
      continue;
    }
    const got = search(grid, f, at, R, p.name ? { tw: inp.measure(p.name), m: inp.metrics } : null);
    if (!got) {
      fails.set(p.place, (fails.get(p.place) ?? 0) + 1);
      slot.packed = true;
      continue;
    }
    fails.set(p.place, 0);
    Object.assign(slot, { x: got.x, y: got.y, dx: got.x - at.x, dy: got.y - at.y, label: got.label });
    grid.add({ kind: "circle", x: got.x, y: got.y, r: R });
    if (got.label) grid.add(got.label.rect);
    drawnOrder.push(slot);
  }

  const events: EventSlot[] = [];
  for (const e of inp.events) {
    const at = places.get(e.place);
    const slot: EventSlot = { id: e.id, place: e.place, x: at ? round2(at.x) : 0, y: at ? round2(at.y) : 0, dx: 0, dy: 0, hidden: true };
    events.push(slot);
    if (!at || !at.visible) continue;
    const got = search(grid, f, at, EVENT_MARK / 2, null);
    if (!got) continue;
    Object.assign(slot, { x: got.x, y: got.y, dx: got.x - at.x, dy: got.y - at.y, hidden: false });
    grid.add({ kind: "circle", x: got.x, y: got.y, r: EVENT_MARK / 2 });
  }

  // Свёрнутые и сверх предела — по местам (только места с видимой точкой привязки).
  const packedBy = new Map<string, PersonSlot[]>();
  for (const s of persons) if (s.packed) (packedBy.get(s.place) ?? packedBy.set(s.place, []).get(s.place)!).push(s);
  const overBy = new Map<string, number>();
  for (let i = limit; i < inp.persons.length; i++) {
    const place = inp.persons[i].place;
    if (places.get(place)?.visible) overBy.set(place, (overBy.get(place) ?? 0) + 1);
  }

  const badges: Badge[] = [];
  const pending: LPlace[] = [];
  const join = (b: number, place: string) => {
    const badge = badges[b];
    if (!badge.places.includes(place)) badge.places.push(place);
    for (const s of packedBy.get(place) ?? []) {
      s.badge = b;
      badge.persons.push(s.id);
    }
    badge.count += (packedBy.get(place)?.length ?? 0) + (overBy.get(place) ?? 0);
  };
  for (const at of inp.places) {
    if (!at.visible || !((packedBy.get(at.id)?.length ?? 0) + (overBy.get(at.id) ?? 0))) continue;
    const got = search(grid, f, at, R, null);
    if (!got) {
      pending.push(at);
      continue;
    }
    grid.add({ kind: "circle", x: got.x, y: got.y, r: R });
    badges.push({ places: [], x: got.x, y: got.y, dx: got.x - at.x, dy: got.y - at.y, hidden: false, count: 0, persons: [] });
    join(badges.length - 1, at.id);
  }
  for (const q of pending) {
    if (badges.length) {
      let best = 0;
      let bestD = Infinity;
      badges.forEach((b, i) => {
        const d = Math.hypot(b.x - q.x, b.y - q.y);
        if (d < bestD) {
          bestD = d;
          best = i;
        }
      });
      join(best, q.id);
      continue;
    }
    // Значков нет: значком становится последний положенный медальон ближайшего места.
    const drawn = drawnOrder.filter((s) => !s.packed);
    if (!drawn.length) {
      // Ни медальонов, ни значков: значок в точке привязки — персона не пропадает из счёта.
      badges.push({ places: [], x: round2(q.x), y: round2(q.y), dx: 0, dy: 0, hidden: false, count: 0, persons: [] });
      grid.add({ kind: "circle", x: q.x, y: q.y, r: R });
      join(badges.length - 1, q.id);
      continue;
    }
    let nearest = drawn[0];
    let nd = Infinity;
    for (const s of drawn) {
      const a = places.get(s.place)!;
      const d = Math.hypot(a.x - q.x, a.y - q.y);
      if (d < nd) {
        nd = d;
        nearest = s;
      }
    }
    const host = [...drawn].reverse().find((s) => s.place === nearest.place)!;
    host.packed = true;
    host.label = null;
    const anchor = places.get(host.place)!;
    badges.push({ places: [host.place], x: host.x, y: host.y, dx: host.x - anchor.x, dy: host.y - anchor.y, hidden: false, count: 1, persons: [host.id] });
    host.badge = badges.length - 1;
    join(badges.length - 1, q.id);
  }
  for (const s of persons) {
    if (s.packed && s.badge != null) {
      s.x = badges[s.badge].x;
      s.y = badges[s.badge].y;
    }
  }
  return { persons, events, badges, grid };
}

// Кадр перетаскивания: сдвиги последней раскладки сохраняются, подписи не показываются.
// Маркер, чей центр вышел из круга или фигура из кадра, скрыт.
export function shiftLayout(prev: Layout, places: LPlace[], f: Frame): Layout {
  const at = new Map(places.map((p) => [p.id, p]));
  const place = (id: string, dx: number, dy: number, r: number) => {
    const a = at.get(id);
    if (!a || !a.visible) return null;
    const x = round2(a.x + dx);
    const y = round2(a.y + dy);
    return inCircle(f, x, y) && inFrame(f, { kind: "circle", x, y, r }) ? { x, y } : null;
  };
  const badges = prev.badges.map((b) => {
    const p = b.hidden ? null : place(b.places[0], b.dx, b.dy, MEDAL / 2);
    return { ...b, x: p?.x ?? b.x, y: p?.y ?? b.y, hidden: !p };
  });
  const persons = prev.persons.map((s) => {
    if (s.hidden) return { ...s, label: null };
    if (s.packed) {
      const b = s.badge != null ? badges[s.badge] : null;
      return { ...s, label: null, x: b?.x ?? s.x, y: b?.y ?? s.y, hidden: !b || b.hidden };
    }
    const p = place(s.place, s.dx, s.dy, MEDAL / 2);
    return { ...s, label: null, x: p?.x ?? s.x, y: p?.y ?? s.y, hidden: !p };
  });
  const events = prev.events.map((e) => {
    if (e.hidden) return e;
    const p = place(e.place, e.dx, e.dy, EVENT_MARK / 2);
    return { ...e, x: p?.x ?? e.x, y: p?.y ?? e.y, hidden: !p };
  });
  return { persons, events, badges, grid: new Grid() };
}

// Раскладка кадра. В покое — полная (full). Во время движения — сдвиги последней раскладки
// покоя (shiftLayout), но только если она построена для той же сцены (key): сменился год
// или слой во время перетаскивания — полная раскладка, кадр — её сдвиги без подписей.
export type RestLayout = { key: unknown; layout: Layout };
export function frameLayout(
  rest: RestLayout | null,
  key: unknown,
  moving: boolean,
  places: LPlace[],
  f: Frame,
  full: () => Layout,
): { layout: Layout; rest: RestLayout } {
  if (moving && rest && rest.key === key) return { layout: shiftLayout(rest.layout, places, f), rest };
  const layout = full();
  const next = { key, layout };
  return { layout: moving ? shiftLayout(layout, places, f) : layout, rest: next };
}

// Маркер персоны на экране: её медальон или значок, куда она свёрнута; null — не виден.
export function markerOf(l: Layout, index: Map<string, PersonSlot>, id: string): Circle | null {
  const s = index.get(id);
  if (!s || s.hidden) return null;
  if (s.packed) {
    const b = s.badge != null ? l.badges[s.badge] : null;
    return b && !b.hidden ? { kind: "circle", x: b.x, y: b.y, r: MEDAL / 2 } : null;
  }
  return { kind: "circle", x: s.x, y: s.y, r: MEDAL / 2 };
}

// --- подписи стран ---

export type CountryInput = { id: string; name: string; feature: Feature<Polygon | MultiPolygon> };
export type CountryLabel = { id: string; text: string; x: number; y: number; area: number; span: number; rect: Rect; font: number; fill: boolean };

// Геометрия страны для отсева (один раз на страну): многоугольники, сферический центр и
// угловой радиус (наибольшее расстояние от центра до вершины).
type CountryGeo = { polys: Polygon[]; center: [number, number]; radius: number };
const geoCache = new WeakMap<object, CountryGeo>();
function geoOf(c: CountryInput): CountryGeo {
  let g = geoCache.get(c.feature);
  if (!g) {
    const polys: Polygon[] =
      c.feature.geometry.type === "Polygon" ? [c.feature.geometry] : c.feature.geometry.coordinates.map((coordinates) => ({ type: "Polygon", coordinates }));
    const center = geoCentroid(c.feature) as [number, number];
    let radius = 0;
    for (const p of polys) for (const ring of p.coordinates) for (const v of ring) radius = Math.max(radius, geoDistance(center, v as [number, number]));
    geoCache.set(c.feature, (g = { polys, center, radius }));
  }
  return g;
}

type CountryCand = { c: CountryInput; area: number; span: number; x: number; y: number };
type CandCache = { key: string; done: boolean; main: CountryCand[]; rest: CountryCand[] | null; later: CountryInput[] };
const candCache = new WeakMap<object, CandCache>();

// Шрифт подписи страны: начертание (для отрисовки), ширина текста и вертикальные метрики.
export type CountryFont = { font: string; measure: Measure; metrics: Metrics };

// Подписи стран. Основной проход: кандидаты с видимой площадью не меньше COUNTRY_MIN_AREA
// (path — проекция с обрезкой по полушарию и кадру) по убыванию площади; точка — центр
// крупнейшего видимого многоугольника, если он внутри страны; ширина подписи не больше
// видимой части; без пересечений с уже положенным (grid); не больше MAX_COUNTRY_LABELS.
// Добор: если подписей меньше COUNTRY_MIN_LABELS — остальные страны видимой стороны по
// убыванию площади по тем же правилам, основным кеглем, а не поместившиеся по ширине —
// кеглем добора (fonts[1]), пока подписей не COUNTRY_MIN_LABELS. Положенные — в grid.
export function layoutCountries(
  countries: CountryInput[],
  path: GeoPath,
  projection: GeoProjection,
  f: Frame,
  grid: Grid,
  fonts: CountryFont[],
): CountryLabel[] {
  const rot = projection.rotate();
  const center: [number, number] = [-rot[0], -rot[1]];
  const scale = projection.scale();
  // Кандидаты зависят только от вида и кадра: при смене года (проигрывание) — из кэша.
  const key = JSON.stringify([rot, scale, projection.translate(), projection.clipExtent(), f.w, f.h]);
  let cache = candCache.get(countries);
  if (!cache || cache.key !== key) candCache.set(countries, (cache = { key, done: false, main: [], rest: null, later: [] }));
  const { main, later } = cache;
  const rest: CountryCand[] = cache.rest ?? [];
  const fresh = !cache.done;
  cache.done = true;
  for (const c of fresh ? countries : []) {
    // Отсев без обрезки путей: страна целиком за полушарием или далеко за кадром.
    const g = geoOf(c);
    const dist = geoDistance(g.center, center);
    if (dist - g.radius > Math.PI / 2) continue;
    if (dist + g.radius < Math.PI / 2) {
      const xy = projection(g.center);
      const reach = 2 * Math.sin(Math.min(g.radius, Math.PI) / 2) * scale; // хорда: проекция не дальше
      if (xy && (xy[0] < -reach || xy[1] < -reach || xy[0] > f.w + reach || xy[1] > f.h + reach)) continue;
    }
    // Верхняя оценка: проекция шапки радиуса r лежит в круге радиуса scale·sin r.
    const bound = g.radius < Math.PI / 2 ? Math.PI * (scale * Math.sin(g.radius)) ** 2 : Infinity;
    if (bound < COUNTRY_MIN_AREA) later.push(c);
    else measureCand(c);
  }
  function measureCand(c: CountryInput): void {
    const g = geoOf(c);
    const area = path.area(c.feature);
    if (!(area > 0)) return;
    let best: Polygon | null = g.polys.length === 1 ? g.polys[0] : null;
    let bestA = 0;
    if (!best)
      for (const p of g.polys) {
        const a = path.area(p);
        if (a > bestA) {
          bestA = a;
          best = p;
        }
      }
    if (!best) return;
    const [[x0], [x1]] = path.bounds(c.feature);
    const [x, y] = path.centroid(best);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    const ll = projection.invert?.([x, y]);
    if (!ll || !geoContains(c.feature, ll)) return;
    (area >= COUNTRY_MIN_AREA ? main : rest).push({ c, area, span: x1 - x0, x, y });
  }
  const order = (a: CountryCand, b: CountryCand) => b.area - a.area || (a.c.id < b.c.id ? -1 : 1);
  if (fresh) main.sort(order);
  const out: CountryLabel[] = [];
  const place = (k: CountryCand, fi: number, fill: boolean): boolean => {
    const { measure, metrics: m } = fonts[fi];
    const tw = measure(k.c.name);
    if (tw + 2 * LABEL_PAD > k.span) return false; // прямоугольник подписи не шире видимой части
    const base = k.y + (m.ascent - m.descent) / 2;
    const rect: Rect = { kind: "rect", x0: k.x - tw / 2 - LABEL_PAD, y0: base - m.ascent - LABEL_PAD, x1: k.x + tw / 2 + LABEL_PAD, y1: base + m.descent + LABEL_PAD };
    if (!inFrame(f, rect) || grid.hits(rect)) return false;
    grid.add(rect);
    out.push({ id: k.c.id, text: k.c.name, x: round2(k.x), y: round2(base), area: Math.round(k.area), span: Math.round(k.span), rect, font: fi, fill });
    return true;
  };
  for (const k of main) {
    if (out.length >= MAX_COUNTRY_LABELS) break;
    place(k, 0, false);
  }
  if (out.length < COUNTRY_MIN_LABELS && !cache.rest) {
    for (const c of later) measureCand(c);
    rest.sort(order);
    cache.rest = rest;
  }
  if (out.length < COUNTRY_MIN_LABELS)
    for (const k of [...main.filter((k) => !out.some((o) => o.id === k.c.id)), ...rest]) {
      if (out.length >= COUNTRY_MIN_LABELS) break;
      for (let fi = 0; fi < fonts.length; fi++) if (place(k, fi, fi > 0 || k.area < COUNTRY_MIN_AREA)) break;
    }
  return out;
}
