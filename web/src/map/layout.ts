// Раскладка карты раздела — перенос из макета desk-chart.js (packPeople, pins, planWorks,
// planEvents, layoutBands, линии влияний). Чистые функции без DOM: ширина текста — через
// измеритель, переданный параметром (measure.ts в браузере, приближение в тестах).
//
// Новое против макета — вписывание в окно: страты событий, эпох и трудов берут высоту по
// содержимому (в пределах долей), люди — остаток. Если дорожек больше, чем помещается,
// возвращается peopleScroll и страта людей прокручивается внутри, ось и прочие страты стоят.
//
// Координаты: x — общие для всех страт; y событий, эпох и трудов — от верха кадра;
// y людей и линий влияний — от верха страты людей (её содержимого при прокрутке).

import type { ColorRole, Related, Visible } from "./model";
import type { MapData, MapEvent, MapPerson, MapWork, Stratum } from "./types";
import { STRATA } from "./types";

export type Measure = (text: string, font: string) => number;

/* ---------- шрифты: те же, что в стилях листа (CSS font shorthand) ---------- */

const SERIF = '"Literata Variable", Literata, Georgia, serif';
const SANS = "Onest, Arial, sans-serif";

export type MapFonts = {
  personName: string;
  selName: string; // имя персоны в цвете выбора
  personYears: string;
  workTitle: string;
  conceptTitle: string; // понятие, позиция, аргумент — прямое начертание
  workActive: string; // подпись труда в цвете выбора
  eventText: string;
  eraText: string;
  axisYear: string;
};

export function mapFonts(dense: boolean): MapFonts {
  return {
    personName: `600 ${dense ? 14 : 16}px ${SERIF}`,
    selName: `700 ${dense ? 15 : 17}px ${SERIF}`,
    personYears: `400 ${dense ? 11.5 : 12.5}px ${SANS}`,
    workTitle: `italic 500 ${dense ? 12.5 : 13}px ${SERIF}`,
    conceptTitle: `500 ${dense ? 12.5 : 13}px ${SERIF}`,
    workActive: `italic 600 13.5px ${SERIF}`,
    eventText: `italic 400 13px ${SERIF}`,
    eraText: `italic 500 14px ${SERIF}`,
    axisYear: `400 13.5px ${SERIF}`,
  };
}

// Все начертания карты — чтобы измеритель дождался их загрузки.
export const allMapFonts = (): string[] => [...new Set([...Object.values(mapFonts(true)), ...Object.values(mapFonts(false))])];

/* ---------- постоянные раскладки (px) ---------- */

export const W_ROW = 56; // ряд «булавок» трудов
export const E_ROW = 24; // ряд событий
export const ERA_H = 48; // страта эпох
export const LANE_STRETCH_DENSE = 1.3; // предел растяжения дорожки в плотном режиме
export const LANE_STRETCH = 2.4; // в редком режиме
export const WORKS_ROWS_SPARE = 5; // рядов трудов, когда люди оставляют место
export const DENSE_PEOPLE = 12; // больше — плотный режим: тонкие ленты, имя внутри

export type LayoutOptions = {
  plotLeft: number; // левое поле под линзы
  plotRightPad: number;
  top: number; // поле над стратами
  axisHeight: number; // ось с годами под стратами
  collapsedHeight: number; // свёрнутая страта
};

export const DEFAULT_OPTIONS: LayoutOptions = { plotLeft: 150, plotRightPad: 26, top: 28, axisHeight: 46, collapsedHeight: 28 };

/* ---------- шкала времени ---------- */

export type TimeScale = {
  y0: number;
  y1: number;
  left: number;
  right: number;
  x: (year: number) => number;
  clampX: (x: number) => number;
  year: (x: number) => number; // обратное x — для рамки окна и подсказок
  step: number; // шаг делений: подписи не ближе ~70 px
  ticks: number[];
};

const STEPS = [1, 2, 5, 10, 25, 50, 100, 200, 500];

