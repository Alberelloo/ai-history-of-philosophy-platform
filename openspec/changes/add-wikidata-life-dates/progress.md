# Progress

## 2026-11-25 — планирование (разработчик, субагент `coder`)

- Ведёт: субагент `coder` по поручению ведущего. Ветка `claude/ontology-extraction`.
- Опоры:
  - задание владельца `PHILO-SPEC-ONTOLOGY.md` (П3, требование «Импорт дат из Wikidata», А5, А6);
  - решения ведущего О1–О8 (`lead-decisions-ontology.md`, scratchpad ведущего): О2 — отдельное изменение, О3 — минимальная правка `filling.py`, О6 — только фикстуры.
- Факт кода:
  - `geo_enrich` P569/P570 читает только для времени мест;
  - `import_wikidata` режет строку даты (`[1:5]`) и теряет знак эры;
  - у большинства персон стенда нет QID (`external_ids` локального `.stack`: только `library`).
- Проверено на локальном `.venv`, только чтение, без сети:
  - `wikidata_time('-0427…', 9)` + `interval` + `format_original` → `span (−426, −346)`, `precision year`, «427 до н. э. – 347 до н. э.»;
  - для Канта с точностью «день» → `(1724, 1804)`, «1724–1804».
- Решения разработчика:
  1. Отдельная команда `life_dates` по образцу `geo_enrich` (запуск, сухой прогон, откат) и манифест QID по образцу `epoch_dates`. Расширять `geo_enrich` или `import_wikidata` не стали: смешение возможностей, нет отката.
  2. «Подтверждённый QID» — уже записанный у сущности, или `accepted` в манифесте (человек), или `auto` (только с флагом `--auto-exact`, правило точного совпадения).
  3. Одна дата — пропуск `partial`. Существующая дата не перезаписывается (`unchanged`/`conflict`).
  4. Таблица `run_actions` (`knowledge:8`) — общий журнал действий запуска вне утверждений. Её переиспользует миграция.
  5. Платон: астрономический счёт (−426/−346). У владельца −427/−347 — исторический счёт той же даты.

Статус: 1.1 сделан, следующий — 1.2.

## Ревью плана — 2026-11-25, коммит ebf1186 (ревьювер, субагент `reviewer`)

Блокирует: нет.

Желательно:
1. `design.md:77` — при `qid_taken` подтверждённый человеком QID — сильнейшее доказательство тождества. Его можно отдать `Dedupe` (`merge:qid`), а не только в очередь. Сейчас это единственный путь, на котором две записи одного лица с одним QID встречаются (PK `external_ids` не даёт двух сущностей с одним QID, см. ревью `improve-person-quality` п. 1).
2. `design.md:108` — блок P577 в `import_wikidata` тоже режет строку (`filling.py:535`). В 2.5 надо назвать его явно.
3. Расхождения со спекой владельца — Платон (−426, −346) вместо −427/−347 и `partial` — допустимы: счёт задан принятым «Нечёткие даты». Их нужно вынести в PR на подтверждение.

Выбор решения: соответствует (отдельная команда по образцу `geo_enrich`/`epoch_dates`, время только в `wikidata.py`).
Подгонка тестов: кода нет; не найдена.
Вердикт: можно к коду.

## 2026-11-25 — план, круг 2 (разработчик, субагент `coder`)

Учтены ревью ревьювера (блокирующих нет), ревью тестировщика Б7, Б8 и решение ведущего О9.

- **Б7.**
  - В spec — таблица точностей Wikidata 6–11 → границы и `precision`. Точность < 6, год `0000` и значение не по формату дают пропуск `bad_value`.
  - Календарная модель не учитывается.
  - Откат разделён на два свойства: без проверенных — `dump` к исходному; с проверенными — проверенные и их QID остаются (`kept`).
  - Сценарии «Точность десятилетия, века и дня», «Год 0000 и малая точность», «Откат с проверенным утверждением».
- **Б8.** Правила манифеста в spec:
  - проверка формы (код 2);
  - обход по порядку;
  - свой другой QID — `qid_conflict`;
  - два подтверждения одного QID — выигрывает первое;
  - QID у другой — `qid_taken`.

  Сценарии «Два подтверждения одного QID», «У сущности другой QID», «Неверный манифест».
