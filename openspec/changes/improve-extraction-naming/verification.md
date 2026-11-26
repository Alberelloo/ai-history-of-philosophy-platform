# Verification

## Тестировщик — 2026-11-25, тесты на коммите b255417 (ветка claude/ontology-extraction)

Тесты написаны от дельт `specs/` и design.md (контракты, «Тестовая инфраструктура», «Границы и сторожевые токены»). Продуктовый код читался только после коммита тестов, для патчей мутаций.

Инфраструктура (3.1): профили hypothesis `ci`/`pure`/`heavy` (60/400/25, `derandomize`, `deadline=None`, `database=None`, `print_blob`) в `tests/conftest.py`; автофикстура запрета сети `tests/knowledge/conftest.py::_forbid_network` (разрешён только хост `PHILOGRAPH_TEST_DATABASE_URL`); `tests/knowledge/dump.py`; стенд извлечения `tests/knowledge/extraction_stand.py` (настоящий `Filling.extract_version`, шлюз с фейковым провайдером, запись запросов к шлюзу, поддельная библиотека; `passed_gateway` — ответ, уже прошедший шлюз); стратегии «вход + ожидание» `tests/knowledge/strategies.py` (`numbers`, `blank`, `long_phrases`, `at_limit`, `stopwords_perturbed`, `proper_names`, `not_names`, `scripts_mix`, `fragment_items`, `datings`; не импортируют `naming`/`dating`/`dates` — `test_strategies_oracle_independent`); `scripts/mutation_check.py` (`--change`, `--id`, `--coverage`); `tests/test_mutation_coverage.py`; `tests/mutations/improve-extraction-naming/` (14 патчей, `mutations.yaml`). `entity-naming` добавлена в `enforce`; `entity-dating` — нет: у неё есть требования `add-wikidata-life-dates` без тестов (по tasks.md — в его 3.6).

### Требование → тесты → мутация

| Требование | Сценарные тесты | Property / нормативные | Мутация | Упал |
|---|---|---|---|---|
| entity-naming «Язык названий сущностей» | test_entity_naming.py: test_russian_textbook, test_existing_english_entity_gets_russian_primary, test_latin_without_russian, test_language_by_script_on_every_path, test_rejected_russian_spelling, test_spellings_found_different_entities | test_lang_for_any_text (pure 400 + 12 @example), test_language_invariant_create_and_add_name (ci), test_extraction_entities.py::test_normalization_and_language_for_any_items (heavy), test_no_latin_name_has_ru (параметры) | lang-given, rename-creates | да, да |
| entity-naming «Валидность названий сущностей» | test_section_number, test_numbers_with_marks, test_sentence_instead_of_term, test_description_with_capital, test_role_instead_of_name, test_stopword_concept, test_empty_names, test_glued_names, test_limit_boundaries, test_particles_and_roman, test_manual_core, test_stopword_list_from_data | test_check_name_any_input (pure 400 + 34 @example), test_rejection_invariant (ci; пути create / set_primary_name / add_name primary + 46 @example), test_rejected_label_is_name_after_strip | number-regex, patterns-case, stopword-before-person, label-no-trim | да ×4 |
| entity-dating «Извлечение дат» | test_entity_dating_extraction.py: test_life_dates_in_text, test_bc_dates, test_work_year, test_event_century, test_century_not_in_quote, test_era_mismatch, test_year_not_in_quote, test_number_inside_number, test_single_year_person, test_unparsed, test_paragraph_outside_fragment | test_dating_invariant (ci, через извлечение + 12 @example), test_dating_check_any_input (pure 400) | numbers-substring, era-unchecked, roman-unchecked | да ×3 |
| ontology-extraction «Структурированный вывод по реестру» | test_extraction_entities.py: test_uncertain_type_falls_back_to_general, test_schema_with_entities_and_dating, test_entity_type_outside_registry, test_answer_without_entities | test_only_registry_types_for_any_items (heavy) | entity-type-unchecked | да |
| ontology-extraction «Нормализация сущностей» | test_binding_by_variant, test_ambiguous_goes_to_review, test_binding_by_english_spelling | test_normalization_and_language_for_any_items (heavy) | spellings-without-en | да |
| epochs «Даты эпох из Wikidata» | test_invalid_name_external.py::test_epoch_name_rejected | test_epoch_created_iff_name_valid (heavy) | epoch-invalid-unchecked | да |
| epoch-context «Контекстные события из Wikidata» | test_context_event_name_rejected | test_context_candidate_written_iff_name_valid (heavy) | context-place-before-event | да |
| geo-timeline «Места и координаты из Wikidata» | test_place_label_rejected | test_place_created_iff_label_valid (heavy) | geo-label-unchecked | да |

Итого: 8 требований, у всех 8 — property-тест и мутация, 14 мутаций / 36 ожидаемых падений — все 36 упали.

Каждый тест проверяет вывод (база, ответ справочника/принятия/отчёт, перехваченный запрос к шлюзу) и событие; поля событий сверяются точным множеством (без полей контекста `request_id`, `run_id`, `service`). Сторожевые токены `SENTINEL…` — в абзацах, цитатах, вариантах названий; проверка `no_token` во всех тестах извлечения и в test_rejection_invariant.

Выдержки событий (сырые, из прогона):

    knowledge.entity.renamed {'run_id': 'fill_…', 'entity_id': 'e_…', 'lang': 'ru', 'previous_lang': 'en'}
    knowledge.entity.rejected {'type': 'person', 'label': 'your Lordship', 'reason': 'not_a_name'}
    knowledge.extraction.dropped {'run_id': 'fill_…', 'reason': 'dating:not_in_quote'}
    knowledge.statement.created {'run_id': 'fill_…', 'statement_id': 'st_…', 'type': 'lifespan', 'status': 'sourced'}

Команды и итоги (по одному файлу, коммит ce7e574):

    pytest -q tests/knowledge/test_entity_naming.py             → 6 failed, 27 passed in 42.8s (6 — дефекты Д1, Д2)
    pytest -q tests/knowledge/test_entity_dating_extraction.py  → 13 passed in 40.8s
    pytest -q tests/knowledge/test_extraction_entities.py       → 9 passed in 32.6s
    pytest -q tests/knowledge/test_invalid_name_external.py     → 6 passed in 29.2s
    pytest -q tests/test_mutation_coverage.py                   → 1 passed
    pytest -q tests/knowledge/test_filling.py test_wikidata.py test_invalid_name_paths_unit.py (с запретом сети) → 86 passed
    ruff check src tests scripts → 1 ошибка: E501 scripts/dev_stack.py:100 (не этого изменения)
    lint-imports → 3 kept, 0 broken
    check_traceability.py → 405 из 405
    mutation_check.py --coverage improve-extraction-naming → мутации есть у всех 8 требований

`--durations` property-слоя (сек): test_dating_invariant 17.96, test_normalization_and_language_for_any_items 11.59, test_dating_check_any_input 8.05, test_check_name_any_input 7.43, test_place_created_iff_label_valid 6.66, test_only_registry_types_for_any_items 5.73, test_epoch_created_iff_name_valid 4.93, test_lang_for_any_text 4.36, test_language_invariant_create_and_add_name 3.16, test_rejection_invariant 2.59, test_context_candidate_written_iff_name_valid ≈6 — итого ≈ 79 с (бюджет четырёх изменений — 180 с).

Мутации: `python scripts/mutation_check.py --change improve-extraction-naming`, запуск в отдельном `git worktree` того же коммита (PYTHONPATH=worktree/src), чтобы не трогать рабочую копию параллельного изменения; после прогона дерево worktree чистое. Вывод:

| Требование | Мутация | Ожидаемый тест | Упал |
|---|---|---|---|
| Язык названий сущностей | lang-given | tests/knowledge/test_entity_naming.py::test_language_by_script_on_every_path | да (1 failed, 1 warning in 4.09s) |
| Язык названий сущностей | lang-given | tests/knowledge/test_entity_naming.py::test_lang_for_any_text | да (1 failed, 1 warning in 1.43s) |
| Язык названий сущностей | lang-given | tests/knowledge/test_entity_naming.py::test_language_invariant_create_and_add_name | да (1 failed, 1 warning in 3.56s) |
| Язык названий сущностей | rename-creates | tests/knowledge/test_entity_naming.py::test_existing_english_entity_gets_russian_primary | да (1 failed, 1 warning in 3.88s) |
| Язык названий сущностей | rename-creates | tests/knowledge/test_extraction_entities.py::test_normalization_and_language_for_any_items | да (1 failed, 1 warning in 4.61s) |
| Валидность названий сущностей | number-regex | tests/knowledge/test_entity_naming.py::test_numbers_with_marks | да (1 failed, 1 warning in 2.93s) |
| Валидность названий сущностей | number-regex | tests/knowledge/test_entity_naming.py::test_check_name_any_input | да (1 failed, 1 warning in 1.35s) |
| Валидность названий сущностей | number-regex | tests/knowledge/test_entity_naming.py::test_rejection_invariant | да (1 failed, 1 warning in 3.53s) |
| Валидность названий сущностей | patterns-case | tests/knowledge/test_entity_naming.py::test_description_with_capital | да (1 failed, 1 warning in 2.46s) |
| Валидность названий сущностей | patterns-case | tests/knowledge/test_entity_naming.py::test_check_name_any_input | да (1 failed, 1 warning in 3.50s) |
| Валидность названий сущностей | patterns-case | tests/knowledge/test_entity_naming.py::test_rejection_invariant | да (1 failed, 1 warning in 4.68s) |
| Валидность названий сущностей | stopword-before-person | tests/knowledge/test_entity_naming.py::test_role_instead_of_name | да (1 failed, 1 warning in 3.44s) |
| Валидность названий сущностей | stopword-before-person | tests/knowledge/test_entity_naming.py::test_check_name_any_input | да (1 failed, 1 warning in 1.69s) |
| Валидность названий сущностей | stopword-before-person | tests/knowledge/test_entity_naming.py::test_rejection_invariant | да (1 failed, 1 warning in 3.91s) |
| Валидность названий сущностей | label-no-trim | tests/knowledge/test_entity_naming.py::test_limit_boundaries | да (1 failed, 1 warning in 2.14s) |
| Валидность названий сущностей | label-no-trim | tests/knowledge/test_entity_naming.py::test_check_name_any_input | да (1 failed, 1 warning in 2.30s) |
| Валидность названий сущностей | label-no-trim | tests/knowledge/test_entity_naming.py::test_rejection_invariant | да (1 failed, 1 warning in 3.38s) |
| Извлечение дат | numbers-substring | tests/knowledge/test_entity_dating_extraction.py::test_number_inside_number | да (1 failed, 1 warning in 2.97s) |
| Извлечение дат | numbers-substring | tests/knowledge/test_entity_dating_extraction.py::test_dating_check_any_input | да (1 failed, 1 warning in 0.60s) |
| Извлечение дат | numbers-substring | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (1 failed, 1 warning in 4.10s) |
| Извлечение дат | era-unchecked | tests/knowledge/test_entity_dating_extraction.py::test_era_mismatch | да (1 failed, 1 warning in 1.79s) |
| Извлечение дат | era-unchecked | tests/knowledge/test_entity_dating_extraction.py::test_dating_check_any_input | да (1 failed, 1 warning in 1.01s) |
| Извлечение дат | era-unchecked | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (1 failed, 1 warning in 4.19s) |
| Извлечение дат | roman-unchecked | tests/knowledge/test_entity_dating_extraction.py::test_century_not_in_quote | да (1 failed, 1 warning in 1.59s) |
| Извлечение дат | roman-unchecked | tests/knowledge/test_entity_dating_extraction.py::test_dating_check_any_input | да (1 failed, 1 warning in 0.96s) |
| Извлечение дат | roman-unchecked | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (1 failed, 1 warning in 4.18s) |
| Структурированный вывод по реестру | entity-type-unchecked | tests/knowledge/test_extraction_entities.py::test_entity_type_outside_registry | да (1 failed, 1 warning in 1.69s) |
| Структурированный вывод по реестру | entity-type-unchecked | tests/knowledge/test_extraction_entities.py::test_only_registry_types_for_any_items | да (1 failed, 1 warning in 1.65s) |
| Нормализация сущностей | spellings-without-en | tests/knowledge/test_extraction_entities.py::test_binding_by_english_spelling | да (1 failed, 1 warning in 1.42s) |
| Нормализация сущностей | spellings-without-en | tests/knowledge/test_extraction_entities.py::test_normalization_and_language_for_any_items | да (1 failed, 1 warning in 2.63s) |
| Даты эпох из Wikidata | epoch-invalid-unchecked | tests/knowledge/test_invalid_name_external.py::test_epoch_name_rejected | да (1 failed, 1 warning in 1.61s) |
| Даты эпох из Wikidata | epoch-invalid-unchecked | tests/knowledge/test_invalid_name_external.py::test_epoch_created_iff_name_valid | да (1 failed, 1 warning in 2.27s) |
| Контекстные события из Wikidata | context-place-before-event | tests/knowledge/test_invalid_name_external.py::test_context_event_name_rejected | да (1 failed, 1 warning in 1.48s) |
| Контекстные события из Wikidata | context-place-before-event | tests/knowledge/test_invalid_name_external.py::test_context_candidate_written_iff_name_valid | да (1 failed, 1 warning in 3.37s) |
| Места и координаты из Wikidata | geo-label-unchecked | tests/knowledge/test_invalid_name_external.py::test_place_label_rejected | да (1 failed, 1 warning in 2.19s) |
| Места и координаты из Wikidata | geo-label-unchecked | tests/knowledge/test_invalid_name_external.py::test_place_created_iff_label_valid | да (1 failed, 1 warning in 2.45s) |

### Дефекты

- **Д1 (спецификация противоречива).** «Язык названий», инвариант: «Ни одно название с латинскими буквами (вне слов из римских цифр) не имеет языка `ru`». Пп. 3–5 того же требования для смешанного названия с перевесом кириллицы дают `ru`. Вход `create("concept", [("ru", "Кантq", "primary")])` и `"Иммануил Kant"` → по инварианту язык ≠ `ru`, получено `ru` (код следует пп. 1–5). Тест `test_no_latin_name_has_ru` красный. Нужно решение: либо инвариант «… если латиница не в большинстве», либо правило «латиница есть → не `ru`».
- **Д2 (код).** «Валидность», «Отказ»: `label` — «название целиком», где название — вход после `strip()` и NFC. Вход `create("concept", [("ru", "  EVERY ", "primary")])` → ожидалось `label="EVERY"`, получено `"  EVERY "`; `" "` → ожидалось `""`, получено `" "`; `" 20.1 "` → `" 20.1 "`; `" " + "Ж"*81 + " "` → обрезка считается по сырому входу (пробел в начале `label`). Причина отказа при этом верная. Тест `test_rejected_label_is_name_after_strip` красный (4 параметра). В test_rejection_invariant вход для этого очищается от краевых пробелов, чтобы остальные утверждения инварианта проверялись.

### Наблюдения (не дефекты по тексту спецификации)

- Элемент `entities`, на который не ссылается ни одно утверждение и у которого нет `dating`, сущность не создаёт. Сценарий «Латиница без русского написания» проверен с утверждением, упоминающим «Ding an sich».
- Датировка у типа без отношения `dating` в реестре (например, `concept`) отклоняется реестром: `knowledge.extraction.dropped` с `reason="тип субъекта concept недопустим для dating"` — причина не из списка `dating:<код>` и содержит текст. Спецификация этот случай не описывает; в стратегии `datings` типы ограничены субъектами `dating` реестра.
- Пустая подпись во внешних данных: манифест эпох отвергает запись (`ManifestError: нет названия ru`), импорт событий берёт другую подпись записи. Класс `empty` в инвариантах путей из Wikidata не участвует (проверен на `Entities.create`).
- `dating.check` фактически `check(text, quote, paragraph, paragraphs, *, is_person)`, в design.md — `(text, quote, paragraph_text, window_len, is_person)`.
- `naming.RULES` из контракта design.md в модуле нет (есть `load_rules()` с кэшем). «Стоп-список из данных» проверен подменой файла данных через `load_rules`.
- Тест «Ручное создание» вызывает `Filling.accept_core_report` напрямую: HTTP-маршрута принятия ядра нет (design.md: «Отдельного API ручного создания сущности сейчас нет»).

### Не покрыто / непроверяемое

- «Модель пишет по-русски», А1 на новых данных — только контракт: литерал «извлекай годы, если они названы» в системном тексте шаблона, `json_schema` (`entities`, `required`), `language` в данных запроса. Литералы правил языка и валидности в промпте отдельно не сверялись (формулировки в спецификации не заданы). Фактический А1 — замер Lead'а.
- «Ответ без `entities` как прежде» — плюс прежние `tests/knowledge/test_filling.py` без правки ожиданий: 30 passed.
- Сценарий «Язык по письменности на любом пути»: миграция не проверена (её путь — `migrate-ontology-quality`).
- Полный `pytest` не запускался (1 ГБ RAM), только файлы выше по одному.

### Перепроверка после О15 — 2026-11-25 (тестировщик, коммит разработчика c76007a)

- Д1 закрыт правкой spec: инвариант «латиницы (вне римских чисел) не меньше кириллицы — не `ru`; перевес кириллицы — `ru`». `test_no_latin_name_has_ru` приведён к новой формулировке, параметры с ожиданием: «Locke» → не ru, «Kant-Кант» (4:4) → не ru, «Kantt-Кант» → не ru, «Кантq» → ru, «Иммануил Kant» → ru, «Людовик XIV» → ru, «XIV» → не ru (букв вне римских нет). 7 passed.
- Д2 закрыт в коде: `test_rejected_label_is_name_after_strip` (4 параметра) passed без правки.
- `dating:type`: новый тест `test_entity_dating_extraction.py::test_dating_of_type_not_allowed` — датировка понятия «Субстанция» во фрагменте: сущность и связь `opposed_to` записаны, датировки и `primary.dates` нет, ровно одно `knowledge.extraction.dropped` с `reason="dating:type"` и `run_id`, сторожевой токен не утёк. Passed. Мутация `dating-type-unchecked` (проверка типа до пп. 1–6 убрана, отказ — текстом реестра): упал (1 failed, 4.26 s), worktree на 3aa55a9.
- Стратегия `stopwords_perturbed`: если разделитель « - » вывел стоп-слово за предел типа, ожидание — `sentence` (порядок правил spec); раньше такой вход был бы ложно помечен `stopword`.
- Прогоны: `test_entity_naming` 35 passed (68.6 s), `test_entity_dating_extraction` 14 passed (57.7 s). Наблюдение про причину текстом реестра у датировки понятия (раздел «Наблюдения» выше) снято: теперь код.

