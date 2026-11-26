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

## Тестировщик — аудит пунктов (О21)

Систематический аудит покрытия (О21): строка «пункт → вид генератора → @example → мутация» на каждый нормативный пункт дельт `person-quality` и `ontology-entities`. Строк в таблице: 86. Мутации аудита — патчи от HEAD в `tests/mutations/improve-person-quality/`, всего в каталоге 76 (новых 50, все падают).

**Пробелы, найденные аудитом, и чем закрыты.**
- Виды генератора `date_chain`, `model_pair`, `mixed_type`, `review_inside` и мутации `component-dates-ignored`, `type-rule-dropped`, `model-pair-ignored`, `review-inside-queued` — уже были (внесены в таблицу).
- Выжили мутации, закрыты новыми тестами в `test_person_quality.py` и `test_entity_merge.py`: `dates-start-only`/`dates-end-only` (`test_dates_conflict_on_start_or_end_interval`: расхождение только начала, только конца, границы допуска 4 и 5 лет), `cluster-reason-dates-first` (`test_component_reason_priority_qid_cluster_over_dates`), `decided-pair-requeued` (`test_decided_pair_not_requeued_after_merge_mapping`), `load-persons-inactive` (`test_redirected_person_not_loaded`), `link-counts-no-authors`/`link-counts-no-object` (`test_link_counts_subject_object_author`), `merge-externals-not-moved` (`test_external_rows_move_to_kept`: через API `externals()` перенос не виден, потому что чтение разыменовывает перенаправление), `undo-event-*` (поле `restored`, `kept`/`removed`), порядок шагов правила (`test_same_person_step_order`: пары 2/3, 3/4, 4/5, 5/6, 6/7, 7/8, 1/всё), `external-not-unique` и `add-external-duplicate` (`test_external_id_unique`), `candidates-dates-ignored` (`test_candidates_need_equal_dates_for_last_word`).
- Эквивалентные или ненормативные мутации, снятые: `decided-edges-queued` (проверка `p not in decided` избыточна: пара с решением «разные» получает вердикт `apart:decided`, а не `merge:*`), `components-order-dependent` (корень союза-объединения не влияет на разбиение), `variants-include-primary` (пересечение основных названий перехватывает шаг 6), `apart-count-wrong` и `merge-reason-rank` (счётчик `apart` и выбор причины слияния составной компоненты спецификацией не заданы).
Обозначения: PQ = `tests/knowledge/test_person_quality.py`, EM = `test_entity_merge.py`, DU = `test_dedupe_unit.py`, PM = `test_person_merge_unit.py`. Генераторы — `tests/knowledge/strategies.py` (S.): `persons_with_variants` (виды лица FACE_KINDS: plain[dated none/equal/within/one_side], two_qids, dates, date_chain, model_pair, mixed_type, review_inside, qids_distinct, confirmed, decided, decided3, variant_single, variant_multi), `not_persons`, `ontology_with_duplicates`, `ontology_names`. Мутации — `tests/mutations/improve-person-quality/<id>.patch`.

### person-quality / Качество персон

