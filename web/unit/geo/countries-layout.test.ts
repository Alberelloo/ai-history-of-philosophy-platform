import { geoContains, geoOrthographic, geoPath } from "d3-geo";
import { countryName } from "../../src/map/geo/countries";
import { COUNTRY_MIN_AREA, COUNTRY_MIN_LABELS, Grid, inFrame, layoutCountries, MAX_COUNTRY_LABELS, overlaps, type Frame } from "../../src/map/geo/layout";
import { COUNTRIES } from "../../src/map/geo/world";
import { done, eq, ok, test } from "../harness";

// Шрифты как у глобуса: основной кегль и мельче для добора (ширина — по числу знаков).
const fonts = [
  { font: "10.5px", measure: (t: string) => t.length * 6.5, metrics: { ascent: 9, descent: 3 } },
  { font: "9px", measure: (t: string) => t.length * 5.6, metrics: { ascent: 8, descent: 2.5 } },
];
const input = COUNTRIES.filter((c) => c.id && countryName(c.id)).map((c) => ({ id: c.id!, name: countryName(c.id)!, feature: c.feature }));

const projOf = (w: number, h: number, lon: number, lat: number, zoom: number) =>
  geoOrthographic()
    .rotate([-lon, -lat])
    .scale((Math.min(w, h) / 2 - 16) * zoom)
    .translate([w / 2, h / 2])
    .clipAngle(90);

function run(w: number, h: number, lon: number, lat: number, zoom: number, grid = new Grid(), countries = input) {
  const R = (Math.min(w, h) / 2 - 16) * zoom;
  const projection = geoOrthographic().rotate([-lon, -lat]).scale(R).translate([w / 2, h / 2]).clipAngle(90).clipExtent([[0, 0], [w, h]]);
  const f: Frame = { w, h, cx: w / 2, cy: h / 2, R };
  return layoutCountries(countries, geoPath(projection), projection, f, grid, fonts);
}

// 564×322 — svg глобуса в окне 1024×576 (панель справа, шкала снизу).
for (const [w, h] of [[564, 322], [1024, 576], [1366, 768], [1920, 1080]])
  for (const [lon, lat] of [[15, 50], [100, 40], [-60, -10], [20, 0], [40, 50]])
    for (const z of [1, 2]) {
      test(`подписи стран ${w}×${h} (${lon}, ${lat}) ×${z}`, () => {
        const out = run(w, h, lon, lat, z);
        ok(out.length >= 5, `подписей ${out.length}`);
        ok(out.length <= MAX_COUNTRY_LABELS, "не больше предела");
        for (let i = 0; i < out.length; i++) {
          const a = out[i];
          if (!a.fill) ok(a.area >= COUNTRY_MIN_AREA, "площадь основной подписи");
          if (a.fill) ok(out.filter((o) => !o.fill).length < COUNTRY_MIN_LABELS, "добор — только когда основных меньше 5");
          ok(a.rect.x1 - a.rect.x0 <= a.span + 0.5, `ширина ${a.text}`);
          ok(inFrame({ w, h, cx: 0, cy: 0, R: 0 }, a.rect), "в кадре");
          eq(a.text, countryName(a.id));
          const m = fonts[a.font].metrics;
          const ll = projOf(w, h, lon, lat, z).invert!([a.x, a.y - (m.ascent - m.descent) / 2]);
          const feature = input.find((c) => c.id === a.id)!.feature;
          ok(ll && geoContains(feature, ll), `точка подписи ${a.text} внутри страны`);
          for (let j = i + 1; j < out.length; j++) ok(!overlaps(a.rect, out[j].rect), `пересечение ${a.text}/${out[j].text}`);
        }
      });
    }

test("Россия есть, Бельгии нет при (15, 50) ×1", () => {
  const ids = run(1920, 1080, 15, 50, 1).map((l) => l.id);
  ok(ids.includes("643"), "Россия");
  ok(!ids.includes("056"), "Бельгия");
});

// Детерминированный генератор.
function rng(seed: number) {
  let v = seed >>> 0;
  return () => ((v = (v * 1664525 + 1013904223) >>> 0) / 2 ** 32);
}

// Сетка с занятыми местами (медальоны раскладки): n кругов MEDAL в случайных точках кадра.
function busy(w: number, h: number, n: number, seed: number): Grid {
  const r = rng(seed);
  const g = new Grid();
  for (let i = 0; i < n; i++) g.add({ kind: "circle", x: r() * w, y: r() * h, r: 13 });
  return g;
}

// Свойство кэша кандидатов: результат вызова не зависит от истории вызовов с тем же видом —
// после любой последовательности сеток (в том числе сначала без добора, потом с добором)
// он равен результату со свежим кэшем.
const sig = (out: ReturnType<typeof run>) => out.map((l) => [l.id, l.x, l.y, l.font, l.fill]);
for (const [w, h] of [[564, 322], [1024, 576], [1366, 768]])
  for (const [lon, lat] of [[15, 50], [100, 40], [-60, -10], [20, 0]])
    for (const z of [1, 2]) {
      test(`кэш подписей без истории ${w}×${h} (${lon}, ${lat}) ×${z}`, () => {
        const shared = [...input];
        const seq = [0, 400, 0, 150, 800, 40];
        seq.forEach((n, i) => {
          const got = run(w, h, lon, lat, z, busy(w, h, n, i + 1), shared);
          const fresh = run(w, h, lon, lat, z, busy(w, h, n, i + 1), [...input]);
          eq(sig(got), sig(fresh), `вызов ${i + 1} (${n} кругов)`);
        });
      });
    }

test("кэш: сначала без добора, потом с добором (1024×576, (15, 50), ×2)", () => {
  const shared = [...input];
  const first = run(1024, 576, 15, 50, 2, new Grid(), shared);
  ok(!first.some((l) => l.fill), "первый вызов без добора");
  const g = () => {
    const grid = busy(1024, 576, 200, 7);
    grid.add({ kind: "rect", x0: 0, y0: 0, x1: 1024, y1: 470 }); // занято всё, кроме угла справа снизу
    grid.add({ kind: "rect", x0: 0, y0: 470, x1: 600, y1: 576 });
    return grid;
  };
  const after = run(1024, 576, 15, 50, 2, g(), shared);
  const fresh = run(1024, 576, 15, 50, 2, g(), [...input]);
  ok(fresh.some((l) => l.fill), "сетка требует добора: " + JSON.stringify(sig(fresh)));
  eq(sig(after), sig(fresh), "как со свежим кэшем");
});

done();
