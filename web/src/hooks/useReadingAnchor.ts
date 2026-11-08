import { useCallback, useEffect, useLayoutEffect, useRef, type RefObject } from "react";

// Привязка места чтения при перестройке раскладки (reader-panels.md, 2.5; T4). Опорный абзац —
// первый, у которого нижний край ниже отступа прокрутки. Он запоминается при каждой прокрутке,
// а когда меняется ключ раскладки (режим K1–K4, ширина текста, ширина навигации), прокрутка в
// том же кадре, до отрисовки, возвращает абзац на прежнее расстояние от верха окна.
//
// Прежний код в ReaderPage запоминал абзац только при смене раскладки: после прокрутки опорным
// оставался абзац с прошлой перестройки, и открытие панели отбрасывало читателя назад.
//
// ``key`` — null, пока глава не загружена.
export function useReadingAnchor(container: RefObject<HTMLElement | null>, key: string | null) {
  const saved = useRef<{ el: HTMLElement; top: number } | null>(null);
  const lastKey = useRef<string | null>(null);

  const capture = useCallback(() => {
    const root = container.current;
    if (!root) return;
    const pad = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
    const paragraphs = root.querySelectorAll<HTMLElement>("[data-paragraph]");
    const el = Array.from(paragraphs).find((p) => p.getBoundingClientRect().bottom > pad);
    saved.current = el ? { el, top: el.getBoundingClientRect().top } : null;
  }, [container]);

  useLayoutEffect(() => {
    if (key === null) {
      lastKey.current = null;
      saved.current = null;
      return;
    }
    if (lastKey.current !== null && lastKey.current !== key) {
      const anchor = saved.current;
      if (anchor && anchor.el.isConnected) {
        const delta = anchor.el.getBoundingClientRect().top - anchor.top;
        if (Math.abs(delta) >= 1) window.scrollBy(0, delta);
      }
    }
    lastKey.current = key;
    capture();
  }, [key, capture]);

  const loaded = key !== null;
  useEffect(() => {
    if (!loaded) return;
    window.addEventListener("scroll", capture, { passive: true });
    return () => window.removeEventListener("scroll", capture);
  }, [loaded, capture]);
}
