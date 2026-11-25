import { createContext, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode, type RefObject } from "react";
import { pick, useT, type Catalog } from "../i18n";
import { ViaNotice } from "./ViaNotice";
import { Icon, type IconName } from "../ui";
import { LinkDetails, type GEdge } from "./LinkDetails";
import { GeoList, GeoPlaceSelected, GeoWhere, GlobeLegend, type GeoPanel } from "./geo/GeoList";
import {
  counts as countsOf,
  epochWindow,
  find,
  index,
  isFiltered,
  search,
  SEARCH_GROUPS,
  type ColorRole,
  type Related,
  type SearchHit,
  type Visible,
} from "./model";
import { emptyFilter, type Filter, type MapData, type MapState } from "./types";

// Правая панель карты (макет v6): поиск с подсказками по типам, «Выбрано» с расшифровкой
// цветов и действиями, фильтры столбиком (<details> со счётчиками), условные знаки.
// Свёрнутая панель — узкий рельс со значками; любой значок разворачивает её к своему разделу.
//
// Без прокрутки (правка владельца 2026-11-18): панель всегда помещается в высоту карты.
// Разделы, которым не хватает места, складываются до заголовка — первыми условные знаки,
// затем фильтры, последним «Выбрано»; раздел, раскрытый читателем, не складывается. Когда
// место освобождается, сложенные подгонкой разделы раскрываются снова. Значения фильтра
// открываются всплывающим окном слева от панели, поверх карты, и высоту панели не меняют.

export type BuildState = {
  running: boolean;
  added: number; // связей, добавленных на карту из потока
  notice: string | null; // уведомление потока (код extension или текст сервера)
  extension: string | null;
  problem: { kind: string; message?: string; suggestions: { code: string; title: string }[] } | null;
};

export const idleBuild = (): BuildState => ({ running: false, added: 0, notice: null, extension: null, problem: null });

export type LinkView = { id: string; edge: GEdge | null; status: "loading" | "ready" | "missing" };

type Props = {
  data: MapData;
  vis: Visible;
  rel: Related | null;
  state: MapState;
  collapsed: boolean;
  onCollapse: (collapsed: boolean) => void;
  onState: (patch: Partial<MapState>) => void;
  // Вид подобран ассистентом (?via=assistant): пометка в панели и «Сбросить вид».
  onResetView?: () => void;
  onSelect: (id: string | null, resetFilter?: boolean) => void;
  link: LinkView | null;
  onCloseLink: () => void;
  build: BuildState;
  onBuild: (recipe?: string) => void;
  generation: boolean;
  onEnableGeneration: () => void;
  onOpenCard: (id: string, title: string) => void;
  // Вид «Глобус» (geo-timeline): список мест в году, выбор места, легенда глобуса.
  geo?: GeoPanel;
};

type Section = "search" | "selected" | "filters" | "legend";

// Названия значений из реестра (ontology.*.json → values) — со строчной; в списке — с прописной.
const cap = (s: string) => (s ? s[0].toLocaleUpperCase() + s.slice(1) : s);

const SECTION_ICON: Record<Section, IconName> = { search: "search", selected: "check", filters: "filter", legend: "legend" };

type Fold = Exclude<Section, "search">;
type Step = Fold | "tight";
// Что уступает место первым: плотный режим (заголовок панели в строке поиска, меньше
// отступы), затем разделы. Раскрываются обратно в обратном порядке.
const FOLD_ORDER: Step[] = ["tight", "legend", "filters", "selected"];
const REOPEN_MARGIN = 16; // px свободного места сверх освобождённого, чтобы раскрыть обратно

type FoldApi = { closed: (k: Fold) => boolean; toggle: (k: Fold) => void };
const FoldContext = createContext<FoldApi>({ closed: () => false, toggle: () => {} });

// Заголовок складываемого раздела: кнопка со стрелкой, раскрывает и складывает раздел.
function FoldHead({ k, children, extra }: { k: Fold; children: ReactNode; extra?: ReactNode }) {
  const fold = useContext(FoldContext);
  const closed = fold.closed(k);
  return (
    <div className="map-panel__row">
      <h2 className="map-panel__h">
        <button type="button" className="pg-btn map-fold" aria-expanded={!closed} aria-controls={`map-sec-${k}`} onClick={() => fold.toggle(k)}>
          {children}
          <Icon name={closed ? "chevronRight" : "chevronDown"} small />
        </button>
      </h2>
      {extra}
    </div>
  );
}