| Пункт | Вид генератора | @example | Мутация |
|---|---|---|---|
| Персона — только названное по имени лицо | S.not_persons + S.proper_names (имена с частицами) | PQ::test_person_quality_invariant, test_person_rule_any_input | person-not-a-name |
| Не персона: местоимения и служебные слова (`some`) | S.not_persons (stopwords_perturbed) | PQ::test_person_rule_any_input (@example «Some») (фактически роняет: test_person_quality_invariant) | person-stopword-skipped |
| Не персона: обращения (`your Lordship`) | S.not_persons (stopwords_perturbed) | PQ::test_person_rule_any_input @example «Your Lordship» (фактически роняет: test_person_quality_invariant) | person-stopword-skipped |
| Не персона: роли и описания (`поэт`, `blind mathematician`, `the author of …`) | S.not_persons (not_names lower/pattern) | PQ::test_garbage_person, test_person_rule_any_input | person-not-a-name |
| Не персона: группы (`children`, `logicians`) | S.not_persons (stopwords_perturbed) | PQ::test_garbage_person (`children`) (фактически роняет: test_person_quality_invariant) | person-stopword-skipped |
| Не персона: неодушевлённые, длинные фразы | S.not_persons (long_phrases) | PQ::test_person_rule_any_input (фактически роняет: test_person_quality_invariant) | person-sentence-unchecked |
| Не персона: склейка двух имён | S.not_persons (not_names glue) | PQ::test_glued | person-not-a-name |
| Пустое название персоны — причина `empty`, не `number` | S.not_persons/blank | PQ::test_person_rule_any_input (фактически роняет: test_person_quality_invariant) | person-empty-as-number |
| Отказ — `knowledge.entity.rejected` с `type="person"` | S.not_persons | PQ::test_garbage_person, test_person_quality_invariant | person-not-a-name |
| Утверждение с отклонённой персоной отброшено, `dropped` с кодом `entity:<причина>` | S.not_persons | PQ::test_person_quality_invariant | improve-extraction-naming/dropped-reason-text (общий путь `entity_items`; в этом каталоге — person-not-a-name) |
| Промпт определяет персону и даёт отрицательные примеры «your Lordship», «blind mathematician», «children» | сценарный стенд (шаблон из перехвата) | PQ::test_person_definition_in_prompt | prompt-no-person-def |
| Инвариант: основное созданных персон не даёт причины; ровно одно `rejected` на отказ; создано = числу `created` | S.not_persons ∪ S.proper_names | PQ::test_person_quality_invariant | person-not-a-name, person-empty-as-number |
| Сценарии «Мусорная персона», «Склейка», «Определение в промпте», «Инвариант качества» | сценарные | PQ::test_garbage_person, test_glued, test_person_definition_in_prompt, test_person_quality_invariant | person-not-a-name, prompt-no-person-def |
| Персоны до изменения приводит миграция | вне изменения (`ontology-migration`) | — | — (не пункт этого изменения: нормативно отнесён к ontology-migration, его тесты — tests/knowledge/test_ontology_migration.py) |

### person-quality / Слияние вариантов персоны

