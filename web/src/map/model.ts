// Модель карты раздела — перенос из макета desk-chart.js (docs/design/system/previews/graph-f02-lenses).
// Три механизма не смешиваются:
// - фильтр (visible) — какие объекты остаются: скрытые исчезают, дорожки перепаковываются;
// - выбор (related) — фокус: нерелевантные труды убираются, люди приглушаются, но читаются;
// - линза — какие страты развёрнуты (types.ts, toggleLens; высоты — layout.ts).
// Цвета здесь — имена ролей, а не значения: палитра — токены сцены (sel-self, sel-teacher…).

import type { Filter, MapData, MapEra, MapEvent, MapGroup, MapLink, MapPerson, MapWork } from "./types";

/* ---------- фильтр ---------- */

export type Visible = {
  range: [number, number]; // окно времени
  people: MapPerson[];
  works: MapWork[];
  events: MapEvent[];
  eras: MapEra[];
  groups: MapGroup[]; // группы, у которых остался хотя бы один видимый участник
  links: MapLink[];
};

export function visible(data: MapData, filter: Filter): Visible {
  const range = data.range ?? [0, 1];
  const from = filter.from ?? range[0];
  const to = filter.to ?? range[1];
  const gs = data.groups.filter((g) => filter.groups.includes(g.id));
  const people = data.people.filter(
    (p) =>
      (!gs.length || gs.some((g) => g.members.includes(p.id))) &&
      (!filter.roles.length || p.roles.some((r) => filter.roles.includes(r))) &&
      p.death >= from &&
      p.birth <= to,
  );
  const ids = new Set(people.map((p) => p.id));
  const known = index(data).people;
  // труд без автора на карте (автора нет или он вне области) виден, пока не фильтруют людей
  const authorShown = (w: MapWork) =>
    w.author != null && known.has(w.author) ? ids.has(w.author) : !gs.length && !filter.roles.length;
  return {
    range: [from, to],
    people,
    works: data.works.filter(
      (w) => authorShown(w) && (!filter.kinds.length || filter.kinds.includes(w.kind)) && w.year >= from && w.year <= to,
    ),
    events: data.events.filter(
      (e) => (!filter.ekinds.length || (e.kind != null && filter.ekinds.includes(e.kind))) && e.year >= from && e.year <= to,
    ),
    eras: data.eras.filter((e) => e.to > from && e.from < to),
    groups: data.groups.filter((g) => g.members.some((m) => ids.has(m))),
    links: data.links.filter((l) => ids.has(l.subject) && ids.has(l.object) && (!filter.verified || !l.generated)),
  };
}

// Фильтр что-то ограничивает (для строки «Показано N из M» и «Сбросить»).
export const isFiltered = (f: Filter): boolean =>
  f.from != null ||
  f.to != null ||
  f.verified ||
  f.groups.length > 0 ||
  f.roles.length > 0 ||
  f.kinds.length > 0 ||
  f.ekinds.length > 0;

/* ---------- поиск сущности по id ---------- */

export type EntityType = "person" | "work" | "event" | "era" | "group";

export type Found =
  | { type: "person"; obj: MapPerson }
  | { type: "work"; obj: MapWork }
  | { type: "event"; obj: MapEvent }
  | { type: "era"; obj: MapEra }
  | { type: "group"; obj: MapGroup };

// Указатели по id. Строятся один раз на ответ (кэш по ссылке на data).
export type Index = {
  people: Map<string, MapPerson>;
  works: Map<string, MapWork>;
  events: Map<string, MapEvent>;
  eras: Map<string, MapEra>;
  groups: Map<string, MapGroup>;
};

const indexCache = new WeakMap<MapData, Index>();

export function index(data: MapData): Index {
  let ix = indexCache.get(data);
  if (!ix) {
    const by = <T extends { id: string }>(a: T[]) => new Map(a.map((x) => [x.id, x]));
    ix = { people: by(data.people), works: by(data.works), events: by(data.events), eras: by(data.eras), groups: by(data.groups) };
    indexCache.set(data, ix);
  }
  return ix;
}

