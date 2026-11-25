// Данные страницы эпох (epochs, «Страница эпох»): список — GET /v1/epochs, участники
// выбранной эпохи — тем же справочником (GET /v1/catalog?epoch=&type=), отдельного эндпоинта нет.

import { TYPE_GROUPS, type CatalogItem, type CatalogPage } from "../reference/types";

const API = "/api/knowledge/v1";

export type DatingSource = "wikidata" | "source" | "common" | "manual";
export type EpochCounts = { people: number; works: number; ideas: number; events: number; groups: number };
export const COUNT_KINDS: (keyof EpochCounts)[] = ["people", "works", "ideas", "events", "groups"];
// Вид счётчика → группа справочника (/reference?group=…).
export const COUNT_GROUP: Record<keyof EpochCounts, string> = {
  people: "person",
  works: "work",
  ideas: "ideas",
  events: "events",
  groups: "group",
};

export type Epoch = {
  id: string;
  label: string;
  from: number;
  to: number;
  fuzzy: { from: [number, number]; to: [number, number] };
  precision: string | null;
  original: string | null;
  dating: { status: string | null; source: DatingSource; wikidata: string | null };
  summary: { text: string; generated: boolean } | null;
  counts: EpochCounts;
};

export type UndatedEpoch = { id: string; label: string; counts: EpochCounts };
export type EpochsData = { epochs: Epoch[]; undated: UndatedEpoch[]; truncated: boolean };

export class EpochsError extends Error {}

// Ссылка «Wikidata ↗» — только из идентификатора по шаблону (тот же, что на сервере).
const QID = /^Q\d+$/;
export function wikidataUrl(qid: string | null | undefined): string | null {
  return qid && QID.test(qid) ? `https://www.wikidata.org/wiki/${qid}` : null;
}

async function json<T>(url: string, signal: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { signal });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new EpochsError("unavailable");
  }
  if (!response.ok) throw new EpochsError(String(response.status));
  try {
    return (await response.json()) as T;
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new EpochsError("bad_json");
  }
}

export function fetchEpochs(signal: AbortSignal): Promise<EpochsData> {
  return json<EpochsData>(`${API}/epochs`, signal);
}

export type MemberList = "people" | "works" | "events";
// Персоны и труды — самые значимые (до восьми каждого вида), события — по времени (до двадцати).
export const MEMBER_QUERY: Record<MemberList, { group: string; sort: string; limit: number }> = {
  people: { group: "person", sort: "weight", limit: 8 },
  works: { group: "work", sort: "weight", limit: 8 },
  events: { group: "events", sort: "date", limit: 20 },
};

export async function fetchMembers(epochId: string, list: MemberList, lang: string, signal: AbortSignal): Promise<CatalogItem[]> {
  const q = MEMBER_QUERY[list];
  const p = new URLSearchParams();
  p.set("epoch", epochId);
  for (const code of TYPE_GROUPS[q.group as keyof typeof TYPE_GROUPS]) p.append("type", code);
  p.set("sort", q.sort);
  p.set("limit", String(q.limit));
  p.set("lang", lang);
  const page = await json<CatalogPage>(`${API}/catalog?${p}`, signal);
  return page.items;
}

export function isAbort(e: unknown): boolean {
  return (e as Error | null)?.name === "AbortError";
}

// Год в астрономическом счёте → подпись: 0 и меньше — «… до н. э.».
export function yearText(y: number, bce: string): string {
  return y <= 0 ? `${1 - y} ${bce}` : String(y);
}

export function spanText(from: number, to: number, bce: string): string {
  const a = yearText(from, bce);
  const b = yearText(to, bce);
  return a.includes(" ") || b.includes(" ") ? `${a} – ${b}` : `${a}–${b}`;
}

// Контекст эпохи (epoch-context, «Контекст эпохи»): GET /v1/context?epoch=… — события эпохи
// с видом, местами и связями «стимулировало». Без модели; цитат в ответе нет.
export const CONTEXT_KINDS = [
  "political",
  "economic",
  "social",
  "religious",
  "scientific",
  "intellectual",
  "biographical",
  "none",
] as const;
export type ContextKind = (typeof CONTEXT_KINDS)[number];

export type ContextLink = {
  statement_id: string;
  target: { id: string; label: string; type: string };
  mechanism: string | null;
  status: string;
  generated: boolean;
  in_textbook: boolean | null;
  attributed_to: string[];
  evidence: { paragraph_id: string; link: string }[];
  pending?: boolean; // предложено достройкой, ещё сохраняется (клиент)
};

export type ContextEvent = {
  id: string;
  label: string;
  type: string;
  kind: string | null;
  wikidata?: string | null;
  dates: { from: number; to: number; precision: string | null; original: string | null } | null;
  places: { id: string; label: string; wikidata: string | null }[];
  basis: string | null;
  stimulated: ContextLink[];
};

export type ContextData = {
  mode: "epoch" | "window";
  events: ContextEvent[];
  counts: Partial<Record<ContextKind, number>>;
  truncated: boolean;
};

export function fetchContext(
  epochId: string,
  opts: { kinds: string[]; verified: boolean; textbook: string | null; lang: string },
  signal: AbortSignal,
): Promise<ContextData> {
  const p = new URLSearchParams();
  p.set("epoch", epochId);
  if (opts.kinds.length) p.set("kinds", opts.kinds.join(","));
  if (opts.verified) p.set("verified", "true");
  if (opts.textbook) p.set("textbook", opts.textbook);
  p.set("lang", opts.lang);
  return json<ContextData>(`${API}/context?${p}`, signal);
}
