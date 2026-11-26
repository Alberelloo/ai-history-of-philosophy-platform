# Verification: reextract-with-claude

## Тестировщик — 2026-11-26, ветка `claude/reextract-claude` (тесты и мутации — коммиты `wip(reextract-with-claude): тесты …`)

Тесты написаны по дельтам `specs/ontology-extraction` и `specs/llm-gateway` и `tasks.md` 3.x; код читался только ради точек входа (`Filling.extract_version/apply_reply/fragments`, `external_extraction.main/ingest`, `LLMGateway.role_info`, маршруты) и имён событий. Ожидания под вывод не подгонялись: четыре красных теста ниже — дефекты кода.

### Найденные дефекты кода (тесты красные, продуктовый код не правился)

| # | Ожидалось по спецификации | Получено | Тест |
|---|---|---|---|
| Д1 | «Проверка ответа по утверждениям», п. 3 и шаг 1: `paragraph` строкой не из цифр, а иначе не целым → отказ элемента `schema_item`, остальные элементы пишутся. Надстрочная цифра `"²"` (`str.isdigit()` истинно) — «не строка из цифр» → `schema_item` | `Filling._item` падает `ValueError: invalid literal for int() with base 10: '²'` (filling.py:600); исключение не поймано, **фрагмент и весь запуск валятся** (`failed`), остальные элементы не записаны | `tests/knowledge/test_reextract_items.py::test_item_fault_is_isolated_and_coded[paragraph надстрочная цифра]` |
| Д2 | «Внешний извлекатель»: ответ с номером вне фрагментов игнорируется, событие `reply_invalid`; остальные ответы пишутся. Ключ `"²"` — не номер | `ingest` падает `ValueError` на `int(key)` (external_extraction.py:265), запуск `failed`, команда падает трассировкой вместо кода выхода/события | `tests/knowledge/test_reextract_external.py::test_reply_out_of_range_ignored[²]` |
| Д3 | «Запуски наполнения», «Запуск всегда завершается»: после выхода из `extract_version` запуск MUST NOT оставаться `running`. Любое исключение после начала запуска → `failed` | `finish_run` вызывается **вне** `try` в `extract_version`: если сводка расходов шлюза (`GET /v1/spend`) отдала 200 с телом не-JSON или не списком, `_run_spend` бросает `ValueError`/`AttributeError` и запуск остаётся `status=running` без `finished_at` | `tests/knowledge/test_reextract_runs.py::test_no_running_run_when_spend_summary_is_broken[not-json]`, `[object]` |

Заметки без падения (не по дельте, для сведения ведущему): `Statements.add` принимает самосвязь `influenced_by` (Кант → Кант) и уточнитель `time` со строкой «когда-нибудь»; значение уточнителя вне перечня даёт `qualifier_invalid`, а не `statement_refused` (в таблице кодов «уточнитель вне реестра» — трактуется шире). Спецификацией не заданы, тестами не фиксируются.

### Прежний контракт (3.3)

| Тест | Что менялось | Решение |
|---|---|---|
| `test_entity_dating_extraction.py` ×5 (`test_century_not_in_quote`, `test_era_mismatch`, `test_year_not_in_quote`, `test_number_inside_number`, `test_single_year_person`) | событие `dropped` теперь `{run_id, reason, code}` | **согласен**: дельта «Коды причин отбраковки». Хелпер `_rejected` проверяет `code == reason` с `dating:`→`dating_` и ключи `{run_id, reason, code}` |
| `test_extraction_entities.py::test_new_entity_without_type_dropped_by_code` | то же | **согласен**: `code == "entity_no_type"`, ключи `{reason, code}` |
| `test_extraction_entities.py::test_schema_with_entities_and_dating` | схема шлюза мягкая: нет `enum`, нет `properties/required` у `dating` | **согласен**: дельта «Мягкая схема в запросе» (MUST NOT enum и типов у полей). Допустимые типы теперь проверяются через `data["entity_types"]`; схема реестра остаётся контрактом (`test_registry_schema_stays_contract`) |
| `test_mentions_cards.py::test_migration_6_adds_mention_position`, `test_portraits.py::test_migration_7_…` (×2 утверждения) | последняя миграция 10 | **согласен**: дельта вводит `knowledge:10` |
| `test_epoch_dates_unit.py::test_repository_manifest_is_valid_and_unconfirmed` | — | **не наше**: падает и на `origin/claude/embedding-docker` (c9a02aa, чистый worktree: `1 failed in 0.25s`, `all(...)` по эпохам без QID); файл `sources/epochs.yaml` изменением не затронут |

### Матрица «требование → сценарий / инвариант → тест → результат»

Файлы: `F`=`tests/knowledge/test_reextract_fragments.py`, `Q`=`…_quotes.py`, `I`=`…_items.py`, `R`=`…_runs.py`, `X`=`…_external.py`, `P`=`…_prompt.py`, `G`=`tests/llm/test_reextract_role_spend.py`. Результат — прогон 2026-11-26 (см. «Команды»). Журнал проверяется в каждом тесте (`events.of/one/where`, точный набор ключей `{run_id, reason, code}` через `assert_event_keys`).

