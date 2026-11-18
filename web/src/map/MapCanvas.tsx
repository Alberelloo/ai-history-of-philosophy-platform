import { useMemo, type KeyboardEvent, type MouseEvent, type MutableRefObject, type ReactNode } from "react";
import { useT } from "../i18n";
import { Icon, monogram } from "../ui";
import { layout, type MapLayout, type Measure } from "./layout";
import type { Related, Visible } from "./model";
import { toggleLens, STRATA, type MapData, type Stratum } from "./types";
import { composeSvg } from "./exportSvg";

// Холст карты: SVG из раскладки layout(). Три части по вертикали — верх (события, эпохи),
// страта людей (прокручивается внутри, если дорожек больше, чем помещается) и низ (труды, ось).
// Координаты частей общие: верх и низ — в координатах кадра (viewBox со смещением),
// люди и линии влияний — от верха страты людей (так их отдаёт layout).
// Цвет — принадлежность: класс map-role-<роль> задаёт --role, палитра — токены --sel-*.

type Props = {
  data: MapData;
  vis: Visible;
  rel: Related | null;
  sel: string | null;
  collapsed: Stratum[];
  width: number;
  height: number;
  measure: Measure;
  fontsVersion: number; // после загрузки шрифтов раскладка пересчитывается
  linkSel: string | null;
  onSelect: (id: string | null) => void;
  onLink: (id: string) => void;
  onLens: (collapsed: Stratum[]) => void;
  exportRef: MutableRefObject<(() => string | null) | null>;
};

const r1 = (n: number) => Math.round(n * 10) / 10;

