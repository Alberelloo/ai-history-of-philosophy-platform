import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import { useT } from "../../i18n";
import { mapFonts, type Measure } from "../layout";
import type { GeoLayer } from "./api";
import { LAND } from "./land";
import {
  arcPath,
  canvasPath,
  centerAttr,
  centerOn,
  degreesPerPixel,
  fmt,
  GRATICULE,
  initialView,
  interpolateCenter,
  isNear,
  projector,
  rotateBy,
  STEP,
  STEP_SHIFT,
  zoomBy,
  type Frame,
  type Projector,
  type View,
} from "./projection";
import type { GlobeRoles } from "./selection";
import { markRadius, MAX_LABELS, opacity, type Scene, type ScenePlace } from "./timeline";

// Вид «Глобус» карты раздела (openspec/changes/add-geo-timeline): ортографическая проекция
// d3-geo. Основа — тень, море, сетка 15°, суша Natural Earth — на canvas 2D (вариант Б по
// замеру 5.6); поверх — SVG с объёмом, дугами влияний, отметками мест, подписями и латунным
// ободом. Ленивый фрагмент: грузится только при открытии вида (MapPage).
//
// Движение — только по действию читателя: перетаскивание (короткая инерция), колесо,
// клавиши, поворот к месту из списка (не дольше FOCUS_MS). При уменьшенном движении повороты
// и приближение — сразу. Кадры — requestAnimationFrame, время — performance.now (без Date).
// Отметки дальнего полушария остаются в DOM с data-hidden="true" и не рисуются.
// SVG-фильтров нет: объём — статический радиальный градиент и обод.

const FOCUS_MS = 600;
const INERTIA_MS = 700;
const DRAG_THRESHOLD = 4; // px: меньше — щелчок
const WHEEL_STEP = 100; // px колеса на шаг приближения
const RIM = 16; // поле под обод и деления вокруг круга глобуса
const LABEL_FONT = mapFonts(false).workTitle;
const LABEL_GAP = 4;
const DRAG_PRECISION = 2.5; // px: точность передискретизации путей во время перетаскивания

type Props = {
  width: number;
  height: number;
  layer: GeoLayer | null;
  status: "loading" | "ok" | "error";
  scene: Scene | null;
  roles: GlobeRoles;
  year: number;
  summary: string;
  measure: Measure;
  fontsVersion: number; // шрифты загружены — подписи меряются заново
  reduced: boolean;
  focus: { lat: number; lon: number; nonce: number } | null;
  nearest: number | null;
  onSelectPlace: (id: string | null) => void;
  onYearStep: (delta: number) => void;
  onTogglePlay: () => void;
  onRetry: () => void;
  onToChrono: () => void;
  onNearest: () => void;
};

type Label = { id: string; x: number; y: number; w: number; text: string; anchor: "start" | "end" | "middle" };
type Rect = { x0: number; y0: number; x1: number; y1: number };
const overlaps = (a: Rect, b: Rect) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;

// Подписи: не больше MAX_LABELS, у кого больше людей; жадно, без наложений друг на друга
// и на отметки, внутри кадра. Ширина — тем же измерителем, что у карты (measure.ts).
// Вертикальные метрики шрифта подписи — те же, что у прямоугольника текста в браузере
// (fontBoundingBox*); без canvas — с запасом от кегля.
let metricsCanvas: CanvasRenderingContext2D | null | undefined;
function labelMetrics(): { ascent: number; descent: number } {
  if (metricsCanvas === undefined) metricsCanvas = typeof document !== "undefined" ? document.createElement("canvas").getContext("2d") : null;
  const c = metricsCanvas;
  if (c) {
    c.font = LABEL_FONT;
    const m = c.measureText("Ag");
    if (m.fontBoundingBoxAscent) return { ascent: m.fontBoundingBoxAscent, descent: m.fontBoundingBoxDescent };
  }
  return { ascent: 15, descent: 5 };
}
const LABEL_PAD = 1.5; // px вокруг прямоугольника подписи

