import { useEffect, useLayoutEffect, useRef, useState, type Dispatch, type MouseEvent as ReactMouseEvent, type ReactNode, type SetStateAction } from "react";
import { api, ApiError, type Chapter, type ChapterBlock, type TocItem } from "./api";
import { navigate, type PanelItem, type PanelState } from "./App";
import { CARD_POPUP_ID, CardPopup } from "./CardPopup";
import { OPEN_CARD_EVENT } from "./FullCard";
import { FootnoteRef } from "./Footnote";
import { fieldItems, MarginCol } from "./Footnote";
import { useAssistantShortcut } from "./hooks/useAssistantShortcut";
import { useReadingAnchor } from "./hooks/useReadingAnchor";
import { useTocLocation } from "./hooks/useTocLocation";
import { Toc } from "./ReaderToc";
import { errorText, useT, type Catalog } from "./i18n";
import { computeLayout, type Layout } from "./layout";
import { storage, useStored } from "./storage";
import { familyOf, Icon } from "./ui";

type Props = {
  sourceId?: string;
  chapterId?: string;
  anchor: string;
  panel: PanelState | null;
  setPanel: Dispatch<SetStateAction<PanelState | null>>;
};

// Ширина окна: раскладка K1–K4 пересчитывается при её изменении.
function useWindowWidth(): number {
  const [width, setWidth] = useState(() => window.innerWidth);
  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return width;
}

// Раскладка по свободной ширине (2.2). Корневой кегль и ширина 1ch измеряются: на окнах шире
// 1920px кегль растёт (9.7), и все величины в rem/ch масштабируются.
function useReaderLayout(panelOpen: boolean): Layout {
  const width = useWindowWidth();
  const pinned = useStored((s) => s.sidebarPinned);
  const [metrics, setMetrics] = useState({ root: 16, ch: 11 });
  useEffect(() => {
    const measure = () => {
      const root = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
      const probe = document.createElement("span");
      probe.style.cssText = "position:absolute;visibility:hidden;width:1ch;font:var(--type-read-body);";
      document.body.appendChild(probe);
      const ch = probe.getBoundingClientRect().width || 11;
      probe.remove();
      setMetrics({ root, ch });
    };
    measure();
    // До загрузки Literata ширина 1ch берётся из запасного шрифта и отличается: после
    // загрузки шрифта раскладка пересчитывается (document.fonts.ready).
    document.fonts?.ready.then(measure).catch(() => {});
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);
  return computeLayout({ root: metrics.root, ch: metrics.ch, width, pinned, panelOpen });
}

function replace(path: string) {
  window.history.replaceState(null, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

type Mention = {
  target_id: string;
  entity_id: string;
  entity_type?: string;
  start: number;
  end: number;
};
// Открыть окно карточки у упоминания: анкор — сам элемент упоминания (положение считает окно),
// ``line`` — строка упоминания, по которой щёлкнули, ``keyboard`` — открыто Enter/Space.
type OpenMention = (
  entityId: string,
  entityType: string | undefined,
  anchor: HTMLElement,
  opts: { line: number; keyboard: boolean },
) => void;
type OpenCard = { id: string; anchor: HTMLElement; line: number; keyboard: boolean; name: string };

// Сервер знаний принимает до 500 абзацев за запрос (`targets[:500]`); главу длиннее
// запрашиваем частями параллельно (N11, раздел 13 дока).
const MENTIONS_CHUNK = 500;

// Щелчок, а не протяжка выделения: указатель сдвинулся меньше чем на 4px и выделение пусто (4.2).
let pointerDownAt: { x: number; y: number } | null = null;
function isClick(e: ReactMouseEvent): boolean {
  const start = pointerDownAt;
  pointerDownAt = null;
  if (start && Math.hypot(e.clientX - start.x, e.clientY - start.y) >= 4) return false;
  const sel = window.getSelection();
  return !sel || sel.isCollapsed || sel.toString().trim() === "";
}

// Строка упоминания, по которой щёлкнули: прямоугольник из getClientRects() под указателем.
function clickedLine(el: HTMLElement, e: ReactMouseEvent): number {
  const rects = Array.from(el.getClientRects());
  const i = rects.findIndex(
    (r) =>
      e.clientX >= r.left - 1 && e.clientX <= r.right + 1 && e.clientY >= r.top - 1 && e.clientY <= r.bottom + 1,
  );
  return i < 0 ? 0 : i;
}
// Что показать вместо главы: код ошибки сервера (переводится) и запасной текст.
type Problem = { kind: string; text?: string };
// Читатель пришёл в главу, которой больше нет, и открыто ближайшее место: куда и почему.
type Relocated = { chapterId: string; reason: "saved" | "link" };

// Предел длины выделенного фрагмента (assistant-dialog «Ограничение длины»).
const MAX_SELECTION = 4000;

// Положить элемент наверх стека панели (4.6): повторное открытие того же — не растит; глубина ≤ 20.
function samePanelItem(a: PanelItem | undefined, b: PanelItem): boolean {
  if (!a) return false;
  if (a.kind === "assistant") return b.kind === "assistant";
  return b.kind === "card" && a.entityId === b.entityId;
}

function pushPanelItem(stack: PanelItem[] | undefined, item: PanelItem): PanelItem[] {
  const items = stack ? [...stack] : [];
  const top = items[items.length - 1];
  if (samePanelItem(top, item)) items[items.length - 1] = item;
  else items.push(item);
  return items.slice(-20);
}

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
        <span
          key={`m${a}`}
          role="button"
          tabIndex={0}
          aria-haspopup="dialog"
          className="mention pg-mention"
          data-entity={mention.entity_id}
          data-family={familyOf(mention.entity_type)}
          onPointerDown={(e) => {
            pointerDownAt = { x: e.clientX, y: e.clientY };
          }}
          onClick={(e) => {
            if (!isClick(e)) return;
            open(mention.entity_id, mention.entity_type, e.currentTarget, {
              line: clickedLine(e.currentTarget, e),
              keyboard: false,
            });
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              open(mention.entity_id, mention.entity_type, e.currentTarget, { line: 0, keyboard: true });
            }
          }}
        >
          {piece}
        </span>
      ) : (
        piece
      ),
    );
  });
  return parts;
}

