import topology from "world-atlas/countries-110m.json";
import data from "../../src/map/geo/countries.ru.json";
import { countryAt, countryName, countryOf } from "../../src/map/geo/countries";
import { BORDERS, COUNTRIES, COUNTRY_COUNT, LAND } from "../../src/map/geo/world";
import { done, eq, ok, test } from "../harness";

const geoms = (topology as unknown as { objects: { countries: { geometries: { id?: string }[] } } }).objects.countries.geometries;
const ids = geoms.filter((g) => g.id).map((g) => String(g.id));
const names = data.names as Record<string, string>;

test("словарь полон и без лишних ключей", () => {
  eq(ids.filter((id) => !names[id]), [], "без названия:");
  eq(Object.keys(names).filter((k) => !ids.includes(k)), [], "лишние:");
  eq(ids.length, 174, "стран с кодом");
});

test("названия — кириллица, пробел, дефис, точка, апостроф", () => {
  const bad = Object.values(names).filter((v) => !/^[А-Яа-яЁё][А-Яа-яЁё \-.'’]*$/u.test(v));
  eq(bad, []);
  eq(names["384"], "Кот-д’Ивуар");
});

test("overrides ссылаются на существующие коды", () => {
  eq(Object.keys(data.overrides).filter((k) => !names[k]), []);
});

test("данные карты", () => {
  eq(COUNTRY_COUNT, 177);
  eq(COUNTRIES.filter((c) => c.id == null).length, 3);
  ok(BORDERS.coordinates.length > 0, "есть границы");
  ok(LAND.features.length > 0, "есть суша");
});

const cases: [string, number, number, string | null][] = [
  ["Афины", 37.98, 23.73, "Греция"],
  ["Кёнигсберг", 54.71, 20.51, "Россия"],
  ["Эдинбург", 55.95, -3.19, "Великобритания"],
  ["Амстердам", 52.37, 4.9, "Нидерланды"],
  ["Париж", 48.86, 2.35, "Франция"],
  ["Рим", 41.9, 12.5, "Италия"],
  ["Стокгольм", 59.33, 18.07, "Швеция"],
  ["Александрия", 31.2, 29.92, "Египет"],
  ["Сиракузы", 37.08, 15.29, "Италия"],
  ["Атлантика", 0, -30, null],
  ["Приштина", 42.66, 21.17, null],
];
for (const [name, lat, lon, want] of cases) {
  test(`страна: ${name}`, () => eq(countryAt(lat, lon)?.name ?? null, want));
}

test("края и мусор без исключений", () => {
  for (const [lat, lon] of [[90, 180], [-90, -180], [0, 180], [0, -180], [NaN, 0], [0, Infinity]] as [number, number][]) {
    const r = countryAt(lat, lon);
    ok(r === null || Object.values(names).includes(r.name), `${lat},${lon}`);
  }
});

test("кэш по месту", () => {
  const a = countryOf({ id: "athens", lat: 37.98, lon: 23.73 });
  eq(a?.id, "300");
  eq(countryOf({ id: "athens", lat: 37.98, lon: 23.73 }), a);
  eq(countryName("300"), "Греция");
  eq(countryName(null), null);
  eq(countryName("999"), null);
});

done();
