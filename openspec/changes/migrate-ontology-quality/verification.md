# Проверка: migrate-ontology-quality

## Тестировщик — 2026-11-26, тесты на bb0340d, код на 1923675 (Д1-mig, Д2-mig), bf2d84f (Д3-mig), спецификация 312ff2e (О27)

Тесты пишутся от сценариев и нормативных фраз `specs/ontology-migration/spec.md`. Модель фейковая (`FakeLLM`), Wikidata — фикстуры (`RecordFetch`), сеть запрещена. Оракулы — `tests/knowledge/migration_world.py`, модули под тестом не импортируются: язык, правило number, нормализация, `a1`–`a5`, `a4_pairs`, `losses`, `verified_dropped`, `name_forms_broken`, `langs_broken`. Ключи событий сверяются точно (`check_keys`).

### Покрытие по требованиям

| Требование | Сценарные | Property (профиль) | Мутаций | Упали все ожидаемые |
|---|---|---|---|---|
| Миграция существующей онтологии | Форма названий; Синтетическая онтология стенда; Транслитерация без решения человека; Сухой прогон; Потеря — аварийный откат; Проверенное человеком не трогается; В журнале нет названий; плюс О29: шаг 7 same_name, шаг 2 после открытой пары, шаг 1 после чистого, источник не снимается, dry_run события шага, `--limit` | test_migration_invariant (heavy) | 24 | да |
| Снятие мусорных сущностей | Номер раздела снят; Ассистент не видит снятое; Возврат при откате | test_retire_invariant (ci) | 6 | да |
| Перевод названий | Пакет с ошибками модели; Русское стоп-слово от модели («universality», О27); Подпись из Wikidata раньше модели; Без флага модель не вызывается; Оценка стоимости; порядок проверок ответа (6 пар); О29: подписи Wikidata после сбоя и отказа | test_translation_invariant (ci) | 21 | да |
| Откат миграции | Полный откат; Последующее изменение сохраняется; проверенное и его QID остаются; О29: пункты очереди запуска → rolled_back, позднее слияние человека остаётся | test_rollback_invariant (heavy) | 9 | да |
| Замер качества онтологии | Синтетическая онтология до и после; А4 — объединение и решение «разные»; А6 и А7 совпадают с API; Без базы сравнения; Только чтение; Старая схема; приёмка П1–П4; О29: пороги на границе, А7 все страницы, А8 с атрибуцией, А4 без пунктов не-персон | test_quality_invariant (ci) | 21 | да |

### Дефекты и расхождения

| № | Ожидалось по спецификации | Получено | Статус |
|---|---|---|---|
| Д1-mig | «Синтетическая онтология стенда»: после слияния «Hume» → «Юм» у «Юм» одно основное и варианты без повторов | точный повтор `(ru, Юм)` переносился вариантом (test_stand_synthetic:309) | исправлен в 1923675, тест зелёный |
| Д2-mig | «Проверенное человеком не трогается» | проверенное утверждение сворачивалось в непроверенный повтор и становилось «по источникам» (test_verified_untouched:474, оракул `verified_dropped`) | исправлен в 1923675, тест зелёный |
| Д3-mig | шаг `lang_fix`: язык по правилу `entity-naming`, у названия без письменности — `und` | у источника «3.1» оставался `en` (test_lang_fix_no_script) | исправлен в bf2d84f, тест зелёный |
| С1 | сценарий «Русское стоп-слово от модели» на «every» | «every» снимается шагом `retire` раньше перевода, до модели оно не доходит | спецификация исправлена в 312ff2e (О27, «universality»), тест обновлён (2c458ec) |
| С2 | текст спецификации «семи шагов» | шагов восемь | решено в О30 (dd1ecc7): «восьми шагов» |
| С3 | шаг 7: источники в очередь `review:same_name` не ставятся? | спецификация не исключала источники | решено в О30: источники не ставятся, остальные не-персоны ставятся. Тест test_same_name_sources_not_queued, мутация same-name-includes-source |
| С4 | шаг 2: пару, закрытую «разные», не ставить? | спецификация говорила только про открытый пункт | решено в О30: не ставится. Тест test_pending_candidate_distinct_not_queued, мутация manifest-candidate-ignores-distinct. `qid-candidate-requeued` остаётся эквивалентным в части открытой пары |
| С5 | бюджет property-слоя ≤ 3 мин | считается на каждое изменение (О30) | миграция: property-слой ≈ 153 s (retire 63,09 + quality 39,65 + migration 24,19 + rollback 19,89 + translation 6,48), весь файл 214,59 s; в бюджете |
| С6 | — | у строки журнала действий `manifest_qids` нет поля `step` (`run_actions`, test_dry_run отфильтровывает их через `"step" in a`) | наблюдение, спецификация поля не требует |

### Эквивалентные мутанты (в yaml не вошли)

- `retire-source`, `a2-with-source`: правило названий не проверяет источники библиотеки (`entity-naming`), поэтому `check_name("source", "3.1") is None`. Без отдельного фильтра поведение то же. Пункт «кроме источников» проверяют `test_source_not_retired` и `test_quality_invariant` (SYMPTOMS_SPEC, s:3.1).
- `qid-candidate-requeued`: см. С4.
- Прогон «`continue` → `break`» в `ontology_migrate` (15 мест): L440 `verify` последний, после него циклов нет. Остальные 14 мест ловят тесты (мутации `*-stops-after-*` в yaml).

### Сырые прогоны

- `pytest tests/knowledge/test_ontology_migration.py --durations=10`:
```

============================= slowest 10 durations =============================
63.09s call     tests/knowledge/test_ontology_migration.py::test_retire_invariant
39.65s call     tests/knowledge/test_ontology_migration.py::test_quality_invariant
24.19s call     tests/knowledge/test_ontology_migration.py::test_migration_invariant
19.89s call     tests/knowledge/test_ontology_migration.py::test_rollback_invariant
6.48s call     tests/knowledge/test_ontology_migration.py::test_translation_invariant
3.37s call     tests/knowledge/test_ontology_migration.py::test_acceptance_symptoms
2.99s call     tests/knowledge/test_ontology_migration.py::test_loss_aborts
2.98s call     tests/knowledge/test_ontology_migration.py::test_stand_synthetic
2.83s call     tests/knowledge/test_ontology_migration.py::test_full_rollback
2.79s call     tests/knowledge/test_ontology_migration.py::test_dry_run
52 passed, 1 warning in 214.59s (0:03:34)
```

- прежние тесты (tasks 3.6): `test_ontology_retrieval, test_catalog, test_geo_{coordinates,enrich,layer,units}, test_graph, test_map, test_map_view, test_mentions_cards, test_portraits` — 403 passed, 1 warning in 379.21s (0:06:19). Ожидания этих тестов в изменении правились только в номере схемы 8 → 9 (e512275: test_mentions_cards, test_portraits); браузерные e2e/web не запускались (1 ГБ RAM).
- `mutation_check.py --coverage migrate-ontology-quality`: migrate-ontology-quality: мутации есть у всех 5 требований
- `check_traceability.py`: Требований с тестами: 415 из 415; `ontology-migration` в `enforce` (openspec/traceability.yaml)
- `ruff check` / `ruff format --check tests/knowledge/` — чисто

### Мутации: `scripts/mutation_check.py --change migrate-ontology-quality --id <id>` по каждой из 81 (по одной под flock), 155 строк, «НЕТ» — 0

