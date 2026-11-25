import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { api, type RestrictedSourceItem, type SourceItem } from "../api";
import { navigate } from "../App";
import { openCardInPanel } from "../FullCard";
import { pick, useLang, useT } from "../i18n";
import { Icon, StatusMark, familyOf } from "../ui";
import { CatalogError, fetchCatalog, isAbort } from "./api";
import { appendPage, hasMore, nextPage, type Paging } from "./paging";
import {
  GROUP_CODES,
  SORTS,
  groupCount,
  onMap,
  readState,
  writeState,
  type CatalogItem,
  type CatalogPage,
  type GroupCode,
  type ReferenceState,
  type Sort,
} from "./types";

// Справочник (entity-catalog, «Страница справочника»): поиск, группы типов, эпоха, раздел,
// сортировка; состояние — в адресе. Ввод в поиск уходит на сервер не раньше чем через 250 мс
// после последнего нажатия (setTimeout — тесты управляют временем через page.clock); фильтры —
// сразу. Ответ на устаревший запрос отбрасывается по номеру запроса, сам запрос отменяется.
// Всё из ответа и адреса выводится текстом React, без разметки.

const DEBOUNCE_MS = 250;
const PLACEHOLDERS = 6;

type Notice = "unknownEpoch" | "unknownTextbook" | null;
type Textbook = { id: string; title: string; restricted: boolean };

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  return el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
}

function dateText(item: CatalogItem): string | null {
  return item.dates ? item.dates.original || `${item.dates.from}–${item.dates.to}` : null;
}

