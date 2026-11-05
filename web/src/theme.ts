import { useEffect } from "react";
import { useLang } from "./i18n";
import { useStored, type Theme } from "./storage";

// Тема и язык страницы. До первой отрисовки их ставит маленький скрипт в index.html (без
// мигания); здесь — то же самое при смене настройки и в других вкладках.

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  // «Как в системе» — без атрибута: работает @media (prefers-color-scheme) в tokens.css.
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}

export function useTheme(): Theme {
  return useStored((s) => s.theme);
}

export function useDocumentAppearance(): void {
  const theme = useTheme();
  const lang = useLang();
  useEffect(() => applyTheme(theme), [theme]);
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
}
