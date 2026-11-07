import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, type Chapter, type ChapterBlock, type TocItem } from "./api";
import { navigate, type PanelState } from "./App";
import { CardPopup } from "./CardPopup";
import { FootnoteRef } from "./Footnote";
import { errorText, useT, type Catalog } from "./i18n";
import { storage } from "./storage";
import { Icon } from "./ui";

type Props = {
  sourceId?: string;
  chapterId?: string;
  anchor: string;
  panel: PanelState | null;
  setPanel: (panel: PanelState | null) => void;
};

function replace(path: string) {
  window.history.replaceState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

type Mention = { target_id: string; entity_id: string; start: number; end: number };
type OpenMention = (entityId: string, x: number, y: number) => void;
// Что показать вместо главы: код ошибки сервера (переводится) и запасной текст.
type Problem = { kind: string; text?: string };
// Читатель пришёл в главу, которой больше нет, и открыто ближайшее место: куда и почему.
type Relocated = { chapterId: string; reason: "saved" | "link" };

// Ближайшее место вместо пропавшей главы: глава сохранённого абзаца, иначе первая глава.
async function nearestPlace(
  sourceId: string,
  paragraphId: string | undefined,
  first: unknown,
): Promise<{ chapterId: string; path: string } | null> {
  if (paragraphId) {
    try {
      const found = await api.paragraph(paragraphId);
      if (found.status === "found" && found.source_id === sourceId) {
        return { chapterId: found.chapter_id, path: `/read/${sourceId}/${found.chapter_id}#p-${found.paragraph_id}` };
      }
      if (found.status === "removed" && found.source_id === sourceId && found.chapter_id) {
        return { chapterId: found.chapter_id, path: `/read/${sourceId}/${found.chapter_id}` };
      }
    } catch {
      // абзац не нашёлся — остаётся первая глава
    }
  }
  return typeof first === "string" ? { chapterId: first, path: `/read/${sourceId}/${first}` } : null;
}

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
          className="mention pg-mention"
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

function blockPoints(block: Extract<ChapterBlock, { type: "block" }>, chapter: Chapter, t: Catalog) {
  return [
    ...block.pages.map(([at, label]) => ({
      at,
      skip: 0,
      node: (key: string) => (
        <span key={key} className="page-mark" data-page={label}>
          {t.reader.page(label)}
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

export function ReaderPage({ sourceId, chapterId, anchor, panel, setPanel }: Props) {
  const t = useT();
  const [toc, setToc] = useState<TocItem[]>([]);
  const [chapter, setChapter] = useState<Chapter | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [previousUnavailable, setPreviousUnavailable] = useState(false);
  const [relocated, setRelocated] = useState<Relocated | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [selection, setSelection] = useState<{ text: string; paragraphs: string[]; top: number } | null>(
    null,
  );
  const [mentions, setMentions] = useState<Record<string, Mention[]>>({});
  const [card, setCard] = useState<{ id: string; x: number; y: number } | null>(null);
  const openCard: OpenMention = (id, x, y) => setCard({ id, x, y });
  const textRef = useRef<HTMLElement>(null);
  const anchorRef = useRef(anchor);
  anchorRef.current = anchor;

  // Открыть ассистента в правой панели; фрагмент — если вопрос задан по выделению.
  const openAssistant = (sel?: { text: string; paragraphs: string[] } | null) =>
    setPanel({
      mode: "assistant",
      sourceId: sourceId ?? "",
      selection: sel?.text ?? null,
      selectionParagraphs: sel?.paragraphs ?? [],
      stripExpanded: true,
    });
  // Возврат к тексту на узком окне сворачивает развёрнутую полоску (2.3).
  const collapsePanel = () => {
    if (panel) setPanel({ ...panel, stripExpanded: false });
  };
  // Панель остаётся открытой при переходе в другую главу/книгу: диалог следует за книгой.
  useEffect(() => {
    if (panel?.mode === "assistant" && sourceId && panel.sourceId !== sourceId) {
      setPanel({ ...panel, sourceId });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceId]);

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
      if (result.notice === "previous_unavailable") setPreviousUnavailable(true);
      if (!result.source_id) {
        setProblem({ kind: "no_default" });
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
      .catch((e: ApiError) => setProblem({ kind: e.kind, text: e.message }));
  }, [sourceId, chapterId]);

  // Глава по адресу. Раздел внутри главы — его глава с прокруткой к разделу. Главы больше нет
  // (книгу обработали заново) — читатель остаётся в книге: ближайшее место и уведомление.
  useEffect(() => {
    if (!sourceId || !chapterId) return;
    let cancelled = false;
    setRelocated((r) => (r && r.chapterId === chapterId ? r : null));
    api
      .chapter(sourceId, chapterId)
      .then((result) => {
        if (cancelled) return;
        if (result.anchor && result.chapter_id !== chapterId) {
          replace(`/read/${sourceId}/${result.chapter_id}#s-${result.anchor}`);
          return;
        }
        setChapter(result);
      })
      .catch(async (e: ApiError) => {
        if (cancelled) return;
        if (e.kind !== "chapter_not_found") {
          setProblem({ kind: e.kind, text: e.message });
          return;
        }
        const saved = storage.position(sourceId);
        const reason = saved?.chapterId === chapterId ? "saved" : "link";
        const linked = anchorRef.current.startsWith("p-") ? anchorRef.current.slice(2) : undefined;
        const paragraphId = linked ?? (reason === "saved" ? saved?.paragraphId : undefined);
        const place = await nearestPlace(sourceId, paragraphId, e.details.first_chapter_id);
        if (cancelled) return;
        if (!place) {
          setProblem({ kind: e.kind, text: e.message });
          return;
        }
        setRelocated({ chapterId: place.chapterId, reason });
        replace(place.path);
      });
    return () => {
      cancelled = true;
    };
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
      // Видимым считается то, что ниже отступа прокрутки, — туда же абзац встаёт при возврате
      // к месту.
      const top = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
      const visible = Array.from(paragraphs).find((p) => p.getBoundingClientRect().bottom > top);
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
      <main className="page page--narrow reader-problem">
        <div className="pg-notice pg-notice--danger" role="alert">
          <Icon name="warning" />
          <div>{problem.kind === "no_default" ? t.reader.noDefault : errorText(t, problem.kind, problem.text)}</div>
        </div>
        <div className="actions">
          <button className="pg-btn pg-btn--secondary" onClick={() => navigate("/")}>
            {t.app.goLibrary}
          </button>
        </div>
      </main>
    );
  }
  if (!sourceId || !chapter) return <main className="page loading">{t.app.loading}</main>;

  const go = (id: string) => navigate(`/read/${sourceId}/${id}`);
  return (
    <div className="reader">
      <nav className="toc" aria-label={t.reader.toc}>
        <button
          className="pg-btn pg-btn--secondary toc__assistant"
          onClick={() => openAssistant(null)}
        >
          <Icon name="chat" />
          {t.reader.assistant}
        </button>
        <p className="toc__title">{t.reader.toc}</p>
        <Toc items={toc} sourceId={sourceId} current={chapter.chapter_id} />
      </nav>
      {selection && (
        <button
          className="ask-selection pg-btn pg-btn--primary pg-btn--sm"
          style={{ top: selection.top + 8 }}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            openAssistant(selection);
            setSelection(null);
          }}
        >
          <Icon name="chat" small />
          {t.reader.askSelection}
        </button>
      )}
      {card && <CardPopup entityId={card.id} x={card.x} y={card.y} onClose={() => setCard(null)} />}
      <article className="chapter pg-reading" ref={textRef} onMouseDown={collapsePanel} onFocusCapture={collapsePanel}>
        {relocated && relocated.chapterId === chapter.chapter_id && (
          <div className="pg-notice notice relocated" role="status">
            <Icon name="info" />
            <div>{relocated.reason === "saved" ? t.reader.relocatedSaved : t.reader.relocatedLink}</div>
          </div>
        )}
        {previousUnavailable && (
          <div className="pg-notice notice" role="status">
            <Icon name="info" />
            <div>{t.reader.previousUnavailable}</div>
          </div>
        )}
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
                <Icon name="info" className="unrendered__icon" />
                <div className="unrendered__body">
                  <span className="unrendered__label">{t.reader.unrendered}</span>
                  {block.detail && <span className="unrendered__detail">{block.detail}</span>}
                  {block.text && <figcaption>{block.text}</figcaption>}
                </div>
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
              {renderText(block.text, blockPoints(block, chapter, t), mentions[block.id] ?? [], openCard)}
              <button
                type="button"
                className="copy-link pg-btn pg-btn--ghost pg-btn--icon pg-btn--sm"
                aria-label={t.reader.copyLink}
                title={copied === block.id ? t.reader.copied : t.reader.copyLink}
                onClick={() => copyLink(block.id, () => setCopied(block.id))}
              >
                <Icon name={copied === block.id ? "check" : "link"} small />
              </button>
            </Tag>
          );
        })}
        {chapter.unlinked_notes.length > 0 && (
          <section className="unlinked-notes" aria-label={t.reader.unlinkedNotes}>
            <h2>{t.reader.notes}</h2>
            <ol>
              {chapter.unlinked_notes.map((note, i) => (
                <li key={i}>{note.text}</li>
              ))}
            </ol>
          </section>
        )}
        <nav className="chapter-nav" aria-label={t.reader.chapters}>
          {chapter.previous && (
            <button className="pg-btn pg-btn--secondary" onClick={() => go(chapter.previous!)} rel="prev">
              <Icon name="arrowLeft" />
              {t.reader.previous}
            </button>
          )}
          {chapter.next && (
            <button className="pg-btn pg-btn--secondary chapter-nav__next" onClick={() => go(chapter.next!)} rel="next">
              {t.reader.next}
              <Icon name="arrowRight" />
            </button>
          )}
        </nav>
      </article>
    </div>
  );
}