// Подгонка разделов под высоту панели: складывает по FOLD_ORDER, пока содержимое выше
// панели, и раскрывает сложенные подгонкой, когда освобождённого места снова хватает.
function useFit(panel: RefObject<HTMLElement>, body: RefObject<HTMLElement>, active: boolean, focusKey: string) {
  const [closed, setClosed] = useState<ReadonlySet<Step>>(new Set());
  const [pin, setPin] = useState<Fold | null>(null);
  const [, setTick] = useState(0);
  const freed = useRef(new Map<Step, number>()); // сложенные подгонкой: сколько места освободили
  const pending = useRef<{ k: Step; before: number } | null>(null);
  const byUser = useRef(new Set<Fold>()); // сложенные читателем — подгонка их не раскрывает

  useEffect(() => {
    if (!active) return;
    const ro = new ResizeObserver(() => setTick((n) => n + 1));
    if (panel.current) ro.observe(panel.current);
    if (body.current) ro.observe(body.current);
    return () => ro.disconnect();
  }, [active, panel, body]);

  // Новый выбор или связь — «Выбрано» раскрывается: читатель хочет его видеть.
  useEffect(() => {
    if (!focusKey) return;
    byUser.current.delete("selected");
    freed.current.delete("selected");
    setPin("selected");
    setClosed((c) => (c.has("selected") ? new Set([...c].filter((x) => x !== "selected")) : c));
  }, [focusKey]);

  useLayoutEffect(() => {
    const p = panel.current;
    const b = body.current;
    if (!active || !p || !b) return;
    // Считаем по экранным прямоугольникам: у тела панели точка отсчёта offsetTop — сама панель.
    const style = getComputedStyle(p);
    const top = p.getBoundingClientRect().top + p.clientTop + parseFloat(style.paddingTop);
    const avail = p.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
    const need = b.getBoundingClientRect().bottom - top;
    if (pending.current) {
      freed.current.set(pending.current.k, Math.max(1, pending.current.before - need));
      pending.current = null;
    }
    if (need > avail + 0.5) {
      // Последнее средство — сложить и раскрытый читателем раздел: прокрутки не бывает.
      const victim = FOLD_ORDER.find((k) => !closed.has(k) && k !== pin) ?? (pin && !closed.has(pin) ? pin : undefined);
      if (!victim) return;
      pending.current = { k: victim, before: need };
      setClosed(new Set([...closed, victim]));
      return;
    }
    // Раскрываем обратно с запасом (без качелей у границы) и не под открытым списком поиска:
    // иначе поле и подсказки сдвигаются под рукой читателя.
    if (b.querySelector(".map-search__list")) return;
    const back = [...FOLD_ORDER].reverse().find((k) => closed.has(k) && freed.current.has(k) && !(k !== "tight" && byUser.current.has(k)));
    if (back && avail - need >= freed.current.get(back)! + REOPEN_MARGIN) {
      freed.current.delete(back);
      setClosed(new Set([...closed].filter((x) => x !== back)));
    }
  });

  const api: FoldApi = {
    closed: (k) => closed.has(k),
    toggle: (k) => {
      freed.current.delete(k);
      if (closed.has(k)) {
        byUser.current.delete(k);
        setPin(k);
        setClosed(new Set([...closed].filter((x) => x !== k)));
      } else {
        byUser.current.add(k);
        if (pin === k) setPin(null);
        setClosed(new Set([...closed, k]));
      }
    },
  };
  return { api, tight: closed.has("tight") };
}

