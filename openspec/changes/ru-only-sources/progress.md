# Журнал: ru-only-sources

- Кто ведёт: ведущий инженер (роль: разработчик), сессия DSH.
- Ветка: `claude/ru-only-sources` (от `main` 3cc63b4); черновой PR #39.
- Статус: **сделаны группы 1–7 и задачи 8.1, 8.2, 8.4, 8.6** (учёт регионов, библиотека, шлюз,
  поиск, знания, ассистент, внешняя обработка, оценка, стенд, данные каталога, развёртывание
  и документация). Остались 8.3 (сквозной тест), 8.5 (traceability), 8.7 (финальная проверка
  и архив).
- Кейсы: `qa/cases.md` (UC-1…UC-30, TC-1…TC-67, EC-1…EC-52).

## Что сделано (2026-11-10)

- Миграция библиотеки **5** (`schema.py`): столбцы `license_kinds.regions`, `sources.regions`
  (JSON, NULL). Номер 5, а не 4: миграция 4 уже занята кодом страницы неразобранной части.
- `registry.py`: `License.regions`, `normalize_regions`, `effective_regions`,
  `effective_permissions`; `add_license_kind(..., regions=None)`, `Registry.regions()`,
  `Registry.license_kinds()`; запрет расширять регионы относительно вида; пустое пересечение —
  запрет показа; `change_license` пишет регионы и событие `source.access_changed` в outbox;
  смена регионов вида рассылает события по источникам этого вида.
- `catalog/`: `license.regions` в `sources/catalog.schema.json`, разбор в `catalog/model.py`,
  сравнение регионов в `ensure_license_kinds`.
- `reading.py`: `Reader.region`, `Reader.ALL_REGIONS`, `parse_region`, правило видимости в одном
  месте; закрытый источник остаётся в списке строкой `{id,title,authors,restricted,regions}`,
  не становится по умолчанию/текущим/запомненным; `resolve_paragraph` отвечает
  `source_unavailable` + `reason: region` + название и авторы; `Internal.access`,
  `regions`/`external_processing` в ответе версии, `published()` видит закрытые источники.
- `library/app.py`: `Reader` из заголовка `X-Philograph-Region`, эндпоинт
  `GET /api/v1/internal/access`.
- Клиент: `SourceItem | RestrictedSourceItem`, строка `li.source--restricted` с пометкой
  «Доступен в РФ» без кнопки «Читать»; `ParagraphLink` показывает «доступен только в России».
- Тесты: `tests/library/test_regions.py` (16), `tests/library/test_regions_api.py` (6),
  `tests/library/catalog/test_regions_sync.py` (3), `tests/web/test_region_restricted.py` (1).

## Прогоны

- `pytest -m "not e2e"`: 363 passed (было 322 требования к traceability), в т.ч. все новые.
- `tests/web` с `TMP`/`TEMP` внутри репозитория: 25 passed (Chromium работает).
- `ruff check`, `ruff format --check`: чисто. `lint-imports`: 3 contracts kept.
- `scripts/check_traceability.py`: 322 из 322.
- `python -m philograph.library.catalog validate`: 0 ошибок, 6 предупреждений о дублях названий.
- `openspec validate ru-only-sources`: valid (3 предупреждения о длинных требованиях).

## Что сделано (2026-11-12): группа 3 — шлюз

- Кейсы группы 3 дописаны до кода: `qa/cases.md` — R10–R13, UC-9…UC-13, TC-18…TC-27,
  EC-16…EC-25; R13 (проверка конфигурации развёртывания) отнесена к задаче 8.6.
- `src/philograph/gateway/region.py`: `RegionSettings.from_env` (`PHILOGRAPH_REGION_HEADER`,
  `PHILOGRAPH_TRUSTED_PROXY`, `PHILOGRAPH_REGION_FALLBACK`), `normalize_region` (две латинские
  буквы, верхний регистр, служебные `XX`/`T1` — неизвестный регион, неверный запасной регион
  игнорируется), `RegionResolver.region/dropped_headers/vary`.