export function find(data: MapData, id: string): Found | null {
  const ix = index(data);
  const p = ix.people.get(id);
  if (p) return { type: "person", obj: p };
  const w = ix.works.get(id);
  if (w) return { type: "work", obj: w };
  const e = ix.events.get(id);
  if (e) return { type: "event", obj: e };
  const era = ix.eras.get(id);
  if (era) return { type: "era", obj: era };
  const g = ix.groups.get(id);
  if (g) return { type: "group", obj: g };
  return null;
}

/* ---------- выбор ---------- */

// Роль цвета: выбранный и его труды, учителя, ученики; для группы, эпохи, события —
// до шести самых значимых участников c1…c6, остальные участники — other.
export type ColorRole = "self" | "teacher" | "student" | "c1" | "c2" | "c3" | "c4" | "c5" | "c6" | "other";
export const PALETTE: readonly ColorRole[] = ["c1", "c2", "c3", "c4", "c5", "c6"];

// Строка расшифровки цветов: роль и персоны этой роли (по году рождения).
// Для self у персоны — сама персона (подпись «его труды»), у труда — автор.
export type LegendItem = { role: ColorRole; people: string[] };

export type Related = Found & {
  people: Map<string, ColorRole>; // участники выбора; кого нет — приглушены
  works: Set<string> | null; // показанные труды; null — все
  links: { link: MapLink; role: ColorRole }[]; // линии влияний выбранного
  era: MapEra | null; // эпоха выбранного (подсветка пролёта)
  events: Set<string> | null; // события в фокусе; null — все
  primary: string | null; // выбранный труд (обводка значка)
  legend: LegendItem[];
};

export const midLife = (p: MapPerson): number => (p.birth + p.death) / 2;

// Эпоха года: [from, to). Членство персоны в эпохе — по середине жизни.
export const eraOf = (eras: MapEra[], y: number): MapEra | null => eras.find((e) => y >= e.from && y < e.to) ?? null;

export const WORKS_AROUND_EVENT = 10; // труды «в пределах десяти лет» от события

