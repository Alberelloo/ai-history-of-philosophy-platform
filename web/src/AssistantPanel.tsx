import { useEffect, useRef, useState } from "react";
import { navigate } from "./App";
import { ScopeToggle, useScope } from "./scope";

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
type Suggestion = { entity_id: string; recipe: string; title: string };
type Turn = {
  question: string;
  selection?: string;
  fragments: Fragment[];
  status: "streaming" | "done" | "stopped" | "error";
  notice?: string;
  suggestion?: Suggestion;
};

const DIALOG_KEY = "philograph:dialog:v1";
const MAX_SELECTION = 4000;
const MAX_QUESTION = 2000;
const UNGROUNDED_MARK = "[без опоры на источники]";

function loadDialog(): Turn[] {
  try {
    const raw = window.localStorage.getItem(DIALOG_KEY);
    return raw ? (JSON.parse(raw) as Turn[]) : [];
  } catch {
    return [];
  }
}

function saveDialog(turns: Turn[]) {
  try {
    window.localStorage.setItem(DIALOG_KEY, JSON.stringify(turns.slice(-20)));
  } catch {
    // без хранилища диалог живёт до закрытия вкладки
  }
}

export function answerText(turn: Turn): string {
  return turn.fragments.map((f) => (f.grounded ? f.text : `${UNGROUNDED_MARK} ${f.text}`)).join(" ");
}

type Props = {
  sourceId: string;
  selection: string | null;
  selectionParagraphs: string[];
  onClose: () => void;
  settings?: { sourcesOnly: boolean; generation: boolean; scope: "all" | "current" };
};

export function AssistantPanel({ sourceId, selection, selectionParagraphs, onClose, settings }: Props) {
  const [turns, setTurns] = useState<Turn[]>(loadDialog);
  const [question, setQuestion] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const current = useRef<string | undefined>(selection ?? undefined);
  const paragraphs = useRef<string[]>(selectionParagraphs);
  const scope = useScope();

  useEffect(() => {
    current.current = selection ?? undefined;
    paragraphs.current = selectionParagraphs;
  }, [selection, selectionParagraphs]);
  useEffect(() => saveDialog(turns), [turns]);

  const update = (index: number, change: (t: Turn) => Turn) =>
    setTurns((all) => all.map((t, i) => (i === index ? change(t) : t)));

  async function send(text: string, selected?: string) {
    setProblem(null);
    if ((selected ?? "").length > MAX_SELECTION || text.length > MAX_QUESTION) {
      setProblem("Слишком длинный фрагмент или вопрос: выделите меньше.");
      return;
    }
    const history = turns
      .filter((t) => t.status === "done")
      .map((t) => ({ question: t.question, answer: answerText(t) }));
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
          sources_only: settings?.sourcesOnly ?? false,
          generation: settings?.generation ?? scope.generation,
          // Общий переключатель источников: «только выбранный учебник» — поиск только в нём.
          scope: settings?.scope ?? (scope.onlyTextbook ? "current" : "all"),
        }),
      });
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
            update(index, (t) => ({ ...t, fragments: [...t.fragments, event] }));
          } else if (event.type === "suggestion") {
            update(index, (t) => ({ ...t, suggestion: event as Suggestion }));
          } else if (event.type === "done") {
            update(index, (t) => ({ ...t, status: "done" }));
          } else if (event.type === "error") {
            update(index, (t) => ({ ...t, status: "error", notice: event.message }));
          } else {
            // notice, refused, unavailable, no_answer — понятное сообщение читателю
            update(index, (t) => ({
              ...t,
              notice: event.message,
              status: event.type === "notice" ? t.status : "done",
            }));
          }
        }
      }
      update(index, (t) => (t.status === "streaming" ? { ...t, status: "done" } : t));
    } catch (e) {
      // Остановка читателем: браузер может сообщить о ней разными ошибками, судим по сигналу.
      if (controller.signal.aborted || (e as Error).name === "AbortError")
        update(index, (t) => ({ ...t, status: "stopped" }));
      else update(index, (t) => ({ ...t, status: "error", notice: "Ответ оборвался. Можно повторить." }));
    }
  }

  return (
    <aside className="assistant" aria-label="Ассистент">
      <header>
        <h2>Ассистент</h2>
        <button className="link" onClick={() => setTurns([])}>
          Новый диалог
        </button>
        <button className="link" aria-label="Закрыть ассистента" onClick={onClose}>
          ✕
        </button>
      </header>
      <ScopeToggle textbook={sourceId} />
      <ol className="turns">
        {turns.map((turn, i) => (
          <li key={i} className="turn">
            {turn.selection && <blockquote className="selection-context">{turn.selection}</blockquote>}
            <p className="question">{turn.question}</p>
            {turn.notice && <p className="assistant-notice" role="status">{turn.notice}</p>}
            <div className="answer" data-status={turn.status}>
              {turn.fragments.map((f, j) => (
                <span key={j} className={f.grounded ? "fragment" : "fragment ungrounded"}>
                  {f.contradicts && f.contradicts.length > 0 && (
                    <span
                      className="contradiction-mark"
                      role="img"
                      aria-label="Противоречит источникам"
                      title={f.contradicts.map((c) => `${c.entity}: в онтологии ${c.expected}`).join("; ")}
                    >
                      ⚠
                    </span>
                  )}
                  {!f.grounded && (!f.contradicts || f.contradicts.length === 0) && (
                    <span className="ungrounded-mark" role="img" aria-label="Без опоры на источники" title="Без опоры на источники">
                      ◇
                    </span>
                  )}
                  {f.text}
                  {f.citations.map((c) =>
                    c.paragraph_id ? (
                      <a
                        key={c.statement_id ?? c.paragraph_id}
                        className="citation"
                        href={`/p/${c.paragraph_id}`}
                        title={c.title}
                        onClick={(e) => {
                          e.preventDefault();
                          navigate(`/p/${c.paragraph_id}`);
                        }}
                      >
                        [{c.title || "источник"}]
                      </a>
                    ) : (
                      <span key={c.statement_id ?? c.title} className="citation" title={c.title}>
                        [{c.title}]
                      </span>
                    ),
                  )}{" "}
                </span>
              ))}
              {turn.status === "stopped" && <span className="status-mark">остановлено</span>}
            </div>
            {turn.suggestion && (
              <button
                className="link"
                onClick={() => navigate(`/graph/${turn.suggestion!.entity_id}?recipe=${turn.suggestion!.recipe}`)}
              >
                {turn.suggestion.title}
              </button>
            )}
            {turn.status === "error" && (
              <button className="link" onClick={() => send(turn.question, turn.selection)}>
                Повторить
              </button>
            )}
            {turn.status !== "streaming" && turn.fragments.length > 0 && (
              <button className="link copy-answer" onClick={() => navigator.clipboard?.writeText(answerText(turn))}>
                Скопировать ответ
              </button>
            )}
          </li>
        ))}
      </ol>
      {problem && <p className="assistant-notice" role="alert">{problem}</p>}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(question, current.current);
          current.current = undefined;
        }}
      >
        {current.current && <blockquote className="selection-context">{current.current}</blockquote>}
        <textarea
          aria-label="Вопрос ассистенту"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Спросите о выделенном месте или о чём угодно в философии"
        />
        <div className="assistant-actions">
          <button type="submit" className="primary">
            Спросить
          </button>
          <button type="button" onClick={() => abort.current?.abort()}>
            Остановить
          </button>
        </div>
      </form>
    </aside>
  );
}
