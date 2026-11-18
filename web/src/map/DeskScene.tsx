import type { ReactNode } from "react";
import { useMedia } from "../SidePanel";

// Сцена карты (openspec/changes/synchro-map, «Сцена карты»): лист бумаги на столе философа.
// Стол, бювар, предметы вокруг листа и свет — декорация (aria-hidden); лист — children.
// Материалы — SVG-фильтры без растровых файлов (перенос из макета graph-f02-lenses/desk.js),
// все цвета — токены сцены (`--desk-*`, `--blotter`, `--sheet*`, `--lamp`, `--sel-*`).
// Предметы лежат только снаружи прямоугольника листа (поля стола и полоса под листом),
// поэтому не перекрывают ни лист, ни панель внутри него. На 1024–1279px их нет совсем.

const COMPACT_MEDIA = "(max-width: 1279px)";
const REDUCED_MOTION_MEDIA = "(prefers-reduced-motion: reduce)";

// Ссылки на фильтры и градиенты: сцена на странице одна, имена с префиксом.
const F = {
  wood: "pg-desk-wood",
  leather: "pg-desk-leather",
  paper: "pg-desk-paper",
  wax: "pg-desk-wax",
  brass: "pg-desk-brass",
  edge: "pg-desk-edge",
  gutter: "pg-desk-gutter",
  sheen: "pg-desk-sheen",
} as const;
const url = (id: string) => `url(#${id})`;
const tok = (name: string) => `var(--${name})`;

type Props = {
  /** Тема сцены поверх темы страницы; без неё — тема документа (атрибут или система). */
  theme?: "light" | "dark";
  /** Узкий десктоп: без предметов, лист на всю рабочую область. По умолчанию — по ширине окна. */
  compact?: boolean;
  /** Без анимации света и появления записок. По умолчанию — системная настройка. */
  reducedMotion?: boolean;
  /** Записки на столе под листом (DeskNotes). */
  notes?: ReactNode;
  /** Лист: шапка, карта и панель. */
  children: ReactNode;
};

export function DeskScene({ theme, compact, reducedMotion, notes, children }: Props) {
  const narrow = useMedia(COMPACT_MEDIA);
  const systemReduced = useMedia(REDUCED_MOTION_MEDIA);
  const isCompact = compact ?? narrow;
  const reduce = reducedMotion ?? systemReduced;
  return (
    <div
      className="desk-scene"
      data-theme={theme}
      data-compact={isCompact ? "" : undefined}
      data-motion={reduce ? "reduce" : undefined}
    >
      <DeskDefs />
      <svg className="desk-wood" aria-hidden="true" preserveAspectRatio="none">
        <rect width="100%" height="100%" fill={tok("desk-wood")} filter={url(F.wood)} />
      </svg>
      {/* свет и виньетка: над столом и предметами, под листом и записками */}
      <div className="desk-light" aria-hidden="true" />
      <div className="desk-stage">
        {/* рамка = прямоугольник листа; предметы привязаны к её краям снаружи */}
        <div className="desk-frame">
          <div className="desk-blotter" aria-hidden="true">
            <svg preserveAspectRatio="none">
              <rect width="100%" height="100%" rx="6" fill={tok("blotter")} filter={url(F.leather)} />
            </svg>
          </div>
          {!isCompact && <DeskProps />}
          <div className="desk-under desk-under-2" aria-hidden="true">
            <PaperFill />
          </div>
          <div className="desk-under desk-under-1" aria-hidden="true">
            <PaperFill />
          </div>
          <div className="desk-sheet">
            <svg className="desk-paper" aria-hidden="true" preserveAspectRatio="none">
              <rect width="100%" height="100%" fill={tok("sheet")} filter={url(F.paper)} />
              <rect width="100%" height="100%" fill={url(F.edge)} />
            </svg>
            <div className="desk-neatline" aria-hidden="true" />
            <div className="desk-sheet-body">{children}</div>
          </div>
        </div>
        {notes && <div className="desk-notes-row">{notes}</div>}
      </div>
    </div>
  );
}

function PaperFill() {
  return (
    <svg preserveAspectRatio="none">
      <rect width="100%" height="100%" fill={tok("sheet")} filter={url(F.paper)} />
    </svg>
  );
}

