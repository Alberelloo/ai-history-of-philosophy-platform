import { useEffect, useState } from "react";
import { api, SourceList } from "./api";
import { navigate } from "./App";
import { pick, useT } from "./i18n";
import { storage } from "./storage";
import { rememberSources } from "./sources";
import { FilterMenu, Icon } from "./ui";

const KINDS = ["textbook", "primary", "reference"];

export function LibraryPage() {
  const t = useT();
  const [kinds, setKinds] = useState<string[]>([]);
  const [languages, setLanguages] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [data, setData] = useState<SourceList | null>(null);
  const [allLanguages, setAllLanguages] = useState<string[]>([]);
  const [openLicense, setOpenLicense] = useState<string | null>(null);
  const current = storage.currentSource();
  const notSet = t.library.notSet;
  const languageName = (code: string) => pick(t.library.languages, code) ?? code;

  useEffect(() => {
    let cancelled = false;
    api.sources({ kinds, languages, query }).then((result) => {
      if (cancelled) return;
      rememberSources(result.sources);
      setData(result);
      setAllLanguages(result.languages);
    });
    return () => {
      cancelled = true;
    };
  }, [kinds, languages, query]);

  const reset = () => {
    setKinds([]);
    setLanguages([]);
    setQuery("");
  };
  const choose = (id: string) => {
    storage.setCurrentSource(id);
    navigate(`/read/${id}`);
  };
  const filtered = kinds.length > 0 || languages.length > 0 || query !== "";

  return (
    <main className="page library">
      <header className="page-header">
        <div>
          <h1 className="page-title">{t.library.title}</h1>
          <p className="page-lead">{t.library.lead}</p>
        </div>
        <button className="pg-btn pg-btn--primary" onClick={() => navigate("/read")}>
          <Icon name="book" />
          {t.library.startReading}
        </button>
      </header>

      <section className="filters" aria-label={t.library.filters}>
        <div className="pg-field filters__search">
          <div className="pg-field__control">
            <Icon name="search" />
            <input
              className="pg-input"
              type="search"
              aria-label={t.library.searchLabel}
              placeholder={t.library.searchPlaceholder}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
        </div>
        <FilterMenu
          label={t.library.kind}
          items={KINDS.map((value) => ({ value, label: pick(t.library.kinds, value) ?? value }))}
          selected={kinds}
          onChange={setKinds}
        />
        <FilterMenu
          label={t.library.language}
          items={allLanguages.map((value) => ({ value, label: languageName(value) }))}
          selected={languages}
          onChange={setLanguages}
        />
        {/* Сброс всегда на своём месте: строка не прыгает, когда фильтры выбирают и снимают.
            Неактивна через aria-disabled: после нажатия фокус остаётся на кнопке. */}
        <button
          className="pg-btn pg-btn--ghost pg-btn--sm filters__reset"
          onClick={() => filtered && reset()}
          aria-disabled={!filtered || undefined}
        >
          <Icon name="close" small />
          {t.library.reset}
        </button>
      </section>

      {data && data.sources.length === 0 && (
        <div className="pg-notice empty" role="status">
          <Icon name="info" />
          <div>{t.library.empty}</div>
          <button className="pg-btn pg-btn--ghost pg-btn--sm" onClick={reset}>
            {t.library.reset}
          </button>
        </div>
      )}

      <ul className="sources">
        {data?.sources.map((s) => (
          <li key={s.id} className={s.id === current ? "source current" : "source"}>
            <div className="source-main">
              <div className="source-head">
                <h2>{s.title}</h2>
                <div className="source-badges">
                  {s.id === current && <span className="badge badge--accent">{t.library.current}</span>}
                  {s.id === data.default_source_id && <span className="badge">{t.library.byDefault}</span>}
                </div>
              </div>
              <dl>
                <dt>{t.library.author}</dt>
                <dd>{s.authors.length ? s.authors.join(", ") : notSet}</dd>
                <dt>{t.library.year}</dt>
                <dd className="num">{s.year ?? notSet}</dd>
                <dt>{t.library.language}</dt>
                <dd>{s.language ? languageName(s.language) : notSet}</dd>
                <dt>{t.library.kind}</dt>
                <dd>{pick(t.library.kinds, s.kind) ?? notSet}</dd>
                <dt>{t.library.license}</dt>
                <dd>
                  <button
                    className="pg-btn pg-btn--ghost pg-btn--sm license-toggle"
                    aria-expanded={openLicense === s.id}
                    onClick={() => setOpenLicense(openLicense === s.id ? null : s.id)}
                  >
                    {s.license.title ?? notSet}
                    <Icon name="chevronDown" small className="license-toggle__chevron" />
                  </button>
                  {openLicense === s.id && (
                    <span className="license-details" role="note">
                      {s.license.title ?? notSet}
                      {s.license.url && (
                        <>
                          {" — "}
                          <a href={s.license.url} target="_blank" rel="noreferrer">
                            {t.library.licenseText}
                          </a>
                        </>
                      )}
                    </span>
                  )}
                </dd>
              </dl>
            </div>
            <div className="source-actions">
              <button className="pg-btn pg-btn--secondary" onClick={() => choose(s.id)}>
                {t.library.read}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </main>
  );
}
