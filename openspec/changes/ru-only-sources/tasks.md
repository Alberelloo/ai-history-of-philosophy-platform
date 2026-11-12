# Tasks

Тесты помечаются `@pytest.mark.req("<возможность>", "<требование>")` (требования `regional-access` и изменённые требования). Возможность `regional-access` добавляется в `openspec/traceability.yaml` в задаче 8.5; до неё `scripts/check_traceability.py` её не проверяет. Группа 7 обязательна: владелец решил, что `external_processing: false` (раздел «Решения владельца» в design.md). Открытых вопросов нет.

## 1. Регионы показа в учёте источников

- [x] 1.1 Миграция библиотеки 4: столбцы `license_kinds.regions` и `sources.regions` (JSON, NULL) в `src/philograph/library/schema.py`. Проверка: `tests/library/test_registry.py` создаёт базу с нуля и накатывает миграцию на базу версии 3; старые данные читаются.
- [x] 1.2 `Registry.add_license_kind(..., regions=None)`, `Registry.regions(source_id)` (пересечение вида и источника; `None` везде, пустое множество нигде), проверка «расширять нельзя» в `_validate_license`, поле `regions` у `License`-сужения и в `change_license`; пустое пересечение равносильно запрету показа (`src/philograph/library/registry.py`). Тесты `source-registry` / «Виды лицензий как данные»: вид с регионом, сужение, расширение отклоняется.
- [x] 1.3 Каталог: `regions` у вида в `sources/licenses.yaml` (добавляется в задаче 8.4, не здесь), `license.regions` в `sources/catalog.schema.json`, разбор в `src/philograph/library/catalog/model.py`, сравнение регионов в `ensure_license_kinds` (`catalog/service.py`). Тесты в `tests/library/catalog/`: запись с `regions` регистрируется; смена `regions` вида при `sync` обновляет учёт.
- [x] 1.4 Событие `source.access_changed` (outbox) при `change_license` и при смене регионов вида через синхронизацию; payload: `source_id`, `regions` (список или `null`), `permissions`. Тест `regional-access` / «Смена регионов у опубликованного источника»: событие записано, повторная публикация не нужна, пустое пересечение показывает источник как «без показа».

## 2. Читатель и библиотека

- [x] 2.1 `Reader.region` и `Reader.ALL_REGIONS` в `src/philograph/library/reading.py`; правило открытости по регионам в `_visible_rows` одной проверкой; `Internal.published()` использует `ALL_REGIONS`; источник по умолчанию, текущий и запомненный берутся только из открытых. Тесты `tests/library/test_reading_chapters.py` (`regional-access` / «Библиотека закрывает текст ограниченных источников»): источник по умолчанию, запомненный источник, оглавление и глава для региона RU, другого региона и `None`.
- [x] 2.1а Список источников: закрытый для региона источник отдаётся строкой `{id, title, authors, restricted: true, regions}` без года, описания, лицензии; фильтры и поиск по названию действуют на неё; открыть её нельзя (`Reading.sources`, `library/app.py`). Тесты `source-library` / «Список источников» (сценарий «Источник закрыт для региона читателя») и `regional-access` / «Читатель вне РФ открывает библиотеку»; клиент `web/` показывает пометку «доступен в РФ» без перехода (тест `tests/web/test_library_reading.py`).
- [x] 2.2 HTTP-слой библиотеки: `library/app.py` строит `Reader` из заголовка `X-Philograph-Region` (нет заголовка — регион `None`); `resolve_paragraph` отвечает `source_unavailable` с причиной `region`, названием и авторами источника (как в списке), без текста, главы и раздела. Тесты `chapter-reading` / «Устойчивость ссылок на абзацы» и `regional-access` / «Ссылка на абзац закрытого источника» (в том числе «читатель вернулся в РФ»).
- [x] 2.3 Внутренний `GET /internal/access?region=XX` (идентификаторы закрытых для региона источников) и поля `regions`, `external_processing` в `version_paragraphs` (`library/app.py`, `Internal`). Тест `regional-access` / «Внутренние интерфейсы не фильтруют по региону»: версия закрытого источника отдаётся без региона, `published()` содержит его.

## 3. Шлюз

