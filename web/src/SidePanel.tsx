import { useEffect, useState, type ReactNode } from "react";
import { useT } from "./i18n";
import { Icon } from "./ui";

// Каркас правой панели (docs/design/features/reader-panels.md, 2.3): на ширине окна ≥1280px
// панель «сдвигает» колонки, на 1024–1279px живёт в полоске 48px у правого края и разворачивается
// поверх текста. Содержимое (ассистент, полная карточка) приходит через children.

const COMPACT_MEDIA = "(max-width: 1279px)";

export function useMedia(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const list = window.matchMedia(query);
    const update = () => setMatches(list.matches);
    list.addEventListener("change", update);
    update();
    return () => list.removeEventListener("change", update);
  }, [query]);
  return matches;
}

type Props = {
  expanded: boolean;
  onExpand: (expanded: boolean) => void;
  ariaLabel: string;
  children: ReactNode;
};

export function SidePanel({ expanded, onExpand, ariaLabel, children }: Props) {
  const t = useT();
  const compact = useMedia(COMPACT_MEDIA);
  const open = !compact || expanded;

  // На ≥1280 панель занимает место и сдвигает содержимое: уведомления над текстом сужаются,
  // чтобы не уходить под панель (правило для .first-run в styles.css).
  useEffect(() => {
    if (!open || compact) return;
    document.documentElement.dataset.panel = "open";
    return () => {
      delete document.documentElement.dataset.panel;
    };
  }, [open, compact]);

  return (
    <>
      {compact && !expanded && (
        <button
          type="button"
          className="side-panel__strip"
          aria-expanded={false}
          aria-controls="side-panel"
          title={t.panel.expandAssistant}
          aria-label={t.panel.expandAssistant}
          onClick={() => onExpand(true)}
        >
          <Icon name="chat" />
          <span className="visually-hidden">{t.panel.expandAssistant}</span>
        </button>
      )}
      {open && (
        <aside
          id="side-panel"
          className="side-panel"
          data-mode={compact ? "strip" : "shift"}
          aria-label={ariaLabel}
        >
          {compact && (
            <button
              type="button"
              className="pg-btn pg-btn--ghost pg-btn--icon pg-btn--sm side-panel__collapse"
              aria-label={t.panel.collapse}
              title={t.panel.collapse}
              onClick={() => onExpand(false)}
            >
              <Icon name="chevronRight" small />
            </button>
          )}
          {children}
        </aside>
      )}
    </>
  );
}
