import { useEffect, useRef, useState } from "react";
import { navigate } from "./App";
import { pick, recipeTitle, useT, type Catalog } from "./i18n";
import { ru } from "./i18n/ru";
import { requestNotice, useNoticeAccepted } from "./Notice";
import { ScopeToggle, useScope } from "./scope";
import {
  newId,
  storage,
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
};

let pending: PendingHandoff | null = null;
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

function eventMessage(event: Record<string, unknown>): Message {
  const code = (event.reason ?? event.kind ?? event.type) as string | undefined;
  const seconds = Number(event.retry_after_seconds ?? 0);
  return {
    code: event.type === "error" ? "broken" : code,
    text: typeof event.message === "string" ? event.message : undefined,
    minutes: seconds ? Math.max(1, Math.floor(seconds / 60)) : undefined,
  };
}

// Ответ одной строкой: для истории диалога (пометка всегда по-русски) и для копирования.
export function answerText(turn: Turn, mark: string = ru.assistant.ungroundedMark): string {
  return turn.fragments.map((f) => (f.grounded ? f.text : `${mark} ${f.text}`)).join(" ");
}

// Название сессии: заданное читателем или первая фраза первого вопроса (до 60 знаков).
function sessionTitle(session: Session, fallback: string): string {
  if (session.title) return session.title;
  const first = session.messages.find((m) => m.question);
  if (!first) return fallback;
  const phrase = first.question.split(/[.!?]/)[0].trim();
  return phrase.length > 60 ? `${phrase.slice(0, 57).trimEnd()}…` : phrase;
}

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
  settings?: { sourcesOnly: boolean; generation: boolean; scope: "all" | "current" };
};