| Пункт | Вид генератора | @example | Мутация |
|---|---|---|---|
| Одно лицо в разных написаниях — одна сущность | S.persons_with_variants plain (n≥2) | PQ::test_merge_invariant_two_orders; test_common_primary_name | step-name-merge-dropped |
| Внешний QID уникален | S.persons_with_variants two_qids | EM::test_candidates…; PQ::test_different_qids (фактически роняет: test_external_id_unique) | external-not-unique |
| Даты противоречат: допуск 2 года | S.persons_with_variants dates (gap 5…200), plain within (сдвиг 0…4) | PQ::test_conflicting_dates, test_plan_partition_any_order | dates-slack-zero, dates-slack-three |
| Даты противоречат: интервалы начала | S.persons_with_variants dates | PQ::test_conflicting_dates (фактически роняет: test_dates_conflict_on_start_or_end_interval) | dates-end-only |
| Даты противоречат: интервалы конца | S.persons_with_variants dates | PQ::test_conflicting_dates (фактически роняет: test_dates_conflict_on_start_or_end_interval) | dates-start-only |
| Даты у одной стороны — не противоречие | S.persons_with_variants plain one_side | PQ::test_dates_on_one_side (фактически роняет: test_date_chain_component) | dates-one-side-conflict |
| Шаг 1 `apart:type` | S.persons_with_variants mixed_type | PQ::test_merge_invariant_two_orders; PM (фактически роняет: test_plan_partition_any_order) | type-rule-dropped |
| Шаг 2 `apart:qid` | S.persons_with_variants qids_distinct | PQ::test_different_qids (фактически роняет: test_transliteration_with_decision) | step-qid-dropped |
| Шаг 3 `apart:decided` | S.persons_with_variants decided, decided3 | PQ::test_namesakes, test_decided_apart_and_third | decided-ignored |
| Шаг 4 `review:dates` | S.persons_with_variants dates, date_chain | PQ::test_conflicting_dates, test_date_chain_component | dates-unchecked |
| Шаг 5 `merge:qid_confirmed` | S.persons_with_variants confirmed | PQ::test_qid_confirmed_for_other, test_transliteration_with_decision | qid-confirmed-ignored |
| Шаг 6 `merge:name` (в т. ч. однословное) | S.persons_with_variants plain | PQ::test_common_primary_name | step-name-merge-dropped, single-word-primary-review |
| Шаг 7 `merge:model_pair` | S.persons_with_variants model_pair | PQ::test_variants_merge_by_model_pair (фактически роняет: test_plan_partition_any_order) | model-pair-ignored |
| Шаг 8 `review:single_name` / `review:variant` | S.persons_with_variants variant_single, variant_multi | PQ::test_only_variant_matched | single-word-variant, variant-merges |
| Шаг 9 `apart:none` | S.persons_with_variants (лица без общих названий) | PQ::test_plan_partition_any_order (фактически роняет: test_same_person) | step-none-as-review |
| Порядок шагов 2 и 3 (QID раньше решения) | S.persons_with_variants decided + qids | PQ::test_plan_partition_any_order (фактически роняет: test_same_person_step_order) | decided-before-qid |
| Порядок шагов 4 и 5 (даты раньше подтверждения) | S.persons_with_variants confirmed + dates | PQ::test_plan_partition_any_order (фактически роняет: test_same_person_step_order) | dates-after-confirmed |
| Порядок шагов 6 и 7 (название раньше пары модели) | S.persons_with_variants plain + model | PQ::test_plan_partition_any_order (фактически роняет: test_same_person_step_order) | model-pair-before-name |
| Компонента: ≥ 2 QID или `apart:qid` → нет слияния, `review:qid_cluster` | S.persons_with_variants two_qids | PQ::test_transitive_component_two_qids | component-qids-unchecked |
| Компонента: `review:dates` → нет слияния | S.persons_with_variants date_chain | PQ::test_date_chain_component | component-dates-ignored |
| Компонента: причина `review:dates` при противоречии дат (не qid_cluster) | S.persons_with_variants date_chain | PQ::test_date_chain_component (фактически роняет: test_component_reason_priority_qid_cluster_over_dates) | cluster-reason-dates-first |
| Компонента: `review:decided_conflict` | S.persons_with_variants decided3 | PQ::test_decided_apart_and_third | decided-as-qid-cluster |
| Пара «разные» в очередь не ставится | S.persons_with_variants decided, decided3 | PQ::test_namesakes | decided-ignored |
| Решённая пара повторно не ставится (через слитую компоненту) | S.persons_with_variants decided | PQ::test_decided_apart_and_third (фактически роняет: test_decided_pair_not_requeued_after_merge_mapping) | decided-pair-requeued |
| `review:*` внутри сливаемой компоненты не ставится | S.persons_with_variants review_inside | PQ::test_merge_invariant_two_orders | review-inside-queued |
| Пара в очереди — без повтора | S.persons_with_variants (двойной запуск) | PQ::test_merge_invariant_two_orders (один `merge_proposed` на пару) (фактически роняет: test_dedupe_run_merges_and_proposes) | propose-repeats |
| Итог не зависит от порядка входа | S.persons_with_variants (две перестановки) | PQ::test_plan_partition_any_order, test_merge_invariant_two_orders | kept-input-order |
| Оставшаяся: с QID | S.persons_with_variants plain (with_qid) | PQ::test_variants_merge_by_model_pair | kept-qid-ignored |
| Оставшаяся: больше ссылок (субъект, объект, автор-атрибуция) | S.persons_with_variants + утверждения теста | PQ::test_merge_invariant_two_orders | kept-counts-ignored, link-counts-no-object, link-counts-no-authors |
| Оставшаяся: меньший идентификатор | S.persons_with_variants plain | PQ::test_plan_partition_any_order | kept-id-tiebreak-reversed |
| Только действующие персоны участвуют | S.persons_with_variants + перенаправленные | PQ::test_merge_invariant_two_orders (фактически роняет: test_redirected_person_not_loaded) | load-persons-inactive |
| QID сохраняется | S.persons_with_variants plain (with_qid) | PQ::test_variants_merge_by_model_pair (фактически роняет: test_external_rows_move_to_kept) | merge-externals-not-moved |
| Одно основное, русское если есть у любой стороны | S.persons_with_variants plain (ru/en) | PQ::test_merge_invariant_two_orders (фактически роняет: test_preservation_and_undo, test_variants_merge_by_model_pair) | merge-russian-not-preferred, kept-primary-stays |
| Виды названий — в запись слияния (для отмены) | S.ontology_with_duplicates | EM::test_preservation_and_undo (фактически роняет: test_undo) | undo-names-kinds-not-restored |
| Утверждения и атрибуции переносятся | S.ontology_with_duplicates | EM::test_preservation_and_undo | merge-subject-not-moved, merge-object-not-moved, author-attribution-stays |
| Журнал `merged.reason` ∈ {merge:qid_confirmed, merge:name, merge:model_pair, merge:review} | S.persons_with_variants (reason по виду) | PQ::test_merge_invariant_two_orders; test_merge_by_human_decision | merge-review-reason |
| `merge_proposed.reason` ∈ review:* | S.persons_with_variants (queue) | PQ::test_merge_invariant_two_orders | review-inside-queued |
| Транслитерации: через решение человека; без решения — очередь | сценарные (Гомер/Омир) | PQ::test_transliteration_with_decision, test_transliteration_pending | qid-confirmed-ignored |
| Инвариант: разбиение по правилу, одинаково в двух перестановках | S.persons_with_variants | PQ::test_merge_invariant_two_orders | kept-input-order, component-qids-unchecked |
| Инвариант: ни одна пара с разными QID не слита; ≤ 1 QID и одно основное на язык | S.persons_with_variants two_qids, qids_distinct | PQ::test_merge_invariant_two_orders | component-qids-unchecked |
| Инвариант: на каждое слияние одно `merged`, на пару — одно `merge_proposed` | S.persons_with_variants | PQ::test_merge_invariant_two_orders (фактически роняет: test_dedupe_run_merges_and_proposes) | propose-repeats |
| Сценарии «Слияние вариантов», «Общее название», «QID подтверждён», «Транслитерация(±)», «Решение разные + третья», «Слияние по решению человека», «Тёзки», «Разные QID», «Транзитивная компонента», «Противоречащие даты», «Даты у одной стороны», «Совпал только вариант» | сценарные | PQ::test_variants_merge_by_model_pair … test_only_variant_matched | model-pair-ignored, step-name-merge-dropped, qid-confirmed-ignored, decided-ignored, component-qids-unchecked, dates-unchecked, single-word-variant |