export function ReferencePage({ search }: { search: string }) {
  const t = useT();
  const lang = useLang();
  const [state, setState] = useState<ReferenceState>(() => readState(search));
  const [input, setInput] = useState(state.q);
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [data, setData] = useState<CatalogPage | null>(null);
  const [paging, setPaging] = useState<Paging | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [textbooks, setTextbooks] = useState<Textbook[]>([]);
  const [epochLabels, setEpochLabels] = useState<Record<string, string>>({});
  const request = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const timer = useRef<number | null>(null);
  const searchBox = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const focusIndex = useRef<number | null>(null);
  const typesRow = useRef<HTMLDivElement>(null);

  // Адрес: ввод заменяет запись истории, смена фильтра добавляет новую.
  const commit = useCallback((next: ReferenceState, push: boolean) => {
    const url = writeState(next);
    if (url !== window.location.pathname + window.location.search) {
      if (push) window.history.pushState(null, "", url);
      else window.history.replaceState(null, "", url);
    }
    setState(next);
  }, []);

  const change = (patch: Partial<ReferenceState>) => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
    setNotice(null);
    commit({ ...state, q: input, ...patch }, true);
  };

  // «Назад» и «Вперёд» восстанавливают состояние из адреса.
  useEffect(() => {
    const onPop = () => {
      if (window.location.pathname !== "/reference") return;
      const next = readState(window.location.search);
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = null;
      setState(next);
      setInput(next.q);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
      controller.current?.abort();
    },
    [],
  );

  // Учебники библиотеки для выбора раздела; закрытые для региона тоже показываются.
  useEffect(() => {
    let cancelled = false;
    api
      .sources({ kinds: ["textbook"], languages: [], query: "" })
      .then((result) => {
        if (cancelled) return;
        setTextbooks(
          result.sources.map((s: SourceItem | RestrictedSourceItem) => ({
            id: s.id,
            title: s.title,
            restricted: "restricted" in s && s.restricted === true,
          })),
        );
      })
      .catch(() => {
        // Без списка учебников остаётся «Все источники»; ошибку покажет сам справочник.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const load = useCallback(
    (page: number) => {
      controller.current?.abort();
      const abort = new AbortController();
      controller.current = abort;
      const id = ++request.current;
      setLoading(true);
      fetchCatalog(state, page, lang, abort.signal)
        .then((result) => {
          if (id !== request.current) return; // ответ на устаревший запрос
          setFailed(false);
          setLoading(false);
          setData(result);
          setEpochLabels((known) => {
            const next = { ...known };
            for (const e of result.facets.epochs) next[e.id] = e.label;
            for (const item of result.items) for (const e of item.epochs) next[e.id] = e.label;
            return next;
          });
          setPaging({ page: result.page, limit: result.limit, total: result.total, returned: result.items.length });
          if (page === 1) setItems(result.items);
          else {
            setItems((shown) => {
              const merged = appendPage(shown, result.items);
              focusIndex.current = merged.firstNew;
              return merged.items;
            });
          }
        })
        .catch((e: unknown) => {
          if (isAbort(e) || id !== request.current) return;
          setLoading(false);
          const kind = e instanceof CatalogError ? e.kind : "unavailable";
          if (kind === "unknown_epoch" && state.epoch) {
            setNotice("unknownEpoch");
            commit({ ...state, epoch: null }, false);
          } else if (kind === "unknown_textbook" && state.textbook) {
            setNotice("unknownTextbook");
            commit({ ...state, textbook: null }, false);
          } else {
            setFailed(true);
          }
        });
    },
    [state, lang, commit],
  );

  useEffect(() => {
    load(1);
  }, [load, retry]);

  // Фокус на первой из дозагруженных записей.
  useEffect(() => {
    if (focusIndex.current === null) return;
    const buttons = list.current?.querySelectorAll<HTMLButtonElement>(".reference-item__open");
    buttons?.[focusIndex.current]?.focus();
    focusIndex.current = null;
  }, [items]);

  // «/» — в строку поиска, если фокус не в поле ввода.
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return;
      e.preventDefault();
      searchBox.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const onInput = (value: string) => {
    setInput(value);
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      timer.current = null;
      commit({ ...state, q: value }, false);
    }, DEBOUNCE_MS);
  };

  const itemButtons = () =>
    Array.from(list.current?.querySelectorAll<HTMLButtonElement>(".reference-item__open") ?? []);

  const onSearchKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape" && input) {
      e.preventDefault();
      e.stopPropagation();
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = null;
      setInput("");
      commit({ ...state, q: "" }, false);
    } else if (e.key === "ArrowDown") {
      const first = itemButtons()[0];
      if (first) {
        e.preventDefault();
        first.focus();
      }
    }
  };

  const onItemKey = (e: KeyboardEvent<HTMLButtonElement>, item: CatalogItem, index: number) => {
    const buttons = itemButtons();
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const next = index + (e.key === "ArrowDown" ? 1 : -1);
      if (next < 0) searchBox.current?.focus();
      else buttons[Math.min(next, buttons.length - 1)]?.focus();
    } else if (e.key === "Enter" && e.shiftKey && onMap(item.type)) {
      e.preventDefault();
      navigate(`/graph/${encodeURIComponent(item.id)}`);
    }
  };

  const open = (item: CatalogItem) => {
    setSelected(item.id);
    openCardInPanel(item.id, item.label);
  };

  const reset = () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
    setInput("");
    setNotice(null);
    commit({ q: "", group: null, epoch: null, textbook: null, sort: null }, true);
  };

  const filtered = Boolean(state.q.trim() || state.group || state.epoch || state.textbook);
  const facets = data?.facets.types ?? {};
  const counted = data !== null && !loading;
  const allCount = Object.values(facets).reduce((a, b) => a + b, 0);
  const emptyOntology = counted && !failed && data.total === 0 && !filtered && !data.textbook_closed;
  const showCounts = data !== null && !(data.total === 0 && !filtered);
  const sort: Sort = data?.sort ?? state.sort ?? (state.q.trim() ? "relevance" : "label");
  const epochOptions = data?.facets.epochs ?? [];
  const typeName = (code: string) => pick(t.family, code) ?? code;
  const count = (n: number) => (counted ? String(n) : "…");

  const scrollTypes = (direction: 1 | -1) => {
    const row = typesRow.current;
    if (row) row.scrollBy({ left: direction * row.clientWidth * 0.6 });
  };

  return (
    <main className="page reference">
      <header className="page-header reference__header">
        <div>
          <h1 className="page-title">{t.reference.title}</h1>
          <p className="page-lead reference__lead">{t.reference.lead}</p>
        </div>
        <p className="reference__found" aria-live="polite">
          {data !== null && !loading ? t.reference.found(data.total) : ""}
        </p>
      </header>

      <div className="reference__controls">
        <div className="pg-field reference__search">
          <label className="pg-field__label visually-hidden" htmlFor="reference-search">
            {t.reference.searchLabel}
          </label>
          <div className="pg-field__control">
            <Icon name="search" small />
            <input
              id="reference-search"
              ref={searchBox}
              className="pg-input"
              type="search"
              autoComplete="off"
              placeholder={t.reference.search}
              value={input}
              onChange={(e) => onInput(e.target.value)}
              onKeyDown={onSearchKey}
            />
            <kbd className="pg-field__kbd" aria-hidden="true">
              /
            </kbd>
          </div>
        </div>
        <div className="reference__selects">
          <label className="reference__select">
            <span className="pg-field__label">{t.reference.epoch}</span>
            <select
              className="pg-input"
              value={state.epoch ?? ""}
              onChange={(e) => change({ epoch: e.target.value || null })}
            >
              <option value="">{t.reference.allEpochs}</option>
              {state.epoch && !epochOptions.some((e) => e.id === state.epoch) && (
                <option value={state.epoch}>{epochLabels[state.epoch] ?? state.epoch}</option>
              )}
              {epochOptions.map((e) => (
                <option key={e.id} value={e.id}>
                  {`${e.label} (${e.count})`}
                </option>
              ))}
            </select>
          </label>
          <label className="reference__select">
            <span className="pg-field__label">{t.reference.scope}</span>
            <select
              className="pg-input"
              value={state.textbook ?? ""}
              onChange={(e) => change({ textbook: e.target.value || null })}
            >
              <option value="">{t.reference.allSources}</option>
              {state.textbook && !textbooks.some((b) => b.id === state.textbook) && (
                <option value={state.textbook}>{state.textbook}</option>
              )}
              {textbooks.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.restricted ? `${b.title} — ${t.reference.restricted}` : b.title}
                </option>
              ))}
            </select>
          </label>
          <label className="reference__select">
            <span className="pg-field__label">{t.reference.sortLabel}</span>
            <select
              className="pg-input"
              value={sort}
              onChange={(e) => change({ sort: e.target.value as Sort })}
            >
              {SORTS.filter((s) => s !== "relevance" || state.q.trim()).map((s) => (
                <option key={s} value={s}>
                  {t.reference.sort[s]}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      <div className="reference__types">
        <button
          type="button"
          className="pg-btn pg-btn--ghost pg-btn--icon pg-btn--sm reference__scroll"
          aria-label={t.reference.scrollTypes.prev}
          onClick={() => scrollTypes(-1)}
        >
          <span aria-hidden="true">‹</span>
        </button>
        <div className="reference__types-row" role="group" aria-label={t.reference.typeLabel} ref={typesRow}>
          <button
            type="button"
            className="reference__type"
            aria-pressed={state.group === null}
            onClick={() => change({ group: null })}
          >
            {t.reference.groups.all}
            {showCounts && <span className="reference__count num">{count(allCount)}</span>}
          </button>
          {GROUP_CODES.map((g: GroupCode) => {
            const n = groupCount(facets, g);
            return (
              <button
                key={g}
                type="button"
                className="reference__type"
                data-empty={counted && n === 0 ? "true" : undefined}
                aria-pressed={state.group === g}
                onClick={() => change({ group: g })}
              >
                {t.reference.groups[g]}
                {showCounts && <span className="reference__count num">{count(n)}</span>}
              </button>
            );
          })}
        </div>
        <button
          type="button"
          className="pg-btn pg-btn--ghost pg-btn--icon pg-btn--sm reference__scroll"
          aria-label={t.reference.scrollTypes.next}
          onClick={() => scrollTypes(1)}
        >
          <span aria-hidden="true">›</span>
        </button>
      </div>

      {notice && (
        <div className="pg-notice reference__notice" role="status">
          <Icon name="info" />
          <div>{t.reference[notice]}</div>
        </div>
      )}
      {failed && (
        <div className="pg-notice pg-notice--warning reference__notice" role="alert">
          <Icon name="warning" />
          <div>{t.reference.unavailable}</div>
          <button type="button" className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => setRetry((n) => n + 1)}>
            {t.reference.retry}
          </button>
        </div>
      )}
      {data?.textbook_closed && !loading && (
        <div className="pg-notice reference__notice" role="status">
          <Icon name="info" />
          <div>{t.reference.closed}</div>
          <button type="button" className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => change({ textbook: null })}>
            {t.reference.allSources}
          </button>
        </div>
      )}

      {emptyOntology ? (
        <div className="reference__empty">
          <Icon name="index" />
          <p>{t.reference.empty}</p>
          <a
            className="pg-btn pg-btn--secondary"
            href="/"
            onClick={(e) => {
              e.preventDefault();
              navigate("/");
            }}
          >
            {t.reference.toLibrary}
          </a>
        </div>
      ) : (
        counted &&
        !failed &&
        !data.textbook_closed &&
        data.total === 0 && (
          <div className="reference__empty">
            <p>{state.group && state.q.trim() === "" ? t.reference.nothingInGroup : t.reference.nothing(state.q.trim())}</p>
            <button type="button" className="pg-btn pg-btn--secondary" onClick={reset}>
              {t.reference.reset}
            </button>
          </div>
        )
      )}

      <ul className="reference__list" aria-label={t.reference.results} aria-busy={loading} ref={list}>
        {data === null && loading
          ? Array.from({ length: PLACEHOLDERS }, (_, i) => (
              <li key={i} className="reference-item reference-item--placeholder" aria-hidden="true">
                <span className="reference-item__bar" />
                <span className="reference-item__bar reference-item__bar--short" />
              </li>
            ))
          : items.map((item, index) => {
              const dates = dateText(item);
              const type = typeName(item.type);
              return (
                <li key={item.id} className="reference-item" data-selected={selected === item.id ? "true" : undefined}>
                  <button
                    type="button"
                    className="reference-item__open"
                    data-family={familyOf(item.type)}
                    tabIndex={index === 0 ? 0 : -1}
                    aria-label={t.reference.itemName(item.label, type, dates)}
                    aria-keyshortcuts={onMap(item.type) ? "Shift+Enter" : undefined}
                    onClick={() => open(item)}
                    onKeyDown={(e) => onItemKey(e, item, index)}
                    onFocus={(e) => {
                      for (const b of itemButtons()) b.tabIndex = b === e.currentTarget ? 0 : -1;
                    }}
                  >
                    <span className="reference-item__head">
                      <span className="reference-item__mark" aria-hidden="true" />
                      <span className="reference-item__name">{item.label}</span>
                      {item.matched_name && (
                        <span className="reference-item__also">{t.reference.alsoKnown(item.matched_name)}</span>
                      )}
                    </span>
                    <span className="reference-item__meta">
                      {[type, dates ?? t.reference.undated, ...item.epochs.map((e) => e.label)].join(" · ")}
                    </span>
                    {item.summary && (
                      <span className="reference-item__summary">
                        <span className="reference-item__text">{item.summary.text}</span>
                        {item.summary.generated && (
                          <span className="reference-item__generated" data-generated="true">
                            <StatusMark status="generated" />
                          </span>
                        )}
                      </span>
                    )}
                  </button>
                  {item.epochs.length > 0 && (
                    <span className="reference-item__epochs">
                      {item.epochs.map((e) => {
                        const to = `/epochs/${encodeURIComponent(e.id)}`;
                        return (
                          <a
                            key={e.id}
                            className="reference-item__epoch"
                            href={to}
                            aria-label={t.epochs.inEpoch(e.label)}
                            onClick={(ev) => {
                              if (ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
                              ev.preventDefault();
                              navigate(to);
                            }}
                          >
                            {e.label}
                          </a>
                        );
                      })}
                    </span>
                  )}
                  {onMap(item.type) && (
                    <button
                      type="button"
                      className="pg-btn pg-btn--ghost pg-btn--sm reference-item__map"
                      aria-label={t.reference.onMapOf(item.label)}
                      title={t.reference.onMapHint}
                      tabIndex={-1}
                      onClick={() => navigate(`/graph/${encodeURIComponent(item.id)}`)}
                    >
                      <span className="reference-item__map-text">{t.reference.onMap}</span>
                      <span aria-hidden="true">→</span>
                    </button>
                  )}
                </li>
              );
            })}
      </ul>

      {data !== null && items.length > 0 && (
        <div className="reference__more">
          {paging !== null && hasMore(paging) ? (
            <button
              type="button"
              className="pg-btn pg-btn--secondary"
              disabled={loading}
              onClick={() => load(nextPage(paging))}
            >
              {t.reference.more(items.length, data.total)}
            </button>
          ) : (
            data.total > data.limit && <p className="reference__all">{t.reference.allShown(data.total)}</p>
          )}
        </div>
      )}
    </main>
  );
}
