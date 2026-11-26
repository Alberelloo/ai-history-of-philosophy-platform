// Страна места (rework-globe-political-map, «Страна места»): по координатам места и тем же
// границам, что нарисованы на глобусе (world.ts). Названия — только из файла данных
// countries.ru.json (ISO 3166-1 numeric → RU), не из модели и не из английских свойств
// world-atlas. Правило одно и живёт здесь:
// 1. страна, чей многоугольник содержит точку; территория без кода — поиск останавливается;
// 2. иначе — страна с кодом с ближайшей вершиной границы не дальше COUNTRY_SNAP_KM
//    (прибрежные и островные места, которых нет в масштабе 1:110m);
// 3. иначе — страны нет.

import { geoContains, geoDistance } from "d3-geo";
import data from "./countries.ru.json";
import { COUNTRIES, type Country } from "./world";

export const COUNTRY_SNAP_KM = 150;
const EARTH_KM = 6371;
const KM_PER_DEG = (Math.PI * EARTH_KM) / 180;

const NAMES: Record<string, string> = data.names;

export type CountryHit = { id: string; name: string };

export function countryName(id: string | null | undefined): string | null {
  return id != null && Object.prototype.hasOwnProperty.call(NAMES, id) ? NAMES[id] : null;
}

const hit = (c: Country): CountryHit | null => {
  const name = countryName(c.id);
  return c.id && name ? { id: c.id, name } : null;
};

// Точка в рамке geoBounds с полем (градусы); рамка через антимеридиан — запад > восток.
function inBounds(c: Country, lon: number, lat: number, padLat: number, padLon: number): boolean {
  const [[w, s], [e, n]] = c.bounds;
  if (lat < s - padLat || lat > n + padLat) return false;
  if (padLon >= 180) return true;
  const within = (x: number) => (w <= e ? x >= w - padLon && x <= e + padLon : x >= w - padLon || x <= e + padLon);
  return within(lon) || within(lon + 360) || within(lon - 360);
}

const vertices = new WeakMap<Country, [number, number][]>();
function verticesOf(c: Country): [number, number][] {
  let v = vertices.get(c);
  if (!v) {
    const out: [number, number][] = [];
    const walk = (x: unknown): void => {
      if (Array.isArray(x) && typeof x[0] === "number") out.push(x as [number, number]);
      else if (Array.isArray(x)) x.forEach(walk);
    };
    walk(c.feature.geometry.coordinates);
    vertices.set(c, (v = out));
  }
  return v;
}

// Страна точки без кэша. Некорректные числа — страны нет (без исключений).
export function countryAt(lat: number, lon: number): CountryHit | null {
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  const p: [number, number] = [lon, lat];
  for (const c of COUNTRIES) {
    if (!inBounds(c, lon, lat, 0.01, 0.01)) continue;
    if (geoContains(c.feature, p)) return hit(c); // территория без кода — поиск останавливается
  }
  const padLat = COUNTRY_SNAP_KM / KM_PER_DEG;
  const cos = Math.cos((lat * Math.PI) / 180);
  const padLon = cos < 1e-3 ? 180 : Math.min(180, padLat / cos);
  const limit = COUNTRY_SNAP_KM / EARTH_KM;
  let best: Country | null = null;
  let bestD = Infinity;
  for (const c of COUNTRIES) {
    if (!c.id || !inBounds(c, lon, lat, padLat, padLon)) continue;
    for (const v of verticesOf(c)) {
      const d = geoDistance(p, v);
      if (d < bestD) {
        bestD = d;
        best = c;
      }
    }
  }
  return best && bestD <= limit ? hit(best) : null;
}

// Страна места: кэш по id и координатам места (смена координат — новый ключ).
const cache = new Map<string, CountryHit | null>();
export function countryOf(place: { id: string; lat: number; lon: number }): CountryHit | null {
  const key = `${place.id}|${place.lat}|${place.lon}`;
  if (!cache.has(key)) cache.set(key, countryAt(place.lat, place.lon));
  return cache.get(key) ?? null;
}
