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

### Перепроверка Д1 после 27ea2fd (разработчик: `rollback_run` не трогает проверенные)

    test_life_dates.py -k rollback: 5 passed, 26 deselected in 66.46s
    (test_rollback_verified_keeps_attribution — зелёный: атрибуция [("source", "wikidata:Q859")] сохранена)

Д1 закрыт. Мутация `rollback-removes-verified` по-прежнему ловится этими тестами (см. таблицу выше).

## Тестировщик — аудит пунктов (О21)

Систематический аудит покрытия (О21): строка «пункт → вид генератора → @example → мутация» на каждый нормативный пункт дельт `entity-dating` и `ontology-extraction`. Строк в таблице: 73. Было 10 мутаций; патчи аудита лежат в `tests/mutations/add-wikidata-life-dates/` (всего 59, новых 49, все падают).

**Пробелы, найденные аудитом, и чем закрыты.** Выжили 8 мутаций; закрыты тестами в `test_life_dates.py`: `suggest-work-needs-no-date` (`test_work_candidate_needs_publication_date`), `exact-dates-unchecked` (`test_auto_exact_needs_compatible_dates`), `suggest-only-primary-name` (`test_suggest_searches_variants`), `suggest-decided-reprocessed` (`test_suggest_keeps_human_decision`), `suggest-holder-any-type` (`test_holder_of_other_kind_ignored`), `suggest-decided-apart-requeued` (`test_holder_pair_decided_apart_not_requeued`), `linked-bad-qid-passed` (`test_linked_bad_qid_skipped_without_fetch`), `fetch-failed-as-skipped` (`test_fetch_failed_counted_as_failed`). Генераторные виды `wd_times` (точность 6–11, знак, нуль, низкая, мусор), `wd_claim_values` (ранги), `wd_person_records` (роли из таблицы и вне её), `manifests` уже покрывали таблицу точностей; мутации по каждой строке таблицы точностей (`prec-9-only`, `decade-plus-10`, `century-floor`, `millennium-floor`, `millennium-precision-century`, `prec-5-accepted`, `year-zero-accepted`, `sign-inverted`) добавлены.
Обозначения: LD = `tests/knowledge/test_life_dates.py`, LU = `test_life_dates_unit.py`, WU = `test_wikidata_unit.py`. Генераторы — `tests/knowledge/strategies.py` (S.): `wd_times` (kind ok/zero/low/garbage; знак ±, точность 6–11), `wd_claim_values` (ранги normal/preferred/deprecated, present), `wd_person_records` (person/work; P569/P570/P577, P106 из таблицы WD_ROLES и вне её WD_NOT_ROLES), `manifests` (решения pending/accepted/auto/rejected, QID верные/неверные/занятые, 0–3 кандидата). Оракул `expected_lifespan`, `expected_dating`, `wd_bounds` в S. не вызывает `wikidata`/`life_dates`. Мутации — `tests/mutations/add-wikidata-life-dates/<id>.patch`.

### entity-dating / Даты жизни из Wikidata