- `src/philograph/gateway/app.py`: `build_app(..., regions=...)`; прокси удаляет клиентский
  `X-Philograph-Region` и заголовок страны, ставит свой `X-Philograph-Region`, считает
  `gateway.region` (`known`/`unknown` — без стран и посетителей), ответы `/api/*` получают
  `Cache-Control: private` и `Vary` на заголовок страны (прежние значения `Vary` сохраняются).
- `src/philograph/ops/alerts.py`: `UnknownRegionRule` над счётчиками шлюза, пороги
  `unknown_region_ratio` (0.10) и `unknown_region_min_requests` (100), правило `region`
  в `standard_rules`; общий сборщик метрик шлюза для правил ошибок и региона.
- `docs/operations/runbook.md`: строка правила «Регион читателя», пояснение про
  `PHILOGRAPH_REGION_HEADER`, доверенный прокси, счётчик и запасной регион.
- Закрыт finding F-2 раунда 1 («шлюз не отбрасывает клиентский `X-Philograph-Region`») — это
  была задача 3.2.
- Тесты: `tests/gateway/test_region.py` (9), `tests/gateway/test_region_proxy.py` (8),
  `tests/ops/test_alerts.py::test_unknown_region_rule` (1); в `test_rules_from_settings`
  ожидаемый набор правил дополнен `region`.

## Прогоны (2026-11-12)

- `pytest -q -m "not e2e"`: 367 passed, 115 skipped (Chromium без `TMP` в репозитории);
- `pytest -q tests/web` с `TMP`/`TEMP` = `<repo>/.tmp`: 127 passed;
- `pytest -q tests/gateway tests/ops`: 38 passed;
- `ruff check`, `ruff format --check`: чисто; `lint-imports`: 3 контракта; traceability 322/322;
  `openspec validate ru-only-sources`: valid (3 предупреждения о длине требований).

## Что сделано (2026-11-12): группа 4 и 8.2

- Кейсы группы 4 дописаны до кода: `qa/cases.md` — R14–R17, UC-14…UC-19, TC-28…TC-37,
  EC-26…EC-32; вводный абзац, «Как проверять», «Статус покрытия (группа 4)» и журнал обновлены.
- `search/schema.py`: миграция 4 — столбцы `docs.regions TEXT NOT NULL DEFAULT '*'`,
  `docs.external BOOLEAN NOT NULL DEFAULT TRUE` (регистрация миграции вызовом, чтобы функцию
  можно было звать в тесте миграции).
- `search/indexing.py`: `regions_column` (`*` / `,RU,BY,` / `,` для пустого пересечения) и
  `regions_payload` (`["*"]` / список / `[]`); запись `regions`/`external` в `_write_doc`,
  в `index_version` (ветка неизменённого текста) и в `_payload`; обработчик `source.access_changed`
  в `handle` и метод `_set_source_regions` (`UPDATE docs` + `VectorStore.set_regions`, без
  эмбеддера); шаг сверки регионов в `reconcile` (сравнение с `version_paragraphs`, закрытые
  источники не считаются лишними).
- `search/searching.py`: `Query.region`, фильтр региона в `_filters` (`region` → `*` или
  `LIKE '%,RU,%'`; без региона — только `*`), передача `region` в `vectors.search`.
- `search/vectors.py`: фильтр `MatchAny([region, "*"])` в `search`, метод `set_regions`.
- `search/app.py`: `SearchBody.region`, `source.access_changed` в `EVENTS`.
- 8.2: `PHILOGRAPH_REGION_FALLBACK=RU` в `scripts/dev_stack.py` и в `tests/e2e/conftest.py`
  (рядом с `PHILOGRAPH_RATE_BURST`).
- Тесты `tests/search/test_regions.py` (11): миграция, формат регионов, RU/DE/без региона,
  лимит открытыми, деградация с регионом, смена регионов событием без вызова эмбеддера,
  дубликат события, пустые регионы, сверка. Маркеры: `paragraph-search` / «Видимость и
  публикация», `regional-access` / «Поиск учитывает регион запроса», «Смена регионов у
  опубликованного источника», «Внутренние интерфейсы не фильтруют по региону».