function layoutLabels(points: { p: ScenePlace; x: number; y: number; r: number }[], measure: Measure, w: number, h: number): Label[] {
  const { ascent, descent } = labelMetrics();
  const placed: Rect[] = [];
  const marks: Rect[] = points.map(({ x, y, r }) => ({ x0: x - r, y0: y - r, x1: x + r, y1: y + r }));
  const out: Label[] = [];
  const order = [...points].sort((a, b) => b.p.people.length - a.p.people.length || (a.p.id < b.p.id ? -1 : 1));
  for (const { p, x, y, r } of order) {
    if (out.length >= MAX_LABELS) break;
    const tw = measure(p.label, LABEL_FONT);
    const options: Label[] = [
      { id: p.id, x: x + r + LABEL_GAP, y: y + 4.5, w: tw, text: p.label, anchor: "start" },
      { id: p.id, x: x - r - LABEL_GAP, y: y + 4.5, w: tw, text: p.label, anchor: "end" },
      { id: p.id, x, y: y - r - LABEL_GAP - descent, w: tw, text: p.label, anchor: "middle" },
      { id: p.id, x, y: y + r + LABEL_GAP + ascent, w: tw, text: p.label, anchor: "middle" },
    ];
    for (const o of options) {
      const x0 = o.anchor === "start" ? o.x : o.anchor === "end" ? o.x - tw : o.x - tw / 2;
      const rect = { x0: x0 - LABEL_PAD, y0: o.y - ascent - LABEL_PAD, x1: x0 + tw + LABEL_PAD, y1: o.y + descent + LABEL_PAD };
      if (rect.x0 < 2 || rect.x1 > w - 2 || rect.y0 < 2 || rect.y1 > h - 2) continue;
      if (placed.some((q) => overlaps(q, rect))) continue;
      if (marks.some((m, i) => points[i].p.id !== p.id && overlaps(m, rect))) continue;
      placed.push(rect);
      out.push(o);
      break;
    }
  }
  return out;
}

// Стрелка к ученику: треугольник у конца видимой части дуги.
function arrowAt(pr: Projector, from: { lat: number; lon: number }, to: { lat: number; lon: number }): string | null {
  const end = pr.projection([to.lon, to.lat]);
  if (!end || !isNear({ lon: -pr.projection.rotate()[0], lat: -pr.projection.rotate()[1], zoom: 1 }, to)) return null;
  // Точка чуть раньше конца по большому кругу — направление стрелки.
  const k = 0.9;
  const lon = from.lon + (to.lon - from.lon) * k;
  const lat = from.lat + (to.lat - from.lat) * k;
  const before = pr.projection([lon, lat]);
  if (!before) return null;
  const dx = end[0] - before[0];
  const dy = end[1] - before[1];
  const len = Math.hypot(dx, dy);
  if (len < 0.5) return null;
  const ux = dx / len;
  const uy = dy / len;
  const tipX = end[0] - ux * 5; // не залезать на отметку
  const tipY = end[1] - uy * 5;
  const s = 5;
  return `M${(tipX).toFixed(1)},${(tipY).toFixed(1)}L${(tipX - ux * s - uy * s * 0.55).toFixed(1)},${(tipY - uy * s + ux * s * 0.55).toFixed(1)}L${(tipX - ux * s + uy * s * 0.55).toFixed(1)},${(tipY - uy * s - ux * s * 0.55).toFixed(1)}Z`;
}

