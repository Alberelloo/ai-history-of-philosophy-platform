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
| person-quality «Качество персон» | test_person_quality.py: test_garbage_person, test_glued, test_person_definition_in_prompt | test_person_rule_any_input (pure 400), test_person_quality_invariant (ci, через извлечение + 9 @example) | person-not-a-name, prompt-no-person-def | да ×5 |
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

    test_person_quality.py      20 passed in 97.73s (рабочее дерево); 21 passed in 119.61s (worktree на 2a886ef, с test_person_rule_any_input)
      38.92s test_merge_invariant_two_orders · 24.47s test_person_quality_invariant · 8.33s test_plan_partition_any_order
    test_entity_merge.py        11 passed in 82.92s; 11 passed in 62.46s (worktree на 2a886ef)
      50.41s test_preservation_and_undo · 13.51s test_candidates_invariant
    test_registry_entities.py   33 passed, 1 skipped in 32.23s (3.6: test_merge_redirect_and_undo, test_duplicate_candidates без правки ожиданий)
    test_entity_naming.py       35 passed in 36.60s · test_entity_dating_extraction.py 14 passed in 57.70s
    test_mutation_coverage.py   2 passed · check_traceability: 407 из 407 · lint-imports: 3 kept, 0 broken
    ruff check / format --check (мои файлы): чисто

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

Дозапуск `--id person-not-a-name` на 2a886ef: и `test_person_rule_any_input` — да (1 failed, 1.92 s).

Итого: 18 мутаций, 42 ожидаемых падения — упали все 42 (rc=0), время 7 мин 42 с. Требований 4, у каждого ≥ 2 мутации; `--coverage improve-person-quality`: «мутации есть у всех 4 требований».

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

## Тестировщик — перепроверка после О17/О18 (2026-11-25, тесты на ea6321d)

- «Слияние по решению человека» (О17): `test_merge_by_human_decision` — `resolve_duplicate(merge=True)`: одна персона, названия `{primary «Бэкон», variant «Фрэнсис Бэкон»}`, утверждение второй при первой, `/v1/entities/<вторая>` отдаёт первую, очередь пуста, `knowledge.entity.merged` `(kept, removed, "merge:review")`, `knowledge.review.decided` `decision="merge"`.
- `dropped.reason` кодом: `test_garbage_not_a_person` / `test_glued_...` / инвариант качества — `["entity:<причина>"]`.
- Пустое название персоны: из `_person_cases` убран фильтр `empty`; `@example` `(person, "")`, `(person, "   ")` → `empty` (зонд: `""`, `"   "`, `"\t"` → `knowledge.entity.rejected {type: person, label: "", reason: empty}` и `dropped entity:empty`).
- Предел группы дублей (О18, ontology-entities «Поиск дублей»): `test_last_word_group_cap[200|201]` — 200 сущностей «… Локк» (из них две «Джон Локк»): пара по последнему слову есть, события нет; 201: пары по последнему слову нет, `duplicate_group_capped` ровно `{type, size, limit}` = `(person, 201, 200)`, без названий; совпадение полного названия найдено в обоих случаях.

Сырые прогоны: test_person_quality 22 passed in 159.27s · test_entity_merge 13 passed in 89.64s.

| Требование | Мутация | Ожидаемый тест | Упал |
|---|---|---|---|
| Слияние вариантов персоны | merge-review-reason | test_person_quality::test_merge_by_human_decision | да (на 2cc4f44) |
| Поиск дублей | group-cap-silent | test_entity_merge::test_last_word_group_cap[201] | да |
| Поиск дублей | group-cap-off | test_entity_merge::test_last_word_group_cap[201] | да |
| Качество персон | person-empty-as-number | test_person_quality::test_person_quality_invariant | да |

Дефектов нет.

## Судья — 2026-11-25, коммит 172787d (тесты изменения — на 01dc7ca; между ними в src только `integrity.py` другого изменения)