export function MapCanvas(props: Props) {
  const { data, vis, rel, sel, collapsed, width, height, measure, fontsVersion, linkSel } = props;
  const t = useT();
  const L = useMemo(
    () => layout({ data, vis, rel, sel, width, height, collapsed, measure }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data, vis, rel, sel, width, height, collapsed, measure, fontsVersion],
  );
  const top = L.bands.people.top;
  const peopleH = L.bands.people.bot - top;
  const contentH = L.peopleScroll ? L.peopleScroll.contentHeight : peopleH;
  const bottomH = L.height - L.bands.people.bot;

  // Выгрузка: три части складываются в один рисунок; люди — целиком, со всеми дорожками.
  props.exportRef.current = () => {
    const parts = [...document.querySelectorAll<SVGSVGElement>(".map-canvas svg[data-part]")];
    const [a, b, c] = ["top", "people", "bottom"].map((k) => parts.find((p) => p.dataset.part === k));
    if (!a || !b || !c) return null;
    const sheet = getComputedStyle(document.querySelector(".map-sheet") ?? document.body).backgroundColor;
    return composeSvg(
      [
        { svg: a, y: 0, height: top },
        { svg: b, y: top, height: contentH },
        { svg: c, y: top + contentH, height: bottomH },
      ],
      width,
      sheet || "white",
    );
  };

  const counts: Record<Stratum, number> = {
    events: vis.events.length,
    eras: vis.eras.length,
    people: vis.people.length,
    works: vis.works.length,
  };

  // Выбор делегирован: щелчок по сущности выбирает её, по линии — открывает связь,
  // по пустому полю — снимает выбор.
  const onClick = (e: MouseEvent) => {
    const target = e.target as Element;
    if (target.closest("button")) return;
    const link = target.closest<SVGElement>("[data-link]");
    if (link) return props.onLink(link.dataset.link!);
    const entity = target.closest<SVGElement>("[data-entity]");
    props.onSelect(entity ? entity.dataset.entity! : null);
  };
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const target = e.target as Element;
    const link = target.closest<SVGElement>("[data-link]");
    const entity = target.closest<SVGElement>("[data-entity]");
    if (!link && !entity) return;
    e.preventDefault();
    if (link) props.onLink(link.dataset.link!);
    else props.onSelect(entity!.dataset.entity!);
  };

  const grid = (y1: number, y2: number) =>
    L.scale.ticks.map((y) => (
      <line key={`g${y}`} className="map-grid" x1={r1(L.scale.x(y))} x2={r1(L.scale.x(y))} y1={y1} y2={y2} />
    ));
  const separator = (k: Stratum) => (
    <line
      key={`sep-${k}`}
      className="map-band-sep"
      x1={L.scale.left - 6}
      x2={L.scale.right}
      y1={L.bands[k].top}
      y2={L.bands[k].top}
    />
  );
  const collapsedNote = (k: Stratum, y: number) =>
    L.bands[k].collapsed ? (
      <text key={`note-${k}`} className="map-collapsed-note" x={L.scale.left + 4} y={y + 15}>
        {t.map.collapsedNote(t.map.count[k](counts[k]))}
      </text>
    ) : null;

  const last = STRATA.filter((k) => !collapsed.includes(k)).length <= 1;

  return (
    <div className="map-canvas" onClick={onClick} onKeyDown={onKeyDown} data-dense={L.dense ? "true" : "false"}>
      {/* Линзы — у своих страт, в левом поле */}
      <div className="map-lenses" role="group" aria-label={t.map.lenses}>
        {STRATA.map((k) => {
          const on = !collapsed.includes(k);
          const locked = on && last;
          return (
            <button
              key={k}
              type="button"
              className={on ? "map-lens" : "map-lens is-off"}
              style={{ top: L.bands[k].top }}
              aria-pressed={on}
              aria-disabled={locked || undefined}
              title={locked ? t.map.lensLast : on ? t.map.lensCollapse : t.map.lensExpand}
              data-lens={k}
              onClick={() => !locked && props.onLens(toggleLens(collapsed, k))}
            >
              <Icon name={on ? "eye" : "eyeOff"} small />
              <span>{t.map.strata[k]}</span>
            </button>
          );
        })}
      </div>

      <svg
        data-part="top"
        className="map-svg"
        width={width}
        height={top}
        viewBox={`0 0 ${width} ${top}`}
        role="group"
        aria-label={t.map.partTop}
      >
        {grid(L.bands.events.top, top)}
        {separator("events")}
        {separator("eras")}
        <Eras L={L} data={data} />
        <Events L={L} sel={sel} />
        {collapsedNote("events", L.bands.events.top)}
        {collapsedNote("eras", L.bands.eras.top)}
      </svg>

      <div
        className={L.peopleScroll ? "map-people is-scroll" : "map-people"}
        style={{ height: peopleH }}
        tabIndex={L.peopleScroll ? 0 : undefined}
        aria-label={L.peopleScroll ? t.map.peopleScroll : undefined}
        role={L.peopleScroll ? "region" : undefined}
      >
        <svg
          data-part="people"
          className="map-svg"
          width={width}
          height={contentH}
          viewBox={`0 0 ${width} ${contentH}`}
          role="group"
          aria-label={t.map.strata.people}
        >
          {grid(0, contentH)}
          <line className="map-band-sep" x1={L.scale.left - 6} x2={L.scale.right} y1={0.5} y2={0.5} />
          {L.bands.people.collapsed ? (
            <>
              {collapsedNote("people", 0)}
              {L.people.map((p) => (
                <rect key={p.id} className="map-people-tick" x={p.bx} y={21} width={Math.max(1, p.dx - p.bx)} height={3} rx={1.5} />
              ))}
            </>
          ) : (
            <>
              <Threads L={L} data={data} linkSel={linkSel} />
              <People L={L} vis={vis} sel={sel} />
            </>
          )}
        </svg>
      </div>

      <svg
        data-part="bottom"
        className="map-svg"
        width={width}
        height={bottomH}
        viewBox={`0 ${L.bands.people.bot} ${width} ${bottomH}`}
        role="group"
        aria-label={t.map.partBottom}
      >
        {grid(L.bands.works.top, L.axisY)}
        {separator("works")}
        <Works L={L} data={data} />
        {collapsedNote("works", L.bands.works.top)}
        <Axis L={L} />
      </svg>
    </div>
  );
}

/* ---------- эпохи ---------- */

function Eras({ L, data }: { L: MapLayout; data: MapData }) {
  const t = useT();
  const b = L.bands.eras;
  if (b.collapsed) return null;
  const anyActive = L.eras.some((e) => e.active);
  return (
    <g>
      {L.eras.map((e) => {
        const label = data.eras.find((x) => x.id === e.id);
        return (
          <g
            key={e.id}
            className={["map-entity", "map-era", e.active ? "is-active" : anyActive ? "is-dim" : ""].join(" ")}
            data-entity={e.id}
            role="button"
            tabIndex={0}
            aria-pressed={e.active}
            aria-label={t.map.aria.era(label?.label ?? "", label?.from ?? 0, label?.to ?? 0)}
          >
            <title>{label ? `${label.label}, ${label.from}–${label.to}` : ""}</title>
            <rect className="map-era__fill" x={e.x1} y={b.top + 1} width={Math.max(0, e.x2 - e.x1 - 1)} height={b.bot - b.top - 2} />
            {e.labelFits && label && (
              <text className="map-era__text" x={(e.x1 + e.x2) / 2} y={(b.top + b.bot) / 2 + 5} style={{ font: L.fonts.eraText }}>
                {label.label}
              </text>
            )}
          </g>
        );
      })}
    </g>
  );
}

