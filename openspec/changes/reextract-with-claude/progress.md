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
