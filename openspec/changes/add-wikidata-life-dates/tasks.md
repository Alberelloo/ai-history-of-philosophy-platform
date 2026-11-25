# Tasks

Третье изменение в ветке. Оно использует:
- `dedupe.same_person` (правило противоречия дат) и `merge_proposed` из `improve-person-quality`;
- `naming.check_name` для подписей при создании — новых сущностей команда не создаёт, но `import_wikidata` создаёт.

Требования «Даты жизни из Wikidata» и «Подтверждение QID…» лежат в возможности `entity-dating`, вместе с «Извлечением дат» из `improve-extraction-naming`. `entity-dating` входит в `enforce` здесь, в 3.6, когда тесты есть у всех её требований.

## 1. План

- [x] 1.1 `proposal.md`, `design.md`, `tasks.md`, `progress.md`, дельты `entity-dating` (ADDED), `ontology-extraction` (MODIFIED «Импорт из Wikidata»)
- [ ] 1.2 Ревью плана, решения ведущего, правки

## 2. Разработчик

- [ ] 2.1 Схема `knowledge:8`: таблица `run_actions`. Юнит-тест миграции на SQLite.
- [ ] 2.2 `wikidata.py`:
  - перенос `WIKIDATA_ROLES`;
  - `simple_time(value)` для упрощённой записи;
  - `HUMAN = "Q5"`.

  Юнит-тесты.
- [ ] 2.3 `knowledge/life_dates.py`:
  - `LifeDates.suggest` (фильтр класса, `--auto-exact` по правилу design.md);
  - `apply` (QID → даты → роли; `unchanged`/`conflict`; сухой прогон; `qid_taken` → очередь и `merge_proposed`);
  - `rollback` (утверждения + QID из `run_actions`);
  - события `knowledge.life_dates.*`.
- [ ] 2.4 CLI `suggest|apply|rollback` (`--manifest`, `--auto-exact`, `--linked`, `--dry-run`, `--limit`, `--from-file`). Сеть — только `wikidata.http_fetch`. Манифест `sources/person_qids.yaml` с шапкой-комментарием и `entities: []`. Проверка формы до базы и сети.
- [ ] 2.5 **Файл Lead'а** `filling.py`:
  - импорт `WIKIDATA_ROLES` из `wikidata.py`;
  - даты `import_wikidata` через `simple_time` + `interval`;
  - `partial` → `knowledge.import.skipped`.

  Прежние тесты `test_filling.py` (импорт Wikidata) зелёные без правки ожиданий.
- [ ] 2.6 Юнит-тесты `life_dates` на фикстурах записей (`tests/knowledge/wd_records.py`, QID — только метки). `ruff`, `lint-imports`, `check_traceability.py`; `pytest -q tests/knowledge/test_wikidata_unit.py tests/knowledge/test_filling.py tests/knowledge/test_geo_enrich.py tests/knowledge/test_epoch_dates.py`.

## 3. Тестировщик

Wikidata — только фикстуры (`fetch`-словарь, `--from-file`), сеть запрещена (О6).

- [ ] 3.1 Генераторы `wd_times`, `wd_person_records`, `manifests` в `tests/knowledge/strategies.py`.
- [ ] 3.2 Сценарные тесты на каждый сценарий обоих требований `entity-dating` этого изменения и MODIFIED «Импорт из Wikidata». Каждый тест проверяет вывод (база, манифест, JSON отчёта CLI) и события с полями.
- [ ] 3.3 Property-тест на каждое требование:
  - «Даты жизни»: разбор равен общему правилу, «−» ⇒ начало ≤ 0, без перезаписи, `dry_run` без изменений, повтор без новых утверждений, откат к исходному дампу;
  - «Подтверждение QID»: QID только при `accepted`/`auto`, `auto` только с флагом и при одном точном кандидате, нет двух сущностей с одним QID;
  - «Импорт из Wikidata»: «−» ⇒ до н. э.
- [ ] 3.4 Мутации, результат — в `verification.md`:
  - срез строки вместо `claim_date`;
  - перезапись существующей даты;
  - `auto` без флага;
  - запись QID при `pending`;
  - откат без удаления QID;
  - `lifespan` при одной дате.
- [ ] 3.5 CLI: `apply --from-file` на фикстуре — код 0 и JSON отчёта; неверный манифест — код 2 до обращения к базе.
- [ ] 3.6 `openspec/traceability.yaml`: `entity-dating` в `enforce`. `python scripts/check_traceability.py` чисто.
- [ ] 3.7 `verification.md`: сырые итоги, события, таблица «требование → доказывающий тест → мутация».

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