| Требование (возможность) | Сценарий / инвариант | Тест | Вывод и журнал | Рез. |
|---|---|---|---|---|
| Фрагменты из нескольких абзацев (ontology-extraction) | Утверждение на границе | `F::test_statement_on_boundary_is_stored_once` | запросы шлюза `[1,2],[1,2]`; 1 утверждение; `knowledge.statement.created`×1; fragment `paragraphs=[2,2]` | ok |
| то же | Короткие абзацы собираются в один фрагмент | `F::test_short_paragraphs_gather_by_volume` | 40×130 → фрагменты 24 и 17, второй с 24-го; fragment `paragraphs=[24,17]`, ключи `{paragraphs,created,dropped}` | ok |
| то же | Длинный абзац — отдельный фрагмент | `F::test_long_paragraph_is_its_own_fragment` | `[[1],[2,3]]`, fragment `[1,2]` | ok |
| то же | Предел числа абзацев | `F::test_paragraph_limit_gives_overlapping_pairs` | `[1,2],[2,3],[3,4],[4,5]` | ok |
| то же | инвариант: границы главы, 1…size, покрытие, правило окончания, перекрытие | `F::test_fragment_rules_property` (300 примеров, эталон по тексту дельты + правила порознь) | — | ok |
| то же | инвариант: `changed` | `F::test_changed_filters_fragments_property`, `F::test_changed_limits_extraction_run` | в запросы уходят только фрагменты с изменённым абзацем; `filling_runs.fragments=2` | ok |
| Цитата у каждого утверждения | Цитата не найдена | `Q::test_quote_not_found` | нет утверждений; `dropped code=quote_not_found`, без текста цитаты | ok |
| то же | Цитата в кавычках и с другим тире | `Q::test_outer_quotes_and_other_dash` | утверждение записано, в подтверждении цитата модели как есть | ok |
| то же | Многоточие-пропуск (по порядку / обратный порядок) | `Q::test_ellipsis_gap_in_order_and_reversed` | записано одно; второе `quote_not_found` | ok |
| то же | Мягкий перенос и ударение | `Q::test_soft_hyphen_and_accent` | записано оба | ok |
| то же | Сирот нет | `Q::test_no_orphans` (quote_not_found / paragraph_out_of_window / quote_too_short), `Q::test_refusal_creates_no_entities_with_attribution_and_entities_block` | ни персон, ни объектов, ни автора атрибуции; `knowledge.entity.created` только `source`; код отказа в `dropped` | ok |
| то же | инвариант: одна функция сверки в 4 местах | `Q::test_one_check_everywhere` ×10 случаев (извлечение, `Statements.add`, перепроверка `handle_library_event`, `quotes.check`), `Q::test_dating_uses_same_quote_check` ×5 (цитата датировки → `dating_quote`) | принято/отказ совпадают во всех местах; `knowledge.library.event lost` | ok |
| то же | инвариант: любая подстрока + типографика + внешние кавычки + NFD | `Q::test_any_substring_found_property` (400) | — | ok |
| то же | инвариант: многоточие — части по порядку, без наложения, ≥10 знаков; враждебные: не по порядку, повтор части, короткая часть | `Q::test_ellipsis_parts_property` (400), `Q::test_overlapping_parts_rejected`, `Q::test_single_short_part_allowed` | `quote_not_found` / `quote_too_short` | ok |
| то же | инвариант: пересказ, перестановка, чужие слова не проходят | `Q::test_paraphrase_and_extra_words_rejected_property` (400) | — | ok |
| то же | инвариант: пустая/вырожденная цитата (`""`, `...`, `[...]`, `""`, `«»`, невидимые знаки) | `Q::test_degenerate_quotes_never_found` ×14 | `quote_not_found`, события | ok |
| то же | инвариант: в подтверждении цитата как есть | `Q::test_stored_quote_is_models_as_is` ×4 | — | ok |
| то же | инвариант: проверки до сущностей (порядок тип → абзац → цитата) | `Q::test_checks_precede_entity_resolution` | коды `entity_type, paragraph_out_of_window, quote_not_found` | ok |
| Запуски наполнения | Проба | `R::test_sample_run_cost_and_estimate` | `estimate` 7 фрагментов, стоимость пробы 2 вызова, оценка = на фрагмент × 7; запуск `done`, `fragments=2` | ok |
| то же | Модель и метрики запуска через шлюз | `R::test_gateway_run_model_and_metrics` | `model=flash`, `extractor=gateway`, `fragments=2`, токены 2000/400, `cost_usd` по тарифу, `duration_seconds=5.0` по часам, `finished_at`; `provenance.model=flash`; `knowledge.run.finished {run_id,kind,created,dropped}` | ok |
| то же | Сбой посреди запуска | `R::test_failure_in_second_fragment` | `failed`, `failure` с `RuntimeError`, `finished_at`, утверждение 1-го фрагмента сохранено; `knowledge.run.failed {run_id,kind,error_kind}`, `run.finished` нет | ok |
| то же | Ответ шлюза не 200 | `R::test_gateway_429_budget` | `drop_reasons={"model_budget":1}`, `dropped=1`; `dropped code=model_budget` | ok |
| то же | инвариант: отказ шлюза — одна отбраковка фрагмента с кодом (429, 4xx, 502, 503, 500, таймаут, обрыв; ×12) | `R::test_gateway_failure_is_one_coded_drop_per_fragment` | `model_budget/model_refused/model_schema/model_unavailable/model_timeout`; соседний фрагмент записан | ok |
| то же | инвариант: `model` — идентификатор, не роль (7 ответов шлюза о роли), модель по настоящему шлюзу | `R::test_run_model_is_identifier_never_role`, `R::test_model_follows_gateway_role_config` | `model` = id или `NULL`, никогда `main/strong/fast`; `provenance.model` то же | ok |
| то же | инвариант: после выхода нет `running` (7 исключений × 2 точки, в т.ч. `KeyboardInterrupt`, `SystemExit`) | `R::test_no_running_run_after_exit` ×14 | `failed`, `failure` ≤500 знаков, `knowledge.run.failed error_kind` | ok |
| то же | инвариант: нет `running`, если сломана сводка расходов | `R::test_no_running_run_when_spend_summary_is_broken` | not-json и «объект» → **Д3, красный**; http-500, `[]`, bad-cost → ok | **FAIL ×2** |
| то же | инвариант: пустой запуск `done`; `failure` ≤500; `fragments` при `limit`; created+dropped=Σ событий fragment | `R::test_empty_run_is_done`, `test_failure_text_limited`, `test_fragments_metric_counts_processed`, `test_created_plus_dropped_equals_items` | — | ok |
| то же | инвариант: миграция `knowledge:10` (старая строка цела, новые поля пусты) | `R::test_migration_10_keeps_old_rows` | `upgrade == [10]`, столбцы добавлены | ok |
| Проверка ответа по утверждениям | Отклонения в одном ответе | `I::test_deviations_in_one_reply` | 3 записаны (атрибуция учебнику, абзац 1, `influenced_by` + предложение `rejects`); `dropped`: `entity_type`, `schema_item`; fragment `created=3,dropped=2`; `drop_reasons` | ok |
| то же | Мягкая схема в запросе | `I::test_soft_schema_in_request`, `I::test_registry_schema_stays_contract` | нет `enum` на любом уровне; `required` корня/элемента; нет типов у полей; `relations`, `entity_types` из реестра | ok |
| то же | инвариант: каждая ветвь проверки — код, остальные пишутся, `dropped = Σ` (44 случая) | `I::test_item_fault_is_isolated_and_coded` | коды `schema_item/stance_invalid/entity_type/relation_not_allowed/paragraph_out_of_window/quote_*/entity_*/type_mismatch/qualifier_invalid`; fragment `created=1,dropped=1` | ok (43), **FAIL (`²`, Д1)** |
| то же | инвариант: порядок проверок | `I::test_check_order` ×5 | — | ok |
| то же | инвариант: ответ не объект / `statements` не массив → один `reply_invalid` (11 видов) | `I::test_reply_invalid` | — | ok |
| то же | инвариант: шлюз `model_schema`, внешний `schema_item` | `I::test_missing_required_field_gateway_vs_external` | — | ok |
| то же | инвариант: `null` ≡ отсутствие (6 полей × значение/нет, типы без `entities`, `entities` с null) | `I::test_null_equals_absent` ×12, `test_null_type_equals_absent_for_new_entity`, `test_entities_item_nulls` | идентичный итог и коды | ok |
| то же | инвариант: `paragraph` строкой (6 форм); позиции; код вне реестра → предложение; код не для извлечения → без предложения | `I::test_paragraph_digit_string`, `test_valid_stances_accepted`, `test_unknown_relation_becomes_proposal` ×5, `test_relation_not_allowed_no_proposal` | `knowledge.registry.proposal` | ok |
| то же | инвариант: только типы реестра при любом ответе (property); отказ элемента не отменяет остальных (property) | `I::test_only_registry_types_stored`, `I::test_bad_item_does_not_reject_the_rest_property` | — | ok |
| Коды причин отбраковки | Сводка причин в запуске | `I::test_drop_reasons_summary` | `drop_reasons={"quote_not_found":1,"paragraph_out_of_window":1}`, `dropped=2`, события | ok |
| то же | инвариант: ключи события, нет названий и цитат, reason ≤300 | `I::test_event_fields_and_no_leak`, `I::test_reason_is_cut_to_300` | — | ok |
| то же | инвариант: `drop_reasons` = число событий по кодам, `dropped` = Σ (property по фрагментам + `reply_missing`, `reply_invalid`) | `I::test_summary_matches_events_over_fragments` + `check_run_accounting` во всех тестах | — | ok |
| то же | инвариант: перечень закрыт; reason `entity:*`/`dating:*` прежний; `dating_*` ×6; `statement_refused`; `entity_ambiguous` | `I::test_code_list_equals_spec_table`, `test_codes_closed_list_and_old_reasons_kept`, `test_dating_codes`, `test_statement_refused_code`, `test_entity_ambiguous_code` | — | ok |
| Внешний извлекатель | Выгрузка задания | `X::test_export_task`, `X::test_export_default_dir_is_cwd` | файл: строка `task` + 4 `fragment`; 2-й `paragraph_ids=ids[1:3]`, `passages` с `[1] `; stdout — путь; `knowledge.extraction.exported {version_id,fragments}` | ok |
| то же | Запись ответов Claude | `X::test_ingest_claude_replies` | `extractor=external`, `model=claude-opus-5-5`, `fragments=4`, `duration=120`, `cost_usd=6.0`, `reply_missing:2`; `provenance`; `run.finished`, fragment×2 | ok |
| то же | Повторная запись | `X::test_ingest_repeat` | код 2 и пусто без `--replace`; с `--replace` счётчики те же, прежний `rolled_back`; `knowledge.run.rolled_back` | ok |
| то же | инвариант: фрагменты `ingest` = `export` (покомпонентно, size 1,2,3,30) | `X::test_ingest_fragments_equal_export` | цитата каждого абзаца k фрагмента n → `evidence.paragraph_id` = `paragraph_ids[k-1]` | ok |
| то же | инвариант: тот же путь проверки, что у шлюза | `X::test_gateway_and_ingest_agree_property` | одинаковые `created/dropped/drop_reasons/коды/утверждения/fragment` | ok |
| то же | инвариант: стоимость по формуле (9 вариантов), модель без тарифа → код 2 до записи (4), с ценами — запись, `model` = переданный id (5) | `X::test_cost_formula`, `test_unknown_model_without_prices_refused_before_writing`, `test_unknown_model_with_prices_ok`, `test_model_is_passed_identifier` | нет запусков, нет `run.started` | ok |
| то же | инвариант: повтор/`--replace` не удваивает (property), не трогает чужие запуски, после `failed` — запись | `X::test_replace_does_not_double_property`, `test_replace_leaves_other_runs_alone`, `test_replace_without_previous_and_failed_previous` | — | ok |
| то же | инвариант: `reply_missing` по одному на фрагмент; номер вне задания → `reply_invalid` | `X::test_missing_reply_one_drop_each` ×4, `X::test_reply_out_of_range_ignored` ×8 | — | ok (7), **FAIL (`²`, Д2)** |
| то же | инвариант: JSON-объект и JSONL; запрет → код 3 и ничего не пишется; нет `running` при исключении; события отбраковки | `X::test_replies_json_and_jsonl_equal`, `test_export_forbidden_exit_3`, `test_ingest_forbidden_exit_3`, `test_ingest_never_leaves_running`, `test_external_drop_events`, `test_export_is_deterministic` | `knowledge.extraction.skipped` | ok |
| Отчёт о запусках извлечения | Отчёт за день | `X::test_report_for_a_day` | 3 строки запусков (откатанный не входит) + «Итого»: токены, стоимость, создано, отброшено, фрагменты равны суммам `filling_runs`; источник — название и `source_id`; доля; топ кодов; `knowledge.extraction.report {runs,out}` | ok |
| то же | инвариант: период, откат исключает, пустой период; топ-3 кодов и доля | `X::test_report_period_and_rollbacks`, `X::test_report_top_codes_and_rates` | — | ok |
| Таймаут вызова модели при извлечении | Таймаут по бюджету роли | `R::test_timeout_by_role_budget` | запрос `structured` с таймаутом 1114,5 | ok |
| то же | инвариант: бюджет + 30 (5 значений); без сведений шлюза (404/недоступен/500/без бюджета) — 1200; настройка `PHILOGRAPH_EXTRACTION_TIMEOUT_SECONDS` | `R::test_timeout_is_budget_plus_30`, `test_timeout_fallback_default`, `test_timeout_fallback_from_service_setting` | — | ok |
| Художественный текст | Правила в промпте | `P::test_prompt_rules_reach_the_model`, `P::test_prompt_rules_in_external_task` | инструкция, ушедшая модели и попавшая в задание, содержит обе фразы и «не пиши null» | ok |
| то же | инвариант: высказывание — автору; персонаж не `person` | `P::test_character_statement_attributed_to_author` ×3, `P::test_character_is_not_a_person_entity` ×4 | атрибуции: автор (`asserts`/`disputes`) + учебник `mentions`; `dropped code=entity_type` | ok |
| Сведения о роли (llm-gateway) | Роль извлечения | `G::test_role_info_extraction_role` | `{"role":"strong","model":"deepseek-v4-pro","call_budget_seconds":1084.5}` | ok |
| то же | Неизвестная роль | `G::test_role_info_unknown_role`, `G::test_role_info_hostile_names_are_404` ×8 | 404 `kind=unknown_role` | ok |
| то же | инварианты: ключи/цены не в ответе; формула (property 120); модель на роль | `G::test_role_info_has_no_secrets_or_prices`, `test_role_budget_formula_property`, `test_role_model_per_role` | — | ok |
| Сводка расходов (llm-gateway) | Токены в сводке по запуску | `G::test_spend_tokens_by_run` | `run-1`: `calls=2, input_tokens=2000, output_tokens=400` (и через `GET /v1/spend`); `llm.call.completed`×3 | ok |
| то же | Приближение к лимиту | `G::test_near_limit_event` | нет события на 14 вызовах, на 15-м `llm.budget.near_limit {budget=site,period=day,spent_usd,limit_usd}` | ok |
| то же | инварианты: токены во всех группировках; суммирование по запускам (property) | `G::test_every_group_has_token_sums` ×7, `G::test_tokens_per_run_property` | — | ok |