- **Желательное 1 (О9: `qid_taken` в Dedupe).** Для `accepted` пара передаётся `Dedupe.run(confirmed=…)` → `merge:qid_confirmed`. Для `auto` пара уходит в очередь. Сценарий «QID занят» переписан.
- **Желательное 2.** Блок P577 `import_wikidata` (`filling.py:535`) назван в 2.5.
- **Желательное 3.** Расхождения (Платон −426/−346, `partial`) — в PR вместе со списком `improve-extraction-naming` 5.4.
- **Задачи тестировщика.** `tasks.md` 3.x: стратегии «вход + ожидание», явные `@example`, мутация на каждое требование с ожидаемым тестом.

- 2026-11-25, круг 2б (О10): транслитерации (Гомер/Омир) — путь через манифест QID и `merge:qid_confirmed`; без решения — очередь `duplicate` (`qid_candidate`), А4 считает открытые пункты любой причины. Сценарии, инварианты и мутации дописаны.

## Ревью плана, круг 2 — 2026-11-25, коммит 9431c21 (ревьювер, субагент `reviewer`)

Желательные круга 1 приняты: `qid_taken` уходит в `Dedupe` как `qid_confirmed`, P577 в 2.5. Добавлены `holder`/`qid_candidate`, `qid_conflict`, проверка формы манифеста и таблица точностей. Таблица совпадает с `wikidata._bounds`.

Блокирует:
1. `specs/entity-dating/spec.md:73-75`, сценарий «Точность десятилетия, века и дня». P570 `+1801` с точностью 7 даёт век ⌈1801/100⌉ = XIX, то есть 1801…1900. Проверено: `wikidata_time('+1801-00-00T00:00:00Z', 7)` → 1801–1900, «XIX в.». Сценарий ждёт 1701…1800. Сделать: `+1800` (→ 1701…1800) или ожидание 1801…1900.

Вердикт: доработать (одна строка), затем можно к коду.

## План, круг 3 — 2026-11-25 (разработчик, О11/О12)

- Блок. ревью п. 1: P570 `+1801` точность 7 → 1801…1900, как в `wikidata.wikidata_time`.
- `reason` очереди с префиксом (`review:qid_candidate`, `review:qid_taken`), слияние — `merge:qid_confirmed`.

## Ревью плана, круг 3 — 2026-11-25, коммит 03d0037 (ревьювер, субагент `reviewer`)

Блокирующее круга 2 закрыто: сценарий точности 7 ждёт 1801…1900, как `wikidata_time`. Причины очереди с префиксом `review:` согласованы с `person-quality`. Нового не найдено.

Вердикт: можно к коду.

## Код — 2026-11-25 (разработчик, субагент `coder`)