| Пункт | Вид генератора | @example | Мутация |
|---|---|---|---|
| Годы жизни персоны из P569/P570 | S.wd_person_records (person) | LD::test_person_with_qid, test_life_dates_invariant | slice-instead-of-claim-date |
| Датировка произведения из P577 | S.wd_person_records (work) | LD::test_work_year | work-as-lifespan |
| Роли из P106 по таблице; вне таблицы — не пишутся | S.wd_person_records (WD_ROLES / WD_NOT_ROLES) | LD::test_person_with_qid, test_life_dates_invariant (роли только из таблицы) | roles-outside-table |
| Знак — эра; `−Y` → 1 − Y; год берётся как записан | S.wd_times (sign) | LD::test_person_with_qid (−0427/−0347), test_time_rule_any_value | sign-inverted, slice-instead-of-claim-date, import-slice |
| Точность 9, 10, 11 → границы a(Y), `year` | S.wd_times (precision 9–11) | LD::test_kant_with_days (день), test_time_rule_any_value | prec-9-only |
| Точность 8 → десятилетие Y…Y+9, `decade` | S.wd_times (precision 8) | LD::test_decade_century | decade-plus-10 |
| Точность 7 → век ⌈Y/100⌉, `century`, упорядочены | S.wd_times (precision 7, ±) | LD::test_decade_century (+1801 → 1801…1900) | century-as-year, century-floor |
| Точность 6 → тысячелетие ⌈Y/1000⌉, `approx` | S.wd_times (precision 6) | LU/WU примеры точности 6; LD::test_time_rule_any_value (фактически роняет: test_life_dates_invariant) | millennium-floor, millennium-precision-century |
| Точность < 6 → нет даты, `bad_value` | S.wd_times kind low | LD::test_year_zero_and_low_precision | prec-5-accepted |
| Год `0000` → `bad_value` | S.wd_times kind zero | LD::test_year_zero_and_low_precision | year-zero-accepted |
| Значение не по формату → `bad_value` | S.wd_times kind garbage | LD::test_life_dates_invariant (garbage) (фактически роняет: test_year_zero_and_low_precision) | bad-value-as-partial |
| Годы жизни — интервал: начало из рождения, конец из смерти; `precision` — year, иначе у более широкой | S.wd_person_records + wd_times | LD::test_decade_century (decade+century → century), test_life_dates_invariant | century-as-year |
| Исходная запись — общим правилом | S.wd_person_records | LD::test_person_with_qid («427 до н. э. – 347 до н. э.»), test_kant_with_days («1724–1804») | slice-instead-of-claim-date |
| Несколько значений: предпочтённое, иначе первое обычное | S.wd_claim_values (ранги) | LD::test_life_dates_invariant (ranks) | best-normal-first |
| Устаревшее не берётся никогда | S.wd_claim_values (deprecated) | LD::test_life_dates_invariant (ranks) | best-takes-deprecated |
| Атрибуция `wikidata:<QID>` со ссылкой на страницу | S.wd_person_records | LD::test_person_with_qid | attribution-no-link |
| Статус «по источникам» | S.wd_person_records | LD::test_person_with_qid | status-generated |
| Происхождение «импорт» с номером запуска | S.wd_person_records | LD::test_person_with_qid, test_rollback_keeps_verified | provenance-no-run |
| Годы жизни только при обеих датах; одна — `partial` | S.wd_person_records (одно/оба/ни одного) | LD::test_one_date | partial-accepted |
| Ни одной даты — `no_dates` | S.wd_person_records | LD::test_life_dates_invariant | no-dates-as-partial |
| Существующая дата не перезаписывается | S.wd_person_records + существующие даты (equal/differ) | LD::test_existing_dates, test_life_dates_invariant | existing-overwritten |
| Совпадение (`span` равен) → `unchanged` | то же | LD::test_existing_dates | unchanged-as-conflict |
| Расхождение → `conflict` и пропуск; счётчик `conflicts` | то же | LD::test_existing_dates | conflict-not-counted |
| Повторный запуск не добавляет утверждений | S.wd_person_records (двойной apply) | LD::test_life_dates_invariant | rerun-recounts |
| Сухой прогон не меняет базу, отчёт тот же | S.wd_person_records (dry_run) | LD::test_dry_run_and_rollback_cli, test_life_dates_invariant | dry-run-writes |
| Откат убирает утверждения запуска | S.wd_person_records | LD::test_rollback_without_verified_restores_dump (фактически роняет: test_dry_run_and_rollback_cli) | rollback-externals-kept |
| Откат убирает записанные запуском QID | S.wd_person_records | LD::test_rollback_without_verified_restores_dump (фактически роняет: test_dry_run_and_rollback_cli) | rollback-externals-kept |
| Проверенное утверждение откат не убирает | S.wd_person_records + data (verified) | LD::test_rollback_keeps_verified, test_rollback_keeps_verified_and_qid | rollback-removes-verified |
| QID проверенного утверждения остаётся и попадает в `kept` | то же | LD::test_rollback_verified_keeps_attribution (фактически роняет: test_rollback_keeps_verified) | referenced-ignored, rollback-kept-zero |
| `skipped` с полями `entity, property, reason` | S.wd_person_records | LD::check_keys в тестах (фактически роняет: test_year_zero_and_low_precision) | skipped-event-entity-wrong |
| Причина `fetch_failed` считается в `failed`, не `skipped` | сценарный (запись не загружается) | LD::test_life_dates_invariant (failed) | fetch-failed-as-skipped |
| `run` с полями `run_id, entities, externals, lifespans, datings, roles, unchanged, conflicts, skipped, failed, dry_run` | S.wd_person_records | LD::test_person_with_qid, test_existing_dates | unchanged-as-conflict, conflict-not-counted |
| Режим `--linked`: обход сущностей с QID | сценарный | LD::test_person_with_qid (`apply --linked`) | linked-skipped |
| `--linked`: QID не по шаблону — `bad_qid` | сценарный | LD::test_life_dates_invariant (bad_qid) | linked-bad-qid-passed |
| Свойства вне перечня и P737 не импортируются | S.wd_person_records (+P737) | LD::test_influence_not_imported | import-skipped-event-missing |
| Инвариант: границы по таблице, «−» ⇒ ≤ 0 | S.wd_times, S.expected_dating | LD::test_life_dates_invariant, test_time_rule_any_value (фактически роняет: test_decade_century, test_kant_with_days, test_person_with_qid) | sign-inverted, prec-9-only, decade-plus-10, century-floor |
| Инвариант: без проверенных откат возвращает дамп; проверенное и QID сохраняются | S.wd_person_records | LD::test_rollback_without_verified_restores_dump, test_rollback_keeps_verified_and_qid | rollback-removes-verified, rollback-externals-kept |
| Сценарии: Персона с QID, Кант с днями, Год произведения, Десятилетие/век, Год 0000, Одна дата, Дата уже есть, Сухой прогон и откат, Откат с проверенным | сценарные | LD::test_person_with_qid … test_rollback_verified_keeps_attribution | slice-instead-of-claim-date, century-as-year, year-zero-accepted, partial-accepted, existing-overwritten, rollback-removes-verified |