## Тестировщик — перепроверка после О17/О18 (2026-11-25, тесты на ea6321d)

- Точное множество кодов `knowledge.extraction.dropped.reason` (`strategies.DROPPED_CODES`: `dating:{paragraph,quote,unparsed,not_in_quote,era,single_year,type,unresolved}`, `entity:{type,no_type,ambiguous,empty,number,sentence,not_a_name,stopword}`) — `assert_dropped_codes` в property `test_only_registry_types_for_any_items`, `test_normalization_and_language_for_any_items`, `test_dating_invariant`, `test_person_quality_invariant`, `test_person_rule_any_input`.
- Точные значения в сценариях: «Номер раздела» → `["entity:number"]`, «Роль вместо имени» → `["entity:not_a_name"]`, «Написания нашли разные сущности» и `test_ambiguous_goes_to_review` → `["entity:ambiguous"]`.
- Новый `test_dating_of_unresolved_entity` (инвариант entity-dating «Извлечение дат», О18): неоднозначный «Бэкон» в утверждении и датировке + отклонённый «children» с датировкой → один `ambiguous_link`, причины `{entity:ambiguous, dating:unresolved ×2}`, новых утверждений нет, сторожевой токен в журнале не встречается.

Сырые прогоны (по одному файлу): test_entity_naming 35 passed in 28.02s · test_extraction_entities 9 passed in 23.62s · test_entity_dating_extraction 15 passed in 34.87s · test_person_quality 22 passed in 159.27s · test_entity_merge 13 passed in 89.64s · test_mutation_coverage 3 passed · check_traceability 410/410.

Мутации (отдельный worktree на ea6321d):

| Требование | Мутация | Ожидаемый тест | Упал |
|---|---|---|---|
| Валидность названий сущностей | dropped-reason-text | test_entity_naming::test_section_number, ::test_role_instead_of_name, test_person_quality::test_person_quality_invariant | да ×3 (на 2cc4f44) |
| Язык названий сущностей | ambiguous-reason-text | test_entity_naming::test_spellings_found_different_entities, test_extraction_entities::test_ambiguous_goes_to_review, test_entity_dating_extraction::test_dating_of_unresolved_entity | да ×3 |
| Извлечение дат | unresolved-reresolved | test_entity_dating_extraction::test_dating_of_unresolved_entity | да |
| Извлечение дат | unresolved-inner-reason | test_entity_dating_extraction::test_dating_of_unresolved_entity | да |

Дефектов нет.

## Судья — 2026-11-25, коммит 63aabff

Новый субагент, без истории разработки. Прогоны — по одному файлу (1 ГБ RAM), мутации — в отдельном `git worktree` на 63aabff (PYTHONPATH на worktree), worktree удалён, `git diff` по продуктовому коду пуст.

| Требование | Сценарии / инвариант | Журнал тестировщика | Мой прогон | Вывод системы (мой проход, настоящий `Filling.extract_version`, фейковый провайдер) | Итог |
|---|---|---|---|---|---|
| entity-naming «Язык названий сущностей» | 7 сценариев + инвариант; маркеры есть у всех | 35 passed; мутации lang-given, rename-creates упали | test_entity_naming 35 passed; своя мутация M1 поймана | «Plato» (en) → тот же `e_…`, основное `ru` «Платон», вариант `en`; `knowledge.entity.renamed {entity_id, lang: ru, previous_lang: en}`; справочник `q=Платон` → тот же id, `label="Платон"` | подтверждено |
| entity-naming «Валидность названий сущностей» | 12 сценариев + инвариант | мутации number-regex, patterns-case, stopword-before-person, label-no-trim, dropped-reason-text упали | 35 passed; повторил stopword-before-person — 3/3 упали; своя мутация M3 поймана только параметризованным тестом (см. ниже) | `rejected {type: concept, label: "20.1", reason: number}` + `dropped {reason: entity:number}`; `rejected {person, "blind mathematician", not_a_name}` + `dropped entity:not_a_name` | подтверждено сценариями; property — с замечанием 3 |
| entity-dating «Извлечение дат» | 11 сценариев + инвариант + `dating:type`, `dating:unresolved` | 15 passed; мутации упали | test_entity_dating_extraction 15 passed; повторил numbers-substring — 3/3; своя M2 поймана | Платон «427–347 до н. э.» → `lifespan`, `span=(−426, −346)`; Кант с цитатой без годов → `dropped dating:not_in_quote`, персона создана | подтверждено |
| ontology-extraction «Структурированный вывод по реестру» | 4 сценария + инвариант | 9 passed | test_extraction_entities 9 passed | элемент `deity` без `passed_gateway` отсекается уже шлюзом (502) — серверная проверка доказана тестом через `passed_gateway` | подтверждено |
| ontology-extraction «Нормализация сущностей» | 3 сценария + инвариант | 9 passed | 9 passed | привязка «Платон» к «Plato» без новой персоны | подтверждено |
| epochs / epoch-context / geo-timeline (MODIFIED) | по 1 новому сценарию + инвариант | 6 passed | test_invalid_name_external 6 passed; повторил geo-label-unchecked — 2/2 | — (только тестовый стенд) | подтверждено |

Прочие прогоны: test_filling 30, test_wikidata 52, test_geo_enrich 37, test_epoch_dates 66, test_invalid_name_paths_unit 4, test_naming_unit 68, test_entity_items_unit 12, test_extraction_codes_unit 10, test_naming_entities_unit 7, test_epoch_context_import 16, test_mutation_coverage 3 — все passed. `mutation_check.py --coverage improve-extraction-naming` — мутации у всех 8 требований. `lint-imports` — 3 kept. `check_traceability.py` — 410 из 410. `ruff format --check` по 27 файлам изменения — чисто. **`ruff check` по файлам изменения — 1 ошибка** (замечание 1). Полный pytest не запускался (ограничение машины) — не проверено.

Свои мутации (нет в списке):
- M1 `naming.py:160` — греческий дополнительный блок U+1F00–1FFF не считается греческим → упали `test_lang_for_any_text`, `test_language_invariant_create_and_add_name`.
- M2 `dating.py:39` — «до нашей эры» в цитате не распознаётся как эра → упали `test_dating_invariant`, `test_dating_check_any_input`.
- M3 `naming.py:272` — `reject` пишет `label` без `strip()`/NFC (откат Д2) → упали 4 параметра `test_rejected_label_is_name_after_strip`; **property `test_rejection_invariant` и `test_check_name_any_input` прошли**.

Файлы Lead'а: в `filling.py` — точки вызова (`EntityItems`, `language`, цикл датировок, `accept_core_report`, перехват `InvalidName`, `entity_types()`), плюс схема `_entities_schema` (данные схемы) и переход `import_wikidata` на `simple_time` (относится к `add-wikidata-life-dates`); в `prompts/__init__.py` — текст `ontology.extract` и поле `language` (`ontology.translate_names` — `migrate-ontology-quality`). Логики правил в них нет.

Подгонка: оракул `strategies.py` не импортирует `naming`/`dating`/`dates`; ожидания строятся генератором; `@example` на границы есть. Найдено сужение (замечание 3), признаков правки ожиданий под вывод нет.

