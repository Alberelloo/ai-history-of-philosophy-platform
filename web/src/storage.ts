// Состояние читателя в браузере: выбранный источник и место чтения в каждом источнике.
// Хранилище может быть недоступно (приватный режим) — тогда работаем в памяти вкладки.

const KEY = "philograph:v1";

export type Position = { chapterId: string; paragraphId?: string };

type State = {
  version: 1;
  currentSource?: string;
  positions: Record<string, Position>;
};

const empty = (): State => ({ version: 1, positions: {} });
let memory: State = empty();

function read(): State {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return memory;
    const parsed = JSON.parse(raw) as State;
    if (parsed.version !== 1 || typeof parsed.positions !== "object") return empty();
    return parsed;
  } catch {
    return memory;
  }
}

function write(state: State): void {
  memory = state;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // Хранилище недоступно: состояние живёт до закрытия вкладки.
  }
}

export const storage = {
  currentSource: (): string | undefined => read().currentSource,
  setCurrentSource(id: string | undefined): void {
    write({ ...read(), currentSource: id });
  },
  position: (sourceId: string): Position | undefined => read().positions[sourceId],
  setPosition(sourceId: string, position: Position): void {
    const state = read();
    write({ ...state, positions: { ...state.positions, [sourceId]: position } });
  },
};
