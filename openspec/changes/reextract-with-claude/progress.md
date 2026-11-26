# Progress

## 2026-11-26 — планирование (разработчик, субагент `coder`)

- Ведёт субагент `coder` по поручению ведущего. Ветка `claude/reextract-claude` от `origin/claude/embedding-docker` (63a07cc), worktree `.claude/worktrees/reextract`.
- CLI `openspec` нет: файлы созданы вручную по образцу `improve-extraction-naming`.
- Прочитано: задача (2.4, 2.5, 3), диагноз (П1–П12, раздел 6), `filling.py`, `entity_items.py`, `statements.py` (`_check`, событие библиотеки), `dating.py`, `registry.output_schema`, шлюз (`structured`, `_complete`, `spend_summary`), `ServiceClient`.
- Решения разработчика по спорному — design.md, «Выбор решения» и «Открытые вопросы»:
  1. библиотека для внешнего извлекателя — только через HTTP-клиент (режима `--library-db` нет);
  2. тариф — `knowledge/extraction_prices.yaml`, аргументы важнее;
  3. модель и бюджет роли — новый маршрут шлюза `GET /v1/roles/{role}` (дельта `llm-gateway`);
  4. повторный `ingest` — отказ без `--replace`, с `--replace` — откат прежнего внешнего запуска: проверка чтением показала, что ключ утверждения не удваивает утверждения, но `_attach` удвоил бы подтверждения и атрибуции;
  5. добавлен столбец `source_id` (не было в списке ведущего): без него отчёт не знает источник запуска без запроса к библиотеке;
  6. неизвестная `stance` — отказ `stance_invalid`.
- Тесты прежнего контракта, которые новая дельта меняет (правит тестировщик, 3.3):
  - `tests/knowledge/test_extraction_entities.py::test_schema_with_entities_and_dating` — ждёт `enum` типов в `entities` схемы шлюза и `required` у `dating`; ADDED «Проверка ответа по утверждениям» запрещает перечни в мягкой схеме;
  - `tests/knowledge/test_extraction_entities.py::test_new_entity_without_type_dropped_by_code` — ждёт у `knowledge.extraction.dropped` ровно `{reason}` сверх контекста; ADDED «Коды причин отбраковки» добавляет обязательный `code`.

Статус: 1.1 сделан, следующий — 2.1.

## 2026-11-26 — 2.1 сверка цитаты

- `knowledge/quotes.py`: `normalize`, `parts`, `check`, `found`. `Statements._check`, перепроверка изменённого абзаца и `dating.check` — через него; `_norm_quote` и `dating._quote_key` удалены.
- Последствие: патчи мутаций `tests/mutations/improve-extraction-naming/quote-*.patch` и `check-order-*.patch` ссылаются на удалённый `dating._quote_key` и больше не применяются (изменение влито). Режим `--coverage` патчи не применяет; полный `--change improve-extraction-naming` потребует обновления патчей — тестировщику.
- Прогон: `pytest -q tests/knowledge/test_quotes_unit.py` — 18 passed; `test_dating_unit.py test_statements.py test_entity_dating_extraction.py test_filling.py` — 114 passed.

## 2026-11-26 — 2.2 коды причин

- `knowledge/extraction_codes.py`: перечень `CODES`, `code_for`. `Skip(reason, code)`; `EntityItems.index(…, on_drop)` — `null` в необязательных полях элемента как отсутствие, не-список `entities` — пусто. Событие `knowledge.extraction.dropped` — обязательный `code`. Временная точка в `Filling._drop` (`code_for`) — до 2.5.
- Прогон: `test_extraction_codes_map_unit.py test_extraction_codes_unit.py test_entity_items_unit.py` — 36 passed.

## 2026-11-26 — 2.3 миграция `knowledge:10`

- `filling_runs`: `extractor`, `source_id`, `fragments`, `duration_seconds`, `input_tokens`, `output_tokens`, `drop_reasons` (JSON), `failure`; миграция `_run_metrics` по образцу `knowledge:9` (пропуск существующих столбцов). Статус `failed` добавлен в комментарий перечня.
- Прогон: `test_run_metrics_migration_unit.py` — 2 passed (база до миграции на SQLite, повтор, свежая база).

## 2026-11-26 — 2.4 шлюз: сведения о роли, токены в сводке

- `LLMGateway.role_info(role)` и `GET /v1/roles/{role}` (404 `unknown_role`); `Store.spend_summary` — суммы `input_tokens`, `output_tokens`.
- Тест прежнего контракта, который меняет новая миграция (тестировщику, 3.3): `tests/knowledge/test_mentions_cards.py` (`assert ks.migrations.latest() == 9`) — теперь последняя `knowledge:10`.
- Прогон: `pytest -q tests/llm` — 23 passed (в том числе `test_role_info_unit.py`, 3).

## 2026-11-26 — 2.5 `filling.py`: поштучная проверка, коды, запуск, метрики, фрагменты

