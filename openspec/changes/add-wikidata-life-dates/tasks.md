# Tasks

Третье изменение в ветке. Оно использует:
- `dedupe.same_person` (правило противоречия дат) и `merge_proposed` из `improve-person-quality`;
- `naming.check_name` для подписей при создании — новых сущностей команда не создаёт, но `import_wikidata` создаёт.

Требования «Даты жизни из Wikidata» и «Подтверждение QID…» лежат в возможности `entity-dating`, вместе с «Извлечением дат» из `improve-extraction-naming`. `entity-dating` входит в `enforce` здесь, в 3.6, когда тесты есть у всех её требований.

## 1. План

- [x] 1.1 `proposal.md`, `design.md`, `tasks.md`, `progress.md`, дельты `entity-dating` (ADDED), `ontology-extraction` (MODIFIED «Импорт из Wikidata»)
- [ ] 1.2 Ревью плана, решения ведущего, правки

## 2. Разработчик

- [x] 2.1 Схема `knowledge:8`: таблица `run_actions`. Юнит-тест миграции на SQLite.
- [x] 2.2 `wikidata.py`:
  - перенос `WIKIDATA_ROLES`;
  - `simple_time(value)` для упрощённой записи;
  - `HUMAN = "Q5"`.

  Юнит-тесты.
- [x] 2.3 `knowledge/life_dates.py`:
  - `LifeDates.suggest` (фильтр класса, `--auto-exact` по правилу design.md);
  - кандидат-держатель (О10): `holder` в кандидате, пункт `duplicate` с `reason="review:qid_candidate"` без повтора;
  - `apply`: QID по правилу 1–4 спецификации (порядок манифеста, `qid_conflict`, `qid_taken`) → даты по таблице точностей (`bad_value`) → роли; `unchanged`/`conflict`; сухой прогон. Пары `qid_taken` с `accepted` идут в `Dedupe.run(confirmed=…)`, с `auto` — в очередь;
  - проверка формы манифеста (код 2);
  - `rollback`: утверждения, кроме проверенных; QID из `run_actions`, кроме тех, на которые ссылается проверенное (`kept`); `undo_merge` слияний запуска;
  - события `knowledge.life_dates.*`.
- [x] 2.4 CLI `suggest|apply|rollback` (`--manifest`, `--auto-exact`, `--linked`, `--dry-run`, `--limit`, `--from-file`). Сеть — только `wikidata.http_fetch`. Манифест `sources/person_qids.yaml` с шапкой-комментарием и `entities: []`. Проверка формы до базы и сети.
- [x] 2.5 **Файл Lead'а** `filling.py`:
  - импорт `WIKIDATA_ROLES` из `wikidata.py`;
  - даты `import_wikidata` через `simple_time` + `interval` — оба блока: P569/P570 и P577 (`filling.py:535`);
  - `partial` → `knowledge.import.skipped`.

  Прежние тесты `test_filling.py` (импорт Wikidata) зелёные без правки ожиданий.
- [x] 2.6 Юнит-тесты `life_dates` на фикстурах записей (`tests/knowledge/wd_records.py`, QID — только метки). `ruff`, `lint-imports`, `check_traceability.py`; `pytest -q tests/knowledge/test_wikidata_unit.py tests/knowledge/test_filling.py tests/knowledge/test_geo_enrich.py tests/knowledge/test_epoch_dates.py`.

## 3. Тестировщик

Wikidata — только фикстуры (`fetch`-словарь, `--from-file`). Сеть запрещена фикстурой (О6). Инфраструктура общая (`improve-extraction-naming` 3.1). Явные `@example` на каждую границу и мутацию и сторожевой токен журнала в каждом тесте с событиями — по общему разделу `improve-extraction-naming/design.md`, «Границы и сторожевые токены» (О11).

