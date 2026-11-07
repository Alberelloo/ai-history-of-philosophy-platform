import { useEffect, useState } from "react";

// Всё, что продукт хранит о читателе, — в одном хранилище браузера с версией формата:
// настройки, открытые книги и текущая из них, места чтения, закрепление боковой панели,
// диалоги, отметка об уведомлении. На сервере
// ничего этого нет: настройки уходят с каждым запросом.
//
// Новая версия формата переносит старые данные; повреждённые сбрасываются к значениям по
// умолчанию. Без хранилища (приватный режим) состояние живёт в памяти вкладки, а читатель
// видит, что настройки не сохранятся.

const KEY = "philograph:v3";
const V2 = "philograph:v2";
const LEGACY = { state: "philograph:v1", scope: "philograph:scope:v1", dialog: "philograph:dialog:v1" };
const EVENT = "philograph:state";
// Диалоги — больше всего данных; при превышении удаляются самые старые.
export const MAX_DIALOG_CHARS = 200_000;
// Открытых книг не больше: лишней уходит та, что открывалась давнее всех.
export const MAX_OPEN_SOURCES = 10;

export type Position = { chapterId: string; paragraphId?: string };
export type OpenSource = { id: string; openedAt: number };
export type Settings = { generation: boolean; sourcesOnly: boolean; onlyTextbook: boolean };
export type Theme = "light" | "dark" | "system";
export type Lang = "ru" | "en";
export const THEMES: Theme[] = ["light", "dark", "system"];
export const LANGS: Lang[] = ["ru", "en"];
export type State = {
  version: 3;
  settings: Settings;
  theme: Theme; // «как в системе» — по умолчанию
  lang?: Lang; // не выбран — язык браузера
  currentSource?: string; // последняя открытая книга
  openSources: OpenSource[]; // новые — первыми
  sidebarPinned: boolean;
  positions: Record<string, Position>;
  dialogs: unknown[][]; // последний — текущий
  mentions: "underline" | "hover"; // вид упоминаний в тексте
  notice?: string; // версия закрытого уведомления
};

export const DEFAULT_SETTINGS: Settings = { generation: true, sourcesOnly: false, onlyTextbook: false };
const empty = (): State => ({
  version: 3,
  settings: { ...DEFAULT_SETTINGS },
  theme: "system",
  openSources: [],
  sidebarPinned: false,
  positions: {},
  dialogs: [[]],
  mentions: "underline",
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
  const currentSource = typeof data.currentSource === "string" ? data.currentSource : undefined;
  const open: OpenSource[] = [];
  (Array.isArray(data.openSources) ? data.openSources : []).forEach((item) => {
    const o = object(item);
    if (typeof o.id === "string" && !open.some((x) => x.id === o.id)) {
      open.push({ id: o.id, openedAt: typeof o.openedAt === "number" ? o.openedAt : 0 });
    }
  });
  // Формат 2 знал только выбранный источник: он становится первой открытой книгой.
  if (!Array.isArray(data.openSources) && currentSource) open.push({ id: currentSource, openedAt: Date.now() });
  return {
    version: 3,
    settings: {
      generation: bool(settings.generation, DEFAULT_SETTINGS.generation),
      sourcesOnly: bool(settings.sourcesOnly, DEFAULT_SETTINGS.sourcesOnly),
      onlyTextbook: bool(settings.onlyTextbook, DEFAULT_SETTINGS.onlyTextbook),
    },
    theme: THEMES.includes(data.theme as Theme) ? (data.theme as Theme) : "system",
    lang: LANGS.includes(data.lang as Lang) ? (data.lang as Lang) : undefined,
    currentSource,
    openSources: trimOpen(open),
    sidebarPinned: bool(data.sidebarPinned, false),
    positions,
    dialogs: dialogs.length ? (dialogs as unknown[][]) : [[]],
    mentions: data.mentions === "hover" ? "hover" : "underline",
    notice: typeof data.notice === "string" ? data.notice : undefined,
  };
}

// Не больше MAX_OPEN_SOURCES: уходят те, что открывались давнее всех; порядок списка сохраняется.
function trimOpen(open: OpenSource[]): OpenSource[] {
  if (open.length <= MAX_OPEN_SOURCES) return open;
  const keep = new Set(
    [...open]
      .sort((a, b) => b.openedAt - a.openedAt)
      .slice(0, MAX_OPEN_SOURCES)
      .map((o) => o.id),
  );
  return open.filter((o) => keep.has(o.id));
}

function opened(state: State, id: string): State {
  const now = Date.now();
  const known = state.openSources.some((o) => o.id === id);
  const open = known
    ? state.openSources.map((o) => (o.id === id ? { ...o, openedAt: now } : o))
    : [{ id, openedAt: now }, ...state.openSources];
  return { ...state, currentSource: id, openSources: trimOpen(open) };
}

function parse(text: string | null): unknown {
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return undefined; // повреждено — значения по умолчанию
  }
}

// Перенос из прежних форматов: 2 — один ключ без открытых книг, 1 — три отдельных ключа.
function migrate(): State | undefined {
  const v2 = parse(window.localStorage.getItem(V2));
  if (v2 !== undefined || window.localStorage.getItem(V2) !== null) {
    window.localStorage.removeItem(V2);
    return normalize(v2);
  }
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
  // Книга открыта для чтения: она текущая и в списке открытых книг.
  setCurrentSource(id: string | undefined): void {
    update((s) => (id ? opened(s, id) : { ...s, currentSource: undefined }));
  },
  openSources: (): OpenSource[] => read().openSources,
  // Закрытая книга уходит из списка, место чтения в ней остаётся. Текущей становится следующая.
  closeSource(id: string): void {
    update((s) => {
      const open = s.openSources.filter((o) => o.id !== id);
      const current = s.currentSource === id ? open[0]?.id : s.currentSource;
      return { ...s, openSources: open, currentSource: current };
    });
  },
  closeAllSources(): void {
    update((s) => ({ ...s, openSources: [], currentSource: undefined }));
  },
  sidebarPinned: (): boolean => read().sidebarPinned,
  setSidebarPinned(pinned: boolean): void {
    update((s) => ({ ...s, sidebarPinned: pinned }));
  },
  position: (sourceId: string): Position | undefined => read().positions[sourceId],
  setPosition(sourceId: string, position: Position): void {
    update((s) => ({ ...s, positions: { ...s.positions, [sourceId]: position } }));
  },
  settings: (): Settings => read().settings,
  setSettings(change: Partial<Settings>): void {
    update((s) => ({ ...s, settings: { ...s.settings, ...change } }));
  },
  mentionsView: (): "underline" | "hover" => read().mentions,
  setMentionsView(mentions: "underline" | "hover"): void {
    update((s) => ({ ...s, mentions }));
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
        [KEY, V2, ...Object.values(LEGACY)].forEach((key) => window.localStorage.removeItem(key));
      } catch {
        // нечего удалять
      }
    }
    memory = empty();
    window.dispatchEvent(new Event(EVENT));
  },
};
