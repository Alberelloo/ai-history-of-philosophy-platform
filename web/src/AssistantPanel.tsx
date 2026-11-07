import { useEffect, useRef, useState } from "react";
import { navigate } from "./App";
import { pick, recipeTitle, useT, type Catalog } from "./i18n";
import { ru } from "./i18n/ru";
import { requestNotice, useNoticeAccepted } from "./Notice";
import { ScopeToggle, useScope } from "./scope";
import { storage } from "./storage";
import { GeneratedMark, Icon, StatusMark } from "./ui";

// Панель ассистента рядом с текстом. Ответ приходит потоком событий NDJSON; каждый фрагмент
// уже проверен сервером: со ссылками на абзацы или с пометкой «без опоры на источники».

type Citation = {
  kind?: "paragraph" | "statement";
  paragraph_id: string | null;
  statement_id?: string | null;
  source_id: string;
  chapter_id: string | null;
  title: string;
};
type Contradiction = { kind: string; entity: string; expected: string; found: string };
type Fragment = { text: string; grounded: boolean; citations: Citation[]; contradicts?: Contradiction[] };
type Suggestion = { entity_id: string; recipe: string; label?: string; title: string };
// Сообщение к ответу: код сервера (reason, kind или тип события) — переводится по каталогу,
// текст сервера — запасной вариант для неизвестного кода.
type Message = { code?: string; text?: string; minutes?: number };
type Turn = {
  question: string;
  selection?: string;
  fragments: Fragment[];
  status: "streaming" | "done" | "stopped" | "error";
  notice?: string;
  message?: Message;
  suggestion?: Suggestion;
};

const MAX_SELECTION = 4000;
const MAX_QUESTION = 2000;

// Диалоги хранятся в общем хранилище браузера; самые старые удаляются при пределе объёма.
function loadDialog(): Turn[] {
  return storage.dialog().filter((t): t is Turn => typeof (t as Turn)?.question === "string");
}

// Ответ одной строкой: для истории диалога (уходит модели, пометка всегда по-русски, как в
// подсказках сервера) и для копирования (пометка на языке интерфейса).
export function answerText(turn: Turn, mark: string = ru.assistant.ungroundedMark): string {
  return turn.fragments.map((f) => (f.grounded ? f.text : `${mark} ${f.text}`)).join(" ");
}

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
  if (message.code === "unavailable") return t.assistant.unavailable;
  if (message.code === "broken") return t.assistant.broken;
  if (SERVER_CODES.includes(message.code as ServerCode)) return t.assistant[message.code as ServerCode];
  return pick(t.errors, message.code) ?? (message.text || t.assistant.unavailable);
}

// Код события потока: причина отказа, вид пояснения или сам тип события.
function eventMessage(event: Record<string, unknown>): Message {
  const code = (event.reason ?? event.kind ?? event.type) as string | undefined;
  const seconds = Number(event.retry_after_seconds ?? 0);
  return {
    code: event.type === "error" ? "broken" : code,
    text: typeof event.message === "string" ? event.message : undefined,
    minutes: seconds ? Math.max(1, Math.floor(seconds / 60)) : undefined,
  };
}

type Props = {
  sourceId: string;
  selection: string | null;
  selectionParagraphs: string[];
  onClose: () => void;
  settings?: { sourcesOnly: boolean; generation: boolean; scope: "all" | "current" };
};