- [x] 3.1 Стратегии «вход + ожидание» (оракул не импортирует `wikidata`, `dates`):
  - `wd_times()` → (значение и точность, ожидаемые границы и `precision` по таблице точностей спецификации);
  - `wd_person_records()`;
  - `manifests()` — порядок записей, два подтверждения одного QID, QID у другой, свой другой QID.

  Явные `@example`: `-0427`/`-0347` (9), `+1724-04-22` (11), точности 8, 7, 6, 5, год `0000`, значение не по формату.
- [x] 3.2 Сценарные тесты на **каждый** сценарий обоих требований `entity-dating` этого изменения и MODIFIED «Импорт из Wikidata». Каждый проверяет:
  - вывод — база, манифест, JSON отчёта CLI, код выхода;
  - события с точным множеством ключей.
- [x] 3.3 Property-тест на **каждое** требование:
  - «Даты жизни» (`ci`): границы = ожидание, «−» ⇒ ≤ 0, без перезаписи, `dry_run` — `dump` без изменений, повтор без новых утверждений. Два отдельных свойства отката: без проверенных ⇒ `dump` к исходному; с проверенными ⇒ проверенные и их QID на месте;
  - «Подтверждение QID» (`ci`): QID только при `accepted`/`auto`, не перезаписывается, первое из двух по порядку, `auto` только с флагом, нет двух сущностей с одним QID;
  - «Импорт из Wikidata» (`pure`): «−» ⇒ до н. э., одна дата ⇒ `partial`.
- [x] 3.4 Мутации — на **каждое** требование, с ожидаемым тестом в `tests/mutations/add-wikidata-life-dates/mutations.yaml`:

  | Требование | Мутация | Ожидаемый упавший тест |
  |---|---|---|
  | Даты жизни | срез строки вместо `claim_date` | «Персона с QID» (Платон) |
  | Даты жизни | точность 7 как год | «Точность десятилетия, века и дня» |
  | Даты жизни | перезапись существующей даты | «Дата уже есть» |
  | Даты жизни | откат удаляет проверенные | «Откат с проверенным утверждением» |
  | Подтверждение QID | QID записывается при `pending` | property подтверждения |
  | Подтверждение QID | `auto` без флага | «Точное совпадение с флагом» / «Кандидаты для персоны» |
  | Подтверждение QID | `qid_taken` не передаётся слиянию | «QID занят» |
  | Подтверждение QID | перезапись своего другого QID | «У сущности другой QID» |
  | Подтверждение QID | `suggest` не ставит кандидата-держателя в очередь | «Кандидат уже у другой персоны» |
  | Импорт из Wikidata | `import_wikidata` со срезом `[1:5]` | «Дата до нашей эры» |

- [x] 3.5 `python scripts/mutation_check.py --change add-wikidata-life-dates` — таблица в `verification.md`; `--coverage add-wikidata-life-dates` чисто (О11).
- [x] 3.6 `openspec/traceability.yaml`: `entity-dating` в `enforce`. `python scripts/check_traceability.py` чисто.
- [x] 3.7 `verification.md`:
  - сырые итоги;
  - `--durations`;
  - события;
  - таблица «требование → сценарный → property → мутация → упал».

## 4. Ревьювер

- [ ] 4.1 Время, сеть и QID — только `wikidata.py`. Нет копии `geo_enrich`/`epoch_dates` там, где можно вызвать общее. Правило противоречия дат — из `dedupe`. Правка `filling.py` минимальная.

## 5. Требует Lead'а

- [ ] 5.1 Согласовать правку `filling.py` (`WIKIDATA_ROLES`, даты `import_wikidata`).
- [ ] 5.2 На стенде: `suggest` (сеть Wikidata, бесплатно) → решение по `--auto-exact` и подтверждение QID в манифесте человеком → `apply --dry-run` → `apply`. Отчёты приложить к PR.
- [ ] 5.3 Вклад в А5/А6 — замер в `migrate-ontology-quality` 5.x.

## 6. Судья

- [ ] 6.1 Новый субагент:
  - полнота;
  - сценарии и инварианты в двух источниках;
  - сам повторить мутацию «срез строки» и «QID при `pending`»;
  - вердикт.
