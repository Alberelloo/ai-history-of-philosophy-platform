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
export const ANNOUNCE_GAP = 1000; // мс: живая область — не чаще раза в секунду

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
  on.current = playing;

  const stop = useCallback(() => setPlaying(false), []);
  const toggle = useCallback(() => {
    if (on.current) return setPlaying(false);
    const { win: w, year: y, setYear: set } = latest.current;
    if (y >= w[1]) set(w[0]); // на конце — с начала окна
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
      const t0 = performance.now();
      const perSecond = ((w[1] - w[0]) / PLAY_SECONDS) * speed;
      const frame = () => {
        const { win: cur, setYear: set } = latest.current;
        const y = from + ((performance.now() - t0) / 1000) * perSecond;
        const next = Math.min(cur[1], Math.round(y));
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

// Живая область: объявляет текст на паузе и при шаге, не во время проигрывания и не чаще
// раза в ANNOUNCE_GAP. Первый показ вида не объявляется: только изменения года.
export function useAnnouncer(text: string, key: number, playing: boolean): string {
  const [said, setSaid] = useState("");
  const lastAt = useRef(-Infinity);
  const first = useRef(true);
  const latest = useRef(text);
  latest.current = text;
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    if (playing) return;
    const wait = Math.max(0, lastAt.current + ANNOUNCE_GAP - performance.now());
    const timer = window.setTimeout(() => {
      lastAt.current = performance.now();
      setSaid(latest.current);
    }, wait);
    return () => window.clearTimeout(timer);
  }, [key, playing]);
  return said;
}
