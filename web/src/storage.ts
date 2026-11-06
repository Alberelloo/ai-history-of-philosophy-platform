import { useEffect, useState } from "react";

// Всё, что продукт хранит о читателе, — в одном хранилище браузера с версией формата:
// настройки, выбранный источник, места чтения, диалоги, отметка об уведомлении. На сервере
// ничего этого нет: настройки уходят с каждым запросом.
//
// Новая версия формата переносит старые данные; повреждённые сбрасываются к значениям по
// умолчанию. Без хранилища (приватный режим) состояние живёт в памяти вкладки, а читатель
// видит, что настройки не сохранятся.

const KEY = "philograph:v2";
const LEGACY = { state: "philograph:v1", scope: "philograph:scope:v1", dialog: "philograph:dialog:v1" };
const EVENT = "philograph:state";
// Диалоги — больше всего данных; при превышении удаляются самые старые.
export const MAX_DIALOG_CHARS = 200_000;

export type Position = { chapterId: string; paragraphId?: string };
export type Settings = { generation: boolean; sourcesOnly: boolean; onlyTextbook: boolean };
export type Theme = "light" | "dark" | "system";
export type Lang = "ru" | "en";
export const THEMES: Theme[] = ["light", "dark", "system"];
export const LANGS: Lang[] = ["ru", "en"];
export type State = {
  version: 2;
  settings: Settings;
  theme: Theme; // «как в системе» — по умолчанию
  lang?: Lang; // не выбран — язык браузера
  currentSource?: string;
  positions: Record<string, Position>;
  dialogs: unknown[][]; // последний — текущий
  notice?: string; // версия закрытого уведомления
};

export const DEFAULT_SETTINGS: Settings = { generation: true, sourcesOnly: false, onlyTextbook: false };
const empty = (): State => ({
  version: 2,
  settings: { ...DEFAULT_SETTINGS },
  theme: "system",
  positions: {},
  dialogs: [[]],
});

let memory: State = empty();
let persistent = probe();

function probe(): boolean {
  try {
    const test = "philograph:probe";
    window.localStorage.setItem(test, "1");
    window.localStorage.removeItem(test);
    return true;
  } catch {
    return false;
  }
}

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

// Приводит что угодно к правильному состоянию: чужие и испорченные поля — к значениям по умолчанию.
function normalize(raw: unknown): State {
  const data = object(raw);
  const settings = object(data.settings);
  const bool = (v: unknown, fallback: boolean) => (typeof v === "boolean" ? v : fallback);
  const positions: Record<string, Position> = {};
  Object.entries(object(data.positions)).forEach(([source, p]) => {
    const position = object(p);
    if (typeof position.chapterId === "string") {
      positions[source] = {
        chapterId: position.chapterId,
        paragraphId: typeof position.paragraphId === "string" ? position.paragraphId : undefined,
      };
    }
  });
  const dialogs = Array.isArray(data.dialogs) ? data.dialogs.filter(Array.isArray) : [];
  return {
    version: 2,
    settings: {
      generation: bool(settings.generation, DEFAULT_SETTINGS.generation),
      sourcesOnly: bool(settings.sourcesOnly, DEFAULT_SETTINGS.sourcesOnly),
      onlyTextbook: bool(settings.onlyTextbook, DEFAULT_SETTINGS.onlyTextbook),
    },
    theme: THEMES.includes(data.theme as Theme) ? (data.theme as Theme) : "system",
    lang: LANGS.includes(data.lang as Lang) ? (data.lang as Lang) : undefined,
    currentSource: typeof data.currentSource === "string" ? data.currentSource : undefined,
    positions,
    dialogs: dialogs.length ? (dialogs as unknown[][]) : [[]],
    notice: typeof data.notice === "string" ? data.notice : undefined,
  };
}

function parse(text: string | null): unknown {
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return undefined; // повреждено — значения по умолчанию
  }
}

