import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type KeyboardEvent as ReactKeyboardEvent } from "react";
import type { SourceItem } from "./api";
import { navigate } from "./App";
import { QUESTION_SELECTOR } from "./hooks/useAssistantShortcut";
import { pick, recipeTitle, useLang, useT, type Catalog } from "./i18n";
import { ru } from "./i18n/ru";
import { requestNotice, useNoticeAccepted } from "./Notice";
import { ScopeToggle, useScope } from "./scope";
import { useSources } from "./sources";
import {
  LIBRARY,
  liveTurns,
  newId,
  storage,
  useDialogSet,
  type Citation,
  type DialogSet,
  type Fragment,
  type Message,
  type Session,
  type Suggestion,
  type Turn,
} from "./storage";
import { GeneratedMark, Icon, StatusMark } from "./ui";

// Поручение перехода с вопросом из панели в раздел «Ассистент» (5.10): живёт только в памяти
// вкладки, не в хранилище; вопрос отправляется один раз, когда страница раздела видит его.
export type PendingHandoff = {
  id: string;
  question: string;
  selection?: string;
  selectionParagraphs: string[];
  from: string;
  chapter?: { id: string; title: string };
};

let pending: PendingHandoff | null = null;
// Отправки по поручениям, идущие прямо сейчас (условие 4 в 5.10; защита от двойного эффекта).
const inflight = new Set<string>();
export function setPendingHandoff(value: PendingHandoff): void {
  pending = value;
}
export function takePendingHandoff(id: string): PendingHandoff | null {
  return pending && pending.id === id ? pending : null;
}
export function clearPendingHandoff(): void {
  pending = null;
}

// Панель ассистента (docs/design/features/reader-panels.md, 5.2–5.9): набор сессий на книгу,
// ответ потоком со стадиями и временем, «Остановить» только в потоке, «Повторить», тайм-аут 45 с.

const MAX_SELECTION = 4000;
const MAX_QUESTION = 2000;
const TIMEOUT_MS = 45_000;
// Стадии ответа (5.3): 0 — разбор вопроса, 1 — поиск, 2 — составление, 3 — текст.
const STAGE_NAMES = ["routing", "searching", "composing", "writing"] as const;

type StageState = { step: number; found?: number; startedAt: number };

const SERVER_CODES = [
  "too_long",
  "off_topic",
  "search_unavailable",
  "no_answer",
  "no_library_support",
  "budget_exhausted",
  "llm_unavailable",
] as const;
type ServerCode = (typeof SERVER_CODES)[number];

function messageText(t: Catalog, message: Message | undefined, legacy?: string): string | undefined {
  if (!message) return legacy;
  if (message.code === "visitor_limit" && message.minutes) return t.assistant.visitor_limit(message.minutes);
  if (message.code === "read_notice") return t.assistant.readNoticeFirst;
  if (message.code === "timeout") return t.assistant.timeout;
  if (message.code === "unavailable") return t.assistant.unavailable;
  if (message.code === "broken") return t.assistant.broken;
  if (SERVER_CODES.includes(message.code as ServerCode)) return t.assistant[message.code as ServerCode];
  return pick(t.errors, message.code) ?? (message.text || t.assistant.unavailable);
}

// Вид сообщения по таблице 5.7: предупреждение, ошибка или обычное.
function messageTone(turn: Turn): "danger" | "warning" | "" {
  const code = turn.message?.code;
  if (turn.status === "error" || code === "broken" || code === "timeout") return "danger";
  if (code === "too_long" || code === "no_library_support" || code === "read_notice") return "warning";
  return "";
}

function eventMessage(event: Record<string, unknown>): Message {
  const code = (event.reason ?? event.kind ?? event.type) as string | undefined;
  const seconds = Number(event.retry_after_seconds ?? 0);
  const suggestions = Array.isArray(event.suggestions)
    ? (event.suggestions as unknown[]).map((s) =>
        typeof s === "string"
          ? { title: s }
          : { title: String((s as { title?: string }).title ?? ""), paragraph_id: (s as { paragraph_id?: string }).paragraph_id ?? null },
      )
    : undefined;
  return {
    code: event.type === "error" ? "broken" : code,
    text: typeof event.message === "string" ? event.message : undefined,
    minutes: seconds ? Math.max(1, Math.ceil(seconds / 60)) : undefined,
    suggestions: suggestions?.length ? suggestions : undefined,
  };
}

// Ответ одной строкой: для истории диалога (пометка всегда по-русски) и для копирования.
export function answerText(turn: Turn, mark: string = ru.assistant.ungroundedMark): string {
  return turn.fragments.map((f) => (f.grounded ? f.text : `${mark} ${f.text}`)).join(" ");
}

// Название сессии: заданное читателем или первая фраза первого вопроса (до 60 знаков, по слову).
export function sessionTitle(session: Session, fallback: string): string {
  if (session.title) return session.title;
  const first = session.messages.find((m) => m.question.trim());
  if (!first) return fallback;
  const phrase = first.question.split(/[.!?]/)[0].trim();
  if (phrase.length <= 60) return phrase;
  const cut = phrase.slice(0, 60);
  const space = cut.lastIndexOf(" ");
  return `${(space > 20 ? cut.slice(0, space) : cut).trimEnd()}…`;
}

// Подпись каталога с вставленным названием книги: название — контент со своим языком.
function withTitle(format: (title: string) => string, source: SourceItem | undefined, fallback: string) {
  const [before, after = ""] = format("\u0001").split("\u0001");
  return (
    <>
      {before}
      <span lang={source?.language}>{source?.title ?? fallback}</span>
      {after}
    </>
  );
}

// --- Потоки ответов -----------------------------------------------------------
// Живут на уровне модуля, а не панели: ответ дописывается в сессию своей книги, даже если
// читатель закрыл панель, переключил сессию или ушёл в другую книгу (5.8, Р13).

type Live = { key: string; sessionId: string; stage: StageState; controller: AbortController };
const live = new Map<string, Live>();
// Лимит посетителя: до этого момента «Спросить» неактивна.
let limitedUntil = 0;
const streamListeners = new Set<() => void>();
let streamsVersion = 0;

