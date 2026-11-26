import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useT } from "../i18n";
import { packIntervals, timeScale } from "../map/layout";
import { canvasMeasure } from "../map/measure";
import { spanText, yearText, type Epoch } from "./api";

// Лента эпох (epochs, «Страница эпох» и «Клавиатура и доступность»): пролёты на линейной оси
// времени, пересекающиеся — по дорожкам (packIntervals — тот же алгоритм, что у лент людей на
// карте), нечёткие границы — растушёвкой от самого раннего до самого позднего года. Занятый
// отрезок дорожки — пролёт вместе с подписью, поэтому ни пролёты, ни подписи не налегают.
// Шкала — шаги делений карты (timeScale). Не хватает ширины — лента прокручивается внутри себя.
// Пролёты — элементы HTML (role="option"): фокус, доступное имя и прямоугольники для проверок.

const PAD = 16; // поля ленты слева и справа
const AXIS = 28; // полоса подписей годов
const LANE = 40; // высота дорожки
const SPAN_H = 30;
const LABEL_PAD = 10;
const GAP = 12; // зазор между отрезками на одной дорожке
const MIN_PX_PER_YEAR = 0.3;
// Шрифт подписи пролёта: им же меряется ширина при раскладке (стиль .epochs-span__label).
export const LABEL_FONT = '500 14px Onest, "Onest Variable", system-ui, sans-serif';

type Placed = {
  epoch: Epoch;
  x0: number; // самое раннее начало
  x1: number; // самый поздний конец
  core0: number; // сплошная часть: самое позднее начало…
  core1: number; // …самый ранний конец
  occ: [number, number];
  lane: number;
};

export function spanName(e: Epoch, bce: string): string {
  const range = spanText(e.from, e.to, bce);
  // Исходная запись — второй признак нечёткости («ок.», «XVIII в.»), если она другая.
  return e.original && e.original !== range ? `${e.label}, ${range} (${e.original})` : `${e.label}, ${range}`;
}