- **Исправление группы 1 (найдено при разборе группы 4):** `library/registry.py` —
  `change_license` теперь кладёт в событие `source.access_changed` действующие регионы
  (пересечение с видом), а не сужение источника. Раньше при виде `[RU]` и отсутствии сужения
  событие уносило `null`, и поиск открывал текст всем регионам до сверки. Тест
  `tests/library/test_regions.py::test_access_changed_carries_effective_regions`, кейсы TC-38/EC-33.

## Прогоны (2026-11-12, группа 4)

- `pytest -q tests/search`: 31 passed.
- `pytest -q tests/search tests/library tests/gateway -p no:cacheprovider`: 183 passed.
- `pytest -q -m "not e2e" -p no:cacheprovider` (с `TMP`/`TEMP` = `<repo>/.tmp`): 509 passed,
  1 skipped (только PostgreSQL), 93 deselected (e2e).
- `ruff check .`, `ruff format --check .`: чисто. `lint-imports`: 3 контракта kept.
  `scripts/check_traceability.py`: 322 из 322.
- e2e (`tests/e2e`) не прогонялся: нужна сборка `web` (`npm run build`) и подъём стека; изменение
  8.2 — только переменная окружения, поведение проверяется на живом стенде раундом тестировщика.

## Что сделано (2026-11-12): 8.4 — данные каталога

- `sources/licenses.yaml`: у вида `public-domain-ru` — `regions: [RU]` и
  `permissions.external_processing: false`; комментарий исправлен: ограничение и запрет внешней
  обработки теперь применяются сервисом, а не остаются меткой.
- `python -m philograph.library.catalog validate` (временная база): записей 317
  (approved 304, rejected 10, draft 3), ошибок 0, предупреждений 6 (известные дубли названий).
- Синхронизация на стенде и проверка через `sync` — в раунде 6 (живой стенд).

## Что сделано (2026-11-12): группа 7 — внешняя обработка

- Индекс: `search/searching.py` отдаёт `external` в каждом результате (поле из `docs`, заполняется
  из `external_processing` при индексации); смыслового индекса у таких абзацев нет, провайдер
  эмбеддингов не вызывается (так было и раньше через `index_version`).
- Ассистент (`assistant/service.py`): выдача делится на `model_results` (уходит модели) и
  `hidden` (текст не уходит); для скрытых в потоке `notice found_not_retold` со ссылками
  (подпись — источник и раздел), `passages` для модели строятся только из `model_results`.
  **Правка при ревью:** пометка `no_library_support` теперь ставится, когда пересказывать нечего
  (`not model_results`), а не когда поиск пуст — иначе ответ по пустому контексту выдавался бы
  за основанный на источниках. Кейс TC-64, тест
  `test_only_hidden_results_marked_as_unsupported`.
- Знания (`knowledge/mentions.py`): признак берётся из `internal/versions/{id}/paragraphs`
  (поле `external_processing`), который `index_version` и так запрашивает — `internal/access`
  не расширялся, библиотека не менялась. Разрешитель неоднозначности не вызывается, упоминание
  остаётся неоднозначным.
- Клиент: `found_not_retold` в `SERVER_CODES`, строка i18n (ru/en), блок suggestions рендерится
  и для этой пометки.
- Спецификация (7.4): в дельту `specs/source-registry/spec.md` добавлено MODIFIED-требование
  «Разрешения управляют обработкой и показом» со сценариями «Внешняя обработка запрещена»,
  «Ответ ассистента», «Показ запрещён»; `openspec validate ru-only-sources` — valid.
- Кейсы: R24–R26, UC-28…UC-30, TC-56…TC-64, EC-46…EC-52.

## Прогоны (2026-11-12, группа 7)

- `pytest -q tests/search tests/assistant tests/knowledge tests/library`: 305 passed, 1 skipped.
- Полный `-m "not e2e"` с `TMP`/`TEMP` в `.tmp`: 532 passed (+1 новый тест ревью = 533),
  1 skipped, 93 deselected.
