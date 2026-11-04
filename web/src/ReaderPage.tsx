import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, type Chapter, type ChapterBlock, type TocItem } from "./api";
import { navigate } from "./App";
import { AssistantPanel } from "./AssistantPanel";
import { FootnoteRef } from "./Footnote";
import { storage } from "./storage";

type Props = { sourceId?: string; chapterId?: string; anchor: string };

function replace(path: string) {
  window.history.replaceState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

// Текст блока с отметками страниц и знаками сносок на своих местах.
function renderText(block: Extract<ChapterBlock, { type: "block" }>, chapter: Chapter) {
  type Mark = { at: number; node: (key: number) => ReactNode; skip: number };
  const marks: Mark[] = [
    ...block.pages.map(([at, label]) => ({
      at,
      skip: 0,
      node: (key: number) => (
        <span key={key} className="page-mark" data-page={label}>
          с. {label}
        </span>
      ),
    })),
    ...block.notes.flatMap(([at, id]) => {
      const note = chapter.footnotes[id];
      if (!note) return [];
      const skip = block.text.startsWith(note.marker, at) ? note.marker.length : 0;
      return [{ at, skip, node: (key: number) => <FootnoteRef key={key} note={note} /> }];
    }),
  ].sort((a, b) => a.at - b.at);
  const parts: ReactNode[] = [];
  let cursor = 0;
  marks.forEach((mark, i) => {
    if (mark.at > cursor) parts.push(block.text.slice(cursor, mark.at));
    parts.push(mark.node(i));
    cursor = Math.max(cursor, mark.at + mark.skip);
  });
  parts.push(block.text.slice(cursor));
  return parts;
}

function copyLink(paragraphId: string, onDone: () => void) {
  const url = `${window.location.origin}/p/${paragraphId}`;
  navigator.clipboard?.writeText(url).then(onDone, onDone);
}

function Toc({ items, sourceId, current }: { items: TocItem[]; sourceId: string; current: string }) {
  return (
    <ul>
      {items.map((item) => {
        const isChapter = item.chapter_id === item.id;
        const target = isChapter
          ? `/read/${sourceId}/${item.id}`
          : `/read/${sourceId}/${item.chapter_id}#s-${item.id}`;
        return (
          <li key={item.id}>
            <a
              href={target}
              aria-current={item.id === current ? "true" : undefined}
              onClick={(e) => {
                e.preventDefault();
                navigate(target);
              }}
            >
              {item.title}
            </a>
            {item.children.length > 0 && <Toc items={item.children} sourceId={sourceId} current={current} />}
          </li>
        );
      })}
    </ul>
  );
}

export function ReaderPage({ sourceId, chapterId, anchor }: Props) {
  const [toc, setToc] = useState<TocItem[]>([]);
  const [chapter, setChapter] = useState<Chapter | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [selection, setSelection] = useState<{ text: string; paragraphs: string[]; top: number } | null>(
    null,
  );
  const [asked, setAsked] = useState<{ text: string; paragraphs: string[] } | null>(null);
  const textRef = useRef<HTMLElement>(null);

  // Выделение в тексте главы: кнопка «спросить ассистента» рядом с выделением.
  useEffect(() => {
    const onUp = () => {
      const sel = window.getSelection();
      const text = sel?.toString().trim() ?? "";
      if (!sel || !text || !textRef.current?.contains(sel.anchorNode)) {
        setSelection(null);
        return;
      }
      const ids = new Set<string>();
      const range = sel.getRangeAt(0);
      textRef.current.querySelectorAll<HTMLElement>("[data-paragraph]").forEach((el) => {
        if (range.intersectsNode(el)) ids.add(el.dataset.paragraph!);
      });
      const rect = range.getBoundingClientRect();
      setSelection({ text, paragraphs: [...ids], top: rect.bottom + window.scrollY });
    };
    document.addEventListener("mouseup", onUp);
    return () => document.removeEventListener("mouseup", onUp);
  }, []);

  // Какой источник открыть, если он не указан: запомненный или учебник по умолчанию.
  useEffect(() => {
    if (sourceId) return;
    const remembered = storage.currentSource();
    api.current(remembered).then((result) => {
      if (result.notice === "previous_unavailable") {
        setNotice("Прежний источник недоступен, открыт учебник по умолчанию.");
      }
      if (!result.source_id) {
        setProblem("В библиотеке пока нет учебника по умолчанию.");
        return;
      }
      storage.setCurrentSource(result.source_id);
      replace(`/read/${result.source_id}`);
    });
  }, [sourceId]);

  // Глава не указана: место, где читатель остановился, иначе первая глава.
  useEffect(() => {
    if (!sourceId) return;
    storage.setCurrentSource(sourceId);
    setProblem(null);
    api
      .toc(sourceId)
      .then((items) => {
        setToc(items);
        if (chapterId) return;
        const saved = storage.position(sourceId);
        const first = items.find((i) => i.chapter_id)?.chapter_id ?? items[0]?.id;
        if (saved) replace(`/read/${sourceId}/${saved.chapterId}${saved.paragraphId ? `#p-${saved.paragraphId}` : ""}`);
        else if (first) replace(`/read/${sourceId}/${first}`);
      })
      .catch((e: ApiError) => setProblem(e.kind === "source_unavailable" ? "Источник недоступен." : e.message));
  }, [sourceId, chapterId]);

  useEffect(() => {
    if (!sourceId || !chapterId) return;
    api
      .chapter(sourceId, chapterId)
      .then(setChapter)
      .catch((e: ApiError) => setProblem(e.message));
  }, [sourceId, chapterId]);

  // Прокрутка к абзацу или разделу из адреса, подсветка абзаца.
  useLayoutEffect(() => {
    if (!chapter) return;
    const target = anchor ? document.getElementById(anchor) : null;
    document.querySelectorAll(".highlight").forEach((el) => el.classList.remove("highlight"));
    if (target) {
      target.scrollIntoView({ block: "start" });
      if (anchor.startsWith("p-")) target.classList.add("highlight");
    } else {
      window.scrollTo(0, 0);
    }
  }, [chapter, anchor]);

  // Запоминание места: первый видимый абзац главы.
  useEffect(() => {
    if (!chapter || !sourceId) return;
    const save = () => {
      const paragraphs = textRef.current?.querySelectorAll<HTMLElement>("[data-paragraph]") ?? [];
      const visible = Array.from(paragraphs).find((p) => p.getBoundingClientRect().bottom > 0);
      storage.setPosition(sourceId, { chapterId: chapter.chapter_id, paragraphId: visible?.dataset.paragraph });
    };
    save();
    let pending = 0;
    const onScroll = () => {
      window.clearTimeout(pending);
      pending = window.setTimeout(save, 150);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.clearTimeout(pending);
    };
  }, [chapter, sourceId]);

  if (problem) {
    return (
      <main className="reader-problem" role="alert">
        <p>{problem}</p>
        <button className="link" onClick={() => navigate("/")}>
          Перейти в библиотеку
        </button>
      </main>
    );
  }
  if (!sourceId || !chapter) return <main className="loading">Загрузка…</main>;

  const go = (id: string) => navigate(`/read/${sourceId}/${id}`);
  return (
    <div className="reader">
      <nav className="toc" aria-label="Оглавление">
        <button className="link" onClick={() => navigate("/")}>
          ← Библиотека
        </button>
        <button
          className="link"
          onClick={() => {
            setAsked(null);
            setAssistantOpen(true);
          }}
        >
          Ассистент
        </button>
        <Toc items={toc} sourceId={sourceId} current={chapter.chapter_id} />
      </nav>
      {selection && (
        <button
          className="ask-selection primary"
          style={{ top: selection.top + 8 }}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            setAsked({ text: selection.text, paragraphs: selection.paragraphs });
            setAssistantOpen(true);
            setSelection(null);
          }}
        >
          Спросить ассистента
        </button>
      )}
      {assistantOpen && (
        <AssistantPanel
          sourceId={sourceId}
          selection={asked?.text ?? null}
          selectionParagraphs={asked?.paragraphs ?? []}
          onClose={() => setAssistantOpen(false)}
        />
      )}
      <article className="chapter" ref={textRef}>
        {notice && <p className="notice" role="status">{notice}</p>}
        <h1>{chapter.title}</h1>
        {chapter.blocks.map((block) => {
          if (block.type === "heading") {
            const Tag = block.level >= 3 ? "h3" : "h2";
            return (
              <Tag key={block.section_id} id={`s-${block.section_id}`}>
                {block.text}
              </Tag>
            );
          }
          if (block.kind === "unrendered") {
            return (
              <figure key={block.id} id={`p-${block.id}`} data-paragraph={block.id} className="unrendered">
                <span>Непереданный элемент: {block.detail}</span>
                {block.text && <figcaption>{block.text}</figcaption>}
              </figure>
            );
          }
          const Tag = block.kind === "quote" ? "blockquote" : "p";
          return (
            <Tag
              key={block.id}
              id={`p-${block.id}`}
              data-paragraph={block.id}
              lang={block.lang}
              className={`block ${block.kind}`}
            >
              {renderText(block, chapter)}
              <button
                type="button"
                className="copy-link"
                aria-label="Скопировать ссылку на абзац"
                onClick={() => copyLink(block.id, () => setCopied(block.id))}
              >
                {copied === block.id ? "Скопировано" : "¶"}
              </button>
            </Tag>
          );
        })}
        {chapter.unlinked_notes.length > 0 && (
          <section className="unlinked-notes" aria-label="Примечания без знака в тексте">
            <h2>Примечания</h2>
            <ol>
              {chapter.unlinked_notes.map((note, i) => (
                <li key={i}>{note.text}</li>
              ))}
            </ol>
          </section>
        )}
        <nav className="chapter-nav" aria-label="Главы">
          {chapter.previous && (
            <button onClick={() => go(chapter.previous!)} rel="prev">
              ← Предыдущая глава
            </button>
          )}
          {chapter.next && (
            <button onClick={() => go(chapter.next!)} rel="next">
              Следующая глава →
            </button>
          )}
        </nav>
      </article>
    </div>
  );
}