### entity-dating / Подтверждение QID персон и произведений

| Пункт | Вид генератора | @example | Мутация |
|---|---|---|---|
| `suggest`: кандидаты по основному названию и вариантам | S.manifests (кандидаты 0–3) | LD::test_candidates_for_person (фактически роняет: test_suggest_searches_variants) | suggest-only-primary-name |
| `suggest`: поиск по ru и en | сценарный (фикстура поиска) | LD::test_candidates_for_person | suggest-single-lang |
| Кандидат персоны — человек (P31 Q5) | S.manifests (не человек) | LD::test_candidates_for_person (Q1234567) | suggest-person-class-unchecked |
| Кандидат произведения — имеет P577 | S.wd_person_records (work без P577) | LD::test_suggest_auto_invariant (фактически роняет: test_work_candidate_needs_publication_date) | suggest-work-needs-no-date |
| Кандидаты пишутся в манифест, база не меняется | S.manifests | LD::test_candidates_for_person (фактически роняет: test_candidate_held_by_other) | holder-not-queued |
| Держатель QID другого типа не считается | сценарный | LD::test_candidate_held_by_other | suggest-holder-any-type |
| Кандидат уже у другой: `holder` в кандидате, пункт `duplicate`, `merge_proposed review:qid_candidate`, без повтора | сценарный (Гомер/Омир) | LD::test_candidate_held_by_other | holder-not-queued |
| Пара с решением «разные» не ставится повторно | сценарный | LD::test_candidate_held_by_other | suggest-decided-apart-requeued |
| Решение уже принято — подбор не трогает запись | S.manifests (accepted/rejected) | LD::test_qid_confirmation_invariant | suggest-decided-reprocessed |
| Подтверждает человек (`accepted`) | S.manifests | LD::test_qid_confirmation_invariant | qid-on-pending |
| `auto` только с `--auto-exact` | S.manifests (флаг) | LD::test_exact_with_flag, test_suggest_auto_invariant | auto-without-flag |
| `auto`: кандидат ровно один | S.manifests (0–3 кандидата) | LD::test_two_candidates, test_suggest_auto_invariant | exact-multi-candidates |
| `auto`: подпись совпадает с названием/вариантом | S.manifests | LD::test_suggest_auto_invariant | exact-label-unchecked |
| `auto`: даты не противоречат | S.manifests (даты) | LD::test_suggest_auto_invariant (фактически роняет: test_auto_exact_needs_compatible_dates) | exact-dates-unchecked |
| `suggested` с `entities, candidates, auto` | S.manifests | LD::test_exact_with_flag (auto=1), test_two_candidates (auto=0) | suggested-event-auto-zero |
| Форма: `entity` уникален | S.manifests / bad (параметры) | LD::test_bad_manifest_forms | validate-entity-unique-dropped |
| Форма: `wikidata` — null или `^Q\d+$` | то же | LD::test_bad_manifest_forms | validate-qid-shape-dropped |
| Форма: `decision` ∈ {pending, accepted, auto, rejected} | то же | LD::test_bad_manifest_forms | validate-decision-set-dropped |
| Форма: accepted/auto ⇒ `wikidata` не null; код 2 до базы и сети | то же | LD::test_bad_manifest, test_bad_manifest_forms | validate-accepted-needs-qid-dropped |
| `apply` пишет QID только для accepted/auto | S.manifests | LD::test_qid_confirmation_invariant | qid-on-pending |
| Правило 1: у сущности уже этот QID — ничего | S.manifests | LD::test_qid_confirmation_invariant | same-qid-conflict |
| Правило 2: другой QID → `qid_conflict`, не перезаписывается | S.manifests | LD::test_entity_has_other_qid | own-qid-overwritten |
| Правило 3: QID занят → `qid_taken`, не записывается | S.manifests (занятые QID) | LD::test_qid_taken | qid-taken-not-skipped |
| Правило 3: два подтверждения одного QID — выигрывает первое | S.manifests | LD::test_two_confirmations (фактически роняет: test_qid_taken) | qid-taken-not-skipped |
| Правило 3: `accepted` → слиянию как `qid_confirmed` | сценарный (Hume/Юм) | LD::test_qid_taken | qid-taken-not-merged |
| Правило 3: `auto` → очередь `duplicate`, не слияние | S.manifests (auto + занятый) | LD::test_qid_confirmation_invariant (фактически роняет: test_qid_rules_conflict_taken_twice) | auto-confirmed-merged |
| Правило 4: иначе QID записывается | S.manifests | LD::test_qid_confirmation_invariant | qid-on-pending |
| Инвариант: ни у двух сущностей один QID | S.manifests | LD::test_qid_confirmation_invariant (фактически роняет: test_qid_taken) | qid-taken-not-skipped |
| Сценарии: Кандидаты, Держатель, Точное, Два кандидата, QID занят, Два подтверждения, Другой QID, Неверный манифест | сценарные | LD::test_candidates_for_person … test_bad_manifest | holder-not-queued, auto-without-flag, qid-taken-not-merged, own-qid-overwritten |