/* ---------- события ---------- */

function Events({ L, sel }: { L: MapLayout; sel: string | null }) {
  const t = useT();
  const b = L.bands.events;
  if (b.collapsed)
    return (
      <g>
        {L.events.map((e) => (
          <rect key={e.id} className="map-event-tick" x={e.x - 0.75} y={b.bot - 9} width={1.5} height={6} />
        ))}
      </g>
    );
  return (
    <g>
      {L.events.map((e) => (
        <g
          key={e.id}
          className={e.focus ? "map-entity map-event" : "map-entity map-event is-dim"}
          data-entity={e.id}
          role="button"
          tabIndex={0}
          aria-pressed={sel === e.id}
          aria-label={t.map.aria.event(e.event.year, e.event.label)}
        >
          <title>{`${e.event.year} — ${e.event.label}`}</title>
          {e.row < 0 ? (
            <>
              <circle className="map-event__ring" cx={e.x} cy={e.y} r={2.5} />
              <rect x={e.x - 6} y={b.top} width={12} height={11} fill="transparent" />
            </>
          ) : (
            <>
              <circle className={sel === e.id ? "map-event__ring is-on" : "map-event__ring"} cx={e.x} cy={e.y} r={5} />
              <circle className="map-event__dot" cx={e.x} cy={e.y} r={1.8} />
              <text
                className="map-event__text"
                x={e.side > 0 ? e.x + 12 : e.x - 12}
                y={e.y + 4.5}
                textAnchor={e.side > 0 ? "start" : "end"}
                style={{ font: L.fonts.eventText }}
              >
                <tspan className="map-event__year">{e.event.year} </tspan>
                {e.event.label}
              </text>
            </>
          )}
        </g>
      ))}
    </g>
  );
}

/* ---------- люди ---------- */

