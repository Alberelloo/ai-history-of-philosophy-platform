// Суша глобуса: Natural Earth 1:110m из пакета world-atlas (land-110m — только суша
// и береговая линия, без границ государств), собрана в клиентский фрагмент глобуса:
// внешних запросов нет. TopoJSON переводится в GeoJSON один раз на загрузку модуля.

import type { FeatureCollection, MultiPolygon, Polygon } from "geojson";
import { feature } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";
import topology from "world-atlas/land-110m.json";

type Land = Topology<{ land: GeometryCollection }>;

export const LAND = feature(topology as unknown as Land, (topology as unknown as Land).objects.land) as FeatureCollection<Polygon | MultiPolygon>;