- Мягкая схема шлюзу (`_gateway_schema`), `_schema()` реестра остаётся контрактом и данными промпта; `_item` — поштучная проверка (порядок дельты), абзац и цитата — до `_resolve`; `apply_reply` — общий путь для шлюза и внешнего извлекателя; `drop`/`drop_fragment`/`_drop` — единственное место события и счёта; ветка «не 200» и недоступность шлюза — коды `model_*`; `_role()` — модель и таймаут по `GET roles/strong`; `start_run`/`finish_run`/`fail_run` с метриками, `knowledge.run.failed`; `fragments` по объёму (`fragment_chars=3000`, `fragment_size=30`). `EntityItems.date*` получают `model`. `main.py` — `PHILOGRAPH_EXTRACTION_TIMEOUT_SECONDS`.
- Отклонение от первой версии дельты: пустой `subject`/`object` — не `schema_item`, а отказ правил названий (`entity:empty`), иначе ломался сценарий `entity-naming` «Пустое название». Сценарий «Отклонения в одном ответе»: «без `quote`» заменено на `quote: 7` — элемент без обязательного поля отвергает уже мягкая схема шлюза (требование ведущего: обязательные поля в схеме шлюза); у внешнего извлекателя — `schema_item`. Дельта поправлена.
- Тесты прежнего контракта, падающие из-за `code` в событии (тестировщику, 3.3): в `tests/knowledge/test_entity_dating_extraction.py` — `test_century_not_in_quote`, `test_era_mismatch`, `test_year_not_in_quote`, `test_number_inside_number`, `test_single_year_person` (ждут ровно `{run_id, reason}`), и два из 1.1 в `test_extraction_entities.py`.
- Прогон: `test_reply_items_unit.py` — 24 passed; `test_filling.py test_extraction_entities.py test_context_unit.py test_entity_naming.py test_entity_dating_extraction.py test_person_quality.py` — до правки пустого названия 9 failed / 221 passed; после — падают только 7 перечисленных тестов прежнего контракта (полный прогон пакета — в 2.8).

## 2026-11-26 — 2.6 промпт `ontology.extract`

- Добавлены правила: «персонажи художественного текста — не персоны …», «атрибутируй автору произведения: attributed_to — автор»; к «не включай в объект вовсе» — «не пиши null».
- Проверка: обе фразы есть в инструкции (нижний регистр); `test_extraction_entities.py -k prompt_language` — 6 passed.

## 2026-11-26 — 2.7 внешний извлекатель

- `knowledge/external_extraction.py`: `task`/`export` (JSONL: строка `task` + строки `fragment`), `read_replies` (JSON-объект или JSONL), `ingest` (через `Filling.apply_reply`; `reply_missing`, `reply_invalid`; `--replace` — откат прежних внешних `done`-запусков версии), `report`/`write_report`, `Price`/`price_for` (тариф `knowledge/extraction_prices.yaml`, аргументы важнее), `build` (база знаний + клиент библиотеки, кэш текстов абзацев версии), `main` (коды выхода 0/2/3). События `knowledge.extraction.exported`, `knowledge.extraction.report`.
- В дельту «Отчёт о запусках» добавлен столбец «статус» (видно `failed`).
- Прогон: `test_external_extraction_unit.py` — 9 passed (в том числе повтор без/с `--replace`: число утверждений, подтверждений, атрибуций после `--replace` то же).

## 2026-11-26 — 2.8 проверки перед передачей

- `ruff check .` — чисто; `ruff format --check .` — 710 files already formatted; `lint-imports` — 3 kept, 0 broken (с `PYTHONPATH` worktree); `check_traceability.py` — 420 из 427: нет тестов у шести ADDED `ontology-extraction` и ADDED `llm-gateway` «Сведения о роли» — ждут тестировщика (3.1).
- `pytest -q tests/knowledge` (до правки миграции): 12 failed, 1677 passed, 1 skipped (29 мин). Разбор:
  - миграция `knowledge:10` падала на частичных схемах проверок миграций (нет `filling_runs`) — исправлено: без таблицы миграция ничего не делает;
  - юнит-тесты `test_retired_unit.py`, `test_run_actions_unit.py` ждали, что последняя миграция 9 — ожидание дополнено `10` (это юнит-тесты миграций, не сценарии);
  - **тесты прежнего контракта — тестировщику (3.3):** `test_mentions_cards.py::test_migration_6_adds_mention_position` (`latest() == 9`), `test_portraits.py::test_migration_7_adds_portraits_and_keeps_old_data` (`upgrade == [7, 8, 9]`), пять тестов `test_entity_dating_extraction.py` и два `test_extraction_entities.py` (см. 2.5);
  - **не из этого изменения:** `test_epoch_dates_unit.py::test_repository_manifest_is_valid_and_unconfirmed` — проверяет `sources/epochs.yaml` (у эпох есть QID), файл в ветке не менялся — падает и на базе.
- После правки: `test_retired_unit.py test_run_actions_unit.py test_run_metrics_migration_unit.py` — 7 passed; `test_portraits.py` и `test_mentions_cards.py` падают только на номере последней миграции.
