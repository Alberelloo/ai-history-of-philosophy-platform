// Карта раздела (openspec/changes/archive/2026-11-18-synchro-map): типы ответа GET /api/knowledge/v1/map,
// состояние страницы (выбор, поиск, фильтр, линзы) и его запись в параметры адреса.
// Без React и DOM: модуль используют модель, раскладка и страница.

// Роли персоны и виды событий — значения из списка реестра (person_role, event_kind).
export type PersonRole = "philosopher" | "scientist" | "writer" | "theologian" | "ruler" | "translator";
export type EventKind =
  | "political"
  | "economic"
  | "social"
  | "scientific"
  | "religious"
  | "intellectual"
  | "biographical";
// Вид значка на страте трудов: произведение или идея (понятие, позиция, аргумент).
export type WorkKind = "work" | "concept" | "position" | "argument";
export type GroupKind = "school" | "direction" | "institution" | "circle";
export type LinkStatus = "verified" | "sourced" | "generated";

export type MapPerson = {
  id: string;
  label: string; // полное имя
  short: string; // краткое имя (фамилия) — для плотных лент и легенды
  birth: number;
  death: number;
  precision: string; // точность датировки: year | decade | century | approx
  roles: string[];
  portrait?: string;
  weight: number; // значимость: число утверждений в области
  epochs?: string[]; // эпохи по правилу сервера (явные важнее дат), по началу эпохи
};

export type MapWork = {
  id: string;
  label: string;
  type: string; // код типа сущности в реестре (work, concept, doctrine…)
  kind: WorkKind;
  year: number; // год труда; у идеи — год самого раннего труда, где она высказана
  author: string | null; // id персоны; может не быть или указывать на персону вне карты
  weight: number;
  epochs?: string[]; // у идеи — только явные
};

// Что событие стимулировало (связи «стимулировало» к персонам, трудам и идеям на карте):
// до 30, проверенные и по источникам раньше сгенерированных; нет таких — поля нет.
export type MapStimulated = { id: string; generated: boolean };
export type MapEvent = {
  id: string;
  label: string;
  year: number;
  kind?: string | null;
  epochs?: string[];
  stimulated?: MapStimulated[];
};
// Нечёткие границы пролёта: пары «самое раннее, самое позднее»; у чёткой границы равны.
export type Fuzzy = { from: [number, number]; to: [number, number] };
export type MapEra = { id: string; label: string; from: number; to: number; fuzzy?: Fuzzy };
export type MapGroup = { id: string; label: string; kind: GroupKind | null; members: string[] };

// Связь между персонами (influenced_by и подтипы, studied_with).
// Направление: subject испытал влияние object (subject — ученик, object — учитель).
export type MapLink = {
  id: string;
  subject: string;
  object: string;
  type: string;
  status: LinkStatus;
  generated: boolean; // достроена моделью — пунктир
  in_textbook: boolean | null;
};

export type MapUndated = { id: string; label: string; type: string };

export type MapData = {
  range: [number, number] | null; // null — карта пуста (нет датированных сущностей)
  truncated: boolean;
  limit: number;
  people: MapPerson[];
  works: MapWork[];
  events: MapEvent[];
  eras: MapEra[];
  groups: MapGroup[];
  links: MapLink[];
  undated: MapUndated[];
};

// Фильтр скрывает объекты; пустой список — фасет не ограничивает.
export type Filter = {
  from?: number;
  to?: number;
  groups: string[];
  roles: string[];
  kinds: string[];
  ekinds: string[];
  epochs: string[]; // id датированных эпох карты; неизвестные карте отбрасываются
  verified: boolean; // только проверенные: без достроенных моделью связей
};

// Выбор — id любой сущности карты (персона, труд или идея, событие, эпоха, группа).
export type Selection = string;

// Страты сверху вниз; линза сворачивает страту в узкую полосу.
export type Stratum = "events" | "eras" | "people" | "works";
export const STRATA: readonly Stratum[] = ["events", "eras", "people", "works"];

export type MapState = {
  sel: Selection | null;
  q: string;
  filter: Filter;
  collapsed: Stratum[]; // свёрнутые линзы
};

export const emptyFilter = (): Filter => ({ groups: [], roles: [], kinds: [], ekinds: [], epochs: [], verified: false });

export const emptyState = (): MapState => ({ sel: null, q: "", filter: emptyFilter(), collapsed: [] });

// Свернуть или развернуть страту. Последнюю развёрнутую свернуть нельзя — список не меняется.
export function toggleLens(collapsed: Stratum[], k: Stratum): Stratum[] {
  if (collapsed.includes(k)) return collapsed.filter((x) => x !== k);
  if (STRATA.filter((x) => !collapsed.includes(x)).length <= 1) return collapsed;
  return STRATA.filter((x) => x === k || collapsed.includes(x));
}

/* Параметры адреса: sel, q, from, to, groups, roles, kinds, ekinds, epochs, verified, lens.
   Списки — через запятую; пустые и значения по умолчанию в адрес не пишутся. */

const list = (p: URLSearchParams, k: string): string[] =>
  (p.get(k) ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

const year = (p: URLSearchParams, k: string): number | undefined => {
  const v = p.get(k);
  if (v == null || !/^-?\d+$/.test(v.trim())) return undefined;
  return Number(v);
};

export function parseState(p: URLSearchParams): MapState {
  let from = year(p, "from");
  let to = year(p, "to");
  if (from != null && to != null && from > to) [from, to] = [to, from];
  const lens = list(p, "lens").filter((k): k is Stratum => (STRATA as readonly string[]).includes(k));
  // все страты свернуть нельзя: тогда адрес игнорируется
  const collapsed = STRATA.filter((k) => lens.includes(k));
  return {
    sel: p.get("sel") || null,
    q: p.get("q") ?? "",
    filter: {
      ...(from != null ? { from } : {}),
      ...(to != null ? { to } : {}),
      groups: list(p, "groups"),
      roles: list(p, "roles"),
      kinds: list(p, "kinds"),
      ekinds: list(p, "ekinds"),
      epochs: [...new Set(list(p, "epochs"))],
      verified: p.get("verified") === "1",
    },
    collapsed: collapsed.length >= STRATA.length ? [] : collapsed,
  };
}

export function writeState(s: MapState): URLSearchParams {
  const p = new URLSearchParams();
  const f = s.filter;
  if (s.sel) p.set("sel", s.sel);
  if (s.q.trim()) p.set("q", s.q);
  if (f.from != null) p.set("from", String(f.from));
  if (f.to != null) p.set("to", String(f.to));
  if (f.groups.length) p.set("groups", f.groups.join(","));
  if (f.roles.length) p.set("roles", f.roles.join(","));
  if (f.kinds.length) p.set("kinds", f.kinds.join(","));
  if (f.ekinds.length) p.set("ekinds", f.ekinds.join(","));
  if (f.epochs.length) p.set("epochs", f.epochs.join(","));
  if (f.verified) p.set("verified", "1");
  const lens = STRATA.filter((k) => s.collapsed.includes(k));
  if (lens.length) p.set("lens", lens.join(","));
  return p;
}

// Строка запроса без экранирования запятых (URLSearchParams пишет их как %2C) — для replaceState.
export const toQuery = (s: MapState): string => writeState(s).toString().replace(/%2C/gi, ",");