Замечания:
1. **`ruff check`** падает на файле изменения: `tests/knowledge/test_entity_items_unit.py:97:36 RUF043` (`match="^dating:type$"` без raw-строки; файл из c76007a). CI `checks` (`ruff check .`) будет красным.
2. **tasks.md неполон** (вне «Требует Lead'а»): 1.2 и 4.1 не отмечены. По progress.md ревью плана пройдено (круг 2), а ревью кода (e843975) дало «к судье после коммита О17»; повторной вычитки О17/О18 (ea6321d) ревьювером нет.
3. **Сужение property-теста**: `test_rejection_invariant` по-прежнему делает `raw = raw.strip()` с комментарием про дефект Д2, хотя Д2 закрыт. Из-за этого инвариант «`label` по правилу обрезки» на пути записи не проверяется для любых входов: мутация M3 проходит property-тесты.

Непроверяемо здесь: поведение настоящей модели (язык названий, датировки), оплачиваемая проба 5.2, А1–А8 на стенде — за Lead'ом.

Вердикт: **не принято** — вернуть:
- разработчику: замечание 1 (raw-строка в `match=`; `ruff check` по файлам изменения чисто);
- тестировщику: замечание 3 (убрать `strip()` входа в `test_rejection_invariant`, чтобы инвариант проверял `label` после `strip()`/NFC на любых входах; добавить мутацию M3 в `mutations.yaml` с ожиданием падения property-теста);
- ревьюверу: замечание 2 (вычитка О17/О18, отметить 4.1; ведущему — отметить 1.2).

## Тестировщик — замечание 3 судьи (2026-11-25)

- `test_rejection_invariant`: `raw = raw.strip()` убран, вход сырой; `label` события сверяется с оракулом `expected_label(raw)` (strip + NFC + обрезка). Добавлены `@example` с краевыми пробелами и табуляцией на путях `create`, `add_name`, `set_primary_name`.
- Мутация судьи M3 добавлена как `reject-label-raw` (`naming.reject` без `strip()`/NFC).

Отдельный worktree:

    test_entity_naming.py  35 passed in 145.30s
    | Валидность названий сущностей | reject-label-raw | test_entity_naming.py::test_rejection_invariant | да (1 failed) |
    | Валидность названий сущностей | reject-label-raw | test_entity_naming.py::test_rejected_label_is_name_after_strip | да (1 failed) |

## Судья — повторно, 2026-11-25, коммит 446bbf4

Новый субагент, без истории разработки. Тесты — по одному файлу (1 ГБ RAM). Мутации и проба системы — в отдельном `git worktree` на 4649bea (PYTHONPATH на worktree). Worktree удалён, `git diff -- src` пуст. Продуктовый код с 63aabff не менялся, кроме `integrity.py` (это `migrate-ontology-quality`).

**Замечания прежнего судьи:**
1. RUF043 закрыто (6a29b22): `ruff check` по 27 файлам изменения чисто.
2. Закрыто: пункты 1.2 и 4.1 отмечены, круг 2 ревью кода О17/О18 записан в progress.md.
3. Закрыто: в `test_rejection_invariant` вход сырой, есть `@example` с краевыми пробелами. Мутация `reject-label-raw` в моём прогоне валит оба ожидаемых теста.

| Требование | Журнал тестировщика | Мой прогон | Вывод системы (мой фрагмент, настоящий `Filling.extract_version`, фейковая модель) | Итог |
|---|---|---|---|---|
| entity-naming «Язык названий сущностей» | 35 passed; lang-given, rename-creates | test_entity_naming 35 passed in 40.7s | «Юм» при существующей «David Hume» (en) → тот же `e_39abcfaf`: основное `ru` «Юм», вариант `en`; `knowledge.entity.renamed {entity_id, lang: ru, previous_lang: en}`; справочник `q=Юм` → тот же id, `label="Юм"`; «Mill» → `en` | **не подтверждено**: своя мутация J1 не поймана |
| entity-naming «Валидность названий сущностей» | 35 passed; 5 мутаций + reject-label-raw | 35 passed; reject-label-raw 2/2; своя J2 поймана | `rejected {concept, "§ 3.1", number}` + `dropped entity:number`; `rejected {person, "teacher of Plato", not_a_name}` + `dropped entity:not_a_name` | подтверждено |
| entity-dating «Извлечение дат» | 15 passed; 6 мутаций | test_entity_dating_extraction 15 passed in 28.7s; roman-unchecked 3/3; своя J5 поймана | Локк «1632–1704» → `lifespan`, (1632, 1704) `year`; произведение «1690» → `dating`; Юм «1776–1711» → `dropped dating:unparsed`, персона и утверждение записаны | **не подтверждено**: своя мутация J3 не поймана |
| ontology-extraction «Структурированный вывод по реестру» | 9 passed | test_extraction_entities 9 passed; своя J4 поймана | — | подтверждено |
| ontology-extraction «Нормализация сущностей» | 9 passed | 9 passed; spellings-without-en 2/2 | «Юм» привязан к «David Hume» по `en`, новой персоны нет | подтверждено |
| epochs / epoch-context / geo-timeline (MODIFIED) | 6 passed | test_invalid_name_external 6 passed | — (тестовый стенд) | подтверждено |

Прочие прогоны (все passed): test_entity_items_unit 12, test_filling 30 (ожидания прежние), test_invalid_name_paths_unit 4, test_extraction_codes_unit 10, test_mutation_coverage 3. `mutation_check.py --coverage improve-extraction-naming`: мутации есть у всех 8 требований. `ruff check` и `ruff format --check` по файлам изменения чисто. `lint-imports`: 3 kept, 0 broken. `check_traceability.py`: 410 из 410. Полный pytest не запускался: ограничение машины, не проверено.

Мутации из `mutations.yaml`, повторены: reject-label-raw, roman-unchecked, spellings-without-en. Все ожидаемые тесты упали.

Свои мутации:
- **J1 (язык).** `naming._script_counts`: `_ROMAN_WORD.match(word.upper())` — слова из букв IVXLCDM в любом регистре считаются римскими. В spec: «только заглавные». Под мутацией `lang_for("Mild") == "und"`, а должно быть `en`; «Mill» тоже теряет язык. Результат: **test_entity_naming 35 passed, мутация не поймана**. Причина: `scripts_mix` строит латинские слова как «заглавная + строчные» из всего алфавита и не делает целенаправленно слова из букв римских цифр не в верхнем регистре («Mill», «Civil», «Lid», «Xiv»). Таких `@example` тоже нет.
- **J2 (валидность).** `naming.normalize` без `ё` → `е`. Упали `test_check_name_any_input` и `test_rejection_invariant`.
- **J3 (даты).** `dating._format`: убрана проверка Г1 ≤ Г2 у интервала нашей эры. Под мутацией «1804–1724» записывается как (1724, 1804) `year`, а должно быть `dating:unparsed`: формата нет в таблице. Результат: **test_entity_dating_extraction 15 passed, мутация не поймана**. Причина: `datings` не порождает обратный интервал без эры, `@example` на него нет.
- **J4 (коды событий).** `EntityItems.index`: тип вне реестра даёт `entity:no_type` вместо `entity:type`. Упали `test_entity_type_outside_registry` и `test_only_registry_types_for_any_items`.
- **J5 (даты).** `single_year` не применяется к веку у персоны. Упали `test_dating_invariant` и `test_dating_check_any_input`.

Файлы Lead'а: `filling.py` и `prompts/__init__.py` с 63aabff не менялись. В `filling.py` по диффу только точки вызова (`EntityItems`, `language`, цикл `date_item`, `accept_core_report`, перехват `InvalidName`, `entity_types()`) и данные схемы. Логики правил там нет.

Подгонка: не найдена. Оракул стратегий не импортирует `naming`/`dating`/`dates`, ожидания не правились под вывод. J1 и J3 — пробелы в области входов генераторов, а не подгонка. Код на этих входах работает верно, это видно по выводу системы.

Вердикт: **не принято** — вернуть тестировщику:
- J1: в `scripts_mix` добавить латинские слова из букв IVXLCDM не в верхнем регистре («Mill», «Civil», «Lid», «Xiv»), их буквы идут в счёт латиницы. Добавить `@example` в `test_lang_for_any_text` и `test_language_invariant_create_and_add_name`. Мутацию J1 записать в `mutations.yaml` с ожиданием падения property-тестов языка.
- J3: в `datings` добавить обратный интервал нашей эры (Г1 > Г2, в том числе «ок.») с ожиданием `dating:unparsed`. Добавить `@example` в `test_dating_check_any_input` и `test_dating_invariant`. Мутацию J3 записать в `mutations.yaml`.

Разработчику, ревьюверу и Lead'у возвратов нет.

## Тестировщик — возврат повторного судьи (J1, J3), 2026-11-25

- **J1.** В `scripts_mix` новый вид слова `roman_letters`: буквы IVXLCDM не целиком заглавными («Mill», «civil», «Xiv»), их буквы считаются латиницей. Добавлены `@example`: «Mill» и «Civil Xiv» → `en` в `test_lang_for_any_text`; «Mill»/«Lid» в `test_language_invariant_create_and_add_name`.
- **J3.** В `datings` (класс `unparsed`) добавлен обратный интервал нашей эры Г1 > Г2, с «ок.» и «около» и без них, → `dating:unparsed`. В `EXAMPLES` добавлены «1804–1724» (персона) и «ок. 1690-1689» (произведение), они идут в `test_dating_invariant` и `test_dating_check_any_input`.
- Базовый прогон: 4 passed in 25.94s.

| Требование | Мутация | Ожидаемый тест | Упал |
|---|---|---|---|
| Язык названий сущностей | roman-any-case (J1) | test_lang_for_any_text, test_language_invariant_create_and_add_name | да ×2 |
| Извлечение дат | reverse-interval-accepted (J3) | test_dating_check_any_input, test_dating_invariant | да ×2 |

## Тестировщик — аудит пунктов (О21)

Систематический аудит покрытия по решению ведущего О21: для каждого нормативного пункта дельт (SHALL/MUST, строка таблицы, шаг порядка проверок, ветвь правила) строка «пункт → вид генератора → @example → мутация». Строк в таблице: 221. Мутации аудита — отдельные патчи от HEAD в `tests/mutations/improve-extraction-naming/`, прогон каждой — в отдельном `git worktree`; всего мутаций в каталоге после аудита — 181 (из них новых 160, все падают).

**Пробелы, найденные аудитом, и чем закрыты.**
- Генератор (`tests/knowledge/strategies.py`): `scripts_mix` — вид `digits` и граничные буквы диапазонов письменностей (ԯ, ῳ, Ա); `person_edge_names` (частица в смешанном регистре, склейка с строчным соседом, склейка и шаблон «the … of …» у типа не «персона»); `rule_order` (empty/number раньше sentence, sentence раньше not_a_name); `datings` — цели `m_*` (две несработавшие проверки сразу, причина — первая по порядку) и новые неразбираемые тексты (интервал веков, «XXII в.», «IIII в.»). Оракул стратегий не импортирует `naming`, `dating`, `dates`, `dedupe`.
- Явные @example: пример на каждую строку таблицы форматов дат (Г, Г1–Г2 с тире и пробелами, «ок. Г» с четырьмя маркерами и регистром, «ок. Г1–Г2», эра, век, век до н. э.), пары порядка проверок, правило поиска цитаты (регистр, ё/е, пробелы), одиночный год/век/«ок.» у персоны; примеры языка по письменности (границы диапазонов, цифры, равенство, таблица языков), примеры правил названий (все ветви правила 4, порядок правил, пределы типов `idea_event`/`phenomenon`/`place`).
- Новые тесты: `test_rules_are_data` (пределы, частицы, шаблоны, союзы, типы персон, `exempt` из данных), `test_signs_counted_after_nfc`, `test_primary_choice_by_item` (пробел: основное при нерусском `ru` — мутация `ru-primary-not-russian` выжила), `test_core_rejection_reasons` (выжила `core-reason-wrong`), `test_prompt_language_and_rules`, `test_new_entity_without_type_dropped_by_code` (выжила `no-type-creates-entity`: код `entity:no_type` не проверялся), `required` схемы (выжила `schema-dating-required-short`), `test_added_from_manifest_gets_external_id` (выжила `epoch-added-without-external`), `test_value_without_id_is_bad_value` (выжила `geo-bad-value-as-bad-qid`), `test_dry_run_with_existing_place_writes_nothing` (выжила `geo-dry-run-writes`: сухой прогон без существующего места ничего не доказывал).
- Мутации, признанные неинформативными и снятые: `epoch-start-after-end-accepted` — «начало позже конца → no_dates» есть только в коде, в спецификации этого нет; `uncertain-type-unfitted` заменена на `fit-no-parent` (первая ломала ветвь `proposed_type`, которой нет в дельте).

**Отрицательные пункты без ветки кода.** «Связи влияния из Wikidata не импортируются» (эпохи), «стимулировало, механизм, влияние не записываются» (контекст), «не создаёт новых персон и событий» (места), «не вызывается из пути читателя»: ломать нечего, мутацию построить нельзя; пункты проверены тестами (`test_influences_not_imported`, `test_never_writes_stimulated_mechanism_influence`, `test_no_new_people_or_events`, `test_not_from_reader_path`), в таблице помечены.
Обозначения файлов тестов: NM = `tests/knowledge/test_entity_naming.py`, ED = `test_entity_dating_extraction.py`, EX = `test_extraction_entities.py`, EPD = `test_epoch_dates.py`, CTX = `test_epoch_context_import.py`, GEO = `test_geo_enrich.py`, INV = `test_invalid_name_external.py`, NU = `test_naming_unit.py`. Генераторы — `tests/knowledge/strategies.py` (S.) или стенд-«мир» теста там, где вход задан сценарием спецификации и property-генератора нет (так отмечено). Мутации — `tests/mutations/improve-extraction-naming/<id>.patch`.

### entity-naming / Язык названий сущностей

| Пункт | Вид генератора | @example | Мутация |
|---|---|---|---|
| Модель возвращает написания ru/en/original (схема) | S.fragment_items (present ⊆ {ru,en,original}) | EX::test_schema_with_entities_and_dating (сценарий), EX::test_normalization_and_language_for_any_items @example Платон+original | schema-no-original |
| Язык ставится при каждой записи названия: `create` | S.scripts_mix | NM::test_language_invariant_create_and_add_name @example Kant-Кант/Locke | create-lang-given, lang-given |
| Язык ставится при каждой записи названия: `add_name` | S.scripts_mix (extra) | NM::test_language_invariant_create_and_add_name @example Locke/Ἀριστοτέλης | add-name-lang-given |
| Все пути: источник, ядро, Wikidata-место, Людовик XIV, греческое, смесь | сценарный стенд (шесть названий из спеки) | NM::test_language_by_script_on_every_path | lang-given |
| п. 1: слово — по пробельным, знаки по краям отбрасываются | S.scripts_mix (left/right marks `(«"` / `)».,"`) | NM::test_lang_for_any_text @example «(XIV) Ки», «Людовик XIV.» | words-edge-kept |
| п. 1: римское слово — только заглавные IVXLCDM | S.scripts_mix kind roman / roman_letters | NM::test_lang_for_any_text @example Mill, Civil Xiv | roman-any-case |
| п. 2: учитываются только буквы `L*` (цифры не считаются) | S.scripts_mix kind digits | NM::test_lang_for_any_text @example «Kant 1781», «Ки 1781 1724» | digits-as-letters |
| п. 2: кириллица U+0400–U+052F (граница ԯ) | S.scripts_mix cyrillic (+ԁԯ) | NM::test_lang_for_any_text @example «Ԯԯ» | cyrillic-range-short |
| п. 2: латиница — имя символа начинается с LATIN (не только ASCII) | S.scripts_mix latin (äöüéèçñ) | NM::test_lang_for_any_text @example Königsberg | latin-ascii-only |
| п. 2: греческая U+0370–U+03FF и U+1F00–U+1FFF | S.scripts_mix greek (+ͱῳ) | NM::test_lang_for_any_text @example «Ͱͱ», «ῳῳ», Ἀριστοτέλης | greek-extended-dropped |
| п. 2: прочие буквы | S.scripts_mix other (+Աա) | NM::test_lang_for_any_text @example «汉字», «Աբգ» | other-script-as-latin |
| п. 3: письменность — строго больше всего букв; равенство → нет | S.scripts_mix mixed | NM::test_lang_for_any_text @example Kant-Кант | tie-first-wins |
| п. 3: без букв письменности нет | S.scripts_mix (только roman/digits слова) | NM::test_lang_for_any_text @example XIV, «1781», «!!!» | given-kept-without-script |
| п. 4: кириллица→ru, латиница→en, греческая→el, прочая/нет→und | S.scripts_mix (все письменности) | NM::test_lang_for_any_text @example Platon, «汉字», Ἀριστοτέλης | und-as-en, greek-el-as-grc, latin-en-as-la |
| п. 5: переданный язык сохраняется только при совпадении письменности | S.scripts_mix GIVEN_LANGS | NM::test_lang_for_any_text @example Ding an sich/de, Аристотель/grc | lang-given |
| п. 5: таблица языков ru; en,de,fr,la,it; el,grc | S.scripts_mix GIVEN_LANGS | NM::test_lang_for_any_text @example la, fr, it, zz, grc, el | given-lang-table-short |
| «Русское название»: есть кириллица, нет латиницы (без римских слов) | S.scripts_mix | NM::test_no_latin_name_has_ru (parametrize) (фактически роняет: test_primary_choice_by_item) | is-russian-ignores-latin |
| Основное: `ru`, если русское и прошло проверку | S.fragment_items | EX::test_normalization_and_language_for_any_items; NU::test_names_for_primary_and_variants (фактически роняет: test_names_for_rejected_spelling_not_written, test_primary_choice_by_item) | ru-primary-unchecked, ru-primary-not-russian |
| Иначе основное — `name` | S.fragment_items (name_key=en) | EX::test_answer_without_entities, NM::test_latin_without_russian (фактически роняет: test_primary_choice_by_item) | ru-primary-not-russian |
| Прочие написания — варианты | S.fragment_items | EX::test_normalization_and_language_for_any_items @example Платон+Πλάτων (фактически роняет: test_names_for_primary_and_variants, test_russian_textbook) | variants-dropped |
| Не прошедшее проверку не пишется ни основным, ни вариантом | сценарный (ru «поэт») + NU::test_names_for_rejected_spelling_not_written | NM::test_rejected_russian_spelling (фактически роняет: test_names_for_rejected_spelling_not_written) | rejected-spelling-variant |
| Английская сущность: ru становится основным, id/утверждения/упоминания сохраняются, новой нет | S.fragment_items (existing=en) | EX::test_normalization_and_language_for_any_items @example Локк/LOCKE | rename-creates |
| Прежнее основное → вариант с языком по п. 5 | S.fragment_items (existing=en) | NM::test_existing_english_entity_gets_russian_primary | rename-keeps-old-primary |
| `knowledge.entity.renamed` ровно `entity_id, lang, previous_lang` | S.fragment_items | EX::test_normalization_and_language_for_any_items (сверка словаря) | renamed-previous-lang-wrong, renamed-extra-field |
| Разные кандидаты: новая не создаётся | сценарный (Substance/Субстанция) | NM::test_spellings_found_different_entities | ambiguous-creates-new |
| …привязка уходит в `ambiguous_link`, утверждение отброшено | сценарный | NM::test_spellings_found_different_entities | ambiguous-no-review-item |
| …`knowledge.extraction.ambiguous` с `candidates=2` | сценарный | NM::test_spellings_found_different_entities | ambiguous-candidates-count |
| …`dropped` с `reason="entity:ambiguous"` | сценарный | NM::test_spellings_found_different_entities | ambiguous-reason-text |
| Инвариант: ≤ 1 основное на язык | S.scripts_mix + S.fragment_items | NM::test_language_invariant_create_and_add_name; EX::…any_items (primaries) (фактически роняет: test_existing_english_entity_gets_russian_primary, test_set_primary_name_keeps_id, test_set_primary_name_promotes_variant) | rename-keeps-old-primary |
| Инвариант: число сущностей = числу `created` | S.scripts_mix | NM::test_language_invariant_create_and_add_name | created-event-doubled |
| Инвариант: нет `created` для элемента с найденным кандидатом по любому написанию | S.fragment_items (existing ∈ ru/en/original) | EX::test_normalization_and_language_for_any_items | spellings-without-en, spellings-without-ru, spellings-without-original |
| Сценарий «Русский учебник» | сценарный | NM::test_russian_textbook | variants-dropped |
| Сценарий «Латиница без русского» | сценарный | NM::test_latin_without_russian (фактически роняет: test_lang_for_any_text, test_language_by_script_on_every_path, test_language_invariant_create_and_add_name) | lang-given |

### entity-naming / Валидность названий сущностей

| Пункт | Вид генератора | @example | Мутация |
|---|---|---|---|
| Проверка при создании (`create`) любого источника | S.names_with_reason × path=create | NM::test_rejection_invariant @example (BOUNDARY_EXAMPLES) | create-unchecked |
| Проверка при смене основного (`set_primary_name`) | S.names_with_reason × path=set_primary_name | NM::test_rejection_invariant @example term «\t» | set-primary-unchecked |
| Проверка при `add_name` основным | S.names_with_reason × path=add_name | NM::test_rejection_invariant @example «  EVERY » | add-name-unchecked |
| Источники библиотеки (`source`) не проверяются | S.names_with_reason (REGISTRY_TYPES) | NM::test_rejection_invariant @example («source», «20.1») (фактически роняет: test_check_name, test_check_name_any_input, test_rules_are_data) | rule-exempt-ignored |
| «Название» = strip + NFC | S.numbers/S.stopwords_perturbed (пробелы, NFD) | NM::test_rejected_label_is_name_after_strip; NM::test_signs_counted_after_nfc | rule-no-strip, rule-no-nfc |
| Текст названия SHALL храниться в форме strip+NFC на любом пути записи (О22): create, add_name, set_primary_name, извлечение | NM.raw_names (S.scripts_mix или пул с ё/й/диакритикой; края: пробел, таб, перевод строки, NBSP, EM SPACE; NFC/NFD) | NM::test_stored_form_strip_nfc @example « Декарт »/«\tLocke\n», NFD «Ἀριστοτέλης»/«Renée Descartes»/«Йозеф Шумпетер»+EM SPACE, «Kant-Кант »; NM::test_stored_form_via_extraction (3 параметра: края, NFD «Пётр», таб+NFD+EM SPACE) | stored-raw-create, stored-raw-add-name, stored-raw-set-primary (упали: 4, 1, 1 теста) |
| «Нормализованное название»: NFC, нижний, ё→е, не-буквы→пробел | S.stopwords_perturbed (регистр, ё, знаки, NFD) | NM::test_check_name_any_input @example «Тот, кто  чувствует», «Тот кто чувствуёт» | rule-stopword-raw-compare |
| Знаки — кодовые точки, слова — `split()` | S.at_limit, S.long_phrases | NM::test_check_name_any_input @example «Один\tДва\nТри…», NFD×80/81 | rule-no-nfc, rule-limit-ge |
| Правило 1 `empty` | S.blank | NM::test_check_name_any_input @example « », «—», «» | rule-empty-as-number |
| Правило 2 `number` («§ 20.1», «(3.2)», «20,1») | S.numbers | NM::…@example «§ 20.1», «(3.2)», «20,1», «23.4.3» (фактически роняет: test_check_name_any_input, test_numbers_with_marks, test_rejection_invariant) | number-regex |
| Правило 3 `sentence`: слов > предела | S.long_phrases (слова) | NM::…@example 7 слов, 13 слов work (фактически роняет: test_check_name, test_check_name_any_input, test_limit_boundaries) | rule-sentence-words-unchecked |
| Правило 3: знаков > предела | S.long_phrases (знаки) | NM::…@example 81, 161 знак (фактически роняет: test_check_name, test_check_name_any_input, test_limit_boundaries) | rule-sentence-chars-unchecked |
| Правило 3: «>» а не «≥» (ровно предел — норма) | S.at_limit | NM::…@example 6 слов, 80 знаков, 12 слов, 160 знаков (фактически роняет: test_check_name, test_check_name_any_input, test_limit_boundaries) | rule-limit-ge |
| Правило 3: пределы 12/160 для work, event, idea_event, phenomenon | S.long_phrases/S.at_limit по LONG_LIMIT_TYPES | NM::…@example work/event/idea_event/phenomenon, place 7 слов (фактически роняет: test_check_name, test_check_name_any_input, test_limit_boundaries) | rule-limits-default-only |
| Правило 4a `not_a_name`: первая буква строчная и нет частицы | S.not_names kind lower | NM::…@example «кант», «(кант)», «blind mathematician» (фактически роняет: test_check_name, test_check_name_any_input, test_manual_core) | rule-lowercase-first-unchecked |
| 4a: частица целиком (de, d, van, von, ibn, al, де, …) | S.proper_names (particle) | NM::…@example «де Бройль», «ибн Сина», «ван Гог», «von Neumann» (фактически роняет: test_rules_are_data) | rules-particles-hardcoded |
| 4a: частица перед `-`, `'`, `’` | S.proper_names (joiner) | NM::…@example «аль-Фараби», «д’Аламбер», «d'Alembert», «al-Kindi» (фактически роняет: test_check_name, test_check_name_any_input, test_particles_and_roman) | rule-particle-apostrophe-ignored |
| 4a: частица без учёта регистра | S.person_edge_names particle_swapcase | NM::…@example «dE Broglie», «дЕ Бройль» (фактически роняет: test_check_name_any_input) | rule-particle-case-sensitive |
| 4b: шаблоны `author of `, `the author `, `the … of` без учёта регистра | S.not_names kind pattern | NM::…@example «The author of the Treatise», «THE TEACHER OF Plato», «Author Of Leviathan» (фактически роняет: test_check_name, test_check_name_any_input, test_description_with_capital) | patterns-case, rule-patterns-dropped |
| 4c: склейка and/и/& между двумя заглавными | S.not_names kind glue | NM::…@example «Кант и Юм», «Kepler and Des Cartes», «Kepler & Des Cartes» (фактически роняет: test_check_name, test_check_name_any_input, test_glued_names) | rule-glue-dropped |
| 4c: только заглавные соседи («Кант и юм» — норма) | S.person_edge_names glue_lower_right | NM::…@example «Кант и юм», «Kant and hume» (фактически роняет: test_check_name_any_input) | rule-glue-lower-neighbors |
| 4: только для типа «персона» | S.person_edge_names glue_nonperson, pattern_nonperson | NM::…@example («concept», «Кант и Юм»), («work», …), («doctrine», «the teacher of Plato») (фактически роняет: test_check_name, test_check_name_any_input, test_rules_are_data) | rule-not-a-name-all-types, rules-person-types-hardcoded |
| Правило 5 `stopword` | S.stopwords_perturbed | NM::…@example «  EVERY », «Тот, кто  чувствует», «тот кто чувствуёт», «your lordship» (фактически роняет: test_check_name_any_input, test_rejection_invariant, test_role_instead_of_name) | stopword-before-person |
| Порядок: первое подходящее; `not_a_name` раньше `stopword` | S.stopwords_perturbed (person) | NM::test_role_instead_of_name; @example «blind mathematician» | stopword-before-person |
| Порядок: `empty`/`number` раньше `sentence` | S.rule_order number_long, empty_long | NM::…@example «1 2 3 4 5 6 7», «- - - - - - -» (фактически роняет: test_check_name_any_input) | rule-sentence-before-number |
| Порядок: `sentence` раньше `not_a_name` | S.rule_order person_long_lower | NM::…@example «a b c d e f g», «the author of An Inquiry…» (фактически роняет: test_check_name_any_input) | not-a-name-before-sentence (O2, О23: меняет местами именно эти два правила; прежняя ссылка на rule-sentence-before-number была неверной) |
| Правила — данные: пределы (слова, знаки) | параметры теста (правка yaml) | NM::test_rules_are_data (_limit, _limit_chars) | rules-limits-hardcoded |
| Правила — данные: частицы | то же | NM::test_rules_are_data (_particle) | rules-particles-hardcoded |
| Правила — данные: шаблоны | то же | NM::test_rules_are_data (_pattern) | rules-patterns-hardcoded |
| Правила — данные: союзы | то же | NM::test_rules_are_data (_conjunction) | rules-conjunctions-hardcoded |
| Правила — данные: типы персон и `exempt` | то же | NM::test_rules_are_data (_person_types, _exempt) | rules-person-types-hardcoded, rule-exempt-ignored |
| Правила — данные: стоп-список | то же | NM::test_stopword_list_from_data (сценарий «Стоп-список из данных») (фактически роняет: test_check_name_any_input, test_rejection_invariant, test_role_instead_of_name) | stopword-before-person |
| `rejected` ровно `type, label, reason` | S.names_with_reason | NM::test_rejection_invariant (сверка словаря полей) | rejected-extra-field |
| `label` ≤ 80 — целиком; иначе 79 + «…» | S.long_phrases | NM::test_limit_boundaries (81 знак), @example 81 | label-no-trim, label-cut-80 |
| `label` после strip/NFC | S.numbers (пробелы по краям) | NM::test_rejected_label_is_name_after_strip; @example « 20.1 » | reject-label-raw |
| Других текстов (цитат, абзацев) в событии нет | S.names_with_reason + токен в варианте | NM::test_rejection_invariant (`no_token`) | rejected-extra-field |
| Утверждение с отклонённой сущностью → `dropped` `entity:<причина>`, без названия | сценарный стенд (5 причин) | NM::test_section_number, test_role_instead_of_name, test_stopword_concept, test_empty_names, test_sentence_instead_of_term | dropped-reason-text |
| Ядро: отклонённый не создаётся, возвращается с причиной, остальные создаются | сценарный (your Lordship + Локк) | NM::test_manual_core | core-reject-aborts, core-reason-wrong |
| Инвариант: создана ⇔ нет причины; одно событие на отказ | S.names_with_reason (все виды) | NM::test_rejection_invariant, test_check_name_any_input | rule-empty-as-number, number-regex, label-no-trim |
| Сценарии «Номер», «Номер со знаками», «Предложение», «Описание с заглавной», «Роль», «Стоп-слово», «Пустое», «Склейка», «Границы», «Частица и римское», «Ручное», «Стоп-список из данных» | сценарные | NM::test_section_number … test_stopword_list_from_data (фактически роняет: test_check_name, test_check_name_any_input, test_description_with_capital) | number-regex, rule-sentence-chars-unchecked, patterns-case, stopword-before-person, rule-empty-as-number, rule-glue-dropped, label-no-trim, rule-particle-apostrophe-ignored, core-reject-aborts, rules-limits-hardcoded |

### entity-dating / Извлечение дат

| Пункт | Вид генератора | @example | Мутация |
|---|---|---|---|
| Поле датировки в схеме: text, paragraph, quote (обязательны) | сценарный стенд (схема) | EX::test_schema_with_entities_and_dating | schema-dating-required-short |
| Промпт: «извлекай годы, если они названы» | сценарный стенд | EX::test_schema_with_entities_and_dating, EX::test_prompt_language_and_rules | prompt-no-years-rule |
| Формат `Г` (1…2100, четыре границы = Г, `year`) | S.datings (form year; `_valid_dating`) | ED::test_dating_invariant @example «1781», «2100», «1» | year-max-2101, year-zero-allowed |
| Формат `Г1–Г2`, тире `–—-`, пробелы вокруг | S.datings (form interval; DASHES, space) | ED @example «1724 - 1804», «1724—1804» (фактически роняет: test_accepted, test_dating_check_any_input, test_dating_invariant) | dash-hyphen-only |
| `Г1 ≤ Г2` у интервала нашей эры | S.datings (unparsed, обратный интервал) | ED @example «1804–1724», «ок. 1690-1689» (фактически роняет: test_dating_check_any_input, test_dating_invariant) | reverse-interval-accepted |
| `ок. Г`: Г ± 10, `approx` | S.datings (form approx) | ED @example «ок. 1780» (фактически роняет: test_accepted, test_dating_check_any_input, test_dating_invariant) | approx-slack-year-wrong, approx-precision-year |
| Маркеры «около»: ок., около, c., circa, регистр | S.datings (APPROX, upper/capitalize) | ED @example «около 1780», «c. 1780», «circa 1780», «ОК. 1780» (фактически роняет: test_accepted, test_dating_check_any_input, test_dating_invariant) | approx-markers-short |
| `ок. Г1–Г2`: ± 5, `approx` | S.datings (form approx_interval) | ED @example «ок. 1739–1740», «ок. 430–420 до н.э.» (фактически роняет: test_dating_check_any_input, test_dating_invariant) | approx-slack-interval-wrong |
| Эра в конце текста: каждый год → 1 − год, границы упорядочены | S.datings (era=True; max,min) | ED @example «427–347 до н. э.», «ок. 470 до н. э.», «375 до н.э.» (фактически роняет: test_accepted, test_dating_check_any_input, test_dating_invariant) | era-text-spaced-only |
| Маркер эры: «до н. э.» и «до н.э.» | S.datings (ERA_TEXT) | ED @example «375 до н.э.», «ок. 430–420 до н.э.» (фактически роняет: test_accepted, test_dating_check_any_input, test_dating_invariant) | era-text-spaced-only |
| Эра в цитате также «до нашей эры» | S.datings (ERA_QUOTE) | ED @example «ок. 470 до н. э.» + цитата «до нашей эры» (фактически роняет: test_accepted, test_dating_check_any_input, test_dating_invariant) | era-quote-nashei-missing |
| `R в.`: (R−1)·100+1…R·100, `century`, R = I…XXI | S.datings (form century, CENTURIES) | ED @example «XVII в.», «XXI в.», «xvii в.» (фактически роняет: test_accepted, test_dating_check_any_input, test_dating_invariant) | century-bounds-off, century-precision-year, century-max-22 |
| `R в. до н. э.`: 1 − R·100 … 1 − ((R−1)·100+1) | S.datings (century, era=True) | ED @example «V в. до н. э.» (−499…−400, span −450) (фактически роняет: test_accepted, test_dating_check_any_input, test_dating_invariant) | century-bce-bounds-off |
| Не допускается: эра только у одной границы | S.datings UNPARSED («4 до н. э. – 65», «470 до н. э. – 399») | ED @example «4 до н. э. – 65» (фактически роняет: test_dating_check_any_input, test_dating_invariant, test_rejected) | era-one-boundary-accepted |
| Не допускается: интервал веков | S.datings UNPARSED («XVII–XVIII в.», «XVII - XVIII в. до н. э.», «XVII в. – XVIII в.») | ED @example те же (фактически роняет: test_dating_check_any_input, test_dating_invariant) | century-interval-accepted |
| Не допускается: месяцы и дни, слова вне таблицы | S.datings UNPARSED («12 мая 1724», «март 1724», «1724 г.», «в эпоху Просвещения») | ED @example те же (фактически роняет: test_dating_check_any_input, test_dating_invariant, test_rejected) | unparsed-lenient |
| Не допускается: год 0, год > 2100, знак «+», век > XXI | S.datings UNPARSED («0», «2101», «+1724», «XXII в.», «IIII в.») | ED @example «0», «2101», «+1724», «XXII в.» (фактически роняет: test_dating_check_any_input, test_dating_invariant, test_rejected) | year-zero-allowed, year-max-2101, century-max-22 |
| Проверка 1 `dating:paragraph` (0, n+1, отрицательные) | S.datings target paragraph | ED::test_paragraph_outside_fragment; @example 0, 5 из 4 (фактически роняет: test_dating_check_any_input, test_dating_invariant, test_rejected) | paragraph-bounds-off |
| Проверка 2 `dating:quote`; правило: пробелы, ё→е, регистр, подстрока | S.datings target quote; `_paragraph_with` | ED @example «кант  (1724–1804)»/«КАНТ…», «Кёнигсберг»/«кенигсберг» (фактически роняет: test_dating_check_any_input, test_dating_invariant, test_quote_rule_like_statements) | quote-case-sensitive, quote-yo-kept, quote-spaces-kept |
| Проверка 3 `dating:unparsed` | S.datings target unparsed | ED::test_unparsed; @example UNPARSED (фактически роняет: test_dating_check_any_input, test_dating_invariant, test_rejected) | unparsed-lenient |
| Проверка 4 `dating:not_in_quote`: числа по границам цифр | S.datings target not_in_quote (inside/other) | ED::test_number_inside_number, test_year_not_in_quote; @example «17245», «18041» | numbers-substring |
| Проверка 4: римский век — отдельным словом | S.datings (XVII внутри XVIII) | ED::test_century_not_in_quote; @example «XVII в.»/«в XVIII в.» | roman-unchecked, roman-substring |
| Проверка 5 `dating:era` (в обе стороны) | S.datings target era | ED::test_era_mismatch; @example «375»/«до н. э.», «375 до н. э.»/«(375)» | era-unchecked, era-one-way |
| Проверка 6 `dating:single_year` (год, «ок. Г», век у персоны) | S.datings (person ∧ single) | ED::test_single_year_person; @example «1724», «ок. 1724», «XVIII в.» (фактически роняет: test_dating_check_any_input, test_dating_invariant, test_rejected) | single-year-dropped, century-person-allowed, approx-year-not-single |
| Порядок: первая несработавшая — paragraph раньше quote | S.datings m_paragraph_quote | ED @example paragraph 0 + цитата вне абзаца (фактически роняет: test_dating_check_any_input, test_dating_invariant, test_rejected) | paragraph-bounds-off |
| Порядок: quote раньше unparsed | S.datings m_quote_unparsed | ED @example «в эпоху Просвещения» + лишняя цитата (фактически роняет: test_dating_check_any_input, test_dating_invariant) | check-order-quote-unparsed |
| Порядок: unparsed раньше not_in_quote | S.datings m_unparsed_numbers | ED @example «12 мая 1724»/«жил в Кёнигсберге» (фактически роняет: test_dating_check_any_input, test_dating_invariant, test_rejected) | unparsed-lenient |
| Порядок: not_in_quote раньше era | S.datings m_numbers_era | ED @example «375 до н. э.»/«(ок. 380)» (фактически роняет: test_dating_check_any_input, test_dating_invariant, test_rejected) | check-order-numbers-era |
| Порядок: era раньше single_year | S.datings m_era_single | ED @example «1724»/«в 1724 до нашей эры» (фактически роняет: test_dating_check_any_input, test_dating_invariant) | check-order-era-single |
| Порядок: not_in_quote раньше single_year | S.datings m_numbers_single | ED @example «1724»/«в 1725 году» (фактически роняет: test_dating_check_any_input, test_dating_invariant, test_rejected) | check-order-numbers-era |
| До проверок: `dating:unresolved` без повторной привязки | сценарный (ambiguous+reject) | ED::test_dating_of_unresolved_entity | unresolved-reresolved, unresolved-inner-reason |
| Затем `dating:type`, причина — код | сценарный (понятие «Субстанция») | ED::test_dating_of_type_not_allowed | dating-type-unchecked |
| Отказ: не записывается, ровно одно `dropped` с `run_id` и причиной | S.datings (все цели) | ED::test_dating_invariant (`[drop] = dropped`), `_rejected` | dating-drop-doubled |
| Отказ не отменяет сущность и прочие утверждения | сценарный | ED::test_year_not_in_quote, test_dating_of_type_not_allowed | dating-type-unchecked |
| Запись: персона — `lifespan`, прочие — `dating` | S.datings (person/non-person) | ED::test_life_dates_in_text, test_work_year | dating-person-as-dating |
| Запись: подтверждение — абзац и цитата | S.datings | ED::test_dating_invariant (evidence) | dating-evidence-dropped |
| Запись: атрибуция — источник; происхождение — «извлечено» | сценарный | ED::test_life_dates_in_text | dating-attribution-dropped, dating-provenance-manual |
| Основное значение — в `primary.dates` | S.datings | ED::test_dating_invariant (span, precision) | approx-slack-year-wrong |
| Инвариант датировки (записана по таблице либо отклонена одной причиной) | S.datings (все цели) | ED::test_dating_invariant, test_dating_check_any_input | numbers-substring, era-unchecked, roman-unchecked, reverse-interval-accepted |
| Сценарии: Дата жизни, До н. э., Год произведения, Века, Века нет в цитате, Эра, Года нет, Число внутри, Один год, Неразборчивая, Абзац вне | сценарные | ED::test_life_dates_in_text … test_paragraph_outside_fragment (фактически роняет: test_century_not_in_quote, test_dating_check_any_input, test_dating_invariant) | century-bounds-off, roman-unchecked, era-unchecked, numbers-substring, single-year-dropped, unparsed-lenient, paragraph-bounds-off |


### ontology-extraction / Структурированный вывод по реестру и Нормализация сущностей

| Пункт | Вид генератора | @example | Мутация |
|---|---|---|---|
| Схема из реестра: только допустимые типы | S.fragment_items / `typed_items` (EX: типы реестра и JUNK_TYPES) | EX::test_only_registry_types_for_any_items @example «deity», «Person» | entity-type-unchecked |
| Неуверенность в частном типе → общий по иерархии | сценарный (studied_with с неподходящими концами) | EX::test_uncertain_type_falls_back_to_general | fit-no-parent |
| Необязательный массив `entities`; в `required` корня только `statements` | сценарный стенд (схема из перехвата) | EX::test_schema_with_entities_and_dating | schema-entities-required |
| Поля элемента: name, type, ru, en, original, dating | сценарный стенд | EX::test_schema_with_entities_and_dating | schema-no-original |
| Датировка: text, paragraph, quote обязательны | сценарный стенд | EX::test_schema_with_entities_and_dating | schema-dating-required-short |
| `language` в данных запроса — преобладающий `lang` абзацев | параметры (ru/en/de, 1–3 абзаца, меньшинство первым) | EX::test_prompt_language_and_rules | language-first-paragraph |
| Промпт: правило языка названий (`ru` всегда по-русски) | сценарный стенд | EX::test_prompt_language_and_rules | prompt-no-ru-language-rule |
| Промпт: что не считается названием | сценарный стенд | EX::test_prompt_language_and_rules | prompt-no-not-a-name-rule |
| Промпт: «извлекай годы, если они названы» | сценарный стенд | EX::test_prompt_language_and_rules, test_schema_with_entities_and_dating | prompt-no-years-rule |
| Причина `entity:type` — тип вне реестра (сервер проверяет сам) | S.typed_items (JUNK_TYPES) | EX::test_entity_type_outside_registry | entity-type-unchecked |
| Причина `entity:no_type` — новая сущность без типа, без названия в причине | сценарный (subject без `subject_type`) | EX::test_new_entity_without_type_dropped_by_code | no-type-creates-entity |
| Причина `entity:ambiguous` | сценарный | EX::test_ambiguous_goes_to_review | ambiguous-reason-text |
| Причина `entity:<причина>` — отклонённое название; названия в причине нет | S.not_persons / сценарии naming | NM::test_section_number, test_role_instead_of_name | dropped-reason-text |
| Ответ без `entities` обрабатывается как прежде | сценарный | EX::test_answer_without_entities | entities-required-in-answer |
| Инвариант: типы, концы, уточнители только из реестра; `entities` дают только lifespan/dating | S.typed_items | EX::test_only_registry_types_for_any_items | entity-type-unchecked, dating-person-as-dating |
| Привязка по всем написаниям: name | S.fragment_items | EX::test_normalization_and_language_for_any_items | spellings-without-original |
| Привязка по `ru` | S.fragment_items (existing=ru) | EX::test_normalization_and_language_for_any_items | spellings-without-ru |
| Привязка по `en` | S.fragment_items (existing=en) | EX::test_binding_by_english_spelling; @example Локк/LOCKE | spellings-without-en |
| Привязка по `original` | S.fragment_items (existing=original) | EX::…any_items @example Платон + Πλάτων (фактически роняет: test_normalization_and_language_for_any_items) | spellings-without-original |
| Привязка по вариантам названий («Хьюма» → «Юм») | сценарный | EX::test_binding_by_variant | binding-by-variant-dropped |
| Неоднозначность → очередь, а не выбор | сценарный | EX::test_ambiguous_goes_to_review | ambiguous-creates-new |
| Новая сущность — только если подходящей нет и название годно | S.fragment_items + S.names_with_reason | EX::…any_items, NM::test_rejection_invariant | spellings-without-en, create-unchecked |
| Критерий дробности из реестра (создавать только крупные сущности) | — (поведение реестра, вне правок этого изменения) | — | — (не покрыто: нет generator-вида; см. «Не покрыто») |
| Ответ не по схеме отбрасывается после повторов с записью в журнал | — (поведение шлюза моделей, вне правок изменения) | — | — (не покрыто: покрывается тестами `tests/llm`) |

### epochs / Даты эпох из Wikidata

Генератор во всех строках — «мир» `mixed_world` в `test_epoch_dates.py` (по эпохе на каждый `result` таблицы) и фикстуры `RecordFetch`/`dated`/`record`/`year` из `wd_records.py`; случайного генератора у команды эпох нет, входы заданы строками таблицы требования.

| Пункт | Вид генератора | @example | Мутация |
|---|---|---|---|
| Только подтверждённый человеком QID (внешний id или поле манифеста) | mixed_world (Античность: без QID) | EPD::test_manifest_qid_differs_from_epoch_qid (фактически роняет: test_created_ambiguous_no_qid_failed_duplicate, test_dry_run_changes_no_table_for_any_result, test_every_result_and_totals) | epoch-no-qid-result |
| `--linked` обходит все эпохи базы с QID | mixed_world (Романтизм) | EPD::test_date_from_wikidata | epoch-linked-skipped |
| Начало/конец P580/P582 | mixed_world (Просвещение) | EPD::test_date_from_wikidata | epoch-attribution-no-link |
| Запасные P571/P576, если нет P580/P582 | `dated` с P571/P576 | EPD::test_fallback_properties | epoch-fallback-props-dropped |
| Только начало или только конец → `no_dates` | mixed_world (Схоластика) | EPD::test_property_choice | epoch-no-dates-as-fetch-failed |
| Статус «по источникам» | mixed_world | EPD::test_date_from_wikidata | epoch-status-generated |
| Атрибуция «Wikidata» со ссылкой на запись | mixed_world | EPD::test_date_from_wikidata | epoch-attribution-no-link |
| Происхождение «импорт» с QID и свойствами | mixed_world | EPD::test_date_from_wikidata | epoch-provenance-no-props |
| Внешний QID записывается, если его не было | `epoch` без QID + манифест | EPD::test_added_from_manifest_gets_external_id | epoch-added-without-external |
| Действующая датировка не перезаписывается | mixed_world (Барокко/Научная революция) | EPD::test_existing_dating_kept, test_existing_never_overwritten | epoch-conflict-overwrites |
| `--dry-run` не меняет базу | mixed_world | EPD::test_dry_run, test_dry_run_changes_no_table_for_any_result | epoch-dry-run-writes, epoch-dry-run-creates |
| Связи влияния из Wikidata не импортируются | `record(items={"P737": …})` | EPD::test_influences_not_imported | — (отрицательный пункт: в коде нет ветки импорта влияния, ломать нечего; тест запрещает появление `influenced_by`) |
| Повторный запуск не создаёт утверждений и сущностей | mixed_world ×2 | EPD::test_repeated_apply_creates_no_rows (фактически роняет: test_apply_linked_adds_then_unchanged, test_created_ambiguous_no_qid_failed_duplicate, test_dry_run_changes_no_table_for_any_result) | epoch-unchanged-as-conflict |
| `result=added` | mixed_world (Просвещение) | EPD::test_every_result_and_totals (фактически роняет: test_added_from_manifest_gets_external_id) | epoch-added-without-external |
| `result=created` (сущность, названия, внешний id, dating) | mixed_world («Долгий XIX век») | EPD::test_new_epoch_from_manifest | epoch-created-without-external |
| `result=unchanged` (совпала по четырём границам) | mixed_world (Научная революция) | EPD::test_repeated_run | epoch-unchanged-as-conflict |
| `result=conflict` (обе датировки в отчёте) | mixed_world (Барокко) | EPD::test_existing_dating_kept | epoch-conflict-overwrites |
| `result=no_dates` | mixed_world (Схоластика) | EPD::test_property_choice | epoch-no-dates-as-fetch-failed |
| `result=no_qid`, загрузка не вызывается | mixed_world, `RecordFetch.calls == []` | EPD::test_no_qid_never_fetches | epoch-no-qid-result |
| `result=fetch_failed` | mixed_world (Средние века) | EPD::test_fetch_failed_and_duplicate_qid (фактически роняет: test_dry_run_changes_no_table_for_any_result) | epoch-fetch-failed-as-no-dates |
| `result=ambiguous` | mixed_world (две «Новое время») | EPD::test_two_epochs_same_name (фактически роняет: test_dry_run_changes_no_table_for_any_result) | epoch-ambiguous-picks-first |
| `result=duplicate_qid`: QID у другой сущности | mixed_world (Возрождение/Эразм Q8) | EPD::test_fetch_failed_and_duplicate_qid (фактически роняет: test_dry_run_changes_no_table_for_any_result) | epoch-qid-owner-ignored |
| `result=duplicate_qid`: у эпохи уже другой QID | `epoch` с QID + манифест с другим | EPD::test_manifest_qid_differs_from_epoch_qid | epoch-own-qid-conflict-ignored |
| `result=invalid_name`, эпоха не заводится, событие `rejected` | S.names_with_reason (число) | INV::test_epoch_name_rejected, test_epoch_created_iff_name_valid | epoch-invalid-unchecked |
| `checked` с полями `epoch_id` (может быть null), `qid`, `result` | mixed_world | EPD::test_every_result_and_totals (ambiguous: epoch_id None) | epoch-no-qid-result |
| `run`: `checked = added + created + conflicts + skipped` | mixed_world | EPD::test_every_result_and_totals | epoch-skipped-without-conflicts |
| Режим проверки: `result` тот, что был бы записан | mixed_world (dry-run) | EPD::test_dry_run_changes_no_table_for_any_result | epoch-dry-run-creates |
| Сценарии: Дата из Wikidata, Запасные, Уже есть, Повторный, Проверка без записи, Без QID, Сбой и одинаковый QID, Название не прошло проверку | сценарные | EPD::test_date_from_wikidata … ; INV::test_epoch_name_rejected | epoch-linked-skipped, epoch-fallback-props-dropped, epoch-conflict-overwrites, epoch-unchanged-as-conflict, epoch-dry-run-writes, epoch-no-qid-result, epoch-qid-owner-ignored, epoch-invalid-unchecked |

### epoch-context / Контекстные события из Wikidata

Генератор — «мир» теста `test_epoch_context_import.py` (записи P793, P585, P31, P276 фикстурами `record`/`RecordFetch`); случайного генератора нет, входы — строки таблицы требования.

| Пункт | Вид генератора | @example | Мутация |
|---|---|---|---|
| `harvest`: P793 «значимые события» эпохи | мир harvest (три события) | CTX::test_harvest_candidates | ctx-undated-offered |
| Дата: момент P585, иначе P580/P582 | мир harvest (революция P585 1789) | CTX::test_harvest_candidates | ctx-point-time-ignored |
| Вид по таблице классов P31; класс не из таблицы — вид не пишется | мир harvest (событие 1755 с чужим классом) | CTX::test_harvest_candidates, test_unknown_class_no_kind | ctx-kind-any-class |
| Первое место P276 | мир harvest (Париж) | CTX::test_harvest_candidates | ctx-undated-offered |
| Кандидаты с решением `pending` | мир harvest | CTX::test_harvest_candidates | ctx-undated-offered |
| Кандидат без даты не предлагается | мир harvest (событие без даты) | CTX::test_undated_never_offered (фактически роняет: test_harvest_candidates) | ctx-undated-offered |
| Повторный `harvest` не меняет решения и поля человека | мир harvest ×2 | CTX::test_repeat_harvest_keeps_decisions, test_repeat_harvest_keeps_human_fields | ctx-harvest-duplicates |
| `harvested` с `epochs`, `candidates` | мир harvest | CTX::test_harvest_candidates | ctx-undated-offered |
| `apply` пишет только `accepted` | мир apply (pending, rejected, accepted) | CTX::test_pending_and_rejected | ctx-pending-applied, ctx-rejected-applied |
| Событие с внешним id (новое или найденное по id) | мир apply | CTX::test_accepted_candidate, test_found_by_qid (фактически роняет: test_repeat_apply_and_dry_run) | ctx-event-not-reused |
| Датировка события | мир apply | CTX::test_accepted_candidate | ctx-statements-count-zero |
| Вид события (если есть) | мир apply (kind=political) | CTX::test_accepted_candidate | ctx-kind-statement-dropped |
| Принадлежность к эпохе: `membership_basis=historians` | мир apply | CTX::test_accepted_candidate | ctx-membership-basis-missing |
| Место (найденное по id или новое) | мир apply (Париж новое / существующее) | CTX::test_accepted_candidate, test_found_by_qid | ctx-place-always-new |
| Статус «по источникам» | мир apply | CTX::test_accepted_candidate | ctx-status-generated |
| Атрибуция «Wikidata» со ссылкой | мир apply | CTX::test_accepted_candidate | ctx-attribution-no-link |
| Связи «стимулировало», механизм, влияние не записываются | мир apply | CTX::test_never_writes_stimulated_mechanism_influence | — (отрицательный пункт: кода записи таких связей нет; тест запрещает их появление) |
| `--dry-run` не меняет базу | мир apply (dry) | CTX::test_repeat_apply_and_dry_run, test_cli_dry_run_changes_nothing | ctx-dry-run-writes |
| Повторный `apply` не создаёт сущностей и утверждений | мир apply ×2 | CTX::test_repeat_apply_and_dry_run | ctx-event-not-reused, ctx-exists-as-created |
| `checked` на каждый кандидат; `run`: `mode, created, statements, places_created, skipped` | мир apply | CTX::test_accepted_candidate (statements=4, places_created=1) | ctx-statements-count-zero, ctx-places-created-zero |
| `result=created` | мир apply | CTX::test_accepted_candidate (фактически роняет: test_repeat_apply_and_dry_run) | ctx-exists-as-created |
| `result=exists` | мир apply ×2 | CTX::test_repeat_apply_and_dry_run | ctx-exists-as-created |
| `result=pending` / `rejected` | мир apply | CTX::test_pending_and_rejected | ctx-pending-applied, ctx-rejected-applied |
| `result=no_date` | мир apply (дата не разбирается) | CTX::test_no_date_and_fetch_failed | ctx-no-date-as-fetch-failed |
| `result=fetch_failed` | мир apply (сбой загрузки) | CTX::test_no_date_and_fetch_failed | ctx-fetch-failed-as-no-date |
| `result=duplicate_qid`: событие | мир apply (QID события у персоны) | CTX::test_duplicate_qid_other_type | ctx-duplicate-qid-event-ignored |
| `result=duplicate_qid`: место | мир apply (QID места у не-места) | CTX::test_duplicate_qid_other_type | ctx-duplicate-qid-place-ignored |
| `result=invalid_name`: ничего не записано, `rejected` | S.names_with_reason (подпись) | INV::test_context_event_name_rejected, test_context_candidate_written_iff_name_valid | context-place-before-event |
| Сценарии: Кандидаты, Принятый, Ожидающий/отклонённый, Повтор и проверка, Повторный подбор, Название не прошло | сценарные | CTX::test_harvest_candidates … ; INV | ctx-undated-offered, ctx-membership-basis-missing, ctx-pending-applied, ctx-exists-as-created, ctx-harvest-duplicates, context-place-before-event |

### geo-timeline / Места и координаты из Wikidata

Генератор — «мир» теста `test_geo_enrich.py` (`person_record`, `place_record`, `kant_records`, `Fetch`); случайных генераторов у команды нет (входы — сценарии спецификации).

| Пункт | Вид генератора | @example | Мутация |
|---|---|---|---|
| Только сущности с QID вида `^Q\d+$` | мир (external «x1»/«q9») | GEO::test_bad_external_id_never_fetched | geo-qid-shape-unchecked |
| Координаты места (P625) | `kant_records` | GEO::test_kant_from_wikidata (фактически роняет: test_bad_external_id_never_fetched) | geo-qid-shape-unchecked |
| «Жил в» `birth` (P19) со временем P569 | `kant_records` | GEO::test_kant_from_wikidata | geo-birth-no-time, geo-time-dropped |
| «Жил в» `death` (P20) со временем P570 | `kant_records` | GEO::test_kant_from_wikidata | geo-time-dropped |
| «Жил в» `activity` (P937) со временем P580–P582 | запись с P937 | GEO::test_activity_from_p937 | geo-activity-no-time |
| Роль места `place_role` | `kant_records` | GEO::test_kant_from_wikidata | geo-place-role-dropped |
| У события «произошло в» (P276) | запись события | GEO::test_only_table_properties (фактически роняет: test_influence_and_foreign_properties_not_imported) | geo-influence-imported |
| Новых персон и событий не создаёт | мир | GEO::test_no_new_people_or_events | — (отрицательный пункт: в коде нет создания персон/событий; тест запрещает) |
| Место, которого нет, создаётся с внешним id | `kant_records` без места | GEO::test_kant_from_wikidata, test_existing_place_reused (фактически роняет: test_rerun_adds_nothing) | geo-rerun-counts-again |
| Влияния (P737) и свойства вне списка не импортируются | запись с P737, P27 | GEO::test_influence_and_foreign_properties_not_imported | geo-influence-imported, geo-citizenship-imported |
| QID в значении не по `^Q\d+$` не запрашивается и не пишется | значение `<script>` | GEO::test_bad_value_id_not_fetched_or_written, test_skips_reasons_and_counters | geo-value-qid-unchecked |
| Атрибуция «Wikidata» со ссылкой из QID | `kant_records` | GEO::test_every_record_attributed (фактически роняет: test_kant_from_wikidata) | geo-attribution-no-link |
| Статус «по источникам» | `kant_records` | GEO::test_kant_from_wikidata | geo-status-generated |
| Происхождение «импорт» с номером запуска | `kant_records` | GEO::test_kant_from_wikidata | geo-provenance-no-run |
| Повторный запуск не добавляет утверждений | `kant_records` ×2 | GEO::test_rerun_adds_nothing | geo-rerun-counts-again |
| Запуск с записями из файла, без сети | `kant_records` в файл | GEO::test_file_run_without_network (фактически роняет: test_bad_external_id_never_fetched) | geo-qid-shape-unchecked |
| Сухой прогон: считает, ничего не пишет и не создаёт мест | `kant_records`, база без мест / с местом | GEO::test_dry_run_writes_nothing, test_dry_run_with_existing_place_writes_nothing | geo-dry-run-creates-places, geo-dry-run-writes |
| Пропуск `bad_qid` | значение `<script>` | GEO::test_skips_reasons_and_counters | geo-value-qid-unchecked |
| Пропуск `bad_value` (значение без id места) | claim без `id` | GEO::test_value_without_id_is_bad_value | geo-bad-value-as-bad-qid |
| Пропуск `refused` (сервер отклонил / подпись не прошла правило) | Юм P625 (95, 0); подпись «20.1» | GEO::test_skips_reasons_and_counters; INV::test_place_label_rejected | geo-refused-as-bad-value, geo-label-unchecked |
| Запись не получена — `fetch_failed`, счётчик `failed` | Стокгольм не загружается | GEO::test_skips_reasons_and_counters | geo-fetch-failed-as-skipped |
| `knowledge.geo.skipped` с `entity`, `property`, `reason`; запуск продолжается | Декарт/Юм | GEO::test_skips_reasons_and_counters, test_event_fields_only_ids_codes_numbers | geo-skipped-entity-wrong |
| `knowledge.geo.enriched` с полями итога | `kant_records` | GEO::test_kant_from_wikidata, test_event_fields_only_ids_codes_numbers (фактически роняет: test_rollback_keeps_verified_and_places) | geo-places-kept-zero |
| Откат удаляет утверждения запуска, кроме проверенных | запуск + verified | GEO::test_rollback_keeps_verified_and_places | geo-rollback-removes-verified |
| Созданные места остаются; `rolled_back` с `statements`, `places_kept` | запуск + verified | GEO::test_rollback_keeps_verified_and_places | geo-places-kept-zero |
| Обогащение не вызывается из пути читателя | мир (счётчик вызовов `fetch`) | GEO::test_not_from_reader_path | — (отрицательный пункт: в читательском пути нет вызова обогащения; тест считает вызовы `fetch` = 0) |
| Подпись нового места проходит правило названий | S.names_with_reason (число) | INV::test_place_label_rejected, test_place_created_iff_label_valid | geo-label-unchecked |
| Сценарии: Кант, Повторный, Влияние, Сухой, Пропуски, Откат, Не из пути читателя, Подпись | сценарные | GEO::test_kant_from_wikidata … ; INV::test_place_label_rejected | geo-time-dropped, geo-rerun-counts-again, geo-influence-imported, geo-dry-run-creates-places, geo-fetch-failed-as-skipped, geo-places-kept-zero, geo-label-unchecked |



Прогоны мутаций аудита (требование | мутация | тест | упал):

| Требование | Мутация | Тест | Упал |
|---|---|---|---|
| Язык названий сущностей | words-edge-kept | tests/knowledge/test_entity_naming.py::test_lang_for_any_text | да (2) |
| Язык названий сущностей | digits-as-letters | tests/knowledge/test_entity_naming.py::test_lang_for_any_text | да (2) |
| Язык названий сущностей | cyrillic-range-short | tests/knowledge/test_entity_naming.py::test_lang_for_any_text | да (2) |
| Язык названий сущностей | tie-first-wins | tests/knowledge/test_entity_naming.py::test_language_by_script_on_every_path | да (4) |
| Язык названий сущностей | given-lang-table-short | tests/knowledge/test_entity_naming.py::test_lang_for_any_text | да (2) |
| Язык названий сущностей | given-kept-without-script | tests/knowledge/test_entity_naming.py::test_language_by_script_on_every_path | да (4) |
| Язык названий сущностей | ru-primary-unchecked | tests/knowledge/test_naming_unit.py::test_names_for_rejected_spelling_not_written | да (1) |
| Язык названий сущностей | ru-primary-not-russian | tests/knowledge/test_entity_naming.py::test_primary_choice_by_item | да (1) |
| Язык названий сущностей | variants-dropped | tests/knowledge/test_entity_naming.py::test_russian_textbook | да (2) |
| Язык названий сущностей | rejected-spelling-variant | tests/knowledge/test_naming_unit.py::test_names_for_rejected_spelling_not_written | да (1) |
| Валидность названий сущностей | rule-sentence-before-number | tests/knowledge/test_entity_naming.py::test_check_name_any_input | да (1) |
| Валидность названий сущностей | rule-empty-as-number | tests/knowledge/test_entity_naming.py::test_empty_names | да (3) |
| Валидность названий сущностей | rule-sentence-chars-unchecked | tests/knowledge/test_entity_naming.py::test_limit_boundaries | да (6) |
| Валидность названий сущностей | rule-sentence-words-unchecked | tests/knowledge/test_entity_naming.py::test_sentence_instead_of_term | да (5) |
| Валидность названий сущностей | rule-limit-ge | tests/knowledge/test_entity_naming.py::test_limit_boundaries | да (4) |
| Валидность названий сущностей | rule-limits-default-only | tests/knowledge/test_entity_naming.py::test_limit_boundaries | да (4) |
| Валидность названий сущностей | rule-particle-apostrophe-ignored | tests/knowledge/test_entity_naming.py::test_particles_and_roman | да (3) |
| Валидность названий сущностей | rule-particle-case-sensitive | tests/knowledge/test_entity_naming.py::test_check_name_any_input | да (1) |
| Валидность названий сущностей | rule-glue-lower-neighbors | tests/knowledge/test_entity_naming.py::test_check_name_any_input | да (1) |
| Валидность названий сущностей | rule-not-a-name-all-types | tests/knowledge/test_entity_naming.py::test_rules_are_data | да (3) |
| Валидность названий сущностей | rule-lowercase-first-unchecked | tests/knowledge/test_entity_naming.py::test_role_instead_of_name | да (5) |
| Валидность названий сущностей | rule-patterns-dropped | tests/knowledge/test_entity_naming.py::test_description_with_capital | да (4) |
| Валидность названий сущностей | rule-glue-dropped | tests/knowledge/test_entity_naming.py::test_glued_names | да (4) |
| Валидность названий сущностей | rule-stopword-raw-compare | tests/knowledge/test_entity_naming.py::test_check_name_any_input | да (2) |
| Валидность названий сущностей | rule-exempt-ignored | tests/knowledge/test_entity_naming.py::test_rules_are_data | да (3) |
| Валидность названий сущностей | rule-no-nfc | tests/knowledge/test_entity_naming.py::test_signs_counted_after_nfc | да (1) |
| Валидность названий сущностей | rule-no-strip | tests/knowledge/test_entity_naming.py::test_signs_counted_after_nfc | да (1) |
| Валидность названий сущностей | label-cut-80 | tests/knowledge/test_entity_naming.py::test_limit_boundaries | да (4) |
| Валидность названий сущностей | rejected-extra-field | tests/knowledge/test_entity_naming.py::test_section_number | да (4) |
| Валидность названий сущностей | rules-limits-hardcoded | tests/knowledge/test_entity_naming.py::test_rules_are_data | да (1) |
| Валидность названий сущностей | rules-particles-hardcoded | tests/knowledge/test_entity_naming.py::test_rules_are_data | да (1) |
| Валидность названий сущностей | rules-patterns-hardcoded | tests/knowledge/test_entity_naming.py::test_rules_are_data | да (1) |
| Валидность названий сущностей | rules-conjunctions-hardcoded | tests/knowledge/test_entity_naming.py::test_rules_are_data | да (1) |
| Валидность названий сущностей | rules-person-types-hardcoded | tests/knowledge/test_entity_naming.py::test_rules_are_data | да (1) |
| Язык названий сущностей | add-name-lang-given | tests/knowledge/test_entity_naming.py::test_language_invariant_create_and_add_name | да (2) |
| Язык названий сущностей | create-lang-given | tests/knowledge/test_entity_naming.py::test_language_by_script_on_every_path | да (3) |
| Язык названий сущностей | rename-keeps-old-primary | tests/knowledge/test_entity_naming.py::test_existing_english_entity_gets_russian_primary | да (3) |
| Язык названий сущностей | renamed-previous-lang-wrong | tests/knowledge/test_entity_naming.py::test_existing_english_entity_gets_russian_primary | да (2) |
| Язык названий сущностей | created-event-doubled | tests/knowledge/test_entity_naming.py::test_russian_textbook | да (3) |
| Язык названий сущностей | ambiguous-creates-new | tests/knowledge/test_entity_naming.py::test_spellings_found_different_entities | да (2) |
| Язык названий сущностей | ambiguous-candidates-count | tests/knowledge/test_entity_naming.py::test_spellings_found_different_entities | да (2) |
| Язык названий сущностей | ambiguous-no-review-item | tests/knowledge/test_entity_naming.py::test_spellings_found_different_entities | да (2) |
| Нормализация сущностей | no-type-creates-entity | tests/knowledge/test_extraction_entities.py::test_new_entity_without_type_dropped_by_code | да (1) |
| Нормализация сущностей | spellings-without-ru | tests/knowledge/test_extraction_entities.py::test_normalization_and_language_for_any_items | да (1) |
| Нормализация сущностей | spellings-without-original | tests/knowledge/test_extraction_entities.py::test_normalization_and_language_for_any_items | да (1) |
| Извлечение дат | dating-person-as-dating | tests/knowledge/test_entity_dating_extraction.py::test_life_dates_in_text | да (6) |
| Извлечение дат | dating-evidence-dropped | tests/knowledge/test_entity_dating_extraction.py::test_life_dates_in_text | да (5) |
| Извлечение дат | dating-attribution-dropped | tests/knowledge/test_entity_dating_extraction.py::test_life_dates_in_text | да (1) |
| Извлечение дат | dating-provenance-manual | tests/knowledge/test_entity_dating_extraction.py::test_life_dates_in_text | да (1) |
| Извлечение дат | check-order-quote-unparsed | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (2) |
| Извлечение дат | check-order-numbers-era | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (3) |
| Извлечение дат | check-order-era-single | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (2) |
| Извлечение дат | paragraph-bounds-off | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (3) |
| Извлечение дат | quote-case-sensitive | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (3) |
| Извлечение дат | quote-yo-kept | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (3) |
| Извлечение дат | quote-spaces-kept | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (3) |
| Извлечение дат | roman-substring | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (3) |
| Извлечение дат | era-one-way | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (3) |
| Извлечение дат | century-person-allowed | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (3) |
| Извлечение дат | approx-year-not-single | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (2) |
| Извлечение дат | year-max-2101 | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (3) |
| Извлечение дат | year-zero-allowed | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (3) |
| Извлечение дат | century-max-22 | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (3) |
| Извлечение дат | dash-hyphen-only | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (5) |
| Извлечение дат | approx-markers-short | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (3) |
| Извлечение дат | era-text-spaced-only | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (3) |
| Извлечение дат | era-quote-nashei-missing | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (3) |
| Извлечение дат | approx-slack-year-wrong | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (2) |
| Извлечение дат | approx-slack-interval-wrong | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (2) |
| Извлечение дат | century-bounds-off | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (2) |
| Извлечение дат | century-bce-bounds-off | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (3) |
| Извлечение дат | century-precision-year | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (3) |
| Извлечение дат | approx-precision-year | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (3) |
| Структурированный вывод по реестру | schema-no-original | tests/knowledge/test_extraction_entities.py::test_schema_with_entities_and_dating | да (1) |
| Структурированный вывод по реестру | schema-entities-required | tests/knowledge/test_extraction_entities.py::test_schema_with_entities_and_dating | да (4) |
| Структурированный вывод по реестру | language-first-paragraph | tests/knowledge/test_extraction_entities.py::test_prompt_language_and_rules | да (1) |
| Структурированный вывод по реестру | prompt-no-years-rule | tests/knowledge/test_extraction_entities.py::test_schema_with_entities_and_dating | да (2) |
| Структурированный вывод по реестру | prompt-no-not-a-name-rule | tests/knowledge/test_extraction_entities.py::test_prompt_language_and_rules | да (1) |
| Структурированный вывод по реестру | prompt-no-ru-language-rule | tests/knowledge/test_extraction_entities.py::test_prompt_language_and_rules | да (1) |
| Даты эпох из Wikidata | epoch-unchanged-as-conflict | tests/knowledge/test_epoch_dates.py::test_repeated_run | да (7) |
| Даты эпох из Wikidata | epoch-conflict-overwrites | tests/knowledge/test_epoch_dates.py::test_existing_dating_kept | да (4) |
| Даты эпох из Wikidata | epoch-fallback-props-dropped | tests/knowledge/test_epoch_dates.py::test_fallback_properties | да (2) |
| Даты эпох из Wikidata | epoch-no-qid-result | tests/knowledge/test_epoch_dates.py::test_dry_run_changes_no_table_for_any_result | да (6) |
| Даты эпох из Wikidata | epoch-ambiguous-picks-first | tests/knowledge/test_epoch_dates.py::test_dry_run_changes_no_table_for_any_result | да (1) |
| Даты эпох из Wikidata | epoch-own-qid-conflict-ignored | tests/knowledge/test_epoch_dates.py::test_manifest_qid_differs_from_epoch_qid | да (1) |
| Даты эпох из Wikidata | epoch-qid-owner-ignored | tests/knowledge/test_epoch_dates.py::test_dry_run_changes_no_table_for_any_result | да (1) |
| Даты эпох из Wikidata | epoch-fetch-failed-as-no-dates | tests/knowledge/test_epoch_dates.py::test_dry_run_changes_no_table_for_any_result | да (1) |
| Даты эпох из Wikidata | epoch-no-dates-as-fetch-failed | tests/knowledge/test_epoch_dates.py::test_property_choice | да (1) |
| Даты эпох из Wikidata | epoch-created-without-external | tests/knowledge/test_epoch_dates.py::test_new_epoch_from_manifest | да (1) |
| Даты эпох из Wikidata | epoch-added-without-external | tests/knowledge/test_epoch_dates.py::test_added_from_manifest_gets_external_id | да (1) |
| Даты эпох из Wikidata | epoch-dry-run-writes | tests/knowledge/test_epoch_dates.py::test_dry_run | да (1) |
| Даты эпох из Wikidata | epoch-dry-run-creates | tests/knowledge/test_epoch_dates.py::test_dry_run_changes_no_table_for_any_result | да (1) |
| Даты эпох из Wikidata | epoch-skipped-without-conflicts | tests/knowledge/test_epoch_dates.py::test_every_result_and_totals | да (1) |
| Даты эпох из Wikidata | epoch-attribution-no-link | tests/knowledge/test_epoch_dates.py::test_date_from_wikidata | да (1) |
| Даты эпох из Wikidata | epoch-provenance-no-props | tests/knowledge/test_epoch_dates.py::test_date_from_wikidata | да (1) |
| Даты эпох из Wikidata | epoch-status-generated | tests/knowledge/test_epoch_dates.py::test_date_from_wikidata | да (1) |
| Даты эпох из Wikidata | epoch-linked-skipped | tests/knowledge/test_epoch_dates.py::test_date_from_wikidata | да (1) |
| Контекстные события из Wikidata | ctx-undated-offered | tests/knowledge/test_epoch_context_import.py::test_harvest_candidates | да (1) |
| Контекстные события из Wikidata | ctx-harvest-duplicates | tests/knowledge/test_epoch_context_import.py::test_repeat_harvest_keeps_decisions | да (1) |
| Контекстные события из Wikidata | ctx-kind-any-class | tests/knowledge/test_epoch_context_import.py::test_harvest_candidates | да (1) |
| Контекстные события из Wikidata | ctx-point-time-ignored | tests/knowledge/test_epoch_context_import.py::test_harvest_candidates | да (1) |
| Контекстные события из Wikidata | ctx-pending-applied | tests/knowledge/test_epoch_context_import.py::test_accepted_candidate | да (1) |
| Контекстные события из Wikidata | ctx-rejected-applied | tests/knowledge/test_epoch_context_import.py::test_pending_and_rejected | да (1) |
| Контекстные события из Wikidata | ctx-exists-as-created | tests/knowledge/test_epoch_context_import.py::test_repeat_apply_and_dry_run | да (1) |
| Контекстные события из Wikidata | ctx-no-date-as-fetch-failed | tests/knowledge/test_epoch_context_import.py::test_no_date_and_fetch_failed | да (1) |
| Контекстные события из Wikidata | ctx-fetch-failed-as-no-date | tests/knowledge/test_epoch_context_import.py::test_no_date_and_fetch_failed | да (1) |
| Контекстные события из Wikidata | ctx-duplicate-qid-event-ignored | tests/knowledge/test_epoch_context_import.py::test_duplicate_qid_other_type | да (1) |
| Контекстные события из Wikidata | ctx-duplicate-qid-place-ignored | tests/knowledge/test_epoch_context_import.py::test_duplicate_qid_other_type | да (1) |
| Контекстные события из Wikidata | ctx-membership-basis-missing | tests/knowledge/test_epoch_context_import.py::test_accepted_candidate | да (1) |
| Контекстные события из Wikidata | ctx-kind-statement-dropped | tests/knowledge/test_epoch_context_import.py::test_accepted_candidate | да (1) |
| Контекстные события из Wikidata | ctx-status-generated | tests/knowledge/test_epoch_context_import.py::test_accepted_candidate | да (1) |
| Контекстные события из Wikidata | ctx-dry-run-writes | tests/knowledge/test_epoch_context_import.py::test_repeat_apply_and_dry_run | да (1) |
| Контекстные события из Wikidata | ctx-statements-count-zero | tests/knowledge/test_epoch_context_import.py::test_accepted_candidate | да (1) |
| Контекстные события из Wikidata | ctx-places-created-zero | tests/knowledge/test_epoch_context_import.py::test_accepted_candidate | да (1) |
| Контекстные события из Wikidata | ctx-attribution-no-link | tests/knowledge/test_epoch_context_import.py::test_accepted_candidate | да (1) |
| Контекстные события из Wikidata | ctx-place-always-new | tests/knowledge/test_epoch_context_import.py::test_found_by_qid | да (1) |
| Контекстные события из Wikidata | ctx-event-not-reused | tests/knowledge/test_epoch_context_import.py::test_repeat_apply_and_dry_run | да (1) |
| Места и координаты из Wikidata | geo-qid-shape-unchecked | tests/knowledge/test_geo_enrich.py::test_bad_external_id_never_fetched | да (1) |
| Места и координаты из Wikidata | geo-value-qid-unchecked | tests/knowledge/test_geo_enrich.py::test_skips_reasons_and_counters | да (1) |
| Места и координаты из Wikidata | geo-fetch-failed-as-skipped | tests/knowledge/test_geo_enrich.py::test_skips_reasons_and_counters | да (1) |
| Места и координаты из Wikidata | geo-skipped-entity-wrong | tests/knowledge/test_geo_enrich.py::test_skips_reasons_and_counters | да (1) |
| Места и координаты из Wikidata | geo-bad-value-as-bad-qid | tests/knowledge/test_geo_enrich.py::test_value_without_id_is_bad_value | да (1) |
| Места и координаты из Wikidata | geo-refused-as-bad-value | tests/knowledge/test_geo_enrich.py::test_skips_reasons_and_counters | да (1) |
| Места и координаты из Wikidata | geo-dry-run-writes | tests/knowledge/test_geo_enrich.py::test_dry_run_with_existing_place_writes_nothing | да (1) |
| Места и координаты из Wikidata | geo-dry-run-creates-places | tests/knowledge/test_geo_enrich.py::test_dry_run_writes_nothing | да (1) |
| Места и координаты из Wikidata | geo-rerun-counts-again | tests/knowledge/test_geo_enrich.py::test_rerun_adds_nothing | да (1) |
| Места и координаты из Wikidata | geo-time-dropped | tests/knowledge/test_geo_enrich.py::test_kant_from_wikidata | да (1) |
| Места и координаты из Wikidata | geo-place-role-dropped | tests/knowledge/test_geo_enrich.py::test_kant_from_wikidata | да (1) |
| Места и координаты из Wikidata | geo-attribution-no-link | tests/knowledge/test_geo_enrich.py::test_kant_from_wikidata | да (1) |
| Места и координаты из Wikidata | geo-status-generated | tests/knowledge/test_geo_enrich.py::test_kant_from_wikidata | да (1) |
| Места и координаты из Wikidata | geo-provenance-no-run | tests/knowledge/test_geo_enrich.py::test_kant_from_wikidata | да (1) |
| Места и координаты из Wikidata | geo-places-kept-zero | tests/knowledge/test_geo_enrich.py::test_rollback_keeps_verified_and_places | да (1) |
| Места и координаты из Wikidata | geo-influence-imported | tests/knowledge/test_geo_enrich.py::test_influence_and_foreign_properties_not_imported | да (1) |
| Места и координаты из Wikidata | geo-citizenship-imported | tests/knowledge/test_geo_enrich.py::test_influence_and_foreign_properties_not_imported | да (1) |
| Места и координаты из Wikidata | geo-activity-no-time | tests/knowledge/test_geo_enrich.py::test_activity_from_p937 | да (1) |
| Места и координаты из Wikidata | geo-birth-no-time | tests/knowledge/test_geo_enrich.py::test_kant_from_wikidata | да (1) |
| Места и координаты из Wikidata | geo-rollback-removes-verified | tests/knowledge/test_geo_enrich.py::test_rollback_keeps_verified_and_places | да (1) |
| Места и координаты из Wikidata | geo-rollback-removes-verified | tests/knowledge/test_geo_enrich.py::test_rollback_keeps_verified_and_places | да (1) |
| Язык названий сущностей | latin-ascii-only | tests/knowledge/test_entity_naming.py::test_lang_for_any_text | да (2) |
| Язык названий сущностей | greek-extended-dropped | tests/knowledge/test_entity_naming.py::test_lang_for_any_text | да (2) |
| Язык названий сущностей | other-script-as-latin | tests/knowledge/test_entity_naming.py::test_lang_for_any_text | да (3) |
| Язык названий сущностей | und-as-en | tests/knowledge/test_entity_naming.py::test_language_by_script_on_every_path | да (4) |
| Язык названий сущностей | greek-el-as-grc | tests/knowledge/test_entity_naming.py::test_language_by_script_on_every_path | да (4) |
| Язык названий сущностей | latin-en-as-la | tests/knowledge/test_entity_naming.py::test_language_by_script_on_every_path | да (7) |
| Язык названий сущностей | is-russian-ignores-latin | tests/knowledge/test_entity_naming.py::test_primary_choice_by_item | да (1) |
| Язык названий сущностей | renamed-extra-field | tests/knowledge/test_entity_naming.py::test_existing_english_entity_gets_russian_primary | да (3) |
| Валидность названий сущностей | add-name-unchecked | tests/knowledge/test_entity_naming.py::test_rejection_invariant | да (1) |
| Валидность названий сущностей | set-primary-unchecked | tests/knowledge/test_entity_naming.py::test_rejection_invariant | да (1) |
| Валидность названий сущностей | create-unchecked | tests/knowledge/test_entity_naming.py::test_section_number | да (4) |
| Нормализация сущностей | binding-by-variant-dropped | tests/knowledge/test_extraction_entities.py::test_binding_by_variant | да (1) |
| Валидность названий сущностей | core-reject-aborts | tests/knowledge/test_entity_naming.py::test_manual_core | да (1) |
| Валидность названий сущностей | core-reason-wrong | tests/knowledge/test_entity_naming.py::test_core_rejection_reasons | да (1) |
| Структурированный вывод по реестру | schema-dating-required-short | tests/knowledge/test_extraction_entities.py::test_schema_with_entities_and_dating | да (1) |
| Извлечение дат | dating-drop-doubled | tests/knowledge/test_entity_dating_extraction.py::test_year_not_in_quote | да (6) |
| Структурированный вывод по реестру | entities-required-in-answer | tests/knowledge/test_extraction_entities.py::test_schema_with_entities_and_dating | да (5) |
| Структурированный вывод по реестру | fit-no-parent | tests/knowledge/test_extraction_entities.py::test_uncertain_type_falls_back_to_general | да (1) |
| Извлечение дат | era-one-boundary-accepted | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (3) |
| Извлечение дат | century-interval-accepted | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (2) |
| Извлечение дат | unparsed-lenient | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (3) |
| Извлечение дат | single-year-dropped | tests/knowledge/test_entity_dating_extraction.py::test_dating_invariant | да (3) |

**Не покрыто:**
- «Критерий дробности из реестра» (ontology-extraction, Нормализация) — поведение реестра, вне правок этого изменения; генератора и мутации нет.
- «Ответ не по схеме отбрасывается после повторов» — поведение шлюза моделей (тесты `tests/llm`), вне кода этого изменения.
- Форма хранимого текста названия (NFD, пробелы по краям) спецификацией не определена: проверяется только решение о создании и `label` отказа.

**Дефекты:** найдены только пробелы тестов (перечислены выше), расхождений кода со спецификацией нет.

Штатный прогон `scripts/mutation_check.py --change improve-extraction-naming --id <id>` в отдельном worktree: ru-primary-not-russian → тест test_primary_choice_by_item упал; no-type-creates-entity → test_new_entity_without_type_dropped_by_code упал. Остальные мутации прогнаны тем же способом (патч в worktree от HEAD, pytest по связанным файлам), строки выше — их результат.

## Судья — третий круг, 2026-11-26, коммит 5e86f9c

Судья — новый субагент без истории разработки. Тесты гонялись по одному файлу (1 ГБ RAM). Мутации и проба системы — в отдельном `git worktree` на 5e86f9c (PYTHONPATH на worktree). Worktree удалён, `git diff -- src` пуст.

**Замечания прежних судей:**
- RUF043 закрыто: `match=r"^dating:type$"`, `ruff check` по 27 файлам изменения чисто.
- strip в property-тесте закрыто: `test_rejection_invariant` берёт сырой вход, `label` сверяется с оракулом.
- J1 закрыто: `roman-any-case` через `--id` валит оба property-теста языка.
- J3 закрыто: `reverse-interval-accepted` валит оба property-теста дат.
- Ревью О17/О18 закрыто: круг 2 кода, 49f6b99. **Но О22 (c1a9177: код и правка дельты — хранимая форма strip+NFC) ревьювер не вычитывал**: после 49f6b99 записей ревьювера в progress.md нет.

| Требование | Журнал тестировщика | Мой прогон | Вывод системы (мой фрагмент, настоящий `Filling.extract_version`, фейковая модель) | Итог |
|---|---|---|---|---|
| entity-naming «Язык названий сущностей» | аудит О21, мутации roman-any-case и др. | test_entity_naming 54 passed in 74s; roman-any-case 2/2 упали; **своя O1 выжила** | «John Locke» (en) → тот же `e_3c659bd29e3b`, основное `ru` «Локк», вариант `en`; `renamed {entity_id, lang: ru, previous_lang: en}`; справочник `q=Локк` → тот же id, `label="Локк"`; `language="ru"` в запросе | **не подтверждено** (O1) |
| entity-naming «Валидность названий сущностей» (вкл. О22 strip+NFC) | аудит, stored-raw-* | 54 passed; stored-raw-set-primary и rule-particle-case-sensitive упали; своя O2 поймана; **своя O5 выжила** | `rejected {person, "2.3", number}` + `dropped entity:number`; `rejected {person, "the teacher of Hume", not_a_name}` + `dropped entity:not_a_name` | **не подтверждено** (O5) |
| entity-dating «Извлечение дат» | аудит, мутации | test_entity_dating_extraction 15 passed in 60s; reverse-interval-accepted и check-order-era-single упали; своя O3 поймана | Локк «1632–1704» → `lifespan` (1632, 1704) `year`; произведение «1690» → `dating`; Демокрит «ок. 460–370 до н. э.» с цитатой «до н.э.» → `lifespan` approx, границы −464…−364; Спиноза «XVII в.» и Беркли «1685» → `dropped dating:single_year`; абзац 7 из 3 → `dropped dating:paragraph` | подтверждено |
| ontology-extraction «Структурированный вывод» / «Нормализация» | аудит | test_extraction_entities 16 passed; no-type-creates-entity упала; своя O4 поймана | привязка «Локк» к «John Locke» по `en`, новой персоны нет | подтверждено |
| epochs / epoch-context / geo-timeline (MODIFIED) | 6 passed | test_invalid_name_external 6 passed | — (тестовый стенд) | подтверждено |

Прочие прогоны (все passed): test_entity_items_unit 12, test_extraction_codes_unit 11, test_filling 30 (ожидания прежние). `mutation_check.py --coverage improve-extraction-naming`: мутации есть у всех 8 требований. `ruff check` и `ruff format --check` по 27 файлам изменения чисто. `lint-imports`: 3 kept, 0 broken. `check_traceability.py`: 415 из 415. Полный pytest не запускался: ограничение машины, не проверено.

Мутации из списка через `--id`: roman-any-case, reverse-interval-accepted, stored-raw-set-primary, check-order-era-single, rule-particle-case-sensitive, no-type-creates-entity. Все ожидаемые тесты упали.

Свои мутации (в списке их нет):
- **O1 (язык, п. 1).** `_ROMAN_WORD = ^[IVXCDM]+$` — без `L`. Не эквивалентна: `lang_for("Ли XL")` даёт `und` вместо `ru`, `is_russian("Пий XL")` — False вместо True, а значит меняется выбор основного. Результат: test_lang_for_any_text, test_language_invariant_create_and_add_name, test_no_latin_name_has_ru, test_naming_unit (68) прошли — **не поймана**. Причина: в `strategies.ROMAN` нет ни одного слова с `L` (L, XL, LX, LIV…).
- **O2 (порядок причин).** `not_a_name` раньше `sentence`. Упали test_check_name_any_input, test_sentence_instead_of_term, test_rejection_invariant. При этом в таблице аудита пункт «Порядок: sentence раньше not_a_name» ссылается на мутацию `rule-sentence-before-number`, которая этот порядок не ломает: строка таблицы неверна.
- **O3 (даты, Г1 ≤ Г2).** `values[0] >= values[1]`, то есть «1724–1724» → `unparsed`. Упал test_dating_check_any_input. test_dating_invariant прошёл: равных годов генератор почти не даёт, `@example` на них нет.
- **O4 (коды событий).** Новая сущность без типа даёт `entity:type` вместо `entity:no_type`. Упали test_extraction_entities (1) и test_extraction_codes_unit (1).
- **O5 (хранимая форма strip+NFC).** `naming.clean` через NFKC вместо NFC. Не эквивалентна: «Kant Hume» хранится как «Kant Hume», а 41 лигатура «ﬁ» даёт `sentence` вместо `None`, потому что знаков 82 вместо 41. Результат: test_stored_form_strip_nfc, test_stored_form_via_extraction, test_signs_counted_after_nfc прошли — **не поймана**. Причина: `raw_names` не даёт символов, которые NFC и NFKC нормализуют по-разному (внутренний EM SPACE/NBSP, лигатуры, полноширинные, надстрочные цифры).

Файлы Lead'а: в `filling.py` только точки вызова (`EntityItems`, `language`, цикл `date_item`, `accept_core_report`, перехват `InvalidName`, `entity_types()`) и данные схемы `_entities_schema`. Переход на `simple_time` относится к `add-wikidata-life-dates`. Логики правил названий и дат в этих файлах нет.

Подгонка: не найдена. Оракул стратегий не импортирует `naming`, `dating`, `dates`. Ожидания под вывод не правились: вывод системы на моём фрагменте совпадает со спецификацией. O1 и O5 — пробелы в области входов генераторов, как J1 и J3.

Вердикт: **не принято** — вернуть:
- тестировщику:
  - O1: добавить в `ROMAN` слова с `L` (L, XL, LX, LIV) и `@example` «Ли XL» → `ru` в test_lang_for_any_text и test_language_invariant_create_and_add_name;
  - O5: добавить в `raw_names` и `scripts_mix` символы, различающие NFC и NFKC (внутренний EM SPACE/NBSP, «ﬁ», полноширинные), и `@example` в test_stored_form_strip_nfc и test_signs_counted_after_nfc;
  - O1, O5 и O2 записать в `mutations.yaml` с ожидаемыми property-тестами;
  - исправить строку аудита «sentence раньше not_a_name» (мутация O2);
  - желательно: `@example` равных годов «1724–1724» в test_dating_invariant;
- ревьюверу: вычитать О22 (c1a9177 и правку дельты `entity-naming`, определение «Название»).

Разработчику и Lead'у возвратов нет.

## Тестировщик — О22/О23 (2026-11-26, коммиты 09be57a, 0f531e4)

Возврат судьи третьего круга (O1, O2-строка аудита, O5, O3-пожелание) и правило О23: каждое множество спецификации — в генераторах целиком, плюс «похожие вне множества».

Генераторы (`tests/knowledge/strategies.py`):
- римские: `ROMAN_LETTERS = "IVXLCDM"`; вид `roman` в `scripts_mix` берёт `ROMAN` (все семь букв по одной и L, XL, LX, LIV, XLIV, CD, DC, CM, MCM, MMXXIV, LXXX) или произвольное слово из `IVXLCDM`; «похожие вне множества» `ROMAN_LOOKALIKE` — строчные и смешанный регистр (l, xl, Xl, xL, Liv, Mdc, Civil, Mill);
- знаки края слова — весь `EDGE_MARKS` слева и справа; пробельные `WHITESPACE` (пробел, таб, перевод строки, NBSP, EM SPACE, U+3000) между словами;
- NFC ≠ NFKC: лигатуры ﬁ ﬂ (латинская буква по имени), полноширинные ａ ｂ ｋ (буква «прочая»), надстрочные ² ¹ ™ у цифр; NFC ≠ NFD — `raw_names` (NFD входа);
- границы письменностей: U+0400/U+0450, U+052F, U+0371, U+03FF, U+1F00, U+1FF3.

Новый тест `tests/knowledge/test_strategies_cover_spec_sets.py`: множества переписаны из спецификаций руками (без импорта `naming`/`dating`/`dedupe`), для каждого элемента `hypothesis.find` ищет пример в генераторе. Прогон: 82 теста (римские буквы ×7 и похожие, знаки края ×18, границы письменностей ×9, письменности и языки п. 5, пробельные ×5, NFC≠NFKC/NFD, причины ×6, данные правил, тире/маркеры ×7, причины датировки по порядку ×7, точности Wikidata ×10, ранги и решения, коды person-quality ×8, коды сценариев) — 82 passed в 217 с (последний прогон после правки шагов 8–9: test_person_scenario_codes passed). Найденные им пробелы закрыты: `review:qid_taken` (test_life_dates::test_qid_taken_queued, `auto` и не-персона), `apart:none`, `review:single_name`, `review:variant` в таблице шагов (test_person_quality::test_same_person_step_order, 11 passed).

Явные `@example`: «Ли XL», «Пий XL», «Ли L», «Ли LX LIV» → `ru`; «Ли xl» → `und`; «Лии Xl» → `ru`; «Кк ﬁ» → `ru`, «К ﬁﬁ» → `en`, «Ｋａｎｔ» → `und`, «Кант Kant» → `und` (test_lang_for_any_text); `("Ли XL","en")`/«Пий LIV» (test_language_invariant_create_and_add_name); «Kant Hume», «ﬁlosoﬁa», «Ｋａｎｔ», «Kant Hume», «Декарт²», «Пий XL» (test_stored_form_strip_nfc); «ﬁ»×41/×80 → нет причины, ×81 → `sentence`, «Ｋ»×80 (test_signs_counted_after_nfc); «1724–1724», «1690–1690» (EXAMPLES test_dating_invariant).

Прогоны (по одному файлу): test_entity_naming 58 passed (68 с); test_person_quality 43 passed (86 с); test_invalid_name_external 6 passed; test_entity_dating_extraction 15 passed (38 с); test_life_dates::test_qid_taken_queued 2 passed. ruff check/format чисто; traceability 415/415.

Мутации — штатный `scripts/mutation_check.py --change improve-extraction-naming --id <id>` в отдельном worktree на 0f531e4:

| Требование | Мутация | Ожидаемый тест | Упал |
|---|---|---|---|
| Язык названий сущностей | roman-without-l (O1) | test_entity_naming.py::test_lang_for_any_text | да (1 failed) |
| Язык названий сущностей | roman-without-l (O1) | test_entity_naming.py::test_language_invariant_create_and_add_name | да (1 failed) |
| Валидность названий сущностей | not-a-name-before-sentence (O2) | test_entity_naming.py::test_check_name_any_input | да (1 failed) |
| Валидность названий сущностей | not-a-name-before-sentence (O2) | test_entity_naming.py::test_rejection_invariant | да (1 failed) |
| Валидность названий сущностей | clean-nfkc (O5) | test_entity_naming.py::test_stored_form_strip_nfc | да (1 failed) |
| Валидность названий сущностей | clean-nfkc (O5) | test_entity_naming.py::test_signs_counted_after_nfc | да (1 failed, 3 passed) |
| Валидность названий сущностей | stored-raw-create | test_entity_naming.py::test_stored_form_strip_nfc | да (1 failed) |
| Валидность названий сущностей | stored-raw-create | test_entity_naming.py::test_stored_form_via_extraction | да (1 failed) |
| Валидность названий сущностей | stored-raw-add-name | test_entity_naming.py::test_stored_form_strip_nfc | да (1 failed) |
| Валидность названий сущностей | stored-raw-set-primary | test_entity_naming.py::test_stored_form_strip_nfc | да (1 failed) |

Строка аудита «Порядок: `sentence` раньше `not_a_name`» исправлена: мутация — `not-a-name-before-sentence` (меняет местами именно эти два правила).

Ограничение: «цифра» для правила `number` спецификацией не уточнена (Nd или любая `isdigit`); надстрочные цифры поэтому порождаются только рядом с обычными цифрами и в `raw_names`, а не как единственный знак названия.

## Судья — четвёртый круг, 2026-11-26, коммит 9ae5ee1

Судья — новый субагент без истории разработки. Тесты гонялись по одному файлу (1 ГБ RAM). Мутации и проба системы — в отдельном `git worktree` на 9ae5ee1. Worktree удалён, `git diff -- src` пуст.

**Замечания прежних судей:**
- O1 (римская L) закрыто: `roman-without-l` через `--id` валит test_lang_for_any_text и test_language_invariant_create_and_add_name.
- O5 (NFC/NFKC) закрыто: `clean-nfkc` валит test_stored_form_strip_nfc и test_signs_counted_after_nfc.
- Строка аудита порядка закрыто: строка 314 ссылается на `not-a-name-before-sentence`. Эта мутация меняет местами `sentence` и `not_a_name` и валит оба property-теста.
- Ревью О22 закрыто: раздел ревьювера в progress.md, коммит 126d217. Его пожелание о пересчёте `normalized` ушло в шаг `normalize_names` изменения `migrate-ontology-quality`.
- J1, J3 закрыто: `reverse-interval-accepted` валит оба property-теста дат.
- strip закрыто: test_rejection_invariant берёт сырой вход.
- RUF043 закрыто: `ruff check` чисто.

**Тест полноты стратегий** (`test_strategies_cover_spec_sets.py`, 82 passed in 114 s). Я сверил его с текстом spec:
- Совпадает со spec: римские буквы `IVXLCDM` и похожие вне множества, знаки края, диапазоны письменностей, таблица языков п. 5, 5 причин названий, пределы, частицы, тире, «около», эры текста и цитаты, века I–XXI, 6 причин датировки по порядку.
- Проверяемый код он не использует: `naming`, `dating` и `dedupe` в оракуле не участвуют.
- Замечание (не дефект): `raw_names` импортируется из `test_entity_naming`, а тот загружает `naming`. В оракул это не попадает, но генератор лучше перенести в `strategies.py`.
- Пробелы. Для эры текста нет «похожих вне множества»: нигде не порождается текст даты с `до нашей эры`. Регистр проверяется только у «около», а у маркера эры и `в.` нет, хотя spec требует «сравнение без учёта регистра». Для нормализованного названия нет знаков, которые `\w` считает словом, хотя это не буква и не цифра: `_`.

| Требование | Журнал тестировщика | Мой прогон | Вывод системы (мой фрагмент, настоящий `Filling.extract_version`, фейковая модель) | Итог |
|---|---|---|---|---|
| entity-naming «Язык названий сущностей» | О22/О23, roman-without-l | test_entity_naming 58 passed in 46 s; roman-without-l 2/2 упали | «George Berkeley» (en) → тот же id, основное `ru` «Беркли», вариант `en`; `renamed {entity_id, lang: ru, previous_lang: en}`; «Юм» `ru`, «David Hume» `en` | подтверждено |
| entity-naming «Валидность названий сущностей» | О22/О23, clean-nfkc, not-a-name-before-sentence | 58 passed; clean-nfkc 2/2 и not-a-name-before-sentence 2/2 упали; своя N10 поймана; **своя N11 выжила** | `rejected {person, "§ 4.2", number}` + `dropped entity:number`; `rejected {person, "Hume and Berkeley", not_a_name}` + `dropped entity:not_a_name`; ru `" Юм "` хранится «Юм» | **не подтверждено** (N11) |
| entity-dating «Извлечение дат» | аудит, reverse-interval-accepted | test_entity_dating_extraction 15 passed in 31 s; reverse-interval-accepted 2/2 упали; своя D6 поймана; **свои D1 и D5 выжили** | Юм «1711–1776» → `lifespan` (1711, 1776) `year`; Сократ «470–399 ДО Н. Э.» → (−469, −398) `year`; событие «XVIII в.» → `dating`, 1701…1800 `century`; Аристотель «384–322 до нашей эры» → `dropped dating:unparsed` | **не подтверждено** (D1, D5) |
| ontology-extraction «Структурированный вывод» / «Нормализация» | аудит | test_extraction_entities 16 passed | «Беркли» привязан к «George Berkeley» по `en`, новой персоны нет | подтверждено |
| epochs / epoch-context / geo-timeline (MODIFIED) | 6 passed | test_invalid_name_external 6 passed | — | подтверждено |

Прочие прогоны (все passed): test_entity_items_unit 12, test_extraction_codes_unit 11, test_filling 30. `mutation_check.py --coverage improve-extraction-naming`: мутации есть у всех 8 требований. `ruff check` и `ruff format --check` по 60 .py файлам диффа чисто. `lint-imports`: 3 kept, 0 broken. `check_traceability.py`: 415 из 415. Полный pytest не запускался из-за ограничения машины, не проверено.

Мутации из списка через `--id`: roman-without-l, clean-nfkc, not-a-name-before-sentence, reverse-interval-accepted. Все ожидаемые тесты упали.

Свои мутации (в списке их нет). Тестовый файл требования прогонялся целиком:
- **D1 (даты, маркер эры в тексте).** В `_ERA_TEXT` добавлено `|до\s+нашей\s+эры`. Не эквивалентна. В spec маркер эры в тексте даты — только `до н. э.`/`до н.э.`, а `до нашей эры` допускается лишь в цитате. Оригинал на «384–322 до нашей эры» даёт `dating:unparsed`. Мутант записывает FuzzyDate 322…384 н. э., то есть неверную эру. Результат: test_entity_dating_extraction 15 passed, **не поймана**. Причина: в генераторе `datings` (и в `UNPARSED`) нет текста даты с `до нашей эры`.
- **D5 (даты, регистр маркера эры).** В `era_text` убран `.lower()`. Не эквивалентна. По spec «427–347 ДО Н. Э.» — допустимый формат, сравнение без учёта регистра. Оригинал записывает (−426, −346), мутант даёт `dating:era`. Результат: 15 passed, **не поймана**. Причина: регистр меняется только у маркера «около», а у маркера эры и `в.` нет.
- **D6 (даты, римское число в цитате отдельным словом).** Убран `strip(_EDGE)`. Поймана: 2 failed (property-тесты дат).
- **N10 (названия, слова по `str.split()`).** Вместо него `split(" ")`. Поймана: test_entity_naming 2 failed.
- **N11 (нормализованное название).** В `normalize` убрано `|_`, то есть `_` больше не заменяется пробелом. Не эквивалентна. По spec заменяется пробелом каждый символ, который не буква, не цифра и не пробел. Оригинал: `check_name("concept", "some_")` = `stopword`, `normalize("Kant_Hume")` = «kant hume». У мутанта `None` и «kant_hume»: отказ теряется, поиск сущности по названию меняется. Результат: test_entity_naming 58 passed, **не поймана**. Причина: генераторы стоп-слов и названий не порождают `_` и другие знаки, которые регулярное выражение `\w` считает частью слова.

Файлы Lead'а: в `filling.py` только точки вызова: `EntityItems`, `language`, цикл `date_item`, `accept_core_report`, перехват `InvalidName`, `entity_types()`. К ним добавлены данные схемы и перенос `WIKIDATA_ROLES`/`simple_time` в `wikidata.py` (это `add-wikidata-life-dates`). Логики правил названий и дат здесь нет.

Подгонка: не найдена. Ожидания под вывод не правились, на моём фрагменте вывод системы совпадает со spec. D1, D5 и N11 — пробелы в области входов генераторов того же класса, что O1, O5, J1 и J3. Код верен, но property-тесты нарушение этих правил не ловят. Требование владельца («каждое требование доказано property-проверкой, падающей при нарушении») для двух требований не выполнено.

Вердикт: **не принято** — вернуть тестировщику:
- D1: в `datings` (unparsed) порождать текст даты с `до нашей эры`, то есть маркеры цитаты вне множества маркеров текста. В `test_strategies_cover_spec_sets` проверять, что для каждого элемента `ERA_QUOTE − ERA_TEXT` текст даты даёт `dating:unparsed`;
- D5: менять регистр маркера эры и `в.` в тексте даты, в том числе у годных датировок. В тесте полноты стратегий проверять, что регистр меняется у каждого маркера;
- N11: в генераторах стоп-слов и названий порождать знаки, которые `\w` считает словом, хотя это не буква и не цифра (`_`), и добавить `@example` `"some_"` → `stopword`;
- D1, D5 и N11 записать в `mutations.yaml` с ожидаемыми property-тестами;
- желательно: перенести `raw_names` в `strategies.py`.

Разработчику, ревьюверу и Lead'у возвратов нет. Это последний допустимый круг цикла: решение о дальнейшем — за ведущим и владельцем.

## Тестировщик — D1, D5, N11 (2026-11-26, коммиты 774b525 и следующий)

Возврат судьи четвёртого круга (dfb00a3).
- D1: в `UNPARSED` — тексты даты с маркером только цитаты («384–322 до нашей эры», «ок. 470 до нашей эры», «V в. до нашей эры», «427 ДО НАШЕЙ ЭРЫ»); @example «384–322 до нашей эры» → `dating:unparsed` (EXAMPLES). В тесте полноты `test_quote_only_era_marker_unparsed`: для каждого маркера `ERA_QUOTE − ERA_TEXT` генератор даёт текст даты с ним и причиной `dating:unparsed`.
- D5: `_any_case` — маркер эры, «около» и «в.» в любом регистре (как есть, ВЕРХНИЙ, С заглавной, вперемешку) у годных и негодных датировок; удаление эры из цитаты для целей `era`/`not_in_quote` — без учёта регистра (`_drop_era`). @example «427–347 ДО Н. Э.» → (−426, −346) `year`, «XVIII В.» → 1701…1800 `century`. Тест полноты `test_marker_case_generated` — по каждому маркеру `ERA_TEXT ∪ APPROX ∪ {в.}`.
- N11: `stopwords_perturbed` — «_» как разделитель и по краям; @example «some_», «_some» → `stopword`, «every_one» → нет причины (BOUNDARY_EXAMPLES); тест полноты `test_underscore_generated`.
- `raw_names` перенесён в `strategies.py`; тест полноты больше не импортирует `test_entity_naming` (и через него `naming`): 91 passed в 224 с без предупреждения FastAPI.

Прогоны: test_entity_dating_extraction 15 passed (38 с); test_entity_naming 58 passed (30 с); test_strategies_cover_spec_sets 91 passed (224 с).

Побочная находка при прогоне: мой первый вариант генератора давал «Iв.» без пробела. По spec римское число века должно стоять в цитате отдельным словом, поэтому `not_in_quote` здесь верен. Вариант убран, формат «R в.» оставлен с пробелом.

Мутации — штатный `mutation_check.py --id` в отдельном worktree:

| Требование | Мутация | Ожидаемый тест | Упал |
|---|---|---|---|
| Извлечение дат | era-text-nashei (D1) | test_entity_dating_extraction.py::test_dating_check_any_input | да (1 failed) |
| Извлечение дат | era-text-nashei (D1) | test_entity_dating_extraction.py::test_dating_invariant | да (1 failed) |
| Извлечение дат | era-text-case (D5) | test_entity_dating_extraction.py::test_dating_check_any_input | да (1 failed) |
| Извлечение дат | era-text-case (D5) | test_entity_dating_extraction.py::test_dating_invariant | да (1 failed) |
| Валидность названий сущностей | normalize-keeps-underscore (N11) | test_entity_naming.py::test_check_name_any_input | да (1 failed) |

Первая версия D1 (`|до\s+нашей\s+эры` без группы) оказалась эквивалентной. Из-за приоритета `|` в `(?P<era>\s+…)` она не принимала «… до нашей эры», поэтому оба теста прошли. Патч переписан с группой `(?:…|…)`: так мутант действительно принимает маркер, и он упал.

## Тестировщик — О26 (все пары порядка, обход после пропуска), 2026-11-26, тесты на 1978deb

Подробности — в `improve-person-quality/verification.md`, раздел «О26». Здесь — итог по naming и dating.

- `test_rule_order_pairs`: 6 возможных пар правил, 6 невозможных; `test_dating_check_order_pairs`: 14 пар, 1 невозможная; оба `*_complete` сверяют перечень пар со спецификацией.
- Обход после пропуска: в `names_for` выжила `names-for-stops-after-rejected` — закрыта случаем `test_primary_choice_by_item[item4]`.
- 11 устаревших патчей (после О22) сняты заново от HEAD. У `reject-label-raw` ожидаемый тест заменён на `test_rejected_variant_label_after_strip`: прежние пути больше не доходят до `reject` с сырым текстом.

`scripts/mutation_check.py --change improve-extraction-naming --id <id>`:

| Требование | Мутация | Ожидаемый тест | Упал |
|---|---|---|---|
| Извлечение дат | check-order-unparsed-paragraph | tests/knowledge/test_entity_dating_extraction.py::test_dating_check_order_pairs | да (1 failed, 7 passed, 1 warning in 0.30s) |
| Извлечение дат | check-order-era-quote | tests/knowledge/test_entity_dating_extraction.py::test_dating_check_order_pairs | да (1 failed, 1 passed, 1 warning in 0.27s) |
| Извлечение дат | check-order-era-unparsed | tests/knowledge/test_entity_dating_extraction.py::test_dating_check_order_pairs | да (1 failed, 1 passed, 1 warning in 0.24s) |
| Извлечение дат | check-order-single-numbers | tests/knowledge/test_entity_dating_extraction.py::test_dating_check_order_pairs | да (1 failed, 1 warning in 0.24s) |
| Извлечение дат | check-order-numbers-quote | tests/knowledge/test_entity_dating_extraction.py::test_dating_check_order_pairs | да (1 failed, 8 passed, 1 warning in 0.34s) |
| Валидность названий сущностей | rule-sentence-before-number | tests/knowledge/test_entity_naming.py::test_rule_order_pairs | да (1 failed, 1 warning in 0.39s) |
| Валидность названий сущностей | rule-sentence-before-number | tests/knowledge/test_entity_naming.py::test_check_name_any_input | да (1 failed, 1 warning in 0.99s) |
| Валидность названий сущностей | not-a-name-before-sentence | tests/knowledge/test_entity_naming.py::test_rule_order_pairs | да (1 failed, 5 passed, 1 warning in 0.29s) |
| Валидность названий сущностей | not-a-name-before-sentence | tests/knowledge/test_entity_naming.py::test_check_name_any_input | да (1 failed, 1 warning in 0.48s) |
| Валидность названий сущностей | not-a-name-before-sentence | tests/knowledge/test_entity_naming.py::test_rejection_invariant | да (1 failed, 1 warning in 1.39s) |
| Валидность названий сущностей | stopword-before-person | tests/knowledge/test_entity_naming.py::test_rule_order_pairs | да (1 failed, 2 passed, 1 warning in 0.32s) |
| Валидность названий сущностей | stopword-before-person | tests/knowledge/test_entity_naming.py::test_role_instead_of_name | да (1 failed, 1 warning in 1.14s) |
| Валидность названий сущностей | stopword-before-person | tests/knowledge/test_entity_naming.py::test_check_name_any_input | да (1 failed, 1 warning in 0.73s) |
| Валидность названий сущностей | stopword-before-person | tests/knowledge/test_entity_naming.py::test_rejection_invariant | да (1 failed, 1 warning in 3.15s) |
| Валидность названий сущностей | add-name-unchecked | tests/knowledge/test_entity_naming.py::test_rejection_invariant | да (1 failed, 1 warning in 3.25s) |
| Язык названий сущностей | create-lang-given | tests/knowledge/test_entity_naming.py::test_language_by_script_on_every_path | да (1 failed, 1 warning in 1.94s) |
| Язык названий сущностей | create-lang-given | tests/knowledge/test_entity_naming.py::test_language_invariant_create_and_add_name | да (1 failed, 1 warning in 1.14s) |
| Язык названий сущностей | create-lang-given | tests/knowledge/test_naming_entities_unit.py::test_create_sets_lang_by_script | да (1 failed in 0.41s) |
| Валидность названий сущностей | create-unchecked | tests/knowledge/test_entity_naming.py::test_section_number | да (1 failed, 1 warning in 1.07s) |
| Валидность названий сущностей | create-unchecked | tests/knowledge/test_entity_naming.py::test_manual_core | да (1 failed, 1 warning in 0.79s) |
| Валидность названий сущностей | create-unchecked | tests/knowledge/test_entity_naming.py::test_rejection_invariant | да (1 failed, 1 warning in 3.03s) |
| Валидность названий сущностей | create-unchecked | tests/knowledge/test_entity_naming.py::test_rejected_label_is_name_after_strip | да (1 failed, 1 warning in 0.89s) |
| Валидность названий сущностей | rejected-extra-field | tests/knowledge/test_entity_naming.py::test_section_number | да (1 failed, 1 warning in 1.65s) |
| Валидность названий сущностей | rejected-extra-field | tests/knowledge/test_entity_naming.py::test_manual_core | да (1 failed, 1 warning in 2.53s) |
| Валидность названий сущностей | rejected-extra-field | tests/knowledge/test_entity_naming.py::test_rejection_invariant | да (1 failed, 1 warning in 2.72s) |
| Валидность названий сущностей | rejected-extra-field | tests/knowledge/test_entity_naming.py::test_rejected_label_is_name_after_strip | да (1 failed, 1 warning in 1.64s) |
| Валидность названий сущностей | rule-empty-as-number | tests/knowledge/test_entity_naming.py::test_empty_names | да (1 failed, 1 warning in 1.70s) |
| Валидность названий сущностей | rule-empty-as-number | tests/knowledge/test_entity_naming.py::test_check_name_any_input | да (1 failed, 1 warning in 1.91s) |
| Валидность названий сущностей | rule-empty-as-number | tests/knowledge/test_naming_unit.py::test_check_name | да (1 failed in 0.15s) |
| Валидность названий сущностей | rule-exempt-ignored | tests/knowledge/test_entity_naming.py::test_rules_are_data | да (1 failed, 6 passed, 1 warning in 4.18s) |
| Валидность названий сущностей | rule-exempt-ignored | tests/knowledge/test_entity_naming.py::test_check_name_any_input | да (1 failed, 1 warning in 1.40s) |
| Валидность названий сущностей | rule-exempt-ignored | tests/knowledge/test_naming_unit.py::test_check_name | да (1 failed, 33 passed in 0.20s) |
| Валидность названий сущностей | rule-no-nfc | tests/knowledge/test_entity_naming.py::test_signs_counted_after_nfc | да (1 failed, 1 warning in 1.16s) |
| Валидность названий сущностей | rule-no-strip | tests/knowledge/test_entity_naming.py::test_signs_counted_after_nfc | да (1 failed, 2 passed, 1 warning in 2.07s) |
| Валидность названий сущностей | set-primary-unchecked | tests/knowledge/test_entity_naming.py::test_rejection_invariant | да (1 failed, 1 warning in 2.86s) |
| Валидность названий сущностей | reject-label-raw | tests/knowledge/test_entity_naming.py::test_rejected_variant_label_after_strip | да (1 failed, 1 warning in 0.63s) |
| Язык названий сущностей | names-for-stops-after-rejected | tests/knowledge/test_entity_naming.py::test_primary_choice_by_item | да (1 failed, 4 passed, 1 warning in 0.42s) |

(Первый прогон `reject-label-raw` до замены ожидания: test_rejection_invariant и test_rejected_label_is_name_after_strip — НЕТ, см. выше.)

## Тестировщик — патчи сняты заново после 0b8b44e (`set_primary_name(conn=)`), 2026-11-26

| Требование | Мутация | Ожидаемый тест | Упал |
|---|---|---|---|
| Валидность названий сущностей | set-primary-unchecked | tests/knowledge/test_entity_naming.py::test_rejection_invariant | да (1 failed, 1 warning in 1.45s) |
| Валидность названий сущностей | stored-raw-set-primary | tests/knowledge/test_entity_naming.py::test_stored_form_strip_nfc | да (1 failed, 1 warning in 1.01s) |

## Тестировщик — J8 (правила по типу), патчи после 40bae79, 2026-11-26

Новые тесты. В `test_primary_choice_by_item` добавлены 6 случаев с расхождением правил по типу:
- ru «слепой математик»: у персоны отклонено, у понятия стало основным;
- вариант en «blind mathematics»: у персоны отброшен, у понятия записан;
- ru из 8 слов: у произведения стало основным, у понятия отклонено (sentence).

Ещё два теста:
- `test_new_entity_spellings_checked_by_type`: новая персона из ответа с ru «слепой математик» → ru не записан, `rejected` с `not_a_name`;
- `test_event_label_checked_by_event_rule` (epoch-context): событие с названием из 9 слов создано (предел event — 12), `rejected` нет.

Мутации и сводка обхода — в verification.md migrate-ontology-quality, раздел J8. `renamed-extra-field`: после 40bae79 `-C0` вставил строку не туда, и тесты не собрались (`НЕТ ()`). Патч переписан на поля события в `rename_in`.

`--id` (под flock):

| Требование | Мутация | Тест | Убита |
|---|---|---|---|
| Валидность названий сущностей | entities-check-as-concept | tests/knowledge/test_entity_naming.py::test_core_rejection_reasons | да (1 failed, 1 warning in 1.27s) |
| Валидность названий сущностей | entities-check-as-concept | tests/knowledge/test_entity_naming.py::test_description_with_capital | да (1 failed, 1 warning in 0.73s) |
| Валидность названий сущностей | entities-check-as-concept | tests/knowledge/test_entity_naming.py::test_glued_names | да (1 failed, 1 warning in 1.23s) |
| Контекстные события из Wikidata | invalid-primary-as-concept | tests/knowledge/test_epoch_context_import.py::test_event_label_checked_by_event_rule | да (1 failed in 0.73s) |
| Контекстные события из Wikidata | epoch-context-primary-as-concept | tests/knowledge/test_epoch_context_import.py::test_event_label_checked_by_event_rule | да (1 failed in 0.61s) |
| Язык названий сущностей | names-for-ru-as-concept | tests/knowledge/test_entity_naming.py::test_primary_choice_by_item | да (1 failed, 4 passed, 1 warning in 0.30s) |
| Язык названий сущностей | names-for-ru-as-concept | tests/knowledge/test_entity_naming.py::test_new_entity_spellings_checked_by_type | да (1 failed, 1 warning in 1.44s) |
| Язык названий сущностей | names-for-variant-as-concept | tests/knowledge/test_entity_naming.py::test_primary_choice_by_item | да (1 failed, 4 passed, 1 warning in 0.30s) |
| Язык названий сущностей | items-names-for-as-concept | tests/knowledge/test_entity_naming.py::test_new_entity_spellings_checked_by_type | да (1 failed, 1 warning in 1.03s) |
| Язык названий сущностей | items-russian-primary-as-concept | tests/knowledge/test_entity_naming.py::test_rejected_russian_spelling | да (1 failed, 1 warning in 1.06s) |
| Язык названий сущностей | renamed-previous-lang-wrong | tests/knowledge/test_entity_naming.py::test_existing_english_entity_gets_russian_primary | да (1 failed, 1 warning in 1.24s) |
| Язык названий сущностей | renamed-previous-lang-wrong | tests/knowledge/test_naming_entities_unit.py::test_set_primary_name_keeps_id | да (1 failed in 0.48s) |
| Язык названий сущностей | rename-keeps-old-primary | tests/knowledge/test_entity_naming.py::test_existing_english_entity_gets_russian_primary | да (1 failed, 1 warning in 1.25s) |
| Язык названий сущностей | rename-keeps-old-primary | tests/knowledge/test_naming_entities_unit.py::test_set_primary_name_keeps_id | да (1 failed in 0.45s) |
| Язык названий сущностей | rename-keeps-old-primary | tests/knowledge/test_naming_entities_unit.py::test_set_primary_name_promotes_variant | да (1 failed in 0.49s) |
| Валидность названий сущностей | set-primary-unchecked | tests/knowledge/test_entity_naming.py::test_rejection_invariant | да (1 failed, 1 warning in 1.61s) |
| Валидность названий сущностей | stored-raw-set-primary | tests/knowledge/test_entity_naming.py::test_stored_form_strip_nfc | да (1 failed, 1 warning in 1.17s) |
| Язык названий сущностей | renamed-extra-field | test_entity_naming.py::test_existing_english_entity_gets_russian_primary, test_extraction_entities.py::test_binding_by_english_spelling, ::test_normalization_and_language_for_any_items | да (повтор после переписи патча) |

## Тестировщик — О35: журнал команд при настоящем запуске, 2026-11-26, код de7e9bd

**Дефект Д5: команды `geo_enrich`, `epoch_dates` и `epoch_context` не подключают журнал.**
- Ожидалось по спецификации: события `knowledge.geo.*`, `knowledge.epoch_dates.*`, `knowledge.context_import.*` при запуске командой.
- Получено: в stderr событий нет.
- Красные тесты: `test_geo_enrich_journal`, `test_epoch_dates_journal`, `test_epoch_context_journal` (`tests/knowledge/test_operator_commands_journal.py`).
- Если подключить приёмник в процессе-обёртке, все три теста зелёные. Подробно — в verification.md migrate-ontology-quality, раздел «третий возврат».