// Перенос из формата 1: три отдельных ключа.
function migrate(): State | undefined {
  const old = object(parse(window.localStorage.getItem(LEGACY.state)));
  const scope = object(parse(window.localStorage.getItem(LEGACY.scope)));
  const dialog = parse(window.localStorage.getItem(LEGACY.dialog));
  if (!Object.keys(old).length && !Object.keys(scope).length && !Array.isArray(dialog)) return undefined;
  const state = normalize({
    currentSource: old.currentSource,
    positions: old.positions,
    settings: scope,
    dialogs: Array.isArray(dialog) ? [dialog] : [],
  });
  Object.values(LEGACY).forEach((key) => window.localStorage.removeItem(key));
  return state;
}

function read(): State {
  if (!persistent) return memory;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw === null) {
      const migrated = migrate();
      if (migrated) write(migrated);
      return migrated ?? memory;
    }
    return normalize(parse(raw));
  } catch {
    persistent = false;
    return memory;
  }
}

// Самые старые диалоги удаляются, пока объём не уложится в предел; в одном огромном
// диалоге — самые старые вопросы.
export function trimDialogs(dialogs: unknown[][]): unknown[][] {
  const result = dialogs.map((d) => [...d]);
  const size = () => JSON.stringify(result).length;
  while (result.length > 1 && size() > MAX_DIALOG_CHARS) result.shift();
  while (result[0].length > 1 && size() > MAX_DIALOG_CHARS) result[0].shift();
  return result;
}

function write(state: State): void {
  memory = { ...state, dialogs: trimDialogs(state.dialogs) };
  if (persistent) {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(memory));
    } catch {
      persistent = false; // хранилище переполнено или отключилось: живём в памяти вкладки
    }
  }
  window.dispatchEvent(new Event(EVENT));
}

export function update(change: (state: State) => State): void {
  write(change(read()));
}

export function useStored<T>(select: (state: State) => T): T {
  const [value, set] = useState<T>(() => select(read()));
  useEffect(() => {
    const refresh = () => set(select(read()));
    window.addEventListener(EVENT, refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener(EVENT, refresh);
      window.removeEventListener("storage", refresh);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return value;
}

export const storage = {
  persistent: (): boolean => persistent,
  read,
  currentSource: (): string | undefined => read().currentSource,
  setCurrentSource(id: string | undefined): void {
    update((s) => ({ ...s, currentSource: id }));
  },
  position: (sourceId: string): Position | undefined => read().positions[sourceId],
  setPosition(sourceId: string, position: Position): void {
    update((s) => ({ ...s, positions: { ...s.positions, [sourceId]: position } }));
  },
  settings: (): Settings => read().settings,
  setSettings(change: Partial<Settings>): void {
    update((s) => ({ ...s, settings: { ...s.settings, ...change } }));
  },
  dialog: (): unknown[] => {
    const dialogs = read().dialogs;
    return dialogs[dialogs.length - 1] ?? [];
  },
  saveDialog(turns: unknown[]): void {
    update((s) => ({ ...s, dialogs: [...s.dialogs.slice(0, -1), turns] }));
  },
  newDialog(): void {
    update((s) => (s.dialogs[s.dialogs.length - 1]?.length ? { ...s, dialogs: [...s.dialogs, []] } : s));
  },
  setTheme(theme: Theme): void {
    update((s) => ({ ...s, theme }));
  },
  setLang(lang: Lang): void {
    update((s) => ({ ...s, lang }));
  },
  notice: (): string | undefined => read().notice,
  acceptNotice(version: string): void {
    update((s) => ({ ...s, notice: version }));
  },
  // Сброс всех данных продукта в этом браузере, включая старые форматы.
  reset(): void {
    if (persistent) {
      try {
        [KEY, ...Object.values(LEGACY)].forEach((key) => window.localStorage.removeItem(key));
      } catch {
        // нечего удалять
      }
    }
    memory = empty();
    window.dispatchEvent(new Event(EVENT));
  },
};
