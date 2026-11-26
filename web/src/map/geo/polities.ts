// Слой политических образований на год (add-historical-polities): ответ
// GET /api/knowledge/v1/map/polities?year=T и его кэш в клиенте. Без React и без d3.
//
// Правила (дельта «Исторические границы на глобусе»):
// - слой держится по интервалу valid_from–valid_to, который прислал сервер: год внутри
//   известного интервала рисуется без запроса (клиент только сравнивает числа);
// - одновременно не больше одного запроса; ответ, интервал которого не содержит текущий
//   год, не рисуется (он кэшируется, и сразу запрашивается текущий год);
// - 503 (артефакта нет) — современная карта без пометки, запросов больше нет;
//   прочая ошибка — современная карта с пометкой, следующая смена года спрашивает снова;
// - не больше POLITY_CACHE слоёв в памяти (давно не нужный вытесняется).

import type { Feature, MultiPolygon, Polygon } from "geojson";
import { KNOWLEDGE_API } from "../stream";

export const POLITY_CACHE = 16;

export type PolityItem = {
  id: string;
  name: string;
  name_status: "ru" | "original";
  name_source: "label" | "sitelink" | "original";
  original: string;
  wikidata: string | null;
  from: number;
  to: number;
  geometry: Polygon | MultiPolygon;
};

export type PolitySource = {
  title: string;
  publisher: string;
  authors: string[];
  version: string;
  license: string;
  license_url: string | null;
  url: string | null;
};

export type PolityLayer = { year: number; valid_from: number; valid_to: number; polities: PolityItem[]; source: PolitySource };

export type PolityResult = { kind: "ok"; layer: PolityLayer } | { kind: "unavailable" } | { kind: "error" };

// pending — первого ответа ещё нет (рисуется современная карта, глобус aria-busy);
// historical — нарисован layer; modern — слоя нет (503 или ошибка, error — пометка).
export type PolityState = { mode: "pending" | "historical" | "modern"; layer: PolityLayer | null; error: boolean };

export type PolityFetch = (year: number, signal?: AbortSignal) => Promise<PolityResult>;

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

function valid(body: unknown): body is PolityLayer {
  const b = body as PolityLayer | null;
  return !!b && isNum(b.year) && isNum(b.valid_from) && isNum(b.valid_to) && Array.isArray(b.polities) && !!b.source && typeof b.source === "object";
}

export const fetchPolities: PolityFetch = async (year, signal) => {
  try {
    const r = await fetch(`${KNOWLEDGE_API}/map/polities?year=${encodeURIComponent(String(year))}`, { signal });
    if (r.status === 503) return { kind: "unavailable" };
    if (!r.ok) return { kind: "error" };
    const body = (await r.json()) as unknown;
    return valid(body) ? { kind: "ok", layer: body } : { kind: "error" };
  } catch {
    return { kind: "error" };
  }
};

export const covers = (layer: PolityLayer, year: number): boolean => layer.valid_from <= year && year <= layer.valid_to;

export class PolityStore {
  private layers: PolityLayer[] = []; // от давно нужного к недавнему
  private inflight = false;
  private wanted: number | null = null;
  private unavailable = false;
  private errorYear: number | null = null;
  private listeners = new Set<(s: PolityState) => void>();
  state: PolityState = { mode: "pending", layer: null, error: false };

  constructor(
    private readonly fetcher: PolityFetch = fetchPolities,
    private readonly limit = POLITY_CACHE,
  ) {}

  subscribe(fn: (s: PolityState) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  cached(): number {
    return this.layers.length;
  }

  private set(next: PolityState): void {
    const s = this.state;
    if (s.mode === next.mode && s.layer === next.layer && s.error === next.error) return;
    this.state = next;
    for (const fn of this.listeners) fn(next);
  }

  private find(year: number): PolityLayer | null {
    const i = this.layers.findIndex((l) => covers(l, year));
    if (i < 0) return null;
    const [hit] = this.layers.splice(i, 1);
    this.layers.push(hit);
    return hit;
  }

  private remember(layer: PolityLayer): void {
    this.layers = this.layers.filter((l) => !(l.valid_from === layer.valid_from && l.valid_to === layer.valid_to));
    this.layers.push(layer);
    while (this.layers.length > this.limit) this.layers.shift();
  }

  // Текущий год глобуса. Ничего не бросает.
  request(year: number): void {
    this.wanted = year;
    if (this.unavailable) return;
    const hit = this.find(year);
    if (hit) return this.set({ mode: "historical", layer: hit, error: false });
    if (this.inflight || this.errorYear === year) return;
    void this.start(year);
  }

  // Ответ на запрос в пути дойдёт и закэшируется, но слушателей уже нет.
  dispose(): void {
    this.listeners.clear();
  }

  private async start(year: number): Promise<void> {
    this.inflight = true;
    const res = await this.fetcher(year);
    this.inflight = false;
    const wanted = this.wanted ?? year;
    if (res.kind === "unavailable") {
      this.unavailable = true;
      return this.set({ mode: "modern", layer: null, error: false });
    }
    if (res.kind === "error") {
      this.errorYear = year;
      if (wanted !== year) return this.request(wanted);
      return this.set({ mode: "modern", layer: null, error: true });
    }
    this.errorYear = null;
    this.remember(res.layer);
    if (covers(res.layer, wanted)) return this.set({ mode: "historical", layer: res.layer, error: false });
    this.request(wanted); // ответ устарел: не рисуется, текущий год — следующим запросом
  }
}

// Вход раскладки подписей: одна подпись на Wikidata-QID — первое образование в порядке
// ответа (сервер упорядочил по убыванию площади, затем по id); без QID — каждое.
export type PolityLabelInput = { id: string; name: string; italic: boolean; feature: Feature<Polygon | MultiPolygon> };

const inputs = new WeakMap<PolityLayer, PolityLabelInput[]>();
export function labelInputs(layer: PolityLayer): PolityLabelInput[] {
  let out = inputs.get(layer);
  if (!out) {
    const seen = new Set<string>();
    out = [];
    for (const p of layer.polities) {
      if (p.wikidata) {
        if (seen.has(p.wikidata)) continue;
        seen.add(p.wikidata);
      }
      out.push({ id: p.id, name: p.name, italic: p.name_status === "original", feature: { type: "Feature", id: p.id, properties: {}, geometry: p.geometry } });
    }
    inputs.set(layer, out);
  }
  return out;
}

export const nameStatusOf = (layer: PolityLayer | null): Map<string, PolityItem["name_status"]> => new Map((layer?.polities ?? []).map((p) => [p.id, p.name_status]));
