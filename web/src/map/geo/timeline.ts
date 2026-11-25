// Глобус во времени (geo-timeline): где персона в год T, что видно на глобусе, год по
// умолчанию и ближайший год с отметками. Чистые функции без DOM, без d3 и без Date —
// правило «где в год T» живёт только здесь (сервер годы жизни не подставляет).
//
// Условности времени — константы этого модуля, они же объяснены в легенде глобуса:
// - ADULT_AGE — начало деятельности без даты и «год связи» (влияние воспринимает взрослый);
// - TRAIL — сколько лет после смерти, события или года связи отметка ещё видна, бледнея;
//   границы включительно;
// - пределы мест и дуг; при избытке остаются самые весомые.

import { midLife } from "../model";
import type { MapEvent, MapLink, MapPerson } from "../types";
import type { GeoLayer, GeoPlace, GeoPlacement } from "./api";

export const ADULT_AGE = 20;
export const TRAIL = 150;
export const MAX_PLACES = 300;
export const MAX_LINKS = 200;
export const MIN_OPACITY = 0.15;

export type GeoModel = {
  places: Map<string, GeoPlace>;
  byEntity: Map<string, GeoPlacement[]>;
  unplaced: string[];
};

const models = new WeakMap<GeoLayer, GeoModel>();

// Указатели слоя: места по id и размещения по сущности (с координатами места). Один раз
// на ответ (кэш по ссылке).
export function geoModel(layer: GeoLayer): GeoModel {
  let m = models.get(layer);
  if (!m) {
    const places = new Map(layer.places.map((p) => [p.id, p]));
    const byEntity = new Map<string, GeoPlacement[]>();
    for (const p of layer.placements) {
      if (!places.has(p.place)) continue; // без координат места размещения нет
      const list = byEntity.get(p.entity);
      if (list) list.push(p);
      else byEntity.set(p.entity, [p]);
    }
    m = { places, byEntity, unplaced: layer.unplaced };
    models.set(layer, m);
  }
  return m;
}

type Life = Pick<MapPerson, "birth" | "death">;

const ROLE_RANK: Record<string, number> = { birth: 0, activity: 1, residence: 1, death: 2 };
const byId = (a: GeoPlacement, b: GeoPlacement) => (a.statement < b.statement ? -1 : a.statement > b.statement ? 1 : 0);

// Записи без вида используются, только если у персоны нет записей с видом.
function effective(rows: GeoPlacement[]): GeoPlacement[] {
  const withRole = rows.filter((r) => r.role != null && r.role !== "event");
  return withRole.length ? withRole : rows.filter((r) => r.role == null);
}

const isInterval = (r: GeoPlacement) => (r.role === "activity" || r.role === "residence" || r.role == null) && r.from != null && r.to != null;

// Начало места: рождение — год рождения; деятельность без времени — рождение + ADULT_AGE;
// смерть — год смерти; запись со временем — её начало; проживание и запись без вида без
// времени — рождение (проживание всю жизнь).
export function startOf(p: Life, r: GeoPlacement): number {
  if (r.role === "birth") return p.birth;
  if (r.role === "death") return p.death;
  if (r.from != null) return r.from;
  if (r.role === "activity") return p.birth + ADULT_AGE;
  return p.birth;
}

// Где персона в год T (если она вообще видна — решает visibleAt):
// 1. место activity/residence, чей интервал содержит T (границы включительно; из
//    нескольких — с более поздним началом);
// 2. иначе последнее место, начавшееся не позже T;
// 3. записи без вида и без времени — только если записей с видом нет: проживание с рождения.
export function whereAt(p: Life, rows: GeoPlacement[], T: number): GeoPlacement | null {
  const list = effective(rows);
  let best: GeoPlacement | null = null;
  for (const r of list) {
    if (!isInterval(r) || T < r.from! || T > r.to!) continue;
    if (!best || r.from! > best.from! || (r.from === best.from && byId(r, best) < 0)) best = r;
  }
  if (best) return best;
  // Из начавшихся — самое позднее начало; в один год смерть позже деятельности, та —
  // позже рождения; затем по id утверждения.
  const rank = (r: GeoPlacement) => ROLE_RANK[r.role ?? ""] ?? 1;
  let bestStart = -Infinity;
  for (const r of list) {
    const s = startOf(p, r);
    if (s > T) continue;
    const order = best ? s - bestStart || rank(r) - rank(best) || byId(best, r) : 1;
    if (order > 0) {
      best = r;
      bestStart = s;
    }
  }
  return best;
}

// Первый год, с которого у персоны есть место (null — мест нет).
export function firstPlacedYear(p: Life, rows: GeoPlacement[]): number | null {
  const list = effective(rows);
  if (!list.length) return null;
  return Math.min(...list.map((r) => startOf(p, r)));
}

// Год связи «subject испытал влияние object»: рождение ученика + ADULT_AGE.
export const linkYear = (student: Life): number => student.birth + ADULT_AGE;

