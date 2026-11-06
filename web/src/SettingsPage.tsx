import { useState } from "react";
import { useLang, useT } from "./i18n";
import { GenerationSettings, NoticeText } from "./Notice";
import { setScope, useScope } from "./scope";
import { storage, type Lang, type Theme } from "./storage";
import { useTheme } from "./theme";
import { Icon, Seg } from "./ui";

// Настройки читателя. Хранятся только в этом браузере и уходят с каждым запросом.
export function SettingsPage() {
  const t = useT();
  const scope = useScope();
  const theme = useTheme();
  const lang = useLang();
  const [confirming, setConfirming] = useState(false);
  const [done, setDone] = useState(false);

  return (
    <main className="page page--narrow settings">
      <header className="page-header">
        <div>
          <h1 className="page-title">{t.settings.title}</h1>
          <p className="page-lead">{t.settings.lead}</p>
        </div>
      </header>
      <section className="settings__section" aria-label={t.settings.appearance}>
        <h2 className="section-title">{t.settings.appearance}</h2>
        <div className="settings__row">
          <span className="settings__label">{t.theme.label}</span>
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
        </div>
        <div className="settings__row">
          <span className="settings__label">{t.lang.label}</span>
          <Seg<Lang>
            label={t.lang.label}
            value={lang}
            onChange={(value) => storage.setLang(value)}
            items={[
              { value: "ru", label: t.lang.ru },
              { value: "en", label: t.lang.en },
            ]}
          />
        </div>
      </section>
      <section className="settings__section" aria-label={t.settings.generationSection}>
        <h2 className="section-title">{t.settings.generationSection}</h2>
        <GenerationSettings />
        <p className="muted">{t.settings.generationNote}</p>
      </section>
      <section className="settings__section" aria-label={t.settings.sources}>
        <h2 className="section-title">{t.settings.sources}</h2>
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
      </section>
      <section className="settings__section">
        <details className="disclosure">
          <summary>
            <Icon name="chevronRight" small className="disclosure__chevron" />
            {t.notice.label}
          </summary>
          <NoticeText />
        </details>
      </section>
      <section className="settings__section" aria-label={t.settings.data}>
        <h2 className="section-title">{t.settings.data}</h2>
        <p className="muted">{t.settings.dataNote}</p>
        {!confirming && (
          <div className="actions">
            <button className="pg-btn pg-btn--secondary" onClick={() => (setDone(false), setConfirming(true))}>
              {t.settings.reset}
            </button>
          </div>
        )}
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
      </section>
    </main>
  );
}
