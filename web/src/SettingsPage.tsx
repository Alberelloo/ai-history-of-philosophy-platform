import { useEffect, useState, type ReactNode } from "react";
import { navigate } from "./App";
import { useLang, useT } from "./i18n";
import { GenerationSettings, NoticeText } from "./Notice";
import { setScope, useScope } from "./scope";
import { useSources } from "./sources";
import { storage, useStored, type Lang, type Theme } from "./storage";
import { useTheme } from "./theme";
import { Icon, Seg } from "./ui";

// Настройки читателя по разделам с оглавлением слева, как на GitHub. Хранятся только в этом
// браузере и уходят с каждым запросом. У раздела свой адрес: /settings#appearance.

const SECTIONS = ["appearance", "assistant", "sources", "books", "about", "data"] as const;
type SectionId = (typeof SECTIONS)[number];

function Section({ id, title, lead, children }: { id: SectionId; title: string; lead?: string; children: ReactNode }) {
  return (
    <section id={id} className="settings__section" aria-labelledby={`${id}-title`}>
      <header className="settings__head">
        <h2 id={`${id}-title`} className="settings__title">
          {title}
        </h2>
        {lead && <p className="settings__lead">{lead}</p>}
      </header>
      {children}
    </section>
  );
}

function Row({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="settings__row">
      <div className="settings__row-text">
        <span className="settings__label">{label}</span>
        {hint && <span className="settings__hint">{hint}</span>}
      </div>
      <div className="settings__control">{children}</div>
    </div>
  );
}

// Раздел, заголовок которого сейчас ближе всего к верху окна. Внизу страницы последние разделы
// не доходят до верха: тогда отмечен раздел из адреса, если он на экране, иначе последний.
function useVisibleSection(requested: SectionId | undefined): SectionId {
  const [visible, setVisible] = useState<SectionId>(requested ?? SECTIONS[0]);
  useEffect(() => {
    const update = () => {
      const top = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
      let current: SectionId = SECTIONS[0];
      for (const id of SECTIONS) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top - top <= 8) current = id;
      }
      // Внизу страницы последний раздел может не дойти до верха — он и виден.
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) {
        const wanted = requested && document.getElementById(requested)?.getBoundingClientRect();
        const onScreen = wanted && wanted.top >= 0 && wanted.top < window.innerHeight;
        current = onScreen ? requested : SECTIONS[SECTIONS.length - 1];
      }
      setVisible(current);
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, [requested]);
  return visible;
}

