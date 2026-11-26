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

## 2026-11-26 — ответ на ревью (Б1, Б2, Ж1–Ж8)

- Б1: `EntityItems.index` — `type` элемента не строка → `schema_item`; `dating` по виду: `text`, `quote` — строки, `paragraph` — целое или ASCII-цифры (приводится), иначе элемент отбрасывается с `schema_item` через `on_drop`. Дельта: «Проверка ответа…», шаг 1, сценарий «Элемент entities не того вида».
- Б2: `_previous` — все неоткатанные внешние запуски версии (`done`, `failed`, `running`). Без `--replace` — код 2, с `--replace` — откат всех. Дельта «Внешний извлекатель»: норматив и сценарий «Повтор после прерванной записи».
- Ж1: `quotes.check` ищет цитату целиком, по многоточию делит только если целиком не нашлась. Дельта: правило и сценарий «Многоточие автора в цитате».
- Ж2: риск `--replace` (откат до записи) — docstring `ingest`, runbook «Извлечение связей», design «Открытые вопросы» 9.
- Ж4: версии нет (404) или библиотека недоступна — отказ команды, код 2, без трассировки. Ж5: повтор номера фрагмента в JSONL или повтор ключа в JSON — код 2. Оба — в дельте.
- Ж6: runbook, раздел «Извлечение связей» (`PHILOGRAPH_EXTRACTION_TIMEOUT_SECONDS`, команда `external_extraction`); ссылки tasks.md 2.5 исправлены.
- Ж7: нормализация в дельте дописана (нулевая ширина, `″′` и обратный апостроф).
- Ж3, Ж8 — design «Открытые вопросы» 7 и 8 (Ж8 — задача ведущему на отдельное изменение).
- Тест тестировщика по прежней формулировке (3.3): `test_reextract_external.py::test_replace_without_previous_and_failed_previous` ждёт, что повтор без `--replace` после `failed` разрешён; по Б2 и новой дельте — код 2. Не менял.
- Прогон: `test_reextract_*.py` + юниты + `test_extraction_entities test_entity_dating_extraction test_entity_items_unit test_statements test_filling test_dating_unit` — 503 passed, 1 failed (тест выше). `ruff check .`, `ruff format --check .` (719), `lint-imports` (3 kept) — чисто.

## 2026-11-26 — цитата без значимого текста

- Дефект после Ж1: цитата «...» (или только знаки и пробелы) находилась целиком в абзаце с авторским многоточием. `quotes.check`: до поиска цитата без обрамляющих кавычек должна содержать хотя бы одну букву или цифру (`MIN_WHOLE = 1`), иначе `quote_too_short`; каждая часть при делении — тоже. Пустая цитата — `quote_not_found`. Почему 1, а не 10 — design.md, `knowledge/quotes.py` («Минимум значимого текста»): подтверждения из одного слова не должны стать потерянными.
- Дельта: норматив «Значимый текст», сценарий «Цитата без значимого текста».
- Тесты тестировщика, которые новое правило меняет (3.3, не менял):
  - `test_reextract_quotes.py::test_degenerate_quotes_never_found[...]` — 9 вариантов (`...`, `…`, `[...]`, `(...)`, ` ... `, `""`, `«»`, `"..."`, `' '`): ждут код `quote_not_found`, теперь `quote_too_short` (цитата по-прежнему не находится);
  - `test_reextract_quotes.py::test_any_substring_found_property` и `test_reextract_review.py::test_substring_with_authors_ellipsis_property` — «любая подстрока находится», а подстрока без букв и цифр (` -`) теперь отказ: генератору нужно брать подстроки со значимым текстом.
- Прогон: `test_quotes_unit.py` — 30 passed; `test_reextract_*.py + test_quotes_unit.py` — 360 passed, 11 failed (ровно перечисленные выше). ruff чисто.

## Ревью (повторное) — 2026-11-26, коммит a393ef8

Проверены коммиты 7e8d8db, 98d643f и тесты к ним (`git diff 6ac7f2d..a393ef8`). Сделано: `ruff check .` чисто, `lint-imports` — 3 kept, `check_traceability` — 427 из 427. `test_reextract_review.py`, `test_quotes_unit.py` и `test_external_extraction_unit.py` — 95 passed. Пробы прошлого ревью повторены из временных файлов, после прогона файлы удалены.

Блокирует: нет.

