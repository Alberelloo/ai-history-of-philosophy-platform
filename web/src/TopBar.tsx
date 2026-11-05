import { useEffect, useState, type MouseEvent } from "react";
import { api } from "./api";
import { navigate } from "./App";
import { useLang, useT } from "./i18n";
import { storage, useStored, type Lang, type Theme } from "./storage";
import { useTheme } from "./theme";
import { Mark, Seg } from "./ui";

// Верхняя панель на всех экранах: знак и название, навигация, язык и тема.

const titles = new Map<string, string>();

// Библиотека сообщает названия, которые уже загрузила: панели не нужен лишний запрос.
export function rememberTitles(sources: { id: string; title: string }[]): void {
  sources.forEach((s) => titles.set(s.id, s.title));
}

function useSourceTitle(id: string | undefined): string | undefined {
  const [title, setTitle] = useState(id ? titles.get(id) : undefined);
  useEffect(() => {
    if (!id) return setTitle(undefined);
    if (titles.has(id)) return setTitle(titles.get(id));
    let cancelled = false;
    api
      .sources({ kinds: [], languages: [], query: "" })
      .then((list) => {
        rememberTitles(list.sources);
        if (!cancelled) setTitle(titles.get(id));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [id]);
  return title;
}

function go(path: string) {
  return (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    navigate(path);
  };
}

export function TopBar({ section }: { section: "library" | "reading" | "settings" | "other" }) {
  const t = useT();
  const lang = useLang();
  const theme = useTheme();
  const sourceId = useStored((s) => s.currentSource);
  const title = useSourceTitle(sourceId);

  return (
    <header className="topbar">
      <a className="topbar__brand" href="/" onClick={go("/")} aria-label={t.nav.home}>
        <Mark />
        <span className="topbar__name">PhiloGraph</span>
      </a>
      <nav className="topbar__nav" aria-label={t.nav.label}>
        <a className="topbar__link" href="/" onClick={go("/")} aria-current={section === "library" ? "page" : undefined}>
          {t.nav.library}
        </a>
        {sourceId && title && (
          <a
            className="topbar__link topbar__link--source"
            href={`/read/${sourceId}`}
            onClick={go(`/read/${sourceId}`)}
            aria-current={section === "reading" ? "page" : undefined}
            title={title}
          >
            {title}
          </a>
        )}
        <a
          className="topbar__link"
          href="/settings"
          onClick={go("/settings")}
          aria-current={section === "settings" ? "page" : undefined}
        >
          {t.nav.settings}
        </a>
      </nav>
      <div className="topbar__tools">
        <Seg<Lang>
          label={t.lang.label}
          value={lang}
          onChange={(value) => storage.setLang(value)}
          items={[
            { value: "ru", label: t.lang.ru },
            { value: "en", label: t.lang.en },
          ]}
        />
        <Seg<Theme>
          label={t.theme.label}
          value={theme}
          onChange={(value) => storage.setTheme(value)}
          items={[
            { value: "light", label: t.theme.light, icon: "sun", iconOnly: true },
            { value: "dark", label: t.theme.dark, icon: "moon", iconOnly: true },
            { value: "system", label: t.theme.system, icon: "system", iconOnly: true },
          ]}
        />
      </div>
    </header>
  );
}