export function SettingsPage({ hash }: { hash: string }) {
  const t = useT();
  const scope = useScope();
  const theme = useTheme();
  const lang = useLang();
  const mentions = useStored((s) => s.mentions);
  const open = useStored((s) => s.openSources);
  const info = useSources(open.map((o) => o.id));
  const books = open.filter((o) => info[o.id]);
  const [confirming, setConfirming] = useState(false);
  const [done, setDone] = useState(false);
  const requested = SECTIONS.find((id) => id === hash);
  const visible = useVisibleSection(requested);

  // Адрес раздела открывает экран на нём (и при переходе по оглавлению, и по ссылке).
  useEffect(() => {
    if (requested) document.getElementById(requested)?.scrollIntoView({ block: "start" });
  }, [requested]);

  const names: Record<SectionId, string> = {
    appearance: t.settings.appearance,
    assistant: t.settings.generationSection,
    sources: t.settings.sources,
    books: t.settings.books,
    about: t.settings.about,
    data: t.settings.data,
  };

  return (
    <main className="page settings">
      <header className="page-header">
        <div>
          <h1 className="page-title">{t.settings.title}</h1>
          <p className="page-lead">{t.settings.lead}</p>
        </div>
      </header>
      <div className="settings__layout">
        <nav className="settings__toc" aria-label={t.settings.toc}>
          <ul>
            {SECTIONS.map((id) => (
              <li key={id}>
                <a
                  href={`#${id}`}
                  aria-current={visible === id ? "true" : undefined}
                  onClick={(e) => {
                    e.preventDefault();
                    navigate(`/settings#${id}`);
                    document.getElementById(id)?.scrollIntoView({ block: "start" });
                  }}
                >
                  {names[id]}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div className="settings__sections">
          <Section id="appearance" title={names.appearance} lead={t.settings.appearanceLead}>
            <Row label={t.theme.label} hint={t.settings.themeHint}>
              <Seg<Theme>
                label={t.theme.label}
                value={theme}
                onChange={(value) => storage.setTheme(value)}
                items={[
                  { value: "light", label: t.theme.light, icon: "sun" },
                  { value: "dark", label: t.theme.dark, icon: "moon" },
                  { value: "system", label: t.theme.system, icon: "system" },
                ]}
              />
            </Row>
            <Row label={t.lang.label} hint={t.settings.langHint}>
              <Seg<Lang>
                label={t.lang.label}
                value={lang}
                onChange={(value) => storage.setLang(value)}
                items={[
                  { value: "ru", label: t.lang.ru },
                  { value: "en", label: t.lang.en },
                ]}
              />
            </Row>
            <Row label={t.settings.mentions} hint={t.settings.mentionsHint}>
              <Seg<"underline" | "hover">
                label={t.settings.mentions}
                value={mentions}
                onChange={(value) => storage.setMentionsView(value)}
                items={[
                  { value: "underline", label: t.settings.mentionsUnderline },
                  { value: "hover", label: t.settings.mentionsHover },
                ]}
              />
            </Row>
          </Section>

          <Section id="assistant" title={names.assistant} lead={t.settings.generationNote}>
            <div className="settings__row settings__row--block">
              <GenerationSettings />
            </div>
          </Section>

          <Section id="sources" title={names.sources} lead={t.settings.sourcesLead}>
            <Row label={t.settings.sourcesLabel}>
              <div className="pg-seg" role="radiogroup" aria-label={t.settings.sources}>
                <label className="pg-seg__item seg-radio">
                  <input
                    className="seg-radio__input"
                    type="radio"
                    name="scope"
                    checked={!scope.onlyTextbook}
                    onChange={() => setScope({ onlyTextbook: false })}
                  />
                  {t.settings.allSources}
                </label>
                <label className="pg-seg__item seg-radio">
                  <input
                    className="seg-radio__input"
                    type="radio"
                    name="scope"
                    checked={scope.onlyTextbook}
                    onChange={() => setScope({ onlyTextbook: true })}
                  />
                  {t.settings.onlyTextbook}
                </label>
              </div>
            </Row>
          </Section>

          <Section id="books" title={names.books} lead={t.settings.booksLead}>
            {books.length === 0 && <p className="settings__empty">{t.sidebar.noOpenBooks}</p>}
            {books.length > 0 && (
              <ul className="settings__books">
                {books.map(({ id }) => (
                  <li key={id} className="settings__row">
                    <div className="settings__row-text">
                      <a
                        className="settings__label"
                        href={`/read/${id}`}
                        onClick={(e) => {
                          e.preventDefault();
                          navigate(`/read/${id}`);
                        }}
                      >
                        {info[id]!.title}
                      </a>
                      {info[id]!.authors.length > 0 && (
                        <span className="settings__hint">{info[id]!.authors.join(", ")}</span>
                      )}
                    </div>
                    <div className="settings__control">
                      <button
                        className="pg-btn pg-btn--ghost pg-btn--sm"
                        aria-label={t.sidebar.closeBook(info[id]!.title)}
                        onClick={() => storage.closeSource(id)}
                      >
                        <Icon name="close" small />
                        {t.settings.closeBook}
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <div className="actions">
              <button
                className="pg-btn pg-btn--secondary"
                disabled={books.length === 0}
                onClick={() => storage.closeAllSources()}
              >
                {t.settings.closeAll}
              </button>
            </div>
          </Section>

          <Section id="about" title={names.about} lead={t.settings.aboutLead}>
            <details className="disclosure">
              <summary>
                <Icon name="chevronRight" small className="disclosure__chevron" />
                {t.notice.label}
              </summary>
              <NoticeText />
            </details>
          </Section>

          <Section id="data" title={names.data} lead={t.settings.dataNote}>
            <ul className="settings__stored">
              {t.settings.stored.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            <div className="settings__danger" role="group" aria-label={t.settings.danger}>
              <div className="settings__row">
                <div className="settings__row-text">
                  <span className="settings__label">{t.settings.danger}</span>
                  <span className="settings__hint">{t.settings.resetHint}</span>
                </div>
                <div className="settings__control">
                  {!confirming && (
                    <button
                      className="pg-btn pg-btn--secondary settings__danger-button"
                      onClick={() => (setDone(false), setConfirming(true))}
                    >
                      {t.settings.reset}
                    </button>
                  )}
                </div>
              </div>
              {confirming && (
                <div role="alertdialog" aria-label={t.settings.confirmLabel} className="pg-notice pg-notice--danger confirm">
                  <Icon name="warning" />
                  <div>
                    <p>{t.settings.confirm}</p>
                    <div className="actions">
                      <button
                        className="pg-btn pg-btn--primary pg-btn--danger"
                        onClick={() => {
                          storage.reset();
                          setConfirming(false);
                          setDone(true);
                        }}
                      >
                        {t.settings.delete}
                      </button>
                      <button className="pg-btn pg-btn--ghost" onClick={() => setConfirming(false)}>
                        {t.settings.cancel}
                      </button>
                    </div>
                  </div>
                </div>
              )}
              {done && (
                <div className="pg-notice" role="status">
                  <Icon name="check" />
                  <div>{t.settings.done}</div>
                </div>
              )}
            </div>
          </Section>
        </div>
      </div>
    </main>
  );
}