### ontology-entities / Поиск дублей

| Пункт | Вид генератора | @example | Мутация |
|---|---|---|---|
| Кандидаты по последнему слову названия и датам | S.ontology_names | EM::test_candidates (Дж. Локк/Джон Локк) | candidates-last-word-dropped, candidates-dates-ignored |
| Кандидаты: основное одной = любое название другой | S.ontology_names / S.ontology_with_duplicates | EM::test_candidates_invariant, test_primary_on_different_records | candidates-primary-only |
| Кандидаты одного типа, разные типы — никогда | S.ontology_names | EM::test_different_types, test_candidates_invariant | candidates-no-type |
| Группа «тип + последнее слово» ≤ 200 перебирается | параметр size теста (200 / 201) | EM::test_last_word_group_cap | group-cap-off |
| Большая группа не перебирается, событие `duplicate_group_capped` | параметр size (201+) | EM::test_last_word_group_cap | group-cap-silent |
| Событие без названий (`type`, `size`, `limit`) | параметр size | EM::test_last_word_group_cap (сверка полей) | capped-event-leaks-name |
| Совпадения основного с названием ищутся и в большой группе | параметр size (201+) + общее основное | EM::test_last_word_group_cap | capped-group-aborts |
| Основное название на разных записях → пункты `duplicate` по парам | сценарный (три «Berkeley») | EM::test_primary_on_different_records (фактически роняет: test_candidates, test_candidates_invariant) | candidates-primary-only |

### ontology-entities / Слияние с перенаправлением

