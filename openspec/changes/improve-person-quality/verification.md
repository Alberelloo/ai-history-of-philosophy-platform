# Verification

## Тестировщик — 2026-11-25, тесты на коммите 3aa55a9 и следующем (ветка claude/ontology-extraction)

Тесты написаны от дельт `specs/person-quality`, `specs/ontology-entities` и design.md; продуктовый код читался только для точек входа (сигнатуры) и, после коммита тестов, для патчей мутаций. Инфраструктура общая с `improve-extraction-naming` 3.1 (профили `ci`/`pure`/`heavy`, `dump.py`, стенд извлечения, запрет сети, `mutation_check.py`).

Стратегии (3.1, `tests/knowledge/strategies.py`, без импорта `dedupe`/`naming`):
- `not_persons` — отклоняемые предложения персон с ожидаемой причиной (строчные описания, «the … of …», склейки → `not_a_name`; обращения и группы с заглавной → `stopword`; длинные → `sentence`; стоп-слово длиннее предела персоны → `sentence` по порядку правил);
- `persons_with_variants` — «лица» и ожидаемый итог: `plain` (1–4 записи, общее основное, QID у одной или нет, даты равные / в допуске ±2 (сдвиг 0–4) / у одной стороны), `two_qids` (транзитивная через запись без QID), `dates` (сдвиг ≥ 5 → `review:dates`), `qids_distinct`, `confirmed` (ru/en без общего написания + подтверждение), `decided`, `decided3`, `variant_single`, `variant_multi`; ожидаемая оставшаяся — `expected_kept` (QID, затем ссылки, затем меньший id);
- `ontology_with_duplicates` — 5–30 сущностей, пара K/R, повторы K/R (в том числе с той же атрибуцией), петли R→K, атрибуции на R, подтверждения, упоминания, портреты с общим признаком, QID у одной стороны;
- `ontology_names` + `expected_candidates` — сущности разных типов с названиями из малого пула.

Явные `@example`: «Hume»(Q1)/«Hume»/«Hume»(Q2) (`TRANSITIVE`), даты на границе допуска (сдвиг 4 → слияние, 5 → `review:dates`, `BOUNDARY_DATES`), точный повтор атрибуции и QID у удалённой (`EXACT_REPEAT`), «Фрэнсис Бэкон»/«Бэкон»/произведение «Бэкон», регистр «Berkeley»/«berkeley»; разные QID «Бэкон» и петля — в сценариях.

### Требование → тесты → мутация

| Требование | Сценарные | Property / нормативные | Мутация | Упал |
|---|---|---|---|---|
| person-quality «Качество персон» | test_person_quality.py: test_garbage_person, test_glued, test_person_definition_in_prompt | test_person_rule_any_input (pure 400), test_person_quality_invariant (ci, через извлечение + 9 @example) | person-not-a-name, prompt-no-person-def | да ×4 |
| person-quality «Слияние вариантов персоны» | test_variants_merge_by_model_pair, test_common_primary_name, test_qid_confirmed_for_other, test_transliteration_with_decision, test_transliteration_pending, test_decided_apart_and_third, test_namesakes, test_different_qids, test_transitive_component_two_qids (3 порядка), test_conflicting_dates, test_dates_on_one_side, test_only_variant_matched | test_plan_partition_any_order (pure 400, две перестановки), test_merge_invariant_two_orders (heavy, через базу, две перестановки) | component-qids-unchecked, dates-unchecked, variant-merges, kept-input-order, qid-confirmed-ignored, single-word-primary-review, decided-ignored, decided-as-qid-cluster, single-word-variant | да ×23 |
| ontology-entities «Поиск дублей» (MODIFIED) | test_entity_merge.py: test_candidates, test_primary_on_different_records, test_different_types | test_candidates_invariant (ci) | candidates-primary-only, candidates-no-type | да ×4 |
| ontology-entities «Слияние с перенаправлением» (MODIFIED) | test_old_link, test_undo, test_repeat_folds, test_author_attribution_moves, test_loop, test_undo_with_fold_and_qid | test_preservation_and_undo (heavy: содержание без петель, атрибуции, подтверждения, одно основное, внешние, упоминания, портреты; отмена ⇒ `dump` равен исходному) | kept-primary-stays, author-attribution-stays, key-not-recomputed, undo-without-externals, loop-shown | да ×10 |