/* ---------- Материалы: дерево, кожа, бумага, сургуч, латунь ---------- */

function DeskDefs() {
  return (
    <svg className="desk-defs" aria-hidden="true" focusable="false">
      <defs>
        {/* Орех: вытянутые волокна, изгиб, широкие полосы — яркость умножается на цвет фигуры */}
        <filter id={F.wood} x="0" y="0" width="1" height="1" colorInterpolationFilters="sRGB">
          <feTurbulence type="fractalNoise" baseFrequency="0.0032 0.115" numOctaves={4} seed={7} result="g" />
          <feTurbulence type="fractalNoise" baseFrequency="0.006" numOctaves={2} seed={11} result="warp" />
          <feDisplacementMap in="g" in2="warp" scale={46} xChannelSelector="R" yChannelSelector="G" result="gw" />
          <feTurbulence type="fractalNoise" baseFrequency="0.0011 0.018" numOctaves={2} seed={3} result="b" />
          <feBlend in="gw" in2="b" mode="multiply" result="gb" />
          <feColorMatrix
            in="gb"
            type="matrix"
            values="1.5 0 0 0 0.3  1.5 0 0 0 0.3  1.5 0 0 0 0.3  0 0 0 0 1"
            result="grain"
          />
          <feBlend in="SourceGraphic" in2="grain" mode="multiply" result="w" />
          <feComposite in="w" in2="SourceGraphic" operator="in" />
        </filter>
        {/* Кожа: шум и рассеянный свет сверху слева, умножение на цвет фигуры */}
        <filter id={F.leather} x="0" y="0" width="1" height="1" colorInterpolationFilters="sRGB">
          <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves={3} seed={5} result="n" />
          <feDiffuseLighting in="n" surfaceScale={1.7} diffuseConstant={1.18} result="lit">
            <feDistantLight azimuth={225} elevation={55} />
          </feDiffuseLighting>
          <feBlend in="SourceGraphic" in2="lit" mode="multiply" result="m" />
          <feComposite in="m" in2="SourceGraphic" operator="in" />
        </filter>
        {/* Бумага: микрорельеф, пятнистость цвета кромки, чуть неровный край */}
        <filter id={F.paper} x="-2%" y="-2%" width="104%" height="104%" colorInterpolationFilters="sRGB">
          <feTurbulence type="fractalNoise" baseFrequency="0.95" numOctaves={3} seed={3} result="n" />
          <feDiffuseLighting in="n" surfaceScale={0.42} diffuseConstant={1.12} result="lit">
            <feDistantLight azimuth={225} elevation={62} />
          </feDiffuseLighting>
          <feBlend in="SourceGraphic" in2="lit" mode="multiply" result="p1" />
          <feTurbulence type="fractalNoise" baseFrequency="0.007" numOctaves={2} seed={9} result="m" />
          <feColorMatrix in="m" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0.35 0 0 0 -0.1" result="ma" />
          <feFlood style={{ floodColor: tok("sheet-edge") }} result="tone" />
          <feComposite in="tone" in2="ma" operator="in" result="mot" />
          <feComposite in="mot" in2="p1" operator="over" result="p2" />
          <feComposite in="p2" in2="SourceGraphic" operator="in" result="p3" />
          <feTurbulence type="fractalNoise" baseFrequency="0.045" numOctaves={3} seed={2} result="d" />
          <feDisplacementMap in="p3" in2="d" scale={2.2} xChannelSelector="R" yChannelSelector="G" />
        </filter>
        {/* Сургуч: неровный край */}
        <filter id={F.wax} x="-20%" y="-20%" width="140%" height="140%">
          <feTurbulence type="fractalNoise" baseFrequency="0.09" numOctaves={2} seed={8} result="w" />
          <feDisplacementMap in="SourceGraphic" in2="w" scale={7} xChannelSelector="R" yChannelSelector="G" />
        </filter>
        <radialGradient id={F.edge} cx="46%" cy="40%" r="78%">
          <stop offset="58%" style={{ stopColor: tok("sel-other"), stopOpacity: 0 }} />
          <stop offset="100%" style={{ stopColor: tok("sel-other"), stopOpacity: 0.14 }} />
        </radialGradient>
        <radialGradient id={F.brass} cx="38%" cy="32%" r="70%">
          <stop offset="0%" style={{ stopColor: tok("sheet") }} />
          <stop offset="30%" style={{ stopColor: tok("sheet-edge") }} />
          <stop offset="65%" style={{ stopColor: tok("sel-6") }} />
          <stop offset="100%" style={{ stopColor: tok("desk-wood-deep") }} />
        </radialGradient>
        <linearGradient id={F.gutter} x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%" style={{ stopColor: tok("desk-wood-deep"), stopOpacity: 0 }} />
          <stop offset="50%" style={{ stopColor: tok("desk-wood-deep"), stopOpacity: 0.3 }} />
          <stop offset="100%" style={{ stopColor: tok("desk-wood-deep"), stopOpacity: 0 }} />
        </linearGradient>
        <linearGradient id={F.sheen} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" style={{ stopColor: tok("lamp"), stopOpacity: 0.3 }} />
          <stop offset="55%" style={{ stopColor: tok("lamp"), stopOpacity: 0 }} />
        </linearGradient>
      </defs>
    </svg>
  );
}