export function timeScale([y0, y1]: [number, number], left: number, right: number): TimeScale {
  const span = Math.max(1, y1 - y0);
  const k = (right - left) / span;
  const step = STEPS.find((s) => s * k >= 70) ?? STEPS[STEPS.length - 1];
  const ticks: number[] = [];
  for (let y = Math.ceil(y0 / step) * step; y <= y1; y += step) ticks.push(y);
  return {
    y0,
    y1,
    left,
    right,
    x: (y) => left + (y - y0) * k,
    clampX: (x) => Math.max(left, Math.min(right, x)),
    year: (x) => y0 + (x - left) / k,
    step,
    ticks,
  };
}

/* ---------- люди: дорожки ---------- */

export type PersonPlace = {
  id: string;
  bx: number; // рождение
  dx: number; // смерть
  lane: number;
  y: number; // центр ленты, от верха страты людей
  label: string; // полное имя или краткое, если полное не влезает в плотную ленту
  nameX: number; // начало подписи имени
  labelEnd: number; // конец подписи — от него идут линии влияний
  yearsIn: boolean; // годы жизни внутри ленты (иначе — справа от неё)
  yearsX: number; // x подписи годов (у правого края ленты при yearsIn, иначе после имени)
  role: ColorRole | null; // цвет в выборе; null — без выбора или приглушён
  dim: boolean; // выбор есть, а персона в него не входит
  medallion: boolean; // плотный режим: медальон выбранного у начала ленты
};

type Packed = { id: string; p: MapPerson; bx: number; dx: number; label: string; yearsIn: boolean; occ: [number, number]; lane: number };

// Жадная упаковка по году рождения; занятый отрезок — лента вместе с подписями.
export function packPeople(people: MapPerson[], s: TimeScale, measure: Measure, fonts: MapFonts, dense: boolean) {
  const r0 = dense ? 4 : 22;
  const items: Packed[] = people.map((p) => {
    const bx = s.clampX(s.x(p.birth));
    const dx = s.clampX(s.x(p.death));
    const full = measure(p.label, fonts.personName);
    const label = !dense || dx - bx >= full + r0 + 30 ? p.label : p.short;
    const lw = label === p.label ? full : measure(p.short, fonts.personName);
    const yw = dense ? 0 : measure(`${p.birth}–${p.death}`, fonts.personYears);
    const nameEnd = bx + r0 + 8 + lw;
    const yearsIn = dense || dx - nameEnd >= yw + 26;
    const end = yearsIn ? Math.max(dx, nameEnd) + 6 : Math.max(dx, nameEnd) + 8 + yw + 12;
    return { id: p.id, p, bx, dx, label, yearsIn, occ: [bx - r0 - 6, end], lane: 0 };
  });
  const lanes: number[] = [];
  [...items]
    .sort((a, b) => a.p.birth - b.p.birth)
    .forEach((it) => {
      let k = lanes.findIndex((end) => end < it.occ[0]);
      if (k < 0) {
        k = lanes.length;
        lanes.push(0);
      }
      lanes[k] = it.occ[1];
      it.lane = k;
    });
  return { items, lanes: lanes.length };
}

/* ---------- «булавки» ---------- */

export type PinItem = { x: number; row: number; bx: number };
type PinOpts<T> = { maxRows: number; maxShift: number; left: number; right: number; block: (it: T, bx: number) => [number, number] };

// Блок (значок + подпись) — в первом свободном ряду рядом с годом. Кандидаты (ряд, сдвиг)
// по цене |сдвиг| + ряд×45. Ножка идёт от года по кромке к блоку, затем вниз: она не пересекает
// блоки верхних рядов, блок не пересекает чужие ножки. Нет места — row = −1, только отметка года.
// Возвращает число занятых рядов (не меньше 1).
export function pins<T extends PinItem>(items: T[], o: PinOpts<T>): number {
  const rows: [number, number][][] = Array.from({ length: o.maxRows }, () => []);
  const stems: { x: number; row: number }[] = [];
  const cands: { r: number; s: number; cost: number }[] = [];
  for (let r = 0; r < o.maxRows; r++) for (let s = -o.maxShift; s <= o.maxShift; s += 12) cands.push({ r, s, cost: Math.abs(s) + r * 45 });
  cands.sort((a, b) => a.cost - b.cost);
  items.forEach((it) => {
    it.row = -1;
    for (const { r, s } of cands) {
      const bx = it.x + s;
      const [a, b] = o.block(it, bx);
      if (a < o.left - 8 || b > o.right) continue;
      if (rows[r].some(([c, d]) => b > c && a < d)) continue;
      if (r > 0 && rows.slice(0, r).some((row) => row.some(([c, d]) => bx > c - 3 && bx < d + 3))) continue;
      if (stems.some((st) => st.row > r && st.x > a - 3 && st.x < b + 3)) continue;
      rows[r].push([a, b]);
      stems.push({ x: bx, row: r });
      it.row = r;
      it.bx = bx;
      break;
    }
  });
  return Math.max(1, rows.filter((r) => r.length).length);
}