| Требование | Мутация | Ожидаемый тест | Упал |
|---|---|---|---|
| Миграция существующей онтологии | verify-no-abort | tests/knowledge/test_ontology_migration.py::test_loss_aborts | да (1 failed, 1 warning in 3.65s) |
| Миграция существующей онтологии | plan-writes-lang | tests/knowledge/test_ontology_migration.py::test_dry_run | да (1 failed, 1 warning in 2.80s) |
| Миграция существующей онтологии | plan-writes-lang | tests/knowledge/test_ontology_migration.py::test_migration_invariant | да (1 failed, 1 warning in 1.58s) |
| Миграция существующей онтологии | step-event-with-names | tests/knowledge/test_ontology_migration.py::test_dry_run | да (1 failed, 1 warning in 2.71s) |
| Миграция существующей онтологии | step-event-with-names | tests/knowledge/test_ontology_migration.py::test_lang_fix_no_script | да (1 failed, 1 warning in 0.75s) |
| Миграция существующей онтологии | step-event-with-names | tests/knowledge/test_ontology_migration.py::test_loss_aborts | да (1 failed, 1 warning in 2.48s) |
| Миграция существующей онтологии | step-event-with-names | tests/knowledge/test_ontology_migration.py::test_migration_invariant | да (1 failed, 1 warning in 1.42s) |
| Миграция существующей онтологии | step-event-with-names | tests/knowledge/test_ontology_migration.py::test_name_form | да (1 failed, 1 warning in 1.01s) |
| Миграция существующей онтологии | step-event-with-names | tests/knowledge/test_ontology_migration.py::test_no_names_in_journal | да (1 failed, 1 warning in 0.84s) |
| Миграция существующей онтологии | step-event-with-names | tests/knowledge/test_ontology_migration.py::test_stand_synthetic | да (1 failed, 1 warning in 2.34s) |
| Миграция существующей онтологии | step-event-with-names | tests/knowledge/test_ontology_migration.py::test_transliteration_pending | да (1 failed, 1 warning in 2.45s) |
| Миграция существующей онтологии | step-event-with-names | tests/knowledge/test_ontology_migration.py::test_verified_untouched | да (1 failed, 1 warning in 2.50s) |
| Миграция существующей онтологии | confirmed-not-passed | tests/knowledge/test_ontology_migration.py::test_migration_invariant | да (1 failed, 1 warning in 2.56s) |
| Миграция существующей онтологии | confirmed-not-passed | tests/knowledge/test_ontology_migration.py::test_stand_synthetic | да (1 failed, 1 warning in 2.70s) |
| Миграция существующей онтологии | dedupe-before-rename | tests/knowledge/test_ontology_migration.py::test_migration_invariant | да (1 failed, 1 warning in 3.17s) |
| Миграция существующей онтологии | dedupe-before-rename | tests/knowledge/test_ontology_migration.py::test_stand_synthetic | да (1 failed, 1 warning in 3.02s) |
| Миграция существующей онтологии | dedupe-before-rename | tests/knowledge/test_ontology_migration.py::test_transliteration_pending | да (1 failed, 1 warning in 2.85s) |
| Миграция существующей онтологии | retire-skips-person | tests/knowledge/test_ontology_migration.py::test_dry_run | да (1 failed, 1 warning in 2.99s) |
| Миграция существующей онтологии | retire-skips-person | tests/knowledge/test_ontology_migration.py::test_migration_invariant | да (1 failed, 1 warning in 2.65s) |
| Миграция существующей онтологии | retire-skips-person | tests/knowledge/test_ontology_migration.py::test_stand_synthetic | да (1 failed, 1 warning in 3.01s) |
| Снятие мусорных сущностей | snapshot-keeps-retired-ends | tests/knowledge/test_ontology_migration.py::test_retire_invariant | да (1 failed, 1 warning in 251.37s (0:04:11)) |
| Снятие мусорных сущностей | snapshot-shows-retired | tests/knowledge/test_ontology_migration.py::test_retire_invariant | да (1 failed, 1 warning in 15.12s) |
| Снятие мусорных сущностей | snapshot-shows-retired | tests/knowledge/test_ontology_migration.py::test_section_number_retired | да (1 failed, 1 warning in 0.97s) |
| Перевод названий | accept-latin | tests/knowledge/test_ontology_migration.py::test_batch_with_model_errors | да (1 failed, 1 warning in 0.68s) |
| Перевод названий | accept-latin | tests/knowledge/test_ontology_migration.py::test_reply_check_order_pairs | да (1 failed, 2 passed, 1 warning in 1.41s) |
| Перевод названий | accept-latin | tests/knowledge/test_ontology_migration.py::test_translation_invariant | да (1 failed, 1 warning in 8.34s) |
| Перевод названий | duplicate-rejects-second-only | tests/knowledge/test_ontology_migration.py::test_batch_with_model_errors | да (1 failed, 1 warning in 0.72s) |
| Перевод названий | duplicate-rejects-second-only | tests/knowledge/test_ontology_migration.py::test_reply_check_order_pairs | да (1 failed, 1 warning in 0.66s) |
| Перевод названий | duplicate-rejects-second-only | tests/knowledge/test_ontology_migration.py::test_translation_invariant | да (1 failed, 1 warning in 1.19s) |
| Перевод названий | model-without-flag | tests/knowledge/test_ontology_migration.py::test_no_model_without_flag | да (1 failed, 1 warning in 2.99s) |
| Перевод названий | model-without-flag | tests/knowledge/test_ontology_migration.py::test_translation_invariant | да (1 failed, 1 warning in 0.91s) |
| Откат миграции | rollback-no-undo-merge | tests/knowledge/test_ontology_migration.py::test_full_rollback | да (1 failed, 1 warning in 3.22s) |
| Откат миграции | rollback-no-undo-merge | tests/knowledge/test_ontology_migration.py::test_name_form | да (1 failed, 1 warning in 0.92s) |
| Откат миграции | rollback-no-undo-merge | tests/knowledge/test_ontology_migration.py::test_rollback_invariant | да (1 failed, 1 warning in 1.85s) |
| Откат миграции | rollback-no-manifest | tests/knowledge/test_ontology_migration.py::test_rollback_invariant | да (1 failed, 1 warning in 2.15s) |
| Откат миграции | rollback-no-manifest | tests/knowledge/test_ontology_migration.py::test_rollback_keeps_verified_qid | да (1 failed, 1 warning in 0.78s) |
| Откат миграции | rollback-overwrites-later | tests/knowledge/test_ontology_migration.py::test_later_change_kept | да (1 failed, 1 warning in 0.75s) |
| Замер качества онтологии | a4-no-queue | tests/knowledge/test_ontology_migration.py::test_quality_invariant | да (1 failed, 1 warning in 119.50s (0:01:59)) |
| Замер качества онтологии | a4-no-queue | tests/knowledge/test_ontology_migration.py::test_transliteration_pending | да (1 failed, 1 warning in 2.65s) |
| Замер качества онтологии | a4-sum | tests/knowledge/test_ontology_migration.py::test_a4_union_and_distinct | да (1 failed, 1 warning in 0.74s) |
| Замер качества онтологии | a4-counts-distinct | tests/knowledge/test_ontology_migration.py::test_a4_union_and_distinct | да (1 failed, 1 warning in 0.76s) |
| Замер качества онтологии | a4-primary-only | tests/knowledge/test_ontology_migration.py::test_a4_primary_in_variants | да (1 failed, 1 warning in 0.76s) |
| Замер качества онтологии | a4-primary-only | tests/knowledge/test_ontology_migration.py::test_a4_union_and_distinct | да (1 failed, 1 warning in 1.17s) |
| Замер качества онтологии | quality-writable | tests/knowledge/test_ontology_migration.py::test_read_only | да (1 failed, 1 warning in 2.44s) |
| Замер качества онтологии | a1-with-source | tests/knowledge/test_ontology_migration.py::test_quality_invariant | да (1 failed, 1 warning in 2.85s) |
| Замер качества онтологии | a6-no-filter | tests/knowledge/test_ontology_migration.py::test_a6_a7_match_api | да (1 failed, 1 warning in 1.17s) |
| Замер качества онтологии | a6-no-filter | tests/knowledge/test_ontology_migration.py::test_quality_invariant | да (1 failed, 1 warning in 2.65s) |
| Замер качества онтологии | a1-threshold-gt | tests/knowledge/test_ontology_migration.py::test_thresholds_at_boundary | да (1 failed, 1 warning in 2.13s) |
| Замер качества онтологии | a2-any-reason | tests/knowledge/test_ontology_migration.py::test_quality_before_after | да (1 failed, 1 warning in 2.31s) |
| Замер качества онтологии | a2-any-reason | tests/knowledge/test_ontology_migration.py::test_quality_invariant | да (1 failed, 1 warning in 2.61s) |
| Замер качества онтологии | a3-concept-rule | tests/knowledge/test_ontology_migration.py::test_quality_before_after | да (1 failed, 1 warning in 2.40s) |
| Замер качества онтологии | a3-concept-rule | tests/knowledge/test_ontology_migration.py::test_quality_invariant | да (1 failed, 1 warning in 71.42s (0:01:11)) |
| Замер качества онтологии | a4-non-persons | tests/knowledge/test_ontology_migration.py::test_a4_ignores_non_person_items | да (1 failed, 1 warning in 0.78s) |
| Замер качества онтологии | a5-all-types | tests/knowledge/test_ontology_migration.py::test_thresholds_at_boundary | да (1 failed, 1 warning in 2.46s) |
| Замер качества онтологии | a5-threshold-gt | tests/knowledge/test_ontology_migration.py::test_thresholds_at_boundary | да (1 failed, 1 warning in 2.57s) |
| Замер качества онтологии | a6-threshold-gt | tests/knowledge/test_ontology_migration.py::test_thresholds_at_boundary | да (1 failed, 1 warning in 2.46s) |
| Замер качества онтологии | a7-concept-rule | tests/knowledge/test_ontology_migration.py::test_quality_invariant | да (1 failed, 1 warning in 73.27s (0:01:13)) |
| Замер качества онтологии | a7-first-page | tests/knowledge/test_ontology_migration.py::test_a7_all_pages | да (1 failed, 1 warning in 1.26s) |
| Замер качества онтологии | a8-statements-only | tests/knowledge/test_ontology_migration.py::test_a8_counts_lost_attribution | да (1 failed, 1 warning in 0.87s) |
| Замер качества онтологии | a8-zero-without-baseline | tests/knowledge/test_ontology_migration.py::test_without_baseline | да (1 failed, 1 warning in 0.74s) |
| Миграция существующей онтологии | aborted-no-error-kind | tests/knowledge/test_ontology_migration.py::test_loss_aborts | да (1 failed, 1 warning in 2.98s) |
| Перевод названий | batch-ignored | tests/knowledge/test_ontology_migration.py::test_translation_invariant | да (1 failed, 1 warning in 1.07s) |
| Перевод названий | estimate-no-multiply | tests/knowledge/test_ontology_migration.py::test_estimate | да (1 failed, 1 warning in 1.71s) |
| Замер качества онтологии | exit-always-zero | tests/knowledge/test_ontology_migration.py::test_quality_before_after | да (1 failed, 1 warning in 2.25s) |
| Замер качества онтологии | exit-always-zero | tests/knowledge/test_ontology_migration.py::test_quality_invariant | да (1 failed, 1 warning in 2.87s) |
| Замер качества онтологии | exit-always-zero | tests/knowledge/test_ontology_migration.py::test_transliteration_pending | да (1 failed, 1 warning in 3.06s) |
| Замер качества онтологии | exit-always-zero | tests/knowledge/test_ontology_migration.py::test_without_baseline | да (1 failed, 1 warning in 0.64s) |
| Перевод названий | gateway-failure-raises | tests/knowledge/test_ontology_migration.py::test_translation_invariant | да (1 failed, 1 warning in 1.03s) |
| Перевод названий | invalid-unchecked | tests/knowledge/test_ontology_migration.py::test_russian_stopword | да (1 failed, 1 warning in 0.75s) |
| Перевод названий | invalid-unchecked | tests/knowledge/test_ontology_migration.py::test_translation_invariant | да (1 failed, 1 warning in 3.02s) |
| Миграция существующей онтологии | lang-fix-skipped | tests/knowledge/test_ontology_migration.py::test_lang_fix_no_script | да (1 failed, 1 warning in 0.66s) |
| Миграция существующей онтологии | lang-fix-skipped | tests/knowledge/test_ontology_migration.py::test_migration_invariant | да (1 failed, 1 warning in 27.55s) |
| Миграция существующей онтологии | lang-fix-stops-after-right-name | tests/knowledge/test_ontology_migration.py::test_lang_fix_no_script | да (1 failed, 1 warning in 0.64s) |
| Миграция существующей онтологии | limit-ignored | tests/knowledge/test_ontology_migration.py::test_limit_only_translation | да (1 failed, 1 warning in 0.72s) |
| Миграция существующей онтологии | manifest-candidate-stops-after-free | tests/knowledge/test_ontology_migration.py::test_transliteration_pending | да (1 failed, 1 passed, 1 warning in 5.31s) |
| Миграция существующей онтологии | manifest-candidate-stops-after-open | tests/knowledge/test_ontology_migration.py::test_pending_candidate_after_open_pair | да (1 failed, 1 warning in 2.96s) |
| Миграция существующей онтологии | manifest-pending-stops-after-decided | tests/knowledge/test_ontology_migration.py::test_transliteration_pending | да (1 failed, 1 passed, 1 warning in 5.56s) |
| Замер качества онтологии | measured-extra-field | tests/knowledge/test_ontology_migration.py::test_a4_primary_in_variants | да (1 failed, 1 warning in 0.71s) |
| Замер качества онтологии | measured-extra-field | tests/knowledge/test_ontology_migration.py::test_a4_union_and_distinct | да (1 failed, 1 warning in 0.85s) |
| Замер качества онтологии | measured-extra-field | tests/knowledge/test_ontology_migration.py::test_a6_a7_match_api | да (1 failed, 1 warning in 1.05s) |
| Замер качества онтологии | measured-extra-field | tests/knowledge/test_ontology_migration.py::test_acceptance_symptoms | да (1 failed, 1 warning in 2.57s) |
| Замер качества онтологии | measured-extra-field | tests/knowledge/test_ontology_migration.py::test_old_schema | да (1 failed, 1 warning in 0.83s) |
| Замер качества онтологии | measured-extra-field | tests/knowledge/test_ontology_migration.py::test_quality_before_after | да (1 failed, 1 warning in 3.15s) |
| Замер качества онтологии | measured-extra-field | tests/knowledge/test_ontology_migration.py::test_quality_invariant | да (1 failed, 1 warning in 4.94s) |
| Замер качества онтологии | measured-extra-field | tests/knowledge/test_ontology_migration.py::test_read_only | да (1 failed, 1 warning in 2.63s) |
| Замер качества онтологии | measured-extra-field | tests/knowledge/test_ontology_migration.py::test_transliteration_pending | да (1 failed, 1 warning in 3.12s) |
| Замер качества онтологии | measured-extra-field | tests/knowledge/test_ontology_migration.py::test_without_baseline | да (1 failed, 1 warning in 0.63s) |
| Перевод названий | missing-not-counted | tests/knowledge/test_ontology_migration.py::test_batch_with_model_errors | да (1 failed, 1 warning in 0.75s) |
| Перевод названий | missing-not-counted | tests/knowledge/test_ontology_migration.py::test_reply_check_order_pairs | да (1 failed, 1 warning in 0.62s) |
| Перевод названий | missing-not-counted | tests/knowledge/test_ontology_migration.py::test_translation_invariant | да (1 failed, 1 warning in 7.82s) |
| Миграция существующей онтологии | normalize-key-stale | tests/knowledge/test_ontology_migration.py::test_migration_invariant | да (1 failed, 1 warning in 2.93s) |
| Миграция существующей онтологии | normalize-key-stale | tests/knowledge/test_ontology_migration.py::test_name_form | да (1 failed, 1 warning in 0.99s) |
| Миграция существующей онтологии | normalize-skipped | tests/knowledge/test_ontology_migration.py::test_migration_invariant | да (1 failed, 1 warning in 2.32s) |
| Миграция существующей онтологии | normalize-skipped | tests/knowledge/test_ontology_migration.py::test_name_form | да (1 failed, 1 warning in 1.32s) |
| Миграция существующей онтологии | normalize-stops-after-clean-name | tests/knowledge/test_ontology_migration.py::test_normalize_after_clean_name | да (1 failed, 1 warning in 0.64s) |
| Перевод названий | not-russian-before-duplicate | tests/knowledge/test_ontology_migration.py::test_batch_with_model_errors | да (1 failed, 1 warning in 0.69s) |
| Перевод названий | not-russian-before-duplicate | tests/knowledge/test_ontology_migration.py::test_reply_check_order_pairs | да (1 failed, 1 passed, 1 warning in 0.92s) |
| Перевод названий | pack-n-from-zero | tests/knowledge/test_ontology_migration.py::test_batch_with_model_errors | да (1 failed, 1 warning in 0.67s) |
| Перевод названий | pack-n-from-zero | tests/knowledge/test_ontology_migration.py::test_russian_stopword | да (1 failed, 1 warning in 0.67s) |
| Перевод названий | pack-n-from-zero | tests/knowledge/test_ontology_migration.py::test_stand_synthetic | да (1 failed, 1 warning in 2.89s) |
| Перевод названий | pack-n-from-zero | tests/knowledge/test_ontology_migration.py::test_translation_invariant | да (1 failed, 1 warning in 0.85s) |
| Перевод названий | pack-with-ids | tests/knowledge/test_ontology_migration.py::test_batch_with_model_errors | да (1 failed, 1 warning in 0.76s) |
| Миграция существующей онтологии | plan-folds-zero | tests/knowledge/test_ontology_migration.py::test_dry_run | да (1 failed, 1 warning in 2.97s) |
| Миграция существующей онтологии | plan-folds-zero | tests/knowledge/test_ontology_migration.py::test_migration_invariant | да (1 failed, 1 warning in 1.93s) |
| Миграция существующей онтологии | qid-candidate-reason | tests/knowledge/test_ontology_migration.py::test_transliteration_pending | да (1 failed, 1 warning in 3.04s) |
| Миграция существующей онтологии | queue-stops-after-open-pair | tests/knowledge/test_ontology_migration.py::test_same_name_queue_after_skips | да (1 failed, 1 warning in 0.74s) |
| Перевод названий | rename-drops-old-primary | tests/knowledge/test_ontology_migration.py::test_stand_synthetic | да (1 failed, 1 warning in 3.08s) |
| Перевод названий | rename-drops-old-primary | tests/knowledge/test_ontology_migration.py::test_translation_invariant | да (1 failed, 1 warning in 0.98s) |
| Перевод названий | reply-duplicate-before-unknown | tests/knowledge/test_ontology_migration.py::test_batch_with_model_errors | да (1 failed, 1 warning in 0.83s) |
| Перевод названий | reply-duplicate-before-unknown | tests/knowledge/test_ontology_migration.py::test_reply_check_order_pairs | да (1 failed, 1 warning in 0.67s) |
| Перевод названий | reply-duplicate-before-unknown | tests/knowledge/test_ontology_migration.py::test_translation_invariant | да (1 failed, 1 warning in 1.04s) |
| Перевод названий | reply-invalid-before-duplicate | tests/knowledge/test_ontology_migration.py::test_reply_check_order_pairs | да (1 failed, 1 warning in 0.74s) |
| Перевод названий | reply-invalid-before-not-russian | tests/knowledge/test_ontology_migration.py::test_batch_with_model_errors | да (1 failed, 1 warning in 0.69s) |
| Перевод названий | reply-invalid-before-not-russian | tests/knowledge/test_ontology_migration.py::test_reply_check_order_pairs | да (1 failed, 2 passed, 1 warning in 1.29s) |
| Снятие мусорных сущностей | retire-stops-after-source | tests/knowledge/test_ontology_migration.py::test_retire_invariant | да (1 failed, 1 warning in 117.64s (0:01:57)) |
| Снятие мусорных сущностей | retired-event-label | tests/knowledge/test_ontology_migration.py::test_assistant_does_not_see_retired | да (1 failed, 1 warning in 0.77s) |
| Снятие мусорных сущностей | retired-event-label | tests/knowledge/test_ontology_migration.py::test_restore_on_rollback | да (1 failed, 1 warning in 0.75s) |
| Снятие мусорных сущностей | retired-event-label | tests/knowledge/test_ontology_migration.py::test_retire_invariant | да (1 failed, 1 warning in 13.31s) |
| Снятие мусорных сущностей | retired-event-label | tests/knowledge/test_ontology_migration.py::test_section_number_retired | да (1 failed, 1 warning in 0.78s) |
| Снятие мусорных сущностей | retired-event-label | tests/knowledge/test_ontology_migration.py::test_stand_synthetic | да (1 failed, 1 warning in 2.41s) |
| Откат миграции | rollback-kept-ignored | tests/knowledge/test_ontology_migration.py::test_later_change_kept | да (1 failed, 1 warning in 0.70s) |
| Откат миграции | rollback-no-lang | tests/knowledge/test_ontology_migration.py::test_full_rollback | да (1 failed, 1 warning in 3.40s) |
| Откат миграции | rollback-no-lang | tests/knowledge/test_ontology_migration.py::test_name_form | да (1 failed, 1 warning in 1.02s) |
| Откат миграции | rollback-no-lang | tests/knowledge/test_ontology_migration.py::test_rollback_invariant | да (1 failed, 1 warning in 3.01s) |
| Откат миграции | rollback-no-restore | tests/knowledge/test_ontology_migration.py::test_full_rollback | да (1 failed, 1 warning in 3.58s) |
| Откат миграции | rollback-no-restore | tests/knowledge/test_ontology_migration.py::test_restore_on_rollback | да (1 failed, 1 warning in 0.96s) |
| Откат миграции | rollback-no-restore | tests/knowledge/test_ontology_migration.py::test_rollback_invariant | да (1 failed, 1 warning in 2.72s) |
| Снятие мусорных сущностей | rollback-no-restored-event | tests/knowledge/test_ontology_migration.py::test_restore_on_rollback | да (1 failed, 1 warning in 1.03s) |
| Откат миграции | rollback-no-text | tests/knowledge/test_ontology_migration.py::test_name_form | да (1 failed, 1 warning in 1.23s) |
| Откат миграции | rollback-no-text | tests/knowledge/test_ontology_migration.py::test_rollback_invariant | да (1 failed, 1 warning in 2.80s) |
| Откат миграции | rollback-other-run-merges | tests/knowledge/test_ontology_migration.py::test_rollback_keeps_later_merge | да (1 failed, 1 warning in 3.51s) |
| Откат миграции | rollback-review-open | tests/knowledge/test_ontology_migration.py::test_rollback_closes_run_items | да (1 failed, 1 warning in 3.33s) |
| Миграция существующей онтологии | run-action-not-recorded | tests/knowledge/test_ontology_migration.py::test_dry_run | да (1 failed, 1 warning in 2.55s) |
| Миграция существующей онтологии | run-action-not-recorded | tests/knowledge/test_ontology_migration.py::test_loss_aborts | да (1 failed, 1 warning in 3.11s) |
| Миграция существующей онтологии | run-action-not-recorded | tests/knowledge/test_ontology_migration.py::test_migration_invariant | да (1 failed, 1 warning in 1.80s) |
| Миграция существующей онтологии | run-action-not-recorded | tests/knowledge/test_ontology_migration.py::test_name_form | да (1 failed, 1 warning in 0.95s) |
| Миграция существующей онтологии | same-name-includes-person | tests/knowledge/test_ontology_migration.py::test_same_name_queue_after_skips | да (1 failed, 1 warning in 0.76s) |
| Миграция существующей онтологии | same-name-not-queued | tests/knowledge/test_ontology_migration.py::test_rollback_closes_run_items | да (1 failed, 1 warning in 3.08s) |
| Миграция существующей онтологии | same-name-not-queued | tests/knowledge/test_ontology_migration.py::test_same_name_queue_after_skips | да (1 failed, 1 warning in 0.85s) |
| Снятие мусорных сущностей | same-name-stops-after-person | tests/knowledge/test_ontology_migration.py::test_rollback_closes_run_items | да (1 failed, 1 warning in 3.22s) |
| Снятие мусорных сущностей | same-name-stops-after-person | tests/knowledge/test_ontology_migration.py::test_same_name_queue_after_skips | да (1 failed, 1 warning in 0.79s) |
| Миграция существующей онтологии | step-dry-run-false | tests/knowledge/test_ontology_migration.py::test_step_event_dry_run | да (1 failed, 1 warning in 2.41s) |
| Замер качества онтологии | table-no-threshold | tests/knowledge/test_ontology_migration.py::test_thresholds_at_boundary | да (1 failed, 1 warning in 2.30s) |
| Перевод названий | translate-stops-after-failed-batch | tests/knowledge/test_ontology_migration.py::test_translation_invariant | да (1 failed, 1 warning in 6.26s) |
| Перевод названий | translated-extra-field | tests/knowledge/test_ontology_migration.py::test_batch_with_model_errors | да (1 failed, 1 warning in 0.78s) |
| Перевод названий | translated-extra-field | tests/knowledge/test_ontology_migration.py::test_estimate | да (1 failed, 1 warning in 1.75s) |
| Перевод названий | translated-extra-field | tests/knowledge/test_ontology_migration.py::test_reply_check_order_pairs | да (1 failed, 1 warning in 0.70s) |
| Перевод названий | translated-extra-field | tests/knowledge/test_ontology_migration.py::test_russian_stopword | да (1 failed, 1 warning in 0.70s) |
| Перевод названий | translated-extra-field | tests/knowledge/test_ontology_migration.py::test_stand_synthetic | да (1 failed, 1 warning in 2.63s) |
| Перевод названий | translated-extra-field | tests/knowledge/test_ontology_migration.py::test_translation_invariant | да (1 failed, 1 warning in 1.02s) |
| Миграция существующей онтологии | verify-no-step-event | tests/knowledge/test_ontology_migration.py::test_stand_synthetic | да (1 failed, 1 warning in 3.05s) |
| Перевод названий | wd-label-latin | tests/knowledge/test_ontology_migration.py::test_wikidata_labels_after_skips | да (1 failed, 1 warning in 0.70s) |
| Перевод названий | wd-label-unchecked | tests/knowledge/test_ontology_migration.py::test_wikidata_labels_after_skips | да (1 failed, 1 warning in 0.78s) |
| Перевод названий | wd-labels-stops-after-bad-label | tests/knowledge/test_ontology_migration.py::test_wikidata_labels_after_skips | да (1 failed, 1 warning in 0.77s) |
| Перевод названий | wd-labels-stops-after-fetch-error | tests/knowledge/test_ontology_migration.py::test_wikidata_labels_after_skips | да (1 failed, 1 warning in 0.72s) |