export function MapPanel(props: Props) {
  const { collapsed, onCollapse } = props;
  const t = useT();
  const body = useRef<HTMLDivElement>(null);
  const searchInput = useRef<HTMLInputElement>(null);
  const [focus, setFocus] = useState<Section | null>(null);
  const aside = useRef<HTMLElement>(null);
  const focusKey = props.link?.id ?? props.rel?.obj.id ?? props.state.sel ?? ""; // и место глобуса: оно не сущность графа
  const { api: fold, tight } = useFit(aside, body, !collapsed, focusKey);

  // После разворачивания — к разделу, с которого его открыли.
  useEffect(() => {
    if (collapsed || !focus) return;
    if (focus === "search") searchInput.current?.focus();
    else body.current?.querySelector<HTMLElement>(`[data-section="${focus}"]`)?.scrollIntoView({ block: "nearest" });
    setFocus(null);
  }, [collapsed, focus]);

  // «/» — к поиску (вне полей ввода).
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
      const el = e.target as HTMLElement;
      if (el.closest("input, textarea, select, [contenteditable='true']")) return;
      e.preventDefault();
      if (collapsed) {
        onCollapse(false);
        setFocus("search");
      } else searchInput.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [collapsed, onCollapse]);

  return (
    <FoldContext.Provider value={fold}>
    <aside ref={aside} className={["map-panel", collapsed ? "is-collapsed" : "", !collapsed && tight ? "is-tight" : ""].join(" ").trim()} aria-label={t.map.panel}>
      <div className="map-panel__bar">
        {!collapsed && <span className="map-panel__title">{t.map.panelTitle}</span>}
        <button
          type="button"
          className="pg-btn pg-btn--ghost pg-btn--sm map-panel__toggle"
          aria-expanded={!collapsed}
          aria-controls="map-panel-body"
          title={collapsed ? t.map.expandPanel : t.map.collapsePanel}
          aria-label={collapsed ? t.map.expandPanel : t.map.collapsePanel}
          onClick={() => onCollapse(!collapsed)}
        >
          <Icon name={collapsed ? "arrowLeft" : "chevronRight"} small />
        </button>
      </div>
      {collapsed ? (
        <div className="map-panel__rail">
          {(["search", "selected", "filters", "legend"] as const).map((k) => (
            <button
              key={k}
              type="button"
              className="pg-btn pg-btn--ghost pg-btn--sm map-panel__rail-btn"
              title={t.map.sections[k]}
              aria-label={t.map.sections[k]}
              data-rail={k}
              onClick={() => {
                onCollapse(false);
                setFocus(k);
              }}
            >
              <Icon name={SECTION_ICON[k]} small />
            </button>
          ))}
        </div>
      ) : (
        <div className="map-panel__body" id="map-panel-body" ref={body}>
          <SearchBox {...props} inputRef={searchInput} />
          {props.onResetView && <ViaNotice data={props.data} state={props.state} onReset={props.onResetView} />}
          <section className="map-panel__sec map-selected" data-section="selected" id="map-sec-selected" aria-live="polite">
            {fold.closed("selected") ? (
              <FoldHead k="selected">
                {t.map.sections.selected}
                {props.rel ? ` · ${props.rel.obj.label}` : ""}
              </FoldHead>
            ) : (
              <Selected {...props} />
            )}
          </section>
          {props.geo && (
            <GeoList data={props.data} geo={props.geo} sel={props.state.sel} onSelect={(id) => props.onSelect(id)} onOpenCard={props.onOpenCard} />
          )}
          <section className="map-panel__sec" data-section="filters" id="map-sec-filters" aria-label={t.map.sections.filters}>
            <Filters {...props} />
          </section>
          <section className="map-panel__sec" data-section="legend" id="map-sec-legend" aria-label={t.map.sections.legend}>
            <FoldHead k="legend">{t.map.sections.legend}</FoldHead>
            {!fold.closed("legend") && (props.geo ? <GlobeLegend /> : <Legend />)}
          </section>
        </div>
      )}
    </aside>
    </FoldContext.Provider>
  );
}

/* ---------- поиск ---------- */

function Mark({ text, match }: { text: string; match: [number, number] }) {
  if (match[1] <= match[0]) return <>{text}</>;
  return (
    <>
      {text.slice(0, match[0])}
      <mark>{text.slice(match[0], match[1])}</mark>
      {text.slice(match[1])}
    </>
  );
}

const HIT_ICON: Record<string, string> = { people: "●", works: "▯", ideas: "◇", events: "◉", eras: "▭" };

function hitSub(t: Catalog, data: MapData, h: SearchHit): string {
  const ix = index(data);
  if (h.undated) return t.map.undated;
  if (h.type === "person") {
    const p = ix.people.get(h.id)!;
    return `${p.birth}–${p.death}`;
  }
  if (h.type === "work") {
    const w = ix.works.get(h.id)!;
    const a = (w.author != null && ix.people.get(w.author)?.short) || "";
    return w.kind === "work" ? `${a}, ${w.year}` : `${t.map.kinds[w.kind]} · ${a}`;
  }
  if (h.type === "event") return String(ix.events.get(h.id)!.year);
  if (h.type === "era") {
    const e = ix.eras.get(h.id)!;
    return `${e.from}–${e.to}`;
  }
  const g = ix.groups.get(h.id)!;
  return cap(pick(t.onto.values.group_kind, g.kind) ?? "");
}