export type Line = { t: string; w: number };

// Перенос подписи по словам: не больше двух строк, вторая с многоточием, если не влезло.
export function wrap(title: string, max: number, font: string, measure: Measure): Line[] {
  const lines = [""];
  title.split(" ").forEach((w) => {
    const last = lines[lines.length - 1];
    const c = (last + " " + w).trim();
    if (measure(c, font) > max && last) lines.push(w);
    else lines[lines.length - 1] = c;
  });
  return lines.slice(0, 2).map((t, i) => {
    const s = i === 1 && lines.length > 2 ? t + "…" : t;
    return { t: s, w: measure(s, font) };
  });
}

/* ---------- труды и идеи ---------- */

export type WorkPlace = {
  id: string;
  work: MapWork;
  x: number; // год — отметка на кромке страты
  row: number; // −1 — без подписи, только отметка
  bx: number; // центр значка и подписи
  y: number; // верх значка (при row ≥ 0)
  lines: Line[];
  role: ColorRole | null; // цвет автора в выборе
  primary: boolean;
};

// Ключевые труды без выбора — самые весомые: треть видимых (подписи остальных — по выбору).
export const KEY_SHARE = 1 / 3;

function keyWorks(works: MapWork[]): Set<string> {
  const n = Math.ceil(works.length * KEY_SHARE);
  return new Set(
    [...works]
      .filter((w) => w.weight > 0)
      .sort((a, b) => b.weight - a.weight || a.year - b.year)
      .slice(0, n)
      .map((w) => w.id),
  );
}

type WorkPin = WorkPlace & { w: number; key: boolean };

function planWorks(
  v: Visible,
  rel: Related | null,
  s: TimeScale,
  measure: Measure,
  fonts: MapFonts,
  dense: boolean,
  maxRows: number,
  right: number,
  all = false,
) {
  const vis = v.works.filter((w) => !rel || !rel.works || rel.works.has(w.id)).sort((a, b) => a.year - b.year);
  const keys = keyWorks(v.works);
  const items: WorkPin[] = vis.map((w) => ({
    id: w.id,
    work: w,
    x: s.x(w.year),
    row: -1,
    bx: s.x(w.year),
    y: 0,
    lines: [],
    w: 0,
    key: keys.has(w.id),
    role: rel ? ((w.author != null ? rel.people.get(w.author) : undefined) ?? "other") : null,
    primary: !!rel && rel.primary === w.id,
  }));
  const cand = items
    .filter((it) => rel || all || it.key)
    .sort((a, b) => Number(b.primary) - Number(a.primary) || Number(b.key) - Number(a.key) || b.work.weight - a.work.weight || a.work.year - b.work.year);
  cand.forEach((it) => {
    const font = rel ? fonts.workActive : it.work.kind === "work" ? fonts.workTitle : fonts.conceptTitle;
    it.lines = wrap(rel ? `${it.work.label}, ${it.work.year}` : it.work.label, dense ? 150 : 170, font, measure);
    it.w = Math.max(...it.lines.map((l) => l.w));
  });
  const rows = pins(cand, {
    maxRows,
    maxShift: rel ? 210 : 84,
    left: s.left,
    right,
    block: (it, bx) => [bx - Math.max(it.w, 20) / 2 - 8, bx + Math.max(it.w, 20) / 2 + 8],
  });
  return { items, rows: cand.some((c) => c.row >= 0) ? rows : 0 };
}

/* ---------- события ---------- */