- `web`: `npm run build` успешно; `tests/web/test_assistant_dialogs.py` 14 passed,
  вместе с остальными затронутыми 25 passed.
- `ruff check`, `ruff format --check` (426 файлов), `lint-imports` (3 контракта),
  `check_traceability` 322/322, `openspec validate` — чисто.

## Что сделано (2026-11-12): группы 6 и 5 (параллельно)

- Группа 6 «Сервис знаний» (`src/philograph/knowledge/`): `closed_sources()` — один запрос
  `internal/access?region=XX` на запрос читателя (`X-Philograph-Region`; для
  `/internal/assistant/context` — поле `region` тела). Множество `closed` пробрасывается в
  `Cards._row`/`card`/`_misconceptions`, `Graphs._edge`/`build`, `Mentions.for_targets`/
  `where_to_read`, `AssistantKnowledge.describe`/`_paragraphs`: скрываются `evidence` (цитаты,
  ссылки `/p/<id>`), атрибуции-источники и строки «где читать»; утверждения и статус
  не пересчитываются. Недоступная библиотека — 503 `knowledge_unavailable` (безопасный отказ).
- Группа 5 «Ассистент» (`src/philograph/assistant/`): `parse_region` из заголовка, `AskRequest.region`,
  `_gather` кладёт регион в запрос поиска, `Ontology.prepare` — в тело контекста знаний; выделение
  и `source_id` закрытого источника работают как отсутствующие; `grounding.verify` — второй слой.
  Регион живёт в `AskRequest`, на `Assistant` не хранится.
- Дополнительно закрыта утечка, найденная разработчиком группы 6: сырые маршруты
  `GET /v1/entities/{id}/statements` и `GET /v1/graph` доступны через шлюз и отдавали цитаты,
  ссылки и атрибуции закрытых источников. Добавлен `without_closed` (по образцу карточки), оба
  маршрута фильтруются по региону; тесты `test_raw_statements_hide_closed_sources`,
  `test_raw_graph_hides_closed_sources` (TC-55).
- Уточнение по `parse_region`: служебные `XX`/`T1` теперь явно считаются неизвестным регионом
  в `library/reading.py` и `assistant/app.py` (раньше `XX` проходил как код страны, хотя спека
  называет его неизвестным). Тесты библиотеки и ассистента расширены.
- Тесты: `tests/knowledge/test_regions.py` (10), `tests/assistant/test_regional_access.py` (6),
  дополнения в `tests/knowledge/test_service.py` и `tests/library/test_regions.py`.
- Кейсы: `qa/cases.md` — R18–R23, UC-20…UC-27, TC-39…TC-55, EC-34…EC-45.

## Прогоны (2026-11-12, группы 5–6)

- `pytest -q tests/knowledge tests/assistant tests/library`: 270 passed, 1 skipped (PostgreSQL).
- Полный `-m "not e2e"` с `TMP`/`TEMP` в `.tmp`: 524 passed, 1 skipped, 93 deselected (до правки
  сырых маршрутов), после правки — пересчёт в раунде 5.
- `ruff check .`, `ruff format --check .` (425 файлов), `lint-imports` (3 контракта),
  `check_traceability` (322 из 322) — чисто.

## Что сделано (2026-11-13): задачи 8.3 и 8.5

- 8.3 Сквозной тест `tests/gateway/test_region_scope.py` (TC-68): настоящий шлюз, настоящая
  библиотека и настоящий ассистент с поиском за ним — клиент ходит только в шлюз. Проверено:
  читатель из РФ получает открытый источник, оглавление, главу и текст источника в контексте
  модели; читатель из DE — строку `restricted`, 404 на главе и отсутствие текста в контексте;
  клиентский `X-Philograph-Region` без страны от CDN не открывает источник; недоверенный прокси
  не даёт регион; запасной регион стенда подставляет `RU`. 5 тестов.
