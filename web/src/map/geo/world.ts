// Политическая карта глобуса (rework-globe-political-map): Natural Earth 1:110m из пакета
// world-atlas (countries-110m — страны с границами и объект суши), собрана в клиентский
// фрагмент глобуса: внешних запросов нет. TopoJSON переводится в GeoJSON один раз на
// загрузку модуля.
// - LAND — суша и береговая линия;
// - BORDERS — только внутренние границы (дуги между двумя разными странами), береговая
//   линия второй раз не обводится;
// - COUNTRIES — страны с кодом ISO 3166-1 (id) или без него (территории без кода).

import { geoBounds } from "d3-geo";
import type { Feature, FeatureCollection, MultiLineString, MultiPolygon, Polygon } from "geojson";
import { feature, mesh } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";
import topology from "world-atlas/countries-110m.json";

type World = Topology<{ countries: GeometryCollection<{ name: string }>; land: GeometryCollection }>;
const world = topology as unknown as World;

export const LAND = feature(world, world.objects.land) as FeatureCollection<Polygon | MultiPolygon>;

export const BORDERS: MultiLineString = mesh(world, world.objects.countries, (a, b) => a !== b);

export type Country = {
  id: string | null; // числовой код ISO 3166-1 строкой из трёх цифр; null — территория без кода
  feature: Feature<Polygon | MultiPolygon>;
  bounds: [[number, number], [number, number]]; // geoBounds: [[запад, юг], [восток, север]]
};

export const COUNTRIES: Country[] = (feature(world, world.objects.countries) as FeatureCollection<Polygon | MultiPolygon>).features.map((f) => ({
  id: f.id == null || f.id === "" ? null : String(f.id),
  feature: f,
  bounds: geoBounds(f) as [[number, number], [number, number]],
}));

export const COUNTRY_COUNT = world.objects.countries.geometries.length;