Вывод в тестах: база (сущности, перенаправления `resolve`, названия и их вид, внешние, утверждения через `get` по старым id, упоминания, портреты), `GET /v1/entities/{id}` и `/card` по старому id, `/v1/entities/{id}/statements`, карта (`SectionMap`), очередь `duplicate` (`Review.queue`), перехваченный запрос к шлюзу (`ontology.extract`, системный текст). События — точное множество ключей (`merged`: kept, removed, reason, statements, attributions, folded, loops; `merge_undone`: kept, removed, restored; `rejected`: type, label, reason) без полей контекста. Сторожевой токен — в тестах извлечения (`no_token`).

Выдержки событий (сырые, id сокращены):

    knowledge.entity.rejected {'run_id': 'fill_…', 'type': 'person', 'label': 'children', 'reason': 'not_a_name'}
    knowledge.extraction.dropped {'run_id': 'fill_…', 'reason': 'название «children» (person) отклонено: not_a_name'}
    knowledge.entity.merged {'run_id': 'fill_…', 'kept': 'e_…', 'removed': 'e_…', 'reason': 'merge:model_pair', 'statements': 1, 'attributions': 0, 'folded': 0, 'loops': 0}
    knowledge.entity.merge_proposed {'kept': 'e_…', 'removed': 'e_…', 'reason': 'review:decided_conflict'}
    knowledge.life_dates.skipped {'entity': 'e_…', 'property': 'wikidata', 'reason': 'qid_taken'}
    knowledge.entity.merged {'kept': 'e_…', 'removed': 'e_…', 'reason': 'merge:qid_confirmed', 'statements': 1, 'attributions': 0, 'folded': 0, 'loops': 0}
    knowledge.entity.merge_undone {'kept': 'e_…', 'removed': 'e_…', 'restored': 1}
    knowledge.entity.merged {'kept': 'e_…', 'removed': 'e_…', 'reason': 'merge:review', 'statements': 1, 'attributions': 0, 'folded': 0, 'loops': 1}

### Сырые итоги (по одному файлу, SQLite, 1 ГБ RAM)

RUNS

### Мутации (`scripts/mutation_check.py --change improve-person-quality`, отдельный worktree на 3aa55a9)