/* ---------- Предметы ---------- */

function DeskProps() {
  return (
    <>
      <div className="desk-prop desk-books" aria-hidden="true">
        <Books />
      </div>
      <div className="desk-prop desk-inkwell" aria-hidden="true">
        <Inkwell />
      </div>
      <div className="desk-prop desk-openbook" aria-hidden="true">
        <OpenBook />
      </div>
      <div className="desk-prop desk-glasses" aria-hidden="true">
        <Glasses />
      </div>
      <div className="desk-prop desk-letter" aria-hidden="true">
        <Letter />
      </div>
    </>
  );
}

type BookProps = { cx: number; cy: number; w: number; h: number; rot: number; cover: string; plaque?: boolean };

function Book({ cx, cy, w, h, rot, cover, plaque }: BookProps) {
  const x = -w / 2;
  const y = -h / 2;
  const edges = [0, 1, 2, 3];
  return (
    <g transform={`translate(${cx} ${cy}) rotate(${rot})`}>
      <rect x={x + 7} y={y + 11} width={w} height={h} rx={4} fill={tok("desk-wood-deep")} />
      <rect x={x + 4} y={y + 7} width={w - 1} height={h - 1} rx={2} fill={tok("sheet")} />
      {edges.map((i) => (
        <path
          key={i}
          d={`M${x + 8} ${y + h + 1.6 + i * 1.5} H${x + w + 3} M${x + w + 1.4 + i * 1.5} ${y + 10} V${y + h + 4}`}
          stroke={tok("sheet-edge")}
          strokeWidth={0.55}
        />
      ))}
      <rect x={x} y={y} width={w} height={h} rx={4} fill={cover} filter={url(F.leather)} />
      {/* корешок темнее крышки */}
      <rect x={x} y={y} width={20} height={h} rx={3} fill={tok("desk-wood-deep")} opacity={0.4} />
      {[0.18, 0.38, 0.62, 0.82].map((t) => (
        <path key={t} d={`M${x} ${y + h * t} h20`} stroke={tok("sheet-edge")} strokeOpacity={0.7} strokeWidth={1.3} />
      ))}
      <rect
        x={x + 30}
        y={y + 10}
        width={w - 42}
        height={h - 20}
        rx={2}
        fill="none"
        stroke={tok("sheet-edge")}
        strokeOpacity={0.42}
      />
      {plaque && (
        <>
          <rect x={x + w / 2 - 30} y={y + h / 2 - 16} width={72} height={30} rx={2} fill={tok("sel-6")} filter={url(F.leather)} />
          <path
            d={`M${x + w / 2 - 22} ${y + h / 2 - 3} h56 M${x + w / 2 - 16} ${y + h / 2 + 5} h44`}
            stroke={tok("sheet-edge")}
            strokeOpacity={0.85}
            strokeWidth={1.2}
          />
        </>
      )}
      <rect x={x} y={y} width={w} height={h} rx={4} fill={url(F.sheen)} />
    </g>
  );
}