function SearchBox({
  data,
  vis,
  state,
  onState,
  onSelect,
  onOpenCard,
  inputRef,
}: Props & { inputRef: RefObject<HTMLInputElement> }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const result = useMemo(() => search(data, vis, state.q), [data, vis, state.q]);
  const groups = SEARCH_GROUPS.map((g) => ({ g, hits: result[g].slice(0, 5) })).filter((x) => x.hits.length);
  const flat = groups.flatMap((x) => x.hits);
  useEffect(() => setActive(0), [state.q]);

  const choose = (h: SearchHit) => {
    setOpen(false);
    if (h.undated) onOpenCard(h.id, h.label);
    else onSelect(h.id, h.hiddenByFilter);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setOpen(true);
      if (flat.length) setActive((i) => (i + (e.key === "ArrowDown" ? 1 : flat.length - 1)) % flat.length);
    } else if (e.key === "Enter") {
      if (flat[active]) {
        e.preventDefault();
        choose(flat[active]);
      }
    } else if (e.key === "Escape") {
      // Esc в поиске закрывает подсказки, а не снимает выбор на карте
      e.stopPropagation();
      e.nativeEvent.stopImmediatePropagation();
      if (open && state.q) setOpen(false);
      else onState({ q: "" });
    }
  };
  const showList = open && state.q.trim().length > 0;
  let n = -1;
  return (
    <div className="map-search" data-section="search">
      <label className={state.q ? "map-search__field is-active" : "map-search__field"}>
        <Icon name="search" small />
        <input
          ref={inputRef}
          type="search"
          value={state.q}
          placeholder={t.map.searchPlaceholder}
          aria-label={t.map.searchLabel}
          role="combobox"
          aria-expanded={showList}
          aria-controls="map-search-list"
          aria-activedescendant={showList && flat[active] ? `map-hit-${flat[active].id}` : undefined}
          onChange={(e) => {
            onState({ q: e.target.value });
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          // Подсказки закрываются после ухода фокуса с запозданием (щелчок по подсказке успевает
          // сработать). Если за это время читатель вернулся в поле, старый таймер список не трогает.
          onBlur={() =>
            setTimeout(() => {
              if (document.activeElement !== inputRef.current) setOpen(false);
            }, 150)
          }
          onKeyDown={onKeyDown}
        />
        <kbd>/</kbd>
      </label>
      {showList && (
        <div className="map-search__list" id="map-search-list" role="listbox" aria-label={t.map.searchLabel}>
          {flat.length === 0 && <p className="map-search__empty">{t.map.nothingFound}</p>}
          {groups.map(({ g, hits }) => (
            <div key={g} role="group" aria-label={t.map.searchGroups[g]}>
              <div className="map-search__group">{t.map.searchGroups[g]}</div>
              {hits.map((h) => {
                n += 1;
                const i = n;
                const out = h.hiddenByFilter || h.undated;
                return (
                  <div
                    key={h.id}
                    id={`map-hit-${h.id}`}
                    role="option"
                    aria-selected={i === active}
                    className={["map-search__row", i === active ? "is-active" : "", out ? "is-out" : ""].join(" ")}
                    onMouseDown={(e) => e.preventDefault()}
                    onMouseEnter={() => setActive(i)}
                    onClick={() => choose(h)}
                  >
                    <span className="map-search__ico" aria-hidden="true">
                      {HIT_ICON[g]}
                    </span>
                    <span className="map-search__main">
                      <Mark text={h.label} match={h.match} />
                    </span>
                    <span className="map-search__sub">
                      {hitSub(t, data, h)}
                      {h.hiddenByFilter ? ` · ${t.map.hiddenByFilter}` : ""}
                    </span>
                  </div>
                );
              })}
            </div>
          ))}
          <div className="map-search__foot">{t.map.searchHint}</div>
        </div>
      )}
    </div>
  );
}

/* ---------- «Выбрано» ---------- */

function Sw({ role }: { role: ColorRole }) {
  return <i className={`sw map-role-${role}`} aria-hidden="true" />;
}

function names(t: Catalog, data: MapData, ids: string[], max = 3): string {
  const ix = index(data).people;
  const list = ids.map((id) => ix.get(id)?.short ?? id);
  return list.length > max ? `${list.slice(0, max).join(", ")} ${t.map.andMore(list.length - max)}` : list.join(", ");
}

function Selected(props: Props) {
  const { data, vis, rel, link, onCloseLink, build, generation } = props;
  const t = useT();
  const ix = index(data);
  if (link) {
    const label = (id: string) => ix.people.get(id)?.label ?? find(data, id)?.obj.label ?? id;
    if (link.status === "loading") return <p className="muted">{t.app.loading}</p>;
    if (!link.edge)
      return (
        <div>
          <p className="muted">{t.map.linkMissing}</p>
          <button type="button" className="pg-btn pg-btn--ghost pg-btn--sm" onClick={onCloseLink}>
            {t.map.closeLink}
          </button>
        </div>
      );
    return <LinkDetails edge={link.edge} label={label} onClose={onCloseLink} />;
  }
  const geo = props.geo;
  if (geo?.place)
    return (
      <GeoPlaceSelected
        data={data}
        place={geo.place}
        country={geo.country?.(geo.place.id) ?? null}
        here={geo.scene?.places.find((p) => p.id === geo.place!.id) ?? null}
        year={geo.year}
        onSelect={(id) => props.onSelect(id)}
        head={
          <FoldHead k="selected">
            {t.map.selected} · {t.geo.placeKicker}
          </FoldHead>
        }
      />
    );
  if (!rel) {
    const many = vis.links.length > 15;
    return (
      <>
        <h2 className="map-panel__h">{t.map.howToRead}</h2>
        <p className="map-selected__hint">
          {t.map.hint}
          {many ? ` ${t.map.hintLinks(vis.links.length)}` : ""}
        </p>
      </>
    );
  }
  const hidden = !(
    vis.people.some((p) => p.id === rel.obj.id) ||
    vis.works.some((w) => w.id === rel.obj.id) ||
    vis.events.some((e) => e.id === rel.obj.id) ||
    vis.eras.some((e) => e.id === rel.obj.id) ||
    vis.groups.some((g) => g.id === rel.obj.id)
  );
  let kicker = "";
  let title = "";
  let sub = "";
  const items: ReactNode[] = [];
  const nWorks = rel.works ? rel.works.size : 0;
  const byRole = (r: ColorRole) => rel.legend.find((x) => x.role === r)?.people ?? [];
  if (rel.type === "person") {
    const p = rel.obj;
    kicker = t.map.types.person;
    title = p.label;
    sub = `${p.birth}–${p.death}`;
    const teachers = byRole("teacher");
    const students = byRole("student");
    if (teachers.length)
      items.push(
        <li key="t">
          <Sw role="teacher" />
          <span>{t.map.teachers(names(t, data, teachers))}</span>
        </li>,
      );
    if (students.length)
      items.push(
        <li key="s">
          <Sw role="student" />
          <span>{t.map.students(names(t, data, students))}</span>
        </li>,
      );
    const own = vis.works.filter((w) => rel.works?.has(w.id) && w.kind === "work").sort((a, b) => b.weight - a.weight);
    items.push(
      <li key="w">
        <Sw role="self" />
        <span>{nWorks ? t.map.ownWorks(nWorks, own[0]?.label) : t.map.noWorks}</span>
      </li>,
    );
  } else if (rel.type === "work") {
    const w = rel.obj;
    const a = w.author != null ? ix.people.get(w.author) : undefined;
    kicker = t.map.kinds[w.kind];
    title = w.kind === "work" ? `«${w.label}»` : w.label;
    sub = String(w.year);
    if (a)
      items.push(
        <li key="a">
          <Sw role="self" />
          <span>{t.map.author(a.label, a.birth, a.death)}</span>
        </li>,
      );
    if (nWorks > 1)
      items.push(
        <li key="m">
          <Sw role="self" />
          <span>{t.map.moreByAuthor(nWorks - 1)}</span>
        </li>,
      );
  } else {
    const o = rel.obj;
    kicker =
      rel.type === "era" ? t.map.types.era : rel.type === "event" ? t.map.types.event : (cap(pick(t.onto.values.group_kind, rel.obj.kind) ?? "") || t.map.types.group);
    title = o.label;
    sub = rel.type === "era" ? `${rel.obj.from}–${rel.obj.to}` : rel.type === "event" ? String(rel.obj.year) : "";
    if (rel.legend.length)
      items.push(
        <li key="l" className="map-selected__names">
          {rel.legend.map((x) => (
            <b key={x.role}>
              <Sw role={x.role} />
              {x.role === "other" ? t.map.andMore(x.people.length) : names(t, data, x.people)}
            </b>
          ))}
        </li>,
      );
    else
      items.push(
        <li key="n">
          <span>{t.map.noMembers}</span>
        </li>,
      );
    items.push(
      <li key="w">
        <i className="k k-works" aria-hidden="true" />
        <span>{rel.type === "event" ? t.map.worksAround(nWorks) : t.map.theirWorks(nWorks)}</span>
      </li>,
    );
  }
  if (rel.era)
    items.push(
      <li key="era">
        <i className="k k-era" aria-hidden="true" />
        <span>{t.map.era(rel.era.label)}</span>
      </li>,
    );
  // Подпись пунктира — только при включённой достройке: без неё читатель о модели не спрашивал.
  if (generation && rel.links.some((x) => x.link.generated))
    items.push(
      <li key="unv">
        <i className="k k-unv" aria-hidden="true" />
        <span>{t.map.dashedNote}</span>
      </li>,
    );
  const noLinks = (rel.type === "person" || rel.type === "group") && rel.links.length === 0;
  const notice = build.notice ? (pick(t.graph.notices, build.extension) ?? build.notice) : null;
  return (
    <>
      <FoldHead k="selected">
        {t.map.selected} · {kicker}
      </FoldHead>
      <div className="map-selected__name">
        {title} {sub && <span>{sub}</span>}
      </div>
      {geo?.noPlace && <p className="map-selected__note geo-selected__noplace">{t.geo.noPlace}</p>}
      {geo?.where && <GeoWhere where={geo.where} />}
      <ul className="map-selected__list">{items}</ul>
      {hidden && (
        <p className="map-selected__note">
          {t.map.selectedHidden}{" "}
          <button type="button" className="map-link-btn" onClick={() => props.onState({ filter: emptyFilter() })}>
            {t.map.reset}
          </button>
        </p>
      )}
      {noLinks && !build.running && (
        <div className="map-selected__note">
          <p>{t.graph.empty}</p>
          {/* После попытки достроить ту же кнопку несёт уведомление ниже — одна кнопка, не две. */}
          {!generation && build.extension !== "disabled" && (
            <button type="button" className="pg-btn pg-btn--secondary pg-btn--sm" onClick={props.onEnableGeneration}>
              {t.graph.enableExtension}
            </button>
          )}
        </div>
      )}
      <div className="actions map-selected__actions">
        <button type="button" className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => props.onOpenCard(rel.obj.id, rel.obj.label)}>
          <Icon name="expand" small />
          {t.graph.openCard}
        </button>
        <button
          type="button"
          className="pg-btn pg-btn--ghost pg-btn--sm"
          disabled={build.running}
          aria-busy={build.running || undefined}
          onClick={() => props.onBuild()}
        >
          <Icon name="graph" small />
          {build.running ? t.graph.extending : t.map.build}
        </button>
      </div>
      {build.added > 0 && <p className="map-selected__note">{t.map.added(build.added)}</p>}
      {notice && (
        <div className="pg-notice pg-notice--stacked map-selected__notice" role="status">
          <Icon name="info" />
          <div>{notice}</div>
          {build.extension === "disabled" && !generation && (
            <button type="button" className="pg-btn pg-btn--ghost pg-btn--sm" onClick={props.onEnableGeneration}>
              {t.graph.enableExtension}
            </button>
          )}
        </div>
      )}
      {build.problem && (
        <div className="pg-notice pg-notice--danger pg-notice--stacked" role="alert">
          <Icon name="warning" />
          <div>
            {build.problem.kind === "service_down" ? t.graph.serviceDown : build.problem.message || t.graph.failed}
            {build.problem.suggestions.length > 0 && (
              <div className="actions">
                {build.problem.suggestions.map((r) => (
                  <button key={r.code} type="button" className="pg-btn pg-btn--secondary pg-btn--sm" onClick={() => props.onBuild(r.code)}>
                    {pick(t.onto.recipes, r.code) ?? r.title}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}

/* ---------- фильтры ---------- */

// Значения фильтра — всплывающим окном слева от панели, поверх карты: высота панели не
// меняется. Открыто одно окно; щелчок вне окна и Esc закрывают его.
function Facet({
  title,
  value,
  open,
  onOpen,
  children,
}: {
  title: string;
  value?: string;
  open: boolean;
  onOpen: (open: boolean) => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDetailsElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const [shift, setShift] = useState(0);
  // Окно не выходит за низ панели: поднимается на сколько нужно.
  useLayoutEffect(() => {
    if (!open || !pop.current || !ref.current) return setShift(0);
    const panel = ref.current.closest(".map-panel");
    if (!panel) return;
    const r = pop.current.getBoundingClientRect();
    const limit = Math.min(panel.getBoundingClientRect().bottom, window.innerHeight - 8);
    const over = r.bottom - shift - limit;
    setShift(over > 0 ? -over : 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) onOpen(false);
    };
    const esc = (e: globalThis.KeyboardEvent) => {
      if (e.key !== "Escape") return;
      // Esc закрывает окно фильтра, а не снимает выбор на карте
      e.stopImmediatePropagation();
      onOpen(false);
      ref.current?.querySelector("summary")?.focus();
    };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc, true);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", esc, true);
    };
  }, [open, onOpen]);
  return (
    <details ref={ref} className={value ? "map-facet is-on" : "map-facet"} open={open}>
      <summary
        onClick={(e) => {
          e.preventDefault();
          onOpen(!open);
        }}
      >
        <span>{title}</span>
        {value && <b>{value}</b>}
      </summary>
      <div className="map-facet__body" ref={pop} role="group" aria-label={title} style={shift ? { marginTop: shift } : undefined}>
        <div className="map-facet__title">{title}</div>
        {children}
      </div>
    </details>
  );
}

function Check({ label, count, checked, onChange }: { label: string; count: number; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="map-check">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}</span>
      <span className="map-check__count">{count}</span>
    </label>
  );
}

const toggle = (list: string[], v: string, on: boolean) => (on ? [...new Set([...list, v])] : list.filter((x) => x !== v));

function YearInput({ label, value, onCommit }: { label: string; value: number; onCommit: (v: number) => void }) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  const commit = () => {
    if (/^-?\d+$/.test(text.trim())) onCommit(Number(text.trim()));
    else setText(String(value));
  };
  return (
    <label>
      {label}
      <input
        className="pg-input map-year"
        inputMode="numeric"
        value={text}
        aria-label={label}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && commit()}
      />
    </label>
  );
}

function Filters({ data, vis, state, onState }: Props) {
  const t = useT();
  const f = state.filter;
  const c = useMemo(() => countsOf(data, vis, f), [data, vis, f]);
  const set = (patch: Partial<Filter>) => onState({ filter: { ...f, ...patch } });
  const groupsOf = (kind: string) => data.groups.filter((g) => g.kind === kind);
  const groupFacet = (kind: "direction" | "school", title: string) => {
    const gs = groupsOf(kind);
    if (!gs.length) return null;
    const n = gs.filter((g) => f.groups.includes(g.id)).length;
    return (
      <Facet {...facet(title)} value={n ? String(n) : undefined}>
        {gs.map((g) => (
          <Check
            key={g.id}
            label={g.label}
            count={c.groups[g.id] ?? 0}
            checked={f.groups.includes(g.id)}
            onChange={(on) => set({ groups: toggle(f.groups, g.id, on) })}
          />
        ))}
      </Facet>
    );
  };
  const listFacet = (key: "roles" | "kinds" | "ekinds", title: string, names: Record<string, string>, tally: Record<string, number>) => {
    const codes = Object.keys(tally);
    if (!codes.length) return null;
    const order = Object.keys(names);
    codes.sort((a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99));
    return (
      <Facet {...facet(title)} value={f[key].length ? String(f[key].length) : undefined}>
        {codes.map((code) => (
          <Check
            key={code}
            label={cap(pick(names, code) ?? code)}
            count={tally[code]}
            checked={f[key].includes(code)}
            onChange={(on) => set({ [key]: toggle(f[key], code, on) } as Partial<Filter>)}
          />
        ))}
      </Facet>
    );
  };
  // Фасет «Эпоха»: только датированные эпохи карты (в data.eras эпох без датировки нет).
  const epochFacet = () => {
    if (!data.eras.length) return null;
    const n = data.eras.filter((e) => f.epochs.includes(e.id)).length;
    return (
      <Facet {...facet(t.map.facets.epoch)} value={n ? String(n) : undefined}>
        {data.eras.map((e) => (
          <Check
            key={e.id}
            label={e.label}
            count={c.epochs[e.id] ?? 0}
            checked={f.epochs.includes(e.id)}
            onChange={(on) => set({ epochs: toggle(f.epochs, e.id, on) })}
          />
        ))}
      </Facet>
    );
  };
  const filtered = isFiltered(f);
  const [from, to] = vis.range;
  // Окно задано читателем или выбранными эпохами (если читатель своё не задал).
  const windowSet = f.from != null || f.to != null || epochWindow(data, f) != null;
  const fold = useContext(FoldContext);
  const [openFacet, setOpenFacet] = useState<string | null>(null);
  const facet = (title: string) => ({
    title,
    open: openFacet === title,
    onOpen: (on: boolean) => setOpenFacet(on ? title : null),
  });
  const head = (
    <FoldHead
      k="filters"
      extra={
        c.active > 0 && (
          <button type="button" className="map-link-btn" onClick={() => onState({ filter: emptyFilter() })}>
            {t.map.reset}
          </button>
        )
      }
    >
      {t.map.sections.filters}
      {c.active > 0 && <span className="badge badge--accent map-badge">{c.active}</span>}
    </FoldHead>
  );
  if (fold.closed("filters")) return head;
  return (
    <>
      {head}
      <p className="map-shown">
        {filtered
          ? t.map.shownOf(c.shown.people, c.total.people, c.shown.works, c.total.works)
          : t.map.totals(c.total.people, c.total.works, c.total.links)}
      </p>
      <Facet {...facet(t.map.facets.time)} value={windowSet ? `${from}–${to}` : undefined}>
        <div className="map-range">
          <YearInput label={t.map.from} value={from} onCommit={(v) => set({ from: v <= (data.range ?? vis.range)[0] ? undefined : Math.min(v, to - 1) })} />
          <YearInput label={t.map.to} value={to} onCommit={(v) => set({ to: v >= (data.range ?? vis.range)[1] ? undefined : Math.max(v, from + 1) })} />
        </div>
        <p className="map-facet__hint">{t.map.timeHint}</p>
      </Facet>
      {epochFacet()}
      {groupFacet("direction", t.map.facets.direction)}
      {groupFacet("school", t.map.facets.school)}
      {listFacet("roles", t.map.facets.role, t.onto.values.person_role, c.roles)}
      {listFacet("kinds", t.map.facets.kind, t.map.kinds, c.kinds)}
      {listFacet("ekinds", t.map.facets.events, t.onto.values.event_kind, c.ekinds)}
      <Facet {...facet(t.map.facets.links)} value={f.verified ? t.map.verifiedShort : undefined}>
        <Check label={t.map.onlyVerified} count={c.verified} checked={f.verified} onChange={(on) => set({ verified: on })} />
        <p className="map-facet__hint">{t.map.verifiedHint}</p>
      </Facet>
    </>
  );
}

/* ---------- условные знаки ---------- */

export function Legend() {
  const t = useT();
  const L = t.map.legend;
  return (
    <>
      <div className="map-legend">
        <span>
          <svg viewBox="0 0 34 12" aria-hidden="true">
            <rect className="map-legend__life" x="1" y="2" width="32" height="8" rx="4" />
          </svg>
          {L.life}
        </span>
        <span>
          <svg viewBox="0 0 34 12" aria-hidden="true">
            <path className="map-legend__thread" d="M2 9 C12 9 20 3 32 3" />
          </svg>
          {L.influence}
        </span>
        <span>
          <svg viewBox="0 0 34 12" aria-hidden="true">
            <path className="map-legend__thread" d="M2 9 C12 9 20 3 32 3" strokeDasharray="4 3" />
          </svg>
          {L.unverified}
        </span>
        <span className="map-kind-work">
          <svg viewBox="0 0 14 16" aria-hidden="true">
            <rect className="map-work__mark" x="2" y="1.5" width="10" height="13" rx="1" />
            <rect className="map-work__spine" x="2" y="1.5" width="2.6" height="13" />
          </svg>
          {L.work}
        </span>
        <span className="map-kind-concept">
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path className="map-work__mark" d="M8 2 L14 8 L8 14 L2 8 Z" />
          </svg>
          {L.concept}
        </span>
        <span className="map-kind-position">
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path className="map-work__mark" d="M8 1.5 L14.5 13.5 L1.5 13.5 Z" />
          </svg>
          {L.position}
        </span>
        <span className="map-kind-argument">
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <path className="map-work__mark" d="M1.5 1.5 H14.5 V14.5 H1.5 Z M5 8 H11 M8.5 5.5 L11 8 L8.5 10.5" />
          </svg>
          {L.argument}
        </span>
        <span>
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <circle className="map-event__ring" cx="8" cy="8" r="5" />
            <circle className="map-event__dot" cx="8" cy="8" r="1.8" />
          </svg>
          {L.event}
        </span>
      </div>
      <p className="map-legend__note">{L.note}</p>
    </>
  );
}