Отбор ожидаемых тестов: цепочка в отдельном worktree (патч → пул тестов требования, сигнатура падений сравнивается с чистым кодом; база — все пулы зелёные). 25 выживших в пулах закрыты тестами О29 или признаны эквивалентными (выше).

### Аудит пунктов (О21, О23, О24; убийцы — по прогону мутаций О29)

Обозначения: OM = `tests/knowledge/test_ontology_migration.py`; W = `tests/knowledge/migration_world.py` (генератор `ontologies`, оракулы `losses`, `verified_dropped`, `name_forms_broken`, `a1`–`a5`, `a4_pairs`; оракулы не импортируют `naming`, `dedupe`, `integrity`, `quality_report`); TR = стратегия `translation_replies` в OM. Явный пример инвариантов — `SYMPTOMS_SPEC` (П1–П4 + О24: NFD «Йоганн», NBSP у «Юм», пробелы у «Berkeley#1» и «causality»).

#### Миграция существующей онтологии

| Пункт | Вид генератора | @example / сценарий | Мутация |
|---|---|---|---|
| Шаг 1 `normalize_names`: текст → strip+NFC | W.ontologies `decorate` (NFD, пробелы/NBSP/EM SPACE по краям) | OM::test_name_form; SYMPTOMS_SPEC | normalize-skipped ← migration_invariant, name_form |
| Шаг 1: `normalized` пересчитывается правилом | W.old_form (устаревший ключ — нижний регистр сырого) | OM::test_name_form («Йоганн» находится запросом) | normalize-key-stale ← migration_invariant, name_form |
| Шаг 1 до слияния: « Кант » сливается с «Кант» | W.ontologies decorate у кластеров | OM::test_name_form (`merge:name`) | normalize-skipped ← migration_invariant, name_form |
| Шаг 2 `manifest_qids`: подтверждённые QID записываются | W.ontologies manifest accepted/auto | OM::test_stand_synthetic (Q6691, Q913) | confirmed-not-passed ← migration_invariant, stand_synthetic |
| Шаг 2: `qid_taken` с решением → `merge:qid_confirmed` | W.ontologies (Омир/Гомер accepted) | OM::test_stand_synthetic | confirmed-not-passed ← migration_invariant, stand_synthetic |
| Шаг 2: `pending` с держателем → очередь `review:qid_candidate` | W.ontologies (pending, holder) | OM::test_transliteration_pending | qid-candidate-reason ← transliteration_pending |
| Шаг 2: не ставить, если открытый пункт уже есть | W.ontologies (повторный run в инварианте отката) | OM::test_pending_candidate_after_open_pair (О29) | qid-candidate-requeued — эквивалентна: dedupe.propose сам не ставит открытую пару повторно |
| Шаг 3 `lang_fix`: язык по письменности | W.ontologies (латиница с `ru`: «causality» ru) | OM::test_stand_synthetic (варианты `en`) | lang-fix-skipped ← lang_fix_no_script, migration_invariant |
| Шаг 4 `retire`: мусор снимается | W.GARBAGE (number/empty/stopword/not_a_name/sentence) | OM::test_stand_synthetic (7 снятий) | retire-skips-person ← dry_run, migration_invariant, stand_synthetic |
| Шаг 4: кроме источников библиотеки | W.SOURCE_NAMES («3.1», латиница) | OM::test_source_not_retired (О29) | retire-source — эквивалентна: правило названий не проверяет источники |
| Шаг 5 `wikidata_labels` | W.LATIN_QID + wd | OM::test_wikidata_before_model; test_wikidata_labels_after_skips (О29) | wd-label-unchecked ← wikidata_labels_after_skips; wd-label-latin ← wikidata_labels_after_skips |
| Шаг 6 `translate` только по флагу | TR | OM::test_no_model_without_flag | model-without-flag ← no_model_without_flag, translation_invariant |
| Шаг 7 `dedupe` после переименований (Hume→Юм сливается) | W.LATIN_QID пары | OM::test_stand_synthetic | dedupe-before-rename ← migration_invariant, stand_synthetic, transliteration_pending |
| Шаг 7: не-персоны с общим названием → `review:same_name` | W.ontologies (понятия-двойники) | OM::test_same_name_queue_after_skips, test_rollback_closes_run_items (О29) | same-name-not-queued ← rollback_closes_run_items, same_name_queue_after_skips; same-name-includes-person ← same_name_queue_after_skips |
| Шаг 8 `verify` + аварийный откат | подмена шага (monkeypatch) | OM::test_loss_aborts | verify-no-abort ← loss_aborts |
| Порядок шагов = спецификация = `STEPS` = отчёт | — | OM::test_stand_synthetic (список SPEC_STEPS) | dedupe-before-rename ← migration_invariant, stand_synthetic, transliteration_pending |
| Каждое действие — в журнале действий | W.ontologies | OM::test_dry_run, test_migration_invariant (оракул 2) | run-action-not-recorded ← dry_run, loss_aborts, migration_invariant, name_form |
| Переименование не меняет идентификатор | W.LATIN_* | OM::test_stand_synthetic | rename-drops-old-primary ← stand_synthetic, translation_invariant |
| Утверждения/атрибуции не удаляются (кроме свёртки) | W.ontologies (атрибуции на дубль и мусор) | W.losses в инвариантах | verify-no-abort ← loss_aborts |
| `aborted` ровно `run_id, lost, lost_attributions, error_kind` | — | OM::test_loss_aborts (check_keys) | aborted-no-error-kind ← loss_aborts |
| Сухой прогон: без записи и без модели | W.ontologies | OM::test_dry_run, инвариант (оракул 1) | plan-writes-lang ← dry_run, migration_invariant |
| Сухой прогон: действия = run off без `names_before` | W.ontologies | инвариант (оракул 2) | plan-writes-lang ← dry_run, migration_invariant; run-action-not-recorded ← dry_run, loss_aborts, migration_invariant, name_form |
| Сухой прогон: числа отчёта = run (свёртки) | W кластеры | OM::test_dry_run, инвариант `folded` | plan-folds-zero ← dry_run, migration_invariant |
| `--limit N` — только перевод | — | OM::test_limit_only_translation (О29) | limit-ignored ← limit_only_translation |
| `step` ровно `run_id, step, actions, dry_run` | — | OM::test_dry_run; test_step_event_dry_run (О29: значение dry_run) | step-dry-run-false ← step_event_dry_run; verify-no-step-event ← stand_synthetic |
| Нет названий в событиях | маркер Zq7Marker; W.name_texts | OM::test_no_names_in_journal, инвариант | step-event-with-names ← dry_run, lang_fix_no_script, loss_aborts, migration_invariant, name_form, no_names_in_journal, stand_synthetic, transliteration_pending, verified_untouched |
| Инвариант: нет действующих с причиной | W.GARBAGE | инвариант `_expect_run` | retire-skips-person ← dry_run, migration_invariant, stand_synthetic |
| Инвариант О24: текст = strip+NFC, `normalized` = нормализация | W.decorate | инвариант `name_forms_broken` | normalize-skipped ← migration_invariant, name_form; normalize-key-stale ← migration_invariant, name_form |
| «Проверенное человеком не трогается» | W.ontologies `verified` | OM::test_verified_untouched; инвариант `verified_dropped` | Д2-mig исправлен в 1923675; мутация слияния merge-verified-folded (improve-person-quality) ← test_preservation_and_undo |

#### Снятие мусорных сущностей

| Пункт | Вид генератора | @example / сценарий | Мутация |
|---|---|---|---|
| Снятая не показывается (справочник, карта, карточки, граф, ассистент) | W.ontologies + произвольный набор мусора | OM::test_retire_invariant, test_section_number_retired | snapshot-shows-retired ← retire_invariant, section_number_retired |
| Карточка снятой — 404 | W.GARBAGE | OM::test_section_number_retired | snapshot-shows-retired ← retire_invariant, section_number_retired |
| Утверждение со снятым концом не показывается, строка остаётся | W.add_statement к мусору | OM::test_section_number_retired, test_assistant_does_not_see_retired | snapshot-keeps-retired-ends ← retire_invariant |
| Атрибуция со снятым автором не показывается | W «your Lordship» автор | OM::test_retire_invariant | snapshot-keeps-retired-ends ← retire_invariant |
| `retired` ровно `entity_id, type, reason, run_id` | — | OM::test_section_number_retired | retired-event-label ← assistant_does_not_see_retired, restore_on_rollback, retire_invariant, section_number_retired, stand_synthetic |
| `restored` ровно `entity_id, run_id` | — | OM::test_restore_on_rollback | rollback-no-restored-event ← restore_on_rollback |
| Возврат при откате | — | OM::test_restore_on_rollback | rollback-no-restore ← full_rollback, restore_on_rollback, rollback_invariant |

#### Перевод названий

| Пункт | Вид генератора | @example / сценарий | Мутация |
|---|---|---|---|
| Порядок: подпись Wikidata раньше модели | W.LATIN_QID | OM::test_wikidata_before_model | dedupe-before-rename ← migration_invariant, stand_synthetic, transliteration_pending; wd-label-unchecked ← wikidata_labels_after_skips |
| Русское = кириллица и нет латиницы вне римских | TR (латиница, смешанные) | OM::test_batch_with_model_errors («Substanz») | accept-latin ← batch_with_model_errors, reply_check_order_pairs, translation_invariant |
| Пакеты ≤ размера, номера с 1, без id | TR (размер пакета 1–3) | OM::test_estimate (batches=3), test_translation_invariant | batch-ignored ← translation_invariant; pack-n-from-zero ← batch_with_model_errors, russian_stopword, stand_synthetic, translation_invariant; pack-with-ids ← batch_with_model_errors |
| 1 `unknown_item` | TR (чужие номера) | OM::test_batch_with_model_errors (n=7) | pack-n-from-zero ← batch_with_model_errors, russian_stopword, stand_synthetic, translation_invariant |
| 2 `duplicate_item`: отклоняются все с номером | TR (повторы) | OM::test_batch_with_model_errors (n=2 ×2) | duplicate-rejects-second-only ← batch_with_model_errors, reply_check_order_pairs, translation_invariant |
| Порядок 2 раньше 3 | TR (повтор с латиницей) | OM::test_batch_with_model_errors (Substanz + Субстанция) | not-russian-before-duplicate ← batch_with_model_errors, reply_check_order_pairs |
| 3 `not_russian` | TR | OM::test_batch_with_model_errors («some») | accept-latin ← batch_with_model_errors, reply_check_order_pairs, translation_invariant |
| 4 `invalid:<причина>` | TR (стоп-слова) | OM::test_russian_stopword (противоречие спецификации, см. ниже) | invalid-unchecked ← russian_stopword, translation_invariant |
| `missing` | TR (пропуски) | OM::test_batch_with_model_errors (4 «mind») | missing-not-counted ← batch_with_model_errors, reply_check_order_pairs, translation_invariant |
| Сбой шлюза пропускает пакет | TR (сбои) | OM::test_translation_invariant | gateway-failure-raises ← translation_invariant |
| Запись: основное `ru`, прежнее — вариант | TR | OM::test_stand_synthetic (варианты `en` прежние) | rename-drops-old-primary ← stand_synthetic, translation_invariant |
| `plan --estimate`: проба × пакеты | — | OM::test_estimate | estimate-no-multiply ← estimate |
| `translated` ровно `run_id, batch, accepted, rejected` | — | OM::test_batch_with_model_errors | translated-extra-field ← batch_with_model_errors, estimate, reply_check_order_pairs, russian_stopword, stand_synthetic, translation_invariant |
| Инвариант: без флага модель не вызывается | TR | OM::test_translation_invariant | model-without-flag ← no_model_without_flag, translation_invariant |

#### Откат миграции

| Пункт | Вид генератора | @example / сценарий | Мутация |
|---|---|---|---|
| Отмена слияний запуска (свёртки, QID удалённых) | W кластеры | OM::test_full_rollback (merges_undone=4) | rollback-no-undo-merge ← full_rollback, name_form, rollback_invariant |
| Отмена слияний только этого запуска | W (повторный run) | OM::test_rollback_keeps_later_merge (О29) | rollback-other-run-merges ← rollback_keeps_later_merge |
| Отмена `manifest_qids` (QID, утверждения команды QID) | W manifest | OM::test_full_rollback | rollback-no-manifest ← rollback_invariant, rollback_keeps_verified_qid |
| Проверенное и его QID остаются (`kept`) | — | OM::test_rollback_keeps_verified_qid | rollback-no-manifest ← rollback_invariant, rollback_keeps_verified_qid |
| Восстановление названий | W.LATIN_* | OM::test_full_rollback | rename-drops-old-primary ← stand_synthetic, translation_invariant |
| Восстановление текста `normalize_names` | W.decorate | OM::test_name_form, test_rollback_invariant | rollback-no-text ← name_form, rollback_invariant |
| Возврат снятых | W.GARBAGE | OM::test_full_rollback (restored=7) | rollback-no-restore ← full_rollback, restore_on_rollback, rollback_invariant |
| Возврат языков | W (lang ru у латиницы) | OM::test_full_rollback | rollback-no-lang ← full_rollback, name_form, rollback_invariant |
| Пункты очереди → `rolled_back` | W manifest pending | OM::test_rollback_closes_run_items (О29; в test_full_rollback проверка по `run_id` пунктов пуста — у пунктов нет `run_id`) | rollback-review-open ← rollback_closes_run_items |
| Последующее переименование сохраняется, `kept` | — | OM::test_later_change_kept | rollback-overwrites-later ← later_change_kept; rollback-kept-ignored ← later_change_kept |
| `rolled_back` ровно 5 полей | — | OM check_keys | rollback-kept-ignored ← later_change_kept |
| Инвариант: дамп = до run | W.ontologies, все решения манифеста | OM::test_rollback_invariant | rollback-no-undo-merge ← full_rollback, name_form, rollback_invariant; rollback-no-text ← name_form, rollback_invariant |

#### Замер качества онтологии

| Пункт | Вид генератора | @example / сценарий | Мутация |
|---|---|---|---|
| А1 доля русских, кроме источников | W.ontologies + SOURCE_NAMES | OM::test_quality_invariant, test_quality_before_after | a1-with-source ← quality_invariant |
| А1 порог ≥ 0,90 (граница) | W | OM::test_thresholds_at_boundary (О29: А1 = 27/30) | a1-threshold-gt ← thresholds_at_boundary |
| А2 только `number`, кроме источников | W.GARBAGE, SOURCE «3.1» | OM::test_quality_before_after (А2=1) | a2-any-reason ← quality_before_after, quality_invariant; a2-with-source — эквивалентна: правило названий не проверяет источники (entity-naming) |
| А3 правило для персоны | W.GARBAGE (персоны) | OM::test_quality_before_after (А3=4) | a3-concept-rule ← quality_before_after, quality_invariant |
| А4 объединение, один раз | W кластеры + очередь | OM::test_a4_union_and_distinct | a4-sum ← a4_union_and_distinct; a4-no-queue ← quality_invariant, transliteration_pending |
| А4 минус «разные» | — | OM::test_a4_union_and_distinct | a4-counts-distinct ← a4_union_and_distinct |
| А4 основное ↔ любое название | — | OM::test_a4_primary_in_variants | a4-primary-only ← a4_primary_in_variants, a4_union_and_distinct |
| А4 только персоны (`review:same_name` не входит) | W понятия-двойники | OM::test_a4_ignores_non_person_items (О29) | a4-non-persons ← a4_ignores_non_person_items |
| А5 персоны с основной датой, порог ≥ 20 | W `dates` | OM::test_thresholds_at_boundary (О29: ровно 20, датированное произведение) | a5-all-types ← thresholds_at_boundary; a5-threshold-gt ← thresholds_at_boundary |
| А6 `people` с `philosopher`, порог ≥ 10 | — | OM::test_a6_a7_match_api; test_thresholds_at_boundary (О29: ровно 10) | a6-no-filter ← a6_a7_match_api, quality_invariant; a6-threshold-gt ← thresholds_at_boundary |
| А7 справочник, все страницы, правило своего типа | W | OM::test_a6_a7_match_api; test_a7_all_pages (О29: 61 негодная > страницы 60) | a7-concept-rule ← quality_invariant; a7-first-page ← a7_all_pages |
| А8 без базы — «не измерено» | — | OM::test_without_baseline | a8-zero-without-baseline ← without_baseline |
| А8 утверждения + атрибуции | подмена (потерянная атрибуция) | OM::test_a8_counts_lost_attribution (О29) | a8-statements-only ← a8_counts_lost_attribution |
| Только чтение | — | OM::test_read_only | quality-writable ← read_only |
| Старая схема | — | OM::test_old_schema | — (ветка кода без мутации: проверка номера схемы) |
| Код выхода 0/1/2 | — | OM::test_without_baseline, test_quality_invariant | exit-always-zero ← quality_before_after, quality_invariant, transliteration_pending, without_baseline |
| `measured` ровно a1…a8, passed, failed | — | OM check_keys | measured-extra-field ← a4_primary_in_variants, a4_union_and_distinct, a6_a7_match_api, acceptance_symptoms, old_schema, quality_before_after, quality_invariant, read_only, transliteration_pending, without_baseline |
| Таблица из восьми строк с порогами | — | OM::test_thresholds_at_boundary (О29: 4 столбца, пороги) | table-no-threshold ← thresholds_at_boundary |


### О30, `--id` (тесты на коммите с С3/С4)

| Требование | Мутация | Ожидаемый тест | Упал |
|---|---|---|---|
| Миграция существующей онтологии | same-name-includes-source | tests/knowledge/test_ontology_migration.py::test_same_name_sources_not_queued | да (1 failed, 1 warning in 0.86s) |
| Миграция существующей онтологии | manifest-candidate-ignores-distinct | tests/knowledge/test_ontology_migration.py::test_pending_candidate_distinct_not_queued | да (1 failed, 1 warning in 3.48s) |

Итого мутаций 83, `--coverage` — чисто.

## Тестировщик — О31/О32, 2026-11-26, код 0b8b44e, спецификация fbb03ad, cf3d9a1

- Новые тесты:
  - О31: `test_rollback_keeps_later_added_name` (add_name человека), `test_rollback_keeps_name_from_later_merge` (слияние другого запуска), `test_negative_limit_rejected[plan|run]`, `test_rollback_unknown_run`;
  - property `test_rollback_keeps_arbitrary_later_names` (heavy): поздние названия у произвольных сущностей после запуска остаются, `kept` ≥ числа переименованных с поздними названиями, сущности без поздних правок откатываются полностью;
  - О32: `test_failure_mid_run`. Второе слияние бросает исключение. Проверяется: `knowledge.migration.failed` ровно с `run_id, dry_run, error, error_kind`, `error_kind=exception`; маркера в событии нет; в stderr есть `run_id` и `rollback <run_id>`; код 1; откат по этому `run_id` возвращает дамп.
- До 0b8b44e тесты О31 были красными (0511502), на 0b8b44e — 7 passed in 41.09s. `test_failure_mid_run` — 1 passed.
- `test_later_change_kept` усилен: после повторного переименования откат не трогает тексты и виды названий. Язык `lang_fix` откатывается отдельным действием.
- Патчи после 0b8b44e:
  - сняты заново: `normalize-key-stale`, `retired-event-label`, `verify-no-abort`, `verify-no-step-event`, `rollback-no-undo-merge`, `rollback-other-run-merges`;
  - `run-action-not-recorded` переписан: запись идёт через `record_in` в 4 местах;
  - `rollback-overwrites-later` переписан: теперь он снимает обе проверки повторного переименования, а снятая по отдельности каждая из них эквивалентна.
- Новые мутации: `rollback-deletes-later-names`, `rollback-later-not-kept`, `unknown-run-silent`, `negative-limit-accepted`, `failed-event-missing`, `failed-no-run-id-in-stderr`. Всего мутаций 89, `--coverage`: migrate-ontology-quality: мутации есть у всех 5 требований. Все патчи накладываются на HEAD.

| Требование | Мутация | Ожидаемый тест | Упал |
|---|---|---|---|
| Миграция существующей онтологии | normalize-key-stale | tests/knowledge/test_ontology_migration.py::test_migration_invariant | да (1 failed, 1 warning in 2.55s) |
| Миграция существующей онтологии | normalize-key-stale | tests/knowledge/test_ontology_migration.py::test_name_form | да (1 failed, 1 warning in 0.95s) |
| Снятие мусорных сущностей | retired-event-label | tests/knowledge/test_ontology_migration.py::test_assistant_does_not_see_retired | да (1 failed, 1 warning in 0.81s) |
| Снятие мусорных сущностей | retired-event-label | tests/knowledge/test_ontology_migration.py::test_restore_on_rollback | да (1 failed, 1 warning in 0.80s) |
| Снятие мусорных сущностей | retired-event-label | tests/knowledge/test_ontology_migration.py::test_retire_invariant | да (1 failed, 1 warning in 14.15s) |
| Снятие мусорных сущностей | retired-event-label | tests/knowledge/test_ontology_migration.py::test_section_number_retired | да (1 failed, 1 warning in 0.85s) |
| Снятие мусорных сущностей | retired-event-label | tests/knowledge/test_ontology_migration.py::test_stand_synthetic | да (1 failed, 1 warning in 2.36s) |
| Откат миграции | rollback-no-undo-merge | tests/knowledge/test_ontology_migration.py::test_full_rollback | да (1 failed, 1 warning in 3.01s) |
| Откат миграции | rollback-no-undo-merge | tests/knowledge/test_ontology_migration.py::test_name_form | да (1 failed, 1 warning in 0.98s) |
| Откат миграции | rollback-no-undo-merge | tests/knowledge/test_ontology_migration.py::test_rollback_invariant | да (1 failed, 1 warning in 1.98s) |
| Откат миграции | rollback-other-run-merges | tests/knowledge/test_ontology_migration.py::test_rollback_keeps_later_merge | да (1 failed, 1 warning in 2.85s) |
| Миграция существующей онтологии | verify-no-abort | tests/knowledge/test_ontology_migration.py::test_loss_aborts | да (1 failed, 1 warning in 2.80s) |
| Миграция существующей онтологии | verify-no-step-event | tests/knowledge/test_ontology_migration.py::test_stand_synthetic | да (1 failed, 1 warning in 3.08s) |
| Откат миграции | rollback-deletes-later-names | tests/knowledge/test_ontology_migration.py::test_rollback_keeps_later_added_name | да (1 failed, 1 warning in 0.77s) |
| Откат миграции | rollback-deletes-later-names | tests/knowledge/test_ontology_migration.py::test_rollback_keeps_name_from_later_merge | да (1 failed, 1 warning in 0.73s) |
| Откат миграции | rollback-deletes-later-names | tests/knowledge/test_ontology_migration.py::test_rollback_keeps_arbitrary_later_names | да (1 failed, 1 warning in 2.35s) |
| Откат миграции | rollback-later-not-kept | tests/knowledge/test_ontology_migration.py::test_rollback_keeps_later_added_name | да (1 failed, 1 warning in 0.72s) |
| Откат миграции | rollback-later-not-kept | tests/knowledge/test_ontology_migration.py::test_rollback_keeps_name_from_later_merge | да (1 failed, 1 warning in 0.79s) |
| Откат миграции | unknown-run-silent | tests/knowledge/test_ontology_migration.py::test_rollback_unknown_run | да (1 failed, 1 warning in 2.28s) |
| Миграция существующей онтологии | negative-limit-accepted | tests/knowledge/test_ontology_migration.py::test_negative_limit_rejected | да (1 failed, 1 warning in 2.31s) |
| Миграция существующей онтологии | failed-event-missing | tests/knowledge/test_ontology_migration.py::test_failure_mid_run | да (1 failed, 1 warning in 2.61s) |
| Миграция существующей онтологии | failed-no-run-id-in-stderr | tests/knowledge/test_ontology_migration.py::test_failure_mid_run | да (1 failed, 1 warning in 2.50s) |
| Миграция существующей онтологии | run-action-not-recorded | tests/knowledge/test_ontology_migration.py::test_dry_run | да (1 failed, 1 warning in 2.67s) |
| Миграция существующей онтологии | run-action-not-recorded | tests/knowledge/test_ontology_migration.py::test_loss_aborts | да (1 failed, 1 warning in 2.99s) |
| Миграция существующей онтологии | run-action-not-recorded | tests/knowledge/test_ontology_migration.py::test_migration_invariant | да (1 failed, 1 warning in 1.81s) |
| Миграция существующей онтологии | run-action-not-recorded | tests/knowledge/test_ontology_migration.py::test_name_form | да (1 failed, 1 warning in 0.91s) |
| Откат миграции | rollback-overwrites-later | tests/knowledge/test_ontology_migration.py::test_later_change_kept | да (1 failed, 1 warning in 0.79s) |

Первые прогоны до правки, «НЕТ»: `rollback-overwrites-later` (снята одна проверка из двух — эквивалентно), `run-action-not-recorded` по `_record` (после 0b8b44e — только слияния).

## Тестировщик — J8 и повторное ревью (тот же ключ), 2026-11-26, тесты 59d9456 и следующий, код 40bae79

Тесты:
- `test_translation_invariant`: генератор `translation_replies` даёт элементы всех типов `entity_types()`, кроме `source`, и вид ответа `lowercase` («слепой математик»). Оракул: у персоны `invalid:not_a_name`, у остальных принят; ответ из 8 слов — `sentence` у понятия, но принят у `work`, `event`, `idea_event`, `phenomenon` (предел 12). Добавлены `@example` J8 (персона и понятие, оба «слепой математик») и пример предела (произведение и понятие, оба 8 слов).
- `test_reply_checked_by_item_type`: персона «Saunderson» и понятие «blind mathematics», ответ «слепой математик» → персона без изменений, понятие переименовано, `untranslated["invalid:not_a_name"] == 1`.
- `test_wikidata_label_checked_by_type`: подпись Wikidata «слепой математик» у персоны (Q900011) не применяется, у понятия (Q900012) применяется.
- `test_rollback_keeps_same_key_rename[yo|case]`: модель дала «Объем» или «Причинность», человек поставил «Объём» или «ПРИЧИННОСТЬ» → после отката название человека основное, `rolled_back.kept == 1`. На 40bae79 — зелёный.
- `test_rollback_keeps_arbitrary_later_names` расширен: у части переименованных запуском сущностей позднее название — тот же ключ, другой текст (`upper()`). Ожидание: оно остаётся основным, сущность в `kept`.

Обход вызовов правил, зависящих от типа (вызов заменён на `"concept"`; прогон файлов теста до новых тестов → после):

| Место | Мутация | До новых тестов | После |
|---|---|---|---|
| `ontology_migrate.py` перевод, ответ модели | `j8-reply-check-as-concept` | выжила (J8 судьи) | убита |
| `ontology_migrate.py` подписи Wikidata | `wd-label-check-as-concept` | убита новым тестом | убита |
| `ontology_migrate.py` снятие | `retire-check-as-concept` | убита (`test_acceptance_symptoms`, `test_dry_run`, `test_full_rollback`) | убита |
| `quality_report.py` A2 | `a2-check-as-concept` | выжила | эквивалентна: правило `number` одинаково для всех типов, кроме `source`, а источники из выборки A2 исключены. В yaml не вошла |
| `naming.py` `invalid_primary` | `invalid-primary-as-concept` (naming) | выжила | убита `test_event_label_checked_by_event_rule` |
| `epoch_context.py` вызов `invalid_primary` | `epoch-context-primary-as-concept` (naming) | выжила | убита |
| `naming.py` `names_for`, проверка ru | `names-for-ru-as-concept` (naming) | выжила | убита |
| `naming.py` `names_for`, варианты | `names-for-variant-as-concept` (naming) | выжила | убита |
| `entity_items.py` вызов `names_for` | `items-names-for-as-concept` (naming) | выжила | убита |
| `entity_items.py` `_russian_primary` | `items-russian-primary-as-concept` (naming) | убита | убита |
| `entities.py` `_check` | `entities-check-as-concept` (naming) | убита | убита |

Строка аудита («Перевод названий»): п. 4 «`invalid:<причина>` по правилу типа элемента». Генератор — все типы, кроме `source`; виды ответа `lowercase` и `sentence` расходятся по типам. Примеры — J8 и предел слов. Сценарий — `test_reply_checked_by_item_type`. Мутация — `j8-reply-check-as-concept`.

Строка аудита («Откат миграции»): «название человека после запуска остаётся, даже с тем же ключом». Генератор — поздние названия `upper()` у переименованных. Сценарий — `test_rollback_keeps_same_key_rename`. Мутация — `rollback-own-name-key-only` (`_own_name` без сравнения текста).

Патчи после 40bae79 сняты заново:
- migrate: `failed-event-missing`, `failed-no-run-id-in-stderr`, `rename-drops-old-primary`, `rollback-overwrites-later` (теперь снимает фильтр kind в `_own_name` и проверку `ours["kind"]`), `run-action-not-recorded` (4 вызова `record_in` и `_record`), `verify-no-abort`;
- naming: `renamed-extra-field`, `renamed-previous-lang-wrong`, `rename-keeps-old-primary`, `set-primary-unchecked`, `stored-raw-set-primary`.

`git apply --check` на HEAD для всех `tests/mutations/*/*.patch` — 0 ненакладывающихся. `--coverage` по обоим изменениям чистый.

`--id` (под flock), строки migrate:

| Требование | Мутация | Тест | Убита |
|---|---|---|---|
| Перевод названий | j8-reply-check-as-concept | tests/knowledge/test_ontology_migration.py::test_reply_checked_by_item_type | да (1 failed, 1 warning in 0.81s) |
| Перевод названий | j8-reply-check-as-concept | tests/knowledge/test_ontology_migration.py::test_translation_invariant | да (1 failed, 1 warning in 1.15s) |
| Перевод названий | wd-label-check-as-concept | tests/knowledge/test_ontology_migration.py::test_wikidata_label_checked_by_type | да (1 failed, 1 warning in 0.77s) |
| Снятие мусорных сущностей | retire-check-as-concept | tests/knowledge/test_ontology_migration.py::test_acceptance_symptoms | да (1 failed, 1 warning in 3.97s) |
| Снятие мусорных сущностей | retire-check-as-concept | tests/knowledge/test_ontology_migration.py::test_dry_run | да (1 failed, 1 warning in 3.54s) |
| Снятие мусорных сущностей | retire-check-as-concept | tests/knowledge/test_ontology_migration.py::test_full_rollback | да (1 failed, 1 warning in 3.74s) |
| Откат миграции | rollback-own-name-key-only | tests/knowledge/test_ontology_migration.py::test_rollback_keeps_same_key_rename | да (1 failed, 1 warning in 0.80s) |
| Откат миграции | rollback-own-name-key-only | tests/knowledge/test_ontology_migration.py::test_rollback_keeps_arbitrary_later_names | да (1 failed, 1 warning in 2.33s) |
| Миграция существующей онтологии | failed-event-missing | tests/knowledge/test_ontology_migration.py::test_failure_mid_run | да (1 failed, 1 warning in 3.02s) |
| Миграция существующей онтологии | failed-no-run-id-in-stderr | tests/knowledge/test_ontology_migration.py::test_failure_mid_run | да (1 failed, 1 warning in 3.23s) |
| Перевод названий | rename-drops-old-primary | tests/knowledge/test_ontology_migration.py::test_stand_synthetic | да (1 failed, 1 warning in 3.42s) |
| Перевод названий | rename-drops-old-primary | tests/knowledge/test_ontology_migration.py::test_translation_invariant | да (1 failed, 1 warning in 1.37s) |
| Откат миграции | rollback-overwrites-later | tests/knowledge/test_ontology_migration.py::test_later_change_kept | да (1 failed, 1 warning in 0.84s) |
| Миграция существующей онтологии | run-action-not-recorded | tests/knowledge/test_ontology_migration.py::test_dry_run | да (1 failed, 1 warning in 2.80s) |
| Миграция существующей онтологии | run-action-not-recorded | tests/knowledge/test_ontology_migration.py::test_loss_aborts | да (1 failed, 1 warning in 3.46s) |
| Миграция существующей онтологии | run-action-not-recorded | tests/knowledge/test_ontology_migration.py::test_migration_invariant | да (1 failed, 1 warning in 1.90s) |
| Миграция существующей онтологии | run-action-not-recorded | tests/knowledge/test_ontology_migration.py::test_name_form | да (1 failed, 1 warning in 1.13s) |
| Миграция существующей онтологии | verify-no-abort | tests/knowledge/test_ontology_migration.py::test_loss_aborts | да (1 failed, 1 warning in 2.83s) |

## Судья — 2026-11-26, коммит 745dbe0

Машина: 1 ГБ ОЗУ, без Docker. Полный `pytest` и e2e не запускались. Мутации шли в отдельном worktree (`PYTHONPATH` на его `src`), рабочая копия не менялась.

| Требование | Сценарий / инвариант | Журнал тестировщика | Мой прогон | Вывод системы | Итог |
|---|---|---|---|---|---|
| Миграция | все сценарии + test_migration_invariant | passed, 24+ мутаций убиты | 61 passed in 247 s (весь test_ontology_migration.py); J2 «verify без отката» → test_loss_aborts упал; J5 «normalize без NFC» → test_name_form упал; verify-no-abort (yaml) упал | CLI на синтетическом стенде (файл SQLite): `plan` — дамп не изменился, 7 снятий по причинам, 4 слияния, `lost=0`; `run --translate model` (фейк, 1 вызов) — код 0, `a1 0.7292→0.973` | подтверждено |
| Снятие | сценарии + test_retire_invariant | passed | J1 «`Entities.find` отдаёт снятых» → retire_invariant; J6 «`Statements.about` без фильтра объекта» → section_number_retired; J7 «без фильтра атрибуций со снятым автором» → retire_invariant | `rollback`: `restored=7` | подтверждено |
| Перевод | сценарии + test_translation_invariant | passed | **J8 выжила**: `check_name("concept", ru)` вместо типа элемента — 61 passed | `renamed.model=2`, `missing=3` | **не подтверждено** |
| Откат | сценарии + test_rollback_invariant, test_rollback_keeps_arbitrary_later_names | passed | passed | `rollback` через CLI — дамп данных равен дампу до `run`, `merges_undone=4`; неизвестный `run_id` — код 2 | подтверждено |
| Замер | сценарии + test_quality_invariant | passed | J4 «название = первое название, а не по определению» → test_quality_before_after; quality-writable (yaml) → test_read_only упал. Моя J3 (без `mode=ro` только у основного файла) выжила, но она эквивалентна: таблицы знаний в присоединённом файле `?mode=ro` | `quality_report` подпроцессом: до — код 1 (А2=1, А3=4, А4=3, А7=7, А8 «не измерено»); после `--baseline` — код 0: А1=0.973, А2=А3=А4=А7=0, А5=24, А6=12, А8=0; md5 файлов базы не изменились | подтверждено |

Приёмка владельца А1–А8 на синтетических данных показана (test_acceptance_symptoms, test_quality_before_after и мой прогон CLI выше). Замер запускается командой `python -m philograph.knowledge.quality_report` с `PHILOGRAPH_DATABASE_URL`, на стенде Lead'а его можно запустить так же. А9: `lint-imports` — 3 kept; трассировка — 415 из 415. `ruff check` (E501 в `scripts/dev_stack.py:100`) и `ruff format --check` (2 файла) падают. Эти файлы — Lead'а, они пришли из базы `claude/embedding-docker`: дифф ветки с базой по `dev_stack.py` и `queue.py` пуст. От изменения это не зависит, нужен пункт для Lead в PR.

Полный pytest: не запускался (ограничение машины). Прослеживаемость: чисто.
Мутации: свои J1–J8 и повтор verify-no-abort и quality-writable. J8 выжила.
Подгонка: не найдена. `skip`/`xfail` не добавлены, в прежних тестах изменён только номер схемы.
Пункт 4.1 (ревьювер) не отмечен: повторного ревью кода 0b8b44e, которым закрыто блокирующее замечание, нет.

Вердикт: **не принято**.
- Вернуть тестировщику: «Перевод названий → Проверка ответа, п. 4 `invalid:<причина>` по правилу **для типа элемента**» не доказан. `translation_replies` порождает только понятия. Нужен property или сценарий с персонами, где ответ проходит правило понятия, но не правило персоны (например, «слепой математик»: для персоны `not_a_name`, для понятия причины нет). Мутацию J8 (`check_name("concept", ru)`) добавить в `mutations.yaml`.
- Вернуть ревьюверу: ревью 0b8b44e и cf3d9a1, пункт 4.1.