- 8.5 `regional-access` внесена в `enforce` файла `openspec/traceability.yaml`.
  `scripts/check_traceability.py`: **334 из 334** требований с тестами (было 322).

## Раунд dev_cycle 7 (2026-11-13) — проверка F-1

- Вердикт: **`pass`**, findings пустые; судья не вызывался. Тестировщик (Flash): 22 кейса
  на живом стенде (543 passed / 1 skipped / 93 deselected; целевые тесты TC-65 — 4 passed).
  Артефакты: `qa/round-7/`, `qa/screenshots/round-7/`, сводка — `qa/rounds/round-7.json`.
- Подтверждено исправление F-1: в одном ходе видны **обе** пометки — «Найдено в источниках,
  не пересказывается.» со ссылкой на абзац и «Ответ составлен без опоры на библиотеку»;
  клик по ссылке открывает `/read/<источник>/<глава>#p-<абзац>` с подсветкой; старая сессия
  с единственным `message` открывается без ошибок; обычные пометки (`no_answer`,
  `no_library_support`, ошибка соединения) работают как раньше.
- Регресс группы 7 и данные 8.4 — без расхождений (TC-56…TC-64, EC-47…EC-50, UC-28/DE).
- Не проверено: `no_answer` живьём (демо-провайдер эмбеддингов находит попадания на любой
  вопрос — отрисовка проверена по подставному потоку); `tests/e2e` (исключены командой;
  сквозной путь покрыт `tests/gateway/test_region_scope.py`); настоящий CDN (8.6);
  EC-51 — клавиатурный обход ссылки отдельно не проверялся.
- Наблюдение вне кейсов (на будущее): в разделе «Ассистент» показывается переключатель
  «Только выбранный учебник», хотя вопрос идёт по всей библиотеке — поведение было и до этого
  изменения, в спецификации не описано, в findings не заносилось.

## Раунд dev_cycle 6 (2026-11-12) — группа 7 и данные 8.4

- Вердикт: **`fix`**. Тестировщик: 21 из 22 кейсов на живом стенде (533 passed в автотестах);
  весь серверный путь закрытого источника проверен: индексация без эмбеддера, текст не уходит
  модели, пометка со ссылками, отсечение для DE, метки 8.4 через настоящий `sync`.
  Артефакты — `qa/round-6/`, `qa/screenshots/round-6/`.
- **F-1 (`product-bug`, major) — исправлено 2026-11-13.** Клиент хранил одну пометку на ход
  (`Turn.message`), поэтому `notice` «без опоры на библиотеку» затирал `found_not_retold`
  со ссылками на найденные абзацы. Теперь ход хранит список `notices`, каждая пометка рендерится
  своим блоком со своими ссылками, старые сессии с единственным `message` читаются
  (`normalizeTurn`). Клиент собран (`npm run build`), тесты
  `test_t22c_two_notices_keep_both_with_link` и `test_t22d_legacy_single_message_session_opens`,
  кейс TC-65.
- **F-2 (`spec-gap`, minor) — исправлено.** Модель-разрешитель неоднозначных упоминаний никогда
  не подключалась в рабочем сервисе знаний (`Mentions(statements, library)` — без resolver).
  Это не регресс группы 7: уточнено требование `regional-access` (разбор моделью не подключён —
  отдельное изменение), переписаны TC-63 и EC-52.

## Что сделано (2026-11-13): задачи 8.1 и 8.6

- 8.1 Оценка: `evaluation/datasets.py` — миграция 3 (`datasets.region`), `create(..., region=...)`
  с нормализацией (`XX`/`T1` → неизвестный), `Datasets.region()`; `snapshot()` отдаёт `region`
  в каждом элементе. `evaluation/components.py` — `search_evaluator`, `assistant_evaluator`,
  `draft_questions` передают регион набора в запросы. Тест
  `test_evaluation_queries_carry_dataset_region` (TC-66).