export default function GlobeView(props: Props) {
  const { width, height, layer, status, scene, roles, measure, reduced } = props;
  const t = useT();
  const svg = useRef<SVGSVGElement>(null);
  const frame: Frame = useMemo(() => {
    const radius = Math.max(40, Math.min(width, height) / 2 - RIM);
    return { cx: width / 2, cy: height / 2, radius };
  }, [width, height]);

  // Исходный вид — из видимых мест первого показа слоя; «0» возвращает к нему.
  const home = useRef<View | null>(null);
  const homeLayer = useRef<GeoLayer | null>(null);
  if (scene && layer && homeLayer.current !== layer) {
    homeLayer.current = layer;
    home.current = initialView(scene.places);
  }
  const [view, setView] = useState<View>(() => home.current ?? initialView([]));
  const viewRef = useRef(view);
  viewRef.current = view;
  const appliedHome = useRef<View | null>(null);
  useEffect(() => {
    if (home.current && appliedHome.current !== home.current) {
      appliedHome.current = home.current;
      setView(home.current);
    }
  });

  // Анимации (поворот к месту, инерция) — одна за раз; любое действие читателя её снимает.
  // Пока глобус тянут (и по инерции), путь грубее, подписи не раскладываются: кадр легче.
  const [moving, setMoving] = useState(false);
  const anim = useRef(0);
  const cancel = useCallback(() => {
    if (anim.current) cancelAnimationFrame(anim.current);
    anim.current = 0;
    setMoving(false);
  }, []);
  useEffect(() => cancel, [cancel]);

  const apply = useCallback(
    (next: View) => {
      cancel();
      setView(next);
    },
    [cancel],
  );

  // Поворот к месту из списка: плавно не дольше FOCUS_MS, при уменьшенном движении — сразу.
  const focusNonce = props.focus?.nonce;
  useEffect(() => {
    const f = props.focus;
    if (!f) return;
    const target = centerOn(viewRef.current, f);
    if (reduced) return apply(target);
    cancel();
    const lerp = interpolateCenter(viewRef.current, target);
    const t0 = performance.now();
    const tick = () => {
      const k = Math.min(1, (performance.now() - t0) / FOCUS_MS);
      const e = k < 0.5 ? 4 * k * k * k : 1 - (-2 * k + 2) ** 3 / 2;
      setView(k >= 1 ? target : lerp(e));
      anim.current = k >= 1 ? 0 : requestAnimationFrame(tick);
    };
    anim.current = requestAnimationFrame(tick);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusNonce]);

  // Колесо — приближение; слушатель не пассивный: страница под глобусом не прокручивается.
  useEffect(() => {
    const el = svg.current;
    if (!el) return;
    let acc = 0;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      acc += e.deltaY;
      const steps = acc <= -WHEEL_STEP / 2 ? 1 : acc >= WHEEL_STEP / 2 ? -1 : 0;
      if (!steps) return;
      acc = 0;
      apply(zoomBy(viewRef.current, steps));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [apply]);

  // Перетаскивание: поворот по пикселям, кадр — не чаще раза за requestAnimationFrame.
  const drag = useRef<{ id: number; x: number; y: number; start: View; moved: boolean; samples: [number, number, number][] } | null>(null);
  const pending = useRef<View | null>(null);
  const pr = useMemo(() => projector(view, frame, moving ? DRAG_PRECISION : undefined), [view, frame, moving]);
  const onPointerDown = (e: ReactPointerEvent<SVGSVGElement>) => {
    if (e.button !== 0) return;
    cancel();
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, start: viewRef.current, moved: false, samples: [[e.clientX, e.clientY, performance.now()]] };
  };
  const onPointerMove = (e: ReactPointerEvent<SVGSVGElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
    if (!d.moved) {
      d.moved = true;
      setMoving(true);
      svg.current?.setPointerCapture?.(e.pointerId);
    }
    d.samples.push([e.clientX, e.clientY, performance.now()]);
    if (d.samples.length > 5) d.samples.shift();
    const k = degreesPerPixel(projector(d.start, frame));
    pending.current = rotateBy(d.start, -dx * k, dy * k);
    if (!anim.current)
      anim.current = requestAnimationFrame(() => {
        anim.current = 0;
        if (pending.current) setView(pending.current);
        pending.current = null;
      });
  };
  const onPointerUp = (e: ReactPointerEvent<SVGSVGElement>) => {
    const d = drag.current;
    drag.current = null;
    if (!d || d.id !== e.pointerId) return;
    if (!d.moved) {
      // Щелчок: по отметке — выбор места, по полю — снять выбор.
      const mark = (e.target as Element).closest?.("[data-geo-place]");
      props.onSelectPlace(mark ? mark.getAttribute("data-geo-place") : null);
      return;
    }
    if (pending.current) {
      setView(pending.current);
      viewRef.current = pending.current;
      pending.current = null;
    }
    const still = () => setMoving(false);
    if (reduced) return still(); // без инерции
    const [a, b] = [d.samples[0], d.samples[d.samples.length - 1]];
    const dt = b[2] - a[2];
    if (dt <= 0 || dt > 120) return still();
    const k = degreesPerPixel(projector(viewRef.current, frame));
    let vLon = (-(b[0] - a[0]) * k) / dt; // градусов в мс
    let vLat = ((b[1] - a[1]) * k) / dt;
    if (Math.hypot(vLon, vLat) < 0.01) return still();
    const t0 = performance.now();
    let last = t0;
    cancel();
    setMoving(true);
    const tick = () => {
      const now = performance.now();
      const step = now - last;
      last = now;
      const decay = Math.pow(0.9, step / 16);
      vLon *= decay;
      vLat *= decay;
      const next = rotateBy(viewRef.current, vLon * step, vLat * step);
      viewRef.current = next;
      setView(next);
      anim.current = now - t0 < INERTIA_MS && Math.hypot(vLon, vLat) > 0.002 ? requestAnimationFrame(tick) : 0;
      if (!anim.current) still();
    };
    anim.current = requestAnimationFrame(tick);
  };

  const onKeyDown = (e: KeyboardEvent<SVGSVGElement>) => {
    const step = e.shiftKey ? STEP_SHIFT : STEP;
    const v = viewRef.current;
    let next: View | null = null;
    if (e.key === "ArrowRight") next = rotateBy(v, step, 0);
    else if (e.key === "ArrowLeft") next = rotateBy(v, -step, 0);
    else if (e.key === "ArrowUp") next = rotateBy(v, 0, step);
    else if (e.key === "ArrowDown") next = rotateBy(v, 0, -step);
    else if (e.key === "+" || e.key === "=") next = zoomBy(v, 1);
    else if (e.key === "-" || e.key === "_" || e.key === "−") next = zoomBy(v, -1);
    else if (e.key === "0") next = home.current ?? initialView([]);
    else if (e.key === "PageUp") props.onYearStep(10);
    else if (e.key === "PageDown") props.onYearStep(-10);
    else if (e.key === "]") props.onYearStep(1);
    else if (e.key === "[") props.onYearStep(-1);
    else if (e.key === " ") props.onTogglePlay();
    else return;
    e.preventDefault();
    if (next) apply(next);
  };

  const [keysOpen, setKeysOpen] = useState(false);

  // --- сцена ---
  // Основа — тень, море, сетка, суша — на canvas (вариант Б design: замер 5.6). Цвета —
  // токены, прочитанные из CSS (getComputedStyle), литералов нет.
  const base = useRef<HTMLCanvasElement>(null);
  useLayoutEffect(() => {
    const c = base.current;
    const ctx = c?.getContext("2d");
    if (!c || !ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const w = Math.round(width * dpr);
    const h = Math.round(height * dpr);
    if (c.width !== w || c.height !== h) {
      c.width = w;
      c.height = h;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const css = getComputedStyle(c);
    const color = (name: string) => css.getPropertyValue(name).trim();
    const R0 = pr.scale;
    // Тень под глобусом: эллипс с радиальным затуханием.
    ctx.save();
    ctx.translate(frame.cx + R0 * 0.04, frame.cy + R0 * 0.98);
    ctx.scale(1, 0.09);
    const g = ctx.createRadialGradient(0, 0, 0, 0, 0, R0 * 0.8);
    g.addColorStop(0, color("--globe-coast"));
    g.addColorStop(1, "transparent");
    ctx.globalAlpha = 0.22;
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(0, 0, R0 * 0.8, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
    const path = canvasPath(pr, ctx);
    ctx.beginPath();
    path({ type: "Sphere" });
    ctx.fillStyle = color("--globe-sea");
    ctx.fill();
    ctx.beginPath();
    path(GRATICULE);
    ctx.strokeStyle = color("--globe-graticule");
    ctx.lineWidth = 0.8;
    ctx.lineCap = "round";
    ctx.setLineDash([0.6, 3.2]);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    path(LAND);
    ctx.fillStyle = color("--globe-land");
    ctx.fill();
    ctx.strokeStyle = color("--globe-coast");
    ctx.lineWidth = 0.75;
    ctx.lineJoin = "round";
    ctx.stroke();
    c.dataset.drawn = "true";
  }, [pr, frame, width, height]);
  const sphere = pr.path({ type: "Sphere" }) ?? "";
  const R = pr.scale;
  const places = scene?.places ?? [];
  const points = places.map((p) => {
    const xy = pr.projection([p.lon, p.lat]);
    const near = isNear(view, p);
    return { p, x: xy ? xy[0] : 0, y: xy ? xy[1] : 0, r: markRadius(p.people.length), near };
  });
  const shown = points.filter((q) => q.near && q.x >= -20 && q.x <= width + 20 && q.y >= -20 && q.y <= height + 20);
  const labels = moving ? [] : layoutLabels(shown, measure, width, height);
  const links = scene?.links ?? [];
  const trail =
    roles.trail.length > 1
      ? pr.path({ type: "LineString", coordinates: roles.trail.map((g) => [g.lon, g.lat]) })
      : null;
  const dim = roles.active;
  const busy = status === "loading";
  const empty = status === "ok" && (layer?.places.length ?? 0) === 0;
  const nobody = status === "ok" && !empty && places.length === 0;

  // Деления латунного обода — через 10°, крупные через 30° (неподвижны, как меридианное кольцо).
  const ticks = useMemo(() => {
    const out: string[] = [];
    const r0 = frame.radius * view.zoom + 5;
    for (let a = 0; a < 360; a += 10) {
      const rad = (a * Math.PI) / 180;
      const len = a % 30 === 0 ? 6 : 3;
      const x1 = frame.cx + Math.cos(rad) * r0;
      const y1 = frame.cy + Math.sin(rad) * r0;
      const x2 = frame.cx + Math.cos(rad) * (r0 + len);
      const y2 = frame.cy + Math.sin(rad) * (r0 + len);
      out.push(`M${x1.toFixed(1)},${y1.toFixed(1)}L${x2.toFixed(1)},${y2.toFixed(1)}`);
    }
    return out.join("");
  }, [frame, view.zoom]);

  return (
    <div className="geo-stage" style={{ width, height }}>
      <canvas ref={base} className="geo-land" data-geo-land="" style={{ width, height }} aria-hidden="true" />
      <svg
        ref={svg}
        className="geo-globe"
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="application"
        aria-roledescription={t.geo.roledescription}
        aria-label={props.summary}
        aria-describedby="geo-keys-hint"
        aria-busy={busy}
        tabIndex={0}
        data-year={props.year}
        data-center={centerAttr(view)}
        data-zoom={fmt(view.zoom)}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => (drag.current = null)}
        onKeyDown={onKeyDown}
      >
        <defs>
          <radialGradient id="geo-shade" cx="38%" cy="32%" r="72%">
            <stop className="geo-shade__light" offset="0%" />
            <stop className="geo-shade__mid" offset="55%" />
            <stop className="geo-shade__dark" offset="100%" />
          </radialGradient>
        </defs>
        <path className="geo-shade" d={sphere} aria-hidden="true" />
        <g className="geo-links" aria-hidden="true">
          {trail && <path className="geo-trail map-role-self" d={trail} />}
          {links.map((l) => {
            const d = arcPath(pr, l.from, l.to);
            const role = roles.links.get(l.id);
            const arrow = d ? arrowAt(pr, l.from, l.to) : null;
            return (
              <g
                key={l.id}
                className={["geo-link", role ? `is-on map-role-${role}` : "", l.link.generated ? "is-generated" : ""].join(" ").trim()}
                data-geo-link={l.id}
                data-status={l.link.status}
                data-generated={l.link.generated ? "true" : "false"}
                data-age={l.age}
                data-role={role}
                data-dim={dim && !role ? "true" : undefined}
                style={{ opacity: opacity(l.age) }}
              >
                {d && <path className="geo-link__arc" d={d} />}
                {arrow && <path className="geo-link__arrow" d={arrow} />}
              </g>
            );
          })}
        </g>
        <g className="geo-places" aria-hidden="true">
          {points.map(({ p, x, y, r, near }) => {
            const role = roles.places.get(p.id);
            const n = p.people.length;
            return (
              <g
                key={p.id}
                className={["geo-place", role ? `is-on map-role-${role}` : "", p.unverified ? "is-unverified" : "", n === 0 ? "is-event" : ""]
                  .join(" ")
                  .trim()}
                data-geo-place={p.id}
                data-people={n}
                data-age={p.age}
                data-unverified={p.unverified ? "true" : "false"}
                data-hidden={near ? "false" : "true"}
                data-role={role}
                data-dim={dim && !role ? "true" : undefined}
                transform={`translate(${x.toFixed(1)},${y.toFixed(1)})`}
                style={{ opacity: opacity(p.age) }}
              >
                <circle className="geo-place__hit" r={Math.max(r + 4, 9)} />
                <circle className="geo-place__dot" r={r} />
                {n >= 2 && (
                  <text className="geo-place__count" y={3.5}>
                    {n}
                  </text>
                )}
              </g>
            );
          })}
        </g>
        <g className="geo-labels" aria-hidden="true">
          {labels.map((l) => (
            <text
              key={l.id}
              className={roles.places.get(l.id) ? `geo-label is-on map-role-${roles.places.get(l.id)}` : dim ? "geo-label is-dim" : "geo-label"}
              data-geo-label={l.id}
              x={l.x}
              y={l.y}
              textAnchor={l.anchor}
              style={{ font: LABEL_FONT }}
            >
              {l.text}
            </text>
          ))}
        </g>
        <circle className="geo-rim" cx={frame.cx} cy={frame.cy} r={R + 2.5} aria-hidden="true" />
        <circle className="geo-rim__inner" cx={frame.cx} cy={frame.cy} r={R} aria-hidden="true" />
        <path className="geo-rim__ticks" d={ticks} aria-hidden="true" />
      </svg>

      <p className="geo-coast">{t.geo.coast}</p>
      <div className="geo-keys">
        <button type="button" className="pg-btn pg-btn--ghost pg-btn--sm" aria-expanded={keysOpen} aria-controls="geo-keys-hint" onClick={() => setKeysOpen((o) => !o)}>
          {t.geo.keys}
        </button>
        <p id="geo-keys-hint" className="geo-keys__hint" hidden={!keysOpen}>
          {t.geo.keysHint}
        </p>
      </div>
      {busy && (
        <p className="geo-state geo-state--loading" role="status">
          {t.geo.loading}
        </p>
      )}
      {status === "error" && (
        <div className="geo-state pg-notice pg-notice--danger pg-notice--stacked" role="alert">
          <div>
            <strong>{t.geo.error}</strong>
            <p>{t.geo.errorHint}</p>
          </div>
          <button type="button" className="pg-btn pg-btn--secondary pg-btn--sm" onClick={props.onRetry}>
            {t.geo.retry}
          </button>
        </div>
      )}
      {empty && (
        <div className="geo-state">
          <strong>{t.geo.empty}</strong>
          <p>{t.geo.emptyHint}</p>
          <button type="button" className="pg-btn pg-btn--secondary pg-btn--sm" onClick={props.onToChrono}>
            {t.geo.toChrono}
          </button>
        </div>
      )}
      {nobody && (
        <div className="geo-state" role="status">
          <strong>{t.geo.nobody(props.year)}</strong>
          {props.nearest != null && (
            <button type="button" className="pg-btn pg-btn--secondary pg-btn--sm" onClick={props.onNearest}>
              {t.geo.nearest}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