function People({ L, vis, sel }: { L: MapLayout; vis: Visible; sel: string | null }) {
  const t = useT();
  const byId = useMemo(() => new Map(vis.people.map((p) => [p.id, p])), [vis.people]);
  const { band: BAND, rx: RX, ry: RY } = L.geometry;
  const dense = L.dense;
  return (
    <g>
      {L.people.map((p) => {
        const m = byId.get(p.id)!;
        const strong = p.role != null && p.role !== "other";
        const cls = ["map-entity", "map-person", p.dim ? "is-dim" : "", p.role ? `map-role-${p.role}` : ""].join(" ");
        const name = (
          <text
            className={strong ? "map-person__name is-strong" : "map-person__name"}
            x={p.nameX}
            y={p.y + (dense ? 4.6 : 5.4)}
            style={{ font: strong ? L.fonts.selName : L.fonts.personName }}
          >
            {p.label}
          </text>
        );
        const years = `${m.birth}–${m.death}`;
        let medal: ReactNode = null;
        if (dense && p.medallion) {
          const r = 13;
          medal = (
            <>
              <circle className="map-person__halo" cx={p.bx} cy={p.y} r={r + 3} />
              <circle className="map-person__medal" cx={p.bx} cy={p.y} r={r} />
              {m.portrait ? (
                <>
                  <clipPath id={`clip-${p.id}`}>
                    <circle cx={p.bx} cy={p.y} r={r} />
                  </clipPath>
                  <image
                    href={m.portrait}
                    x={p.bx - r}
                    y={p.y - r}
                    width={r * 2}
                    height={r * 2}
                    preserveAspectRatio="xMidYMid slice"
                    clipPath={`url(#clip-${p.id})`}
                  />
                </>
              ) : (
                <text className="map-person__mono" x={p.bx} y={p.y + 3.5} style={{ font: `500 10px ${SERIF}` }}>
                  {monogram(m.label)}
                </text>
              )}
            </>
          );
        } else if (!dense) {
          medal = (
            <>
              {sel === p.id && <ellipse className="map-person__halo" cx={p.bx} cy={p.y} rx={RX + 4} ry={RY + 4} />}
              <ellipse className="map-person__medal" cx={p.bx} cy={p.y} rx={RX} ry={RY} />
              {m.portrait ? (
                <>
                  <clipPath id={`clip-${p.id}`}>
                    <ellipse cx={p.bx} cy={p.y} rx={RX} ry={RY} />
                  </clipPath>
                  <image
                    href={m.portrait}
                    x={p.bx - RX}
                    y={p.y - RY}
                    width={RX * 2}
                    height={RY * 2}
                    preserveAspectRatio="xMidYMid slice"
                    clipPath={`url(#clip-${p.id})`}
                  />
                </>
              ) : (
                <text className="map-person__mono" x={p.bx} y={p.y + RY * 0.27} style={{ font: `500 ${(RY * 0.72).toFixed(1)}px ${SERIF}` }}>
                  {monogram(m.label)}
                </text>
              )}
            </>
          );
        }
        return (
          <g
            key={p.id}
            className={cls}
            data-entity={p.id}
            data-person={p.id}
            role="button"
            tabIndex={0}
            aria-pressed={sel === p.id}
            aria-label={t.map.aria.person(m.label, m.birth, m.death)}
          >
            <title>{`${m.label}, ${years}`}</title>
            <rect
              className="map-person__life"
              x={p.bx}
              y={p.y - BAND / 2}
              width={Math.max(BAND, p.dx - p.bx)}
              height={BAND}
              rx={BAND / 2}
            />
            {dense && !p.medallion && <circle className="map-person__dot" cx={p.bx + BAND / 2} cy={p.y} r={2.2} />}
            {medal}
            {name}
            {!dense && (
              <text
                className="map-person__years"
                x={p.yearsX}
                y={p.y + 4.3}
                textAnchor={p.yearsIn ? "end" : "start"}
                style={{ font: L.fonts.personYears }}
              >
                {years}
              </text>
            )}
            <rect
              className="map-focus-ring"
              x={p.bx - (p.medallion ? 18 : 6)}
              y={p.y - Math.max(BAND / 2, p.medallion ? 16 : 0) - 3}
              width={Math.max(p.dx, p.labelEnd) - p.bx + (p.medallion ? 24 : 12)}
              height={Math.max(BAND, p.medallion ? 32 : 0) + 6}
              rx={4}
            />
          </g>
        );
      })}
    </g>
  );
}

const SERIF = '"Literata Variable", Literata, Georgia, serif';

/* ---------- линии влияний ---------- */

function Threads({ L, data, linkSel }: { L: MapLayout; data: MapData; linkSel: string | null }) {
  const t = useT();
  const links = useMemo(() => new Map(data.links.map((l) => [l.id, l])), [data.links]);
  const label = (id: string) => data.people.find((p) => p.id === id)?.label ?? id;
  return (
    <g>
      {L.threads.map((x) => (
        <g key={x.linkId} className={x.role ? `map-role-${x.role}` : undefined}>
          <path
            className={[x.role ? "map-thread is-on" : "map-thread", linkSel === x.linkId ? "is-picked" : ""].join(" ")}
            d={x.d}
            strokeDasharray={x.dashed ? "4 3" : undefined}
            data-generated={x.dashed ? "true" : "false"}
          />
          {x.role && <circle className="map-thread__end" cx={x.end.x} cy={x.end.y} r={2.4} />}
        </g>
      ))}
      {/* Цели нажатия поверх линий: широкий прозрачный штрих */}
      {L.threads.map((x) => {
        const meta = links.get(x.linkId);
        const name = meta ? t.map.aria.link(label(meta.subject), label(meta.object), x.dashed) : x.linkId;
        return (
          <path
            key={`hit-${x.linkId}`}
            className="map-thread-hit"
            d={x.d}
            data-link={x.linkId}
            role="button"
            tabIndex={0}
            aria-pressed={linkSel === x.linkId}
            aria-label={name}
          >
            <title>{name}</title>
          </path>
        );
      })}
    </g>
  );
}

/* ---------- труды и идеи ---------- */