export function related(data: MapData, v: Visible, sel: string | null): Related | null {
  const f = sel ? find(data, sel) : null;
  if (!f) return null;
  const people = new Map<string, ColorRole>();
  const links: Related["links"] = [];
  let works: Set<string> | null = null;
  let era: MapEra | null = null;
  let events: Set<string> | null = null;
  let primary: string | null = null;
  let legend: LegendItem[] = [];
  const byBirth = (ids: string[]) => {
    const ix = index(data).people;
    return [...ids].sort((a, b) => (ix.get(a)?.birth ?? 0) - (ix.get(b)?.birth ?? 0));
  };

  // группа участников: шесть самых весомых — свои цвета (по году рождения), прочие — other
  const group = (members: MapPerson[]) => {
    const top = [...members]
      .sort((a, b) => b.weight - a.weight || a.birth - b.birth)
      .slice(0, PALETTE.length)
      .sort((a, b) => a.birth - b.birth);
    members.forEach((p) => people.set(p.id, "other"));
    top.forEach((p, i) => people.set(p.id, PALETTE[i]));
    legend = top.map((p, i) => ({ role: PALETTE[i], people: [p.id] }));
    const rest = members.filter((p) => !top.includes(p));
    if (rest.length) legend.push({ role: "other", people: byBirth(rest.map((p) => p.id)) });
  };

  if (f.type === "person") {
    const p = f.obj;
    people.set(p.id, "self");
    // subject испытал влияние object: object — учитель subject
    v.links.forEach((l) => {
      if (l.subject === p.id && l.object !== p.id) {
        people.set(l.object, "teacher");
        links.push({ link: l, role: "teacher" });
      } else if (l.object === p.id && l.subject !== p.id) {
        people.set(l.subject, "student");
        links.push({ link: l, role: "student" });
      }
    });
    works = new Set(v.works.filter((w) => w.author === p.id).map((w) => w.id));
    era = eraOf(v.eras, midLife(p));
    events = new Set(v.events.filter((e) => e.year >= p.birth && e.year <= p.death).map((e) => e.id));
    const of = (r: ColorRole) => byBirth([...people].filter(([, c]) => c === r).map(([id]) => id));
    legend = [
      { role: "teacher" as const, people: of("teacher") },
      { role: "student" as const, people: of("student") },
      { role: "self" as const, people: [p.id] },
    ].filter((x) => x.people.length);
  } else if (f.type === "work") {
    const w = f.obj;
    primary = w.id;
    const author = w.author != null && index(data).people.has(w.author) ? w.author : null;
    if (author) {
      people.set(author, "self");
      legend = [{ role: "self", people: [author] }];
    }
    works = new Set(author ? v.works.filter((x) => x.author === author).map((x) => x.id) : []);
    works.add(w.id);
    era = eraOf(v.eras, w.year);
    events = new Set(v.events.filter((e) => Math.abs(e.year - w.year) <= WORKS_AROUND_EVENT).map((e) => e.id));
  } else if (f.type === "era") {
    const e = f.obj;
    group(v.people.filter((p) => midLife(p) >= e.from && midLife(p) < e.to));
    era = e;
    works = new Set(v.works.filter((w) => w.author != null && people.has(w.author) && w.year >= e.from && w.year < e.to).map((w) => w.id));
    events = new Set(v.events.filter((x) => x.year >= e.from && x.year < e.to).map((x) => x.id));
  } else if (f.type === "event") {
    const e = f.obj;
    group(v.people.filter((p) => p.birth <= e.year && p.death >= e.year));
    era = eraOf(v.eras, e.year);
    works = new Set(
      v.works.filter((w) => w.author != null && people.has(w.author) && Math.abs(w.year - e.year) <= WORKS_AROUND_EVENT).map((w) => w.id),
    );
    events = new Set([e.id]);
  } else {
    const g = f.obj;
    group(v.people.filter((p) => g.members.includes(p.id)));
    works = new Set(v.works.filter((w) => w.author != null && people.has(w.author)).map((w) => w.id));
    // влияния внутри группы — цветом учителя (object)
    v.links.forEach((l) => {
      if (people.has(l.subject) && people.has(l.object)) links.push({ link: l, role: people.get(l.object)! });
    });
  }
  return { ...f, people, works, links, era, events, primary, legend };
}

/* ---------- поиск ---------- */

export type SearchGroupKey = "people" | "works" | "ideas" | "events" | "eras";

export type SearchHit = {
  id: string;
  label: string;
  type: EntityType | "undated";
  entityType: string; // код типа: person, work, concept…, epoch, group, event
  match: [number, number]; // [начало, конец) совпадения в label
  hiddenByFilter: boolean; // найдено, но скрыто фильтром
  undated: boolean; // без даты — не стоит на оси
};

export type SearchResult = Record<SearchGroupKey, SearchHit[]>;
export const SEARCH_GROUPS: readonly SearchGroupKey[] = ["people", "works", "ideas", "events", "eras"];

// Сравнение без регистра и без различия е/ё (длина строки не меняется — диапазон совпадения верен).
const fold = (s: string) => s.toLocaleLowerCase("ru").replace(/ё/g, "е");

// Группа подсказки для сущности без даты — по коду типа из реестра.
const undatedGroup = (type: string): SearchGroupKey =>
  type === "person"
    ? "people"
    : type === "work"
      ? "works"
      : type === "event" || type === "idea_event" || type === "phenomenon"
        ? "events"
        : type === "epoch" || type === "group"
          ? "eras"
          : "ideas";