| Пункт | Вид генератора | @example | Мутация |
|---|---|---|---|
| Переносятся названия | S.ontology_with_duplicates | EM::test_preservation_and_undo | merge-names-not-moved |
| Переносятся утверждения (субъект) | S.ontology_with_duplicates | EM::test_preservation_and_undo (фактически роняет: test_repeat_folds) | merge-subject-not-moved |
| Переносятся утверждения (объект) | S.ontology_with_duplicates | EM::test_preservation_and_undo | merge-object-not-moved |
| Переносятся атрибуции автора позиции | S.ontology_with_duplicates (kind rel/holds) | EM::test_author_attribution_moves | author-attribution-stays |
| Переносятся внешние идентификаторы | S.ontology_with_duplicates (QID у одной стороны) | EM::test_undo_with_fold_and_qid (фактически роняет: test_external_rows_move_to_kept) | merge-externals-not-moved |
| Переносятся упоминания | S.ontology_with_duplicates (mentions) | EM::test_preservation_and_undo | merge-mentions-not-moved |
| Переносятся портреты; с тем же признаком остаётся за удалённой | S.ontology_with_duplicates (portraits одинаковый phash) | EM::test_preservation_and_undo | merge-portraits-not-moved, merge-portraits-same-phash-moved |
| Названия: одно основное, русское если есть у любой | S.ontology_with_duplicates | EM::test_preservation_and_undo; пример «Locke»←«Локк» | merge-russian-not-preferred, kept-primary-stays |
| Прочие бывшие основные — варианты; виды — в запись слияния | S.ontology_with_duplicates | EM::test_preservation_and_undo | kept-primary-stays, undo-names-kinds-not-restored |
| Ключи перенесённых пересчитываются, повтор сворачивается | S.ontology_with_duplicates (repeats) | EM::test_repeat_folds | key-not-recomputed |
| Ссылка по id свёрнутого отдаёт оставшееся | S.ontology_with_duplicates | EM::test_repeat_folds | key-not-recomputed |
| Петля остаётся в базе, не показывается, считается как петля | S.ontology_with_duplicates (loops) | EM::test_loop | loop-shown, merged-loops-zero |
| Перенаправление: старый id отдаёт оставшуюся | S.ontology_with_duplicates | EM::test_old_link | merge-redirect-missing |
| Отмена: названия и их вид | S.ontology_with_duplicates | EM::test_preservation_and_undo (фактически роняет: test_undo) | undo-names-kinds-not-restored |
| Отмена: утверждения, включая свёрнутые, с прежними id | S.ontology_with_duplicates | EM::test_undo_with_fold_and_qid | undo-subject-not-restored |
| Отмена: атрибуции и подтверждения | S.ontology_with_duplicates | EM::test_preservation_and_undo | undo-attributions-not-restored |
| Отмена: QID возвращается удалённой | сценарный (Hume Q41568) | EM::test_undo_with_fold_and_qid | undo-without-externals |
| Отмена: упоминания и портреты | S.ontology_with_duplicates | EM::test_preservation_and_undo | undo-mentions-not-restored, undo-portraits-not-restored |
| Отмена снимает перенаправление | S.ontology_with_duplicates | EM::test_undo | undo-redirect-kept |
| `merged` с полями `kept, removed, reason, statements, attributions, folded, loops` | S.ontology_with_duplicates | EM::test_repeat_folds (folded=1), test_author_attribution_moves (attributions≥1), test_loop (loops=1) | merged-statements-count, merged-attributions-zero, merged-folded-zero, merged-loops-zero |
| `merge_undone` с `kept, removed, restored` | сценарный | EM::test_undo_with_fold_and_qid (restored=1) | undo-event-restored-zero, undo-event-kept-removed-swapped |
| Инвариант: не потеряно утверждение/атрибуция/подтверждение; отмена ⇒ дамп равен исходному | S.ontology_with_duplicates (5–30 сущностей) | EM::test_preservation_and_undo | merge-subject-not-moved, merge-object-not-moved, undo-subject-not-restored, key-not-recomputed |



Прогоны мутаций аудита (требование | мутация | тест | упал):

