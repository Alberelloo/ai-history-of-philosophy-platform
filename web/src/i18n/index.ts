import { useStored, type Lang } from "../storage";
import { en } from "./en";
import { ru, type Catalog } from "./ru";

// Язык интерфейса: выбранный читателем или, пока он не выбрал, язык браузера.

const CATALOGS: Record<Lang, Catalog> = { ru, en };

export function browserLang(): Lang {
  const language = typeof navigator === "undefined" ? "" : navigator.language || "";
  return language.toLowerCase().startsWith("ru") ? "ru" : "en";
}

export function useLang(): Lang {
  return useStored((s) => s.lang) ?? browserLang();
}

export function useT(): Catalog {
  return CATALOGS[useLang()];
}

export function catalog(lang: Lang): Catalog {
  return CATALOGS[lang];
}

// Строка из справочника по коду сервера (kind, reason, тип сущности); нет такой — undefined.
export function pick(map: object, key: string | null | undefined): string | undefined {
  if (key === null || key === undefined) return undefined;
  const value = (map as Record<string, unknown>)[key];
  return typeof value === "string" ? value : undefined;
}

export type { Catalog };
