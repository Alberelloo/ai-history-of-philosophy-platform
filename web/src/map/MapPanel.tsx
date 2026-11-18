import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode, type RefObject } from "react";
import { pick, useT, type Catalog } from "../i18n";
import { Icon, type IconName } from "../ui";
import { LinkDetails, type GEdge } from "./LinkDetails";
import {
  counts as countsOf,
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
  onSelect: (id: string | null, resetFilter?: boolean) => void;
  link: LinkView | null;
  onCloseLink: () => void;
  build: BuildState;
  onBuild: (recipe?: string) => void;
  generation: boolean;
  onEnableGeneration: () => void;
  onOpenCard: (id: string, title: string) => void;
};

type Section = "search" | "selected" | "filters" | "legend";

const SECTION_ICON: Record<Section, IconName> = { search: "search", selected: "check", filters: "filter", legend: "legend" };

export function MapPanel(props: Props) {
  const { collapsed, onCollapse } = props;
  const t = useT();
  const body = useRef<HTMLDivElement>(null);
  const searchInput = useRef<HTMLInputElement>(null);
  const [focus, setFocus] = useState<Section | null>(null);

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
    <aside className={collapsed ? "map-panel is-collapsed" : "map-panel"} aria-label={t.map.panel}>
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
          <section className="map-panel__sec map-selected" data-section="selected" aria-live="polite">
            <Selected {...props} />
          </section>
          <section className="map-panel__sec" data-section="filters" aria-label={t.map.sections.filters}>
            <Filters {...props} />
          </section>
          <section className="map-panel__sec" data-section="legend" aria-label={t.map.sections.legend}>
            <Legend />
          </section>
        </div>
      )}
    </aside>
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
    const a = ix.people.get(w.author)?.short ?? "";
    return w.kind === "work" ? `${a}, ${w.year}` : `${t.map.kinds[w.kind]} · ${a}`;
  }
  if (h.type === "event") return String(ix.events.get(h.id)!.year);
  if (h.type === "era") {
    const e = ix.eras.get(h.id)!;
    return `${e.from}–${e.to}`;
  }
  const g = ix.groups.get(h.id)!;
  return pick(t.map.groupKinds, g.kind) ?? g.kind;
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
          onBlur={() => setTimeout(() => setOpen(false), 150)}
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
    const a = ix.people.get(w.author);
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
      rel.type === "era" ? t.map.types.era : rel.type === "event" ? t.map.types.event : (pick(t.map.groupKinds, rel.obj.kind) ?? t.map.types.group);
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
  if (rel.links.some((x) => x.link.generated))
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
      <h2 className="map-panel__h">
        {t.map.selected} · {kicker}
      </h2>
      <div className="map-selected__name">
        {title} {sub && <span>{sub}</span>}
      </div>
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
          {!generation && (
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

function Facet({ title, value, open, children }: { title: string; value?: string; open?: boolean; children: ReactNode }) {
  return (
    <details className={value ? "map-facet is-on" : "map-facet"} open={open || !!value || undefined}>
      <summary>
        <span>{title}</span>
        {value && <b>{value}</b>}
      </summary>
      <div className="map-facet__body">{children}</div>
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
      <Facet title={title} value={n ? String(n) : undefined}>
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
      <Facet title={title} value={f[key].length ? String(f[key].length) : undefined}>
        {codes.map((code) => (
          <Check
            key={code}
            label={pick(names, code) ?? code}
            count={tally[code]}
            checked={f[key].includes(code)}
            onChange={(on) => set({ [key]: toggle(f[key], code, on) } as Partial<Filter>)}
          />
        ))}
      </Facet>
    );
  };
  const filtered = isFiltered(f);
  const [from, to] = vis.range;
  return (
    <>
      <div className="map-panel__row">
        <h2 className="map-panel__h">
          {t.map.sections.filters}
          {c.active > 0 && <span className="badge badge--accent map-badge">{c.active}</span>}
        </h2>
        {c.active > 0 && (
          <button type="button" className="map-link-btn" onClick={() => onState({ filter: emptyFilter() })}>
            {t.map.reset}
          </button>
        )}
      </div>
      <p className="map-shown">
        {filtered
          ? t.map.shownOf(c.shown.people, c.total.people, c.shown.works, c.total.works)
          : t.map.totals(c.total.people, c.total.works, c.total.links)}
      </p>
      <Facet title={t.map.facets.time} value={f.from != null || f.to != null ? `${from}–${to}` : undefined}>
        <div className="map-range">
          <YearInput label={t.map.from} value={from} onCommit={(v) => set({ from: v <= data.range[0] ? undefined : Math.min(v, to - 1) })} />
          <YearInput label={t.map.to} value={to} onCommit={(v) => set({ to: v >= data.range[1] ? undefined : Math.max(v, from + 1) })} />
        </div>
        <p className="map-facet__hint">{t.map.timeHint}</p>
      </Facet>
      {groupFacet("direction", t.map.facets.direction)}
      {groupFacet("school", t.map.facets.school)}
      {listFacet("roles", t.map.facets.role, t.map.roles, c.roles)}
      {listFacet("kinds", t.map.facets.kind, t.map.kinds, c.kinds)}
      {listFacet("ekinds", t.map.facets.events, t.map.ekinds, c.ekinds)}
      <Facet title={t.map.facets.links} value={f.verified ? t.map.verifiedShort : undefined}>
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
      <h2 className="map-panel__h">{t.map.sections.legend}</h2>
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
