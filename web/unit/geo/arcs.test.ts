import { arcBetween } from "../../src/map/geo/arcs";
import { inCircle, type Frame } from "../../src/map/geo/layout";
import { homeView } from "../../src/map/geo/projection";
import { done, eq, near, ok, test } from "../harness";

function rng(seed: number) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32);
}
const nums = (d: string) => d.match(/-?\d+(\.\d+)?/g)!.map(Number);

for (const [w, h] of [[1024, 576], [1366, 768], [1920, 1080]])
  test(`концы, стрелка и кривая в круге и кадре ${w}×${h}`, () => {
    const r = rng(w);
    const f: Frame = { w, h, cx: w / 2, cy: h / 2, R: (Math.min(w, h) / 2 - 16) * (1 + r() * 2) };
    let checked = 0;
    for (let i = 0; i < 400; i++) {
      const pt = () => {
        for (;;) {
          const x = 13 + r() * (w - 26);
          const y = 13 + r() * (h - 26);
          if (inCircle(f, x, y)) return { kind: "circle" as const, x: Math.round(x * 100) / 100, y: Math.round(y * 100) / 100, r: 13 };
        }
      };
      const a = pt();
      const b = pt();
      const arc = arcBetween(a, b, f);
      if (Math.hypot(a.x - b.x, a.y - b.y) <= 13.5) {
        eq(arc, null, "слишком близко");
        continue;
      }
      ok(arc, "дуга есть");
      const [x0, y0, cx, cy, x1, y1] = nums(arc!.d);
      eq([x0, y0, x1, y1], [a.x, a.y, b.x, b.y], "концы");
      const [tx, ty] = nums(arc!.arrow);
      near(Math.hypot(tx - b.x, ty - b.y), 13, 1, "вершина на окружности");
      let onCurve = Infinity;
      for (let k = 0; k <= 2000; k++) {
        const t = k / 2000;
        const u = 1 - t;
        const px = u * u * x0 + 2 * u * t * cx + t * t * x1;
        const py = u * u * y0 + 2 * u * t * cy + t * t * y1;
        onCurve = Math.min(onCurve, Math.hypot(px - tx, py - ty));
        ok(inCircle({ ...f, R: f.R + 0.05 }, px, py) && px >= -0.05 && py >= -0.05 && px <= w + 0.05 && py <= h + 0.05, "кривая внутри");
      }
      ok(onCurve <= 1, "вершина на кривой");
      checked++;
    }
    ok(checked > 300, "проверено");
  });

test("исходный вид: приближение из ряда и не больше 4", () => {
  const f = { cx: 683, cy: 384, radius: 360 };
  const v = homeView([{ lat: 37.98, lon: 23.73 }, { lat: 41.9, lon: 12.5 }], f, 1366, 768, 26);
  ok([1, 1.25, 1.5625, 1.953125, 2.44140625, 3.0517578125, 3.814697265625].some((z) => Math.abs(z - v.zoom) < 1e-9), `ряд ${v.zoom}`);
  ok(v.zoom > 1, "приближено");
  eq(homeView([{ lat: 51.5, lon: -0.1 }, { lat: 42.36, lon: -71.06 }], f, 1366, 768, 26).zoom >= 1, true);
  eq(homeView([], f, 1366, 768, 26).zoom, 1);
});

done();