| Требование | Мутация | Ожидаемый тест | Упал |
|---|---|---|---|
| Качество персон | person-not-a-name | tests/knowledge/test_person_quality.py::test_garbage_person | да (1 failed, 1 warning in 5.96s) |
| Качество персон | person-not-a-name | tests/knowledge/test_person_quality.py::test_glued | да (1 failed, 1 warning in 5.33s) |
| Качество персон | person-not-a-name | tests/knowledge/test_person_quality.py::test_person_quality_invariant | да (1 failed, 1 warning in 16.80s) |
| Качество персон | prompt-no-person-def | tests/knowledge/test_person_quality.py::test_person_definition_in_prompt | да (1 failed, 1 warning in 3.47s) |
| Слияние вариантов персоны | component-qids-unchecked | tests/knowledge/test_person_quality.py::test_transitive_component_two_qids | да (1 failed, 1 warning in 3.35s) |
| Слияние вариантов персоны | component-qids-unchecked | tests/knowledge/test_person_quality.py::test_plan_partition_any_order | да (1 failed, 1 warning in 4.58s) |
| Слияние вариантов персоны | component-qids-unchecked | tests/knowledge/test_person_quality.py::test_merge_invariant_two_orders | да (1 failed, 1 warning in 11.13s) |
| Слияние вариантов персоны | dates-unchecked | tests/knowledge/test_person_quality.py::test_conflicting_dates | да (1 failed, 1 warning in 5.68s) |
| Слияние вариантов персоны | dates-unchecked | tests/knowledge/test_person_quality.py::test_plan_partition_any_order | да (1 failed, 1 warning in 4.50s) |
| Слияние вариантов персоны | dates-unchecked | tests/knowledge/test_person_quality.py::test_merge_invariant_two_orders | да (1 failed, 1 warning in 8.83s) |
| Слияние вариантов персоны | variant-merges | tests/knowledge/test_person_quality.py::test_only_variant_matched | да (1 failed, 1 warning in 1.81s) |
| Слияние вариантов персоны | variant-merges | tests/knowledge/test_person_quality.py::test_plan_partition_any_order | да (1 failed, 1 warning in 3.10s) |
| Слияние вариантов персоны | kept-input-order | tests/knowledge/test_person_quality.py::test_plan_partition_any_order | да (1 failed, 1 warning in 3.67s) |
| Слияние вариантов персоны | kept-input-order | tests/knowledge/test_person_quality.py::test_merge_invariant_two_orders | да (1 failed, 1 warning in 7.17s) |
| Слияние вариантов персоны | qid-confirmed-ignored | tests/knowledge/test_person_quality.py::test_transliteration_with_decision | да (1 failed, 1 warning in 2.95s) |
| Слияние вариантов персоны | qid-confirmed-ignored | tests/knowledge/test_person_quality.py::test_qid_confirmed_for_other | да (1 failed, 1 warning in 2.62s) |
| Слияние вариантов персоны | qid-confirmed-ignored | tests/knowledge/test_person_quality.py::test_plan_partition_any_order | да (1 failed, 1 warning in 7.34s) |
| Слияние вариантов персоны | single-word-primary-review | tests/knowledge/test_person_quality.py::test_common_primary_name | да (1 failed, 1 warning in 2.33s) |
| Слияние вариантов персоны | single-word-primary-review | tests/knowledge/test_person_quality.py::test_plan_partition_any_order | да (1 failed, 1 warning in 1.15s) |
| Слияние вариантов персоны | single-word-primary-review | tests/knowledge/test_person_quality.py::test_merge_invariant_two_orders | да (1 failed, 1 warning in 4.86s) |
| Слияние вариантов персоны | decided-ignored | tests/knowledge/test_person_quality.py::test_namesakes | да (1 failed, 1 warning in 1.94s) |
| Слияние вариантов персоны | decided-ignored | tests/knowledge/test_person_quality.py::test_decided_apart_and_third | да (1 failed, 1 warning in 2.46s) |
| Слияние вариантов персоны | decided-ignored | tests/knowledge/test_person_quality.py::test_plan_partition_any_order | да (1 failed, 1 warning in 3.24s) |
| Слияние вариантов персоны | decided-as-qid-cluster | tests/knowledge/test_person_quality.py::test_decided_apart_and_third | да (1 failed, 1 warning in 4.36s) |
| Слияние вариантов персоны | decided-as-qid-cluster | tests/knowledge/test_person_quality.py::test_plan_partition_any_order | да (1 failed, 1 warning in 1.56s) |
| Слияние вариантов персоны | single-word-variant | tests/knowledge/test_person_quality.py::test_only_variant_matched | да (1 failed, 1 warning in 1.63s) |
| Слияние вариантов персоны | single-word-variant | tests/knowledge/test_person_quality.py::test_plan_partition_any_order | да (1 failed, 1 warning in 12.84s) |
| Слияние с перенаправлением | kept-primary-stays | tests/knowledge/test_person_quality.py::test_variants_merge_by_model_pair | да (1 failed, 1 warning in 2.94s) |
| Слияние с перенаправлением | kept-primary-stays | tests/knowledge/test_entity_merge.py::test_preservation_and_undo | да (1 failed, 1 warning in 4.37s) |
| Поиск дублей | candidates-primary-only | tests/knowledge/test_entity_merge.py::test_candidates | да (1 failed, 1 warning in 1.58s) |
| Поиск дублей | candidates-primary-only | tests/knowledge/test_entity_merge.py::test_candidates_invariant | да (1 failed, 1 warning in 2.44s) |
| Поиск дублей | candidates-no-type | tests/knowledge/test_entity_merge.py::test_different_types | да (1 failed, 1 warning in 1.18s) |
| Поиск дублей | candidates-no-type | tests/knowledge/test_entity_merge.py::test_candidates_invariant | да (1 failed, 1 warning in 3.19s) |
| Слияние с перенаправлением | author-attribution-stays | tests/knowledge/test_entity_merge.py::test_author_attribution_moves | да (1 failed, 1 warning in 2.51s) |
| Слияние с перенаправлением | author-attribution-stays | tests/knowledge/test_entity_merge.py::test_preservation_and_undo | да (1 failed, 1 warning in 3.72s) |
| Слияние с перенаправлением | key-not-recomputed | tests/knowledge/test_entity_merge.py::test_repeat_folds | да (1 failed, 1 warning in 1.52s) |
| Слияние с перенаправлением | key-not-recomputed | tests/knowledge/test_entity_merge.py::test_preservation_and_undo | да (1 failed, 1 warning in 2.27s) |
| Слияние с перенаправлением | undo-without-externals | tests/knowledge/test_entity_merge.py::test_undo_with_fold_and_qid | да (1 failed, 1 warning in 2.03s) |
| Слияние с перенаправлением | undo-without-externals | tests/knowledge/test_entity_merge.py::test_preservation_and_undo | да (1 failed, 1 warning in 2.55s) |
| Слияние с перенаправлением | loop-shown | tests/knowledge/test_entity_merge.py::test_loop | да (1 failed, 1 warning in 3.54s) |
| Слияние с перенаправлением | loop-shown | tests/knowledge/test_entity_merge.py::test_preservation_and_undo | да (1 failed, 1 warning in 3.04s) |

