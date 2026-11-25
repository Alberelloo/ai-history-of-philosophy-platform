# Verification

## Тестировщик — 2026-11-25, тесты на коммите 2cc4f44 (ветка claude/ontology-extraction)

Тесты — от дельт `specs/entity-dating`, `specs/ontology-extraction` и design.md; код читался только для точек входа и, после коммита тестов, для патчей мутаций. Wikidata — записи теста (`wd_records.record`, `RecordFetch`, `--from-file`), сеть запрещена (`no_network` + автофикстура). Файл: `tests/knowledge/test_life_dates.py`.

Стратегии (3.1, `tests/knowledge/strategies.py`, без `wikidata`/`dates`):
- `wd_times` — знак ±, год 1…3000, точность 6–11 (месяц/день при 10/11), год `0000`, точность 0–5, строки не по формату → ожидание по таблице точностей (`wd_bounds`: `a(y)`, десятилетие `min/max(a(Y), a(Y+9))`, век `⌈Y/100⌉`, тысячелетие `⌈Y/1000⌉`) или `bad_value`;
- `wd_person_records` — персоны и произведения: P569/P570/P577 с рангами (предпочтённое → первое обычное, устаревшее никогда; одни устаревшие = свойства нет), одно/оба/ни одного, P106 из таблицы и вне её, существующие даты; `expected_dating` / `expected_lifespan` (начало из рождения, конец из смерти, `precision` — `year` или более широкая);
- `manifests` — персоны с QID из малого пула, порядок записей, решения `pending/accepted/auto/rejected`, два подтверждения одного QID, QID у другой, свой другой QID; ожидание — обход по правилу 1–4;
- `suggest_cases` (в тесте) — 0–3 кандидата на сущность, точная/неточная подпись, человек/не человек, флаг.

Явные `@example`: `-0427`/`-0347` (9), `+1724-04-22` (11), точности 8, 7 (в том числе `-0427` век → −499…−400), 6, 5, год `0000`, `1724-04-22` без знака; ранги (устаревшее + обычное + предпочтённое); два подтверждения одного QID; свой QID + чужой занятый.

### Требование → тесты → мутация

| Требование | Сценарные | Property / нормативные | Мутация | Упал |
|---|---|---|---|---|
| entity-dating «Даты жизни из Wikidata» | test_person_with_qid, test_kant_with_days, test_work_year, test_decade_century, test_year_zero_and_low_precision, test_one_date, test_existing_dates, test_dry_run_and_rollback_cli (CLI: JSON, код выхода, dump), test_rollback_keeps_verified, test_rollback_verified_keeps_attribution (красный, Д1) | test_life_dates_invariant (ci: границы = таблица, «−» ⇒ ≤ 0, без перезаписи, сухой прогон = dump + тот же отчёт, повтор без утверждений, роли только из таблицы), test_rollback_without_verified_restores_dump (ci), test_rollback_keeps_verified_and_qid (ci) | slice-instead-of-claim-date, century-as-year, existing-overwritten, rollback-removes-verified | да ×9 |
| entity-dating «Подтверждение QID персон и произведений» | test_candidates_for_person, test_candidate_held_by_other, test_exact_with_flag, test_two_candidates, test_qid_taken, test_two_confirmations, test_entity_has_other_qid, test_bad_manifest (CLI, код 2, без базы), test_bad_manifest_forms | test_qid_confirmation_invariant (ci), test_suggest_auto_invariant (ci, с флагом и без, затем apply) | qid-on-pending, auto-without-flag, qid-taken-not-merged, own-qid-overwritten, holder-not-queued | да ×7 |
| ontology-extraction «Импорт из Wikidata» (MODIFIED) | test_influence_not_imported, test_import_bce, test_import_one_date | test_time_rule_any_value (pure 400 + 9 @example), test_import_invariant (ci: «−» ⇒ до н. э., одна дата ⇒ `partial`) | import-slice | да ×2 |

Платон Q859: `-0427`/`-0347` → границы (−426, −426, −346, −346), исходная запись «427 до н. э. – 347 до н. э.» (астрономический счёт, О-расхождение для PR).

События сверяются точным множеством ключей (`check_keys`: `run`, `skipped`, `rolled_back`, `suggested`; `run_id` у `run`/`rolled_back` — равен номеру запуска). Сторожевой токен — в описании записи Q859 (`no_token`).

    knowledge.life_dates.run {'run_id': 'life_…', 'dry_run': False, 'entities': 1, 'externals': 0, 'lifespans': 1, 'datings': 0, 'roles': 1, 'unchanged': 0, 'conflicts': 0, 'skipped': 0, 'failed': 0}
    knowledge.life_dates.run {'run_id': 'life_…', 'dry_run': False, 'entities': 1, 'externals': 1, 'lifespans': 1, 'datings': 0, 'roles': 1, 'unchanged': 0, 'conflicts': 0, 'skipped': 0, 'failed': 0}
    knowledge.life_dates.rolled_back {'run_id': 'life_…', 'statements': 1, 'externals': 0, 'kept': 1}