- 8.6 Развёртывание и документация: `docs/architecture/source-ingestion.md` (поле `regions`,
  `external_processing`), `docs/operations/runbook.md` (шлюз только через CDN, настройка CDN,
  переменные, что делать при высокой доле неизвестных регионов), `.env.example`
  (`PHILOGRAPH_REGION_HEADER`, `PHILOGRAPH_TRUSTED_PROXY`, `PHILOGRAPH_REGION_FALLBACK` только
  для стенда), `deploy/Caddyfile` (снимает клиентский регион и заголовок страны не от CDN,
  не кэширует `/api/*`), `compose.prod.yaml` (переменные региона у шлюза), `scripts/deploy.py`
  (проверка конфигурации до сборки, отказ с сообщением оператору). Тесты
  `test_deploy_requires_region_config`, `test_caddyfile_strips_region_headers_and_no_api_cache`
  (TC-67).

## Прогоны (2026-11-13, после F-1, 8.1, 8.6)

- `pytest -q -m "not e2e"` с `TMP`/`TEMP` в `.tmp`: **538 passed**, 1 skipped (PostgreSQL),
  93 deselected.
- `pytest -q tests/web`: **130 passed** (клиент пересобран, `web/dist` свежий).
- `ruff check`, `ruff format --check` (426 файлов), `lint-imports` (3 контракта),
  `check_traceability` 322/322, `openspec validate ru-only-sources` — valid.

## Раунд dev_cycle 5 (2026-11-12) — группы 5–6

- Вердикт: **`pass`**, findings пустые; судья не вызывался. Тестировщик (Flash): 38 кейсов
  (UC-20…UC-27, TC-39…TC-55, EC-34…EC-45) на живом стенде — все пройдены; 527 passed / 1 skipped
  (PostgreSQL) / 93 deselected автотестов, 43 целевых.
  Артефакты: `qa/round-5/` (`live-report.json`, журналы стенда, `harness/`),
  `qa/screenshots/round-5/`, сводка — `qa/rounds/round-5.json`.
- Проверено на живом стенде: карточка, граф, «где читать», упоминания и контекст ассистента
  скрывают цитаты, ссылки `/p/<id>` и атрибуции закрытых источников, утверждения и статус
  `sourced` остаются; сырые `/v1/entities/{id}/statements` и `/v1/graph` через шлюз тоже без
  цитат закрытых источников (TC-55); недоступная библиотека — 503 `knowledge_unavailable`;
  ассистент для DE не видит текста закрытого источника в промпте модели, для RU — видит;
  выделение и `source_id` закрытого источника не используются, `grounding.verify` удаляет
  выдуманную ссылку `[99]`; `XX`/`T1` — неизвестный регион, `ru` — RU.
- Не проверено: `tests/e2e` (93 deselected — нужен подъём полного стека, остаётся на 8.3);
  настоящий CDN и проверка конфигурации развёртывания (8.6); интерфейс ассистента в браузере
  не прокликивался (ответ проверен по HTTP, промпту и журналам; в браузере — карточка).
- Инструмент: `dev_cycle` по-прежнему видит `maxRounds=3` (читается при старте профиля), раунд
  снова запущен эквивалентным workflow. После перезапуска DSH лимит 5 вступит в силу.

## Раунд dev_cycle 4 (2026-11-12) — группы 4 и 8.2

- Вердикт: **`pass`**, findings пустые; судья не вызывался (при пустых findings `round.js`
  пропускает фазу разбора). Тестировщик (Flash) — 29 живых проверок без провалов, 510 passed /
  1 skipped (PostgreSQL) / 93 deselected автотестов, 27 целевых, 4 скриншота.
  Артефакты: `qa/round-4/` (`live-report.json`, логи, `harness/`), `qa/screenshots/round-4/`,
  сводка — `qa/rounds/round-4.json`.
