// Места для ?fixture=dense&view=globe — только ручной просмотр глобуса без сервиса знаний.
// Тесты ожиданий отсюда не берут: данные задаёт каждый тест сам. Места — города, где жили
// философы плотного набора (fixture.ts); годы деятельности упрощены, для проверки вида,
// не для цитирования. Модуль грузится вместе с фрагментом глобуса.

import type { GeoLayer, GeoPlacement } from "./api";

const PLACES: [string, string, number, number][] = [
  ["bordeaux", "Бордо", 44.84, -0.58], ["london", "Лондон", 51.51, -0.13], ["pisa", "Пиза", 43.72, 10.4],
  ["florence", "Флоренция", 43.77, 11.26], ["paris", "Париж", 48.86, 2.35], ["malmesbury", "Малмсбери", 51.58, -2.1],
  ["digne", "Динь", 44.09, 6.24], ["lahaye", "Ла-Э", 46.97, 0.7], ["amsterdam", "Амстердам", 52.37, 4.9],
  ["stockholm", "Стокгольм", 59.33, 18.07], ["clermont", "Клермон", 45.78, 3.08], ["thehague", "Гаага", 52.08, 4.3],
  ["wrington", "Рингтон", 51.36, -2.76], ["oxford", "Оксфорд", 51.75, -1.26], ["cambridge", "Кембридж", 52.21, 0.12],
  ["leipzig", "Лейпциг", 51.34, 12.37], ["hanover", "Ганновер", 52.37, 9.74], ["rotterdam", "Роттердам", 51.92, 4.48],
  ["naples", "Неаполь", 40.85, 14.27], ["breslau", "Бреслау", 51.11, 17.03], ["halle", "Галле", 51.48, 11.97],
  ["dublin", "Дублин", 53.35, -6.26], ["geneva", "Женева", 46.2, 6.14], ["glasgow", "Глазго", 55.86, -4.25],
  ["edinburgh", "Эдинбург", 55.95, -3.19], ["berlin", "Берлин", 52.52, 13.4], ["konigsberg", "Кёнигсберг", 54.71, 20.51],
  ["dessau", "Дессау", 51.83, 12.24], ["dusseldorf", "Дюссельдорф", 51.23, 6.78], ["weimar", "Веймар", 50.98, 11.33],
  ["jena", "Йена", 50.93, 11.59], ["bergerac", "Бержерак", 44.85, 0.48], ["stuttgart", "Штутгарт", 48.78, 9.18],
  ["leonberg", "Леонберг", 48.8, 9.01], ["danzig", "Данциг", 54.35, 18.65], ["frankfurt", "Франкфурт", 50.11, 8.68],
  ["mohrungen", "Морунген", 53.92, 19.93], ["rammenau", "Рамменау", 51.16, 14.13], ["saintmalo", "Сен-Мало", 48.65, -2.03],
];

// Персона: рождение, деятельность (место, с, по) — по одному на персону для простоты.
const LIVES: [string, string, string, number, number][] = [
  ["montaigne", "bordeaux", "bordeaux", 1554, 1592], ["bacon", "london", "london", 1580, 1626],
  ["galileo", "pisa", "florence", 1610, 1642], ["mersenne", "paris", "paris", 1611, 1648],
  ["hobbes", "malmesbury", "london", 1608, 1679], ["gassendi", "digne", "paris", 1641, 1655],
  ["descartes", "lahaye", "amsterdam", 1628, 1649], ["arnauld", "paris", "paris", 1641, 1694],
  ["pascal", "clermont", "paris", 1631, 1662], ["spinoza", "amsterdam", "thehague", 1670, 1677],
  ["locke", "wrington", "oxford", 1652, 1704], ["malebranche", "paris", "paris", 1660, 1715],
  ["newton", "london", "cambridge", 1661, 1727], ["leibniz", "leipzig", "hanover", 1676, 1716],
  ["bayle", "bergerac", "rotterdam", 1681, 1706], ["vico", "naples", "naples", 1699, 1744],
  ["shaftesbury", "london", "london", 1690, 1713], ["wolff", "breslau", "halle", 1706, 1754],
  ["berkeley", "dublin", "dublin", 1700, 1753], ["montesquieu", "bordeaux", "paris", 1721, 1755],
  ["voltaire", "paris", "geneva", 1755, 1778], ["hutcheson", "dublin", "glasgow", 1730, 1746],
  ["lamettrie", "saintmalo", "berlin", 1748, 1751], ["reid", "glasgow", "glasgow", 1764, 1796],
  ["hume", "edinburgh", "edinburgh", 1730, 1776], ["rousseau", "geneva", "paris", 1742, 1778],
  ["diderot", "paris", "paris", 1735, 1784], ["condillac", "paris", "paris", 1740, 1780],
  ["baumgarten", "berlin", "frankfurt", 1740, 1762], ["helvetius", "paris", "paris", 1738, 1771],
  ["dalembert", "paris", "paris", 1740, 1783], ["kant", "konigsberg", "konigsberg", 1755, 1804],
  ["mendelssohn", "dessau", "berlin", 1743, 1786], ["hamann", "konigsberg", "konigsberg", 1759, 1788],
  ["jacobi", "dusseldorf", "dusseldorf", 1770, 1819], ["herder", "mohrungen", "weimar", 1776, 1803],
  ["fichte", "rammenau", "jena", 1794, 1814],
  ["hegel", "stuttgart", "berlin", 1818, 1831], ["schelling", "leonberg", "jena", 1798, 1854],
  ["schopenhauer", "danzig", "frankfurt", 1833, 1860],
];

let n = 0;
const row = (entity: string, place: string, role: GeoPlacement["role"], from: number | null, to: number | null, generated = false): GeoPlacement => ({
  entity,
  place,
  role,
  from,
  to,
  status: generated ? "generated" : "sourced",
  generated,
  statement: `s_fixture_${String(++n).padStart(3, "0")}`,
});

export const DENSE_GEO: GeoLayer = {
  places: PLACES.map(([id, label, lat, lon]) => ({ id, label, lat, lon, status: "sourced" })),
  placements: LIVES.flatMap(([who, birth, work, from, to]) => [
    row(who, birth, "birth", null, null),
    // Деятельность Бейля и Вико — «достроено моделью»: полые кольца при ручном просмотре.
    row(who, work, "activity", from, to, who === "bayle" || who === "vico"),
  ]),
  unplaced: ["biran"], // Мен де Биран — без места: «1 без места» при ручном просмотре
  truncated: false,
  limit: 400,
};
