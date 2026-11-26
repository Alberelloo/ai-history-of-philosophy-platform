import { covers, labelInputs, PolityStore, type PolityLayer, type PolityResult } from "../../src/map/geo/polities";
import { done, eq, ok, test } from "../harness";

const src = { title: "Cliopatria", publisher: "Seshat", authors: ["A"], version: "v1", license: "CC BY 4.0", license_url: null, url: null };
const sq = { type: "Polygon" as const, coordinates: [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]] };
const item = (id: string, wikidata: string | null, status: "ru" | "original" = "ru") => ({ id, name: id, name_status: status, name_source: "label" as const, original: id, wikidata, from: 0, to: 0, geometry: sq });
const layer = (year: number, from: number, to: number): PolityLayer => ({ year, valid_from: from, valid_to: to, polities: [item(`p${from}`, null)], source: src });

// Управляемый сервер: каждый запрос ждёт release; счётчик одновременных.
function server(intervals: [number, number][], kind: "ok" | "unavailable" | "error" = "ok") {
  const calls: number[] = [];
  let open = 0;
  let maxOpen = 0;
  const pending: (() => void)[] = [];
  const fetcher = (year: number): Promise<PolityResult> => {
    calls.push(year);
    open += 1;
    maxOpen = Math.max(maxOpen, open);
    return new Promise((resolve) =>
      pending.push(() => {
        open -= 1;
        if (kind !== "ok") return resolve({ kind });
        const iv = intervals.find(([a, b]) => a <= year && year <= b) ?? [year, year];
        resolve({ kind: "ok", layer: layer(year, iv[0], iv[1]) });
      }),
    );
  };
  const release = async () => {
    while (pending.length) {
      pending.shift()!();
      await Promise.resolve();
      await Promise.resolve();
    }
  };
  return { fetcher, calls, release, maxOpen: () => maxOpen };
}

const IV: [number, number][] = [
  [1600, 1648],
  [1649, 1700],
  [1701, 1800],
];

{
  const s = server(IV);
  const store = new PolityStore(s.fetcher);
  test("до первого ответа — pending", () => eq(store.state.mode, "pending"));
  store.request(1650);
  store.request(1651);
  store.request(1750);
  test("одновременно один запрос", () => eq(s.calls, [1650]));
  await s.release();
  test("устаревший ответ не рисуется, текущий год запрошен следом", () => {
    eq(s.calls, [1650, 1750]);
    ok(store.state.layer === null || covers(store.state.layer, 1750), "нарисован слой не того года");
  });
  await s.release();
  test("слой года нарисован", () => {
    eq(store.state.mode, "historical");
    ok(store.state.layer && covers(store.state.layer, 1750), "нет слоя 1750");
    eq(s.maxOpen(), 1, "одновременных");
  });
  store.request(1660);
  test("год в известном интервале — без запроса", () => {
    eq(s.calls.length, 2);
    ok(store.state.layer && covers(store.state.layer, 1660), "слой 1660 из кэша");
  });
}

{
  const s = server(IV, "unavailable");
  const store = new PolityStore(s.fetcher);
  store.request(1650);
  await s.release();
  store.request(1750);
  test("503 — современная карта без пометки, запросов больше нет", () => {
    eq(store.state, { mode: "modern", layer: null, error: false });
    eq(s.calls, [1650]);
  });
}

{
  const s = server(IV, "error");
  const store = new PolityStore(s.fetcher);
  store.request(1650);
  await s.release();
  test("ошибка — современная карта с пометкой", () => eq(store.state, { mode: "modern", layer: null, error: true }));
  store.request(1650);
  test("тот же год повторно не спрашивается", () => eq(s.calls, [1650]));
  store.request(1700);
  test("смена года — снова запрос", () => eq(s.calls, [1650, 1700]));
}

{
  const s = server(Array.from({ length: 40 }, (_, i) => [i * 10, i * 10 + 9] as [number, number]));
  const store = new PolityStore(s.fetcher, 4);
  for (let i = 0; i < 10; i++) {
    store.request(i * 10);
    await s.release();
  }
  test("кэш ограничен", () => eq(store.cached(), 4));
}

test("одна подпись на QID, без QID — каждое", () => {
  const l: PolityLayer = { year: 1650, valid_from: 1650, valid_to: 1650, source: src, polities: [item("big", "Q1"), item("x", null, "original"), item("small", "Q1"), item("y", null)] };
  eq(labelInputs(l).map((i) => [i.id, i.italic]), [["big", false], ["x", true], ["y", false]]);
});

done();