function Books() {
  return (
    <svg viewBox="0 0 350 300">
      <path d="M238 208 C262 236 280 250 318 262" stroke={tok("sel-4")} strokeWidth={8} fill="none" />
      <Book cx={168} cy={158} w={258} h={182} rot={5} cover={tok("desk-wood-deep")} />
      <Book cx={176} cy={146} w={222} h={162} rot={-7} cover={tok("blotter")} />
      <path d="M206 214 C236 246 262 262 300 286" stroke={tok("sel-self")} strokeWidth={8.5} fill="none" />
      <Book cx={158} cy={132} w={198} h={144} rot={10} cover={tok("sel-3")} plaque />
    </svg>
  );
}

function Inkwell() {
  // Перо лежит по диагонали и кончиком смотрит на лист (влево вниз).
  const p0 = { x: 16, y: 270 };
  const dx = 180;
  const dy = -234;
  const len = Math.hypot(dx, dy);
  const n = { x: -dy / len, y: dx / len };
  const at = (t: number, o: number) => ({ x: p0.x + dx * t + n.x * o, y: p0.y + dy * t + n.y * o });
  const a = at(0.3, 0);
  const c1 = at(0.56, -27);
  const c2 = at(0.86, -22);
  const tip = at(1, 0);
  const c3 = at(0.86, 15);
  const c4 = at(0.56, 17);
  const barbs: string[] = [];
  for (let t = 0.33; t < 0.97; t += 0.03) {
    const w1 = -(t < 0.6 ? (27 * (t - 0.3)) / 0.3 : 27 - (15 * (t - 0.6)) / 0.4) * 0.92;
    const w2 = (t < 0.6 ? (17 * (t - 0.3)) / 0.3 : 17 - (9 * (t - 0.6)) / 0.4) * 0.92;
    const s = at(t, 0);
    const e1 = at(t + 0.05, w1);
    const e2 = at(t + 0.05, w2);
    barbs.push(`M${s.x},${s.y} L${e1.x},${e1.y} M${s.x},${s.y} L${e2.x},${e2.y}`);
  }
  const s0 = at(0, 0);
  const s9 = at(0.98, 0);
  const nib = at(0.07, 0);
  return (
    <svg viewBox="0 0 300 290">
      <path
        d={`M${a.x},${a.y} C${c1.x},${c1.y} ${c2.x},${c2.y} ${tip.x},${tip.y} C${c3.x},${c3.y} ${c4.x},${c4.y} ${a.x},${a.y} Z`}
        fill={tok("sheet")}
        stroke={tok("sheet-edge")}
        strokeWidth={0.8}
      />
      <path d={barbs.join(" ")} stroke={tok("sheet-edge")} strokeWidth={0.5} />
      <path d={`M${s0.x},${s0.y} L${s9.x},${s9.y}`} stroke={tok("sheet-edge")} strokeWidth={2.2} strokeLinecap="round" />
      <path
        d={`M${s0.x},${s0.y} L${nib.x + n.x * 2.6},${nib.y + n.y * 2.6} L${nib.x - n.x * 2.6},${nib.y - n.y * 2.6} Z`}
        fill={tok("desk-wood-deep")}
      />
      {/* гранёное стекло, латунный ворот, чернила с бликом */}
      <g transform="translate(208 92) rotate(9)">
        <rect x={-56} y={-56} width={112} height={112} rx={14} fill={tok("blotter")} fillOpacity={0.8} stroke={tok("sheet")} strokeOpacity={0.3} strokeWidth={1.2} />
        <path d="M-44 -56 L-30 -42 H30 L44 -56 M-56 -44 L-42 -30 V30 L-56 44" stroke={tok("sheet")} strokeOpacity={0.22} fill="none" />
        <path d="M-50 -54 H40" stroke={tok("sheet")} strokeOpacity={0.45} strokeWidth={2} strokeLinecap="round" />
        <circle r={31} fill={url(F.brass)} />
        <circle r={31} fill="none" stroke={tok("desk-wood-deep")} strokeOpacity={0.6} />
        <circle r={20} fill={tok("desk-wood-deep")} />
        <ellipse cx={-7} cy={-7} rx={6.5} ry={3} fill={tok("sheet")} fillOpacity={0.5} transform="rotate(-35 -7 -7)" />
      </g>
    </svg>
  );
}

