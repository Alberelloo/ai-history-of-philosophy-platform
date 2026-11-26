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

## 2026-11-26 — дефекты тестировщика Д1–Д3

- Д1: `Filling._item` — номер абзаца строкой принимается только из ASCII-цифр (`[0-9]+`); `"²"` проходило `str.isdigit()` и роняло `int()` → весь запуск `failed`. Теперь — `schema_item` у элемента.
- Д2: `external_extraction.ingest` — то же для ключа ответа → `reply_invalid`.
- Д3: `_run_spend` — сводка расходов не JSON или не список → нули; `finish_run` перенесён внутрь `try` в `extract_version`: сбой завершения тоже даёт `failed`, а не `running`.
- Прогон: `tests/knowledge/test_reextract_*.py test_reply_items_unit.py test_external_extraction_unit.py` — 321 passed; ruff чисто. Тесты не менялись.

## Ревью — 2026-11-26, коммит 09f3911

База дифа — `origin/claude/embedding-docker`. Сделано: `ruff check .` и `ruff format --check .` чисто, `lint-imports` — 3 kept, 0 broken, `check_traceability.py` — 427 из 427. Миграция `knowledge:10` проверена на PostgreSQL 16 (контейнер): база дошла до 9, в ней строка `running` с `model='main'`, затем upgrade дал `[10]`. Строка цела, у новых столбцов NULL, типы `DOUBLE PRECISION`/`JSON`/`TEXT`, запись `drop_reasons={...}` работает. На том же PostgreSQL прошли `test_reply_items_unit.py`, `test_run_metrics_migration_unit.py` и `test_external_extraction_unit.py` — 35 passed. Пробы ниже запускались из временных файлов тестов, после прогона файлы удалены.

Блокирует:
1. `src/philograph/knowledge/entity_items.py:115` и `src/philograph/knowledge/filling.py:564-574` — у элементов `entities` вид полей не проверяется, а мягкая схема (`"type": {}`, `"dating": {}`) теперь пропускает через шлюз что угодно. Вход через настоящий шлюз: `{"statements":[<верное>], "entities":[{"name":"Кант","type":["person"]}]}`. Итог: `TypeError: unhashable type: 'list'` (`list in set`), запуск `failed`, верное утверждение того же ответа потеряно для счёта (`created=0`). Второй вход: `"dating": {"text": 1724, "paragraph": 1, "quote": "..."}` (год числом — правдоподобный ответ модели). Итог: `AttributeError: 'int' object has no attribute 'strip'`, запуск `failed`. Так же падает `dating.quote` числом: `TypeError` в `quotes.normalize`. Нарушены «отказ одного элемента MUST NOT отменять запись остальных» и «Запуск всегда завершается» по смыслу: запуск завершается, но весь, а не один элемент. На внешнем пути то же самое роняет `ingest`, и это ведёт к п. 2. Что сделать: в `EntityItems.index` проверять вид `type` (строка) и полей `dating` (`text`, `quote` — строки, `paragraph` — целое или строка ASCII-цифр, как в `_item`) и при отказе давать `schema_item` (или `dating_*`) через `on_drop`. Правило вписать в дельту «Проверка ответа по утверждениям», шаг 1 (сейчас там только поля `statements`). Тестировщику — инвариант «любой JSON-ответ не роняет запуск» (property по произвольным значениям полей `entities`).
2. `src/philograph/knowledge/external_extraction.py:208-222, 247-248` — `--replace` откатывает только запуски `done`, а прерванный `ingest` оставляет запуск `failed` с уже записанными утверждениями. Проба: два фрагмента, сбой на втором ответе (запуск `failed`, одно утверждение), затем `ingest ... --replace`. Итог: код 0, запуски `[failed, done]`, утверждений 2, подтверждений 3, атрибуций 3, то есть у утверждения первого фрагмента подтверждение и атрибуция удвоены. Без `--replace` повтор тоже проходит (прежнего `done` нет) и тоже удваивает. Это противоречит дельте («с `--replace` … подтверждения и атрибуции не удваиваются») и выбору 5 в design.md. При 208 источниках и п. 1 случай реальный. Что сделать: `_previous` берёт внешние запуски версии в статусах `done` и `failed`: без `--replace` отказ с кодом 2, с `--replace` откат обоих. Дельту «Внешний извлекатель» поправить («при завершённом или прерванном внешнем запуске»), инвариант тестировщика `test_replace_leaves_other_runs_alone` дополнить случаем `failed`.