function emitStreams() {
  streamsVersion += 1;
  streamListeners.forEach((listener) => listener());
}

function useStreams(): number {
  return useSyncExternalStore(
    (listener) => {
      streamListeners.add(listener);
      return () => streamListeners.delete(listener);
    },
    () => streamsVersion,
  );
}

function setStage(turnId: string, change: (stage: StageState) => StageState) {
  const item = live.get(turnId);
  if (!item) return;
  item.stage = change(item.stage);
  emitStreams();
}

function abortSession(key: string, sessionId: string) {
  live.forEach((item) => {
    if (item.key === key && item.sessionId === sessionId) item.controller.abort("deleted");
  });
}

function patchSession(key: string, sessionId: string, change: (s: Session) => Session) {
  storage.updateDialogs(key, (set) => ({
    ...set,
    updatedAt: Date.now(),
    sessions: set.sessions.map((s) => (s.id === sessionId ? change(s) : s)),
  }));
}

function patchTurn(key: string, sessionId: string, turnId: string, change: (t: Turn) => Turn) {
  patchSession(key, sessionId, (s) => ({
    ...s,
    messages: s.messages.map((m) => (m.id === turnId ? change(m) : m)),
  }));
}

type AskSettings = { sourcesOnly: boolean; generation: boolean; scope: "all" | "current" };

type Ask = {
  key: string; // книга или LIBRARY: куда пишется обмен
  sessionId: string;
  question: string;
  selection?: string;
  selectionParagraphs: string[];
  sourceId: string; // source_id запроса
  context: "book" | "library";
  settings: AskSettings;
  handoff?: { declined: boolean; reason: string };
  handoffId?: string;
  from?: { sourceId: string; chapterId?: string };
  chapter?: { id: string; title?: string };
};

// Отправить вопрос новым обменом в сессию и читать ответ потоком.
async function ask(a: Ask): Promise<void> {
  const session = storage.dialogsFor(a.key).sessions.find((s) => s.id === a.sessionId);
  const history = (session?.messages ?? [])
    .filter((m) => m.status === "done")
    .map((m) => ({ question: m.question, answer: answerText(m) }));
  const turnId = newId();
  const turn: Turn = {
    id: turnId,
    question: a.question,
    selection: a.selection,
    selectionParagraphs: a.selection ? a.selectionParagraphs : undefined,
    fragments: [],
    status: "streaming",
    handoffId: a.handoffId,
    from: a.from,
    chapterId: a.chapter?.id,
    chapterTitle: a.chapter?.title,
  };
  const controller = new AbortController();
  live.set(turnId, { key: a.key, sessionId: a.sessionId, stage: { step: 0, startedAt: Date.now() }, controller });
  liveTurns.add(turnId);
  patchSession(a.key, a.sessionId, (s) => ({ ...s, updatedAt: Date.now(), messages: [...s.messages, turn] }));
  emitStreams();
  const patch = (change: (t: Turn) => Turn) => patchTurn(a.key, a.sessionId, turnId, change);
  const finish = (change: (t: Turn) => Turn) => {
    const stage = live.get(turnId)?.stage;
    const stats = stage
      ? { seconds: Math.round((Date.now() - stage.startedAt) / 1000), found: stage.found, stage: stage.step }
      : undefined;
    patch((t) => ({ ...change(t), stats }));
  };
  let timer = window.setTimeout(() => controller.abort("timeout"), TIMEOUT_MS);
  const resetTimer = () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => controller.abort("timeout"), TIMEOUT_MS);
  };
  try {
    const response = await fetch("/api/assistant/v1/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
        question: a.question,
        selection: a.selection ?? null,
        selection_paragraphs: a.selection ? a.selectionParagraphs : [],
        source_id: a.sourceId || null,
        history,
        sources_only: a.settings.sourcesOnly,
        generation: a.settings.generation,
        scope: a.settings.scope,
        context: a.context,
        handoff_declined: a.handoff?.declined ?? false,
        handoff_reason: a.handoff?.reason ?? null,
      }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      const message = body.reason ? eventMessage(body) : { code: body.kind ?? "unavailable", text: body.error };
      finish((t) => ({ ...t, status: "done", message }));
      return;
    }
    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      resetTimer();
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.type === "stage") {
          if (event.name === "searching") setStage(turnId, (s) => ({ ...s, step: 1 }));
          else if (event.name === "composing") setStage(turnId, (s) => ({ ...s, step: 2, found: Number(event.found ?? 0) }));
        } else if (event.type === "fragment") {
          setStage(turnId, (s) => ({ ...s, step: 3 }));
          patch((t) => ({ ...t, fragments: [...t.fragments, event as Fragment] }));
        } else if (event.type === "suggestion") {
          patch((t) => ({ ...t, suggestion: event as Suggestion }));
        } else if (event.type === "handoff") {
          patch((t) => ({ ...t, handoff: { reason: event.reason } }));
        } else if (event.type === "done") {
          finish((t) => ({ ...t, status: "done" }));
        } else if (event.type === "error") {
          finish((t) => ({ ...t, status: "error", message: eventMessage(event) }));
        } else {
          const message = eventMessage(event);
          if (event.reason === "visitor_limit" && Number(event.retry_after_seconds) > 0) {
            // «Спросить» неактивна до конца срока (5.7).
            limitedUntil = Date.now() + Number(event.retry_after_seconds) * 1000;
          }
          if (event.type === "notice") patch((t) => ({ ...t, message }));
          else finish((t) => ({ ...t, message, status: "done" }));
        }
      }
    }
    patch((t) => (t.status === "streaming" ? { ...t, status: "done" } : t));
  } catch (e) {
    const reason = controller.signal.reason;
    if (controller.signal.aborted && reason === "timeout") {
      finish((t) => ({ ...t, status: "error", message: { code: "timeout" } }));
    } else if (controller.signal.aborted || (e as Error).name === "AbortError") {
      finish((t) => ({ ...t, status: "stopped" }));
    } else {
      finish((t) => ({ ...t, status: "error", message: { code: "broken" } }));
    }
  } finally {
    window.clearTimeout(timer);
    live.delete(turnId);
    liveTurns.delete(turnId);
    emitStreams();
  }
}

