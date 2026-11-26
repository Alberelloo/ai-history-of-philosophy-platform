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