### Команды и итоги

    ruff check . && ruff format --check .  →  All checks passed! / 718 files already formatted
    lint-imports                            →  Contracts: 3 kept, 0 broken.
    python scripts/check_traceability.py    →  Требований с тестами: 427 из 427
    pytest -q tests/knowledge/test_reextract_{fragments,quotes,items,runs,external,prompt}.py tests/llm
                                            →  4 failed, 330 passed in 304s  (4 failed = Д1, Д2, Д3×2)
    pytest -q tests/knowledge/test_entity_dating_extraction.py tests/knowledge/test_extraction_entities.py tests/knowledge/test_mentions_cards.py::test_migration_6_adds_mention_position tests/knowledge/test_portraits.py
                                            →  passed (после правки ожиданий 3.3)
    pytest -q tests/knowledge/test_epoch_dates_unit.py::test_repository_manifest_is_valid_and_unconfirmed на origin/claude/embedding-docker (c9a02aa)
                                            →  1 failed  (не наше)
    Полный `pytest -q tests/knowledge` не запускался повторно (29 мин, по условию — не более одного раза; этот прогон делал разработчик, 2.8).

### Мутации (`python scripts/mutation_check.py --change reextract-with-claude`)

49 мутаций, 11 из 11 требований (`--coverage`: «мутации есть у всех 11 требований»). Сырой вывод таблицы:

