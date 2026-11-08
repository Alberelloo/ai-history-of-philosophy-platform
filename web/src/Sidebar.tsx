import { useEffect, useRef, useState, type FocusEvent, type KeyboardEvent, type MouseEvent } from "react";
import { navigate } from "./App";
import { pick, useLang, useT } from "./i18n";
import { SOON } from "./SoonPage";
import { useSources } from "./sources";
import { storage, THEMES, useStored, type Lang, type Theme } from "./storage";
import { useTheme } from "./theme";
import { Icon, Mark, type IconName } from "./ui";

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

export function Sidebar({ active, sourceId, panelOpen }: { active: string; sourceId?: string; panelOpen: boolean }) {
  const t = useT();
  const lang = useLang();
  const theme = useTheme();
  const pinnedChoice = useStored((s) => s.sidebarPinned);
  const open = useStored((s) => s.openSources);
  const current = useStored((s) => s.currentSource);
  const wide = useMedia(PIN_MEDIA);
  // Временное сворачивание (2.2): закреплённая навигация + открытая панель не помещаются на
  // ширине 1280–1471px — навигация сворачивается до 56px, пока панель открыта; выбор сохраняется.
  const roomy = useMedia("(min-width: 1472px)");
  const blocked = wide && panelOpen && !roomy;
  const pinned = pinnedChoice && wide && !blocked;
  const [hover, setHover] = useState(false);
  const [focused, setFocused] = useState(false);
  // Esc свернул панель: она не раскроется снова, пока указатель или фокус не уйдут и не вернутся.
  const [dismissed, setDismissed] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const expanded = pinned || ((hover || focused) && !dismissed);
  const state = pinned ? "pinned" : expanded ? "expanded" : "collapsed";

  const info = useSources(open.map((o) => o.id));
  const books = open.filter((o) => info[o.id]);

  // Отступ содержимого — по фактическому состоянию панели (с учётом временного сворачивания):
  // при временном сворачивании содержимое сдвигается только на 56px, как у свёрнутой панели.
  useEffect(() => {
    if (pinned) document.documentElement.dataset.sidebar = "pinned";
    else delete document.documentElement.dataset.sidebar;
  }, [pinned]);

  // Раскрывает только фокус с клавиатуры: после щелчка мышью фокус остаётся на пункте, и панель
  // не должна висеть поверх текста, когда указатель ушёл.
  const onFocus = (e: FocusEvent) => {
    if ((e.target as HTMLElement).matches?.(":focus-visible")) setFocused(true);
  };
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
    // Закрыта книга, которую сейчас читают: к следующей открытой, а если она была последней —
    // в библиотеку (адрес заменяется, чтобы «Назад» не открыл закрытую книгу снова).
    if (active === "reading" && sourceId === id) {
      const next = storage.currentSource();
      if (next) navigate(`/read/${next}`);
      else {
        window.history.replaceState(null, "", "/");
        window.dispatchEvent(new PopStateEvent("popstate"));
      }
    }
  };
  const nextTheme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
  const themeName = (value: Theme) => t.theme[value];
  const otherLang: Lang = lang === "ru" ? "en" : "ru";
  // Ни одной открытой книги: заголовок ведёт в библиотеку. Ссылка на «/read» открыла бы учебник
  // по умолчанию, и закрытая последней книга тут же вернулась бы в список.
  const lastOpen = current && open.some((o) => o.id === current) ? current : open[0]?.id;
  const continueHref = lastOpen ? `/read/${lastOpen}` : "/";

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
      onFocus={onFocus}
      onBlur={onBlur}
      onKeyDown={onKeyDown}
    >
      <a className="sidebar__brand" href="/" onClick={go("/")} aria-label={t.nav.home}>
        <span className="sidebar__icon">
          <Mark size={28} />
        </span>
        <span className="sidebar__label sidebar__name">PhiloGraph</span>
      </a>
      {/* Навигация — и список разделов, и низ панели с настройками: одна область «Разделы». */}
      <nav className="sidebar__nav" aria-label={t.nav.label}>
        <div className="sidebar__scroll">
          <p className="sidebar__group">
            <span>{t.sidebar.read}</span>
          </p>
          <Item href="/" icon="library" label={t.nav.library} current={active === "library"} />
          <Item
            href={continueHref}
            icon="books"
            label={t.sidebar.openBooks}
            count={books.length}
            title={books.length ? t.sidebar.openBooksCount(books.length) : t.sidebar.noOpenBooks}
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
                    <span className="sidebar__icon" role="img" aria-label={pick(t.library.kinds, book.kind)}>
                      <Icon name={KIND_ICON[book.kind] ?? "book"} small />
                    </span>
                    <span className="sidebar__label sidebar__book-text">
                      <span className="sidebar__book-title">{book.title}</span>
                      {book.authors.length > 0 && (
                        <span className="sidebar__book-author">{book.authors.join(", ")}</span>
                      )}
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
                const isAssistant = s.code === "assistant";
                return (
                  <Item
                    key={s.code}
                    href={isAssistant ? "/assistant" : `/soon/${s.code}`}
                    icon={s.icon}
                    label={text.title}
                    soon={!isAssistant}
                    title={isAssistant ? undefined : text.hint}
                    current={active === s.code}
                  />
                );
              })}
            </div>
          ))}
        </div>
        <div className="sidebar__foot">
          <Item href="/settings" icon="settings" label={t.nav.settings} current={active === "settings"} />
          {/* Язык и тема — одни и те же кнопки в свёрнутой и раскрытой панели: наведение раскрывает
              панель, и кнопка под указателем не должна исчезать. */}
          <button
            type="button"
            className="pg-btn pg-btn--ghost sidebar__item sidebar__tool"
            aria-label={t.sidebar.langToggle(t.lang[otherLang])}
            title={t.sidebar.langToggle(t.lang[otherLang])}
            onClick={() => storage.setLang(otherLang)}
          >
            <span className="sidebar__icon sidebar__lang" aria-hidden="true">
              {t.lang[lang]}
            </span>
            <span className="sidebar__label" aria-hidden="true">
              {t.sidebar.langName}
            </span>
          </button>
          <button
            type="button"
            className="pg-btn pg-btn--ghost sidebar__item sidebar__tool"
            aria-label={t.sidebar.themeCycle(themeName(theme), themeName(nextTheme))}
            title={t.sidebar.themeCycle(themeName(theme), themeName(nextTheme))}
            onClick={() => storage.setTheme(nextTheme)}
          >
            <span className="sidebar__icon">
              <Icon name={theme === "light" ? "sun" : theme === "dark" ? "moon" : "system"} />
            </span>
            <span className="sidebar__label" aria-hidden="true">
              {t.sidebar.themeName(themeName(theme))}
            </span>
          </button>
          <button
            type="button"
            className="pg-btn pg-btn--ghost sidebar__item sidebar__pin"
            aria-pressed={pinnedChoice}
            aria-disabled={blocked || undefined}
            disabled={!wide}
            title={blocked ? t.reader.pinBlocked : wide ? undefined : t.sidebar.pinNarrow}
            onClick={() => {
              if (blocked) return;
              storage.setSidebarPinned(!pinnedChoice);
            }}
          >
            <span className="sidebar__icon">
              <Icon name="pin" />
            </span>
            <span className="sidebar__label">{t.sidebar.pin}</span>
          </button>
        </div>
      </nav>
    </div>
  );
}