- [x] 3.1 `RegionSettings` и разбор заголовка страны (`PHILOGRAPH_REGION_HEADER`, доверие только при `PHILOGRAPH_TRUSTED_PROXY=1`, проверка значения «две латинские буквы», запасной `PHILOGRAPH_REGION_FALLBACK`) в новом `src/philograph/gateway/region.py`, чтение настроек рядом с `LimitSettings.from_env`. Новых зависимостей нет. Тесты в новом `tests/gateway/test_region.py`: «Читатель из РФ», «Запрос не от доверенного прокси», «Заголовка страны нет», «Локальный адрес в стенде разработки», значения `XX`/`T1`.
- [x] 3.2 В `gateway/app.py` `proxy` удаляет клиентские `X-Philograph-Region` и заголовок страны, ставит определённый шлюзом, добавляет `Cache-Control: private` и `Vary` на заголовок страны в ответы `/api/*`; страна не сохраняется и не попадает в журналы с привязкой к читателю. Тесты `regional-access` / «Регион читателя определяет шлюз»: подделанный заголовок, недоверенный прокси, «Регион не сохраняется», «Заголовок региона не пришёл» (проверка сервиса за шлюзом).
- [x] 3.3 Предупреждение оператору: доля запросов с неизвестным регионом как обезличенный счётчик шлюза (без страны и читателя) в `ops/alerts.py`, правило в документации оповещений. Проверка: тест правила в `tests/ops/test_alerts.py`.

## 4. Поиск и индексация

- [ ] 4.1 Миграция поиска 4: `docs.regions TEXT NOT NULL DEFAULT '*'`, `docs.external BOOLEAN NOT NULL DEFAULT TRUE` в `src/philograph/search/schema.py`; запись в `Indexer.index_version/_write_doc` из `version_paragraphs`. Тест `tests/search/` (миграция на старой базе, значения по умолчанию).
- [ ] 4.2 `Query.region` и `SearchBody.region` (нет значения — неизвестный регион); фильтр в `Searcher._filters` и `lexical`; полезная нагрузка `regions` и фильтр `MatchAny([region, "*"])` в `search/vectors.py`. Тесты `paragraph-search` / «Видимость и публикация», `regional-access` / «Поиск учитывает регион запроса»: RU, DE, без региона, лимит результатов заполняется открытыми.
- [ ] 4.3 Обработчик `source.access_changed` в `search/app.py` (`EVENTS`) и `Indexer.handle`: `UPDATE docs`, `VectorStore.set_regions` без вызова провайдера эмбеддингов. Тест: смена регионов меняет выдачу без вызова эмбеддера (счётчик вызовов фиктивного провайдера).
- [ ] 4.4 Шаг сверки регионов в `Indexer.reconcile` (расхождение с библиотекой чинится) и проверка, что закрытые источники не гасятся как лишние. Тест `regional-access` / «Внутренние интерфейсы не фильтруют по региону» / «Сверка индексов».

## 5. Ассистент

- [ ] 5.1 `assistant/app.py` читает заголовок региона, `AskRequest.region`; `_gather` добавляет `region` в запрос поиска; `assistant/clients.py` передаёт его. Тест `tests/assistant/`: поддельный поиск получает регион из заголовка.
- [ ] 5.2 Контекст онтологии: `OntologyContext` запрашивается с регионом (`assistant/ontology.py`); выделение и `source_id` закрытого источника игнорируются. Тесты `regional-access` / «Ассистент не использует закрытые источники»: вопрос из другого региона, выделение в закрытом источнике.
- [ ] 5.3 Проверка опоры: в `grounding.verify` ссылки на закрытые абзацы не могут появиться (регрессионный тест `answer-grounding`: ссылка на непереданный абзац удаляется, как раньше).

## 6. Сервис знаний

- [ ] 6.1 Единая функция «закрытые источники региона» (клиент `internal/access`) в `knowledge/app.py`; регион из заголовка передаётся в `Cards`, `Graph`, `Mentions`, `Assist`. Тест `tests/knowledge/`: фиктивная библиотека отдаёт множество закрытых источников.
- [ ] 6.2 `cards._row`, `graph`: скрытие `evidence`, ссылок `/p/<id>`, цитат и атрибуций-источников закрытых источников; утверждения остаются, статус не меняется (`knowledge/cards.py`, `knowledge/graph.py`). Тесты `regional-access` / «Онтология не раскрывает текст закрытых источников»: «Карточка для читателя вне РФ», «Граф».
- [ ] 6.3 `mentions.where_to_read` и `for_targets` скрывают закрытые источники (`knowledge/mentions.py`). Тест «Где читать».
- [ ] 6.4 `assist._paragraphs/_facts` не отдаёт текст абзацев закрытых источников (`knowledge/assist.py`). Тест `tests/knowledge/test_service.py`: контекст ассистента для региона DE без абзаца закрытого источника.