| Требование | Мутация | Ожидаемый тест | Упал |
|---|---|---|---|
| Фрагменты из нескольких абзацев | frag-ignore-volume | tests/knowledge/test_reextract_fragments.py::test_short_paragraphs_gather_by_volume | да (1 failed, 1 warning in 1.27s) |
| Фрагменты из нескольких абзацев | frag-ignore-volume | tests/knowledge/test_reextract_fragments.py::test_fragment_rules_property | да (1 failed, 1 warning in 1.18s) |
| Фрагменты из нескольких абзацев | frag-no-overlap | tests/knowledge/test_reextract_fragments.py::test_statement_on_boundary_is_stored_once | да (1 failed, 1 warning in 1.12s) |
| Фрагменты из нескольких абзацев | frag-no-overlap | tests/knowledge/test_reextract_fragments.py::test_paragraph_limit_gives_overlapping_pairs | да (1 failed, 1 warning in 1.21s) |
| Фрагменты из нескольких абзацев | frag-size-off-by-one | tests/knowledge/test_reextract_fragments.py::test_paragraph_limit_gives_overlapping_pairs | да (1 failed, 1 warning in 1.06s) |
| Фрагменты из нескольких абзацев | frag-size-off-by-one | tests/knowledge/test_reextract_fragments.py::test_fragment_rules_property | да (1 failed, 1 warning in 1.51s) |
| Фрагменты из нескольких абзацев | frag-changed-ignored | tests/knowledge/test_reextract_fragments.py::test_changed_limits_extraction_run | да (1 failed, 1 warning in 1.23s) |
| Фрагменты из нескольких абзацев | frag-changed-ignored | tests/knowledge/test_reextract_fragments.py::test_changed_filters_fragments_property | да (1 failed, 1 warning in 2.52s) |
| Цитата у каждого утверждения | quote-order-ignored | tests/knowledge/test_reextract_quotes.py::test_ellipsis_gap_in_order_and_reversed | да (1 failed, 1 warning in 1.11s) |
| Цитата у каждого утверждения | quote-order-ignored | tests/knowledge/test_reextract_quotes.py::test_ellipsis_parts_property | да (1 failed, 1 warning in 4.34s) |
| Цитата у каждого утверждения | quote-overlap-allowed | tests/knowledge/test_reextract_quotes.py::test_overlapping_parts_rejected | да (1 failed, 1 warning in 0.25s) |
| Цитата у каждого утверждения | quote-no-min-part | tests/knowledge/test_reextract_quotes.py::test_ellipsis_parts_property | да (1 failed, 1 warning in 4.61s) |
| Цитата у каждого утверждения | quote-no-min-part | tests/knowledge/test_reextract_quotes.py::test_one_check_everywhere | да (1 failed, 9 passed, 1 warning in 7.85s) |
| Цитата у каждого утверждения | quote-no-edge-strip | tests/knowledge/test_reextract_quotes.py::test_outer_quotes_and_other_dash | да (1 failed, 1 warning in 0.94s) |
| Цитата у каждого утверждения | quote-no-edge-strip | tests/knowledge/test_reextract_quotes.py::test_any_substring_found_property | да (1 failed, 1 warning in 5.13s) |
| Цитата у каждого утверждения | quote-no-dash-map | tests/knowledge/test_reextract_quotes.py::test_outer_quotes_and_other_dash | да (1 failed, 1 warning in 0.96s) |
| Цитата у каждого утверждения | quote-no-dash-map | tests/knowledge/test_reextract_quotes.py::test_any_substring_found_property | да (1 failed, 1 warning in 5.95s) |
| Цитата у каждого утверждения | quote-no-yo | tests/knowledge/test_reextract_quotes.py::test_one_check_everywhere | да (1 failed, 1 passed, 1 warning in 1.77s) |
| Цитата у каждого утверждения | quote-no-yo | tests/knowledge/test_reextract_quotes.py::test_any_substring_found_property | да (1 failed, 1 warning in 8.80s) |
| Цитата у каждого утверждения | quote-substring-loose | tests/knowledge/test_reextract_quotes.py::test_paraphrase_and_extra_words_rejected_property | да (1 failed, 1 warning in 3.95s) |
| Цитата у каждого утверждения | quote-substring-loose | tests/knowledge/test_reextract_quotes.py::test_quote_not_found | да (1 failed, 1 warning in 1.12s) |
| Цитата у каждого утверждения | quote-add-unchecked | tests/knowledge/test_reextract_quotes.py::test_one_check_everywhere | да (1 failed, 4 passed, 1 warning in 4.70s) |
| Цитата у каждого утверждения | quote-recheck-unchecked | tests/knowledge/test_reextract_quotes.py::test_one_check_everywhere | да (1 failed, 4 passed, 1 warning in 4.49s) |
| Цитата у каждого утверждения | quote-dating-own-check | tests/knowledge/test_reextract_quotes.py::test_dating_uses_same_quote_check | да (1 failed, 1 warning in 1.03s) |
| Цитата у каждого утверждения | quote-checked-after-entities | tests/knowledge/test_reextract_quotes.py::test_no_orphans | да (1 failed, 1 warning in 1.08s) |
| Цитата у каждого утверждения | quote-checked-after-entities | tests/knowledge/test_reextract_quotes.py::test_refusal_creates_no_entities_with_attribution_and_entities_block | да (1 failed, 1 warning in 1.30s) |
| Запуски наполнения | runs-no-fail-run | tests/knowledge/test_reextract_runs.py::test_failure_in_second_fragment | да (1 failed, 1 warning in 1.29s) |
| Запуски наполнения | runs-no-fail-run | tests/knowledge/test_reextract_runs.py::test_failure_text_limited | да (1 failed, 1 warning in 1.03s) |
| Запуски наполнения | runs-model-is-role | tests/knowledge/test_reextract_runs.py::test_gateway_run_model_and_metrics | да (1 failed, 1 warning in 1.17s) |
| Запуски наполнения | runs-model-is-role | tests/knowledge/test_reextract_runs.py::test_run_model_is_identifier_never_role | да (1 failed, 1 warning in 0.97s) |
| Запуски наполнения | runs-tokens-lost | tests/knowledge/test_reextract_runs.py::test_gateway_run_model_and_metrics | да (1 failed, 1 warning in 1.07s) |
| Запуски наполнения | runs-duration-lost | tests/knowledge/test_reextract_runs.py::test_gateway_run_model_and_metrics | да (1 failed, 1 warning in 1.13s) |
| Запуски наполнения | runs-429-as-refused | tests/knowledge/test_reextract_runs.py::test_gateway_429_budget | да (1 failed, 1 warning in 0.86s) |
| Запуски наполнения | runs-gateway-failure-not-counted | tests/knowledge/test_reextract_runs.py::test_gateway_429_budget | да (1 failed, 1 warning in 0.86s) |
| Проверка ответа по утверждениям | check-isolation-broken | tests/knowledge/test_reextract_items.py::test_bad_item_does_not_reject_the_rest_property | да (1 failed, 1 warning in 9.58s) |
| Проверка ответа по утверждениям | check-isolation-broken | tests/knowledge/test_reextract_items.py::test_deviations_in_one_reply | да (1 failed, 1 warning in 1.12s) |
| Проверка ответа по утверждениям | check-null-not-absent | tests/knowledge/test_reextract_items.py::test_deviations_in_one_reply | да (1 failed, 1 warning in 1.08s) |
| Проверка ответа по утверждениям | check-null-not-absent | tests/knowledge/test_reextract_items.py::test_null_equals_absent | да (1 failed, 1 warning in 1.07s) |
| Проверка ответа по утверждениям | check-paragraph-string | tests/knowledge/test_reextract_items.py::test_paragraph_digit_string | да (1 failed, 1 warning in 0.83s) |
| Проверка ответа по утверждениям | check-unknown-relation-dropped | tests/knowledge/test_reextract_items.py::test_unknown_relation_becomes_proposal | да (1 failed, 1 warning in 0.91s) |
| Проверка ответа по утверждениям | check-unknown-relation-dropped | tests/knowledge/test_reextract_items.py::test_deviations_in_one_reply | да (1 failed, 1 warning in 1.23s) |
| Проверка ответа по утверждениям | check-stance-unchecked | tests/knowledge/test_reextract_items.py::test_item_fault_is_isolated_and_coded | да (1 failed, 20 passed, 1 warning in 13.74s) |
| Проверка ответа по утверждениям | check-hard-schema | tests/knowledge/test_reextract_items.py::test_soft_schema_in_request | да (1 failed, 1 warning in 1.12s) |
| Проверка ответа по утверждениям | check-reply-invalid-ignored | tests/knowledge/test_reextract_items.py::test_reply_invalid | да (1 failed, 1 warning in 0.84s) |
| Коды причин отбраковки | codes-always-refused | tests/knowledge/test_reextract_items.py::test_drop_reasons_summary | да (1 failed, 1 warning in 1.04s) |
| Коды причин отбраковки | codes-always-refused | tests/knowledge/test_reextract_quotes.py::test_quote_not_found | да (1 failed, 1 warning in 0.95s) |
| Коды причин отбраковки | codes-summary-not-counted | tests/knowledge/test_reextract_items.py::test_drop_reasons_summary | да (1 failed, 1 warning in 1.06s) |
| Коды причин отбраковки | codes-summary-not-counted | tests/knowledge/test_reextract_items.py::test_summary_matches_events_over_fragments | да (1 failed, 1 warning in 2.28s) |
| Коды причин отбраковки | codes-leak-quote | tests/knowledge/test_reextract_items.py::test_event_fields_and_no_leak | НЕТ (1 passed, 1 warning in 0.79s) |
| Внешний извлекатель | ext-output-price-wrong | tests/knowledge/test_reextract_external.py::test_cost_formula | да (1 failed, 1 warning in 0.97s) |
| Внешний извлекатель | ext-output-price-wrong | tests/knowledge/test_reextract_external.py::test_ingest_claude_replies | да (1 failed, 1 warning in 1.00s) |
| Внешний извлекатель | ext-replace-no-rollback | tests/knowledge/test_reextract_external.py::test_ingest_repeat | да (1 failed, 1 warning in 1.11s) |
| Внешний извлекатель | ext-replace-no-rollback | tests/knowledge/test_reextract_external.py::test_replace_does_not_double_property | да (1 failed, 1 warning in 65.82s (0:01:05)) |
| Внешний извлекатель | ext-repeat-allowed | tests/knowledge/test_reextract_external.py::test_ingest_repeat | да (1 failed, 1 warning in 1.23s) |
| Внешний извлекатель | ext-missing-not-dropped | tests/knowledge/test_reextract_external.py::test_ingest_claude_replies | да (1 failed, 1 warning in 1.12s) |
| Внешний извлекатель | ext-missing-not-dropped | tests/knowledge/test_reextract_external.py::test_missing_reply_one_drop_each | да (1 failed, 1 warning in 0.97s) |
| Внешний извлекатель | ext-forbidden-exported | tests/knowledge/test_reextract_external.py::test_export_forbidden_exit_3 | да (1 failed, 1 warning in 0.83s) |
| Внешний извлекатель | ext-forbidden-exported | tests/knowledge/test_reextract_external.py::test_ingest_forbidden_exit_3 | да (1 failed, 1 warning in 0.97s) |
| Внешний извлекатель | ext-fragment-numbering | tests/knowledge/test_reextract_external.py::test_export_task | да (1 failed, 1 warning in 0.83s) |
| Внешний извлекатель | ext-out-of-range-applied | tests/knowledge/test_reextract_external.py::test_reply_out_of_range_ignored | да (1 failed, 1 passed, 1 warning in 1.61s) |
| Внешний извлекатель | ext-model-fixed | tests/knowledge/test_reextract_external.py::test_model_is_passed_identifier | да (1 failed, 1 warning in 0.97s) |
| Внешний извлекатель | ext-model-fixed | tests/knowledge/test_reextract_external.py::test_ingest_claude_replies | да (1 failed, 1 warning in 0.95s) |
| Отчёт о запусках извлечения | rep-includes-rolled-back | tests/knowledge/test_reextract_external.py::test_report_for_a_day | да (1 failed, 1 warning in 1.17s) |
| Отчёт о запусках извлечения | rep-includes-rolled-back | tests/knowledge/test_reextract_external.py::test_report_period_and_rollbacks | да (1 failed, 1 warning in 1.28s) |
| Отчёт о запусках извлечения | rep-total-tokens-swapped | tests/knowledge/test_reextract_external.py::test_report_for_a_day | да (1 failed, 1 warning in 1.12s) |
| Отчёт о запусках извлечения | rep-top-two | tests/knowledge/test_reextract_external.py::test_report_top_codes_and_rates | да (1 failed, 1 warning in 0.94s) |
| Таймаут вызова модели при извлечении | to-no-margin | tests/knowledge/test_reextract_runs.py::test_timeout_by_role_budget | да (1 failed, 1 warning in 0.95s) |
| Таймаут вызова модели при извлечении | to-fallback-ignored | tests/knowledge/test_reextract_runs.py::test_timeout_fallback_default | да (1 failed, 3 passed, 1 warning in 2.81s) |
| Художественный текст | fic-prompt-rule-dropped | tests/knowledge/test_reextract_prompt.py::test_prompt_rules_reach_the_model | да (1 failed, 1 warning in 0.98s) |
| Художественный текст | fic-prompt-rule-dropped | tests/knowledge/test_reextract_prompt.py::test_prompt_rules_in_external_task | да (1 failed, 1 warning in 0.79s) |
| Сводка расходов | spend-no-tokens | tests/llm/test_reextract_role_spend.py::test_spend_tokens_by_run | да (1 failed, 1 warning in 0.43s) |
| Сводка расходов | spend-no-tokens | tests/llm/test_reextract_role_spend.py::test_every_group_has_token_sums | да (1 failed, 1 warning in 0.43s) |
| Сведения о роли | role-budget-no-schema-retries | tests/llm/test_reextract_role_spend.py::test_role_info_extraction_role | да (1 failed, 1 warning in 0.39s) |
| Сведения о роли | role-budget-no-schema-retries | tests/llm/test_reextract_role_spend.py::test_role_budget_formula_property | да (1 failed, 1 warning in 9.29s) |
| Сведения о роли | role-leaks-price | tests/llm/test_reextract_role_spend.py::test_role_info_has_no_secrets_or_prices | да (1 failed, 1 warning in 0.43s) |
| Сведения о роли | role-leaks-price | tests/llm/test_reextract_role_spend.py::test_role_info_extraction_role | да (1 failed, 1 warning in 0.44s) |
| Запуски наполнения | runs-migration-noop | tests/knowledge/test_reextract_runs.py::test_migration_10_keeps_old_rows | да (1 failed, 1 warning in 0.44s) |

