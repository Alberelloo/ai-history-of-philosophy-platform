import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { useT } from "../i18n";
import { Icon, Seg } from "../ui";
import { DEFAULT_OPTIONS, timeScale } from "./layout";
import type { MapPerson } from "./types";

// Обзорная шкала под осью: весь период раздела, плотность жизней и рамка окна времени.
// Рамку и её края можно тянуть мышью и двигать стрелками; окно — это фильтр «Время»
// (from/to); при узком окне карта приближается. Окно на весь период — фильтра нет.

export const OVERVIEW_HEIGHT = 46;
// Ряд управления годом под шкалой в виде «Глобус»: «Играть/Пауза», год и эпоха, скорость.
export const YEAR_BAR_HEIGHT = 38;

// Год глобуса (geo-timeline): точка на шкале и ряд управления. Без неё шкала — как на
// хронологии. Год всегда внутри окна: зажим — у страницы (clampYear).
export type YearControl = {
  value: number;
  era: string | null;
  playing: boolean;
  speed: number;
  speeds: readonly number[];
  onChange: (year: number) => void;
  onToggle: () => void;
  onSpeed: (speed: number) => void;
};
const MIN_SPAN = 5;

type Drag = { kind: "from" | "to" | "move" | "year"; x0: number; from: number; to: number };

