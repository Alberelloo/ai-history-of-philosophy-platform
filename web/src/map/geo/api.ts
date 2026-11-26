// Географический слой карты (geo-timeline): ответ GET /api/knowledge/v1/map/places и его
// загрузка. Без React и без d3: модуль нужен странице карты (загрузка при открытии вида
// «Глобус») и модели времени. Запрос — только к своему адресу.

import { KNOWLEDGE_API } from "../stream";
import type { LinkStatus } from "../types";

export type PlaceRole = "birth" | "death" | "activity" | "residence" | "event";

export type GeoPlace = { id: string; label: string; lat: number; lon: number; status: LinkStatus };

export type GeoPlacement = {
  entity: string;
  place: string;
  role: PlaceRole | null; // null — запись «жил в» без вида места
  from: number | null;
  to: number | null;
  status: LinkStatus;
  generated: boolean;
  statement: string;
};

export type GeoLayer = {
  places: GeoPlace[];
  placements: GeoPlacement[];
  unplaced: string[];
  truncated: boolean;
  limit: number;
};

export type GeoLoad = { status: "idle" | "loading" | "ok" | "error"; data: GeoLayer | null };

// Область — та же, что у карты (учебник, «только учебник»). Ошибка — значение, а не
// исключение: страница показывает «Не удалось загрузить места» и не пишет в консоль.
export async function fetchPlaces(textbook: string | null, onlyTextbook: boolean, signal?: AbortSignal): Promise<GeoLayer | null> {
  const params = new URLSearchParams();
  if (textbook) params.set("textbook", textbook);
  if (onlyTextbook) params.set("only_textbook", "true");
  const q = params.toString();
  try {
    const r = await fetch(`${KNOWLEDGE_API}/map/places${q ? `?${q}` : ""}`, { signal });
    if (!r.ok) return null;
    const body = (await r.json()) as GeoLayer;
    return Array.isArray(body?.places) && Array.isArray(body?.placements) ? body : null;
  } catch {
    return null;
  }
}
