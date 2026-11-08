import { useEffect, useState } from "react";

// Всё, что продукт хранит о читателе, — в одном хранилище браузера с версией формата:
// настройки, открытые книги, места чтения, закрепление боковой панели, диалоги ассистента,
// вид упоминаний, отметка об уведомлении. На сервере ничего этого нет.
//
// Формат 4 (reader-panels.md, 12.3): у каждой книги свой набор сессий (``dialogs``), у раздела
// «Ассистент» — свой (``libraryDialogs``). Перенос из формата 3 переводит старый общий диалог
// в ``libraryDialogs``.

const KEY = "philograph:v4";
const V3 = "philograph:v3";
const V2 = "philograph:v2";
const LEGACY = { state: "philograph:v1", scope: "philograph:scope:v1", dialog: "philograph:dialog:v1" };
const EVENT = "philograph:state";
// Диалоги — больше всего данных; при превышении удаляются по порядку вытеснения (5.8).
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

// --- диалоги ассистента (формат 4) -------------------------------------------

export type Citation = {
  kind?: "paragraph" | "statement";
  paragraph_id: string | null;
  statement_id?: string | null;
  entity_id?: string | null;
  source_id: string;
  chapter_id: string | null;
  title: string;
  source_title?: string | null;
  chapter_title?: string | null;
  paragraph_start?: string | null;
};
export type Contradiction = { kind: string; entity: string; expected: string; found: string };
export type Fragment = {
  text: string;
  grounded: boolean;
  citations: Citation[];
  contradicts?: Contradiction[];
};
export type Suggestion = { entity_id: string; recipe: string; label?: string; title: string };
export type Message = {
  code?: string;
  text?: string;
  minutes?: number;
  suggestions?: { title: string; paragraph_id?: string | null }[]; // «Близкое в библиотеке» (5.6)
};
// sent — вопрос по ссылке уже отправлен в разделе «Ассистент» (5.10).
export type Handoff = { reason: "broader" | "outside_book"; choice?: "book" | "library"; sent?: boolean };
// Итог хода ответа (5.3): время, число найденных абзацев, стадия, на которой ответ закончился.
export type TurnStats = { seconds: number; found?: number; stage?: number };
export type Turn = {
  id: string;
  question: string;
  selection?: string;
  selectionParagraphs?: string[];
  fragments: Fragment[];
  status: "streaming" | "done" | "stopped" | "error";
  message?: Message;
  suggestion?: Suggestion;
  // Глава, в которой задан вопрос (5.8): у вопроса из другой главы — подпись с её названием.
  chapterId?: string;
  chapterTitle?: string;
  handoff?: Handoff;
  handoffId?: string;
  from?: { sourceId: string; chapterId?: string };
  stats?: TurnStats;
};
export type Session = {
  id: string;
  title: string; // "" — название по первой фразе первого вопроса, до вопроса — «Новая сессия»
  createdAt: number;
  updatedAt: number;
  messages: Turn[];
};
export type DialogSet = { updatedAt: number; activeId: string; sessions: Session[] };

export type State = {
  version: 4;
  settings: Settings;
  theme: Theme;
  lang?: Lang;
  currentSource?: string;
  openSources: OpenSource[];
  sidebarPinned: boolean;
  positions: Record<string, Position>;
  dialogs: Record<string, DialogSet>; // книга → набор сессий
  libraryDialogs: DialogSet; // раздел «Ассистент»
  mentions: "underline" | "hover";
  notice?: string;
};

export const DEFAULT_SETTINGS: Settings = { generation: true, sourcesOnly: false, onlyTextbook: false };

// Ключ набора сессий раздела «Ассистент» среди ключей книг (``dialogs``).
export const LIBRARY = "library:";
// Обмены, поток которых идёт в этой вкладке: остальные «streaming» при чтении — «остановлено».
export const liveTurns = new Set<string>();

export function newId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function emptySession(title = ""): Session {
  const now = Date.now();
  return { id: newId(), title, createdAt: now, updatedAt: now, messages: [] };
}

export function emptyDialogSet(): DialogSet {
  const session = emptySession();
  return { updatedAt: Date.now(), activeId: session.id, sessions: [session] };
}

