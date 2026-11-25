// Вид глобуса (geo-timeline): центр и приближение, их изменение и проекция d3-geo.
// Без DOM и без Date. Вид — только данные: исходный вид зависит от мест и размера, а не от
// случайности или времени.

import { geoDistance, geoGraticule, geoInterpolate, geoOrthographic, geoPath, type GeoPath, type GeoProjection } from "d3-geo";

export type View = { lon: number; lat: number; zoom: number };

export const MAX_LAT = 80; // широта центра зажата: полюс не встаёт под курсор
export const ZOOM_STEP = 1.25;
export const MIN_ZOOM = 1;
export const MAX_ZOOM = 8;
export const STEP = 10; // стрелка — 10°, с Shift — 30°
export const STEP_SHIFT = 30;
export const DEFAULT_CENTER: [number, number] = [15, 50]; // мест нет — Европа

const clampLat = (lat: number) => Math.max(-MAX_LAT, Math.min(MAX_LAT, lat));
// Долгота — в (−180, 180].
const wrapLon = (lon: number) => {
  const x = ((((lon + 180) % 360) + 360) % 360) - 180;
  return x === -180 ? 180 : x;
};
const round2 = (x: number) => {
  const r = Math.round(x * 100) / 100;
  return r === 0 ? 0 : r; // без «-0»
};

// Сферический центр масс мест: среднее единичных векторов. Пусто или центр масс в нуле
// (места по всему шару) — центр по умолчанию.
export function centroid(points: { lat: number; lon: number }[]): [number, number] {
  if (!points.length) return DEFAULT_CENTER;
  let x = 0;
  let y = 0;
  let z = 0;
  for (const p of points) {
    const la = (p.lat * Math.PI) / 180;
    const lo = (p.lon * Math.PI) / 180;
    x += Math.cos(la) * Math.cos(lo);
    y += Math.cos(la) * Math.sin(lo);
    z += Math.sin(la);
  }
  const n = Math.hypot(x, y, z);
  if (n < 1e-9) return DEFAULT_CENTER;
  return [round2((Math.atan2(y, x) * 180) / Math.PI), round2((Math.asin(z / n) * 180) / Math.PI)];
}

// Исходный вид: центр — центр масс видимых мест (широта зажата), приближение 1 — весь
// глобус в кадре, видимое полушарие вокруг центра масс вмещает места.
export function initialView(places: { lat: number; lon: number }[]): View {
  const [lon, lat] = centroid(places);
  return { lon: round2(wrapLon(lon)), lat: round2(clampLat(lat)), zoom: 1 };
}

export const rotateBy = (v: View, dLon: number, dLat: number): View => ({
  ...v,
  lon: round2(wrapLon(v.lon + dLon)),
  lat: round2(clampLat(v.lat + dLat)),
});

export const zoomBy = (v: View, steps: number): View => ({
  ...v,
  zoom: Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, v.zoom * ZOOM_STEP ** steps)),
});

export const centerOn = (v: View, place: { lat: number; lon: number }): View => ({
  ...v,
  lon: round2(wrapLon(place.lon)),
  lat: round2(clampLat(place.lat)),
});

// Отметка на видимом полушарии: угловое расстояние от центра не больше 90°.
export const isNear = (v: View, place: { lat: number; lon: number }): boolean =>
  geoDistance([v.lon, v.lat], [place.lon, place.lat]) <= Math.PI / 2 + 1e-9;

// Числа якорей: округлены до 0,01, без лишних нулей («45,80», «1.56», «1»).
export const fmt = (x: number): string => String(round2(x));
export const centerAttr = (v: View): string => `${fmt(v.lon)},${fmt(v.lat)}`;

// Промежуточный центр поворота к месту (дуга большого круга): t — от 0 до 1.
export function interpolateCenter(a: View, b: View): (t: number) => View {
  const f = geoInterpolate([a.lon, a.lat], [b.lon, b.lat]);
  return (t: number) => {
    if (t >= 1) return b;
    const [lon, lat] = f(t);
    return { ...b, lon: round2(wrapLon(lon)), lat: round2(clampLat(lat)) };
  };
}

export type Frame = { cx: number; cy: number; radius: number }; // круг глобуса при zoom 1

export type Projector = { projection: GeoProjection; path: GeoPath; scale: number };

// Ортографическая проекция вида: обрезка по видимому полушарию (clipAngle 90).
export function projector(v: View, f: Frame): Projector {
  const projection = geoOrthographic()
    .rotate([-v.lon, -v.lat])
    .scale(f.radius * v.zoom)
    .translate([f.cx, f.cy])
    .clipAngle(90)
    .precision(0.6);
  return { projection, path: geoPath(projection), scale: f.radius * v.zoom };
}

// Путь дуги большого круга между двумя местами; на дальнем полушарии — обрезан (null —
// дуга целиком не видна).
export function arcPath(p: Projector, from: { lat: number; lon: number }, to: { lat: number; lon: number }): string | null {
  return p.path({ type: "LineString", coordinates: [[from.lon, from.lat], [to.lon, to.lat]] }) || null;
}

// Градусная сетка через 15°.
export const GRATICULE = geoGraticule().step([15, 15])();

// Градусов на пиксель при перетаскивании: сдвиг на радиус глобуса — около 57°.
export const degreesPerPixel = (p: Projector): number => 180 / Math.PI / p.scale;
