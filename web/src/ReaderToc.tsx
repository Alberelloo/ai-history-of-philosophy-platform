import type { TocItem } from "./api";
import { navigate } from "./App";

// Оглавление источника на экране чтения (reader-panels.md 8.1): полное (K1, K2) и в слое
// (K3, K4). Текущая глава — aria-current="page"; раздел у верхнего края текста —
// aria-current="location" (сценарий «Отметка текущего места», T32; раздел даёт useTocLocation).
export function Toc({
  items,
  sourceId,
  current,
  section = null,
  onNavigate,
}: {
  items: TocItem[];
  sourceId: string;
  current: string;
  section?: string | null;
  onNavigate?: () => void;
}) {
  return (
    <ul>
      {items.map((item) => {
        const isChapter = item.chapter_id === item.id;
        const target = isChapter
          ? `/read/${sourceId}/${item.id}`
          : `/read/${sourceId}/${item.chapter_id}#s-${item.id}`;
        return (
          <li key={item.id}>
            <a
              href={target}
              aria-current={item.id === current ? "page" : item.id === section ? "location" : undefined}
              onClick={(e) => {
                e.preventDefault();
                navigate(target);
                onNavigate?.();
              }}
            >
              {item.title}
            </a>
            {item.children.length > 0 && (
              <Toc items={item.children} sourceId={sourceId} current={current} section={section} onNavigate={onNavigate} />
            )}
          </li>
        );
      })}
    </ul>
  );
}