- 2.1 `schema.py`: таблица `run_actions` (`id, run_id, seq, kind, payload, created_at`, индекс по `run_id`), миграция `knowledge:8`. Юнит-тест `tests/knowledge/test_run_actions_unit.py` (1 passed).
  - **Конфликт с прежними тестами (решение Lead'а / тестировщика):** `tests/knowledge/test_portraits.py:97,124` (`applied == [7]`, `latest() == 7`) и `tests/knowledge/test_mentions_cards.py:308` (`latest() == 7`) закрепляют последнюю версию схемы и падают при любой новой миграции. Ожидания не правлю (чужие тесты). Варианты: ожидание `>= 7` / накат только до 7 в этих тестах, либо отказ от `knowledge:8` (тогда `run_actions` негде хранить).
- 2.2 `wikidata.py`: `HUMAN = "Q5"`, `INSTANCE_OF = "P31"`, `WIKIDATA_ROLES` (перенос таблицы из `filling.py`, сама замена импорта — 2.5), `simple_time(value)` — `"+ГГГГ-ММ-ДД"` или полное значение → `wikidata_time(…, 9)`. Юнит-тесты `tests/knowledge/test_wikidata_simple_unit.py` (13 passed).
- 2.3 `knowledge/life_dates.py`: `LifeDates(statements, fetch, review=None)`, `suggest(manifest, auto_exact, limit)`, `apply(manifest, linked, dry_run, limit) -> Report`, `rollback(run_id)`, `validate`/`check_manifest`, `record_dates`; события `knowledge.life_dates.{suggested,run,skipped,rolled_back}`. Общее не копируется: `load_manifest`/`save_manifest`/`ManifestError`/`FETCH_ERRORS` — из `epoch_dates`, `file_fetch` — из `geo_enrich`, время/QID/поиск — `wikidata`, противоречие дат — `dedupe.dates_conflict`, очередь — `dedupe.propose`.
  - Сопутствующие правки (свои модули): `Entities.remove_external`, `Entities.external_of`; `Entities.set_primary(…, None)` снимает ключ (раньше писал `null`); `Statements.rollback_run` пересчитывает копии основных значений (`PRIMARY_TYPES`) у субъектов удалённых утверждений — без этого откат оставлял `primary.dates`, и дамп не возвращался к исходному (найдено юнит-тестом сухого прогона и отката). `Dedupe.plan/run(scope=…)` — только компоненты и пары очереди с сущностями подтверждений: `apply` не сливает чужие дубли.
  - Решения в пределах design: поиск — каждое название (основное и варианты) на ru и на en; `holder` не ставится в очередь, если пара закрыта решением «разные» (О13); `conflict` считается и в `conflicts`, и в `skipped`; сущность манифеста, которой нет, — `skipped` с `property="wikidata"`, `reason="refused"`; пары `qid_taken` не-персон (`work`) — в очередь `review:qid_taken` (`Dedupe` сливает только персоны); `Dedupe.run` вызывается только при непустых подтверждениях, в сухом прогоне — только `plan`.
- 2.4 CLI `python -m philograph.knowledge.life_dates suggest|apply|rollback` (`--manifest`, `--auto-exact`, `--linked`, `--dry-run`, `--limit`, `--from-file`); форма манифеста и файл записей проверяются до `service(fetch)` (база) и сети, ошибка — код 2. Сеть — только `partial(wikidata.http_fetch, wait=time.sleep)`. Манифест `sources/person_qids.yaml` — шапка-комментарий (схема, порядок работы) и `entities: []`; `save_manifest` шапку сохраняет. Юнит-тесты CLI в `test_life_dates_unit.py` (14 passed).
- 2.5 **Файл Lead'а** `filling.py` — точки вызова:
  - `filling.py:19` импорт `interval` из `dates` (вместо `FuzzyDate, lifespan, parse`); `filling.py:32` импорт `WIKIDATA_ROLES, format_original, simple_time` из `wikidata`; таблица `WIKIDATA_ROLES` из `filling.py` удалена (перенесена в `wikidata.py`, 2.2);
  - `filling.py:498-517` P569/P570: `simple_time` обеих дат → `interval(born, died, format_original(born, died))`; одна дата — `knowledge.import.skipped` с `property` недостающей, `reason="partial"`;
  - `filling.py:519` P577: `simple_time` → `dating` (срез `[1:5]` убран);
  - `filling.py:531` роли — та же строка, таблица из `wikidata`.
  - `test_filling.py` 30 passed без правки ожиданий. `simple_time('-0427-00-00T00:00:00Z')` → −426, «427 до н. э.».
- 2.6 Юнит-тесты `tests/knowledge/test_life_dates_unit.py` на `wd_records.RecordFetch`/`record` (14: форма манифеста, Платон до н. э. и роли, повтор, `partial`/`bad_value`, точности 8 и 7, `unchanged`/`conflict`, `qid_conflict`/`qid_taken`/два подтверждения, слияние `merge:qid_confirmed`, сухой прогон = отчёт и дамп, откат к дампу, откат с проверенным `kept=1`, `suggest` с `holder` без повтора и `--auto-exact`, произведение P577, CLI код 2 и `--from-file`). Прогоны по одному: `test_life_dates_unit` 14, `test_run_actions_unit` 1, `test_wikidata_simple_unit` 13, `test_wikidata_unit` 36, `test_filling` 30, `test_geo_enrich` 37, `test_epoch_dates` 66, `test_statements` 19, `test_registry_entities` 33 + 1 skipped, `test_dedupe_unit` 19, `test_person_merge_unit` 7 — все passed. `ruff check src/` чисто, `ruff format --check` чисто, `lint-imports` 3 kept, `check_traceability.py` 405 из 405.
  - Падают из-за `knowledge:8` (см. 2.1): `test_portraits.py::test_migration_7_adds_portraits_and_keeps_old_data`, `test_mentions_cards.py::test_migration_6_adds_mention_position` — закреплено `latest() == 7`.
- Решение ведущего О14 (разрешённое исключение из «существующие тесты не правишь», прецедент #40 — переход 6→7): миграция `knowledge:8` остаётся; ожидания обновлены только в строках `tests/knowledge/test_portraits.py:97` (`applied == [7, 8]`: миграция 7 применилась, порядок сохранён), `:124` и `tests/knowledge/test_mentions_cards.py:308` (`latest() == 8`). Прогоны по одному: `test_portraits` 13 passed, `test_mentions_cards` 32 passed.
