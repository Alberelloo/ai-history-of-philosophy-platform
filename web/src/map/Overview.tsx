import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { useEvent } from "../hooks/useEvent";
import { useT } from "../i18n";
import { DEFAULT_OPTIONS, timeScale } from "./layout";
import type { MapPerson } from "./types";

// Обзорная шкала под осью: весь период раздела, плотность жизней и рамка окна времени.
// Рамку и её края можно тянуть мышью и двигать стрелками; окно — это фильтр «Время»
// (from/to); при узком окне карта приближается. Окно на весь период — фильтра нет.

export const OVERVIEW_HEIGHT = 46;
const MIN_SPAN = 5;

type Drag = { kind: "from" | "to" | "move"; x0: number; from: number; to: number };

export function Overview({
  range,
  win,
  people,
  width,
  onChange,
}: {
  range: [number, number];
  win: [number, number];
  people: MapPerson[];
  width: number;
  onChange: (from: number | undefined, to: number | undefined) => void;
}) {
  const t = useT();
  const svg = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  // Пока тянут — рамка рисуется по локальному окну, фильтр обновляется с каждым шагом.
  const [A0, A1] = range;
  const s = timeScale(range, DEFAULT_OPTIONS.plotLeft, width - DEFAULT_OPTIONS.plotRightPad);
  const [from, to] = win;
  const { left, right } = s;
  const oy = 16;

  const commit = useEvent((f: number, e: number) => {
    let a = Math.round(Math.max(A0, Math.min(f, A1 - MIN_SPAN)));
    const b = Math.round(Math.min(A1, Math.max(e, a + MIN_SPAN)));
    if (b - a < MIN_SPAN) a = b - MIN_SPAN;
    onChange(a <= A0 ? undefined : a, b >= A1 ? undefined : b);
  });

  useEffect(() => {
    if (!drag) return;
    const k = (right - left) / Math.max(1, A1 - A0);
    const move = (e: globalThis.PointerEvent) => {
      const dy = (e.clientX - drag.x0) / k;
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
  }, [drag, left, right, A0, A1, commit]);

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

  const w0 = s.x(from);
  const w1 = s.x(to);
  const step = s.step < 25 ? 25 : s.step;
  const ticks: number[] = [];
  for (let y = Math.ceil(A0 / step) * step; y <= A1; y += step) ticks.push(y);

  return (
    <svg
      ref={svg}
      className={drag ? "map-overview is-dragging" : "map-overview"}
      width={width}
      height={OVERVIEW_HEIGHT}
      viewBox={`0 0 ${width} ${OVERVIEW_HEIGHT}`}
      role="group"
      aria-label={t.map.overview}
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
    </svg>
  );
}