function blockPoints(
  block: Extract<ChapterBlock, { type: "block" }>,
  chapter: Chapter,
  t: Catalog,
  field: boolean,
  noteActive: string | null,
  setNoteActive: (id: string | null) => void,
) {
  const pageAnchor = (at: number) => `${block.id}-${at}`;
  return [
    ...block.pages.map(([at, label]) => ({
      at,
      skip: 0,
      node: (key: string) =>
        field ? (
          // В K1 номер страницы на поле: в тексте — невидимая метка, к которой он привязывается.
          <span key={key} className="page-anchor" data-page-anchor={pageAnchor(at)} aria-hidden="true" />
        ) : (
          <span key={key} className="page-mark" data-page={label} data-nontext>
            {t.reader.page(label)}
          </span>
        ),
    })),
    ...block.notes.flatMap(([at, id]) => {
      const note = chapter.footnotes[id];
      if (!note) return [];
      const skip = block.text.startsWith(note.marker, at) ? note.marker.length : 0;
      return [
        {
          at,
          skip,
          node: (key: string) => (
            <FootnoteRef
              key={key}
              note={note}
              noteId={id}
              field={field}
              active={noteActive === id}
              onActive={setNoteActive}
            />
          ),
        },
      ];
    }),
  ];
}

function unrenderedDetail(t: Catalog, block: Extract<ChapterBlock, { type: "block" }>): string | null {
  if (block.detail_code === "blank_page") return t.unrendered.blank_page(block.page ?? "");
  if (block.detail_code === "missing") return t.unrendered.missing;
  return block.detail;
}