- Проверено на живом стенде: поиск отсекает абзацы источника `[RU]` для DE и для запроса без
  региона (по словам и по смыслу, `semantic_used=true`), лимит заполняется открытыми; событие
  `source.access_changed` меняет видимость без вызова эмбеддера (счётчик `llm.call.completed
  (role=embeddings)` 4 → 4), повтор — `search.index.duplicate`, `regions: []` закрывает всем;
  `reconcile` чинит расхождение и не гасит закрытый источник; миграция 4 на базе версии 3;
  `change_license` уносит `regions: ["RU"]` при виде `[RU]` без сужения; стенд с
  `PHILOGRAPH_REGION_FALLBACK=RU` открывает ограниченный источник через шлюз, а прямой запрос
  в библиотеку без региона по-прежнему видит строку «Доступен в РФ».
- Не проверено: `tests/e2e` (93 deselected — нужен подъём стека, остаётся на 8.3); настоящий CDN
  и проверка конфигурации развёртывания (8.6); группы 5–8 (кода ещё нет). На стенде не задан
  `PHILOGRAPH_REGION_HEADER`, поэтому `Vary` на этом стенде не проверялся — он закрыт раундом 3.
- Уточнение по инструменту: `dev_cycle` прочитал `maxRounds=3` при старте профиля, хотя профиль
  уже обновлён до 5 — раунд запущен эквивалентным workflow с теми же промптами, схемами и ролями.
  После перезапуска DSH раунды 5+ пойдут обычным путём.

## Раунд dev_cycle 3 (2026-11-12)

- Вердикт: **`fix`**. Тестировщик: 385 passed в общем прогоне (115 skipped — Chromium без `TMP`
  в репозитории), 27 passed по `tests/gateway` и `tests/ops`, 25 passed клиентских с `TEMP`
  в репозитории; независимый стенд из четырёх шлюзов (доверенный прокси, недоверенный,
  запасной регион, без настроек) — 32 шага, 2 нарушения. Артефакты: `qa/round-3/`,
  `qa/screenshots/round-3/` (24 PNG).
- Кейсы TC-18…TC-24, TC-26, TC-27, EC-16…EC-20, EC-22…EC-25 — пройдены.
- F-4 (`product-bug`, major): TC-25 и EC-21 — шлюз дописывал второй `Cache-Control` вместо
  замены: httpx отдаёт имя в нижнем регистре (`cache-control`), код присваивал `Cache-Control`,
  и клиент получал «public, max-age=300» от сервиса вместе с «private» шлюза. **Исправлено**:
  прежние значения снимаются без учёта регистра (как в `_add_vary`); тест
  `test_api_response_is_private_and_varies` усилен — поддельный сервис отдаёт свой
  `Cache-Control: public, max-age=300`, проверяется ровно одно значение через
  `get_list("cache-control") == ["private"]`. Живая проверка harness
  `qa/round-3/harness/headers_evidence.py`: один `Cache-Control: private`,
  `Vary: Accept-Encoding, CF-IPCountry`.
- Не проверено: настоящий CDN и проверка конфигурации развёртывания (R13, задача 8.6); штатный
  `scripts/dev_stack.py` без `PHILOGRAPH_REGION_FALLBACK` (задача 8.2) — на нём регион неизвестен
  по замыслу; группы 4–8 не проверялись, задач нет.

## Раунд dev_cycle 1 (2026-11-10)

- Вердикт: `fix`. Тестировщик: все UC-1…UC-8, TC-1…TC-17, EC-1…EC-15 прошли по поведению;
  13 скриншотов и отчёты — `qa/screenshots/round-1/`, `qa/round-1/`.
- F-1 (`test-artifact`, major): `tests/web/test_region_restricted.py` считал строки сразу после
  `page.goto` без ожидания отрисовки списка — гонка. **Исправлено**: добавлен
  `page.wait_for_selector("li.source--restricted")`; 5 прогонов подряд зелёные.
- F-3 (`test-artifact`, minor): EC-4 в `qa/cases.md` ожидал строку «доступен в РФ» при пустом
  пересечении регионов, что противоречит спеке (пустое пересечение = нет разрешения на показ).
  **Исправлено**: кейс приведён к R3/TC-4 и `source-library`.