export function AssistantPanel({ sourceId, selection, selectionParagraphs, onClose, onBack, backLabel, mode = "book", pending = null, initialQuestion, settings }: Props) {
  const t = useT();
  const [set, setSet] = useState<DialogSet>(() =>
    mode === "library" ? storage.libraryDialogs() : storage.dialogsFor(sourceId),
  );
  const accepted = useNoticeAccepted();
  const [question, setQuestion] = useState(initialQuestion ?? "");
  const [problem, setProblem] = useState<Message | null>(null);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const [selectionDraft, setSelectionDraft] = useState<{ text: string; paragraphs: string[] } | null>(
    selection ? { text: selection, paragraphs: selectionParagraphs } : null,
  );
  const [streams, setStreams] = useState<Record<string, StageState>>({});
  const aborts = useRef<Record<string, AbortController>>({});
  const scope = useScope();

  const activeId = set.activeId;
  const active = set.sessions.find((s) => s.id === activeId) ?? set.sessions[0];

  // Внешнее выделение заменяет фрагмент (5.2): новое выделение не добавляет второй.
  useEffect(() => {
    if (selection) setSelectionDraft({ text: selection, paragraphs: selectionParagraphs });
  }, [selection, selectionParagraphs]);

  // Каждое изменение набора сохраняется в хранилище этой книги или раздела «Ассистент».
  useEffect(() => {
    if (mode === "library") storage.saveLibraryDialogs(set);
    else storage.saveDialogs(sourceId, set);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [set, sourceId, mode]);

  const patchSession = (id: string, change: (s: Session) => Session) =>
    setSet((prev) => ({
      ...prev,
      updatedAt: Date.now(),
      sessions: prev.sessions.map((s) => (s.id === id ? change(s) : s)),
    }));

  const patchTurn = (sessionId: string, turnId: string, change: (t: Turn) => Turn) =>
    patchSession(sessionId, (s) => ({
      ...s,
      updatedAt: Date.now(),
      messages: s.messages.map((m) => (m.id === turnId ? change(m) : m)),
    }));

  const switchSession = (id: string) => {
    setSet((prev) => ({ ...prev, activeId: id }));
    setSessionsOpen(false);
    // Пустая сессия без названия, с которой ушли, удаляется сама (5.8).
    setSet((prev) => {
      const left = prev.sessions.find((s) => s.id === prev.activeId);
      if (left && left.id !== id && left.messages.length === 0 && !left.title) {
        return {
          ...prev,
          activeId: id,
          sessions: prev.sessions.filter((s) => s.id !== left.id),
        };
      }
      return { ...prev, activeId: id };
    });
  };

  const createSession = () => {
    if (active.messages.length === 0 && !active.title) {
      setSessionsOpen(false);
      return; // пустая сессия не плодится — фокус остаётся в поле вопроса
    }
    const session: Session = { id: newId(), title: "", createdAt: Date.now(), updatedAt: Date.now(), messages: [] };
    setSet((prev) => ({ updatedAt: Date.now(), activeId: session.id, sessions: [...prev.sessions, session] }));
    setSessionsOpen(false);
  };

  const renameSession = (id: string) => {
    const name = renameDraft.trim();
    patchSession(id, (s) => ({ ...s, title: name })); // пустое — «название по первой фразе»
    setRenaming(null);
  };

  const deleteSession = (id: string) => {
    const controller = aborts.current[id];
    controller?.abort();
    delete aborts.current[id];
    setSet((prev) => {
      const sessions = prev.sessions.filter((s) => s.id !== id);
      if (!sessions.length) {
        const fresh = { id: newId(), title: "", createdAt: Date.now(), updatedAt: Date.now(), messages: [] };
        return { updatedAt: Date.now(), activeId: fresh.id, sessions: [fresh] };
      }
      const activeId = prev.activeId === id ? sessions[sessions.length - 1].id : prev.activeId;
      return { updatedAt: Date.now(), activeId, sessions };
    });
    setConfirming(null);
  };

  async function send(
    text: string,
    selected?: string,
    sessionId = active.id,
    handoff?: { declined: boolean; reason: string },
    handoffId?: string,
    from?: { sourceId: string; chapterId?: string },
  ) {
    setProblem(null);
    if (!accepted) {
      setProblem({ code: "read_notice" });
      requestNotice();
      return;
    }
    if ((selected ?? "").length > MAX_SELECTION || text.length > MAX_QUESTION) {
      setProblem({ code: "too_long" });
      return;
    }
    const history = active.messages
      .filter((m) => m.status === "done")
      .map((m) => ({ question: m.question, answer: answerText(m) }));
    const turnId = newId();
    const turn: Turn = {
      id: turnId,
      question: text,
      selection: selected,
      fragments: [],
      status: "streaming",
      handoffId,
      from,
    };
    patchSession(sessionId, (s) => ({ ...s, updatedAt: Date.now(), messages: [...s.messages, turn] }));
    setQuestion("");
    setSelectionDraft(null);
    setStreams((m) => ({ ...m, [turnId]: { step: 0, startedAt: Date.now() } }));
    const controller = new AbortController();
    aborts.current[turnId] = controller;
    let timer: number | undefined = window.setTimeout(() => controller.abort("timeout"), TIMEOUT_MS);
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
          question: text,
          selection: selected ?? null,
          selection_paragraphs: selected ? selectionParagraphs : [],
          source_id: sourceId,
          history,
          sources_only: settings?.sourcesOnly ?? scope.sourcesOnly,
          generation: settings?.generation ?? scope.generation,
          scope: settings?.scope ?? (scope.onlyTextbook ? "current" : "all"),
          context: mode === "library" ? "library" : "book",
          handoff_declined: handoff?.declined ?? false,
          handoff_reason: handoff?.reason ?? null,
        }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        patchTurn(sessionId, turnId, (t) => ({
          ...t,
          status: "done",
          message: { code: body.kind ?? "unavailable", text: body.error },
        }));
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
            if (event.name === "searching") setStreams((m) => ({ ...m, [turnId]: { ...m[turnId], step: 1 } }));
            else if (event.name === "composing")
              setStreams((m) => ({ ...m, [turnId]: { ...m[turnId], step: 2, found: Number(event.found ?? 0) } }));
          } else if (event.type === "fragment") {
            setStreams((m) => ({ ...m, [turnId]: { ...m[turnId], step: 3 } }));
            patchTurn(sessionId, turnId, (t) => ({ ...t, fragments: [...t.fragments, event as Fragment] }));
          } else if (event.type === "suggestion") {
            patchTurn(sessionId, turnId, (t) => ({ ...t, suggestion: event as Suggestion }));
          } else if (event.type === "handoff") {
            patchTurn(sessionId, turnId, (t) => ({ ...t, handoff: { reason: event.reason } }));
          } else if (event.type === "done") {
            patchTurn(sessionId, turnId, (t) => ({ ...t, status: "done" }));
          } else if (event.type === "error") {
            patchTurn(sessionId, turnId, (t) => ({ ...t, status: "error", message: eventMessage(event) }));
          } else {
            patchTurn(sessionId, turnId, (t) => ({
              ...t,
              message: eventMessage(event),
              status: event.type === "notice" ? t.status : "done",
            }));
          }
        }
      }
      patchTurn(sessionId, turnId, (t) => (t.status === "streaming" ? { ...t, status: "done" } : t));
    } catch (e) {
      const aborted = controller.signal.aborted;
      if (aborted && controller.signal.reason === "timeout") {
        patchTurn(sessionId, turnId, (t) => ({ ...t, status: "error", message: { code: "timeout" } }));
      } else if (aborted || (e as Error).name === "AbortError") {
        patchTurn(sessionId, turnId, (t) => ({ ...t, status: "stopped" }));
      } else {
        patchTurn(sessionId, turnId, (t) => ({ ...t, status: "error", message: { code: "broken" } }));
      }
    } finally {
      window.clearTimeout(timer);
      delete aborts.current[turnId];
      setStreams((m) => {
        const next = { ...m };
        delete next[turnId];
        return next;
      });
    }
  }

  // Поручение перехода из панели (5.10): обмен с handoffId добавляется и отправляется один раз.
  useEffect(() => {
    if (!pending) return;
    const state = window.history.state as { consumed?: boolean } | null;
    if (state?.consumed) return;
    if (set.sessions.some((s) => s.messages.some((m) => m.handoffId === pending.id))) return;
    send(pending.question, pending.selection, active.id, undefined, pending.id, { sourceId: pending.from });
    window.history.replaceState({ ...state, consumed: true }, "");
    clearPendingHandoff();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending]);

  const streaming = active.messages.filter((m) => m.status === "streaming");
  const streamingTurn = streaming[streaming.length - 1];

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
          {mode !== "library" && <span className="assistant__book">{t.assistant.bookDialog(sourceId)}</span>}
        </div>
        <button
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
          <ul className="assistant__sessions" role="list" aria-label={t.assistant.session.list}>
            {set.sessions.map((s) => {
              const running = s.messages.some((m) => m.status === "streaming");
              return (
                <li key={s.id} className={s.id === activeId ? "assistant__session is-active" : "assistant__session"} aria-current={s.id === activeId ? "true" : undefined}>
                  {renaming === s.id ? (
                    <input
                      className="pg-input"
                      aria-label={t.assistant.session.renameLabel}
                      value={renameDraft}
                      onChange={(e) => setRenameDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") renameSession(s.id);
                        if (e.key === "Escape") setRenaming(null);
                      }}
                      onBlur={() => setRenaming(null)}
                      autoFocus
                    />
                  ) : confirming === s.id ? (
                    <span className="assistant__session-confirm" role="group">
                      <span className="assistant__session-confirm-text">
                        {running ? t.assistant.session.deleteRunning : t.assistant.session.deleteConfirm}
                      </span>
                      <button className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => deleteSession(s.id)}>
                        {t.assistant.session.delete}
                      </button>
                      <button className="pg-btn pg-btn--ghost pg-btn--sm" onClick={() => setConfirming(null)}>
                        {t.assistant.session.cancel}
                      </button>
                    </span>
                  ) : (
                    <>
                      <button className="pg-btn pg-btn--ghost assistant__session-title" onClick={() => switchSession(s.id)}>
                        {running && <span className="assistant__dot" aria-label={t.panel.answering} />}
                        {sessionTitle(s, t.assistant.session.new)}
                      </button>
                      <button
                        className="pg-btn pg-btn--ghost pg-btn--sm"
                        aria-label={`${t.assistant.session.rename}: ${sessionTitle(s, t.assistant.session.new)}`}
                        title={t.assistant.session.rename}
                        onClick={() => {
                          setRenaming(s.id);
                          setRenameDraft(s.title);
                        }}
                      >
                        {t.assistant.session.rename}
                      </button>
                      <button
                        className="pg-btn pg-btn--ghost pg-btn--sm"
                        aria-label={`${t.assistant.session.delete}: ${sessionTitle(s, t.assistant.session.new)}`}
                        title={t.assistant.session.delete}
                        onClick={() => setConfirming(s.id)}
                      >
                        {t.assistant.session.delete}
                      </button>
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        <ScopeToggle textbook={sourceId} />
        {((settings?.sourcesOnly ?? scope.sourcesOnly) || !(settings?.generation ?? scope.generation)) && (
          <p className="assistant__sources-only">
            {t.assistant.sourcesOnlyNote}{" "}
            <a href="/settings#assistant" onClick={(e) => { e.preventDefault(); navigate("/settings#assistant"); }}>
              {t.assistant.changeInSettings}
            </a>
          </p>
        )}
        <ol className="turns">
          {active.messages.map((turn) => {
            const notice = messageText(t, turn.message);
            const isStreaming = turn.status === "streaming";
            const st = isStreaming ? streams[turn.id] : undefined;
            return (
              <li key={turn.id} className="turn">
                {turn.selection && <blockquote className="selection-context">{turn.selection}</blockquote>}
                <p className="question">{turn.question}</p>
                {isStreaming && st && (
                  <StageLine t={t} stage={st} />
                )}
                {notice && (
                  <div className={turn.status === "error" ? "assistant-notice pg-notice pg-notice--danger" : "assistant-notice pg-notice"} role="status">
                    <Icon name={turn.status === "error" ? "warning" : "info"} />
                    <div>{notice}</div>
                    {turn.message?.code === "read_notice" && (
                      <button className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => requestNotice()}>
                        {t.assistant.showNotice}
                      </button>
                    )}
                  </div>
                )}
                <div className="answer" data-status={turn.status}>
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
                          c.paragraph_id ? (
                            <a
                              key={c.statement_id ?? c.paragraph_id}
                              className="citation pg-cite"
                              href={`/p/${c.paragraph_id}`}
                              title={c.source_title || c.title || t.assistant.citationFallback}
                              onClick={(e) => {
                                e.preventDefault();
                                navigate(`/p/${c.paragraph_id}`);
                              }}
                            >
                              {k + 1}
                            </a>
                          ) : (
                            <span key={c.statement_id ?? c.title} className="citation pg-cite pg-cite--statement" title={c.title}>
                              {k + 1}
                            </span>
                          ),
                        )}{" "}
                      </span>
                    );
                  })}
                  {turn.status === "stopped" && <span className="status-mark pg-status">{t.assistant.stopped}</span>}
                </div>
                {turn.handoff && !turn.handoff.choice && (
                  <div className="handoff-block">
                    <p>{turn.handoff.reason === "broader" ? t.assistant.handoff.broader : t.assistant.handoff.outside}</p>
                    <div className="handoff-block__actions">
                      <button
                        className="pg-btn pg-btn--secondary pg-btn--sm"
                        onClick={() => {
                          patchTurn(active.id, turn.id, (t) => ({ ...t, handoff: { reason: t.handoff!.reason, choice: "book" } }));
                          send(turn.question, turn.selection, active.id, { declined: true, reason: turn.handoff!.reason });
                        }}
                      >
                        {t.assistant.handoff.decline}
                      </button>
                      <a
                        className="pg-btn pg-btn--primary pg-btn--sm"
                        href={`/assistant?q=${encodeURIComponent(turn.question)}&from=${encodeURIComponent(sourceId)}`}
                        onClick={(e) => {
                          e.preventDefault();
                          patchTurn(active.id, turn.id, (t) => ({ ...t, handoff: { reason: t.handoff!.reason, choice: "library" } }));
                          setPendingHandoff({ id: turn.id, question: turn.question, selection: turn.selection, selectionParagraphs, from: sourceId });
                          onClose();
                          navigate(`/assistant?q=${encodeURIComponent(turn.question)}&from=${encodeURIComponent(sourceId)}`, { handoff: turn.id });
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
                {turn.handoff?.choice === "library" && (
                  <a
                    className="pg-btn pg-btn--ghost pg-btn--sm handoff-open"
                    href="/assistant"
                    onClick={(e) => {
                      e.preventDefault();
                      navigate("/assistant");
                    }}
                  >
                    {t.assistant.handoff.open}
                  </a>
                )}
                <div className="turn__actions">
                  {turn.suggestion && (
                    <button className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => navigate(`/graph/${turn.suggestion!.entity_id}?recipe=${turn.suggestion!.recipe}`)}>
                      <Icon name="graph" small />
                      {turn.suggestion.label ? t.assistant.openGraph(recipeTitle(t, turn.suggestion.recipe), turn.suggestion.label) : turn.suggestion.title}
                    </button>
                  )}
                  {(turn.status === "error" || turn.status === "stopped") && (
                    <button className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => send(turn.question, turn.selection, active.id)}>
                      <Icon name="retry" small />
                      {t.assistant.retry}
                    </button>
                  )}
                  {turn.status !== "streaming" && turn.fragments.length > 0 && (
                    <button className="pg-btn pg-btn--ghost pg-btn--sm copy-answer" onClick={() => navigator.clipboard?.writeText(answerText(turn, t.assistant.ungroundedMark))}>
                      <Icon name="copy" small />
                      {t.assistant.copy}
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
        {active.messages.length === 0 && (
          <p className="assistant__empty">{mode === "library" ? t.assistantPage.empty : t.assistant.empty}</p>
        )}
        {problem && (
          <div className="assistant-notice pg-notice pg-notice--warning" role="alert">
            <Icon name="info" />
            <div>{messageText(t, problem)}</div>
            {problem.code === "read_notice" && (
              <button className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => requestNotice()}>
                {t.assistant.showNotice}
              </button>
            )}
          </div>
        )}
        <form
          className="assistant__form"
          onSubmit={(e) => {
            e.preventDefault();
            if (question.length > MAX_QUESTION) return;
            send(question, selectionDraft?.text, active.id);
          }}
        >
          {selectionDraft && (
            <blockquote className="selection-context">
              {selectionDraft.text}
              <button type="button" className="pg-btn pg-btn--ghost pg-btn--icon pg-btn--sm" aria-label={t.assistant.removeFragment} title={t.assistant.removeFragment} onClick={() => setSelectionDraft(null)}>
                <Icon name="close" small />
              </button>
            </blockquote>
          )}
          <textarea
            className="pg-input"
            aria-label={t.assistant.question}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={t.assistant.placeholder}
          />
          {question.length > MAX_QUESTION * 0.8 && (
            <p className={question.length > MAX_QUESTION ? "assistant__counter is-over" : "assistant__counter"}>
              {question.length > MAX_QUESTION ? t.assistant.questionTooLong(MAX_QUESTION) : t.assistant.counter(question.length, MAX_QUESTION)}
            </p>
          )}
          <div className="assistant-actions">
            <button type="submit" className="pg-btn pg-btn--primary" aria-disabled={question.length > MAX_QUESTION || undefined}>
              {t.assistant.ask}
            </button>
            {streamingTurn && (
              <button type="button" className="pg-btn pg-btn--ghost" onClick={() => aborts.current[streamingTurn.id]?.abort()}>
                <Icon name="stop" small />
                {t.assistant.stop}
              </button>
            )}
          </div>
        </form>
      </div>
    </>
  );
}

function StageLine({ t, stage }: { t: Catalog; stage: StageState }) {
  const [elapsed, setElapsed] = useState(() => Math.floor((Date.now() - stage.startedAt) / 1000));
  useEffect(() => {
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - stage.startedAt) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [stage.startedAt]);
  const name = STAGE_NAMES[Math.min(stage.step, 3)];
  return (
    <p className="assistant__stage" role="status" aria-live="polite">
      <span className="assistant__dot" aria-hidden="true" />
      <span>{t.assistant.stage[name]}</span>
      <span className="assistant__stage-meta">
        {t.assistant.stage.step(stage.step + 1, 4)} · {t.assistant.elapsed(elapsed)}
      </span>
      {stage.step >= 2 && (
        <span className="assistant__stage-found">{stage.found ? t.assistant.stage.found(stage.found) : t.assistant.stage.foundNone}</span>
      )}
    </p>
  );
}