Прежние блокирующие закрыты:
- Б1. Через настоящий шлюз отправлен ответ, где у элементов `entities` встречаются `type: ["person"]`, `type: {...}`, `dating.text: 1724`, `dating.paragraph: [1]`, и есть одно верное утверждение. Итог: запуск `done`, `created=1`, `drop_reasons={"schema_item": 4}`.
- Б2. Прерванный `ingest` (`failed`, одно утверждение) и затем повтор без `--replace` дают код 2. Повтор с `--replace` даёт код 0, запуски `[rolled_back, done]`, утверждений, подтверждений и атрибуций по 2 — удвоения нет. Откат выбирает только `kind=extraction`, `extractor=external`, `target=<версия>`. Запуски шлюза и других версий не трогаются (`test_replace_leaves_other_runs_alone`). `rollback_run` по-прежнему удаляет только строки своего `run_id`.

Правило цитат и существующие подтверждения. Новое правило сравнено с прежним (`_norm_quote(q) in _norm_quote(text)`): нормализация симметрична и сначала ищется цитата целиком. Поэтому всё, что находило прежнее правило, находится и сейчас, кроме двух классов:
- (а) цитаты без букв и цифр («—», «...», « »);
- (б) пустая цитата. Прежнее правило принимало её: `"" in text` истинно.

Теперь оба класса при перепроверке изменённого абзаца станут `lost`. Подтверждением такие строки не являются, но это расходится с THEN сценария «Многоточие автора в цитате» («подтверждение, чья цитата найдена прежним правилом, не становится потерянным»). Цитаты в кавычках вида `"Бог"` теперь находятся, а раньше нет — это только улучшение.

Желательно:
1. До развёртывания посчитать на боевой базе подтверждения, которые новое правило отвергнет. Запрос: `SELECT count(*) FROM knowledge.evidence WHERE NOT lost AND quote !~ '[[:alnum:]]'` (PostgreSQL). Если строк 0 — R6 соблюдён. Если нет — либо принять их потерю и записать в отчёт, либо сузить THEN сценария до «цитата со значимым текстом».
2. `external_extraction.py` `_previous` — в откат попадает и `running`. Если параллельно идёт `ingest` той же версии в другом процессе, `--replace` откатит активный запуск. Стоит отказывать (код 2), если `running` моложе, например, часа, или хотя бы написать об этом в runbook.
3. `entity_items.py` `_without_nulls` — `dating` не объектом (например строка `"1724"`) молча удаляется, а элемент остаётся без датировки и без события. Это расходится с дельтой, шаг 1 («иначе элемент `entities` отбрасывается с `schema_item`»).
4. `external_extraction.py` `read_replies` — `_unique` запрещает повтор ключа на любом уровне JSON-объекта, так что один ответ модели с дважды названным полем останавливает весь `ingest`. Для JSONL такой проверки нет — форматы ведут себя по-разному. Стоит либо проверять только верхний уровень, либо делать одинаково в обоих форматах.
5. Docstring `ingest` говорит, что откат снимает «проверенные человеком решения по утверждениям этого запуска». Но `rollback_run` проверенные (`verified`) утверждения со всеми их подтверждениями сохраняет. Текст стоит поправить, чтобы он не пугал оператора зря.

Выбор решения: соответствует. «Открытые вопросы» 7–9 честно фиксируют то, что не закрыто.
Подгонка тестов: не найдена. Изменённые ожидания (`"…"` → `quote_too_short`, повтор после `failed` → код 2) следуют за правкой дельты по ревью. Проверки не ослаблены, добавлены сценарии и мутации.

Вердикт ревьювера: можно к судье. Желательный п. 1 ведущему стоит выполнить до применения на боевой базе.

## 2026-11-26 — повторное ревью, желательные (1)–(5)

- (3) `dating` не объект (строка, число, список) — отказ элемента `entities` с `schema_item` (было: молча удалялось). Дельта, шаг 1.
- (4) Повтор ключа проверяется только на верхнем уровне файла ответов (номер фрагмента — код 2); внутри ответа — обычный JSON, последнее значение. Дельта «Внешний извлекатель».
- (2) `running` моложе `STALE_RUNNING_HOURS = 6` — отказ «запись идёт» (код 2) и с `--replace`, ничего не откатывается; `--replace` откатывает `done`, `failed` и `running` старше 6 ч. Дельта: норматив, сценарии «Идёт запись той же версии», «Брошенная запись».
- (5) Docstring `ingest`: проверенные человеком утверждения откат не снимает (`Statements.rollback_run`), повторная запись добавит им подтверждения.
- (1) Runbook «Извлечение связей» и tasks.md 6.1 — SQL подсчёта подтверждений без значимого текста перед переизвлечением; THEN сценария «Многоточие автора в цитате» сужен до подтверждений со значимым текстом.
- Тесты тестировщика по прежней формулировке (3.3, не менял): `test_reextract_review.py::test_any_unrolled_external_run_blocks_repeat[statuses1]` и `[statuses3]` (`running` свежий — теперь «запись идёт», `--replace` не откатывает); `test_duplicate_key_in_json_object[{"1": {"statements": [], "statements": []}}]` (повтор внутри ответа — теперь не ошибка).
- Прогон: юниты 35 passed; `test_reextract_*.py test_quotes_unit test_external_extraction_unit test_extraction_codes_map_unit test_extraction_entities test_entity_dating_extraction` — 465 passed, 3 failed (перечислены). ruff, format (720), lint-imports (3 kept) — чисто.