export function Timeline({
  epochs,
  selected,
  onSelect,
  onClear,
}: {
  epochs: Epoch[];
  selected: string | null;
  onSelect: (id: string) => void;
  onClear: () => void;
}) {
  const t = useT();
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(960);
  const measure = useMemo(() => canvasMeasure(), []);
  const [fonts, setFonts] = useState(0);
  const [focus, setFocus] = useState(0);
  const options = useRef<(HTMLDivElement | null)[]>([]);

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const update = () => setWidth(Math.max(320, Math.round(el.clientWidth)));
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    let live = true;
    document.fonts?.ready.then(() => {
      if (!live) return;
      measure.clear();
      setFonts((v) => v + 1);
    });
    return () => {
      live = false;
    };
  }, [measure]);

  const plan = useMemo(() => {
    const y0 = Math.min(...epochs.map((e) => e.fuzzy.from[0]));
    const y1 = Math.max(...epochs.map((e) => e.fuzzy.to[1]));
    const span = Math.max(1, y1 - y0);
    const k = Math.max((width - 2 * PAD) / span, MIN_PX_PER_YEAR);
    const inner = Math.max(width, Math.ceil(span * k + 2 * PAD));
    const s = timeScale([y0, y1], PAD, inner - PAD);
    const placed: Placed[] = epochs.map((epoch) => {
      const x0 = s.x(epoch.fuzzy.from[0]);
      const x1 = Math.max(x0 + 2, s.x(epoch.fuzzy.to[1]));
      const core0 = Math.min(s.x(epoch.fuzzy.from[1]), s.x(epoch.fuzzy.to[0]));
      const core1 = Math.max(core0, s.x(epoch.fuzzy.to[0]));
      const label = measure(epoch.label, LABEL_FONT) + 2 * LABEL_PAD;
      return { epoch, x0, x1, core0, core1, occ: [x0, Math.max(x1, x0 + label) + GAP], lane: 0 };
    });
    const lanes = packIntervals(placed, (a, b) => a.epoch.from - b.epoch.from || a.epoch.label.localeCompare(b.epoch.label, "ru"));
    // Подпись не уходит за правый край: ширина содержимого — по самому правому отрезку.
    const right = Math.max(inner, ...placed.map((p) => Math.ceil(p.occ[1] + PAD)));
    return { placed, lanes, ticks: s.ticks.map((y) => ({ y, x: s.x(y) })), inner: right, fonts };
  }, [epochs, width, measure, fonts]); // fonts — пересчёт после загрузки шрифтов

  // Фокус ленты — на выбранной эпохе, иначе на первой (один пролёт в порядке Tab).
  useEffect(() => {
    const at = epochs.findIndex((e) => e.id === selected);
    if (at >= 0) setFocus(at);
  }, [epochs, selected]);

  const move = (to: number) => {
    const at = Math.max(0, Math.min(epochs.length - 1, to)); // края — без перехода по кругу
    setFocus(at);
    const el = options.current[at];
    el?.focus();
    el?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>, index: number) => {
    if (e.key === "ArrowRight") move(index + 1);
    else if (e.key === "ArrowLeft") move(index - 1);
    else if (e.key === "Home") move(0);
    else if (e.key === "End") move(epochs.length - 1);
    else if (e.key === "Enter" || e.key === " ") onSelect(epochs[index].id);
    else if (e.key === "Escape") onClear();
    else return;
    e.preventDefault();
  };

  const bce = t.epochs.bce;
  return (
    <div className="epochs-ribbon" ref={box}>
      <div
        className="epochs-ribbon__inner"
        role="listbox"
        aria-label={t.epochs.ribbon}
        style={{ width: plan.inner, height: AXIS + plan.lanes * LANE + 8 }}
      >
        <div className="epochs-ribbon__axis" aria-hidden="true">
          {plan.ticks.map((tick) => (
            <span key={tick.y} className="epochs-ribbon__tick" style={{ left: tick.x }}>
              {yearText(tick.y, bce)}
            </span>
          ))}
        </div>
        {plan.placed.map((p) => {
          const index = epochs.indexOf(p.epoch);
          const e = p.epoch;
          const w = p.x1 - p.x0;
          const inStart = p.core0 - p.x0;
          const inEnd = p.core1 - p.x0;
          const isSelected = e.id === selected;
          return (
            <div
              key={e.id}
              ref={(el) => {
                options.current[index] = el;
              }}
              id={`epoch-span-${index}`}
              className={isSelected ? "epochs-span is-selected" : "epochs-span"}
              role="option"
              aria-selected={isSelected}
              aria-label={spanName(e, bce)}
              tabIndex={index === focus ? 0 : -1}
              data-epoch={e.id}
              data-lane={p.lane}
              data-fuzzy-start={e.fuzzy.from[1] - e.fuzzy.from[0]}
              data-fuzzy-end={e.fuzzy.to[1] - e.fuzzy.to[0]}
              style={{ left: p.x0, width: w, top: AXIS + p.lane * LANE + (LANE - SPAN_H) / 2, height: SPAN_H }}
              onClick={() => onSelect(e.id)}
              onFocus={() => setFocus(index)}
              onKeyDown={(ev) => onKey(ev, index)}
            >
              <span
                className="epochs-span__fill"
                aria-hidden="true"
                style={{
                  background: `linear-gradient(to right, transparent 0, var(--history-tint) ${inStart}px, var(--history-tint) ${inEnd}px, transparent ${w}px)`,
                }}
              />
              <span className="epochs-span__label" style={{ font: LABEL_FONT }}>
                {e.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function TimelinePlaceholder() {
  const t = useT();
  return (
    <div className="epochs-ribbon epochs-ribbon--placeholder" aria-busy="true" aria-label={t.epochs.loading}>
      {[0, 1, 2].map((lane) => (
        <span key={lane} className="epochs-ribbon__bar" style={{ top: AXIS + lane * LANE + (LANE - SPAN_H) / 2 }} />
      ))}
    </div>
  );
}