Одна мутация выжила в первом прогоне — `codes-leak-quote` (`reason` удваивается, но не превышает 300 знаков, потому что настоящие причины короткие): тест усилен (`test_reason_is_cut_to_300`, причина из ключа уточнителя в 1000 знаков), повтор: `| Коды причин отбраковки | codes-leak-quote | tests/knowledge/test_reextract_items.py::test_reason_is_cut_to_300 | да (1 failed …) |`. После мутаций `git status` по продуктовому коду чист.

Исключения из проверки журнала: нет.

Не покрыто:
- `external_extraction.build()` и реальный HTTP-клиент библиотеки (`PHILOGRAPH_DATABASE_URL`/`PHILOGRAPH_LIBRARY_URL`) — команда проверена через `main(argv, service=…)` со стендом, сборка настоящего сервиса требует поднятой библиотеки (нужен dev_stack, по условию не запускался);
- запуск `extract_version(changed=…)` по событию библиотеки `source.published` (`Filling.handle_published`) — проверено прямым вызовом с `changed`, не через очередь;
- сценарий «Утверждение на границе» через реальный шлюз с кэшем ответов — стенд берёт уникальные тексты абзацев, чтобы кэш не подменял ответы; поведение кэша шлюза не менялось дельтой;
- повторный полный `pytest tests/knowledge` (29 мин) не гонялся: прогнаны только новые файлы, `tests/llm` и правленные прежние тесты;
- `entity_ambiguous` проверен кодом и счётом, но не сценарием «пункт проверки» (проверка оператора — вне дельты).

