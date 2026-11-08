import { useEffect, useState } from "react";
import { api, type SourceItem } from "./api";

// Описания источников (название, авторы, вид) для боковой панели и настроек. Библиотека
// сообщает то, что уже загрузила; иначе — один запрос полного списка на вкладку.

const known = new Map<string, SourceItem>();
const EVENT = "philograph:sources";
let loading: Promise<void> | null = null;

export function rememberSources(sources: SourceItem[]): void {
  sources.forEach((s) => known.set(s.id, s));
  window.dispatchEvent(new Event(EVENT));
}

function loadAll(): Promise<void> {
  loading ??= api
    .sources({ kinds: [], languages: [], query: "" })
    .then((list) => rememberSources(list.sources))
    .catch(() => {
      loading = null; // сервис недоступен: попробуем при следующем открытии книги
    });
  return loading;
}

// Описания этих источников; неизвестный (снят с публикации) — undefined.
export function useSources(ids: string[]): Record<string, SourceItem | undefined> {
  const [, setVersion] = useState(0);
  const key = ids.join(",");
  useEffect(() => {
    const refresh = () => setVersion((v) => v + 1);
    window.addEventListener(EVENT, refresh);
    if (ids.length) loadAll(); // полный список один раз: так видно, какие книги сняты с публикации
    return () => window.removeEventListener(EVENT, refresh);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return Object.fromEntries(ids.map((id) => [id, known.get(id)]));
}
