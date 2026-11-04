import { useEffect, useState } from "react";
import { api, SourceList } from "./api";
import { navigate } from "./App";
import { storage } from "./storage";

const KINDS: [string, string][] = [
  ["textbook", "Учебник"],
  ["primary", "Первоисточник"],
  ["reference", "Справочное издание"],
];
const KIND_NAME = Object.fromEntries(KINDS);
const LANGUAGE_NAME: Record<string, string> = {
  ru: "русский",
  en: "английский",
  de: "немецкий",
  fr: "французский",
  la: "латынь",
  grc: "древнегреческий",
};
const NOT_SET = "не указано";

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

export function LibraryPage() {
  const [kinds, setKinds] = useState<string[]>([]);
  const [languages, setLanguages] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [data, setData] = useState<SourceList | null>(null);
  const [allLanguages, setAllLanguages] = useState<string[]>([]);
  const [openLicense, setOpenLicense] = useState<string | null>(null);
  const current = storage.currentSource();

  useEffect(() => {
    let cancelled = false;
    api.sources({ kinds, languages, query }).then((result) => {
      if (cancelled) return;
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
    <main className="library">
      <header className="library-header">
        <h1>Библиотека</h1>
        <button className="primary" onClick={() => navigate("/read")}>
          Перейти к чтению
        </button>
      </header>

      <section className="filters" aria-label="Поиск и фильтры">
        <input
          type="search"
          aria-label="Поиск по названию и автору"
          placeholder="Название или автор"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <fieldset>
          <legend>Вид</legend>
          {KINDS.map(([value, label]) => (
            <label key={value}>
              <input
                type="checkbox"
                checked={kinds.includes(value)}
                onChange={() => setKinds(toggle(kinds, value))}
              />
              {label}
            </label>
          ))}
        </fieldset>
        <fieldset>
          <legend>Язык</legend>
          {allLanguages.map((value) => (
            <label key={value}>
              <input
                type="checkbox"
                checked={languages.includes(value)}
                onChange={() => setLanguages(toggle(languages, value))}
              />
              {LANGUAGE_NAME[value] ?? value}
            </label>
          ))}
        </fieldset>
        {filtered && (
          <button className="link" onClick={reset}>
            Сбросить поиск и фильтры
          </button>
        )}
      </section>

      {data && data.sources.length === 0 && (
        <p className="empty" role="status">
          Подходящих источников нет.{" "}
          <button className="link" onClick={reset}>
            Сбросить поиск и фильтры
          </button>
        </p>
      )}

      <ul className="sources">
        {data?.sources.map((s) => (
          <li key={s.id} className={s.id === current ? "source current" : "source"}>
            <div className="source-main">
              <h2>{s.title}</h2>
              {s.id === current && <span className="badge">Текущий</span>}
              {s.id === data.default_source_id && <span className="badge muted">По умолчанию</span>}
              <dl>
                <dt>Автор</dt>
                <dd>{s.authors.length ? s.authors.join(", ") : NOT_SET}</dd>
                <dt>Год</dt>
                <dd>{s.year ?? NOT_SET}</dd>
                <dt>Язык</dt>
                <dd>{LANGUAGE_NAME[s.language] ?? s.language ?? NOT_SET}</dd>
                <dt>Вид</dt>
                <dd>{KIND_NAME[s.kind] ?? NOT_SET}</dd>
                <dt>Лицензия</dt>
                <dd>
                  <button
                    className="link"
                    aria-expanded={openLicense === s.id}
                    onClick={() => setOpenLicense(openLicense === s.id ? null : s.id)}
                  >
                    {s.license.title ?? NOT_SET}
                  </button>
                  {openLicense === s.id && (
                    <span className="license-details" role="note">
                      {s.license.title ?? NOT_SET}
                      {s.license.url && (
                        <>
                          {" — "}
                          <a href={s.license.url} target="_blank" rel="noreferrer">
                            текст лицензии
                          </a>
                        </>
                      )}
                    </span>
                  )}
                </dd>
              </dl>
            </div>
            <button className="primary" onClick={() => choose(s.id)}>
              Читать
            </button>
          </li>
        ))}
      </ul>
    </main>
  );
}
