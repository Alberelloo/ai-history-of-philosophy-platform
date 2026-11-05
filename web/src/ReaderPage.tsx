import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, type Chapter, type ChapterBlock, type TocItem } from "./api";
import { navigate } from "./App";
import { AssistantPanel } from "./AssistantPanel";
import { CardPopup } from "./CardPopup";
import { FootnoteRef } from "./Footnote";
import { storage } from "./storage";

type Props = { sourceId?: string; chapterId?: string; anchor: string };

function replace(path: string) {
  window.history.replaceState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

// Текст блока с отметками страниц и знаками сносок на своих местах.
type Mention = { target_id: string; entity_id: string; start: number; end: number };
type OpenMention = (entityId: string, x: number, y: number) => void;

// Текст с отметками страниц, знаками сносок и упоминаниями сущностей на своих местах.
function renderText(
  text: string,
  points: { at: number; skip: number; node: (key: string) => ReactNode }[],
  mentions: Mention[],
  open: OpenMention,
): ReactNode[] {
  const cuts = new Set<number>([0, text.length]);
  points.forEach((p) => {
    cuts.add(p.at);
    cuts.add(Math.min(text.length, p.at + p.skip));
  });
  mentions.forEach((m) => {
    cuts.add(m.start);
    cuts.add(m.end);
  });
  const sorted = [...cuts].filter((c) => c <= text.length).sort((a, b) => a - b);
  const skipped = points.flatMap((p) => (p.skip ? [[p.at, p.at + p.skip]] : []));
  const parts: ReactNode[] = [];
  sorted.forEach((a, i) => {
    points.filter((p) => p.at === a).forEach((p, j) => parts.push(p.node(`p${a}-${j}`)));
    const b = sorted[i + 1];
    if (b === undefined || b <= a) return;
    if (skipped.some(([x, y]) => a >= x && b <= y)) return; // знак сноски заменён кнопкой
    const piece = text.slice(a, b);
    const mention = mentions.find((m) => m.start <= a && b <= m.end);
    parts.push(
      mention ? (
        <button
          key={`m${a}`}
          type="button"
          className="mention"
          data-entity={mention.entity_id}
          onClick={(e) => open(mention.entity_id, e.pageX, e.pageY + 12)}
        >
          {piece}
        </button>
      ) : (
        piece
      ),
    );
  });
  return parts;
}

function blockPoints(block: Extract<ChapterBlock, { type: "block" }>, chapter: Chapter) {
  return [
    ...block.pages.map(([at, label]) => ({
      at,
      skip: 0,
      node: (key: string) => (
        <span key={key} className="page-mark" data-page={label}>
          с. {label}
        </span>
      ),
    })),
    ...block.notes.flatMap(([at, id]) => {
      const note = chapter.footnotes[id];
      if (!note) return [];
      const skip = block.text.startsWith(note.marker, at) ? note.marker.length : 0;
      return [{ at, skip, node: (key: string) => <FootnoteRef key={key} note={note} /> }];
    }),
  ];
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
  const [mentions, setMentions] = useState<Record<string, Mention[]>>({});
  const [card, setCard] = useState<{ id: string; x: number; y: number } | null>(null);
  const openCard: OpenMention = (id, x, y) => setCard({ id, x, y });
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

  // Упоминания сущностей главы. Без онтологии глава показывается без них.
  useEffect(() => {
    setMentions({});
    if (!chapter) return;
    const targets = chapter.blocks.map((b) => (b.type === "block" ? b.id : b.section_id));
    fetch(`/api/knowledge/v1/mentions?targets=${targets.join(",")}`)
      .then((r) => (r.ok ? r.json() : []))
      .then((items: Mention[]) => {
        const map: Record<string, Mention[]> = {};
        items.forEach((m) => (map[m.target_id] ??= []).push(m));
        setMentions(map);
      })
      .catch(() => setMentions({}));
  }, [chapter]);

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
        <button className="link" onClick={() => navigate("/settings")}>
          Настройки
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
      {card && <CardPopup entityId={card.id} x={card.x} y={card.y} onClose={() => setCard(null)} />}
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
                {renderText(block.text, [], mentions[block.section_id] ?? [], openCard)}
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
              {renderText(block.text, blockPoints(block, chapter), mentions[block.id] ?? [], openCard)}
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