function Works({ L, data }: { L: MapLayout; data: MapData }) {
  const t = useT();
  const b = L.bands.works;
  const people = useMemo(() => new Map(data.people.map((p) => [p.id, p])), [data.people]);
  if (b.collapsed)
    return (
      <g>
        {L.works.map((w) => (
          <rect key={w.id} className="map-work-tick" x={w.x - 0.75} y={b.bot - 9} width={1.5} height={6} />
        ))}
      </g>
    );
  const rail = b.top + 9;
  return (
    <g>
      {L.works.map((it) => {
        const w = it.work;
        const author = people.get(w.author);
        const cls = ["map-entity", "map-work", `map-kind-${w.kind}`, it.role ? `map-role-${it.role}` : "", it.primary ? "is-primary" : ""].join(" ");
        const x = it.bx;
        const iy = it.y;
        const cy = iy + 10;
        const font = it.role ? L.fonts.workActive : w.kind === "work" ? L.fonts.workTitle : L.fonts.conceptTitle;
        return (
          <g
            key={it.id}
            className={cls}
            data-entity={it.id}
            role="button"
            tabIndex={0}
            aria-pressed={it.primary}
            aria-label={t.map.aria.work(t.map.kinds[w.kind], w.label, w.year, author?.label ?? "")}
          >
            <title>{`${w.label}, ${w.year}${author ? ` — ${author.label}` : ""}`}</title>
            <rect className="map-work__tick" x={it.x - 0.75} y={rail - 4} width={1.5} height={8} />
            {it.row < 0 ? (
              <rect x={it.x - 5} y={rail - 7} width={10} height={14} fill="transparent" />
            ) : (
              <>
                <path className="map-work__stem" d={`M${r1(it.x)} ${rail + 4} L${r1(x)} ${rail + 9} V${iy - 2}`} />
                <WorkIcon kind={w.kind} x={x} iy={iy} cy={cy} />
                {it.primary && <circle className="map-work__halo" cx={x} cy={cy} r={15} />}
                <text className="map-work__title" x={x} y={iy + 36} textAnchor="middle" style={{ font }}>
                  {it.lines.map((ln, k) => (
                    <tspan key={k} x={x} dy={k ? 15 : 0}>
                      {ln.t}
                    </tspan>
                  ))}
                </text>
              </>
            )}
          </g>
        );
      })}
    </g>
  );
}

// Значок по виду: труд — книга с корешком, понятие — ромб, позиция — треугольник,
// аргумент — квадрат со стрелкой.
export function WorkIcon({ kind, x, iy, cy }: { kind: string; x: number; iy: number; cy: number }) {
  if (kind === "work")
    return (
      <>
        <rect className="map-work__mark" x={x - 8} y={iy} width={16} height={20} rx={1.5} />
        <rect className="map-work__spine" x={x - 8} y={iy} width={4} height={20} rx={1.2} />
      </>
    );
  if (kind === "position") return <path className="map-work__mark" d={`M${x} ${cy - 9} L${x + 9} ${cy + 7} L${x - 9} ${cy + 7} Z`} />;
  if (kind === "argument")
    return (
      <path
        className="map-work__mark"
        d={`M${x - 8} ${cy - 8} H${x + 8} V${cy + 8} H${x - 8} Z M${x - 4} ${cy} H${x + 4} M${x + 1} ${cy - 3} L${x + 4} ${cy} L${x + 1} ${cy + 3}`}
      />
    );
  return (
    <>
      <path className="map-work__mark" d={`M${x} ${cy - 9} L${x + 9} ${cy} L${x} ${cy + 9} L${x - 9} ${cy} Z`} />
      <circle className="map-work__spine" cx={x} cy={cy} r={1.8} />
    </>
  );
}

/* ---------- ось ---------- */

function Axis({ L }: { L: MapLayout }) {
  const ay = L.axisY;
  return (
    <g className="map-axis">
      <line className="map-axis__line" x1={L.scale.left - 6} x2={L.scale.right} y1={ay} y2={ay} />
      {L.scale.ticks.map((y) => {
        const x = r1(L.scale.x(y));
        return (
          <g key={y}>
            <line className="map-axis__line" x1={x} x2={x} y1={ay} y2={ay + 6} />
            <text className="map-axis__year" x={x} y={ay + 24} textAnchor="middle" style={{ font: L.fonts.axisYear }}>
              {y}
            </text>
          </g>
        );
      })}
    </g>
  );
}