- F-2 (`product-bug`, minor): шлюз не отбрасывает клиентский `X-Philograph-Region` — это задача
  **3.2 группы 3**, а не групп 1–2. В охват этого PR не входит; переносится в следующий шаг
  (группа 3 целиком: `RegionSettings`, доверие только прокси, `Vary`, счётчик неизвестных).
  Доказательство расхождения — `qa/round-1/api-run.log`.
- Не проверено: Postgres (только SQLite), реальная доставка `source.access_changed` в поиск и
  знания (группы 4–6), откат старого кода на новой базе (задача 8).

## Раунд dev_cycle 2 (2026-11-10)

- Вердикт: **`pass`**. Тестировщик: 257 passed командой
  `.venv/Scripts/python -m pytest -q tests/library tests/web -p no:cacheprovider` (130 + 127),
  `tests/web/test_region_restricted.py` — 5/5 зелёных (гонка F-1 не воспроизводится).
  Независимый стенд: 58 HTTP/учёт/события, 16 браузерных сценариев, 6 регрессионных, доступность
  и раскладка — 0 провалов. Артефакты: `qa/round-2/`, `qa/screenshots/round-2/` (19 PNG).
- F-4 (`test-artifact`, minor): harness раунда 1 искал корень по `parents[2]` и попадал в каталог
  `qa`, поэтому скриншоты раунда 1 не воспроизводились. **Исправлено**: `_repo_root()` ищет вверх
  до `pyproject.toml` (как в round-2); `diag.py` теперь отдаёт HTML библиотеки (13140 байт, 4 строки
  списка) вместо `{"detail":"Not Found"}`.
- F-2 (шлюз не отбрасывает клиентский `X-Philograph-Region`) остаётся запланированной задачей 3.2
  группы 3 — в охват групп 1–2 не входит, судья подтвердил, что дефектом этих групп не является.
- Поведенческих расхождений по группам 1–2 нет.

## Следующий шаг

- 8.3: сквозной тест «читатель с заголовком региона через шлюз получает библиотеку, главу и поиск
  из закрытого источника для RU и не получает для DE».
- 8.5: добавить `regional-access` в `enforce` файла `openspec/traceability.yaml`, добиться
  зелёного `scripts/check_traceability.py`.
- Раунд `dev_cycle` 7 по F-1 (две пометки в клиенте) — тестировщик и судья.
- 8.7: `ruff check .`, `ruff format --check .`, `pytest`, `openspec validate`, архивация
  изменения в том же PR; затем обновить описание PR #39 и снять с черновика.

## Проблемы и замечания

- Environment: браузерные тесты (`tests/web`) и Playwright проходят только если `TMP`/`TEMP`
  указывают внутрь репозитория — иначе Chromium падает с `EPERM mkdtemp`; при работе в песочнице
  DSH тесты без этого падают полностью (`PermissionError` на временных каталогах).
- В `tasks.md` задача 1.1 называет миграцию 4, фактически применена 5 (4 занята). Число в задаче
  исправлять не стал: история изменений важнее, отметка стоит.
- Старое замечание `progress.md` о расхождении кода и спецификации (ассистент и разбор упоминаний
  не проверяют `external_processing`) относится к группе 7 — не закрыто.
- Клиентская проверка строки списка идёт через шлюз без заголовка региона: для браузера регион
  неизвестен, поэтому источник `[RU]` закрыт. Настоящий CDN — группа 3 и 8.3.
- **Расхождение кода и спецификации (группа 1, `src/philograph/library/registry.py`) — исправлено
  2026-11-12.** `change_license` клал в событие `source.access_changed` поле `regions` равным
  сужению источника, а не действующим регионам (пересечению с видом). Если у вида есть регионы
  (`[RU]`), а у источника сужения нет (`lic.regions is None`), событие уносило `regions: null`
  вместо `["RU"]`, и обработчик поиска записывал `*` (везде) — текст уходил всем регионам до
  следующей сверки `reconcile`. Теперь событие несёт действующие регионы (как путь синхронизации
  каталога `_share_kind_access`); тест `test_access_changed_carries_effective_regions`,
  кейсы TC-38/EC-33.