// Поле сносок (K1): элементы встают верхом на уровне своих строк; при наезде сдвигаются вниз
// каскадом до промежутка 12px. Положения считаются одним проходом после отрисовки.
function copyLink(paragraphId: string, onDone: () => void) {
  const url = `${window.location.origin}/p/${paragraphId}`;
  navigator.clipboard?.writeText(url).then(onDone, onDone);
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
  const [card, setCard] = useState<OpenCard | null>(null);
  // Повторный щелчок по тому же упоминанию закрывает окно (4.2).
  const openCard: OpenMention = (id, _type, anchorEl, opts) =>
    setCard((c) =>
      c && c.anchor === anchorEl && !opts.keyboard
        ? null
        : { id, anchor: anchorEl, name: anchorEl.textContent ?? "", ...opts },
    );
  // Упоминание открытого окна: aria-expanded и aria-controls (10.2).
  useEffect(() => {
    if (!card) return;
    const el = card.anchor;
    el.setAttribute("aria-expanded", "true");
    el.setAttribute("aria-controls", CARD_POPUP_ID);
    return () => {
      el.setAttribute("aria-expanded", "false");
      el.removeAttribute("aria-controls");
    };
  }, [card]);
  // Переход по связи в полной карточке (FullCard): карточка ложится наверх стека панели.
  useEffect(() => {
    const onOpen = (e: Event) => {
      const detail = (e as CustomEvent<{ entityId: string; title: string }>).detail;
      if (!detail) return;
      setPanel((p) =>
        p
          ? {
              ...p,
              stack: pushPanelItem(p.stack, { kind: "card", entityId: detail.entityId, title: detail.title }),
            }
          : p,
      );
    };
    window.addEventListener(OPEN_CARD_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_CARD_EVENT, onOpen);
  }, [setPanel]);
  const textRef = useRef<HTMLElement>(null);
  const anchorRef = useRef(anchor);
  anchorRef.current = anchor;
  const [tocOpen, setTocOpen] = useState(false);
  const layout = useReaderLayout(panel !== null);
  const mentionsView = useStored((s) => s.mentions);
  const [noteActive, setNoteActive] = useState<string | null>(null);

  // Открыть ассистента в правой панели; фрагмент — если вопрос задан по выделению.
  const openAssistant = (sel?: { text: string; paragraphs: string[] } | null) =>
    setPanel((p) => ({
      stack: pushPanelItem(p?.stack, { kind: "assistant" }),
      sourceId: sourceId ?? p?.sourceId ?? "",
      selection: sel?.text ?? null,
      selectionParagraphs: sel?.paragraphs ?? [],
      stripExpanded: true,
      chapterId: chapter?.chapter_id ?? p?.chapterId,
      chapterTitle: chapter?.title ?? p?.chapterTitle,
    }));
  useAssistantShortcut(textRef, openAssistant);
  // Возврат к тексту на узком окне сворачивает развёрнутую полоску (2.3).
  const collapsePanel = () => {
    if (panel) setPanel({ ...panel, stripExpanded: false });
  };
  // Панель остаётся открытой при переходе в другую главу/книгу: диалог следует за книгой.
  useEffect(() => {
    const top = panel?.stack[panel.stack.length - 1];
    if (panel && top?.kind === "assistant" && sourceId && panel.sourceId !== sourceId) {
      setPanel({ ...panel, sourceId, chapterId: chapter?.chapter_id, chapterTitle: chapter?.title });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceId]);

  // Выделение в тексте главы: панель действий над выделением через 120 мс (раздел 7).
  useEffect(() => {
    let pending = 0;
    const onUp = () => {
      window.clearTimeout(pending);
      pending = window.setTimeout(() => {
        const sel = window.getSelection();
        const text = sel?.toString().trim() ?? "";
        const article = textRef.current;
        if (
          !sel ||
          !text ||
          !article ||
          !article.contains(sel.anchorNode) ||
          !article.contains(sel.focusNode)
        ) {
          setSelection(null);
          return;
        }
        const ids = new Set<string>();
        const range = sel.getRangeAt(0);
        article.querySelectorAll<HTMLElement>("[data-paragraph]").forEach((el) => {
          if (range.intersectsNode(el)) ids.add(el.dataset.paragraph!);
        });
        const rect = range.getBoundingClientRect();
        setSelection({ text, paragraphs: [...ids], top: rect.bottom + window.scrollY });
      }, 120);
    };
    document.addEventListener("mouseup", onUp);
    document.addEventListener("keyup", onUp);
    return () => {
      document.removeEventListener("mouseup", onUp);
      document.removeEventListener("keyup", onUp);
      window.clearTimeout(pending);
    };
  }, []);

  // Какой источник открыть, если он не указан: запомненный или учебник по умолчанию.
  useEffect(() => {
    if (sourceId) return;
    // Ответ пришёл, когда читатель уже ушёл с экрана чтения (например, закрыл книгу): адрес
    // не трогаем и книгу снова не открываем.
    let cancelled = false;
    const remembered = storage.currentSource();
    api.current(remembered).then((result) => {
      if (cancelled) return;
      if (result.notice === "previous_unavailable") setPreviousUnavailable(true);
      if (!result.source_id) {
        setProblem({ kind: "no_default" });
        return;
      }
      storage.setCurrentSource(result.source_id);
      replace(`/read/${result.source_id}`);
    });
    return () => {
      cancelled = true;
    };
  }, [sourceId]);

  // Глава не указана: место, где читатель остановился, иначе первая глава.
  useEffect(() => {
    if (!sourceId) return;
    let cancelled = false;
    storage.setCurrentSource(sourceId);
    setProblem(null);
    api
      .toc(sourceId)
      .then((items) => {
        if (cancelled) return;
        setToc(items);
        if (chapterId) return;
        const saved = storage.position(sourceId);
        const first = items.find((i) => i.chapter_id)?.chapter_id ?? items[0]?.id;
        if (saved) replace(`/read/${sourceId}/${saved.chapterId}${saved.paragraphId ? `#p-${saved.paragraphId}` : ""}`);
        else if (first) replace(`/read/${sourceId}/${first}`);
      })
      .catch((e: ApiError) => {
        if (!cancelled) setProblem({ kind: e.kind, text: e.message });
      });
    return () => {
      cancelled = true;
    };
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

  // Упоминания сущностей главы. Без онтологии глава показывается без них. Абзацев больше 500 —
  // запросы частями по 500 параллельно (N11); часть, на которую сервер не ответил, остаётся без
  // упоминаний. Ответ для прежней главы отбрасывается.
  useEffect(() => {
    setMentions({});
    setCard(null);
    if (!chapter) return;
    const controller = new AbortController();
    const targets = [...new Set(chapter.blocks.map((b) => (b.type === "block" ? b.id : b.section_id)))];
    const chunks: string[][] = [];
    for (let i = 0; i < targets.length; i += MENTIONS_CHUNK) chunks.push(targets.slice(i, i + MENTIONS_CHUNK));
    Promise.all(
      chunks.map((part) =>
        fetch(`/api/knowledge/v1/mentions?targets=${part.map(encodeURIComponent).join(",")}`, {
          signal: controller.signal,
        })
          .then((r) => (r.ok ? (r.json() as Promise<Mention[]>) : []))
          .catch(() => [] as Mention[]),
      ),
    ).then((parts) => {
      if (controller.signal.aborted) return;
      const map: Record<string, Mention[]> = {};
      parts.flat().forEach((m) => (map[m.target_id] ??= []).push(m));
      setMentions(map);
    });
    return () => controller.abort();
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

  useReadingAnchor(textRef, chapter ? `${layout.mode}:${Math.round(layout.text)}:${layout.navWidth}` : null);
  const tocSection = useTocLocation(textRef, chapter?.chapter_id ?? null, anchor);

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
  const readerStyle = {
    ["--rl-pad-left" as string]: `${layout.offsetLeft}px`,
    ["--rl-pad-right" as string]: `${layout.offsetRight}px`,
  };
  const tocNav = (
    <nav className="toc" aria-label={t.reader.toc} style={{ width: layout.toc, flexBasis: layout.toc }}>
      <button className="pg-btn pg-btn--secondary toc__assistant" onClick={() => openAssistant(null)}>
        <Icon name="chat" />
        {t.reader.assistant}
      </button>
      <p className="toc__title">{t.reader.toc}</p>
      <Toc items={toc} sourceId={sourceId} current={chapter.chapter_id} section={tocSection} />
    </nav>
  );
  const rail = (
    <div className="rail">
      <button
        type="button"
        className="pg-btn pg-btn--ghost pg-btn--icon"
        aria-expanded={tocOpen}
        aria-controls="reader-toc-layer"
        aria-label={t.reader.toc}
        title={t.reader.toc}
        onClick={() => setTocOpen((v) => !v)}
      >
        <Icon name="index" />
      </button>
      <button
        type="button"
        className="pg-btn pg-btn--ghost pg-btn--icon"
        aria-label={t.reader.assistant}
        title={t.reader.assistant}
        onClick={() => openAssistant(null)}
      >
        <Icon name="chat" />
      </button>
    </div>
  );
  return (
    <div className="reader" data-layout={layout.mode} style={readerStyle}>
      {(layout.mode === "K1" || layout.mode === "K2") && tocNav}
      {layout.mode === "K3" && rail}
      {selection && (
        <div
          className="selection-toolbar pg-popover"
          role="toolbar"
          aria-label={t.reader.selectionActions}
          style={{ top: selection.top + 8 }}
          onMouseDown={(e) => e.preventDefault()}
        >
          <button
            className="pg-btn pg-btn--primary pg-btn--sm"
            aria-disabled={selection.text.length > MAX_SELECTION || undefined}
            title={selection.text.length > MAX_SELECTION ? t.reader.selectionTooLong(MAX_SELECTION) : t.reader.assistantHint}
            onClick={() => {
              if (selection.text.length <= MAX_SELECTION) {
                openAssistant(selection);
                setSelection(null);
              }
            }}
          >
            <Icon name="chat" small />
            {t.reader.askSelection}
          </button>
          <button
            className="pg-btn pg-btn--ghost pg-btn--icon pg-btn--sm"
            aria-label={t.reader.copyLink}
            title={t.reader.copyLink}
            onClick={() => {
              const id = selection.paragraphs[0];
              if (id) copyLink(id, () => setCopied(id));
            }}
          >
            <Icon name="link" small />
          </button>
        </div>
      )}
      {card && (
        <CardPopup
          entityId={card.id}
          anchor={card.anchor}
          line={card.line}
          name={card.name}
          keyboard={card.keyboard}
          onClose={(opts) => {
            const el = card.anchor;
            setCard(null);
            if (opts?.restoreFocus && el.isConnected) el.focus({ preventScroll: true });
          }}
          onOpenFull={(id, title) => {
            setCard(null);
            setPanel((p) => ({
              stack: pushPanelItem(p?.stack, { kind: "card", entityId: id, title }),
              sourceId: sourceId ?? p?.sourceId ?? "",
              selection: p?.selection ?? null,
              selectionParagraphs: p?.selectionParagraphs ?? [],
              stripExpanded: true,
            }));
          }}
        />
      )}
      <article
        className="chapter pg-reading"
        ref={textRef}
        data-mentions={mentionsView === "hover" ? "quiet" : undefined}
        onMouseDown={collapsePanel}
        onFocusCapture={collapsePanel}
        style={{ width: layout.text, flexBasis: layout.text }}
      >
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
        {layout.mode === "K4" && (
          <button type="button" className="pg-btn pg-btn--ghost pg-btn--sm toc-open" onClick={() => setTocOpen(true)}>
            <Icon name="index" small />
            {t.reader.toc}
          </button>
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
              <figure key={block.id} id={`p-${block.id}`} data-paragraph={block.id} className="unrendered" data-nontext>
                <Icon name="info" className="unrendered__icon" />
                <div className="unrendered__body">
                  <span className="unrendered__label">{t.reader.unrendered}</span>
                  {unrenderedDetail(t, block) && (
                    <span className="unrendered__detail">{unrenderedDetail(t, block)}</span>
                  )}
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
              {renderText(block.text, blockPoints(block, chapter, t, layout.mode === "K1", noteActive, setNoteActive), mentions[block.id] ?? [], openCard)}
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
      {layout.mode === "K1" && <MarginCol items={fieldItems(chapter)} noteActive={noteActive} onActive={setNoteActive} />}
      {tocOpen && (
        <div
          id="reader-toc-layer"
          className="toc-layer pg-popover"
          role="dialog"
          aria-modal="false"
          aria-label={t.reader.toc}
        >
          <Toc items={toc} sourceId={sourceId} current={chapter.chapter_id} section={tocSection} onNavigate={() => setTocOpen(false)} />
        </div>
      )}
    </div>
  );
}
