import { geoOrthographic, geoPath } from "d3-geo";
import { countryName } from "../../src/map/geo/countries";
import { COUNTRY_MIN_AREA, Grid, inFrame, layoutCountries, MAX_COUNTRY_LABELS, overlaps, type Frame } from "../../src/map/geo/layout";
import { COUNTRIES } from "../../src/map/geo/world";
import { done, eq, ok, test } from "../harness";

const measure = (t: string) => t.length * 6.5;
const metrics = { ascent: 9, descent: 3 };
const input = COUNTRIES.filter((c) => c.id && countryName(c.id)).map((c) => ({ id: c.id!, name: countryName(c.id)!, feature: c.feature }));

function run(w: number, h: number, lon: number, lat: number, zoom: number) {
  const R = (Math.min(w, h) / 2 - 16) * zoom;
  const projection = geoOrthographic().rotate([-lon, -lat]).scale(R).translate([w / 2, h / 2]).clipAngle(90).clipExtent([[0, 0], [w, h]]);
  const f: Frame = { w, h, cx: w / 2, cy: h / 2, R };
  return layoutCountries(input, geoPath(projection), projection, f, new Grid(), measure, metrics);
}

for (const [w, h] of [[1024, 576], [1366, 768], [1920, 1080]])
  for (const [lon, lat] of [[15, 50], [100, 40], [-60, -10], [20, 0], [40, 50]])
    for (const z of [1, 2]) {
      test(`подписи стран ${w}×${h} (${lon}, ${lat}) ×${z}`, () => {
        const out = run(w, h, lon, lat, z);
        ok(out.length >= 5, `подписей ${out.length}`);
        ok(out.length <= MAX_COUNTRY_LABELS, "не больше предела");
        for (let i = 0; i < out.length; i++) {
          const a = out[i];
          ok(a.area >= COUNTRY_MIN_AREA, "площадь");
          ok(a.rect.x1 - a.rect.x0 <= a.span + 0.5, `ширина ${a.text}`);
          ok(inFrame({ w, h, cx: 0, cy: 0, R: 0 }, a.rect), "в кадре");
          eq(a.text, countryName(a.id));
          for (let j = i + 1; j < out.length; j++) ok(!overlaps(a.rect, out[j].rect), `пересечение ${a.text}/${out[j].text}`);
        }
      });
    }

test("Россия есть, Бельгии нет при (15, 50) ×1", () => {
  const ids = run(1920, 1080, 15, 50, 1).map((l) => l.id);
  ok(ids.includes("643"), "Россия");
  ok(!ids.includes("056"), "Бельгия");
});

done();
