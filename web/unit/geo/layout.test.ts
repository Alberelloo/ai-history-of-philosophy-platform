import { EVENT_MARK, frameLayout, inCircle, inFrame, layoutMarkers, MAX_SHIFT, MEDAL, overlaps, shiftLayout, type Frame, type LPlace, type Shape } from "../../src/map/geo/layout";
import { done, eq, ok, test } from "../harness";

const measure = (t: string) => t.length * 7;
const metrics = { ascent: 13, descent: 4 };

// Детерминированный генератор.
function rng(seed: number) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32);
}

function drawnShapes(l: ReturnType<typeof layoutMarkers>): Shape[] {
  const out: Shape[] = [];
  for (const s of l.persons) {
    if (s.hidden || s.packed) continue;
    out.push({ kind: "circle", x: s.x, y: s.y, r: MEDAL / 2 });
    ok(s.label, `подпись у ${s.id}`);
    out.push(s.label!.rect);
  }
  for (const b of l.badges) if (!b.hidden) out.push({ kind: "circle", x: b.x, y: b.y, r: MEDAL / 2 });
  for (const e of l.events) if (!e.hidden) out.push({ kind: "circle", x: e.x, y: e.y, r: EVENT_MARK / 2 });
  return out;
}

test("кольцо 1 вокруг места без пересечений", () => {
  eq(overlaps({ kind: "circle", x: 0, y: 0, r: 13 }, { kind: "circle", x: 30 * Math.sin(Math.PI / 3), y: 15, r: 13 }), false);
  eq(overlaps({ kind: "circle", x: 0, y: 0, r: 13 }, { kind: "circle", x: 25.4, y: 0, r: 13 }), true);
  eq(overlaps({ kind: "rect", x0: 0, y0: 0, x1: 10, y1: 10 }, { kind: "rect", x0: 9.6, y0: 0, x1: 20, y1: 10 }), false);
  eq(overlaps({ kind: "circle", x: 0, y: 0, r: 13 }, { kind: "rect", x0: 12.6, y0: -5, x1: 20, y1: 5 }), false);
});

for (const [w, h] of [[1024, 576], [1366, 768], [1920, 1080]]) {
  for (const seed of [1, 2, 3, 4, 5]) {
    test(`инварианты раскладки ${w}×${h} seed ${seed}`, () => {
      const r = rng(seed * 97 + w);
      const R = Math.min(w, h) / 2 - 16;
      const f: Frame = { w, h, cx: w / 2, cy: h / 2, R };
      const nPlaces = 1 + Math.floor(r() * 40);
      const places: LPlace[] = [];
      for (let i = 0; i < nPlaces; i++) {
        const a = r() * Math.PI * 2;
        const d = Math.sqrt(r()) * R * (seed === 5 ? 0.15 : 1);
        places.push({ id: `p${i}`, x: f.cx + Math.cos(a) * d, y: f.cy + Math.sin(a) * d, visible: r() > 0.1 });
      }
      const persons = [];
      for (let i = 0; i < 1 + Math.floor(r() * 120); i++) persons.push({ id: `x${i}`, place: `p${Math.floor(r() * nPlaces)}`, name: "Имя".repeat(1 + Math.floor(r() * 3)) });
      const events = [{ id: "e1", place: "p0" }];
      const l = layoutMarkers({ places, persons, events, frame: f, measure, metrics, maxPersons: 80 });
      const shapes = drawnShapes(l);
      for (let i = 0; i < shapes.length; i++) {
        ok(inFrame(f, shapes[i]), `в кадре ${i}`);
        for (let j = i + 1; j < shapes.length; j++) ok(!overlaps(shapes[i], shapes[j]), `пересечение ${i}/${j}`);
      }
      const byId = new Map(places.map((p) => [p.id, p]));
      let visiblePersons = 0;
      for (const p of persons) if (byId.get(p.place)!.visible) visiblePersons += 1;
      let drawn = 0;
      for (const s of l.persons) {
        if (s.hidden || s.packed) {
          if (!s.hidden) ok(s.badge != null, `свёрнут без значка ${s.id}`);
          continue;
        }
        drawn += 1;
        ok(inCircle(f, s.x, s.y), "центр в круге");
        const a = byId.get(s.place)!;
        ok(Math.hypot(s.x - a.x, s.y - a.y) <= MAX_SHIFT + 0.02, "сдвиг");
      }
      const counted = l.badges.reduce((n, b) => n + b.count, 0);
      const hiddenVisible = l.persons.filter((s) => s.hidden && byId.get(s.place)!.visible).length;
      eq(drawn + counted + hiddenVisible, visiblePersons, "каждая персона — медальон или в значке");
      eq(hiddenVisible, 0, "скрытых персон у видимых мест нет");
      eq(l.persons.length, Math.min(80, persons.length), "медальонов в DOM");
      const again = layoutMarkers({ places, persons, events, frame: f, measure, metrics, maxPersons: 80 });
      eq(again.persons.map((s) => [s.x, s.y, s.packed]), l.persons.map((s) => [s.x, s.y, s.packed]), "детерминированность");
    });
  }
}

