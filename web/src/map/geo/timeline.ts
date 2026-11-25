// Глобус во времени (geo-timeline): где персона в год T, что видно на глобусе, год по
// умолчанию и ближайший год с отметками. Чистые функции без DOM, без d3 и без Date —
// правило «где в год T» живёт только здесь (сервер годы жизни не подставляет).
//
// Условности времени — константы этого модуля, они же объяснены в легенде глобуса:
// - ADULT_AGE — начало деятельности без даты и «год связи» (влияние воспринимает взрослый);
// - TRAIL — сколько лет после смерти, события или года связи отметка ещё видна, бледнея;
//   границы включительно;
// - пределы отметок, дуг и подписей; при избытке остаются самые весомые.

import { midLife } from "../model";
import type { MapEvent, MapLink, MapPerson } from "../types";
import type { GeoLayer, GeoPlace, GeoPlacement } from "./api";

export const ADULT_AGE = 20;
export const TRAIL = 150;
export const MAX_PLACES = 300;
export const MAX_LINKS = 200;
export const MAX_LABELS = 12;
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

// Главное место персоны — конец дуг влияния: первое activity (по началу), иначе birth,
// иначе запись без вида. Одно на все годы: дуги не прыгают при проигрывании.
export function mainPlace(p: Life, rows: GeoPlacement[]): GeoPlacement | null {
  const pick = (f: (r: GeoPlacement) => boolean) =>
    rows.filter(f).sort((a, b) => startOf(p, a) - startOf(p, b) || byId(a, b))[0] ?? null;
  return pick((r) => r.role === "activity") ?? pick((r) => r.role === "birth") ?? pick((r) => r.role == null);
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

export type SceneLink = { id: string; link: MapLink; from: GeoPlace; to: GeoPlace; age: number; weight: number };

export type Scene = {
  year: number;
  places: ScenePlace[]; // не больше MAX_PLACES, по убыванию людей, затем по id
  totalPlaces: number;
  links: SceneLink[]; // не больше MAX_LINKS, по весу концов, затем по id связи
  totalLinks: number;
  where: Map<string, string>; // персона или событие → место на год T
};

export type SceneInput = { people: MapPerson[]; events: MapEvent[]; links: MapLink[] };

// Что видно на год T. Персона — с рождения до смерти + TRAIL, событие — с года + TRAIL,
// связь — с года связи + TRAIL (границы включительно). Связь без главного места у одного
// из концов не рисуется и не считается.
export function visibleAt(model: GeoModel, input: SceneInput, T: number): Scene {
  type Acc = { place: GeoPlace; people: string[]; events: string[]; age: number; flags: boolean[] };
  const acc = new Map<string, Acc>();
  const where = new Map<string, string>();
  const add = (placeId: string, kind: "people" | "events", id: string, age: number, generated: boolean) => {
    const place = model.places.get(placeId);
    if (!place) return;
    let a = acc.get(placeId);
    if (!a) acc.set(placeId, (a = { place, people: [], events: [], age, flags: [] }));
    a[kind].push(id);
    a.age = Math.min(a.age, age);
    a.flags.push(generated);
    where.set(id, placeId);
  };
  for (const p of input.people) {
    if (T < p.birth || T > p.death + TRAIL) continue;
    const r = whereAt(p, model.byEntity.get(p.id) ?? [], T);
    if (r) add(r.place, "people", p.id, Math.max(0, T - p.death), r.generated);
  }
  for (const e of input.events) {
    if (T < e.year || T > e.year + TRAIL) continue;
    const r = (model.byEntity.get(e.id) ?? []).filter((x) => x.role === "event").sort(byId)[0];
    if (r) add(r.place, "events", e.id, T - e.year, r.generated);
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

  const people = new Map(input.people.map((p) => [p.id, p]));
  const mains = new Map<string, GeoPlace | null>();
  const main = (p: MapPerson) => {
    if (!mains.has(p.id)) {
      const r = mainPlace(p, model.byEntity.get(p.id) ?? []);
      mains.set(p.id, r ? (model.places.get(r.place) ?? null) : null);
    }
    return mains.get(p.id)!;
  };
  const links: SceneLink[] = [];
  for (const l of input.links) {
    const student = people.get(l.subject);
    const teacher = people.get(l.object);
    if (!student || !teacher) continue;
    const y = linkYear(student);
    if (T < y || T > y + TRAIL) continue;
    const from = main(teacher);
    const to = main(student);
    if (!from || !to) continue;
    links.push({ id: l.id, link: l, from, to, age: T - y, weight: student.weight + teacher.weight });
  }
  links.sort((a, b) => b.weight - a.weight || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return {
    year: T,
    places: all.slice(0, MAX_PLACES),
    totalPlaces: all.length,
    links: links.slice(0, MAX_LINKS),
    totalLinks: links.length,
    where,
  };
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
