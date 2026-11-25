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
