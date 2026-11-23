# Design: расширение покрытия источников

## 1. Открытые каналы (full-text)

Три адаптера в `library/catalog/adapters.py`, каждый реализует протокол `Adapter` (`matches` + `harvest(url, fetcher) -> Harvest`):

| Адаптер | matches | API | Лицензия |
|---|---|---|---|
| `arxiv` | `arxiv.org/abs/<id>`, `arxiv.org/pdf/<id>` | `export.arxiv.org/api/query?id_list=<id>` (Atom XML) | «arXiv.org perpetual, non-exclusive license» → вид `arxiv-non-exclusive` (`open_license`) |
| `philarchive` | `philarchive.org/rec/<id>`, `philpapers.org/rec/<id>` | OAI-PMH `philarchive.org/oai?verb=GetRecord&metadataPrefix=oai_dc&identifier=…` (Dublin Core) | `dc:rights`/подсказка CC → `open_license` |
| `doaj` | `doaj.org/article/<id>` | `doaj.org/api/search/articles/…` (bibjson) | `bibjson.license` (CC-*) → `open_license` |

Каждый `harvest` собирает `metadata` (title, authors, year, language=en, publisher, abstract) и `files` (ссылка на PDF), `license_hint` — строку лицензии из API. Классификация — существующая `suggest_license` + новый паттерн arXiv (добавляется в `LICENSE_HINTS`/`classify_tier`): открытая лицензия → `rights_tier: open_license`. Годы смерти современных авторов НЕ берутся из Wikidata как основание срока — статус всегда `open_license`, а не `public_domain`.

Сбой сети: `fetcher.get` уже бросает `FetchError`; адаптер его не глотает, команда `catalog add` сообщает об ошибке и запись не создаётся (как у существующих адаптеров).

## 2. Metadata-only (без полного текста)

Новый вид записи каталога:

- Поля: `metadata_only: true`, `files: []`, `license` с `rights_tier: in_copyright` и `basis: in_copyright`; плюс `abstract` (аннотация), `toc` (оглавление), `citations` (список цитат/ссылок) — хранятся в `settings` источника.
- В учёте (`registry`): источник регистрируется без файлов, без версии текста, `display: false`. Событие `source.metadata_registered` несёт метаданные.
- В онтологии (`knowledge`): обработчик события создаёт `person` (авторы), `work` (произведение и цитируемые произведения), связь `authored` (персона → авторство → произведение) и `cites` (произведение → ссылается → произведение). Полный текст нигде не хранится.
- Читателю источник не виден (существующий гейтинг `display: false` в библиотеке/поиске/ассистенте).

## 3. Выбор решения

**Как доставлять metadata-only в онтологию** (варианты по критериям: оптимальность, архитектурная правильность, поддерживаемость):

| Вариант | Описание | Оценка |
|---|---|---|
| **А. Отдельное событие `source.metadata_registered` (выбрано)** | Реестр не создаёт версию текста, а эмитит событие с метаданными; knowledge создаёт сущности и связи сам | Архитектурно чисто: текст никогда не проходит конвейер; метаданные — явный payload. Поддерживаемо: новый обработчик в knowledge, не трогает filling |
| Б. Фейковая версия текста | Реестр создаёт «пустую» версию, filling её пропускает | Хак: пустая версия загрязняет состояние, а filling всё равно читает абзацы |
| В. Прямая запись в knowledge из каталога | Каталог пишет сущности напрямую, минуя очередь | Нарушает границы сервисов (catalog→knowledge), не проходит `lint-imports` |

Выбран вариант А: событие через исходящую таблицу `outbox`, очередь доставляет его в knowledge; гейтинг `display: false` переиспользуется, а полный текст физически не создаётся.

## 4. Явные договорённости

1. Открытые репозитории дают `open_license` (не `public_domain`); полный текст раздаётся читателям как открытая лицензия.
2. `metadata_only` → `rights_tier: in_copyright`, `display: false`, файлов и текста нет; читателю не виден.
3. Производные факты (сущности, связи цитирования) из metadata-only — законны; полный текст не хранится.
4. Сеть на сервере: массовый harvest отложен (здесь хосты недостижимы), адаптеры покрыты мок-тестами.