### ontology-extraction / Импорт из Wikidata

| Пункт | Вид генератора | @example | Мутация |
|---|---|---|---|
| Импортируются только даты, места, авторство, учителя; влияние — нет | сценарный (запись с P737) | LD::test_influence_not_imported | import-skipped-event-missing |
| Атрибуция, статус, внешний id у импортированного | сценарный | LD::test_import_bce | import-slice |
| Знак — эра; до н. э. — астрономический счёт; срез строки не используется | `S.wd_times` + простая запись (LD::test_time_rule_any_value) | LD::test_import_bce (−0427/−0347 → −426, −346) | import-slice |
| Годы жизни только при обеих датах | сценарный + S.wd_times | LD::test_import_one_date | import-partial-event-missing |
| Одна дата — `knowledge.import.skipped reason="partial"` | сценарный | LD::test_import_one_date | import-partial-event-missing |
| Инвариант: «−» даёт начало ≤ 0; записанное равно разбору общим правилом | S.wd_times | LD::test_time_rule_any_value, test_import_invariant | import-slice, sign-inverted |



Прогоны мутаций аудита (требование | мутация | тест | упал):

| Требование | Мутация | Тест | Упал |
|---|---|---|---|
| Даты жизни из Wikidata | prec-9-only | tests/knowledge/test_life_dates.py::test_kant_with_days | да (1) |
| Даты жизни из Wikidata | decade-plus-10 | tests/knowledge/test_life_dates.py::test_decade_century | да (1) |
| Даты жизни из Wikidata | century-floor | tests/knowledge/test_life_dates.py::test_decade_century | да (1) |
| Даты жизни из Wikidata | millennium-floor | tests/knowledge/test_life_dates.py::test_life_dates_invariant | да (1) |
| Даты жизни из Wikidata | millennium-precision-century | tests/knowledge/test_life_dates.py::test_life_dates_invariant | да (1) |
| Даты жизни из Wikidata | prec-5-accepted | tests/knowledge/test_life_dates.py::test_year_zero_and_low_precision | да (1) |
| Даты жизни из Wikidata | year-zero-accepted | tests/knowledge/test_life_dates.py::test_year_zero_and_low_precision | да (1) |
| Даты жизни из Wikidata | sign-inverted | tests/knowledge/test_life_dates.py::test_person_with_qid | да (1) |
| Даты жизни из Wikidata | best-normal-first | tests/knowledge/test_life_dates.py::test_life_dates_invariant | да (1) |
| Даты жизни из Wikidata | best-takes-deprecated | tests/knowledge/test_life_dates.py::test_life_dates_invariant | да (1) |
| Даты жизни из Wikidata | bad-value-as-partial | tests/knowledge/test_life_dates.py::test_year_zero_and_low_precision | да (1) |
| Даты жизни из Wikidata | no-dates-as-partial | tests/knowledge/test_life_dates.py::test_life_dates_invariant | да (1) |
| Даты жизни из Wikidata | partial-accepted | tests/knowledge/test_life_dates.py::test_one_date | да (1) |
| Даты жизни из Wikidata | unchanged-as-conflict | tests/knowledge/test_life_dates.py::test_existing_dates | да (1) |
| Даты жизни из Wikidata | conflict-not-counted | tests/knowledge/test_life_dates.py::test_existing_dates | да (1) |
| Даты жизни из Wikidata | skipped-event-entity-wrong | tests/knowledge/test_life_dates.py::test_year_zero_and_low_precision | да (1) |
| Даты жизни из Wikidata | roles-outside-table | tests/knowledge/test_life_dates.py::test_life_dates_invariant | да (1) |
| Даты жизни из Wikidata | attribution-no-link | tests/knowledge/test_life_dates.py::test_person_with_qid | да (1) |
| Даты жизни из Wikidata | status-generated | tests/knowledge/test_life_dates.py::test_person_with_qid | да (1) |
| Даты жизни из Wikidata | provenance-no-run | tests/knowledge/test_life_dates.py::test_person_with_qid | да (1) |
| Даты жизни из Wikidata | dry-run-writes | tests/knowledge/test_life_dates.py::test_dry_run_and_rollback_cli | да (1) |
| Даты жизни из Wikidata | rerun-recounts | tests/knowledge/test_life_dates.py::test_life_dates_invariant | да (1) |
| Даты жизни из Wikidata | rollback-externals-kept | tests/knowledge/test_life_dates.py::test_dry_run_and_rollback_cli | да (1) |
| Даты жизни из Wikidata | rollback-kept-zero | tests/knowledge/test_life_dates.py::test_rollback_keeps_verified | да (1) |
| Даты жизни из Wikidata | referenced-ignored | tests/knowledge/test_life_dates.py::test_rollback_keeps_verified | да (1) |
| Подтверждение QID персон и произведений | suggest-person-class-unchecked | tests/knowledge/test_life_dates.py::test_candidates_for_person | да (1) |
| Подтверждение QID персон и произведений | suggest-work-needs-no-date | tests/knowledge/test_life_dates.py::test_work_candidate_needs_publication_date | да (1) |
| Подтверждение QID персон и произведений | exact-multi-candidates | tests/knowledge/test_life_dates.py::test_two_candidates | да (1) |
| Подтверждение QID персон и произведений | exact-label-unchecked | tests/knowledge/test_life_dates.py::test_suggest_auto_invariant | да (1) |
| Подтверждение QID персон и произведений | exact-dates-unchecked | tests/knowledge/test_life_dates.py::test_auto_exact_needs_compatible_dates | да (1) |
| Подтверждение QID персон и произведений | suggest-only-primary-name | tests/knowledge/test_life_dates.py::test_suggest_searches_variants | да (1) |
| Подтверждение QID персон и произведений | suggest-single-lang | tests/knowledge/test_life_dates.py::test_candidates_for_person | да (1) |
| Подтверждение QID персон и произведений | suggest-decided-reprocessed | tests/knowledge/test_life_dates.py::test_suggest_keeps_human_decision | да (1) |
| Подтверждение QID персон и произведений | suggest-holder-any-type | tests/knowledge/test_life_dates.py::test_holder_of_other_kind_ignored | да (1) |
| Подтверждение QID персон и произведений | suggest-decided-apart-requeued | tests/knowledge/test_life_dates.py::test_holder_pair_decided_apart_not_requeued | да (1) |
| Подтверждение QID персон и произведений | suggested-event-auto-zero | tests/knowledge/test_life_dates.py::test_exact_with_flag | да (1) |
| Подтверждение QID персон и произведений | validate-entity-unique-dropped | tests/knowledge/test_life_dates.py::test_bad_manifest_forms | да (1) |
| Подтверждение QID персон и произведений | validate-qid-shape-dropped | tests/knowledge/test_life_dates.py::test_bad_manifest_forms | да (1) |
| Подтверждение QID персон и произведений | validate-decision-set-dropped | tests/knowledge/test_life_dates.py::test_bad_manifest_forms | да (1) |
| Подтверждение QID персон и произведений | validate-accepted-needs-qid-dropped | tests/knowledge/test_life_dates.py::test_bad_manifest | да (1) |
| Подтверждение QID персон и произведений | qid-taken-not-skipped | tests/knowledge/test_life_dates.py::test_qid_taken | да (1) |
| Подтверждение QID персон и произведений | same-qid-conflict | tests/knowledge/test_life_dates.py::test_qid_confirmation_invariant | да (1) |
| Подтверждение QID персон и произведений | auto-confirmed-merged | tests/knowledge/test_life_dates_unit.py::test_qid_rules_conflict_taken_twice | да (1) |
| Даты жизни из Wikidata | linked-skipped | tests/knowledge/test_life_dates.py::test_person_with_qid | да (1) |
| Даты жизни из Wikidata | linked-bad-qid-passed | tests/knowledge/test_life_dates.py::test_linked_bad_qid_skipped_without_fetch | да (1) |
| Даты жизни из Wikidata | fetch-failed-as-skipped | tests/knowledge/test_life_dates.py::test_fetch_failed_counted_as_failed | да (1) |
| Даты жизни из Wikidata | work-as-lifespan | tests/knowledge/test_life_dates.py::test_work_year | да (1) |
| Импорт из Wikidata | import-skipped-event-missing | tests/knowledge/test_life_dates.py::test_influence_not_imported | да (1) |
| Импорт из Wikidata | import-partial-event-missing | tests/knowledge/test_life_dates.py::test_import_one_date | да (1) |

**Не покрыто:**
- «Сеть используется только общим доступом к Wikidata» — структурное свойство (импорт `http_fetch` в одном модуле); мутацией не ломается, проверяется тестами `no_network` (сетевой вызов даёт ошибку).
- Код выхода 2 и текст сообщения `apply` с неверным манифестом проверяет `test_bad_manifest`; мутаций на слой CLI нет.

**Дефекты:** расхождений кода со спецификацией не найдено.

Штатный прогон `scripts/mutation_check.py --change add-wikidata-life-dates --id suggest-work-needs-no-date` в worktree: test_work_candidate_needs_publication_date упал. Остальные мутации — тем же способом (патч в worktree от HEAD, pytest по связанным файлам).
