import { useCallback, useLayoutEffect, useRef } from "react";

// Обработчик для эффекта: стабильная функция, которая вызывает последнюю версию ``handler``.
// Эффект, вызывающий такой обработчик, перезапускается только от своих зависимостей, а
// обработчик видит значения последней отрисовки (как useEffectEvent в React 19). Версия
// обновляется в useLayoutEffect — раньше пассивных эффектов той же отрисовки. Вызывать из
// эффектов и обработчиков событий, не во время отрисовки.
export function useEvent<A extends unknown[], R>(handler: (...args: A) => R): (...args: A) => R {
  const ref = useRef(handler);
  useLayoutEffect(() => {
    ref.current = handler;
  });
  return useCallback((...args: A) => ref.current(...args), []);
}