| Требование | Сценарий / инвариант | Журнал тестировщика | Мой прогон | Вывод системы | Итог |
|---|---|---|---|---|---|
| person-quality «Качество персон» | Мусорная персона, Склейка, Определение в промпте, Инвариант качества (ci + pure) | 22 passed (файл), мутации person-not-a-name, prompt-no-person-def, person-empty-as-number — упали | test_person_quality.py 22 passed in 274.80s | — (покрыто стендом извлечения в тестах) | подтверждено |
| person-quality «Слияние вариантов персоны» | 13 сценариев + test_plan_partition_any_order, test_merge_invariant_two_orders | все мутации упали | passed; component-qids-unchecked — упали все 3 теста; **моя J1 — не упал ни один** | онтология судьи: Berkeley×3 → одна (2× `merged` `merge:name`); Бэкон/Бэкон с решением «разные» — обе остаются, пункта нет; Омир → Гомер (`life_dates.skipped qid_taken`, `merged merge:qid_confirmed`), QID Q6691 у Гомера; Locke/Локк(вариант Locke) — `merge_proposed review:single_name` (по правилу, шаг 8) | **не подтверждено** (ветка компоненты `review:dates`) |
| ontology-entities «Поиск дублей» (MODIFIED) | Кандидаты, Основное на разных записях, Разные типы, test_candidates_invariant, test_last_word_group_cap | passed, мутации упали | test_entity_merge.py 13 passed in 56.92s | — | подтверждено |
| ontology-entities «Слияние с перенаправлением» (MODIFIED) | Старая ссылка, Отмена, Повтор, Атрибуция автору, Петля, Отмена со свёрткой и QID, test_preservation_and_undo | passed, мутации упали | passed; undo-without-externals, author-attribution-stays — упали; моя J2 (отмена не возвращает `attributions.who`) — упал test_preservation_and_undo | Locke(Q9353)/Локк слиты человеком (`merged merge:review`, `review.decided merge`): QID у оставшейся; отмена — QID снова у Locke, основное «Locke»; после отмены всех 4 слияний `dump` равен исходному (0 различающихся таблиц), `merge_undone` ×4 | подтверждено |

Прежние: test_registry_entities 33 passed, 1 skipped (PostgreSQL-гонка) · test_statements 19 passed · test_snapshot 6 passed · test_filling 30 passed; правок ожиданий в них нет (`git diff origin/claude/embedding-docker...HEAD` пуст по этим файлам).
`ruff check` / `ruff format --check` по файлам изменения — чисто; `lint-imports` 3 kept, 0 broken; `check_traceability.py` 410 из 410, `person-quality` в `enforce`; `mutation_check.py --coverage improve-person-quality` — все 4 требования. Правка файла Lead'а `prompts/__init__.py` — только текст `ontology.extract` (плюс блок `language` и `translate_names` — от `improve-extraction-naming`).
Полный `pytest` и стенд не запускались (1 ГБ RAM, указание ведущего); вывод системы — по базе и журналу собранной в памяти онтологии (`Dedupe.run`, `LifeDates.apply`, `Review.resolve_duplicate`, `Statements.undo_merge`).

Мутации (отдельный worktree, удалён; `git diff -- src` пуст):
- component-qids-unchecked, undo-without-externals, author-attribution-stays (из списка) — упали все ожидаемые тесты;
- **J1 (моя):** в `dedupe.plan` из условия отказа компоненты убрано `review:dates` (`kinds & {"apart:qid", "apart:decided"}`). Под мутацией `plan` сливает «Berkeley» 1685–1753, «Berkeley» без дат и «Berkeley» 1885–1953 в одну сущность (без мутации — три пункта `review:dates`, по спецификации). **Не упали** test_plan_partition_any_order (1 passed) и test_merge_invariant_two_orders (1 passed); сценарного теста на эту ветку нет;
- J2 (моя): `undo_merge` не возвращает `attributions.who` — упал test_preservation_and_undo.

Подгонка: признаков не найдено (оракулы не импортируют `dedupe`/`naming`, `@example` на границы дат 4/5 и транзитивные QID есть, skip/xfail нет). Но стратегия `persons_with_variants` строит лица только изолированными видами: противоречие дат — лишь в паре из двух записей, поэтому правило спецификации «компонента, у какой-либо пары которой `review:dates`, не сливается» (транзитивная цепочка через запись без дат) входом не порождается и не проверено ничем. Инвариант «слиты ровно компоненты, допустимые по правилу» доказан не для любых входов. Код ведёт себя по спецификации (проверено вручную), дефект — в покрытии.

