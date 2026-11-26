// Бюджет раскладки в покое (задача 3.8, сценарий «Предел медальонов»): layoutMarkers и
// layoutCountries вместе — чистый расчёт без отрисовки React и canvas — на данных «Много
// мест» (320 мест, 51 360 персон) в кадре 1366×768. Медиана 5 прогонов после прогрева по
// времени процессора
// ≤ 150 мс; кэш кандидатов стран не участвует (новый массив стран). Ширина текста — приближённая (без canvas), как у измерителя без DOM.
import { geoOrthographic, geoPath } from "d3-geo";
import { countryName } from "../../src/map/geo/countries";
import { layoutCountries, layoutMarkers, type Frame, type LPerson, type LPlace } from "../../src/map/geo/layout";
import { COUNTRIES } from "../../src/map/geo/world";
import { done, ok, test } from "../harness";

const BUDGET_MS = 150;
// Время процессора (user + system), а не по часам: машина общая, замер по часам зависит
// от соседних процессов. Раскладка однопоточная — это её собственное время.
const cpuMs = (): number => {
  const u = process.cpuUsage();
  return (u.user + u.system) / 1000;
};
const [w, h] = [1366, 768];
const input = COUNTRIES.filter((c) => c.id && countryName(c.id)).map((c) => ({ id: c.id!, name: countryName(c.id)!, feature: c.feature }));
const fonts = [
  { font: "10.5px", measure: (t: string) => t.length * 6.5, metrics: { ascent: 9, descent: 3 } },
  { font: "9px", measure: (t: string) => t.length * 5.6, metrics: { ascent: 8, descent: 2.5 } },
];

// Порядок сцены: ранг внутри места, затем порядок мест (у места i — i персон).
const persons: LPerson[] = [];
for (let j = 0; j < 320; j++) for (let i = j + 1; i <= 320; i++) persons.push({ id: `x${i}_${j}`, place: `g${i}`, name: `Человек ${i}-${j}` });

function run(lon: number, lat: number): number {
  const R = Math.min(w, h) / 2 - 16;
  const projection = geoOrthographic().rotate([-lon, -lat]).scale(R).translate([w / 2, h / 2]).clipAngle(90).precision(2); // как у подписей стран в GlobeView
  const f: Frame = { w, h, cx: w / 2, cy: h / 2, R };
  const t0 = cpuMs();
  const places: LPlace[] = [];
  for (let i = 1; i <= 320; i++) {
    const ll: [number, number] = [-170 + ((i * 53) % 340), -60 + ((i * 37) % 120)];
    const xy = projection(ll);
    const back = xy ? projection.invert!(xy) : null;
    const near = !!back && Math.abs(back[0] - ll[0]) < 1e-6;
    places.push({ id: `g${i}`, x: xy ? xy[0] : 0, y: xy ? xy[1] : 0, visible: !!xy && near && xy[0] >= 0 && xy[1] >= 0 && xy[0] <= w && xy[1] <= h });
  }
  const lay = layoutMarkers({ places, persons, events: [], frame: f, measure: (t) => t.length * 7, metrics: { ascent: 13, descent: 4 } });
  projection.clipExtent([
    [0, 0],
    [w, h],
  ]);
  layoutCountries([...input], geoPath(projection), projection, f, lay.grid, fonts);
  return cpuMs() - t0;
}

for (const [lon, lat] of [[0, 0], [15, 50], [100, 40]]) {
  test(`раскладка в покое ≤ ${BUDGET_MS} мс (${lon}, ${lat})`, () => {
    run(lon, lat);
    const times = Array.from({ length: 5 }, () => run(lon, lat)).sort((a, b) => a - b);
    console.log(`раскладка в покое (${lon}, ${lat}), мс:`, times.map((t) => Math.round(t)).join(" "));
    ok(times[2] <= BUDGET_MS, `медиана ${Math.round(times[2])} мс`);
  });
}

done();
