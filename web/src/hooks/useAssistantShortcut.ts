import { useEffect, useRef, type RefObject } from "react";

// Alt+Q — открыть ассистента (reader-panels.md, 5.1, 10.5):
// - при выделении в тексте главы — панель с фрагментом (S6);
// - без выделения — панель без фрагмента (S5); если панель уже открыта — фокус в поле вопроса.
// Внутри полей ввода, кроме поля вопроса, сочетание не перехватывается. Клавиша берётся по
// физическому коду (KeyQ), поэтому работает и в русской раскладке.
//
// Подключение в ReaderPage (делает интегратор, файл потока B):
//   useAssistantShortcut(textRef, openAssistant);

export const MAX_SELECTION = 4000;
// Поле вопроса ассистента: в нём Alt+Q не мешает, а без выделения фокус переходит сюда.
export const QUESTION_SELECTOR = "[data-assistant-question]";

export type ShortcutSelection = { text: string; paragraphs: string[] };

function editable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.matches(QUESTION_SELECTOR)) return false;
  return target.isContentEditable || target.matches("input, textarea, select");
}

// Текст выделения без служебных вставок (5.2): номера страниц, кнопки и плашки пропускаются.
export function selectionInside(article: HTMLElement | null): ShortcutSelection | null {
  const sel = window.getSelection();
  if (!article || !sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
  if (!article.contains(sel.anchorNode) || !article.contains(sel.focusNode)) return null;
  const range = sel.getRangeAt(0);
  const holder = document.createElement("div");
  holder.appendChild(range.cloneContents());
  holder.querySelectorAll("[data-nontext], button, .note-ref, .note-popup, .page-anchor").forEach((el) => el.remove());
  const text = (holder.textContent ?? "").replace(/\s+/g, " ").trim();
  if (!text) return null;
  const paragraphs: string[] = [];
  article.querySelectorAll<HTMLElement>("[data-paragraph]").forEach((el) => {
    if (range.intersectsNode(el) && !el.hasAttribute("data-nontext")) paragraphs.push(el.dataset.paragraph!);
  });
  return { text, paragraphs };
}

function focusQuestion(attempts = 20): void {
  const field = document.querySelector<HTMLElement>(QUESTION_SELECTOR);
  if (field) {
    field.focus();
    return;
  }
  if (attempts > 0) requestAnimationFrame(() => focusQuestion(attempts - 1));
}

export function useAssistantShortcut(
  article: RefObject<HTMLElement | null>,
  open: (selection: ShortcutSelection | null) => void,
): void {
  // Последняя функция открытия без переподписки на клавиатуру при каждой отрисовке.
  const openRef = useRef(open);
  openRef.current = open;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || e.code !== "KeyQ") return;
      if (e.repeat || editable(e.target)) return;
      e.preventDefault();
      const selection = selectionInside(article.current);
      if (selection && selection.text.length <= MAX_SELECTION) {
        openRef.current(selection);
        focusQuestion();
        return;
      }
      const field = document.querySelector<HTMLElement>(QUESTION_SELECTOR);
      if (field) {
        field.focus();
        return;
      }
      openRef.current(null);
      focusQuestion();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [article]);
}