Вердикт: **не принято** — вернуть тестировщику: (1) в `persons_with_variants` вид лица «цепочка дат»: ≥ 3 записи с общим основным, крайние с противоречащими датами, между ними запись без дат — ожидание: слияний нет, все пары лица в очереди с `review:dates`; явный `@example` этой границы; (2) сценарный или нормативный тест на эту ветку; (3) мутацию J1 (`review:dates` убрано из условия отказа компоненты) — в `mutations.yaml` с ожидаемым падением обоих property-тестов; перепрогон `--id` и строка в таблице. Разработчику возвращать нечего.

## Тестировщик — возврат судьи (J1), 2026-11-25

- `persons_with_variants`: новый вид лица `date_chain`. Это три записи с общим основным названием: крайние с противоречащими датами (сдвиг 5–200 лет), средняя без дат. Ожидание: слияний нет, все три пары в очереди с `review:dates`. Явный `@example(DATE_CHAIN)` («Berkeley» 1685–1753 / без дат / 1885–1953) стоит в `test_plan_partition_any_order` и `test_merge_invariant_two_orders`.
- Нормативный тест `test_date_chain_component`: `Dedupe.run` на этой тройке. Три персоны остаются, `merged` нет, очередь = три пары, `merge_proposed` только с `review:dates`.
- Прогон: `-k "date_chain or plan_partition or merge_invariant_two_orders"` — 3 passed in 38.75s.

| Требование | Мутация | Ожидаемый тест | Упал |
|---|---|---|---|
| Слияние вариантов персоны | component-dates-ignored (J1) | test_date_chain_component | да |
| Слияние вариантов персоны | component-dates-ignored (J1) | test_plan_partition_any_order | да |
| Слияние вариантов персоны | component-dates-ignored (J1) | test_merge_invariant_two_orders | да |

Ветви правила «Слияние вариантов» и виды генератора `persons_with_variants`:

| Ветвь | Вид генератора |
|---|---|
| 1 `apart:type` | `mixed_type`: пара модели «персона — понятие с тем же названием» → понятие не сливается, две персоны сливаются `merge:name`. Мутация type-rule-dropped |
| 2 `apart:qid` | `qids_distinct`; в компоненте — `two_qids` (пара 0–2) |
| 3 `apart:decided` | `decided`, `decided3` |
| 4 `review:dates` | `dates` (пара); в компоненте — `date_chain` (новый) |
| 5 `merge:qid_confirmed` | `confirmed` |
| 6 `merge:name` | `plain` (1–4 записи, регистр, даты в допуске и с одной стороны) |
| 7 `merge:model_pair` | `model_pair`: пары модели в `case["model"]` → `plan(pairs_by_model=…)` сливает. В `Dedupe.run` пар модели нет — ожидание: ни слияния, ни очереди. Мутация model-pair-ignored |
| 8 `review:single_name` / `review:variant` | `variant_single` / `variant_multi` |
| 9 `apart:none` | разные лица (уникальный хвост названия) |
| компонента: два QID → `review:qid_cluster` | `two_qids` |
| компонента: решение «разные» — единственная преграда → `review:decided_conflict` | `decided3` |
| пара без других рёбер, кроме решённой, — не в очередь | `decided` |
| пара `review:*` внутри сливаемой компоненты — не в очередь | `review_inside`: B и C подтверждены для QID A; основное B = вариант C (`review:single_name`) → слита вся тройка, очереди нет. Мутация review-inside-queued |

Явные `@example`: `MODEL_PAIR` (Hume/Хьюм по модели; Substance — две персоны и понятие) и `REVIEW_INSIDE` (Homer Q6691, Омир, «Гомерос» с вариантом «Омир») — в обоих property-тестах. Прогон `-k "date_chain or plan_partition or merge_invariant_two_orders"` — 3 passed in 37.90s.

| Требование | Мутация | Ожидаемый тест | Упал |
|---|---|---|---|
| Слияние вариантов персоны | type-rule-dropped | test_plan_partition_any_order | да |
| Слияние вариантов персоны | model-pair-ignored | test_plan_partition_any_order | да |
| Слияние вариантов персоны | review-inside-queued | test_plan_partition_any_order | да |
| Слияние вариантов персоны | review-inside-queued | test_merge_invariant_two_orders | да |

`apart:type` и `merge:model_pair` проверяются только чистым `plan`: `Dedupe.run` по базе берёт одни персоны и не принимает пар модели. Это видно из сигнатуры `run(confirmed, scope)`.
