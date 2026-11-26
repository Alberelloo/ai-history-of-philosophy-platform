// Запрос справочника с отменой: устаревший запрос прерывается AbortController, а ответ,
// пришедший позже более нового, отбрасывает страница по номеру запроса (ReferencePage).

import { TYPE_GROUPS, type CatalogPage, type ReferenceState } from "./types";

const API = "/api/knowledge/v1";

export class CatalogError extends Error {
  constructor(
    public kind: string,
    public status: number,
  ) {
    super(kind);
  }
}

export function catalogQuery(state: ReferenceState, page: number, lang: string): URLSearchParams {
  const p = new URLSearchParams();
  const q = state.q.trim();
  if (q) p.set("q", q);
  if (state.group) TYPE_GROUPS[state.group].forEach((code) => p.append("type", code));
  if (state.epoch) p.set("epoch", state.epoch);
  if (state.textbook) p.set("textbook", state.textbook);
  if (state.sort) p.set("sort", state.sort);
  if (page > 1) p.set("page", String(page));
  p.set("lang", lang);
  return p;
}

// Ошибка сервиса — CatalogError с kind из ответа (bad_query, unknown_epoch, …) или
// "unavailable", если ответа нет или он не JSON; отмена — AbortError, её страница молча пропускает.
export async function fetchCatalog(
  state: ReferenceState,
  page: number,
  lang: string,
  signal: AbortSignal,
): Promise<CatalogPage> {
  let response: Response;
  try {
    response = await fetch(`${API}/catalog?${catalogQuery(state, page, lang)}`, { signal });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new CatalogError("unavailable", 0);
  }
  let body: unknown = null;
  try {
    body = await response.json();
  } catch (e) {
    if (isAbort(e)) throw e;
    body = null;
  }
  if (!response.ok || body === null) {
    const kind = (body as { kind?: unknown } | null)?.kind;
    throw new CatalogError(typeof kind === "string" ? kind : "unavailable", response.status);
  }
  return body as CatalogPage;
}

export function isAbort(e: unknown): boolean {
  return (e as Error | null)?.name === "AbortError";
}