export function Overview({
  range,
  win,
  people,
  width,
  onChange,
  year,
}: {
  range: [number, number];
  win: [number, number];
  people: MapPerson[];
  width: number;
  onChange: (from: number | undefined, to: number | undefined) => void;
  year?: YearControl;
}) {
  const t = useT();
  const svg = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  // Пока тянут — рамка рисуется по локальному окну, фильтр обновляется с каждым шагом.
  const [A0, A1] = range;
  const s = timeScale(range, DEFAULT_OPTIONS.plotLeft, width - DEFAULT_OPTIONS.plotRightPad);
  const [from, to] = win;
  const oy = 16;

  const commit = (f: number, e: number) => {
    let a = Math.round(Math.max(A0, Math.min(f, A1 - MIN_SPAN)));
    let b = Math.round(Math.min(A1, Math.max(e, a + MIN_SPAN)));
    if (b - a < MIN_SPAN) a = b - MIN_SPAN;
    onChange(a <= A0 ? undefined : a, b >= A1 ? undefined : b);
  };

  useEffect(() => {
    if (!drag) return;
    const k = (s.right - s.left) / Math.max(1, A1 - A0);
    const move = (e: globalThis.PointerEvent) => {
      const dy = (e.clientX - drag.x0) / k;
      if (drag.kind === "year") return year?.onChange(Math.round(s.year(e.clientX - (svg.current?.getBoundingClientRect().left ?? 0))));
      if (drag.kind === "from") commit(Math.min(drag.from + dy, drag.to - MIN_SPAN), drag.to);
      else if (drag.kind === "to") commit(drag.from, Math.max(drag.to + dy, drag.from + MIN_SPAN));
      else {
        const span = drag.to - drag.from;
        const f = Math.max(A0, Math.min(A1 - span, drag.from + dy));
        commit(f, f + span);
      }
    };
    const up = () => setDrag(null);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drag, width, A0, A1]);

  const start = (kind: Drag["kind"]) => (e: PointerEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDrag({ kind, x0: e.clientX, from, to });
  };

  // Клавиши: стрелки — год, Shift — десять лет, PageUp/PageDown — 25, Home/End — край периода.
  const key = (kind: Drag["kind"]) => (e: KeyboardEvent) => {
    const step = e.key === "PageUp" || e.key === "PageDown" ? 25 : e.shiftKey ? 10 : 1;
    let d = 0;
    if (e.key === "ArrowLeft" || e.key === "ArrowDown" || e.key === "PageDown") d = -step;
    else if (e.key === "ArrowRight" || e.key === "ArrowUp" || e.key === "PageUp") d = step;
    else if (e.key === "Home") d = -(A1 - A0);
    else if (e.key === "End") d = A1 - A0;
    else return;
    e.preventDefault();
    if (kind === "from") commit(Math.min(from + d, to - MIN_SPAN), to);
    else if (kind === "to") commit(from, Math.max(to + d, from + MIN_SPAN));
    else {
      const span = to - from;
      const f = Math.max(A0, Math.min(A1 - span, from + d));
      commit(f, f + span);
    }
  };

  // Год глобуса: щелчок по шкале — год под курсором и перетаскивание точки.
  const yearDown = (e: PointerEvent) => {
    if (!year || e.button !== 0) return;
    const left = svg.current?.getBoundingClientRect().left ?? 0;
    e.preventDefault();
    year.onChange(Math.round(s.year(e.clientX - left)));
    setDrag({ kind: "year", x0: e.clientX, from, to });
  };
  // Клавиши точки года: PageUp/PageDown — ±10, [ ] и стрелки — ±1, Home/End — края окна,
  // пробел — играть или пауза.
  const yearKey = (e: KeyboardEvent) => {
    if (!year) return;
    const v = year.value;
    let next: number | null = null;
    if (e.key === "PageUp") next = v + 10;
    else if (e.key === "PageDown") next = v - 10;
    else if (e.key === "]" || e.key === "ArrowRight" || e.key === "ArrowUp") next = v + 1;
    else if (e.key === "[" || e.key === "ArrowLeft" || e.key === "ArrowDown") next = v - 1;
    else if (e.key === "Home") next = from;
    else if (e.key === "End") next = to;
    else if (e.key === " ") {
      e.preventDefault();
      return year.onToggle();
    } else return;
    e.preventDefault();
    year.onChange(next);
  };
  const yearText = year ? (year.era ? `${year.value} · ${year.era}` : String(year.value)) : "";

  const w0 = s.x(from);
  const w1 = s.x(to);
  const step = s.step < 25 ? 25 : s.step;
  const ticks: number[] = [];
  for (let y = Math.ceil(A0 / step) * step; y <= A1; y += step) ticks.push(y);

  const scale = (
    <svg
      ref={svg}
      className={drag ? "map-overview is-dragging" : "map-overview"}
      width={width}
      height={OVERVIEW_HEIGHT}
      viewBox={`0 0 ${width} ${OVERVIEW_HEIGHT}`}
      role="group"
      aria-label={t.map.overview}
      onPointerDown={year ? yearDown : undefined}
    >
      <text className="map-overview__label" x={s.left - 12} y={oy + 4} textAnchor="end">
        {t.map.overviewLabel}
      </text>
      <line className="map-overview__rail" x1={s.left} x2={s.right} y1={oy} y2={oy} />
      {ticks.map((y) => (
        <g key={y}>
          <line className="map-overview__rail" x1={s.x(y)} x2={s.x(y)} y1={oy - 3} y2={oy + 3} />
          <text className="map-overview__year" x={s.x(y)} y={oy + 17} textAnchor="middle">
            {y}
          </text>
        </g>
      ))}
      {people.map((p) => (
        <line
          key={p.id}
          className="map-overview__life"
          x1={s.x(Math.max(A0, p.birth))}
          x2={s.x(Math.min(A1, p.death))}
          y1={oy - 1.5}
          y2={oy - 1.5}
        />
      ))}
      <rect
        className="map-overview__window"
        x={w0}
        y={oy - 8}
        width={Math.max(2, w1 - w0)}
        height={16}
        rx={3}
        tabIndex={0}
        role="slider"
        aria-label={t.map.windowMove}
        aria-valuemin={A0}
        aria-valuemax={A1}
        aria-valuenow={from}
        aria-valuetext={`${from}–${to}`}
        onPointerDown={start("move")}
        onKeyDown={key("move")}
      />
      {(["from", "to"] as const).map((k) => {
        const x = k === "from" ? w0 : w1;
        return (
          <rect
            key={k}
            className="map-overview__handle"
            x={x - 4}
            y={oy - 11}
            width={8}
            height={22}
            rx={2}
            tabIndex={0}
            role="slider"
            aria-label={k === "from" ? t.map.windowFrom : t.map.windowTo}
            aria-valuemin={A0}
            aria-valuemax={A1}
            aria-valuenow={k === "from" ? from : to}
            onPointerDown={start(k)}
            onKeyDown={key(k)}
          >
            <title>{k === "from" ? from : to}</title>
          </rect>
        );
      })}
      {year && (
        <g className="map-overview__year-mark" transform={`translate(${s.x(year.value).toFixed(1)},${oy})`}>
          <line className="map-overview__year-stem" y1={-12} y2={12} />
          <circle
            className="map-overview__year-dot"
            r={6}
            tabIndex={0}
            role="slider"
            aria-label={t.geo.yearSlider}
            aria-valuemin={from}
            aria-valuemax={to}
            aria-valuenow={year.value}
            aria-valuetext={yearText}
            data-year={year.value}
            onPointerDown={(e) => {
              e.stopPropagation();
              yearDown(e);
            }}
            onKeyDown={yearKey}
          />
        </g>
      )}
    </svg>
  );
  if (!year) return scale;
  return (
    <>
      {scale}
      <div className="geo-yearbar" style={{ height: YEAR_BAR_HEIGHT }}>
        <button type="button" className="pg-btn pg-btn--secondary pg-btn--sm geo-yearbar__play" aria-pressed={year.playing} onClick={year.onToggle}>
          <Icon name={year.playing ? "pause" : "play"} small />
          {year.playing ? t.geo.pause : t.geo.play}
        </button>
        <output className="geo-yearbar__year" data-year={year.value} aria-label={t.geo.yearSlider}>
          {yearText}
        </output>
        <Seg<string>
          className="geo-yearbar__speed"
          label={t.geo.speed}
          items={year.speeds.map((v) => ({ value: String(v), label: t.geo.speedValue(v) }))}
          value={String(year.speed)}
          onChange={(v) => year.onSpeed(Number(v))}
        />
      </div>
    </>
  );
}
