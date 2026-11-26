// Проигрывание года глобуса и объявления живой области (geo-timeline). Без d3: хуки нужны
// странице карты и панели. Время — только requestAnimationFrame, setTimeout и
// performance.now (без Date): тесты управляют им через page.clock.
//
// Проигрывание:
// - запускается и останавливается только читателем (кнопка, пробел), само — никогда;
// - проходит окно за PLAY_SECONDS на ×1 (×0,5 — вдвое дольше, ×2 — вдвое быстрее); год
//   считается по прошедшему времени, а не по числу кадров;
// - на конце окна встаёт на последнем годе; новое «Играть» на конце начинает с начала окна;
// - скрытая вкладка ставит на паузу, после возврата пауза остаётся;
// - при уменьшенном движении — шаги по REDUCED_STEP лет раз в секунду.

import { useCallback, useEffect, useRef, useState } from "react";

export const PLAY_SECONDS = 60;
export const SPEEDS = [0.5, 1, 2] as const;
export type Speed = (typeof SPEEDS)[number];
export const REDUCED_STEP = 10;
export const ANNOUNCE_GAP = 1000;
const FRAME_SLACK = 0.02; // с // мс: живая область — не чаще раза в секунду

export function useReducedMotion(): boolean {
  const query = "(prefers-reduced-motion: reduce)";
  const [reduced, setReduced] = useState(() => typeof window !== "undefined" && !!window.matchMedia?.(query).matches);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return;
    const on = () => setReduced(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  return reduced;
}

export type Playback = { playing: boolean; speed: Speed; setSpeed: (s: Speed) => void; toggle: () => void; stop: () => void };

export function usePlayback(win: [number, number], year: number, setYear: (y: number) => void, reduced: boolean): Playback {
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeedState] = useState<Speed>(1);
  const latest = useRef({ win, year, setYear });
  latest.current = { win, year, setYear };

  const on = useRef(false);
  const startedAt = useRef<number | null>(null);
  on.current = playing;

  const stop = useCallback(() => setPlaying(false), []);
  const toggle = useCallback(() => {
    if (on.current) return setPlaying(false);
    const { win: w, year: y, setYear: set } = latest.current;
    if (y >= w[1]) set(w[0]); // на конце — с начала окна
    startedAt.current = performance.now(); // отсчёт — от нажатия, а не от эффекта после отрисовки
    setPlaying(true);
  }, []);
  const setSpeed = useCallback((s: Speed) => setSpeedState(s), []);

  // Год идёт от точки запуска (или смены скорости): база — год и время старта.
  useEffect(() => {
    if (!playing) return;
    const { win: w } = latest.current;
    const from = latest.current.year >= w[1] ? w[0] : latest.current.year;
    let last = from;
    let raf = 0;
    let timer = 0;
    if (reduced) {
      const step = () => {
        const { win: cur, setYear: set } = latest.current;
        last = Math.min(cur[1], last + REDUCED_STEP);
        set(last);
        if (last >= cur[1]) setPlaying(false);
        else timer = window.setTimeout(step, 1000);
      };
      timer = window.setTimeout(step, 1000);
    } else {
      const t0 = startedAt.current ?? performance.now();
      startedAt.current = null;
      const perSecond = ((w[1] - w[0]) / PLAY_SECONDS) * speed;
      // Год — целая часть пройденного; FRAME_SLACK покрывает кадр, не дошедший до границы
      // секунды (rAF раз в ~16 мс): год сменяется по времени, а не по числу кадров.
      const slack = perSecond * FRAME_SLACK;
      const frame = () => {
        const { win: cur, setYear: set } = latest.current;
        const y = from + ((performance.now() - t0) / 1000) * perSecond;
        const next = Math.min(cur[1], Math.floor(y + slack));
        if (next !== last) {
          last = next;
          set(next);
        }
        if (next >= cur[1]) setPlaying(false);
        else raf = requestAnimationFrame(frame);
      };
      raf = requestAnimationFrame(frame);
    }
    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(timer);
    };
  }, [playing, speed, reduced]);

  // Скрытая вкладка — пауза; после возврата остаётся на паузе.
  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState === "hidden") setPlaying(false);
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  return { playing, speed, setSpeed, toggle, stop };
}

// Живая область: объявляет год и сводку, когда год постоял ANNOUNCE_GAP без изменений и
// проигрывание не идёт (серия шагов — одно объявление последнего значения; объявления не
// чаще раза в секунду). До готовности сцены (ready) и при первом показе — пусто: объявляются
// только изменения года.
export function useAnnouncer(text: string, key: number, playing: boolean, ready: boolean): string {
  const [said, setSaid] = useState("");
  const first = useRef<number | null>(null);
  const latest = useRef(text);
  latest.current = text;
  useEffect(() => {
    if (!ready) return;
    if (first.current == null) {
      first.current = key; // год первого показа не объявляется
      return;
    }
    if (playing) return;
    const timer = window.setTimeout(() => setSaid(latest.current), ANNOUNCE_GAP);
    return () => window.clearTimeout(timer);
  }, [key, playing, ready]);
  return said;
}