## 7. Внешняя обработка закрытых источников (обязательная, решение владельца)

- [ ] 7.1 Индексатор сохраняет `external` в `docs`, поиск отдаёт его в результате (`search/indexing.py`, `searching.py`). Тест `regional-access` / «Внешняя обработка закрытых источников» / «Индексация».
- [ ] 7.2 Ассистент не отправляет модели абзацы с `external = false` и показывает их ссылками с пометкой «найдено в источниках, не пересказывается» (`assistant/service.py`, поток событий NDJSON; клиент в `web/` показывает пометку). Тесты `tests/assistant/test_routing_grounding.py`: текст не уходит модели (фиктивная модель фиксирует `passages`), в потоке есть пометка со ссылкой.
- [ ] 7.3 Разбор неоднозначных упоминаний моделью пропускает источники без внешней обработки (`knowledge/mentions.py`). Тест: фиктивный разрешитель не вызван.
- [ ] 7.4 Поправка спецификации `source-registry` («Разрешения управляют обработкой и показом») при архивации: сценарий «Ответ ассистента» (расхождение кода и спецификации, найденное при подготовке).

## 8. Оценка, стенд, данные, документация

- [ ] 8.1 `evaluation/components.py` и наборы оценки: поле `region`, запросы идут с регионом; тесты `regional-access` / «Оценка и служебные запросы задают регион явно» в `tests/evaluation/test_evaluation.py`.
- [ ] 8.2 Стенд разработки: `PHILOGRAPH_REGION_FALLBACK=RU` в `scripts/dev_stack.py` и в окружении `tests/e2e/conftest.py`. Проверка: сквозные тесты зелёные.
- [ ] 8.3 Сквозной тест: читатель с заголовком региона через шлюз получает библиотеку, главу и поиск из закрытого источника для `RU` и не получает для `DE` (`tests/e2e/` или API-тест на подставных сервисах `tests/gateway/`).
- [ ] 8.4 Данные: `regions: [RU]` и `external_processing: false` (если задача 7 принята) у `public-domain-ru` в `sources/licenses.yaml` с обновлением комментария («метка» → «применяется сервисом»); `python -m philograph.library.catalog check` проходит; `sync` на стенде меняет учёт.
- [ ] 8.5 Добавить `regional-access` в `enforce` файла `openspec/traceability.yaml`; `python scripts/check_traceability.py` зелёный.
- [ ] 8.6 Развёртывание и документация: `docs/architecture/source-ingestion.md` (поле `regions`); `docs/operations/runbook.md` (требование «шлюз только через CDN», настройка CDN: передавать страну, не кэшировать `/api/*`, закрыть прямой доступ к серверу); `.env.example` (`PHILOGRAPH_REGION_HEADER`, `PHILOGRAPH_REGION_FALLBACK` только для стенда); `deploy/Caddyfile` (удаление клиентского `X-Philograph-Region` и заголовка страны, если запрос не от CDN); проверка конфигурации в `scripts/deploy.py` (`update` отказывает, если в `compose.prod.yaml` нет `PHILOGRAPH_TRUSTED_PROXY=1` или не задан `PHILOGRAPH_REGION_HEADER`) с тестом в `tests/platform/` или `tests/ops/` (`regional-access` / «Шлюз доступен только через CDN»).
- [ ] 8.7 Финальная проверка: `ruff check .`, `ruff format --check .`, `pytest` с `PYTHONPATH=src`, `openspec validate ru-only-sources`; архивация изменения в том же PR (`openspec archive ru-only-sources --yes`).

## Workflow follow-up

- Открытых вопросов нет: решения владельца внесены в design.md (раздел «Решения владельца»).
- Оценка объёма: группы 1-2 малые (около дня), 3-4 средние (по 1-2 дня), 5-6 средние (1-2 дня), 7 средняя и самая рискованная, 8 малая.