Итого: 18 мутаций, 41 ожидаемое падение — упали все 41 (rc=0), время 7 мин 42 с. Требований 4, у каждого ≥ 2 мутации; `--coverage improve-person-quality`: «мутации есть у всех 4 требований».

### Дефекты

Расхождений вывода со спецификацией в покрытых сценариях и инвариантах не найдено.

### Наблюдения

- `knowledge.extraction.dropped` для утверждения с отклонённой персоной несёт `reason` текстом с названием: `'название «children» (person) отклонено: not_a_name'`. Спецификация `person-quality` формат причины не задаёт; в design `improve-extraction-naming` (таблица событий) причины `dropped` — коды (`dating:<код>`, `entity:type`). Название в журнале и так есть в `rejected.label` (≤ 80 знаков); здесь оно без обрезки.
- `Statements.add` с тем же ключом и той же атрибуцией добавляет атрибуцию второй раз (`[('source','s_a','asserts')] × 2` на одном утверждении) — до слияния, вне этой дельты (`ontology-statements`). Поэтому в инварианте сохранения атрибуции сравниваются множеством; «точный повтор» спецификация и так разрешает терять.
- «Отмена» — оператором: HTTP-маршрута отмены нет, тесты вызывают `Statements.undo_merge` (путь оператора и миграции).
- Решение «разные» в тестах ставится как в жизни: пункт `duplicate` (через `dedupe.propose`) закрыт `Review.resolve_duplicate(item, False, …)`.
- Сценарий «Даты у одной стороны»: оставшаяся по правилу — та, у которой больше ссылок (утверждение `lifespan`), даты 1685–1753 у неё.

### Не покрыто / непроверяемое

- «Персоны, созданные до этого изменения, приводит миграция» — путь `migrate-ontology-quality`, не здесь.
- `merge:review` (человек «слить» в очереди) — только через `resolve_duplicate` в юнит-тестах разработчика; сценария в дельте нет.
- Полный `pytest` не запускался (1 ГБ RAM), только файлы выше по одному.