### Повторный прогон после исправления Д1–Д3 (коммит разработчика 09f3911)

Тесты не менялись.

    pytest -q tests/knowledge/test_reextract_{fragments,quotes,items,runs,external,prompt}.py tests/llm \
              tests/knowledge/test_entity_dating_extraction.py tests/knowledge/test_extraction_entities.py \
              tests/knowledge/test_portraits.py tests/knowledge/test_mentions_cards.py::test_migration_6_adds_mention_position
        →  394 passed, 1 warning in 379s

Д1 (`paragraph: "²"`), Д2 (ключ ответа `"²"`), Д3 (сломанная сводка расходов, `not-json` и `object`): все четыре прежде красных теста зелёные. Мутации после правки не перепрогонялись.

## Тестировщик — дополнение после ревью (дельта в коммите 7e8d8db)

Новые тесты: `tests/knowledge/test_reextract_review.py` (53 теста, с маркерами `req`); обновлён `test_reextract_external.py::test_replace_without_previous_and_failed_previous` (по новой формулировке: после `failed` без `--replace` — код 2 и ничего не записано; с `--replace` — `rolled_back` + новый `done`). Остальные свои тесты не ослаблялись.

| Требование | Сценарий / инвариант | Тест | Вывод и журнал |
|---|---|---|---|
| Цитата у каждого утверждения | Многоточие автора в цитате | `test_authors_ellipsis_in_quote` | абзац «Он сказал... и замолчал.», цитата «сказал... и» найдена, записана как есть, без `dropped`; перепроверка `rechecked=1, lost=0`, `evidence.lost=False`; `knowledge.library.event lost=0` |
| то же | инвариант: целиком сначала, части потом (7 случаев) | `test_whole_first_then_parts` | `None` / `quote_too_short` / `quote_not_found` |
| то же | инвариант: U+200B/U+2060/U+FEFF; ″ ′ ` | `test_zero_width_removed` ×3, `test_primes_and_backtick` ×3 | цитата и абзац — в обе стороны |
| то же | инвариант: `Statements.add` с многоточием автора; property подстрок с «...» (300) | `test_add_accepts_authors_ellipsis`, `test_substring_with_authors_ellipsis_property` | — |
| Проверка ответа по утверждениям | Элемент entities не того вида | `test_entities_item_wrong_kind` | утверждение записано, запуск `done`, сущностей/датировок нет, 3×`dropped code=schema_item`, `drop_reasons={"schema_item":3}` |
| то же | инвариант: 10 видов (type не строка, dating.text/quote не строки, paragraph float/bool/список/`²`/`٣`/`１`) | `test_entities_item_kinds_dropped_rest_kept` | один `schema_item`, верное утверждение записано |
| то же | инвариант: `dating.paragraph` — int или ASCII-цифры | `test_dating_paragraph_ascii_digits_pass_kind_check` | датировка записана |
| то же | инвариант: ASCII 0-9 у `paragraph` (`² ٣ １ १ ①`) | `test_paragraph_unicode_digits_refused` | `schema_item`, остальное записано |
| то же | **property: произвольные значения полей `entities` не роняют запуск** (150 внешний путь, 40 — через шлюз) | `test_arbitrary_entities_never_crash_property`, `…_gateway_property` | `done`, `failure=None`, верное утверждение записано, `dropped == Σ drop_reasons == событий`, коды из перечня |
| Внешний извлекатель | Повтор после прерванной записи | `test_repeat_after_interrupted_ingest` | `failed`; без `--replace` код 2, счётчики те же, `run.started` нет; с `--replace` — `rolled_back` + `done`, счётчики = одной полной записи на пустой онтологии |
| то же | инвариант: любой неоткатанный (done/failed/running и сочетания) блокирует, `--replace` откатывает все (5 наборов); откатанные и чужая версия не блокируют | `test_any_unrolled_external_run_blocks_repeat`, `test_rolled_back_and_other_version_do_not_block`, обновлённый `test_replace_without_previous_and_failed_previous` | — |
| то же | Повтор фрагмента в файле ответов | `test_duplicate_fragment_in_jsonl` | код 2, stderr, нет запуска и записей |
| то же | инвариант: повтор ключа в JSON-объекте (верхний и вложенный) | `test_duplicate_key_in_json_object` ×2 | код 2 |
| то же | инвариант: версия не найдена (404), библиотека 500/недоступна; export и ingest | `test_version_missing_or_library_down` ×6 | код 2, сообщение без «Traceback», ничего не создано |

Прогон:

    ruff check . / ruff format --check .   →  All checks passed! / 720 files already formatted
    python scripts/check_traceability.py   →  Требований с тестами: 427 из 427
    pytest -q tests/knowledge/test_reextract_{fragments,quotes,items,runs,external,prompt,review}.py tests/llm
              + правленные прежние + test_external_extraction_unit/test_quotes_unit/test_extraction_codes_map_unit
                                          →  497 passed, 1 warning in 436s

Мутации на новые правила (12, `--id`; сырой вывод):

| Цитата у каждого утверждения | quote-whole-first-removed | tests/knowledge/test_reextract_review.py::test_authors_ellipsis_in_quote | да (1 failed, 1 warning in 1.01s) |
| Цитата у каждого утверждения | quote-whole-first-removed | tests/knowledge/test_reextract_review.py::test_whole_first_then_parts | да (1 failed, 1 warning in 0.27s) |
| Цитата у каждого утверждения | quote-no-zero-width | tests/knowledge/test_reextract_review.py::test_zero_width_removed | да (1 failed, 1 warning in 0.24s) |
| Цитата у каждого утверждения | quote-no-primes | tests/knowledge/test_reextract_review.py::test_primes_and_backtick | да (1 failed, 1 passed, 1 warning in 0.30s) |
| Проверка ответа по утверждениям | check-entities-type-unchecked | tests/knowledge/test_reextract_review.py::test_entities_item_wrong_kind | да (1 failed, 1 warning in 0.94s) |
| Проверка ответа по утверждениям | check-entities-type-unchecked | tests/knowledge/test_reextract_review.py::test_arbitrary_entities_never_crash_property | да (1 failed, 1 warning in 19.77s) |
| Проверка ответа по утверждениям | check-dating-kind-unchecked | tests/knowledge/test_reextract_review.py::test_entities_item_wrong_kind | да (1 failed, 1 warning in 1.07s) |
| Проверка ответа по утверждениям | check-dating-kind-unchecked | tests/knowledge/test_reextract_review.py::test_arbitrary_entities_never_crash_property | НЕТ (1 passed, 1 warning in 19.63s) |
| Проверка ответа по утверждениям | check-unicode-digits | tests/knowledge/test_reextract_review.py::test_entities_item_kinds_dropped_rest_kept | да (1 failed, 7 passed, 1 warning in 5.55s) |
| Проверка ответа по утверждениям | check-statement-unicode-digits | tests/knowledge/test_reextract_review.py::test_paragraph_unicode_digits_refused | да (1 failed, 1 passed, 1 warning in 1.69s) |
| Внешний извлекатель | ext-repeat-after-failed-allowed | tests/knowledge/test_reextract_review.py::test_repeat_after_interrupted_ingest | да (1 failed, 1 warning in 1.33s) |
| Внешний извлекатель | ext-repeat-after-failed-allowed | tests/knowledge/test_reextract_review.py::test_any_unrolled_external_run_blocks_repeat | да (1 failed, 1 warning in 1.20s) |
| Внешний извлекатель | ext-duplicate-fragment-allowed | tests/knowledge/test_reextract_review.py::test_duplicate_fragment_in_jsonl | да (1 failed, 1 warning in 0.93s) |
| Внешний извлекатель | ext-json-duplicate-allowed | tests/knowledge/test_reextract_review.py::test_duplicate_key_in_json_object | да (1 failed, 1 warning in 0.82s) |
| Внешний извлекатель | ext-library-down-traceback | tests/knowledge/test_reextract_review.py::test_version_missing_or_library_down | да (1 failed, 2 passed, 1 warning in 2.22s) |
| Внешний извлекатель | ext-404-not-handled | tests/knowledge/test_reextract_review.py::test_version_missing_or_library_down | да (1 failed, 1 warning in 0.87s) |
| Проверка ответа по утверждениям | check-dating-kind-unchecked | tests/knowledge/test_reextract_review.py::test_entities_item_wrong_kind | да (1 failed, 1 warning in 1.1s) |  (повтор после правки списка)

В первом прогоне `check-dating-kind-unchecked` пережила property `test_arbitrary_entities_never_crash_property`: без проверки вида `dating` дальнейшая проверка датировки (`dating_*`) всё равно отбрасывает элемент, и запуск не падает. Мутацию убивает сценарий «Элемент entities не того вида» (`schema_item` вместо `dating_*`); property из `expect_fail` этой мутации убран. Остальные 11 убиты всеми заявленными тестами.

Наблюдение (не дефект по тексту дельты): раз цитата ищется целиком, цитата из одного многоточия (`...`) находится в любом абзаце, где есть многоточие автора, и проходит как подтверждение с пустым смыслом; без многоточия в абзаце — `quote_not_found`.