export type EventPlace = {
  id: string;
  event: MapEvent;
  x: number; // кольцо стоит точно на годе
  row: number; // −1 — без подписи: засечка на верхней кромке страты
  side: 1 | -1; // подпись справа или слева от кольца
  y: number; // центр кольца
  focus: boolean; // в фокусе выбора (иначе приглушено)
};

function planEvents(v: Visible, rel: Related | null, s: TimeScale, measure: Measure, fonts: MapFonts, maxRows: number, right: number) {
  const items: (EventPlace & { w: number })[] = [...v.events]
    .sort((a, b) => a.year - b.year)
    .map((e) => ({
      id: e.id,
      event: e,
      x: s.x(e.year),
      row: -1,
      side: 1,
      y: 0,
      focus: !rel || !rel.events || rel.events.has(e.id),
      w: measure(`${e.year} ${e.label}`, fonts.eventText),
    }));
  const order = [...items].sort((a, b) => Number(!a.focus || !rel?.events) - Number(!b.focus || !rel?.events) || a.event.year - b.event.year);
  const rows: [number, number][][] = Array.from({ length: maxRows }, () => []);
  order.forEach((e) => {
    for (let r = 0; r < maxRows && e.row < 0; r++)
      for (const side of [1, -1] as const) {
        const a = side > 0 ? e.x - 7 : e.x - 12 - e.w - 6;
        const b = side > 0 ? e.x + 12 + e.w + 6 : e.x + 7;
        if (a < s.left - 8 || b > right || rows[r].some(([c, d]) => b > c && a < d)) continue;
        rows[r].push([a, b]);
        e.row = r;
        e.side = side;
        break;
      }
  });
  return { items, rows: Math.max(1, rows.filter((r) => r.length).length) };
}

/* ---------- эпохи ---------- */

export type EraPlace = { id: string; x1: number; x2: number; labelFits: boolean; active: boolean };

/* ---------- линии влияний ---------- */

export type ThreadPlace = {
  linkId: string;
  role: ColorRole | null; // null — тихая линия без выбора
  dashed: boolean; // достроена моделью
  d: string; // путь SVG (кубическая кривая), от верха страты людей
  end: { x: number; y: number }; // точка у ученика
  mid: { x: number; y: number }; // середина — подсказка и цель нажатия
};

export const QUIET_THREADS_MAX = 15; // без выбора линии видны, только если их немного

/* ---------- страты ---------- */

export type Band = { key: Stratum; top: number; bot: number; collapsed: boolean };

export type PeopleGeometry = {
  lanes: number;
  laneH: number;
  band: number; // толщина ленты
  rx: number; // медальон (обычный режим)
  ry: number;
};

export type MapLayout = {
  width: number;
  height: number; // фактическая высота кадра (≤ доступной, если страты свёрнуты)
  dense: boolean;
  scale: TimeScale;
  bands: Record<Stratum, Band>;
  axisY: number;
  people: PersonPlace[];
  geometry: PeopleGeometry;
  peopleScroll: { contentHeight: number; viewportHeight: number } | null;
  works: WorkPlace[];
  events: EventPlace[];
  eras: EraPlace[];
  threads: ThreadPlace[];
  fonts: MapFonts;
};

export type LayoutInput = {
  data: MapData;
  vis: Visible;
  rel: Related | null;
  sel: string | null;
  width: number;
  height: number; // доступная высота кадра: страты + ось
  collapsed: readonly Stratum[];
  measure: Measure;
  dense?: boolean; // по умолчанию — больше 12 персон в разделе (не зависит от фильтра)
  options?: Partial<LayoutOptions>;
};

const cubic = (P: { x: number; y: number }[], t: number) => {
  const u = 1 - t;
  return {
    x: u * u * u * P[0].x + 3 * u * u * t * P[1].x + 3 * u * t * t * P[2].x + t * t * t * P[3].x,
    y: u * u * u * P[0].y + 3 * u * u * t * P[1].y + 3 * u * t * t * P[2].y + t * t * t * P[3].y,
  };
};

const r1 = (n: number) => Math.round(n * 10) / 10;

