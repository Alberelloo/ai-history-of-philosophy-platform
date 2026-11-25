// Справочник (entity-catalog): группы типов и ответ GET /api/knowledge/v1/catalog.
// Состав групп — данные (groups.json): точные коды реестра, в том числе подтипы (idea_event),
// потому что счётчики facets.types приходят по точному коду. Код группы раскрывается в
// повторяющиеся `type` запроса (подтипы сервер включил бы и сам — повтор безвреден). Сверку
// с реестром делает tests/knowledge/test_reference_groups.py: каждый тип, кроме источника,
// ровно в одной группе; неизвестный код — ошибка теста, а не тихий пропуск.

import groups from "./groups.json";

export type GroupCode = "person" | "ideas" | "term" | "work" | "events" | "epoch" | "group" | "place";

export const TYPE_GROUPS: Record<GroupCode, string[]> = groups;
export const GROUP_CODES = Object.keys(TYPE_GROUPS) as GroupCode[];

// Типы, которые есть на карте раздела: у их записей — действие «На карте».
const ON_MAP = new Set([
  "person",
  "work",
  "concept",
  "conception",
  "doctrine",
  "problem",
  "position",
  "argument",
  "event",
  "idea_event",
  "phenomenon",
  "epoch",
  "group",
]);

export function onMap(type: string): boolean {
  return ON_MAP.has(type);
}

export function isGroup(code: string | null): code is GroupCode {
  return code !== null && code in TYPE_GROUPS;
}

// Счётчик группы — сумма facets.types по её кодам.
export function groupCount(facets: Record<string, number>, group: GroupCode): number {
  return TYPE_GROUPS[group].reduce((n, code) => n + (facets[code] ?? 0), 0);
}

export type Sort = "label" | "date" | "weight" | "relevance";
export const SORTS: Sort[] = ["label", "date", "weight", "relevance"];

export type CatalogItem = {
  id: string;
  type: string;
  label: string;
  matched_name: string | null;
  dates: { from: number; to: number; precision: string; original: string } | null;
  epochs: { id: string; label: string; basis: "explicit" | "dates" }[];
  summary: { text: string; generated: boolean } | null;
  weight: number;
};

export type CatalogPage = {
  items: CatalogItem[];
  total: number;
  page: number;
  limit: number;
  sort: Sort;
  facets: { types: Record<string, number>; epochs: { id: string; label: string; count: number }[] };
  textbook_closed: boolean;
};

// Состояние страницы — то же, что в адресе (q, group, epoch, textbook, sort).
export type ReferenceState = {
  q: string;
  group: GroupCode | null;
  epoch: string | null;
  textbook: string | null;
  sort: Sort | null;
};

export function readState(search: string): ReferenceState {
  const p = new URLSearchParams(search);
  const group = p.get("group");
  const sort = p.get("sort");
  return {
    q: p.get("q") ?? "",
    group: isGroup(group) ? group : null,
    epoch: p.get("epoch") || null,
    textbook: p.get("textbook") || null,
    sort: SORTS.includes(sort as Sort) ? (sort as Sort) : null,
  };
}

export function writeState(s: ReferenceState): string {
  const p = new URLSearchParams();
  if (s.q.trim()) p.set("q", s.q);
  if (s.group) p.set("group", s.group);
  if (s.epoch) p.set("epoch", s.epoch);
  if (s.textbook) p.set("textbook", s.textbook);
  if (s.sort) p.set("sort", s.sort);
  const query = p.toString();
  return "/reference" + (query ? `?${query}` : "");
}