export function AssistantPanel({ sourceId, selection, selectionParagraphs, onClose, settings }: Props) {
  const t = useT();
  const [turns, setTurns] = useState<Turn[]>(loadDialog);
  const accepted = useNoticeAccepted();
  const [question, setQuestion] = useState("");
  const [problem, setProblem] = useState<Message | null>(null);
  const abort = useRef<AbortController | null>(null);
  const current = useRef<string | undefined>(selection ?? undefined);
  const paragraphs = useRef<string[]>(selectionParagraphs);
  const scope = useScope();

  useEffect(() => {
    current.current = selection ?? undefined;
    paragraphs.current = selectionParagraphs;
  }, [selection, selectionParagraphs]);
  useEffect(() => storage.saveDialog(turns), [turns]);

  const update = (index: number, change: (t: Turn) => Turn) =>
    setTurns((all) => all.map((turn, i) => (i === index ? change(turn) : turn)));

  async function send(text: string, selected?: string) {
    setProblem(null);
    if (!accepted) {
      // Сначала читатель видит, что вопросы обрабатывает внешний провайдер.
      setProblem({ code: "read_notice" });
      requestNotice();
      return;
    }
    if ((selected ?? "").length > MAX_SELECTION || text.length > MAX_QUESTION) {
      setProblem({ code: "too_long" });
      return;
    }
    const history = turns
      .filter((turn) => turn.status === "done")
      .map((turn) => ({ question: turn.question, answer: answerText(turn) }));
    const index = turns.length;
    setTurns((all) => [...all, { question: text, selection: selected, fragments: [], status: "streaming" }]);
    setQuestion("");
    const controller = new AbortController();
    abort.current = controller;
    try {
      const response = await fetch("/api/assistant/v1/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          question: text,
          selection: selected ?? null,
          selection_paragraphs: selected ? paragraphs.current : [],
          source_id: sourceId,
          history,
          sources_only: settings?.sourcesOnly ?? scope.sourcesOnly,
          generation: settings?.generation ?? scope.generation,
          // Общий переключатель источников: «только выбранный учебник» — поиск только в нём.
          scope: settings?.scope ?? (scope.onlyTextbook ? "current" : "all"),
        }),
      });
      if (!response.ok) {
        // Отказ шлюза (например, нет токена страницы) приходит обычным JSON.
        const body = await response.json().catch(() => ({}));
        update(index, (turn) => ({
          ...turn,
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
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const event = JSON.parse(line);
          if (event.type === "fragment") {
            update(index, (turn) => ({ ...turn, fragments: [...turn.fragments, event] }));
          } else if (event.type === "suggestion") {
            update(index, (turn) => ({ ...turn, suggestion: event as Suggestion }));
          } else if (event.type === "done") {
            update(index, (turn) => ({ ...turn, status: "done" }));
          } else if (event.type === "error") {
            update(index, (turn) => ({ ...turn, status: "error", message: eventMessage(event) }));
          } else {
            // notice, refused, unavailable, no_answer — понятное сообщение читателю
            update(index, (turn) => ({
              ...turn,
              message: eventMessage(event),
              status: event.type === "notice" ? turn.status : "done",
            }));
          }
        }
      }
      update(index, (turn) => (turn.status === "streaming" ? { ...turn, status: "done" } : turn));
    } catch (e) {
      // Остановка читателем: браузер может сообщить о ней разными ошибками, судим по сигналу.
      if (controller.signal.aborted || (e as Error).name === "AbortError")
        update(index, (turn) => ({ ...turn, status: "stopped" }));
      else update(index, (turn) => ({ ...turn, status: "error", message: { code: "broken" } }));
    }
  }

  return (
    <>
      <div className="pg-panel__head">
        <h2 className="pg-panel__title">{t.assistant.label}</h2>
        <button
          className="pg-btn pg-btn--ghost pg-btn--sm"
          onClick={() => {
            storage.newDialog();
            setTurns([]);
          }}
        >
          <Icon name="newDialog" small />
          {t.assistant.newDialog}
        </button>
        <button
          className="pg-btn pg-btn--ghost pg-btn--icon pg-btn--sm"
          aria-label={t.assistant.close}
          title={t.assistant.close}
          onClick={onClose}
        >
          <Icon name="close" small />
        </button>
      </div>
      <div className="pg-panel__body assistant__body">
        <ScopeToggle textbook={sourceId} />
        <ol className="turns">
          {turns.map((turn, i) => {
            const notice = messageText(t, turn.message, turn.notice);
            return (
              <li key={i} className="turn">
                {turn.selection && <blockquote className="selection-context">{turn.selection}</blockquote>}
                <p className="question">{turn.question}</p>
                {notice && (
                  <div
                    className={
                      turn.status === "error" ? "assistant-notice pg-notice pg-notice--danger" : "assistant-notice pg-notice"
                    }
                    role="status"
                  >
                    <Icon name={turn.status === "error" ? "warning" : "info"} />
                    <div>{notice}</div>
                  </div>
                )}
                <div className="answer" data-status={turn.status}>
                  {turn.fragments.map((f, j) => {
                    const contradicts = f.contradicts && f.contradicts.length > 0;
                    return (
                      <span key={j} className={f.grounded ? "fragment" : "fragment ungrounded pg-generated"}>
                        {contradicts && (
                          <span
                            className="contradiction-mark"
                            title={f.contradicts!.map((c) => t.assistant.contradiction(c.entity, c.expected)).join("; ")}
                          >
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
                              title={c.title || t.assistant.source}
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
                <div className="turn__actions">
                  {turn.suggestion && (
                    <button
                      className="pg-btn pg-btn--secondary pg-btn--sm"
                      onClick={() => navigate(`/graph/${turn.suggestion!.entity_id}?recipe=${turn.suggestion!.recipe}`)}
                    >
                      <Icon name="graph" small />
                      {turn.suggestion.label
                        ? t.assistant.openGraph(recipeTitle(t, turn.suggestion.recipe), turn.suggestion.label)
                        : turn.suggestion.title}
                    </button>
                  )}
                  {turn.status === "error" && (
                    <button className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => send(turn.question, turn.selection)}>
                      <Icon name="retry" small />
                      {t.assistant.retry}
                    </button>
                  )}
                  {turn.status !== "streaming" && turn.fragments.length > 0 && (
                    <button
                      className="pg-btn pg-btn--ghost pg-btn--sm copy-answer"
                      onClick={() => navigator.clipboard?.writeText(answerText(turn, t.assistant.ungroundedMark))}
                    >
                      <Icon name="copy" small />
                      {t.assistant.copy}
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
        {problem && (
          <div className="assistant-notice pg-notice pg-notice--warning" role="alert">
            <Icon name="info" />
            <div>{messageText(t, problem)}</div>
          </div>
        )}
        <form
          className="assistant__form"
          onSubmit={(e) => {
            e.preventDefault();
            send(question, current.current);
            current.current = undefined;
          }}
        >
          {current.current && <blockquote className="selection-context">{current.current}</blockquote>}
          <textarea
            className="pg-input"
            aria-label={t.assistant.question}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={t.assistant.placeholder}
          />
          <div className="assistant-actions">
            <button type="submit" className="pg-btn pg-btn--primary">
              {t.assistant.ask}
            </button>
            <button type="button" className="pg-btn pg-btn--ghost" onClick={() => abort.current?.abort()}>
              <Icon name="stop" small />
              {t.assistant.stop}
            </button>
          </div>
        </form>
      </div>
    </>
  );
}
