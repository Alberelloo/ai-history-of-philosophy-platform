import { useEffect, useState } from "react";

// Замеры для раскладки и ширины панели (layout.ts): ширина окна, корневой кегль и 1ch шрифта
// чтения. На окнах шире 1920px кегль растёт (9.7), и все величины в rem/ch масштабируются.
export type Metrics = { width: number; root: number; ch: number };

export function useLayoutMetrics(): Metrics {
  const [metrics, setMetrics] = useState<Metrics>(() => ({ width: window.innerWidth, root: 16, ch: 11 }));
  useEffect(() => {
    const measure = () => {
      const root = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
      const probe = document.createElement("span");
      probe.style.cssText = "position:absolute;visibility:hidden;width:1ch;font:var(--type-read-body);";
      document.body.appendChild(probe);
      const ch = probe.getBoundingClientRect().width || 11;
      probe.remove();
      setMetrics({ width: window.innerWidth, root, ch });
    };
    measure();
    // До загрузки Literata ширина 1ch берётся из запасного шрифта и отличается: после
    // загрузки шрифта раскладка пересчитывается (document.fonts.ready).
    document.fonts?.ready.then(measure).catch(() => {});
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);
  return metrics;
}