// Непрозрачность по возрасту: 1 у живого, линейно до MIN_OPACITY на конце TRAIL.
export const opacity = (age: number): number => Math.max(MIN_OPACITY, 1 - ((1 - MIN_OPACITY) * Math.max(0, age)) / TRAIL);

export const clampYear = (y: number, win: [number, number]): number => Math.min(win[1], Math.max(win[0], Math.round(y)));

export type ScenePlace = {
  id: string;
  label: string;
  lat: number;
  lon: number;
  people: string[]; // персоны в этом месте на год T (порядок — по году рождения)
  events: string[];
  age: number; // наименьший возраст людей и событий места
  unverified: boolean; // все показанные размещения достроены моделью
};

// Персона на год T — медальон глобуса (rework-globe-political-map). rank — место персоны
// внутри своего места по весу (0 — самая весомая, при равенстве — по id), placeIndex —
// порядок её места в сцене: раскладка кладёт по (rank, placeIndex).
export type ScenePerson = {
  id: string;
  place: string;
  lat: number;
  lon: number;
  age: number;
  generated: boolean; // размещение на год T достроено моделью
  row: GeoPlacement;
  weight: number;
  rank: number;
  placeIndex: number;
};

export type SceneEvent = { id: string; place: string; lat: number; lon: number; age: number; generated: boolean; placeIndex: number };

// Связь на год T: from — учитель (object), to — ученик (subject), обе персоны в сцене.
export type SceneLink = { id: string; link: MapLink; from: string; to: string; age: number; weight: number };

export type Scene = {
  year: number;
  places: ScenePlace[]; // не больше MAX_PLACES, по убыванию людей, затем по id
  totalPlaces: number;
  persons: ScenePerson[]; // персоны мест сцены, по (rank, placeIndex, id)
  events: SceneEvent[]; // события мест сцены, по (placeIndex, id)
  links: SceneLink[]; // не больше MAX_LINKS, по весу концов, затем по id связи
  totalLinks: number;
  where: Map<string, string>; // персона или событие → место на год T
};

export type SceneInput = { people: MapPerson[]; events: MapEvent[]; links: MapLink[] };

