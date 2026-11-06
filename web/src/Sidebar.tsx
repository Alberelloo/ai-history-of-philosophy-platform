import { useEffect, useRef, useState, type FocusEvent, type KeyboardEvent, type MouseEvent } from "react";
import { navigate } from "./App";
import { pick, useLang, useT } from "./i18n";
import { SOON } from "./SoonPage";
import { useSources } from "./sources";
import { storage, THEMES, useStored, type Lang, type Theme } from "./storage";
import { useTheme } from "./theme";
import { Icon, Mark, Seg, type IconName } from "./ui";

// Боковая панель навигации (docs/design/system/components/Sidebar.md): свёрнута до значков,
// раскрывается при наведении или фокусе поверх содержимого, закрепляется и тогда сдвигает его.

// С какой ширины окна закрепление действует: уже — колонка текста стала бы уже 60 знаков.
export const PIN_MEDIA = "(min-width: 1280px)";
const KIND_ICON: Record<string, IconName> = { textbook: "book", primary: "quill", reference: "bookmark" };

function useMedia(query: string): boolean {
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

function go(path: string) {
  return (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    navigate(path);
  };
}

type ItemProps = {
  href: string;
  icon: IconName;
  label: string;
  current?: boolean;
  soon?: boolean;
  title?: string;
  count?: number;
};

function Item({ href, icon, label, current, soon, title, count }: ItemProps) {
  const t = useT();
  return (
    <a
      className="sidebar__item"
      href={href}
      onClick={go(href)}
      aria-current={current ? "page" : undefined}
      title={title}
    >
      <span className="sidebar__icon">
        <Icon name={icon} />
        {count !== undefined && count > 0 && (
          <span className="sidebar__count num" aria-hidden="true">
            {count}
          </span>
        )}
      </span>
      <span className="sidebar__label">
        <span className="sidebar__text">{label}</span>
        {soon && <span className="badge sidebar__soon">{t.sidebar.soon}</span>}
      </span>
    </a>
  );
}

export function Sidebar({ active, sourceId }: { active: string; sourceId?: string }) {
  const t = useT();
  const lang = useLang();
  const theme = useTheme();
  const pinnedChoice = useStored((s) => s.sidebarPinned);
  const open = useStored((s) => s.openSources);
  const current = useStored((s) => s.currentSource);
  const wide = useMedia(PIN_MEDIA);
  const pinned = pinnedChoice && wide;
  const [hover, setHover] = useState(false);
  const [focused, setFocused] = useState(false);
  // Esc свернул панель: она не раскроется снова, пока указатель или фокус не уйдут и не вернутся.
  const [dismissed, setDismissed] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const expanded = pinned || ((hover || focused) && !dismissed);
  const state = pinned ? "pinned" : expanded ? "expanded" : "collapsed";

  const info = useSources(open.map((o) => o.id));
  const books = open.filter((o) => info[o.id]);

  // Отступ содержимого — по выбору читателя; ширина окна решает в CSS (index.html ставит его
  // до первой отрисовки).
  useEffect(() => {
    if (pinnedChoice) document.documentElement.dataset.sidebar = "pinned";
    else delete document.documentElement.dataset.sidebar;
  }, [pinnedChoice]);

  const onBlur = (e: FocusEvent) => {
    if (!root.current?.contains(e.relatedTarget as Node | null)) {
      setFocused(false);
      setDismissed(false);
    }
  };
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== "Escape" || pinned) return;
    setDismissed(true);
    document.getElementById("content")?.focus();
  };
  const close = (id: string) => {
    storage.closeSource(id);
    if (active === "reading" && sourceId === id) {
      const next = storage.currentSource();
      navigate(next ? `/read/${next}` : "/");
    }
  };
  const nextTheme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
  const themeName = (value: Theme) => t.theme[value];
  const otherLang: Lang = lang === "ru" ? "en" : "ru";
  const continueHref = current ? `/read/${current}` : "/read";

  return (
    <div
      ref={root}
      className="sidebar"
      data-state={state}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => {
        setHover(false);
        setDismissed(false);
      }}
      onFocus={() => setFocused(true)}
      onBlur={onBlur}
      onKeyDown={onKeyDown}
    >
      <a className="sidebar__brand" href="/" onClick={go("/")} aria-label={t.nav.home}>
        <span className="sidebar__icon">
          <Mark size={28} />
        </span>
        <span className="sidebar__label sidebar__name">PhiloGraph</span>
      </a>
      <nav className="sidebar__nav" aria-label={t.nav.label}>
        <p className="sidebar__group">
          <span>{t.sidebar.read}</span>
        </p>
        <Item href="/" icon="library" label={t.nav.library} current={active === "library"} />
        <Item
          href={continueHref}
          icon="books"
          label={t.sidebar.openBooks}
          count={books.length}
          title={books.length ? t.sidebar.openBooksCount(books.length) : undefined}
          current={active === "reading" && !books.some((b) => b.id === sourceId)}
        />
        <ul className="sidebar__books" aria-label={t.sidebar.openBooks}>
          {books.length === 0 && <li className="sidebar__empty">{t.sidebar.noOpenBooks}</li>}
          {books.map(({ id }) => {
            const book = info[id]!;
            const reading = active === "reading" && sourceId === id;
            return (
              <li key={id} className={id === current ? "sidebar__book is-current" : "sidebar__book"}>
                <a
                  className="sidebar__item sidebar__item--book"
                  href={`/read/${id}`}
                  onClick={go(`/read/${id}`)}
                  aria-current={reading ? "page" : id === current ? "true" : undefined}
                >
                  <span className="sidebar__icon">
                    <Icon name={KIND_ICON[book.kind] ?? "book"} small />
                  </span>
                  <span className="sidebar__label sidebar__book-text">
                    <span className="sidebar__book-title">{book.title}</span>
                    {book.authors.length > 0 && (
                      <span className="sidebar__book-author">{book.authors.join(", ")}</span>
                    )}
                    <span className="visually-hidden">{pick(t.library.kinds, book.kind)}</span>
                  </span>
                </a>
                <button
                  type="button"
                  className="pg-btn pg-btn--ghost pg-btn--icon pg-btn--sm sidebar__close"
                  aria-label={t.sidebar.closeBook(book.title)}
                  title={t.sidebar.closeBook(book.title)}
                  onClick={() => close(id)}
                >
                  <Icon name="close" small />
                </button>
              </li>
            );
          })}
        </ul>
        {(["explore", "mine"] as const).map((group) => (
          <div key={group} className="sidebar__section">
            <p className="sidebar__group">
              <span>{t.sidebar[group]}</span>
            </p>
            {SOON.filter((s) => s.group === group).map((s) => {
              const text = t.soon.sections[s.code];
              return (
                <Item
                  key={s.code}
                  href={`/soon/${s.code}`}
                  icon={s.icon}
                  label={text.title}
                  soon
                  title={text.hint}
                  current={active === s.code}
                />
              );
            })}
          </div>
        ))}
      </nav>
      <div className="sidebar__foot">
        <Item href="/settings" icon="settings" label={t.nav.settings} current={active === "settings"} />
        <div className="sidebar__tools sidebar__tools--full">
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
        <div className="sidebar__tools sidebar__tools--compact">
          <button
            type="button"
            className="pg-btn pg-btn--ghost pg-btn--icon sidebar__tool"
            aria-label={t.sidebar.langToggle(t.lang[otherLang])}
            title={t.sidebar.langToggle(t.lang[otherLang])}
            onClick={() => storage.setLang(otherLang)}
          >
            {t.lang[lang]}
          </button>
          <button
            type="button"
            className="pg-btn pg-btn--ghost pg-btn--icon sidebar__tool"
            aria-label={t.sidebar.themeCycle(themeName(theme), themeName(nextTheme))}
            title={t.sidebar.themeCycle(themeName(theme), themeName(nextTheme))}
            onClick={() => storage.setTheme(nextTheme)}
          >
            <Icon name={theme === "light" ? "sun" : theme === "dark" ? "moon" : "system"} />
          </button>
        </div>
        <button
          type="button"
          className="pg-btn pg-btn--ghost sidebar__item sidebar__pin"
          aria-pressed={pinnedChoice}
          disabled={!wide}
          title={wide ? undefined : t.sidebar.pinNarrow}
          onClick={() => storage.setSidebarPinned(!pinnedChoice)}
        >
          <span className="sidebar__icon">
            <Icon name="pin" />
          </span>
          <span className="sidebar__label">{t.sidebar.pin}</span>
        </button>
      </div>
    </div>
  );
}