export function layout(input: LayoutInput): MapLayout {
  const { data, vis: v, rel, sel, measure } = input;
  const o = { ...DEFAULT_OPTIONS, ...input.options };
  const dense = input.dense ?? data.people.length > DENSE_PEOPLE;
  const fonts = mapFonts(dense);
  const W = input.width;
  const right = W - 6; // правая граница подписей
  const s = timeScale(v.range, o.plotLeft, W - o.plotRightPad);
  const on = (k: Stratum) => !input.collapsed.includes(k);
  const COLL = o.collapsedHeight;
  const body = Math.max(0, input.height - o.top - o.axisHeight);

  // дорожки людей
  const packed = packPeople(v.people, s, measure, fonts, dense);
  const LANES = Math.max(1, packed.lanes);
  const laneMin = dense ? 27 : 56;
  const peopleNeed = 30 + LANES * laneMin;
  // В низком кадре (окно 1024×576) людям хватает двух видимых дорожек — остальные прокручиваются.
  const peopleMin = on("people") ? 30 + laneMin * Math.min(LANES, body < 320 ? 2 : 3) : COLL;

  // доли: события — до 20% высоты, труды — до 38%; если люди свёрнуты, труды берут остаток
  const erasH = on("eras") ? ERA_H : COLL;
  const eventsCap = Math.max(20 + E_ROW + 4, body * 0.2);
  const worksCap = on("people")
    ? Math.max(22 + W_ROW + 6, body * 0.38)
    : body - erasH - COLL - (on("events") ? 20 + E_ROW + 4 : COLL);
  const eventsMaxRows = Math.max(1, Math.min(dense ? 4 : 2, Math.floor((eventsCap - 24) / E_ROW)));
  const ep = planEvents(v, rel, s, measure, fonts, on("events") ? eventsMaxRows : 0, right);
  const eventsH = on("events") ? 20 + ep.rows * E_ROW + 4 : COLL;
  let worksMaxRows = Math.max(1, Math.min(on("people") ? (dense ? (rel ? 4 : 3) : 2) : 8, Math.floor((worksCap - 28) / W_ROW)));
  // Дорожек мало (фильтр) — люди не займут страту даже растянутыми: лишние ряды отдаются
  // подписям трудов, но не больше WORKS_ROWS_SPARE.
  let allWorks = false; // подписывать не только ключевые труды
  if (on("people") && dense) {
    const peopleFit = 30 + LANES * laneMin * LANE_STRETCH_DENSE;
    const spare = body - eventsH - erasH - peopleFit - (22 + worksMaxRows * W_ROW + 6);
    if (spare > W_ROW) {
      worksMaxRows = Math.min(WORKS_ROWS_SPARE, worksMaxRows + Math.floor(spare / W_ROW));
      allWorks = true;
    }
  }
  const wp = planWorks(v, rel, s, measure, fonts, dense, on("works") ? worksMaxRows : 0, right, allWorks);

  const h: Record<Stratum, number> = {
    events: eventsH,
    eras: erasH,
    people: COLL,
    works: on("works") ? 22 + Math.max(wp.rows, 1) * W_ROW + 6 : COLL,
  };
  let peopleScroll: MapLayout["peopleScroll"] = null;
  let laneH = laneMin;
  if (on("people")) {
    const viewport = Math.max(peopleMin, body - h.events - h.eras - h.works);
    if (peopleNeed > viewport) {
      h.people = viewport;
      peopleScroll = { contentHeight: peopleNeed, viewportHeight: viewport };
    } else {
      // Естественная высота: дорожки растянуты до предела — в плотном разделе 1,3 минимальной,
      // в редком 2,4. Остаток кадра ниже делится между всеми развёрнутыми стратами.
      laneH = Math.min(laneMin * (dense ? LANE_STRETCH_DENSE : LANE_STRETCH), (viewport - 30) / LANES);
      h.people = 30 + LANES * laneH;
    }
  }
  // Полотно постоянного размера (правка владельца 2026-11-18): страты заполняют кадр целиком.
  // Свободная высота — от свёрнутых линз или коротких страт — делится между развёрнутыми
  // стратами пропорционально их высоте; ряды событий и трудов, дорожки людей и полоса эпох
  // растягиваются вместе со своей стратой, пустого низа не остаётся.
  const open = STRATA.filter((k) => on(k));
  const natural = open.reduce((sum, k) => sum + h[k], 0);
  const free = body - STRATA.reduce((sum, k) => sum + h[k], 0);
  let eRow = E_ROW;
  let wRow = W_ROW;
  if (free > 0.5 && natural > 0 && !peopleScroll) {
    const k = (natural + free) / natural;
    for (const key of open) h[key] *= k;
    if (on("events") && ep.rows > 0) eRow = (h.events - 24) / ep.rows;
    if (on("works") && wp.rows > 0) wRow = (h.works - 28) / wp.rows;
    if (on("people")) laneH = (h.people - 30) / LANES;
  }
  const bands = {} as Record<Stratum, Band>;
  let y = o.top;
  STRATA.forEach((k) => {
    bands[k] = { key: k, top: y, bot: y + h[k], collapsed: !on(k) };
    y += h[k];
  });
  const axisY = y;

  // геометрия лент (как в макете)
  const ry = dense ? 4 : Math.min(27, laneH * 0.4);
  const rx = dense ? 4 : ry * 0.82;
  const BAND = dense ? Math.min(18, laneH * 0.66) : Math.min(24, Math.max(14, laneH * 0.46));
  const authorSel = rel && rel.type === "work" ? rel.obj.author : null;
  const people: PersonPlace[] = packed.items.map((it) => {
    const role = rel ? (rel.people.get(it.id) ?? null) : null;
    const strong = role != null && role !== "other";
    const medallion = dense && (sel === it.id || authorSel === it.id);
    const nameX = dense ? (medallion ? it.bx + 13 + 7 : it.bx + 10) : it.bx + rx + 8;
    const labelEnd = nameX + measure(it.label, strong ? fonts.selName : fonts.personName);
    return {
      id: it.id,
      bx: it.bx,
      dx: it.dx,
      lane: it.lane,
      y: 20 + (it.lane + 0.5) * laneH,
      label: it.label,
      nameX,
      labelEnd,
      yearsIn: it.yearsIn,
      yearsX: it.yearsIn ? it.dx - BAND / 2 : Math.max(it.dx, labelEnd) + 8,
      role,
      dim: !!rel && role == null,
      medallion,
    };
  });

  // труды и события — координаты в кадре
  const works: WorkPlace[] = wp.items.map(({ w: _w, key: _k, ...it }) => ({ ...it, y: it.row >= 0 ? bands.works.top + 22 + it.row * wRow : bands.works.top }));
  const events: EventPlace[] = ep.items.map(({ w: _w, ...e }) => ({ ...e, y: e.row >= 0 ? bands.events.top + 20 + e.row * eRow : bands.events.top + 5 }));
  const eras: EraPlace[] = v.eras.map((e) => {
    const x1 = s.clampX(s.x(e.from));
    const x2 = s.clampX(s.x(e.to));
    return { id: e.id, x1, x2, labelFits: measure(e.label, fonts.eraText) <= x2 - x1 - 12, active: !!rel && rel.era?.id === e.id };
  });

  // линии влияний: от учителя (object) к ученику (subject); у каждой ленты концы разводятся по слотам
  const byId = new Map(people.map((p) => [p.id, p]));
  const pById = new Map(v.people.map((p) => [p.id, p]));
  const shown: { link: Visible["links"][number]; role: ColorRole | null }[] = !on("people")
    ? []
    : rel
      ? rel.links
      : v.links.length > QUIET_THREADS_MAX
        ? []
        : v.links.map((link) => ({ link, role: null }));
  const drawn = shown.filter((x) => byId.has(x.link.subject) && byId.has(x.link.object) && x.link.subject !== x.link.object);
  // Концы линии — на свободной части ленты: после подписи имени и до годов (или конца ленты).
  // Линия выходит из ленты учителя и входит в ленту ученика почти отвесно (касательные
  // вертикальны), поэтому не тянется вдоль чужих лент и вдоль ленты выбранного; середина
  // кривой между соседними дорожками ложится в промежуток между ними. Если концы обеих
  // лент перекрываются по времени — линия отвесная. Концы у одной кромки ленты разводятся
  // по слотам (шаг SLOT), в порядке x противоположных концов — чтобы линии не перекрещивались.
  const SLOT = 9;
  const span = (p: PersonPlace) => {
    const m = pById.get(p.id)!;
    const lo = p.labelEnd + 10;
    const yw = !dense && p.yearsIn ? measure(`${m.birth}–${m.death}`, fonts.personYears) + 8 : 0;
    const hi = p.dx - 8 - yw;
    // подпись длиннее ленты — конец у точки в начале ленты, до подписи
    if (hi < lo) return { lo: p.bx + BAND / 2, hi: p.bx + BAND / 2 };
    return { lo, hi };
  };
  type End = { key: string; x: number; other: number; lo: number; hi: number };
  const plans = drawn.map(({ link, role }) => {
    const sp = byId.get(link.object)!; // учитель
    const tp = byId.get(link.subject)!; // ученик
    const sm = pById.get(link.object)!;
    const sR = span(sp);
    const tR = span(tp);
    const via = s.x(Math.min(sm.death - 5, sm.birth + 40)); // в макете — год влияния
    const lo = Math.max(sR.lo, tR.lo);
    const hi = Math.min(sR.hi, tR.hi);
    let ax: number;
    let bx: number;
    if (lo <= hi) ax = bx = Math.min(Math.max(via, lo), hi);
    else if (sR.hi < tR.lo) [ax, bx] = [sR.hi, tR.lo];
    else [ax, bx] = [sR.lo, tR.hi];
    // кромка: к другой ленте; на одной дорожке — обе верхние (дуга над дорожкой)
    const same = sp.lane === tp.lane;
    const aSide = same ? -1 : tp.y > sp.y ? 1 : -1;
    const bSide = same ? -1 : -aSide;
    const A: End = { key: `${sp.id}:${aSide}`, x: ax, other: bx, lo: sR.lo, hi: sR.hi };
    const B: End = { key: `${tp.id}:${bSide}`, x: bx, other: ax, lo: tR.lo, hi: tR.hi };
    return { link, role, sp, tp, aSide, bSide, same, A, B };
  });
  const groups = new Map<string, End[]>();
  plans.forEach(({ A, B }) => [A, B].forEach((e) => groups.set(e.key, [...(groups.get(e.key) ?? []), e])));
  groups.forEach((list) => {
    list.sort((a, b) => a.x - b.x || a.other - b.other);
    for (let k = 1; k < list.length; k++) list[k].x = Math.max(list[k].x, list[k - 1].x + SLOT);
    const over = list[list.length - 1].x - list[0].hi;
    if (over > 0) list.forEach((e) => (e.x = Math.max(e.lo, e.x - over)));
  });
  const threads: ThreadPlace[] = plans.map(({ link, role, sp, tp, aSide, bSide, same, A: a, B: b }) => {
    const A = { x: a.x, y: sp.y + (aSide * BAND) / 2 };
    const B = { x: b.x, y: tp.y + (bSide * BAND) / 2 };
    const dy = B.y - A.y;
    const lift = same ? -Math.max(laneH * 0.55, 10) : 0;
    const P = [A, { x: A.x, y: A.y + dy * 0.5 + lift }, { x: B.x, y: B.y - dy * 0.5 + lift }, B];
    return {
      linkId: link.id,
      role,
      dashed: link.generated,
      d: `M${r1(A.x)},${r1(A.y)} C${r1(P[1].x)},${r1(P[1].y)} ${r1(P[2].x)},${r1(P[2].y)} ${r1(B.x)},${r1(B.y)}`,
      end: B,
      mid: cubic(P, 0.5),
    };
  });

  return {
    width: W,
    height: axisY + o.axisHeight,
    dense,
    scale: s,
    bands,
    axisY,
    people,
    geometry: { lanes: packed.lanes, laneH, band: BAND, rx, ry },
    peopleScroll,
    works,
    events,
    eras,
    threads,
    fonts,
  };
}

// Приближённый измеритель без DOM (тесты, сервер): средняя ширина знака от кегля.
export const approxMeasure: Measure = (text, font) => {
  const m = /(\d+(?:\.\d+)?)px/.exec(font);
  const size = m ? Number(m[1]) : 14;
  return text.length * size * (/italic/.test(font) ? 0.5 : 0.55);
};
