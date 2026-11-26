# Tasks

Ветка `claude/reextract-claude` от `origin/claude/embedding-docker`. Задача — [spec-ontology-reextraction.md](../../../docs/process/spec-ontology-reextraction.md), диагноз — [extraction-diagnosis.md](../../../docs/audit/extraction-diagnosis.md).

## 1. План

- [x] 1.1 `proposal.md`, `design.md` («Выбор решения», «Открытые вопросы»), дельты `ontology-extraction` (MODIFIED ×3, ADDED ×6) и `llm-gateway` (MODIFIED «Сводка расходов», ADDED «Сведения о роли»), `tasks.md`, `progress.md`

## 2. Разработчик

- [x] 2.1 `knowledge/quotes.py` (нормализация, части по многоточию, `check`); `Statements._check`, перепроверка при событии библиотеки и `dating.check` — через него. Юнит-тесты `tests/knowledge/test_quotes_unit.py`.
- [x] 2.2 `knowledge/extraction_codes.py` (перечень, `code_for`); `Skip(reason, code)`; `EntityItems.index(…, on_drop)`. Юнит-тесты.
- [x] 2.3 `schema.py`: столбцы `filling_runs` и миграция `knowledge:10`. Юнит-тест миграции на SQLite (база до `knowledge:10` → столбцы есть, старые строки целы).
- [x] 2.4 `llm`: `LLMGateway.role_info`, маршрут `GET /v1/roles/{role}`, токены в `spend_summary`. Юнит-тесты `tests/llm/test_role_info_unit.py`.
- [x] 2.5 `filling.py`: мягкая схема шлюзу, `_item` (поштучная проверка), `apply_reply`, проверки абзаца и цитаты до сущностей, `_drop` с кодом и счётом, ветка «не 200» считается, коды отказов шлюза, таймаут по бюджету роли, модель роли в запуске и `Provenance`, метрики, `fail_run` и `knowledge.run.failed`, фрагменты по объёму; `main.py` — `PHILOGRAPH_EXTRACTION_TIMEOUT_SECONDS`. Юнит-тесты `tests/knowledge/test_reply_items_unit.py`, `test_fragments_unit.py`, `test_run_lifecycle_unit.py`.
- [x] 2.6 Промпт `ontology.extract`: художественный текст, атрибуция автору, поля без `null`.
- [ ] 2.7 `knowledge/external_extraction.py`, `knowledge/extraction_prices.yaml` (package data): `export`, `ingest` (`--replace`), `report`. Юнит-тесты `tests/knowledge/test_external_extraction_unit.py`.
- [ ] 2.8 `ruff check . && ruff format --check .`, `lint-imports`, `python scripts/check_traceability.py` (ADDED без тестов до 3.x — ожидаемо), `pytest -q tests/knowledge tests/llm`. Список тестов прежнего контракта — в `progress.md`.

## 3. Тестировщик

- [ ] 3.1 Сценарные тесты на **каждый** сценарий дельт `ontology-extraction` и `llm-gateway`; каждый проверяет вывод (база `filling_runs`, утверждения, файл задания/отчёта, ответ маршрута) и событие журнала с точным множеством ключей.
- [ ] 3.2 Нормативные тесты (`invariant=`), в том числе property:
  - фрагменты: в пределах главы, 1…`fragment_size` абзацев, покрытие всех абзацев, правило окончания по длине, `changed`;
  - цитата: любая подстрока абзаца (в том числе с типографскими заменами, обрамляющими кавычками, многоточием между частями по порядку) находится; перестановка частей и посторонний текст — нет; одно правило в `Statements.add`, перепроверке абзаца и датировке;
  - поштучная проверка: отказ элемента не отменяет остальные; `null` ≡ отсутствие; в базе только типы реестра;
  - коды: `code` всегда из перечня; `dropped = Σ drop_reasons = число событий`;
  - запуск: после `extract_version` нет `running` ни при каком исключении;
  - сирот нет при отказе по абзацу или цитате;
  - внешний: фрагменты `ingest` = `export`; стоимость по формуле; повтор без `--replace` ничего не пишет, с `--replace` — без удвоения.
- [ ] 3.3 Обновить тесты прежнего контракта, перечисленные разработчиком в `progress.md` (если согласен с причиной в дельте), записать решение.
- [ ] 3.4 Мутации — по одной и больше на каждое требование (`tests/mutations/reextract-with-claude/mutations.yaml`), прогон `scripts/mutation_check.py --change reextract-with-claude`.
- [ ] 3.5 `openspec/traceability.yaml` — `ontology-extraction`, `llm-gateway` уже под `enforce`; `python scripts/check_traceability.py` чисто.
- [ ] 3.6 `verification.md`, раздел «Тестировщик»: сырые итоги, выдержки событий, таблица «требование → сценарий → инвариант → мутация».

## 4. Ревьювер

- [ ] 4.1 Дифф против `origin/claude/embedding-docker`: соответствие дельтам, «Выбор решения», одна функция проверки ответа для шлюза и внешнего пути, одна нормализация цитаты, границы сервисов (`lint-imports`; знания не читают таблицы библиотеки), события без текста цитат.

## 5. Судья

- [ ] 5.1 Новый субагент без истории разработки: полнота `tasks.md`, каждый сценарий и инвариант в журнале тестировщика и в собственном прогоне, выборочные мутации, вердикт в `verification.md`. PR в draft до «принято».

## 6. Ведущий (после принятия)

- [ ] 6.1 Переизвлечение всех 208 источников: `export` → ответы Claude → `ingest --model claude-opus-5-5 …`; отчёт `report --since 2026-11-26 --out docs/audit/extraction-run-2026-11-26.md`; критерии R1–R8 задачи.
