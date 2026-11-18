// Измеритель ширины текста для раскладки карты: canvas measureText с кэшем.
// Шрифты — Literata и Onest, как в --font-read и --font-ui (styles/tokens.css); пока они
// не загружены, ширина считается по запасному шрифту — после загрузки кэш нужно сбросить
// и разложить карту заново (loadMapFonts).

import { allMapFonts, approxMeasure, type Measure } from "./layout";

export type CanvasMeasure = Measure & { clear: () => void };

export function canvasMeasure(): CanvasMeasure {
  const cache = new Map<string, number>();
  let ctx: CanvasRenderingContext2D | null | undefined;
  const context = () => {
    if (ctx === undefined) ctx = typeof document !== "undefined" ? document.createElement("canvas").getContext("2d") : null;
    return ctx;
  };
  const m = ((text: string, font: string) => {
    const key = font + "\u0000" + text;
    let w = cache.get(key);
    if (w == null) {
      const c = context();
      if (c) {
        c.font = font;
        w = c.measureText(text).width;
      } else w = approxMeasure(text, font);
      cache.set(key, w);
    }
    return w;
  }) as CanvasMeasure;
  m.clear = () => cache.clear();
  return m;
}

// Дождаться начертаний карты (document.fonts). Ошибки загрузки не роняют карту:
// раскладка остаётся по запасному шрифту.
export async function loadMapFonts(): Promise<void> {
  if (typeof document === "undefined" || !document.fonts) return;
  await Promise.all(allMapFonts().map((f) => document.fonts.load(f, "АаZz0").catch(() => [])));
  await document.fonts.ready;
}