const empty = (): State => ({
  version: 4,
  settings: { ...DEFAULT_SETTINGS },
  theme: "system",
  openSources: [],
  sidebarPinned: false,
  positions: {},
  dialogs: {},
  libraryDialogs: emptyDialogSet(),
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

function normalizeTurn(raw: unknown): Turn | null {
  const t = object(raw);
  if (typeof t.question !== "string") return null;
  const status = ["streaming", "done", "stopped", "error"].includes(t.status as string)
    ? (t.status as Turn["status"])
    : "done";
  return {
    id: typeof t.id === "string" ? t.id : newId(),
    question: t.question,
    selection: typeof t.selection === "string" ? t.selection : undefined,
    selectionParagraphs: Array.isArray(t.selectionParagraphs)
      ? t.selectionParagraphs.filter((p): p is string => typeof p === "string")
      : undefined,
    fragments: Array.isArray(t.fragments) ? (t.fragments as Fragment[]) : [],
    // Обмен, который при перезагрузке шёл, восстанавливается как «остановлено» (5.8): поток
    // принадлежал закрытой вкладке и уже не допишется.
    status: status === "streaming" && !liveTurns.has(t.id as string) ? "stopped" : status,
    message: object(t.message).code || object(t.message).text ? (t.message as Message) : undefined,
    suggestion: object(t.suggestion).entity_id ? (t.suggestion as Suggestion) : undefined,
    chapterId: typeof t.chapterId === "string" ? t.chapterId : undefined,
    chapterTitle: typeof t.chapterTitle === "string" ? t.chapterTitle : undefined,
    handoff: t.handoff ? (t.handoff as Handoff) : undefined,
    handoffId: typeof t.handoffId === "string" ? t.handoffId : undefined,
    from: object(t.from).sourceId ? (t.from as Turn["from"]) : undefined,
    stats: typeof object(t.stats).seconds === "number" ? (t.stats as TurnStats) : undefined,
  };
}

function normalizeSession(raw: unknown): Session | null {
  const s = object(raw);
  if (typeof s.id !== "string") return null;
  const messages = (Array.isArray(s.messages) ? s.messages : [])
    .map(normalizeTurn)
    .filter((t): t is Turn => t !== null);
  return {
    id: s.id,
    title: typeof s.title === "string" ? s.title : "",
    createdAt: typeof s.createdAt === "number" ? s.createdAt : Date.now(),
    updatedAt: typeof s.updatedAt === "number" ? s.updatedAt : Date.now(),
    messages,
  };
}

function normalizeDialogSet(raw: unknown): DialogSet {
  const d = object(raw);
  const sessions = (Array.isArray(d.sessions) ? d.sessions : [])
    .map(normalizeSession)
    .filter((s): s is Session => s !== null);
  if (!sessions.length) return emptyDialogSet();
  const activeId = typeof d.activeId === "string" && sessions.some((s) => s.id === d.activeId)
    ? d.activeId
    : sessions[sessions.length - 1].id;
  return { updatedAt: typeof d.updatedAt === "number" ? d.updatedAt : Date.now(), activeId, sessions };
}

// Приводит что угодно к правильному состоянию формата 4: чужие и испорченные поля — к значениям
// по умолчанию.
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
  const dialogs: Record<string, DialogSet> = {};
  Object.entries(object(data.dialogs)).forEach(([source, set]) => {
    const normalized = normalizeDialogSet(set);
    if (normalized.sessions.length) dialogs[source] = normalized;
  });
  const currentSource = typeof data.currentSource === "string" ? data.currentSource : undefined;
  const open: OpenSource[] = [];
  (Array.isArray(data.openSources) ? data.openSources : []).forEach((item) => {
    const o = object(item);
    if (typeof o.id === "string" && !open.some((x) => x.id === o.id)) {
      open.push({ id: o.id, openedAt: typeof o.openedAt === "number" ? o.openedAt : 0 });
    }
  });
  if (!Array.isArray(data.openSources) && currentSource) open.push({ id: currentSource, openedAt: Date.now() });
  return {
    version: 4,
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
    dialogs,
    libraryDialogs: normalizeDialogSet(data.libraryDialogs),
    mentions: data.mentions === "hover" ? "hover" : "underline",
    notice: typeof data.notice === "string" ? data.notice : undefined,
  };
}

// Не больше MAX_OPEN_SOURCES: уходят те, что открывались давнее всех; порядок списка сохраняется.
function trimOpen(open: OpenSource[]): OpenSource[] {
  if (open.length <= MAX_OPEN_SOURCES) return open;
  const keep = new Set(
    [...open].sort((a, b) => b.openedAt - a.openedAt).slice(0, MAX_OPEN_SOURCES).map((o) => o.id),
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

// Перенос v3 → v4: поля, кроме dialogs, переносятся как есть; старый общий диалог разбивается
// на сессии и уходит в libraryDialogs.
function fromV3(raw: unknown): State {
  const data = object(raw);
  const state = normalize({ ...data, dialogs: {}, libraryDialogs: undefined });
  const oldDialogs = Array.isArray(data.dialogs) ? data.dialogs.filter(Array.isArray) : [];
  if (oldDialogs.length) {
    const now = Date.now();
    const sessions: Session[] = oldDialogs.map((d) => ({
      id: newId(),
      title: "",
      createdAt: now,
      updatedAt: now,
      messages: (d as unknown[]).map(normalizeTurn).filter((t): t is Turn => t !== null),
    }));
    state.libraryDialogs = {
      updatedAt: now,
      activeId: sessions[sessions.length - 1].id,
      sessions,
    };
  }
  return state;
}

function migrate(): State | undefined {
  const v3 = window.localStorage.getItem(V3);
  if (v3 !== null) {
    window.localStorage.removeItem(V3);
    return fromV3(parse(v3));
  }
  const v2 = window.localStorage.getItem(V2);
  if (v2 !== null) {
    window.localStorage.removeItem(V2);
    return fromV3(normalizeV3Fields(parse(v2)));
  }
  const old = object(parse(window.localStorage.getItem(LEGACY.state)));
  const scope = object(parse(window.localStorage.getItem(LEGACY.scope)));
  const dialog = parse(window.localStorage.getItem(LEGACY.dialog));
  if (!Object.keys(old).length && !Object.keys(scope).length && !Array.isArray(dialog)) return undefined;
  const v3Shape = {
    currentSource: old.currentSource,
    positions: old.positions,
    settings: scope,
    dialogs: Array.isArray(dialog) ? [dialog] : [],
  };
  Object.values(LEGACY).forEach((key) => window.localStorage.removeItem(key));
  return fromV3(v3Shape);
}

// v2 → v3-подобная форма (открытые книги и остальные поля нормализуются как в формате 3).
function normalizeV3Fields(raw: unknown): unknown {
  const data = object(raw);
  const currentSource = typeof data.currentSource === "string" ? data.currentSource : undefined;
  const open = Array.isArray(data.openSources) ? data.openSources : currentSource ? [{ id: currentSource, openedAt: Date.now() }] : [];
  return { ...data, openSources: open };
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

// Порядок вытеснения (5.8): сначала сессии закрытых книг, затем прежние сессии открытых книг и
// раздела, затем самые старые обмены активных сессий. Активная сессия текущей книги — последней.
export function trimDialogs(state: State): State {
  const size = () => JSON.stringify({ dialogs: state.dialogs, libraryDialogs: state.libraryDialogs }).length;
  if (size() <= MAX_DIALOG_CHARS) return state;
  const openIds = new Set(state.openSources.map((o) => o.id));
  const drop = (source: string, sessionId: string) => {
    const set = state.dialogs[source];
    if (!set) return;
    const sessions = set.sessions.filter((s) => s.id !== sessionId);
    if (!sessions.length) delete state.dialogs[source];
    else state.dialogs[source] = { ...set, sessions, activeId: set.activeId === sessionId ? sessions[0].id : set.activeId };
  };
  // 1. Сессии закрытых книг от давно обновлённых.
  for (const source of Object.keys(state.dialogs)) {
    if (openIds.has(source)) continue;
    for (const s of [...state.dialogs[source].sessions].sort((a, b) => a.updatedAt - b.updatedAt)) {
      if (size() <= MAX_DIALOG_CHARS) return state;
      drop(source, s.id);
    }
  }
  // 2. Прежние сессии открытых книг и раздела от давно обновлённых.
  const allSessions = (set: DialogSet) => set.sessions.filter((s) => s.id !== set.activeId);
  const books = [...openIds].sort(
    (a, b) => (state.dialogs[a]?.updatedAt ?? 0) - (state.dialogs[b]?.updatedAt ?? 0),
  );
  for (const source of books) {
    const set = state.dialogs[source];
    if (!set) continue;
    for (const s of [...allSessions(set)].sort((a, b) => a.updatedAt - b.updatedAt)) {
      if (size() <= MAX_DIALOG_CHARS) return state;
      drop(source, s.id);
    }
  }
  for (const s of [...allSessions(state.libraryDialogs)].sort((a, b) => a.updatedAt - b.updatedAt)) {
    if (size() <= MAX_DIALOG_CHARS) return state;
    state.libraryDialogs = { ...state.libraryDialogs, sessions: state.libraryDialogs.sessions.filter((x) => x.id !== s.id) };
  }
  // 3. Самые старые обмены активных сессий (кроме активной сессии текущей книги).
  const current = state.currentSource;
  const activeSession = (set: DialogSet) => set.sessions.find((s) => s.id === set.activeId);
  for (const source of books) {
    const s = activeSession(state.dialogs[source]);
    if (!s || (source === current && s.id === state.dialogs[source].activeId)) continue;
    while (s.messages.length > 1 && size() > MAX_DIALOG_CHARS) s.messages.shift();
    if (size() <= MAX_DIALOG_CHARS) return state;
  }
  // В последнюю очередь — активная сессия текущей книги и раздела.
  const lastBooks = [...books].filter((s) => s !== current);
  for (const source of [current, ...lastBooks].filter((s): s is string => Boolean(s))) {
    const s = activeSession(state.dialogs[source]);
    if (!s) continue;
    while (s.messages.length > 1 && size() > MAX_DIALOG_CHARS) s.messages.shift();
    if (size() <= MAX_DIALOG_CHARS) return state;
  }
  const libActive = activeSession(state.libraryDialogs);
  if (libActive) {
    while (libActive.messages.length > 1 && size() > MAX_DIALOG_CHARS) libActive.messages.shift();
  }
  return state;
}

function write(state: State): void {
  memory = trimDialogs(state);
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

// Набор сессий книги, которой ещё нет в хранилище: один и тот же до первой записи, чтобы
// активная сессия не менялась от чтения к чтению.
const unsaved = new Map<string, DialogSet>();

function dialogSetOf(state: State, key: string): DialogSet {
  if (key === LIBRARY) return state.libraryDialogs;
  const set = state.dialogs[key];
  if (set) {
    unsaved.delete(key);
    return set;
  }
  if (!unsaved.has(key)) unsaved.set(key, emptyDialogSet());
  return unsaved.get(key)!;
}

// Запись меняет только набор своей книги (или раздела) поверх свежего состояния: две вкладки
// с разными книгами и поток, дописывающий ответ в прежнюю книгу, друг друга не затирают (5.8).
function updateDialogs(key: string, change: (set: DialogSet) => DialogSet): void {
  update((s) => {
    const next = change(dialogSetOf(s, key));
    if (key === LIBRARY) return { ...s, libraryDialogs: next };
    unsaved.delete(key);
    return { ...s, dialogs: { ...s.dialogs, [key]: next } };
  });
}

// Набор сессий книги или раздела; обновляется при любой записи в этой и других вкладках.
export function useDialogSet(key: string): DialogSet {
  const [, setTick] = useState(0);
  useEffect(() => {
    const refresh = () => setTick((n) => n + 1);
    window.addEventListener(EVENT, refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener(EVENT, refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);
  return dialogSetOf(read(), key);
}

export const storage = {
  persistent: (): boolean => persistent,
  read,
  currentSource: (): string | undefined => read().currentSource,
  setCurrentSource(id: string | undefined): void {
    update((s) => (id ? opened(s, id) : { ...s, currentSource: undefined }));
  },
  openSources: (): OpenSource[] => read().openSources,
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
  // Диалоги книги и раздела «Ассистент» (ключ LIBRARY).
  dialogsFor(key: string): DialogSet {
    return dialogSetOf(read(), key);
  },
  saveDialogs(key: string, set: DialogSet): void {
    updateDialogs(key, () => set);
  },
  libraryDialogs(): DialogSet {
    return read().libraryDialogs;
  },
  saveLibraryDialogs(set: DialogSet): void {
    updateDialogs(LIBRARY, () => set);
  },
  updateDialogs: (key: string, change: (set: DialogSet) => DialogSet): void => updateDialogs(key, change),
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
        [KEY, V3, V2, ...Object.values(LEGACY)].forEach((key) => window.localStorage.removeItem(key));
      } catch {
        // нечего удалять
      }
    }
    memory = empty();
    unsaved.clear();
    window.dispatchEvent(new Event(EVENT));
  },
};
