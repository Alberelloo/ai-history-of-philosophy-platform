// Точные связи глобуса (rework-globe-political-map, «Точные связи»): кривая влияния между
// центрами маркеров учителя и ученика на экране и стрелка у маркера ученика. Без DOM и без d3.
//
// Кривая — квадратичная: контрольная точка — середина отрезка, сдвинутая влево от
// направления «учитель → ученик» на четверть длины; если она вне круга глобуса или кадра —
// придвигается по прямой к середине (середина всегда внутри: оба центра внутри). Кривая
// лежит в треугольнике концов и контрольной точки, поэтому целиком в круге и в кадре.
// Концы пути — ровно центры маркеров (те же числа, что data-x/data-y).

import { inCircle, round2, type Circle, type Frame } from "./layout";

export const ARROW = 6; // длина стрелки, px
const WING = 0.55;

type P = [number, number];

const bez = (a: P, c: P, b: P, t: number): P => {
  const u = 1 - t;
  return [u * u * a[0] + 2 * u * t * c[0] + t * t * b[0], u * u * a[1] + 2 * u * t * c[1] + t * t * b[1]];
};
const tangent = (a: P, c: P, b: P, t: number): P => [2 * (1 - t) * (c[0] - a[0]) + 2 * t * (b[0] - c[0]), 2 * (1 - t) * (c[1] - a[1]) + 2 * t * (b[1] - c[1])];

const inside = (f: Frame, p: P) => inCircle(f, p[0], p[1]) && p[0] >= 0 && p[1] >= 0 && p[0] <= f.w && p[1] <= f.h;

export function control(a: P, b: P, f: Frame): P {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const mid: P = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  const want: P = [mid[0] + dy / 4, mid[1] - dx / 4]; // «влево» в экранных координатах (y вниз)
  if (inside(f, want)) return want;
  let lo = 0;
  let hi = 1;
  for (let i = 0; i < 30; i++) {
    const t = (lo + hi) / 2;
    if (inside(f, [mid[0] + (want[0] - mid[0]) * t, mid[1] + (want[1] - mid[1]) * t])) lo = t;
    else hi = t;
  }
  return [mid[0] + (want[0] - mid[0]) * lo, mid[1] + (want[1] - mid[1]) * lo];
}

export type Arc = { d: string; arrow: string; tip: P; ctrl: P };

const n = (x: number) => String(round2(x));

// null — маркеры совпадают или концы слишком близко для стрелки вне маркера.
export function arcBetween(from: Circle, to: Circle, f: Frame): Arc | null {
  const a: P = [from.x, from.y];
  const b: P = [to.x, to.y];
  const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
  if (len <= to.r + 0.5) return null;
  const c = control(a, b, f);
  // Вершина стрелки — последнее пересечение кривой с окружностью цели (поиск с конца).
  const outside = (t: number) => {
    const p = bez(a, c, b, t);
    return Math.hypot(p[0] - b[0], p[1] - b[1]) > to.r;
  };
  let t0 = 1;
  while (t0 > 0 && !outside(t0)) t0 -= 0.02;
  t0 = Math.max(0, t0);
  let lo = t0; // снаружи
  let hi = Math.min(1, t0 + 0.02); // внутри
  for (let i = 0; i < 40; i++) {
    const t = (lo + hi) / 2;
    if (outside(t)) lo = t;
    else hi = t;
  }
  const tip = bez(a, c, b, hi);
  const tg = tangent(a, c, b, hi);
  const tl = Math.hypot(tg[0], tg[1]) || 1;
  const ux = tg[0] / tl;
  const uy = tg[1] / tl;
  const bx = tip[0] - ux * ARROW;
  const by = tip[1] - uy * ARROW;
  const w = ARROW * WING;
  const arrow = `M${n(tip[0])},${n(tip[1])}L${n(bx - uy * w)},${n(by + ux * w)}L${n(bx + uy * w)},${n(by - ux * w)}Z`;
  const d = `M${n(a[0])},${n(a[1])}Q${n(c[0])},${n(c[1])} ${n(b[0])},${n(b[1])}`;
  return { d, arrow, tip, ctrl: c };
}