// Детерминированный «случай»: длины строк в раскрытой книге одинаковы при каждом рендере.
function lines(seed: number, from: number, to: number, base: number): number[] {
  let s = seed;
  const out: number[] = [];
  for (let y = from; y < to; y += 12.5) {
    s = (s * 16807) % 2147483647;
    out.push(base + ((s - 1) / 2147483646) * 30);
  }
  return out;
}

const LEFT_LINES = lines(7, 82, 286, 150);
const RIGHT_LINES = lines(13, 178, 286, 140);

function OpenBook() {
  const ink = { stroke: tok("sheet-ink-2"), strokeOpacity: 0.32, strokeWidth: 2.1, strokeLinecap: "round" as const };
  return (
    <svg viewBox="0 0 480 336">
      <g transform="rotate(6 240 170)">
        <path
          d="M16 46 Q128 20 240 38 Q352 20 464 46 L460 322 Q352 302 240 316 Q128 302 20 322 Z"
          fill={tok("desk-wood-deep")}
          filter={url(F.leather)}
        />
        <path d="M30 54 Q130 30 238 46 L238 304 Q130 290 34 308 Z" fill={tok("sheet")} filter={url(F.paper)} />
        <path d="M242 46 Q350 30 450 54 L446 308 Q350 290 242 304 Z" fill={tok("sheet")} filter={url(F.paper)} />
        <rect x={206} y={40} width={68} height={270} fill={url(F.gutter)} />
        {/* текст — нечитаемые строки, иначе шум */}
        <path d={LEFT_LINES.map((len, i) => `M58 ${82 + i * 12.5} h${82 + i * 12.5 > 270 ? len - 80 : len}`).join(" ")} {...ink} />
        <path d="M300 76 h96" stroke={tok("sheet-ink")} strokeOpacity={0.5} strokeWidth={3} strokeLinecap="round" />
        <circle cx={346} cy={128} r={32} fill="none" stroke={tok("sheet-ink-2")} strokeOpacity={0.45} strokeWidth={1.2} />
        <path d={RIGHT_LINES.map((len, i) => `M272 ${178 + i * 12.5} h${len}`).join(" ")} {...ink} />
        <path d="M244 40 C250 120 246 250 262 336" stroke={tok("blotter")} strokeWidth={7} fill="none" />
      </g>
    </svg>
  );
}

function Glasses() {
  return (
    <svg viewBox="0 0 230 120">
      <g transform="rotate(-8 115 60)" fill="none">
        <path d="M24 50 L118 26 M206 52 L112 30" stroke={tok("sel-6")} strokeWidth={2.4} strokeLinecap="round" />
        {[
          [62, 62],
          [168, 64],
        ].map(([x, y]) => (
          <g key={x}>
            <ellipse cx={x} cy={y} rx={44} ry={35} fill={tok("lamp")} fillOpacity={0.12} stroke={tok("sel-6")} strokeWidth={3} />
            <path
              d={`M${x - 30} ${y - 18} Q${x - 16} ${y - 30} ${x + 2} ${y - 31}`}
              stroke={tok("sheet")}
              strokeOpacity={0.6}
              strokeWidth={2}
              strokeLinecap="round"
            />
          </g>
        ))}
        <path d="M106 58 Q115 44 124 59" stroke={tok("sel-6")} strokeWidth={3} />
      </g>
    </svg>
  );
}

function Letter() {
  return (
    <svg viewBox="0 0 300 230">
      <g transform="rotate(-9 150 115)">
        <rect x={22} y={24} width={256} height={176} fill={tok("sheet")} filter={url(F.paper)} />
        <path
          d="M22 24 L150 116 L278 24 M22 200 L124 110 M278 200 L176 110"
          stroke={tok("sheet-ink-2")}
          strokeOpacity={0.3}
          fill="none"
        />
        <circle cx={150} cy={118} r={24} fill={tok("sel-self")} filter={url(F.wax)} />
        <circle cx={150} cy={118} r={15} fill="none" stroke={tok("desk-wood-deep")} strokeOpacity={0.4} strokeWidth={1.5} />
        <text x={150} y={125} textAnchor="middle" className="desk-seal">
          φ
        </text>
        <path d="M136 104 Q146 97 158 99" stroke={tok("sheet")} strokeOpacity={0.5} strokeWidth={2} fill="none" strokeLinecap="round" />
      </g>
    </svg>
  );
}