// --- Переходы по ссылкам на абзацы (5.4, Р13) ---------------------------------

type ReturnPlace = { paragraph: string; offset: number };
type HistoryState = {
  assistantFrom?: { sourceId: string };
  assistantReturn?: ReturnPlace;
  handoff?: string;
  consumed?: boolean;
} | null;

function readerPlace(): { sourceId?: string; chapterId?: string } {
  const parts = window.location.pathname.split("/").filter(Boolean);
  return parts[0] === "read" ? { sourceId: parts[1], chapterId: parts[2] } : {};
}

// Опорный абзац у верхнего края окна: к нему «Назад» вернёт читателя на прежнее место.
function topParagraph(): ReturnPlace | null {
  const top = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
  const paragraphs = document.querySelectorAll<HTMLElement>("article.chapter [data-paragraph]");
  const el = Array.from(paragraphs).find((p) => p.getBoundingClientRect().bottom > top);
  return el ? { paragraph: el.dataset.paragraph!, offset: el.getBoundingClientRect().top } : null;
}

function highlight(el: HTMLElement) {
  document.querySelectorAll(".highlight").forEach((x) => x.classList.remove("highlight"));
  el.classList.add("highlight");
  // Подсветка снимается через dur-flash (2400ms); фон гаснет переходом .block.
  window.setTimeout(() => el.classList.remove("highlight"), 2400);
}