## 2026-11-26 — дефект судьи Д4 и `report` без библиотеки

- Д4: `read_replies` проверяет повтор по номеру фрагмента после приведения (`_number`: ASCII-цифры, пробелы по краям) в обоих форматах: `1`/`"01"`/`" 1"` — один фрагмент → код 2, ничего не записано. Ключи, которые не номер, сравниваются как есть (в `ingest` → `reply_invalid`). `ingest` берёт номер той же функцией.
- `report` открывает только базу знаний, `PHILOGRAPH_LIBRARY_URL` не нужен.
- Дельта «Внешний извлекатель»: повтор — по номеру после приведения; `report` — без библиотеки.
- Прогон: `test_external_extraction_unit.py test_reextract_external.py test_reextract_review.py` — 144 passed; ruff, format, lint-imports — чисто.

## Ревью (третье) — 2026-11-26, коммит 6b789af

Проверены bd21bb3 и 6b789af (`git diff 3208c4c..6b789af -- src openspec docs`), а также тесты к ним. Сделано: `ruff check .` и `ruff format --check .` чисто, `lint-imports` — 3 kept, `check_traceability` — 427 из 427. `test_reextract_review.py`, `test_external_extraction_unit.py` и `test_reextract_external.py` — 144 passed.

Блокирует: нет.

Соответствие дельте:
- `dating` не объектом даёт `schema_item`, а `null` по-прежнему значит «поля нет» (`entity_items.py:148`). Это шаг 1 дельты.
- Повтор номера фрагмента проверяется по номеру после приведения (Д4). Проба `read_replies`:
  - `{"1":…,"01":…}` — код 2;
  - точный повтор `"1"` в JSON-объекте — код 2;
  - JSONL `1` и `" 1"` — код 2;
  - повтор ключа внутри ответа (`"quote"` дважды, `"statements"` дважды) — читается как обычный JSON (последнее значение), команда идёт дальше.
- `ingest` проверяет «запись идёт» (`running` моложе `STALE_RUNNING_HOURS`) раньше `--replace`, поэтому ничего не откатывает. Брошенный `running` старше порога откатывается. `_age_hours` учитывает время без пояса (SQLite); PostgreSQL отдаёт `timestamptz` (проверено в первом ревью).
- `report` работает без библиотеки, как записано в дельте.
- Runbook дополнен: запрос подтверждений без значимого текста, порог 6 ч, оговорка про `verified`. Docstring `ingest` исправлен.

Желательно:
1. `external_extraction.py` `ingest` — между проверкой «запись идёт» и `start_run` есть окно гонки: два `ingest` одной версии, запущенные одновременно, оба пройдут проверку. Для ручной команды оператора это приемлемо. Если запускать параллельно по 208 источникам, версии не должны повторяться — стоит написать об этом в runbook.
2. Если `PHILOGRAPH_DATABASE_URL` не задан, `_knowledge` падает с `KeyError` и трассировкой. Лучше понятный отказ с кодом 2 (относится и к `build`).
3. Тест повтора ключа на вложенном уровне (код 2) заменён на «продолжается» вслед за правкой дельты по моему п. 4 прошлого ревью. Это не подгонка.

Выбор решения: соответствует.
Подгонка тестов: не найдена.

Вердикт ревьювера: можно к судье. Пункт 4.1 отмечен.

## Ведущий — 2026-11-26, архив

- Вердикт судьи (повторно, 471c77d): **принято**.
- Дельты перенесены в `openspec/specs/ontology-extraction` и `openspec/specs/llm-gateway` вручную (CLI `openspec` нет); требования `improve-extraction-naming` не пересекаются. `check_traceability`: 427 из 427.
- Желательное из третьего ревью оставлено: гонка двух `ingest` одной версии — переизвлечение ведёт каждую версию одним процессом; отказ без `PHILOGRAPH_DATABASE_URL` — открытый вопрос.
- 6.1 (переизвлечение 208 источников на боевой базе) — вне PR: на сервере Claude нет боевой базы; выполняется отдельным прогоном после доступа к данным, отчёт — `docs/audit/extraction-run-YYYY-MM-DD.md`.
