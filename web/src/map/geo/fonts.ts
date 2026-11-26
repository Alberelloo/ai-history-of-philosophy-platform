// Начертания глобуса (без d3: их ждёт страница карты до первой раскладки). Подписи персон —
// курсив Literata, подписи стран — Onest 500, добор подписей стран — тот же Onest мельче.
// Пока начертание не загружено, canvas меряет ширину по запасному шрифту, а SVG потом
// рисует настоящим: поэтому раскладка ждёт loadGlobeFonts, а глобус до этого aria-busy.

import { mapFonts } from "../layout";

export const NAME_FONT = mapFonts(false).workTitle;
export const COUNTRY_FONT = "500 10.5px Onest, Arial, sans-serif";
export const COUNTRY_FILL_FONT = "500 9px Onest, Arial, sans-serif"; // добор: не мельче 9 px
export const GLOBE_FONTS = [NAME_FONT, COUNTRY_FONT, COUNTRY_FILL_FONT];

// Ошибки загрузки не роняют глобус: раскладка остаётся по запасному шрифту.
export async function loadGlobeFonts(): Promise<void> {
  if (typeof document === "undefined" || !document.fonts) return;
  await Promise.all(GLOBE_FONTS.map((f) => document.fonts.load(f, "АаZz0").catch(() => [])));
  await document.fonts.ready;
}
