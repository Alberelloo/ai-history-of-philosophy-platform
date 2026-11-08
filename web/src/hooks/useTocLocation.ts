import { useEffect, useState, type RefObject } from "react";

// Отметка текущего места в оглавлении (chapter-reading «Оглавление», reader-panels.md 8.1; T32).
// Возвращает id раздела у верхнего края: последний раздел главы, заголовок которого дошёл до
// верха окна (с учётом отступа прокрутки); выше первого раздела — null. Пункт раздела в
// оглавлении получает aria-current="location" (Toc в ReaderToc.tsx), глава — "page".
//
// Переход к разделу (адрес #s-<id>, в том числе из слоя оглавления K3/K4) ставит фокус на
// заголовок раздела: слой закрылся, и фокус не теряется в начале страницы (10.4).
export function useTocLocation(
  container: RefObject<HTMLElement | null>,
  chapterId: string | null,
  anchor: string,
): string | null {
  const [current, setCurrent] = useState<string | null>(null);

  useEffect(() => {
    if (!chapterId) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      const pad = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
      let id: string | null = null;
      const headings = container.current?.querySelectorAll<HTMLElement>('h2[id^="s-"], h3[id^="s-"]') ?? [];
      for (const heading of Array.from(headings)) {
        if (heading.getBoundingClientRect().top <= pad + 8) id = heading.id.slice(2);
      }
      setCurrent(id);
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
    };
  }, [container, chapterId, anchor]);

  useEffect(() => {
    if (!chapterId || !anchor.startsWith("s-")) return;
    const heading = document.getElementById(anchor);
    if (!heading) return;
    if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1");
    heading.focus({ preventScroll: true });
  }, [chapterId, anchor]);

  return current;
}