test("перетаскивание: вышедшие за круг скрыты", () => {
  const f: Frame = { w: 400, h: 400, cx: 200, cy: 200, R: 180 };
  const places = [{ id: "a", x: 200, y: 200, visible: true }];
  const persons = Array.from({ length: 7 }, (_, i) => ({ id: `x${i}`, place: "a", name: "Кант" }));
  const l = layoutMarkers({ places, persons, events: [], frame: f, measure, metrics });
  const moved = shiftLayout(l, [{ id: "a", x: 375, y: 200, visible: true }], f);
  for (const s of moved.persons) if (!s.hidden) ok(inCircle(f, s.x, s.y) && inFrame(f, { kind: "circle", x: s.x, y: s.y, r: 13 }), "видимый внутри");
  ok(moved.persons.some((s) => s.hidden), "хотя бы один скрыт");
  ok(moved.persons.every((s) => s.label === null), "подписей нет");
});

test("кадр движения: раскладка покоя только своей сцены", () => {
  const f: Frame = { w: 400, h: 400, cx: 200, cy: 200, R: 180 };
  const places = [{ id: "a", x: 200, y: 200, visible: true }];
  const sceneA = { year: 1700 };
  const sceneB = { year: 1801 };
  const mk = (ids: string[]) => () => layoutMarkers({ places, persons: ids.map((id) => ({ id, place: "a", name: "Кант" })), events: [], frame: f, measure, metrics });
  let calls = 0;
  const count = (fn: () => ReturnType<typeof layoutMarkers>) => () => (calls++, fn());
  const rest0 = frameLayout(null, sceneA, false, places, f, count(mk(["descartes"]))).rest;
  eq(calls, 1, "покой — полная раскладка");
  const same = frameLayout(rest0, sceneA, true, places, f, count(mk(["descartes"])));
  eq(calls, 1, "та же сцена в движении — без полной раскладки");
  eq(same.rest, rest0, "раскладка покоя та же");
  const other = frameLayout(rest0, sceneB, true, places, f, count(mk(["hume", "kant"])));
  eq(calls, 2, "сцена сменилась в движении — полная раскладка");
  eq(other.layout.persons.map((s) => s.id), ["hume", "kant"], "медальоны новой сцены, прошлой нет");
  ok(other.layout.persons.every((s) => s.label === null), "в движении без подписей");
  eq(other.rest.key, sceneB, "ключ раскладки покоя — новая сцена");
});

test("ни медальонов, ни значков: значок в точке привязки, персоны в счёте", () => {
  // Медальон не помещается в кадр 20×20 ни в одной позиции; значок — в точке привязки.
  const f: Frame = { w: 20, h: 20, cx: 10, cy: 10, R: 9 };
  const places = [{ id: "a", x: 10, y: 10, visible: true }];
  const persons = Array.from({ length: 3 }, (_, i) => ({ id: `p${i}`, place: "a", name: "Кант" }));
  const l = layoutMarkers({ places, persons, events: [], frame: f, measure, metrics, maxPersons: 2 });
  eq(l.badges.length, 1, "один значок");
  eq([l.badges[0].x, l.badges[0].y, l.badges[0].count], [10, 10, 3], "в точке привязки, все три персоны (одна сверх предела)");
  ok(l.persons.every((s) => s.packed && !s.hidden && s.badge === 0), "каждая — ровно в одном значке");
});

test("персона без имени — медальон без подписи", () => {
  const f: Frame = { w: 400, h: 400, cx: 200, cy: 200, R: 180 };
  const l = layoutMarkers({ places: [{ id: "a", x: 200, y: 200, visible: true }], persons: [{ id: "x", place: "a", name: null }], events: [], frame: f, measure, metrics });
  eq([l.persons[0].hidden, l.persons[0].packed, l.persons[0].label], [false, false, null], "медальон без подписи");
});

done();