### Сырые итоги

    test_life_dates.py  1 failed, 30 passed in 236.02s (рабочее дерево); 1 failed, 30 passed in 148.56s (worktree на 2cc4f44)
      FAILED test_rollback_verified_keeps_attribution (Д1)
      78.36s test_rollback_keeps_verified_and_qid · 50.41s test_rollback_without_verified_restores_dump · 42.15s test_life_dates_invariant
      10.76s test_qid_confirmation_invariant · 8.67s test_import_invariant · 8.55s test_suggest_auto_invariant
    check_traceability: 410 из 410 (entity-dating в enforce) · --coverage add-wikidata-life-dates: мутации у всех 3 требований

### Мутации (отдельный worktree на 2cc4f44, 2 мин 38 с)

| Требование | Мутация | Ожидаемый тест | Упал |
|---|---|---|---|
| Даты жизни из Wikidata | slice-instead-of-claim-date | tests/knowledge/test_life_dates.py::test_person_with_qid | да (1 failed, 1 warning in 1.45s) |
| Даты жизни из Wikidata | slice-instead-of-claim-date | tests/knowledge/test_life_dates.py::test_life_dates_invariant | да (1 failed, 1 warning in 2.24s) |
| Даты жизни из Wikidata | century-as-year | tests/knowledge/test_life_dates.py::test_decade_century | да (1 failed, 1 warning in 0.91s) |
| Даты жизни из Wikidata | century-as-year | tests/knowledge/test_life_dates.py::test_time_rule_any_value | да (1 failed, 1 warning in 1.19s) |
| Даты жизни из Wikidata | century-as-year | tests/knowledge/test_life_dates.py::test_life_dates_invariant | да (1 failed, 1 warning in 2.07s) |
| Даты жизни из Wikidata | existing-overwritten | tests/knowledge/test_life_dates.py::test_existing_dates | да (1 failed, 1 warning in 1.67s) |
| Даты жизни из Wikidata | existing-overwritten | tests/knowledge/test_life_dates.py::test_life_dates_invariant | да (1 failed, 1 warning in 27.22s) |
| Даты жизни из Wikidata | rollback-removes-verified | tests/knowledge/test_life_dates.py::test_rollback_keeps_verified | да (1 failed, 1 warning in 1.72s) |
| Даты жизни из Wikidata | rollback-removes-verified | tests/knowledge/test_life_dates.py::test_rollback_keeps_verified_and_qid | да (1 failed, 1 warning in 3.13s) |
| Подтверждение QID персон и произведений | qid-on-pending | tests/knowledge/test_life_dates.py::test_qid_confirmation_invariant | да (1 failed, 1 warning in 3.30s) |
| Подтверждение QID персон и произведений | auto-without-flag | tests/knowledge/test_life_dates.py::test_candidates_for_person | да (1 failed, 1 warning in 4.53s) |
| Подтверждение QID персон и произведений | auto-without-flag | tests/knowledge/test_life_dates.py::test_suggest_auto_invariant | да (1 failed, 1 warning in 12.01s) |
| Подтверждение QID персон и произведений | qid-taken-not-merged | tests/knowledge/test_life_dates.py::test_qid_taken | да (1 failed, 1 warning in 2.52s) |
| Подтверждение QID персон и произведений | own-qid-overwritten | tests/knowledge/test_life_dates.py::test_entity_has_other_qid | да (1 failed, 1 warning in 2.16s) |
| Подтверждение QID персон и произведений | own-qid-overwritten | tests/knowledge/test_life_dates.py::test_qid_confirmation_invariant | да (1 failed, 1 warning in 2.53s) |
| Подтверждение QID персон и произведений | holder-not-queued | tests/knowledge/test_life_dates.py::test_candidate_held_by_other | да (1 failed, 1 warning in 0.99s) |
| Импорт из Wikidata | import-slice | tests/knowledge/test_life_dates.py::test_import_bce | да (1 failed, 1 warning in 1.69s) |
| Импорт из Wikidata | import-slice | tests/knowledge/test_life_dates.py::test_import_invariant | да (1 failed, 1 warning in 1.82s) |

Итого: 10 мутаций, 18 ожидаемых падений — упали все 18 (rc=0).

### Дефекты

- **Д1 (код).** «Даты жизни», «Режимы»: «Утверждение запуска, которое человек успел проверить, откат MUST NOT убирать. Внешний идентификатор, на который ссылается проверенное утверждение (атрибуция `wikidata:<QID>`), тоже остаётся». Вход: `apply` с `accepted` Q859 для «Платон», `Statements.confirm(lifespan)`, `rollback(run_id)`. Ожидалось: у проверенного `lifespan` атрибуция `[("source", "wikidata:Q859")]`. Получено: утверждение и QID на месте, `kept=1`, но `attributions == []` — `Statements.rollback_run` удаляет все атрибуции запуска (`delete(attributions).where(run_id)`), в том числе у проверенных. Тест `test_rollback_verified_keeps_attribution` красный; в property `test_rollback_keeps_verified_and_qid` эта проверка вынесена в него.

### Наблюдения

- Датировка произведения точности «десятилетие/век» хранится четырьмя границами `(lo, hi, lo, hi)` — так понята строка таблицы «Границы (все четыре)»; совпало с кодом.
- Проверка «откат удаляет проверенные» — через `Statements.confirm` (путь человека), а не прямой записью статуса.

### Не покрыто / непроверяемое

- `fetch_failed` от настоящей сети, `Retry-After` — общий `http_fetch` (`wikidata.py`), не эта дельта; сеть запрещена.
- `--limit` — не нормативное в дельте, не проверялось.
- Полный `pytest` не запускался (1 ГБ RAM).
