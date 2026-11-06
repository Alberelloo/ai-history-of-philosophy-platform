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

// Сообщение об ошибке сервера: по коду из каталога, иначе текст сервера, иначе общее.
export function errorText(t: Catalog, kind: string | null | undefined, fallback?: string | null): string {
  return pick(t.errors, kind) ?? (fallback || t.errors.generic);
}

// Названия онтологии по коду; неизвестный код (тип добавлен в реестр во время работы) —
// подпись сервера.
type RelationNames = Record<string, { title: string; inverse?: string } | undefined>;

export function sectionTitle(t: Catalog, code: string, fallback: string): string {
  return pick(t.onto.sections, code) ?? fallback;
}

export function relationTitle(t: Catalog, code: string | undefined, inverse: boolean, fallback: string): string {
  const names = code ? (t.onto.relations as RelationNames)[code] : undefined;
  if (!names) return fallback;
  return inverse ? (names.inverse ?? names.title) : names.title;
}

export function recipeTitle(t: Catalog, code: string, fallback?: string): string {
  return pick(t.onto.recipes, code) ?? fallback ?? code;
}

// Кто так считает: «распространённое мнение» переводится, имена — контент.
export function whoLabel(t: Catalog, a: { who: string; kind?: string }): string {
  return a.kind === "common" ? t.card.commonOpinion : a.who;
}