export function search(data: MapData, v: Visible, q: string): SearchResult {
  const out: SearchResult = { people: [], works: [], ideas: [], events: [], eras: [] };
  const needle = fold(q.trim());
  if (!needle) return out;
  const shown = new Set<string>([
    ...v.people.map((x) => x.id),
    ...v.works.map((x) => x.id),
    ...v.events.map((x) => x.id),
    ...v.eras.map((x) => x.id),
    ...v.groups.map((x) => x.id),
  ]);
  const rank = new Map<SearchHit, number>();
  const add = (
    g: SearchGroupKey,
    id: string,
    label: string,
    type: SearchHit["type"],
    entityType: string,
    weight: number,
    alt?: string,
  ) => {
    const at = fold(label).indexOf(needle);
    // персону находим и по краткому имени; тогда подсветки в полном нет
    if (at < 0 && !(alt != null && fold(alt).includes(needle))) return;
    const undated = type === "undated";
    const hit: SearchHit = {
      id,
      label,
      type,
      entityType,
      match: at >= 0 ? [at, at + needle.length] : [0, 0],
      hiddenByFilter: !undated && !shown.has(id),
      undated,
    };
    out[g].push(hit);
    // начало названия или слова — выше, затем значимость
    const word = at === 0 ? 0 : at > 0 && /[\s«"(-]/.test(label[at - 1]) ? 1 : 2;
    rank.set(hit, word * 1e6 - weight);
  };
  data.people.forEach((p) => add("people", p.id, p.label, "person", "person", p.weight, p.short));
  data.works.forEach((w) => add(w.kind === "work" ? "works" : "ideas", w.id, w.label, "work", w.type, w.weight));
  data.events.forEach((e) => add("events", e.id, e.label, "event", "event", 0));
  data.eras.forEach((e) => add("eras", e.id, e.label, "era", "epoch", 0));
  data.groups.forEach((g) => add("eras", g.id, g.label, "group", "group", g.members.length));
  data.undated.forEach((u) => add(undatedGroup(u.type), u.id, u.label, "undated", u.type, -1));
  // сначала видимые, потом скрытые фильтром и без даты
  const key = (h: SearchHit) => (h.hiddenByFilter || h.undated ? 1e7 : 0) + rank.get(h)!;
  SEARCH_GROUPS.forEach((g) => out[g].sort((a, b) => key(a) - key(b) || a.label.localeCompare(b.label, "ru")));
  return out;
}

/* ---------- счётчики фасетов ---------- */

export type Counts = {
  total: { people: number; works: number; events: number; eras: number; links: number };
  shown: { people: number; works: number; events: number; eras: number; links: number };
  groups: Record<string, number>; // участников в группе
  roles: Record<string, number>; // персон с ролью
  kinds: Record<string, number>; // трудов и идей вида
  ekinds: Record<string, number>; // событий вида
  verified: number; // связей, не достроенных моделью
  active: number; // активных фасетов (значок у «Фильтры»)
};

const tally = (keys: string[]): Record<string, number> => {
  const r: Record<string, number> = {};
  keys.forEach((k) => (r[k] = (r[k] ?? 0) + 1));
  return r;
};

// Счётчики по всему разделу (как в макете): число рядом с галочкой не прыгает при выборе других.
export function counts(data: MapData, v: Visible, f: Filter): Counts {
  const size = (x: { people: unknown[]; works: unknown[]; events: unknown[]; eras: unknown[]; links: unknown[] }) => ({
    people: x.people.length,
    works: x.works.length,
    events: x.events.length,
    eras: x.eras.length,
    links: x.links.length,
  });
  const gkind = (id: string) => data.groups.find((g) => g.id === id)?.kind;
  const gkinds = new Set(f.groups.map(gkind).filter(Boolean));
  return {
    total: size(data),
    shown: size(v),
    groups: Object.fromEntries(data.groups.map((g) => [g.id, g.members.length])),
    roles: tally(data.people.flatMap((p) => p.roles)),
    kinds: tally(data.works.map((w) => w.kind)),
    ekinds: tally(data.events.flatMap((e) => (e.kind ? [e.kind] : []))),
    verified: data.links.filter((l) => !l.generated).length,
    // время, каждый вид групп (направление, школа…), роль, вид, вид события, проверенность
    active:
      [f.from != null || f.to != null, f.roles.length > 0, f.kinds.length > 0, f.ekinds.length > 0, f.verified].filter(Boolean)
        .length + gkinds.size,
  };
}