function reducedMotion(): boolean {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

export function openCitation(c: Citation, currentSource: string | undefined) {
  if (!c.paragraph_id) return;
  const place = readerPlace();
  // Абзац этой главы — плавная прокрутка и подсветка, панель и фокус остаются.
  if (place.chapterId && c.chapter_id === place.chapterId && place.sourceId === c.source_id) {
    const el = document.getElementById(`p-${c.paragraph_id}`);
    if (el) {
      el.scrollIntoView({ block: "start", behavior: reducedMotion() ? "auto" : "smooth" });
      highlight(el);
      return;
    }
  }
  // Другая глава или книга — переход с записью в историю; у прежней записи — опорный абзац.
  if (place.sourceId) {
    const ret = topParagraph();
    const state = (window.history.state ?? {}) as Record<string, unknown>;
    window.history.replaceState(ret ? { ...state, assistantReturn: ret } : state, "");
  }
  const target = c.chapter_id
    ? `/read/${c.source_id}/${c.chapter_id}#p-${c.paragraph_id}`
    : `/p/${c.paragraph_id}`;
  const from = currentSource && c.source_id !== currentSource ? { assistantFrom: { sourceId: currentSource } } : undefined;
  navigate(target, from);
}

// «Назад» к записи с опорным абзацем: когда глава отрисована, абзац встаёт на прежнее место.
function restorePlace() {
  const ret = (window.history.state as HistoryState)?.assistantReturn;
  if (!ret) return;
  const started = Date.now();
  let settled = 0;
  const step = () => {
    const el = document.getElementById(`p-${ret.paragraph}`);
    if (el && el.closest("article.chapter")) {
      const delta = el.getBoundingClientRect().top - ret.offset;
      if (Math.abs(delta) > 1) window.scrollBy(0, delta);
      settled += 1;
      // Несколько кадров подряд: раскладка и шрифты могут сдвинуть абзац после первой отрисовки.
      if (settled >= 5) return;
    }
    if (Date.now() - started < 5000) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

if (typeof window !== "undefined") window.addEventListener("popstate", restorePlace);

function useLocationKey(): string {
  return useSyncExternalStore(
    (listener) => {
      window.addEventListener("popstate", listener);
      window.addEventListener("hashchange", listener);
      return () => {
        window.removeEventListener("popstate", listener);
        window.removeEventListener("hashchange", listener);
      };
    },
    () => window.location.pathname + window.location.search,
  );
}

// --- Черновики в памяти вкладки (5.9, п. 6) -----------------------------------

type Draft = { question: string; fragment: { text: string; paragraphs: string[] } | null };
const drafts = new Map<string, Draft>();

// --- Панель --------------------------------------------------------------------

type Props = {
  sourceId: string;
  selection: string | null;
  selectionParagraphs: string[];
  onClose: () => void;
  onBack?: () => void;
  backLabel?: string;
  mode?: "book" | "library";
  pending?: PendingHandoff | null;
  initialQuestion?: string;
  pendingFrom?: string;
  chapterId?: string;
  chapterTitle?: string;
  settings?: AskSettings;
};

export function AssistantPanel({ sourceId, selection, selectionParagraphs, onClose, onBack, backLabel, mode = "book", pending = null, initialQuestion, pendingFrom, chapterId, chapterTitle, settings }: Props) {
  const t = useT();
  const lang = useLang();
  const key = mode === "library" ? LIBRARY : sourceId;
  const set: DialogSet = useDialogSet(key);
  useStreams();
  useLocationKey();
  const accepted = useNoticeAccepted();
  const [problem, setProblem] = useState<Message | null>(null);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const [linkBusy, setLinkBusy] = useState<string | null>(null);
  const sessionsButton = useRef<HTMLButtonElement>(null);
  const sessionsList = useRef<HTMLUListElement>(null);
  // Куда вернуть фокус после перерисовки списка сессий (10.4). Кнопка, на которой был фокус,
  // при удалении и отмене исчезает из DOM, поэтому фокус ставится в том же коммите, где уже
  // нарисован новый список, а не по таймеру (иначе фокус успевал упасть на body).
  const focusAfter = useRef<{ kind: "active" } | { kind: "delete"; id: string } | null>(null);
  useLayoutEffect(() => {
    const target = focusAfter.current;
    const list = sessionsList.current;
    if (!target || !list) return;
    const el =
      target.kind === "active"
        ? list.querySelector<HTMLElement>(".assistant__session.is-active .assistant__session-title")
        : list.querySelector<HTMLElement>(`[data-delete-session="${CSS.escape(target.id)}"]`);
    if (!el) return;
    focusAfter.current = null;
    el.focus();
  });
  const scope = useScope();
  const cameFrom = mode === "book" ? (window.history.state as HistoryState)?.assistantFrom : undefined;
  const sources = useSources([
    ...new Set(
      [
        mode === "library" ? pendingFrom : sourceId,
        cameFrom?.sourceId,
        ...set.sessions.flatMap((s) => s.messages.map((m) => m.from?.sourceId)),
      ].filter((x): x is string => Boolean(x)),
    ),
  ]);
  const effective: AskSettings = settings ?? {
    sourcesOnly: scope.sourcesOnly,
    generation: scope.generation,
    scope: scope.onlyTextbook ? "current" : "all",
  };

  const activeId = set.activeId;
  const active = set.sessions.find((s) => s.id === activeId) ?? set.sessions[0];
  const draftKey = `${key}|${active.id}`;
  const [draft, setDraftState] = useState<Draft>(() =>
    initialQuestion !== undefined
      ? { question: initialQuestion, fragment: null }
      : drafts.get(draftKey) ?? { question: "", fragment: null },
  );
  // Поручение не отправлено (уведомление не закрыто): вопрос остаётся в поле (5.10).
  const [blocked, setBlocked] = useState(false);
  const setDraft = (change: (d: Draft) => Draft) =>
    setDraftState((d) => {
      const next = change(d);
      drafts.set(draftKey, next);
      return next;
    });
  // Смена сессии или книги — свой черновик (вопрос и фрагмент) у каждой сессии.
  const shownDraft = useRef(draftKey);
  useEffect(() => {
    if (shownDraft.current === draftKey) return;
    shownDraft.current = draftKey;
    setDraftState(drafts.get(draftKey) ?? { question: "", fragment: null });
  }, [draftKey]);

  // Внешнее выделение заменяет фрагмент (5.2): новое выделение не добавляет второй.
  useEffect(() => {
    if (selection) setDraft((d) => ({ ...d, fragment: { text: selection, paragraphs: selectionParagraphs } }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection, selectionParagraphs]);

  // Глава, в которой задан вопрос: по адресу; название — из панели или заголовка главы.
  const chapterNow = (): { id: string; title?: string } | undefined => {
    const id = readerPlace().chapterId ?? chapterId;
    if (!id) return undefined;
    const title = id === chapterId ? chapterTitle : document.querySelector("article.chapter h1")?.textContent ?? undefined;
    return { id, title };
  };
  const currentChapter = mode === "book" ? readerPlace().chapterId ?? chapterId : undefined;

  const send = (
    text: string,
    selected: { text: string; paragraphs: string[] } | null,
    extra: Partial<Pick<Ask, "handoff" | "handoffId" | "from" | "sourceId">> = {},
  ) => {
    setProblem(null);
    if (!accepted) {
      setProblem({ code: "read_notice" });
      requestNotice();
      return;
    }
    if ((selected?.text ?? "").length > MAX_SELECTION || text.length > MAX_QUESTION) {
      setProblem({ code: "too_long" });
      return;
    }
    setDraft(() => ({ question: "", fragment: null }));
    void ask({
      key,
      sessionId: active.id,
      question: text,
      selection: selected?.text,
      selectionParagraphs: selected?.paragraphs ?? [],
      sourceId,
      context: mode === "library" ? "library" : "book",
      settings: effective,
      chapter: mode === "book" ? chapterNow() : undefined,
      ...extra,
    });
  };

  const switchSession = (id: string) => {
    setSessionsOpen(false);
    storage.updateDialogs(key, (prev) => {
      // Пустая сессия без названия, с которой ушли, удаляется сама (5.8).
      const left = prev.sessions.find((s) => s.id === prev.activeId);
      const drop = left && left.id !== id && left.messages.length === 0 && !left.title;
      return {
        ...prev,
        activeId: id,
        sessions: drop ? prev.sessions.filter((s) => s.id !== left!.id) : prev.sessions,
      };
    });
  };

  const focusQuestion = () =>
    requestAnimationFrame(() => document.querySelector<HTMLElement>(`.assistant__form ${QUESTION_SELECTOR}`)?.focus());

  const createSession = () => {
    setSessionsOpen(false);
    if (active.messages.length === 0 && !active.title) {
      focusQuestion(); // пустая сессия не плодится — фокус в поле вопроса
      return;
    }
    const now = Date.now();
    const session: Session = { id: newId(), title: "", createdAt: now, updatedAt: now, messages: [] };
    storage.updateDialogs(key, (prev) => ({ ...prev, updatedAt: now, activeId: session.id, sessions: [...prev.sessions, session] }));
    focusQuestion();
  };

  const renameSession = (id: string) => {
    const name = renameDraft.trim().slice(0, 60);
    // Пустое — «название по первой фразе»; дата последнего обмена не меняется.
    storage.updateDialogs(key, (prev) => ({
      ...prev,
      sessions: prev.sessions.map((s) => (s.id === id ? { ...s, title: name } : s)),
    }));
    setRenaming(null);
  };

  const deleteSession = (id: string) => {
    abortSession(key, id); // идущий ответ останавливается и удаляется вместе с сессией
    drafts.delete(`${key}|${id}`);
    storage.updateDialogs(key, (prev) => {
      const sessions = prev.sessions.filter((s) => s.id !== id);
      if (!sessions.length) {
        const now = Date.now();
        const fresh: Session = { id: newId(), title: "", createdAt: now, updatedAt: now, messages: [] };
        return { updatedAt: now, activeId: fresh.id, sessions: [fresh] };
      }
      // Удалив активную, читатель получает самую свежую из оставшихся.
      const freshest = [...sessions].sort((a, b) => b.updatedAt - a.updatedAt)[0];
      const nextActive = prev.activeId === id ? freshest.id : prev.activeId;
      return { ...prev, updatedAt: Date.now(), activeId: nextActive, sessions };
    });
    setConfirming(null);
    focusAfter.current = { kind: "active" }; // на название активной сессии (10.4)
  };

  const cancelDelete = (id: string) => {
    setConfirming(null);
    focusAfter.current = { kind: "delete", id }; // на «Удалить» этой строки (10.4)
  };

  // Поручение перехода из панели (5.10): обмен с handoffId добавляется и отправляется один раз.
  useEffect(() => {
    if (!pending) return;
    const state = window.history.state as HistoryState;
    if (state?.handoff !== pending.id || state?.consumed) return;
    if (inflight.has(pending.id)) return;
    const library = storage.dialogsFor(LIBRARY);
    if (library.sessions.some((s) => s.messages.some((m) => m.handoffId === pending.id))) return;
    clearPendingHandoff();
    if (!accepted) {
      // Уведомление не закрыто: не отправлено, вопрос в поле, S12 (условие 5).
      setBlocked(true);
      setProblem({ code: "read_notice" });
      requestNotice();
      return;
    }
    inflight.add(pending.id);
    window.history.replaceState({ ...state, consumed: true }, "");
    send(
      pending.question,
      pending.selection ? { text: pending.selection, paragraphs: pending.selectionParagraphs } : null,
      { handoffId: pending.id, sourceId: pending.from, from: { sourceId: pending.from, chapterId: pending.chapter?.id } },
    );
    // У обмена книги отметка «отправлено»: по ней панель книги отличает удалённый ответ.
    storage.updateDialogs(pending.from, (set) => ({
      ...set,
      sessions: set.sessions.map((s) => ({
        ...s,
        messages: s.messages.map((m) => (m.id === pending.id && m.handoff ? { ...m, handoff: { ...m.handoff, sent: true } } : m)),
      })),
    }));
    window.setTimeout(() => inflight.delete(pending.id), 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending]);

  const streamingTurns = active.messages.filter((m) => m.status === "streaming" && live.has(m.id));
  const streamingTurn = streamingTurns[streamingTurns.length - 1];
  const sorted = [...set.sessions].sort((a, b) => b.updatedAt - a.updatedAt);
  const question = draft.question;
  const fragment = draft.fragment;
  const limited = Date.now() < limitedUntil;
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!limited) return;
    const timer = window.setTimeout(() => setTick((n) => n + 1), limitedUntil - Date.now() + 50);
    return () => window.clearTimeout(timer);
  }, [limited]);

  const onListKey = (e: ReactKeyboardEvent) => {
    if (e.key !== "Escape") return;
    e.stopPropagation();
    if (renaming || confirming) return; // Esc в поле и в подтверждении обрабатывают они сами
    setSessionsOpen(false);
    sessionsButton.current?.focus();
  };

  const handoffHref = (turn: Turn) =>
    `/assistant?q=${encodeURIComponent(turn.question)}&from=${encodeURIComponent(sourceId)}${turn.chapterId ?? chapterId ? `&chapter=${encodeURIComponent((turn.chapterId ?? chapterId)!)}` : ""}`;

  // Вопрос уже задан в разделе: обмен с тем же handoffId есть или удалён (5.10).
  const libraryTurn = (turnId: string) =>
    storage.dialogsFor(LIBRARY).sessions.some((s) => s.messages.some((m) => m.handoffId === turnId));

  return (
    <>
      <div className="pg-panel__head">
        <div className="pg-panel__title-wrap">
          {onBack ? (
            <button className="pg-btn pg-btn--ghost pg-btn--sm" onClick={onBack}>
              <Icon name="arrowLeft" small />
              {backLabel ?? t.panel.backToAssistant}
            </button>
          ) : mode === "library" ? null : (
            <h2 className="pg-panel__title">{t.assistant.label}</h2>
          )}
          {mode !== "library" && (
            <span className="assistant__book">{withTitle(t.assistant.bookDialog, sources[sourceId], sourceId)}</span>
          )}
        </div>
        <button
          ref={sessionsButton}
          className="pg-btn pg-btn--ghost pg-btn--sm"
          aria-expanded={sessionsOpen}
          onClick={() => setSessionsOpen((v) => !v)}
        >
          <Icon name="index" small />
          {t.assistant.session.list}
        </button>
        <button className="pg-btn pg-btn--ghost pg-btn--icon pg-btn--sm" aria-label={t.assistant.session.new} title={t.assistant.session.new} onClick={createSession}>
          <Icon name="plus" small />
        </button>
        {mode !== "library" && (
          <button className="pg-btn pg-btn--ghost pg-btn--icon pg-btn--sm" aria-label={t.assistant.close} title={t.assistant.close} onClick={onClose}>
            <Icon name="close" small />
          </button>
        )}
      </div>
      <div className="pg-panel__body assistant__body">
        {sessionsOpen && (
          <ul ref={sessionsList} className="assistant__sessions" role="list" aria-label={t.assistant.session.list} onKeyDown={onListKey}>
            {sorted.map((s) => {
              const running = s.messages.some((m) => m.status === "streaming" && live.has(m.id));
              const title = sessionTitle(s, t.assistant.session.new);
              return (
                <li key={s.id} className={s.id === activeId ? "assistant__session is-active" : "assistant__session"} aria-current={s.id === activeId ? "true" : undefined}>
                  {renaming === s.id ? (
                    <input
                      className="pg-input assistant__session-input"
                      aria-label={t.assistant.session.renameLabel}
                      value={renameDraft}
                      maxLength={60}
                      onChange={(e) => setRenameDraft(e.target.value)}
                      onFocus={(e) => e.currentTarget.select()}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          renameSession(s.id);
                        }
                        if (e.key === "Escape") {
                          e.preventDefault();
                          setRenaming(null); // отмена; список остаётся открытым
                        }
                      }}
                      onBlur={() => setRenaming((r) => (r === s.id ? null : r))}
                      autoFocus
                    />
                  ) : confirming === s.id ? (
                    <span
                      className="assistant__session-confirm"
                      role="group"
                      aria-label={`${t.assistant.session.delete}: ${title}`}
                      onKeyDown={(e) => {
                        if (e.key === "Escape") cancelDelete(s.id);
                      }}
                    >
                      <span className="assistant__session-confirm-text">
                        {running ? t.assistant.session.deleteRunning : t.assistant.session.deleteConfirm}
                      </span>
                      <span className="assistant__session-confirm-actions">
                        <button className="pg-btn pg-btn--secondary pg-btn--sm assistant__danger" onClick={() => deleteSession(s.id)}>
                          {t.assistant.session.delete}
                        </button>
                        <button className="pg-btn pg-btn--ghost pg-btn--sm" autoFocus onClick={() => cancelDelete(s.id)}>
                          {t.assistant.session.cancel}
                        </button>
                      </span>
                    </span>
                  ) : (
                    <>
                      <button className="pg-btn pg-btn--ghost assistant__session-title" onClick={() => switchSession(s.id)}>
                        <span className="assistant__session-name">{title}</span>
                        <span className="assistant__session-meta">
                          {running ? (
                            <>
                              <span className="assistant__dot" aria-hidden="true" />
                              {t.assistant.session.answering}
                            </>
                          ) : (
                            new Date(s.updatedAt).toLocaleString(lang === "ru" ? "ru-RU" : "en-GB", {
                              day: "numeric",
                              month: "short",
                              hour: "2-digit",
                              minute: "2-digit",
                            })
                          )}
                        </span>
                      </button>
                      <button
                        className="pg-btn pg-btn--ghost pg-btn--icon pg-btn--sm"
                        aria-label={`${t.assistant.session.rename}: ${title}`}
                        title={t.assistant.session.rename}
                        onClick={() => {
                          setRenaming(s.id);
                          setRenameDraft(s.title || title);
                        }}
                      >
                        <Icon name="quill" small />
                      </button>
                      <button
                        className="pg-btn pg-btn--ghost pg-btn--icon pg-btn--sm"
                        aria-label={`${t.assistant.session.delete}: ${title}`}
                        title={t.assistant.session.delete}
                        data-delete-session={s.id}
                        onClick={() => setConfirming(s.id)}
                      >
                        <Icon name="close" small />
                      </button>
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        <ScopeToggle textbook={sourceId || undefined} />
        {(effective.sourcesOnly || !effective.generation) && (
          <p className="assistant__sources-only">
            {t.assistant.sourcesOnlyNote}{" "}
            <a href="/settings#assistant" onClick={(e) => { e.preventDefault(); navigate("/settings#assistant"); }}>
              {t.assistant.changeInSettings}
            </a>
          </p>
        )}
        {cameFrom && cameFrom.sourceId !== sourceId && (
          <div className="assistant-notice pg-notice assistant__came-from" role="status">
            <Icon name="info" />
            <div>{withTitle(t.assistant.cameFrom, sources[cameFrom.sourceId], cameFrom.sourceId)}</div>
            <button type="button" className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => window.history.back()}>
              <Icon name="arrowLeft" small />
              {t.assistant.returnBack}
            </button>
          </div>
        )}
        <ol className="turns">
          {active.messages.map((turn) => {
            const notice = messageText(t, turn.message);
            const tone = messageTone(turn);
            const isStreaming = turn.status === "streaming" && live.has(turn.id);
            const st = isStreaming ? live.get(turn.id)?.stage : undefined;
            const otherChapter = mode === "book" && turn.chapterId && currentChapter && turn.chapterId !== currentChapter;
            return (
              <li key={turn.id} className="turn" id={`turn-${turn.id}`}>
                {otherChapter && (
                  <p className="assistant__chapter-label">{t.assistant.chapterLabel(turn.chapterTitle || t.assistant.otherChapter)}</p>
                )}
                {turn.selection && <blockquote className="selection-context">{turn.selection}</blockquote>}
                <p className="question">{turn.question.trim() ? turn.question : t.assistant.explainFragment}</p>
                {turn.from && (
                  <p className="handoff-from">
                    <a
                      href={`/read/${turn.from.sourceId}${turn.from.chapterId ? `/${turn.from.chapterId}` : ""}`}
                      onClick={(e) => {
                        e.preventDefault();
                        navigate(`/read/${turn.from!.sourceId}${turn.from!.chapterId ? `/${turn.from!.chapterId}` : ""}`);
                      }}
                    >
                      {withTitle(t.assistantPage.fromBook, sources[turn.from.sourceId], "")}
                    </a>
                  </p>
                )}
                {isStreaming && st && <StageLine t={t} stage={st} />}
                {!isStreaming && turn.stats && <StageSummary t={t} turn={turn} />}
                {notice && (
                  <div className={tone ? `assistant-notice pg-notice pg-notice--${tone}` : "assistant-notice pg-notice"} role="status">
                    <Icon name={tone === "danger" || tone === "warning" ? "warning" : "info"} />
                    <div>{notice}</div>
                    {turn.message?.code === "read_notice" && (
                      <button className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => requestNotice()}>
                        {t.assistant.showNotice}
                      </button>
                    )}
                  </div>
                )}
                <div className="answer" data-status={isStreaming ? "streaming" : turn.status}>
                  {turn.fragments.map((f, j) => {
                    const contradicts = f.contradicts && f.contradicts.length > 0;
                    return (
                      <span key={j} className={f.grounded ? "fragment" : "fragment ungrounded pg-generated"}>
                        {contradicts && (
                          <span className="contradiction-mark" title={f.contradicts!.map((c) => t.assistant.contradiction(c.entity, c.expected)).join("; ")}>
                            <StatusMark status="contradiction" iconOnly />
                          </span>
                        )}
                        {!f.grounded && !contradicts && <GeneratedMark label={t.status.ungrounded} />}
                        {f.text}
                        {f.citations.map((c, k) =>
                          c.paragraph_id && c.kind !== "statement" ? (
                            <a
                              key={`${c.paragraph_id}-${k}`}
                              className="citation pg-cite"
                              href={c.chapter_id ? `/read/${c.source_id}/${c.chapter_id}#p-${c.paragraph_id}` : `/p/${c.paragraph_id}`}
                              title={citationTitle(t, c)}
                              onClick={(e) => {
                                e.preventDefault();
                                openCitation(c, mode === "book" ? sourceId : undefined);
                              }}
                            >
                              {k + 1}
                            </a>
                          ) : (
                            <span key={`${c.statement_id ?? c.title}-${k}`} className="citation pg-cite pg-cite--statement" title={c.title}>
                              {k + 1}
                            </span>
                          ),
                        )}{" "}
                      </span>
                    );
                  })}
                  {turn.status === "stopped" && <span className="status-mark pg-status">{t.assistant.stopped}</span>}
                </div>
                {turn.handoff && !turn.handoff.choice && !isStreaming && (
                  <div className="handoff-block">
                    <p>{turn.handoff.reason === "broader" ? t.assistant.handoff.broader : t.assistant.handoff.outside}</p>
                    <div className="handoff-block__actions">
                      <button
                        className="pg-btn pg-btn--secondary pg-btn--sm"
                        onClick={() => {
                          const reason = turn.handoff!.reason;
                          patchTurn(key, active.id, turn.id, (x) => ({ ...x, handoff: { reason, choice: "book" } }));
                          send(
                            turn.question,
                            turn.selection ? { text: turn.selection, paragraphs: turn.selectionParagraphs ?? [] } : null,
                            { handoff: { declined: true, reason } },
                          );
                        }}
                      >
                        {t.assistant.handoff.decline}
                      </button>
                      <a
                        className="pg-btn pg-btn--primary pg-btn--sm"
                        href={handoffHref(turn)}
                        aria-disabled={linkBusy === turn.id || undefined}
                        onClick={(e) => {
                          // Ctrl/⌘ + щелчок, средняя кнопка — новая вкладка без поручения: там вопрос
                          // только в поле ввода, без отправки (5.10).
                          if (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
                          e.preventDefault();
                          if (linkBusy === turn.id) return; // двойной щелчок не делает второй переход
                          setLinkBusy(turn.id);
                          const choice = { reason: turn.handoff!.reason, choice: "library" as const };
                          patchTurn(key, active.id, turn.id, (x) => ({ ...x, handoff: choice }));
                          const chapter = turn.chapterId ?? chapterId;
                          setPendingHandoff({
                            id: turn.id,
                            question: turn.question,
                            selection: turn.selection,
                            selectionParagraphs: turn.selectionParagraphs ?? [],
                            from: sourceId,
                            chapter: chapter ? { id: chapter, title: turn.chapterTitle ?? chapterTitle ?? "" } : undefined,
                          });
                          onClose();
                          navigate(handoffHref(turn), { handoff: turn.id });
                        }}
                      >
                        {t.assistant.handoff.link}
                      </a>
                    </div>
                    <p className="handoff-block__note">{t.assistant.handoff.note}</p>
                  </div>
                )}
                {turn.handoff?.choice === "book" && (
                  <span className="status-mark pg-status handoff-declined">{t.assistant.handoff.declined}</span>
                )}
                {turn.handoff?.choice === "library" &&
                  (!turn.handoff.sent || libraryTurn(turn.id) ? (
                    // Ведёт в раздел без отправки: отправленный ответ там уже есть, неотправленный
                    // вопрос встанет в поле ввода (5.10).
                    <a
                      className="pg-btn pg-btn--ghost pg-btn--sm handoff-open"
                      href={turn.handoff.sent ? "/assistant" : handoffHref(turn)}
                      onClick={(e) => {
                        if (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
                        e.preventDefault();
                        if (mode === "book") onClose();
                        navigate(turn.handoff!.sent ? "/assistant" : handoffHref(turn));
                      }}
                    >
                      {t.assistant.handoff.open}
                    </a>
                  ) : (
                    <span className="status-mark pg-status handoff-deleted">{t.assistant.handoff.deleted}</span>
                  ))}
                <div className="turn__actions">
                  {turn.suggestion && (
                    <button className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => navigate(`/graph/${turn.suggestion!.entity_id}?recipe=${turn.suggestion!.recipe}`)}>
                      <Icon name="graph" small />
                      {turn.suggestion.label ? t.assistant.openGraph(recipeTitle(t, turn.suggestion.recipe), turn.suggestion.label) : turn.suggestion.title}
                    </button>
                  )}
                  {!isStreaming && (turn.status === "error" || turn.status === "stopped" || turn.status === "streaming" || retryable(turn)) && (
                    <button
                      className="pg-btn pg-btn--secondary pg-btn--sm"
                      onClick={() =>
                        send(turn.question, turn.selection ? { text: turn.selection, paragraphs: turn.selectionParagraphs ?? [] } : null)
                      }
                    >
                      <Icon name="retry" small />
                      {t.assistant.retry}
                    </button>
                  )}
                  {!isStreaming && turn.fragments.length > 0 && (
                    <button className="pg-btn pg-btn--ghost pg-btn--sm copy-answer" onClick={() => navigator.clipboard?.writeText(answerText(turn, t.assistant.ungroundedMark))}>
                      <Icon name="copy" small />
                      {t.assistant.copy}
                    </button>
                  )}
                </div>
                {turn.message?.code === "no_answer" && turn.message.suggestions && turn.message.suggestions.length > 0 && (
                  <div className="assistant__suggestions">
                    <p>{t.assistant.nearby}</p>
                    <ul>
                      {turn.message.suggestions.map((s, i) => (
                        <li key={i}>
                          {s.paragraph_id ? (
                            <a
                              href={`/p/${s.paragraph_id}`}
                              onClick={(e) => {
                                e.preventDefault();
                                navigate(`/p/${s.paragraph_id}`);
                              }}
                            >
                              {s.title}
                            </a>
                          ) : (
                            s.title
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </li>
            );
          })}
        </ol>
        {active.messages.length === 0 && (
          <p className="assistant__empty">{mode === "library" ? t.assistantPage.empty : t.assistant.empty}</p>
        )}
        {problem && (
          <div className="assistant-notice pg-notice pg-notice--warning" role="alert">
            <Icon name="warning" />
            <div>{messageText(t, problem)}</div>
            {problem.code === "read_notice" && (
              <button className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => requestNotice()}>
                {t.assistant.showNotice}
              </button>
            )}
          </div>
        )}
        {mode === "library" && initialQuestion && (() => {
          const asked = set.sessions.flatMap((s) => s.messages).find((m) => m.question === initialQuestion && (m.handoffId || m.from));
          if (asked && (!pending || question === initialQuestion)) {
            return (
              <div className="assistant-notice pg-notice assistant__asked" role="status">
                <Icon name="info" />
                <div>{t.assistantPage.asked}</div>
                <button
                  type="button"
                  className="pg-btn pg-btn--secondary pg-btn--sm"
                  onClick={() => document.getElementById(`turn-${asked.id}`)?.scrollIntoView({ block: "start" })}
                >
                  {t.assistantPage.showAnswer}
                </button>
              </div>
            );
          }
          if (!asked && pendingFrom && (!pending || blocked) && question === initialQuestion) {
            return (
              <div className="assistant-notice pg-notice assistant__pending" role="status">
                <Icon name="info" />
                <div>{withTitle(t.assistantPage.pending, sources[pendingFrom], "")}</div>
                <button type="button" className="pg-btn pg-btn--ghost pg-btn--sm" onClick={() => setDraft((d) => ({ ...d, question: "" }))}>
                  {t.assistantPage.clear}
                </button>
              </div>
            );
          }
          return null;
        })()}
        <form
          className="assistant__form"
          onSubmit={(e) => {
            e.preventDefault();
            if (question.length > MAX_QUESTION || limited) return;
            if (!question.trim() && !fragment) return;
            send(question, fragment, mode === "library" && pendingFrom && question === initialQuestion ? { sourceId: pendingFrom } : {});
          }}
        >
          {fragment && (
            <blockquote className="selection-context">
              {fragment.text}
              <button type="button" className="pg-btn pg-btn--ghost pg-btn--icon pg-btn--sm" aria-label={t.assistant.removeFragment} title={t.assistant.removeFragment} onClick={() => setDraft((d) => ({ ...d, fragment: null }))}>
                <Icon name="close" small />
              </button>
            </blockquote>
          )}
          <textarea
            className="pg-input"
            aria-label={t.assistant.question}
            data-assistant-question=""
            value={question}
            onChange={(e) => {
              const value = e.target.value;
              setDraft((d) => ({ ...d, question: value }));
            }}
            onKeyDown={(e) => {
              // Enter — отправить, Shift+Enter — новая строка (5.9).
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                e.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder={t.assistant.placeholder}
          />
          {question.length > MAX_QUESTION * 0.8 && (
            <p className={question.length > MAX_QUESTION ? "assistant__counter is-over" : "assistant__counter"}>
              {question.length > MAX_QUESTION ? t.assistant.questionTooLong(MAX_QUESTION) : t.assistant.counter(question.length, MAX_QUESTION)}
            </p>
          )}
          <div className="assistant-actions">
            {streamingTurn ? (
              <button type="button" className="pg-btn pg-btn--primary" onClick={() => live.get(streamingTurn.id)?.controller.abort("stopped")}>
                <Icon name="stop" small />
                {t.assistant.stop}
              </button>
            ) : (
              <button type="submit" className="pg-btn pg-btn--primary" aria-disabled={question.length > MAX_QUESTION || limited || undefined}>
                {t.assistant.ask}
              </button>
            )}
          </div>
        </form>
      </div>
    </>
  );
}

// Сообщения, после которых по таблице 5.7 предлагается «Повторить».
function retryable(turn: Turn): boolean {
  const code = turn.message?.code;
  return code === "llm_unavailable" || code === "search_unavailable" || code === "unavailable";
}

// Подсказка ссылки (5.4): книга, глава и начало абзаца; без них — заголовок раздела.
function citationTitle(t: Catalog, c: Citation): string {
  const head = [c.source_title, c.chapter_title].filter(Boolean).join(", ");
  const start = c.paragraph_start ? `${c.paragraph_start}${c.paragraph_start.length >= 120 ? "…" : ""}` : "";
  const text = [head, start].filter(Boolean).join(" — ");
  return text || c.title || t.assistant.citationFallback;
}

function StageLine({ t, stage }: { t: Catalog; stage: StageState }) {
  const [elapsed, setElapsed] = useState(() => Math.floor((Date.now() - stage.startedAt) / 1000));
  useEffect(() => {
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - stage.startedAt) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [stage.startedAt]);
  const name = STAGE_NAMES[Math.min(stage.step, 3)];
  return (
    <p className="assistant__stage">
      <span className="assistant__dot" aria-hidden="true" />
      {/* В живую область — только смена стадии; время читалка не проговаривает каждую секунду. */}
      <span role="status">{t.assistant.stage[name]}</span>
      <span className="assistant__stage-meta">
        {t.assistant.stage.step(stage.step + 1, 4)} · {t.assistant.elapsed(elapsed)}
      </span>
      {stage.step >= 2 && (
        <span className="assistant__stage-found">{stage.found ? t.assistant.stage.found(stage.found) : t.assistant.stage.foundNone}</span>
      )}
    </p>
  );
}

// Итог хода ответа одной строкой (5.3): время и найденные абзацы, или стадия остановки.
function StageSummary({ t, turn }: { t: Catalog; turn: Turn }) {
  const stats = turn.stats!;
  const stage = t.assistant.stage[STAGE_NAMES[Math.min(stats.stage ?? 0, 3)]];
  let text: string;
  if (turn.status === "stopped") text = t.assistant.stoppedAt(stage, stats.seconds);
  else if (turn.status === "error") text = t.assistant.brokenAt(stage, stats.seconds);
  else text = t.assistant.summary(stats.seconds, stats.found);
  return (
    <p className={turn.status === "error" ? "assistant__summary is-broken" : "assistant__summary"}>
      {turn.status === "error" && <Icon name="warning" small />}
      {text}
    </p>
  );
}