// Что видно на год T. Персона — с рождения до смерти + TRAIL, событие — с года + TRAIL,
// связь — с года связи + TRAIL (границы включительно) и только если обе персоны в сцене
// (видны и их место среди мест сцены); иначе не рисуется и не считается.
export function visibleAt(model: GeoModel, input: SceneInput, T: number): Scene {
  type Acc = { place: GeoPlace; people: string[]; events: string[]; age: number; flags: boolean[] };
  type Who = { id: string; row: GeoPlacement; age: number };
  const acc = new Map<string, Acc>();
  const where = new Map<string, string>();
  const who = new Map<string, { people: Who[]; events: Who[] }>();
  const add = (row: GeoPlacement, kind: "people" | "events", id: string, age: number) => {
    const place = model.places.get(row.place);
    if (!place) return;
    let a = acc.get(row.place);
    if (!a) {
      acc.set(row.place, (a = { place, people: [], events: [], age, flags: [] }));
      who.set(row.place, { people: [], events: [] });
    }
    a[kind].push(id);
    a.age = Math.min(a.age, age);
    a.flags.push(row.generated);
    who.get(row.place)![kind].push({ id, row, age });
    where.set(id, row.place);
  };
  for (const p of input.people) {
    if (T < p.birth || T > p.death + TRAIL) continue;
    const r = whereAt(p, model.byEntity.get(p.id) ?? [], T);
    if (r) add(r, "people", p.id, Math.max(0, T - p.death));
  }
  for (const e of input.events) {
    if (T < e.year || T > e.year + TRAIL) continue;
    const r = (model.byEntity.get(e.id) ?? []).filter((x) => x.role === "event").sort(byId)[0];
    if (r) add(r, "events", e.id, T - e.year);
  }
  const all: ScenePlace[] = [...acc.values()].map((a) => ({
    id: a.place.id,
    label: a.place.label,
    lat: a.place.lat,
    lon: a.place.lon,
    people: a.people,
    events: a.events,
    age: a.age,
    unverified: a.flags.length > 0 && a.flags.every(Boolean),
  }));
  all.sort((a, b) => b.people.length - a.people.length || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const places = all.slice(0, MAX_PLACES);

  const people = new Map(input.people.map((p) => [p.id, p]));
  const cmpId = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);
  const persons: ScenePerson[] = [];
  const events: SceneEvent[] = [];
  places.forEach((sp, placeIndex) => {
    const w = who.get(sp.id)!;
    const ranked = [...w.people].sort((a, b) => (people.get(b.id)?.weight ?? 0) - (people.get(a.id)?.weight ?? 0) || cmpId(a.id, b.id));
    ranked.forEach((x, rank) =>
      persons.push({
        id: x.id,
        place: sp.id,
        lat: sp.lat,
        lon: sp.lon,
        age: x.age,
        generated: x.row.generated,
        row: x.row,
        weight: people.get(x.id)?.weight ?? 0,
        rank,
        placeIndex,
      }),
    );
    [...w.events]
      .sort((a, b) => cmpId(a.id, b.id))
      .forEach((x) => events.push({ id: x.id, place: sp.id, lat: sp.lat, lon: sp.lon, age: x.age, generated: x.row.generated, placeIndex }));
  });
  persons.sort((a, b) => a.rank - b.rank || a.placeIndex - b.placeIndex || cmpId(a.id, b.id));
  const inScene = new Set(persons.map((p) => p.id));

  const links: SceneLink[] = [];
  for (const l of input.links) {
    const student = people.get(l.subject);
    const teacher = people.get(l.object);
    if (!student || !teacher) continue;
    const y = linkYear(student);
    if (T < y || T > y + TRAIL) continue;
    if (!inScene.has(teacher.id) || !inScene.has(student.id)) continue;
    links.push({ id: l.id, link: l, from: teacher.id, to: student.id, age: T - y, weight: student.weight + teacher.weight });
  }
  links.sort((a, b) => b.weight - a.weight || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return {
    year: T,
    places,
    totalPlaces: all.length,
    persons,
    events,
    links: links.slice(0, MAX_LINKS),
    totalLinks: links.length,
    where,
  };
}

// Годы в месте (панель «Где в <год> году»): наибольший непрерывный отрезок лет в пределах
// жизни, на котором whereAt даёт ту же запись, что в год T; T после смерти — отрезок,
// содержащий год смерти, и after=true. Правило места — то же whereAt, без второй копии.
export function stayAt(p: Life, rows: GeoPlacement[], T: number): { row: GeoPlacement; from: number; to: number; after: boolean } | null {
  const row = whereAt(p, rows, T);
  if (!row) return null;
  const at = Math.max(p.birth, Math.min(T, p.death));
  const same = (y: number) => whereAt(p, rows, y) === row;
  let from = at;
  let to = at;
  if (same(at)) {
    while (from - 1 >= p.birth && same(from - 1)) from -= 1;
    while (to + 1 <= p.death && same(to + 1)) to += 1;
  } else {
    // Запись года T не действует в год at (не должно случаться): отрезок по последнему году записи в жизни.
    let last: number | null = null;
    for (let y = p.death; y >= p.birth; y--) if (same(y)) { last = y; break; }
    if (last == null) return { row, from: T, to: T, after: T > p.death };
    from = to = last;
    while (from - 1 >= p.birth && same(from - 1)) from -= 1;
  }
  return { row, from, to, after: T > p.death };
}

// Год по умолчанию (без t в адресе): середина жизни выбранной персоны (та же формула, что
// dates.middle на сервере, — midLife карты), иначе год с наибольшим числом живых видимых
// персон (при равенстве — более ранний); всегда внутри окна.
export function defaultYear(people: MapPerson[], selected: MapPerson | null, win: [number, number]): number {
  if (selected) return clampYear(Math.floor(midLife(selected)), win);
  const [a, b] = win;
  const n = b - a + 1;
  if (n <= 0 || !people.length) return clampYear(a, win);
  const diff = new Int32Array(n + 1);
  for (const p of people) {
    const s = Math.max(a, p.birth);
    const e = Math.min(b, p.death);
    if (s > e) continue;
    diff[s - a] += 1;
    diff[e - a + 1] -= 1;
  }
  let best = a;
  let bestCount = -1;
  let cur = 0;
  for (let i = 0; i < n; i++) {
    cur += diff[i];
    if (cur > bestCount) {
      bestCount = cur;
      best = a + i;
    }
  }
  return best;
}

// Ближайший к T год окна, на котором видна хотя бы одна отметка; при равенстве — более
// ранний; null — отметок нет ни в один год окна.
export function nearestYear(model: GeoModel, input: SceneInput, T: number, win: [number, number]): number | null {
  const spans: [number, number][] = [];
  for (const p of input.people) {
    const first = firstPlacedYear(p, model.byEntity.get(p.id) ?? []);
    if (first != null) spans.push([Math.max(first, p.birth), p.death + TRAIL]);
  }
  for (const e of input.events) {
    if ((model.byEntity.get(e.id) ?? []).some((x) => x.role === "event")) spans.push([e.year, e.year + TRAIL]);
  }
  let best: number | null = null;
  for (const [s0, e0] of spans) {
    const s = Math.max(s0, win[0]);
    const e = Math.min(e0, win[1]);
    if (s > e) continue;
    const y = T < s ? s : T > e ? e : T;
    if (best == null || Math.abs(y - T) < Math.abs(best - T) || (Math.abs(y - T) === Math.abs(best - T) && y < best)) best = y;
  }
  return best;
}

// Лет на глобусе (размер отметки): √n людей, 4–12 px; место только с событиями — 4.
export const markRadius = (people: number): number => Math.min(12, Math.max(4, 4 * Math.sqrt(people)));