| Требование | Мутация | Тест | Упал |
|---|---|---|---|
| Слияние вариантов персоны | step-qid-dropped | tests/knowledge/test_person_quality.py::test_transliteration_with_decision | да (1) |
| Слияние вариантов персоны | step-name-merge-dropped | tests/knowledge/test_person_quality.py::test_common_primary_name | да (1) |
| Слияние вариантов персоны | step-none-as-review | tests/knowledge/test_dedupe_unit.py::test_same_person | да (1) |
| Слияние вариантов персоны | dates-slack-zero | tests/knowledge/test_person_quality.py::test_plan_partition_any_order | да (1) |
| Слияние вариантов персоны | dates-slack-three | tests/knowledge/test_person_quality.py::test_plan_partition_any_order | да (1) |
| Слияние вариантов персоны | dates-start-only | tests/knowledge/test_person_quality.py::test_dates_conflict_on_start_or_end_interval | да (1) |
| Слияние вариантов персоны | dates-end-only | tests/knowledge/test_person_quality.py::test_dates_conflict_on_start_or_end_interval | да (1) |
| Слияние вариантов персоны | kept-qid-ignored | tests/knowledge/test_person_quality.py::test_variants_merge_by_model_pair | да (1) |
| Слияние вариантов персоны | kept-counts-ignored | tests/knowledge/test_person_quality.py::test_merge_invariant_two_orders | да (1) |
| Слияние вариантов персоны | kept-id-tiebreak-reversed | tests/knowledge/test_person_quality.py::test_plan_partition_any_order | да (1) |
| Слияние вариантов персоны | cluster-reason-dates-first | tests/knowledge/test_person_quality.py::test_component_reason_priority_qid_cluster_over_dates | да (1) |
| Слияние вариантов персоны | decided-pair-requeued | tests/knowledge/test_person_quality.py::test_decided_pair_not_requeued_after_merge_mapping | да (1) |
| Слияние вариантов персоны | propose-repeats | tests/knowledge/test_dedupe_unit.py::test_dedupe_run_merges_and_proposes | да (1) |
| Слияние вариантов персоны | load-persons-inactive | tests/knowledge/test_person_quality.py::test_redirected_person_not_loaded | да (1) |
| Слияние вариантов персоны | link-counts-no-authors | tests/knowledge/test_person_quality.py::test_link_counts_subject_object_author | да (1) |
| Слияние вариантов персоны | link-counts-no-object | tests/knowledge/test_person_quality.py::test_link_counts_subject_object_author | да (1) |
| Поиск дублей | candidates-ignore-variants | tests/knowledge/test_person_quality.py::test_only_variant_matched | да (1) |
| Слияние с перенаправлением | merge-subject-not-moved | tests/knowledge/test_entity_merge.py::test_repeat_folds | да (1) |
| Слияние с перенаправлением | merge-object-not-moved | tests/knowledge/test_entity_merge.py::test_preservation_and_undo | да (1) |
| Слияние с перенаправлением | merge-externals-not-moved | tests/knowledge/test_entity_merge.py::test_external_rows_move_to_kept | да (1) |
| Слияние с перенаправлением | merge-mentions-not-moved | tests/knowledge/test_entity_merge.py::test_preservation_and_undo | да (1) |
| Слияние с перенаправлением | merge-names-not-moved | tests/knowledge/test_entity_merge.py::test_preservation_and_undo | да (1) |
| Слияние с перенаправлением | merge-portraits-same-phash-moved | tests/knowledge/test_entity_merge.py::test_preservation_and_undo | да (1) |
| Слияние с перенаправлением | merge-portraits-not-moved | tests/knowledge/test_entity_merge.py::test_preservation_and_undo | да (1) |
| Слияние с перенаправлением | merge-redirect-missing | tests/knowledge/test_entity_merge.py::test_old_link | да (1) |
| Слияние с перенаправлением | merge-russian-not-preferred | tests/knowledge/test_entity_merge.py::test_preservation_and_undo | да (1) |
| Слияние с перенаправлением | undo-names-kinds-not-restored | tests/knowledge/test_entity_merge.py::test_undo | да (1) |
| Слияние с перенаправлением | undo-subject-not-restored | tests/knowledge/test_entity_merge.py::test_undo | да (1) |
| Слияние с перенаправлением | undo-mentions-not-restored | tests/knowledge/test_entity_merge.py::test_preservation_and_undo | да (1) |
| Слияние с перенаправлением | undo-portraits-not-restored | tests/knowledge/test_entity_merge.py::test_preservation_and_undo | да (1) |
| Слияние с перенаправлением | undo-attributions-not-restored | tests/knowledge/test_entity_merge.py::test_preservation_and_undo | да (1) |
| Слияние с перенаправлением | undo-redirect-kept | tests/knowledge/test_entity_merge.py::test_undo | да (1) |
| Слияние с перенаправлением | undo-event-restored-zero | tests/knowledge/test_entity_merge.py::test_undo_with_fold_and_qid | да (1) |
| Слияние с перенаправлением | undo-event-kept-removed-swapped | tests/knowledge/test_entity_merge.py::test_undo | да (1) |
| Слияние с перенаправлением | merged-statements-count | tests/knowledge/test_person_merge_unit.py::test_merge_entities_folds_repeat_and_undo_restores | да (1) |
| Слияние с перенаправлением | merged-attributions-zero | tests/knowledge/test_entity_merge.py::test_author_attribution_moves | да (1) |
| Слияние с перенаправлением | merged-folded-zero | tests/knowledge/test_entity_merge.py::test_repeat_folds | да (1) |
| Слияние с перенаправлением | merged-loops-zero | tests/knowledge/test_entity_merge.py::test_loop | да (1) |
| Качество персон | person-stopword-skipped | tests/knowledge/test_person_quality.py::test_person_quality_invariant | да (1) |
| Качество персон | person-sentence-unchecked | tests/knowledge/test_person_quality.py::test_person_quality_invariant | да (1) |
| Слияние вариантов персоны | dates-one-side-conflict | tests/knowledge/test_person_quality.py::test_date_chain_component | да (1) |
| Слияние вариантов персоны | dates-after-confirmed | tests/knowledge/test_person_quality.py::test_same_person_step_order | да (1) |
| Слияние вариантов персоны | decided-before-qid | tests/knowledge/test_person_quality.py::test_same_person_step_order | да (1) |
| Слияние вариантов персоны | model-pair-before-name | tests/knowledge/test_person_quality.py::test_same_person_step_order | да (1) |
| Слияние вариантов персоны | external-not-unique | tests/knowledge/test_person_quality.py::test_external_id_unique | да (1) |
| Слияние вариантов персоны | add-external-duplicate | tests/knowledge/test_person_quality.py::test_external_id_unique | да (1) |
| Поиск дублей | candidates-dates-ignored | tests/knowledge/test_entity_merge.py::test_candidates_need_equal_dates_for_last_word | да (1) |
| Поиск дублей | candidates-last-word-dropped | tests/knowledge/test_entity_merge.py::test_candidates | да (1) |
| Поиск дублей | capped-event-leaks-name | tests/knowledge/test_entity_merge.py::test_last_word_group_cap | да (1) |
| Поиск дублей | capped-group-aborts | tests/knowledge/test_entity_merge.py::test_last_word_group_cap | да (1) |
| — | merge-reason-rank | — | НЕТ (20 passed, 1 warning in 67.08s (0:01:07)) |
| — | decided-edges-queued | — | НЕТ (49 passed, 1 warning in 47.81s) |
| — | components-order-dependent | — | НЕТ (49 passed, 1 warning in 120.58s (0:02:00)) |
| — | variants-include-primary | — | НЕТ (49 passed, 1 warning in 93.12s (0:01:33)) |
| — | apart-count-wrong | — | НЕТ (49 passed, 1 warning in 93.84s (0:01:33)) |
| — | merge-kinds-not-recorded | — | НЕТ (не прогнан) |

**Не покрыто:**
- «Персоны, созданные до изменения, приводит миграция» — пункт `ontology-migration` (тесты `test_ontology_migration.py` и мутации `migrate-ontology-quality`), здесь не дублируется.
- Причины `review:qid_candidate`/`review:qid_taken` ставит команда QID — покрыты в `add-wikidata-life-dates` (`holder-not-queued`, `suggest-decided-apart-requeued`).
- «Кандидаты по внешним идентификаторам» (ontology-entities): внешний идентификатор уникален, поиск по нему тождественен поиску по названию; отдельной ветки кода нет.

**Дефекты:** расхождений кода со спецификацией не найдено; все выжившие мутации были пробелами тестов и закрыты.