Желательно:
1. `src/philograph/knowledge/quotes.py:31,50-63` — регресс для цитат с авторским многоточием. Абзац «Он молчал... Потом сказал: да.», цитата «Он молчал... Потом» даёт `quote_too_short` (части по 9 и 5 знаков), а прежнее правило подстроки её принимало. Это же правило работает при перепроверке изменённого абзаца (`statements.py:1175`), поэтому такие подтверждения на боевой базе при переиздании абзаца станут `lost`. Предложение: сначала искать нормализованную цитату целиком и только потом делить по многоточию. Если правку принять, нужен пункт в дельте.
2. `src/philograph/knowledge/external_extraction.py:247-249` — откат прежнего запуска идёт до `start_run` и вне `try`. Если новая запись затем упадёт, версия останется без утверждений. При наличии п. 2 это переживаемо (повтор с `--replace`), но об этом стоит написать в docstring или runbook.
3. `src/philograph/knowledge/entity_items.py` `date_item` — сущность из `entities` создаётся `resolve` до проверки датировки. Отказ `dating_*` оставляет сироту (проба: `dating.paragraph: "1"` → `dating_paragraph`, а персона «Кант» создана). Вне «Сирот нет» (там утверждения), но П7 диагноза здесь не закрыт. Стоит отметить в «Открытых вопросах».
4. `src/philograph/knowledge/external_extraction.py:428-431, 481-524` — если версии нет (библиотека отвечает 404), получаем `KeyError: 'permissions'` с трассировкой и кодом выхода 1. Стоит сделать понятный отказ с кодом 2.
5. `read_replies` — повтор номера фрагмента в JSONL молча перезаписывает ответ. Стоит отказывать (код 2) или считать `reply_invalid`.
6. Документы: новая переменная `PHILOGRAPH_EXTRACTION_TIMEOUT_SECONDS` и команда `external_extraction` не описаны ни в runbook, ни в docs (п. 7 скилла). `tasks.md` 2.5 ссылается на несуществующие `test_fragments_unit.py` и `test_run_lifecycle_unit.py`: юниты собраны в `test_reply_items_unit.py`.
7. `quotes.py:19-20` — нормализация шире дельты: удаляются `​⁠﻿`, к кавычкам приводятся `″′` и обратная кавычка. Это безвредно, но правило теперь описано не полностью. Стоит дописать в дельту или убрать.
8. Повтор задания очереди после `failed` (design, «Открытые вопросы» 1) удваивает подтверждения на шлюзовом пути. Вместе с п. 1 блокирующих это частый случай, поэтому стоит завести задачу, а не оставлять открытым вопросом.

Проверено и в порядке:
- граница сервисов: тексты абзацев идут только через `internal/versions/{id}/paragraphs` и `internal/paragraphs/{id}`, SQL к `library` нет;
- шлюз и внешний путь проходят одну функцию `Filling.apply_reply` → `_item` → `_store`, дублирования проверки нет;
- нормализация цитаты одна (`quotes`), `_norm_quote` и `_quote_key` удалены;
- `rollback_run` удаляет только строки с `run_id` запуска, а утверждение — только если у него не осталось подтверждений и атрибуций. Утверждения, подтверждённые другими запусками (шлюз, другой учебник), остаются, это покрывает `test_replace_leaves_other_runs_alone`;
- в DDL миграции только константы; текст модели не попадает ни в адреса, ни в SQL;
- в событиях `dropped` есть только `run_id`, `reason[:300]`, `code`, а в `run.failed` — имя класса;
- `GET /v1/roles/{role}` не отдаёт ключи и цены;
- `extract_version` закрывает запуск при любом исключении после `start_run`, включая сбой `finish_run`.

Выбор решения: соответствует (варианты Б/А/Б/Б/Б/Б). Цену варианта 1Б design.md называет («проверка обязана быть полной»), но для `entities` она не полна — это блокирующий п. 1.
Подгонка тестов: не найдена. Тесты прежнего контракта (`test_extraction_entities.py`, `test_entity_dating_extraction.py`, номера миграций) изменены тестировщиком по новой дельте: проверки не ослаблены, добавлена проверка `code`, `skip`/`xfail` нет. Недостающий инвариант для п. 1 — пробел покрытия, а не подгонка.

Вердикт ревьювера: вернуть разработчику (2 блокирующих), к судье — после исправления.
