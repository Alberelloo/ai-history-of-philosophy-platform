# Verification — redesign-entity-cards

## Тестировщик — 2026-11-27, коммит f8f02fb (ветка claude/entity-cards)

Тесты написаны по дельтам `specs/{entity-cards,entity-mentions,visual-design}/spec.md`, не по коду. Код читался только ради
имён полей и селекторов, которые называет дельта. Продуктовый код не менялся (`git diff -- src web/src docs` пуст).

### Файлы тестов

| Файл | Тестов | Что |
|---|---|---|
| `tests/knowledge/test_cards_redesign.py` (новый) | 165 | сервер: сценарии и инварианты, запрос по HTTP с `X-Request-Id`, журнал сверяется автоматически в каждом запросе |
| `tests/knowledge/test_mentions_cards.py` (правка) | 44 | «Где читать» (3 сценария + инвариант по типам), «Мало данных», переписанные ожидания MODIFIED |
| `tests/web/test_card_content.py` (новый) | 25 | браузер, настоящий стенд `knowledge_stack`: шапка, метки, легенда, списки, страна, пустые состояния, XSS |
| `tests/web/test_card_layout.py` (новый) | 41 | браузер: таблица ширины панели, раскладка 3 размера × 2 темы, карта, инфобокс, компактное окно, сборка |
| `tests/web/test_reader_cards.py` (правка) | 20 | моки `/card` приведены к новому контракту; T12 и N10 переписаны |
| `tests/web/card_world.py`, `tests/web/knowledge_stack.py` | — | данные для стенда; стенд передаёт `PolityLayer` и в `Cards` (правка тестовой инфраструктуры) |
| `tests/e2e/test_site.py`, `tests/e2e/test_reader_snapshots.py` | — | переписаны, **не запускались** (Docker): проверяется в CI e2e |

Вывод и журнал. Серверные тесты: ответ `GET /v1/entities/{id}/card`; `CardSvc.get` в каждом запросе проверяет, что событие
`knowledge.card.served` с этим `request_id` одно и его `entity_id`, `type`, `sections`, `rows`, `layout`, `empty`, `inferred` равны ответу.
Браузерные тесты: DOM и ответ карточки, событие — по заголовку `x-request-id` ответа, полученного страницей (`served(...)`,
`served_for(...)`).

### Матрица: требование → сценарий / инвариант → тест

Сценариев в трёх дельтах 46, у каждого есть тест с `scenario=` (проверено разбором маркеров). Инвариантов с отдельным тестом 41. Строки с «—» — прежние тесты, переписанные по новой спецификации.

| Возможность | Требование | Вид | Сценарий / инвариант | Тест |
|---|---|---|---|---|
| entity-cards | Выведенные строки | инвариант | выведенная строка берётся только из видимых утверждений | tests/knowledge/test_cards_redesign.py::test_inference_ignores_statements_of_hidden_source |
| entity-cards | Выведенные строки | инвариант | выведенная строка — полная строка с прежними полями | tests/knowledge/test_cards_redesign.py::test_inferred_row_has_all_old_fields |
| entity-cards | Выведенные строки | инвариант | выведенное не пишется в онтологию и не идёт в очередь проверки | tests/knowledge/test_cards_redesign.py::test_inferred_rows_not_written_and_not_queued |
| entity-cards | Выведенные строки | инвариант | интересы: просматривается не больше 30 трудов | tests/knowledge/test_cards_redesign.py::test_interests_scan_limit |
| entity-cards | Выведенные строки | инвариант | интересы: типы, порядок, исключение учений, пределы | tests/knowledge/test_cards_redesign.py::test_interests_rules |
| entity-cards | Выведенные строки | инвариант | отметка вывода не сильнее самого слабого звена | tests/knowledge/test_cards_redesign.py::test_inferred_mark_is_weakest_link |
| entity-cards | Выведенные строки | инвариант | раздел с выведенным подписан «по трудам и связям», подробности — через что | tests/web/test_card_content.py::test_inferred_section_label_and_via |
| entity-cards | Выведенные строки | сценарий | Интересы Юма | tests/knowledge/test_cards_redesign.py::test_hume_interests |
| entity-cards | Выведенные строки | сценарий | Компактное окно без выводов | tests/web/test_card_content.py::test_doctrine_card_relates_to_and_in_works |
| entity-cards | Выведенные строки | сценарий | Компактное окно без выводов | tests/web/test_card_layout.py::test_popup_shows_statements_only |
| entity-cards | Выведенные строки | сценарий | Отвергнутое звено не даёт вывода | tests/knowledge/test_cards_redesign.py::test_rejected_link_gives_no_inference |
| entity-cards | Государство основного места | инвариант | без года рождения образование не ищется; название не из словаря | tests/knowledge/test_cards_redesign.py::test_polity_needs_birth_year |
| entity-cards | Государство основного места | инвариант | образование — на год рождения, из слоя, меньшее по площади | tests/knowledge/test_cards_redesign.py::test_polity_depends_on_birth_year_and_picks_smallest |
| entity-cards | Государство основного места | инвариант | страна не показывается ни названием, ни заглушкой, если модуль границ не загрузился | tests/web/test_card_content.py::test_country_module_failure_shows_nothing |
| entity-cards | Государство основного места | сценарий | Без координат | tests/knowledge/test_cards_redesign.py::test_no_coordinates |
| entity-cards | Государство основного места | сценарий | Без координат | tests/web/test_card_content.py::test_no_coordinates_no_country_no_fragment |
| entity-cards | Государство основного места | сценарий | Вне покрытия слоя | tests/knowledge/test_cards_redesign.py::test_outside_layer_coverage |
| entity-cards | Государство основного места | сценарий | Вне покрытия слоя | tests/web/test_card_content.py::test_outside_layer_coverage |
| entity-cards | Государство основного места | сценарий | Историческое государство | tests/knowledge/test_cards_redesign.py::test_historical_polity |
| entity-cards | Государство основного места | сценарий | Историческое государство | tests/web/test_card_content.py::test_historical_state_in_summary |
| entity-cards | Государство основного места | сценарий | Место с координатами | tests/knowledge/test_cards_redesign.py::test_place_card_has_geo_without_polity |
| entity-cards | Государство основного места | сценарий | Место с координатами | tests/web/test_card_content.py::test_place_card_shows_modern_country |
| entity-cards | Государство основного места | сценарий | Основной фрагмент не растёт | tests/web/test_card_layout.py::test_country_data_is_a_separate_chunk |
| entity-cards | Государство основного места | сценарий | Слоя нет — современная страна с пометкой | tests/knowledge/test_cards_redesign.py::test_no_layer |
| entity-cards | Государство основного места | сценарий | Слоя нет — современная страна с пометкой | tests/web/test_card_content.py::test_no_layer_shows_modern_country_with_note |
| entity-cards | К кому относится | инвариант | набор типов, выводы у понятия, место раздела | tests/knowledge/test_cards_redesign.py::test_relates_to_term_authors_only_for_concept_and_position_in_order |
| entity-cards | К кому относится | инвариант | одна строка на персону, прямая вытесняет выведенную | tests/knowledge/test_cards_redesign.py::test_relates_to_one_row_per_person |
| entity-cards | К кому относится | сценарий | Прямая строка вытесняет вывод | tests/knowledge/test_cards_redesign.py::test_direct_row_replaces_inferred |
| entity-cards | К кому относится | сценарий | Учение без сторонников, но с трудом | tests/knowledge/test_cards_redesign.py::test_relates_to_inferred_via_work |
| entity-cards | К кому относится | сценарий | Учение без сторонников, но с трудом | tests/web/test_card_content.py::test_doctrine_card_relates_to_and_in_works |
| entity-cards | Карточка персоны | инвариант | не больше одной строки на сущность в местах, влияниях, учителях и трудах | tests/knowledge/test_cards_redesign.py::test_one_row_per_entity |
| entity-cards | Карточка персоны | инвариант | основное место: роль, отметка, подтверждения, порядок | tests/knowledge/test_cards_redesign.py::test_main_place_by_role |
| entity-cards | Карточка персоны | инвариант | основное место: роль, отметка, подтверждения, порядок | tests/knowledge/test_cards_redesign.py::test_main_place_tie_breaks_by_evidence_count |
| entity-cards | Карточка персоны | инвариант | основное место: роль, отметка, подтверждения, порядок | tests/knowledge/test_cards_redesign.py::test_main_place_tie_breaks_by_mark_then_order |
| entity-cards | Карточка персоны | инвариант | порядок разделов персоны и их вид показа | tests/knowledge/test_cards_redesign.py::test_person_section_order_and_display |
| entity-cards | Карточка персоны | инвариант | примечание строки труда — год, если труд датирован | tests/knowledge/test_cards_redesign.py::test_work_note_is_year_only_when_dated |
| entity-cards | Карточка персоны | инвариант | у персоны нет influence, studied_with и «Где читать» | tests/knowledge/test_cards_redesign.py::test_person_has_no_influence_code_and_no_where |
| entity-cards | Карточка персоны | сценарий | Влияние в обе стороны без повторов | tests/knowledge/test_cards_redesign.py::test_influence_both_ways_without_repeats |
| entity-cards | Карточка персоны | сценарий | Влияние в обе стороны без повторов | tests/web/test_card_content.py::test_influence_sections_without_repeats |
| entity-cards | Карточка персоны | сценарий | Где жил свёрнут | tests/knowledge/test_cards_redesign.py::test_places_inline_collapsed |
| entity-cards | Карточка персоны | сценарий | Где жил свёрнут | tests/web/test_card_content.py::test_places_collapsed_and_expanded |
| entity-cards | Карточка персоны | сценарий | Только годы жизни | tests/knowledge/test_cards_redesign.py::test_only_lifespan |
| entity-cards | Карточка персоны | сценарий | Только годы жизни | tests/web/test_card_content.py::test_only_lifespan |
| entity-cards | Карточка персоны | сценарий | Шапка и сводка Локка | tests/knowledge/test_cards_redesign.py::test_locke_header_and_summary |
| entity-cards | Карточка персоны | сценарий | Шапка и сводка Локка | tests/web/test_card_content.py::test_locke_header_and_summary |
| entity-cards | Природа каждой строки | инвариант | легенда: отметки строк, сводки и сгенерированного описания по шкале | tests/knowledge/test_cards_redesign.py::test_legend_equals_marks_in_every_type |
| entity-cards | Природа каждой строки | инвариант | метка одинакова во всех карточках и различима по отметке | tests/web/test_card_content.py::test_mark_looks_same_in_every_card |
| entity-cards | Природа каждой строки | инвариант | отметка — «спорное» либо статус, одна шкала | tests/knowledge/test_cards_redesign.py::test_mark_rule_for_all_combinations |
| entity-cards | Природа каждой строки | инвариант | регион снимает подтверждение, но не меняет отметку | tests/knowledge/test_cards_redesign.py::test_region_hides_evidence_but_keeps_mark |
| entity-cards | Природа каждой строки | инвариант | сгенерированное описание попадает в легенду, пустая карточка — без легенды | tests/knowledge/test_cards_redesign.py::test_generated_description_in_legend_and_none_when_empty |
| entity-cards | Природа каждой строки | инвариант | только цвет: у каждой строки одна метка с именем, слов статуса нет | tests/web/test_card_content.py::test_one_legend_and_no_status_words |
| entity-cards | Природа каждой строки | сценарий | Одна легенда | tests/knowledge/test_cards_redesign.py::test_legend_is_set_of_marks |
| entity-cards | Природа каждой строки | сценарий | Одна легенда | tests/web/test_card_content.py::test_one_legend_and_no_status_words |
| entity-cards | Природа каждой строки | сценарий | Одна легенда | tests/web/test_reader_cards.py::test_t12_nature_of_each_row |
| entity-cards | Природа каждой строки | сценарий | По источникам без подтверждения | tests/knowledge/test_cards_redesign.py::test_sourced_without_evidence |
| entity-cards | Природа каждой строки | сценарий | По источникам без подтверждения | tests/web/test_card_content.py::test_row_marks_sourced_generated_disputed |
| entity-cards | Природа каждой строки | сценарий | Сгенерированная строка | tests/knowledge/test_cards_redesign.py::test_generated_row |
| entity-cards | Природа каждой строки | сценарий | Сгенерированная строка | tests/web/test_card_content.py::test_row_marks_sourced_generated_disputed |
| entity-cards | Природа каждой строки | сценарий | Сгенерированная строка | tests/web/test_reader_cards.py::test_t12_nature_of_each_row |
| entity-cards | Природа каждой строки | сценарий | Спорное | tests/knowledge/test_cards_redesign.py::test_disputed_row |
| entity-cards | Природа каждой строки | сценарий | Спорное | tests/web/test_card_content.py::test_disputed_mark_accessible_name_wording |
| entity-cards | Природа каждой строки | сценарий | Спорное | tests/web/test_card_content.py::test_row_marks_sourced_generated_disputed |
| entity-cards | Природа каждой строки | сценарий | Спорное | tests/web/test_reader_cards.py::test_t12_nature_of_each_row |
| entity-cards | Природа каждой строки | — | (общий) | tests/e2e/test_site.py::test_mention_opens_card_and_navigates |
| entity-cards | Природа каждой строки | — | (общий) | tests/knowledge/test_mentions_cards.py::test_row_attribution_status_and_dispute |
| entity-cards | Пустые разделы | инвариант | место только с координатами: карточка не пуста | tests/knowledge/test_cards_redesign.py::test_place_with_only_coordinates_is_not_empty |
| entity-cards | Пустые разделы | инвариант | ни одного пустого раздела; пустая персона — без раздела, но с сводкой | tests/knowledge/test_cards_redesign.py::test_no_empty_sections_in_any_type |
| entity-cards | Пустые разделы | инвариант | ни одной пустой карточки: у типа с утверждением есть раздел или сводка | tests/knowledge/test_cards_redesign.py::test_one_statement_never_gives_empty_card |
| entity-cards | Пустые разделы | инвариант | сущность без утверждений — empty = true, разделов нет | tests/knowledge/test_cards_redesign.py::test_no_statements_gives_empty_card |
| entity-cards | Пустые разделы | сценарий | Мало данных | tests/knowledge/test_mentions_cards.py::test_little_data_doctrine_with_where_to_read |
| entity-cards | Пустые разделы | сценарий | Мало данных | tests/web/test_card_content.py::test_empty_states |
| entity-cards | Пустые разделы | сценарий | Ни одной пустой карточки | tests/web/test_card_content.py::test_no_card_is_empty_in_every_type |
| entity-cards | Пустые разделы | сценарий | Совсем пусто | tests/knowledge/test_cards_redesign.py::test_place_completely_empty |
| entity-cards | Пустые разделы | сценарий | Совсем пусто | tests/web/test_card_content.py::test_empty_states |
| entity-cards | Пустые разделы | — | (общий) | tests/knowledge/test_mentions_cards.py::test_no_empty_sections |
| entity-cards | Разделы карточки по типу | инвариант | «Исторический контекст» — у понятия, персоны, произведения и учений | tests/knowledge/test_mentions_cards.py::test_context_section_for_types |
| entity-cards | Разделы карточки по типу | инвариант | ни одно видимое утверждение не пропадает | tests/knowledge/test_cards_redesign.py::test_nothing_lost_for_every_type |
| entity-cards | Разделы карточки по типу | инвариант | принадлежность по датам не показывается строками | tests/knowledge/test_mentions_cards.py::test_epoch_card_without_date_membership |
| entity-cards | Разделы карточки по типу | инвариант | разделы по типам: порядок и состав | tests/knowledge/test_cards_redesign.py::test_section_codes_order_by_type |
| entity-cards | Разделы карточки по типу | инвариант | у события «стимулировало» — не «Исторический контекст» | tests/knowledge/test_mentions_cards.py::test_event_card_has_no_context_section |
| entity-cards | Разделы карточки по типу | сценарий | Исторический контекст учения | tests/knowledge/test_mentions_cards.py::test_doctrine_historical_context |
| entity-cards | Разделы карточки по типу | сценарий | Карточка группы | tests/knowledge/test_cards_redesign.py::test_group_card |
| entity-cards | Разделы карточки по типу | сценарий | Карточка группы | tests/web/test_card_content.py::test_group_and_event_cards |
| entity-cards | Разделы карточки по типу | сценарий | Карточка понятия | tests/knowledge/test_cards_redesign.py::test_concept_card |
| entity-cards | Разделы карточки по типу | сценарий | Карточка события | tests/knowledge/test_cards_redesign.py::test_event_card |
| entity-cards | Разделы карточки по типу | сценарий | Карточка события | tests/web/test_card_content.py::test_group_and_event_cards |
| entity-cards | Разделы карточки по типу | сценарий | Карточка труда | tests/knowledge/test_cards_redesign.py::test_work_card |
| entity-cards | Разделы карточки по типу | сценарий | Карточка труда | tests/web/test_card_content.py::test_work_card_infobox |
| entity-cards | Разделы карточки по типу | сценарий | Карточка труда | tests/web/test_card_content.py::test_work_card_infobox_labels |
| entity-cards | Разделы карточки по типу | сценарий | Карточка эпохи | tests/knowledge/test_mentions_cards.py::test_epoch_card |
| entity-cards | Разделы карточки по типу | сценарий | Ничего не теряется | tests/knowledge/test_cards_redesign.py::test_nothing_lost_tabula_rasa |
| entity-cards | Разделы карточки по типу | сценарий | Ничего не теряется | tests/web/test_card_content.py::test_other_section_in_dom |
| entity-cards | Разделы карточки по типу | — | (общий) | tests/e2e/test_site.py::test_concept_card_with_definition_and_where_to_read |
| entity-cards | Разделы карточки по типу | — | (общий) | tests/knowledge/test_mentions_cards.py::test_sections_by_type |
| entity-cards | Раскладка полной карточки | инвариант | инфобокс: две колонки от 32rem ширины панели, иначе одна | tests/web/test_card_layout.py::test_infobox_columns_follow_panel_width |
| entity-cards | Раскладка полной карточки | инвариант | текст строк не обрезается: длинное слово без пробелов переносится | tests/web/test_card_layout.py::test_unbroken_long_word_is_wrapped |
| entity-cards | Раскладка полной карточки | сценарий | Инфобокс по ширине | tests/web/test_card_layout.py::test_infobox_columns_by_window_width |
| entity-cards | Раскладка полной карточки | сценарий | Карточка на карте | tests/web/test_card_layout.py::test_card_on_map_in_three_sizes |
| entity-cards | Раскладка полной карточки | сценарий | Три размера окна | tests/web/test_card_layout.py::test_card_fits_panel_in_three_sizes |
| entity-cards | Свёрнутые списки | инвариант | кнопка «Показать все (N)» при total > visible, без нового запроса | tests/web/test_card_content.py::test_places_collapsed_and_expanded |
| entity-cards | Свёрнутые списки | инвариант | у каждого раздела есть display, visible и total = числу строк | tests/knowledge/test_cards_redesign.py::test_every_section_has_display_visible_total |
| entity-cards | Свёрнутые списки | сценарий | Длинный список | tests/knowledge/test_cards_redesign.py::test_long_list_totals |
| entity-cards | Свёрнутые списки | сценарий | Длинный список | tests/web/test_card_content.py::test_short_and_long_lists |
| entity-cards | Свёрнутые списки | сценарий | Короткий список без кнопки | tests/knowledge/test_cards_redesign.py::test_short_list_totals |
| entity-cards | Свёрнутые списки | сценарий | Короткий список без кнопки | tests/web/test_card_content.py::test_short_and_long_lists |
| entity-cards | Тексты карточки — текст | инвариант | значение, примечание и «через» выводятся текстом | tests/web/test_card_content.py::test_markup_in_values_notes_and_via_is_text |
| entity-cards | Тексты карточки — текст | инвариант | значения, примечания и названия «через» отдаются как есть | tests/knowledge/test_cards_redesign.py::test_markup_in_value_note_via_served_verbatim |
| entity-cards | Тексты карточки — текст | сценарий | Разметка в названии | tests/knowledge/test_cards_redesign.py::test_markup_in_titles_served_verbatim |
| entity-cards | Тексты карточки — текст | сценарий | Разметка в названии | tests/web/test_card_content.py::test_markup_is_text |
| entity-mentions | Где читать | инвариант | у персоны указатель не вызывается, у остальных типов блок остаётся | tests/knowledge/test_mentions_cards.py::test_where_to_read_for_every_non_person_type |
| entity-mentions | Где читать | сценарий | Где читать в карточке понятия | tests/knowledge/test_mentions_cards.py::test_where_to_read_in_concept_card |
| entity-mentions | Где читать | сценарий | Где читать о причинности | tests/knowledge/test_mentions_cards.py::test_where_to_read_causality |
| entity-mentions | Где читать | сценарий | Персона без «Где читать» | tests/knowledge/test_mentions_cards.py::test_person_without_where_to_read |
| entity-mentions | Где читать | — | (общий) | tests/e2e/test_site.py::test_concept_card_with_definition_and_where_to_read |
| entity-mentions | Где читать | — | (общий) | tests/knowledge/test_mentions_cards.py::test_migration_6_adds_mention_position |
| entity-mentions | Где читать | — | (общий) | tests/knowledge/test_mentions_cards.py::test_where_to_read |
| entity-mentions | Где читать | — | (общий) | tests/knowledge/test_mentions_cards.py::test_where_to_read_first_paragraph |
| entity-mentions | Где читать | — | (общий) | tests/knowledge/test_mentions_cards.py::test_where_to_read_without_position |
| entity-mentions | Где читать | — | (общий) | tests/web/test_reader_cards.py::test_n10_where_to_read_opens_first_paragraph |
| visual-design | Раскладка экрана чтения | инвариант | колонка текста при открытой панели не уже 62ch | tests/web/test_card_layout.py::test_text_column_with_open_panel |
| visual-design | Раскладка экрана чтения | инвариант | ширина открытой панели > 448px на 1024, 1366 и 1920 | tests/web/test_card_layout.py::test_panel_wider_than_448 |
| visual-design | Раскладка экрана чтения | сценарий | Временное сворачивание навигации | tests/web/test_card_layout.py::test_pinned_navigation_collapses_while_panel_open |
| visual-design | Раскладка экрана чтения | сценарий | Колонка текста в пределах меры | tests/web/test_card_layout.py::test_closed_panel_layout_modes |
| visual-design | Раскладка экрана чтения | сценарий | Оглавление важнее поля | tests/web/test_card_layout.py::test_toc_kept_field_dropped_when_panel_opens |
| visual-design | Раскладка экрана чтения | сценарий | Панель сдвигает колонки | tests/web/test_card_layout.py::test_toc_kept_field_dropped_when_panel_opens |
| visual-design | Раскладка экрана чтения | сценарий | Плавный масштаб | tests/web/test_card_layout.py::test_root_font_scales_above_1920 |
| visual-design | Раскладка экрана чтения | сценарий | Полоска справа | tests/web/test_card_layout.py::test_strip_expands_over_text |
| visual-design | Раскладка экрана чтения | сценарий | Состав раскладок | tests/web/test_card_layout.py::test_closed_panel_layout_modes |
| visual-design | Раскладка экрана чтения | сценарий | Ширина панели по окну | tests/web/test_card_layout.py::test_panel_width_by_window |
| visual-design | Раскладка экрана чтения | — | (общий) | tests/e2e/test_reader_snapshots.py::test_s0_s5_layout |
| visual-design | Раскладка экрана чтения | — | (общий) | tests/e2e/test_reader_snapshots.py::test_strip |

### C1–C9 → тесты

| # | Критерий владельца | Тесты |
|---|---|---|
| C1 | нет линии жизни, нет текстовых статусов | `test_card_content.py::test_locke_header_and_summary` (нет `.pg-lifeline`, `.card-summary`, `[data-section=life]`, «1632» один раз), `::test_one_legend_and_no_status_words` (слова статусов вне легенды, одна `button.card-mark` с именем у каждой `.card-row`, нет `.pg-status`), `::test_row_marks_sourced_generated_disputed`, `test_reader_cards.py::test_t12_nature_of_each_row[light|dark]`, `::test_inferred_section_label_and_via` |
| C2 | сводка, свёрнутые места, влияние списком, интересы, труды | `test_card_content.py::test_locke_header_and_summary`, `::test_places_collapsed_and_expanded`, `::test_short_and_long_lists`, `::test_influence_sections_without_repeats`, `::test_only_lifespan`, `::test_historical_state_in_summary`; сервер: `test_cards_redesign.py::test_locke_header_and_summary`, `::test_places_inline_collapsed`, `::test_person_section_order_and_display`, `::test_hume_interests`, `::test_main_place_*` |
| C3 | карточки остальных типов не пусты | `test_card_content.py::test_no_card_is_empty_in_every_type` (9 типов в DOM), `::test_empty_states`; сервер: `test_cards_redesign.py::test_one_statement_never_gives_empty_card[14 типов]`, `::test_no_statements_gives_empty_card`, `::test_nothing_lost_for_every_type`, `::test_place_with_only_coordinates_is_not_empty` (**падает, дефект D4**) |
| C4 | понятия и учения: к кому относятся | `test_card_content.py::test_doctrine_card_relates_to_and_in_works`; сервер: `test_relates_to_inferred_via_work`, `test_direct_row_replaces_inferred`, `test_relates_to_term_authors_only_for_concept_and_position_in_order`, `test_relates_to_one_row_per_person`, `test_concept_card`; `test_layout::test_popup_shows_statements_only` |
| C5 | труды: автор, дата, сферы | `test_card_content.py::test_work_card_infobox`, `::test_work_card_infobox_labels` (**падает, дефект D1**); сервер: `test_work_card` |
| C6 | единая индикация, одна легенда | `test_card_content.py::test_one_legend_and_no_status_words`, `::test_mark_looks_same_in_every_card` (цвет и форма метки в разных карточках), `::test_disputed_mark_accessible_name_wording` (**падает, дефект D2**); сервер: `test_legend_equals_marks_in_every_type[14 типов]`, `test_legend_is_set_of_marks`, `test_mark_rule_for_all_combinations`, `test_inferred_mark_is_weakest_link` |
| C7 | тексты — текст | `test_card_content.py::test_markup_is_text` (имя персоны, труда, места), `::test_markup_in_values_notes_and_via_is_text`; сервер: `test_markup_in_titles_served_verbatim`, `test_markup_in_value_note_via_served_verbatim` |
| C8 | `lint-imports`, traceability, `ruff`; визуальная проверка на 1024×576 | команды ниже; `test_card_layout.py::test_card_fits_panel_in_three_sizes[light|dark]` (1024×576, 1366×768, 1920×1080: нет горизонтальной прокрутки, текст строк не обрезан, панель не на навигации), `::test_unbroken_long_word_is_wrapped`; e2e `test_s1_s4_card` — в CI |
| C9 | карточки шире, 1024×576 не ломается, панели не перекрываются | `test_card_layout.py::test_panel_width_by_window[7 окон]` (таблица сценария, `--panel`, 62–68ch, неизменность при замене карточки ассистентом), `::test_panel_wider_than_448[1024|1366|1920]`, `::test_text_column_with_open_panel[8 окон]`, `::test_card_fits_panel_in_three_sizes`, `::test_card_on_map_in_three_sizes` (`.map-chart`, `.map-panel` в окне), `::test_strip_expands_over_text`, `::test_toc_kept_field_dropped_when_panel_opens`, `::test_pinned_navigation_collapses_while_panel_open` |

### Команды и итоги (сырые строки)

```
### pytest -q tests/knowledge/test_mentions_cards.py
44 passed, 1 warning in 50.30s
### pytest -q tests/knowledge/test_cards_redesign_unit.py tests/knowledge/test_context.py tests/knowledge/test_context_unit.py tests/knowledge/test_epoch_card_unit.py tests/knowledge/test_regions.py tests/knowledge/test_graph.py tests/knowledge/test_retired_unit.py tests/knowledge/test_polities_layer_spec.py
205 passed, 1 warning in 225.93s (0:03:45)
### pytest -q tests/web/test_reader_cards.py
20 passed, 1 warning in 30.77s
### pytest -q tests/web/test_reader_layout.py
3 passed, 1 warning in 6.24s
### pytest -q tests/web/test_design_system.py
8 passed, 1 warning in 3.48s
```

Прогоны трёх новых файлов (последняя редакция; первый прогон давал те же падения плюс `test_root_font_scales_above_1920`, исправленный в самом тесте — проверялась привязка к `nav`, а не к rem):

```
### pytest -q tests/knowledge/test_cards_redesign.py
FAILED tests/knowledge/test_cards_redesign.py::test_place_with_only_coordinates_is_not_empty
1 failed, 164 passed, 1 warning in 161.51s (0:02:41)
### pytest -q tests/web/test_card_layout.py
FAILED tests/web/test_card_layout.py::test_infobox_columns_by_window_width - ...
1 failed, 40 passed, 1 warning in 207.71s (0:03:27)
### pytest -q tests/web/test_card_content.py
FAILED tests/web/test_card_content.py::test_disputed_mark_accessible_name_wording
FAILED tests/web/test_card_content.py::test_work_card_infobox_labels - Assert...
2 failed, 23 passed, 1 warning in 82.08s (0:01:22)
```

Проверки стиля и связей:

```
All checks passed!
722 files already formatted
### traceability
Требований с тестами: 433 из 433
### git diff product
(пусто = нет)
lint-imports: Contracts: 3 kept, 0 broken.
```

Сборка клиента перед браузерными прогонами: `cd web && npm run build` — rc=0.

### Мутации (15 из 15 пойманы)

Каждая мутация вносилась в продуктовый файл, прогонялся целевой тест (`-k`, `-x`), затем `git checkout -- <файл>` и пересборка клиента.
После всех мутаций `git status` по `src`, `web/src` пуст.

| # | Мутация | Упавший тест |
|---|---|---|
| 1 | `mark_of` всегда `status` | `test_cards_redesign.py::test_disputed_row` |
| 2 | отметка вывода — сильнейшее звено (`max`) | `test_cards_redesign.py::test_hume_interests` |
| 3 | в шапку персоны возвращён `.pg-lifeline` | `test_card_content.py::test_locke_header_and_summary` |
| 4 | у метки строки видимый текст статуса | `test_card_content.py::test_one_legend_and_no_status_words`, `test_reader_cards.py::test_t12_nature_of_each_row[light]` |
| 5 | вторая легенда в каждом разделе | `test_card_content.py::test_one_legend_and_no_status_words` |
| 6 | убран раздел `other` | `test_cards_redesign.py::test_nothing_lost_tabula_rasa` |
| 7 | `where_to_read` у персоны заполнен | `test_cards_redesign.py::test_person_has_no_influence_code_and_no_where`, `test_mentions_cards.py::test_person_without_where_to_read` |
| 8 | клиент игнорирует `visible` | `test_card_content.py::test_places_collapsed_and_expanded` |
| 9a | `panelWidth` всегда 36rem | `test_card_layout.py::test_panel_width_by_window[1280-False-472-K4]` |
| 9b | `panelWidth` всегда 28rem | `test_card_layout.py::test_panel_wider_than_448[1024]` |
| 10 | `dangerouslySetInnerHTML` для `label` | `test_card_content.py::test_markup_is_text` |
| 11 | основное место — без правила ролей | `test_cards_redesign.py::test_main_place_by_role[order0]` |
| 12 | `studied_with` в `influenced_by` | `test_cards_redesign.py::test_influence_both_ways_without_repeats` |
| 13 | страна без «ныне» | `test_card_content.py::test_no_layer_shows_modern_country_with_note` |
| 14 | `CardPopup` показывает выведенные строки | `test_card_layout.py::test_popup_shows_statements_only` |
| 15 | образование ищется без учёта года | `test_cards_redesign.py::test_polity_depends_on_birth_year_and_picks_smallest` |

Сырой журнал серверных мутаций (1, 2, 6, 7, 11, 12, 15):

```
1 [["tests/knowledge/test_cards_redesign.py", "disputed_row or mark_rule or legend_is_set", "1 failed, 156 deselected, 1 warning in 0.98s", ["FAILED tests/knowledge/test_cards_redesign.py::test_disputed_row - AssertionE..."]]]
2 [["tests/knowledge/test_cards_redesign.py", "weakest_link or hume_interests", "1 failed, 145 deselected, 1 warning in 0.91s", ["FAILED tests/knowledge/test_cards_redesign.py::test_hume_interests - Assertio..."]]]
6 [["tests/knowledge/test_cards_redesign.py", "nothing_lost", "1 failed, 149 deselected, 1 warning in 0.83s", ["FAILED tests/knowledge/test_cards_redesign.py::test_nothing_lost_tabula_rasa"]]]
7 [["tests/knowledge/test_cards_redesign.py", "no_influence_code_and_no_where", "1 failed, 163 deselected, 1 warning in 0.97s", ["FAILED tests/knowledge/test_cards_redesign.py::test_person_has_no_influence_code_and_no_where"]], ["tests/knowledge/test_mentions_cards.py", "person_without_where", "1 failed, 43 deselected, 1 warning in 1.93s", ["FAILED tests/knowledge/test_mentions_cards.py::test_person_without_where_to_read"]]]
11 [["tests/knowledge/test_cards_redesign.py", "main_place", "1 failed, 150 deselected, 1 warning in 0.89s", ["FAILED tests/knowledge/test_cards_redesign.py::test_main_place_by_role[order0]"]]]
12 [["tests/knowledge/test_cards_redesign.py", "influence_both or no_influence_code", "1 failed, 162 deselected, 1 warning in 1.09s", ["FAILED tests/knowledge/test_cards_redesign.py::test_influence_both_ways_without_repeats"]]]
15 [["tests/knowledge/test_cards_redesign.py", "birth_year", "1 failed, 162 deselected, 1 warning in 1.25s", ["FAILED tests/knowledge/test_cards_redesign.py::test_polity_depends_on_birth_year_and_picks_smallest"]]]
DONE
```

Сырой журнал клиентских мутаций (3, 4, 5, 8, 9a, 9b, 10, 13, 14):

```
3 [["tests/web/test_card_content.py", "locke_header", "1 failed, 24 deselected, 1 warning in 12.90s", ["FAILED tests/web/test_card_content.py::test_locke_header_and_summary[knowledge_stack0]"]]]
4 [["tests/web/test_card_content.py", "one_legend_and_no_status_words", "1 failed, 24 deselected, 1 warning in 5.90s", ["FAILED tests/web/test_card_content.py::test_one_legend_and_no_status_words - ..."]], ["tests/web/test_reader_cards.py", "t12", "1 failed, 18 deselected, 1 warning in 3.21s", ["FAILED tests/web/test_reader_cards.py::test_t12_nature_of_each_row[light] - A..."]]]
5 [["tests/web/test_card_content.py", "one_legend_and_no_status_words", "1 failed, 24 deselected, 1 warning in 13.09s", ["FAILED tests/web/test_card_content.py::test_one_legend_and_no_status_words - ..."]]]
8 [["tests/web/test_card_content.py", "places_collapsed or short_and_long", "1 failed, 23 deselected, 1 warning in 4.71s", ["FAILED tests/web/test_card_content.py::test_places_collapsed_and_expanded - a..."]]]
9a [["tests/web/test_card_layout.py", "panel_width_by_window and 1280 or text_column_with_open_panel and 1280", "1 failed, 39 deselected, 1 warning in 6.02s", ["FAILED tests/web/test_card_layout.py::test_panel_width_by_window[1280-False-472-K4]"]]]
9b [["tests/web/test_card_layout.py", "wider_than_448", "1 failed, 38 deselected, 1 warning in 5.64s", ["FAILED tests/web/test_card_layout.py::test_panel_wider_than_448[1024] - Asser..."]]]
10 [["tests/web/test_card_content.py", "markup_is_text", "1 failed, 24 deselected, 1 warning in 3.69s", ["FAILED tests/web/test_card_content.py::test_markup_is_text - AssertionError: b"]]]
13 [["tests/web/test_card_content.py", "no_layer_shows_modern or place_card_shows_modern", "1 failed, 23 deselected, 1 warning in 11.39s", ["FAILED tests/web/test_card_content.py::test_no_layer_shows_modern_country_with_note"]]]
14 [["tests/web/test_card_layout.py", "popup_shows", "1 failed, 40 deselected, 1 warning in 11.97s", ["FAILED tests/web/test_card_layout.py::test_popup_shows_statements_only - Asse..."]]]
DONE
```

### Дефекты (тест падает, продукт не правился)

**D1. Карточка труда: подписи инфобокса.** Сценарий «Карточка труда» (entity-cards «Разделы карточки по типу»): в DOM `dt` «Автор» и `dt` «Дата».
Получено: `['автор', 'датировка']` (строчная буква, «датировка» вместо «Дата»).
Тест: `tests/web/test_card_content.py::test_work_card_infobox_labels`. Значения `dd` («Джон Локк», «1689») и метки `verified`, `sourced` проверяет `test_work_card_infobox` — он проходит.

**D2. Имя метки спорной строки.** Сценарий «Спорное»: доступное имя метки содержит «Спорно» и «Не согласны: B».
Получено: `Спорно. так считает: Учебник N, Рассел. не согласны: Рассел` (строчная «не»).
Тест: `tests/web/test_card_content.py::test_disputed_mark_accessible_name_wording`. Остальная часть сценария (нет слов до нажатия, `aria-expanded`, `.card-row__details`) проходит в `test_row_marks_sourced_generated_disputed`. Мелкое расхождение в регистре. Замечание рядом: в «так считает» попал и тот, кто не согласен (Рассел); подстрока «так считает: A» есть, поэтому тест её не отвергает, но по смыслу сценария «так считает» — только A.

**D3. Инфобокс на 1366 — две колонки вместо одной (противоречие внутри дельты).** Сценарий «Инфобокс по ширине»: на 1920 две колонки, на 1366 значение под подписью.
Правило того же требования: две колонки при ширине панели от 32rem (512px). Панель на 1366 — 560px (35rem), на 1920 — 528px (33rem): по правилу обе дают две колонки. Получено: на обоих окнах `dt` и `dd` на одной высоте (1920: dtTop 327, ddTop 323; 1366: dtTop 301, ddTop 297, dtBottom 317).
Тест: `tests/web/test_card_layout.py::test_infobox_columns_by_window_width` (сценарий буквально). Правило по ширине панели проверено отдельно и проходит: `::test_infobox_columns_follow_panel_width` (1280 → одна колонка при 472px, 1680 и 1920 → две). Нужно решение: поправить сценарий или порог (чтобы на 1366 колонка была одна, порог должен быть больше 35rem, но тогда на 1920 при 33rem колонка тоже одна).

**D4. Место только с координатами — `empty = true`.** Сценарий «Ни одной пустой карточки»: у сущности каждого типа с хотя бы одним видимым утверждением, кроме `description`, `empty = false`. Получено: у места, у которого единственное утверждение — `coordinates`, `empty = true` (правило «нет строк, описания и сводки» не считает координаты; поле `geo` в расчёте не участвует). Клиент покажет «Об этом пока известно мало» рядом со страной по координатам.
Тест: `tests/knowledge/test_cards_redesign.py::test_place_with_only_coordinates_is_not_empty`.

### Переписанные ожидания MODIFIED-требований (по новой спецификации, не удалены и не ослаблены)

- `tests/knowledge/test_mentions_cards.py`: `test_where_to_read_first_paragraph` (у Канта `where_to_read == []`, поле проверено на карточке понятия), `test_sections_by_type` (нет `life`, `influence`; `layout`, `summary.years`), `test_no_empty_sections` (Гоббс: `sections == []`, `summary.years`, `empty = false`), `test_epoch_card` (+`layout = epoch`, нет `other`), `test_doctrine_historical_context` (+`mark`, `legend`, `layout`, `inferred`).
- `tests/web/test_reader_cards.py`: моки `/card` — новый контракт (`layout`, `summary`, `legend`, `mark`, `display`, `visible`, `total`); `test_t10_...` (`[data-section=influenced_by]`); `test_t12_nature_of_each_row` — метки вместо слов, одна легенда, подробности по нажатию, слова статусов только в легенде (светлая и тёмная темы); `test_n10_...` — «Где читать» теперь у карточки понятия.
- `tests/e2e/test_site.py::test_mention_opens_card_and_navigates` (сводка с годами, `influenced_by|influenced`, метка, «так считает» после нажатия), `::test_concept_card_with_definition_and_where_to_read` («так считает» после нажатия) — **проверяется в CI e2e**.
- `tests/e2e/test_reader_snapshots.py::test_s1_s4_card` (S4 без линии жизни: нет `.pg-lifeline`, `.card-summary`, `[data-section=where]`; сводка с годами один раз; шире 448px; нет горизонтальной прокрутки) — **проверяется в CI e2e**; эталоны снимков только Windows.
- `tests/web/test_reader_layout.py` — прежние 3 теста проходят без правок (`3 passed`).

### Исключения из проверки журнала

- `tests/web/test_card_layout.py::test_country_data_is_a_separate_chunk` — свойство сборки, события нет (сказано в сценарии «Основной фрагмент не растёт»).
- `tests/web/test_card_layout.py::test_root_font_scales_above_1920`, `::test_closed_panel_layout_modes` — панель закрыта, карточка не запрашивается; последний проверяет, что `knowledge.card.served` не писалось.
- `tests/knowledge/test_mentions_cards.py::test_where_to_read_causality` — указатель `/where`, не карточка.

### Не покрыто

- **E2E (Docker)** не запускались по ограничению сервера: `tests/e2e/test_site.py`, `tests/e2e/test_reader_snapshots.py`. Ожидания переписаны по спецификации, проверка — в CI e2e.
- **«Основной фрагмент не растёт»:** вес точки входа сравнивается с константой 158 566 байт из `progress.md` (3.x), собранной разработчиком до изменения; я не пересобирал базовый коммит. Проверяется: `countries-*.js` лежит отдельно, в точке входа нет границ, gzip -9 точки входа не больше константы + 15 КБ.
- **«Тексты карточки — текст»:** покрыты `title`, `label`, `value`, `note`, `via[].label`, названия труда и места. Не покрыты отдельными тестами: атрибуции, названия источников и глав в «Где читать», подписи портретов (механизм вывода — тот же текстовый узел React; мутация 10 ловится на `label`).
- **«Выведенные строки», скрытие по региону:** проверено скрытие источника оператором (`_set_source_hidden`) и отвергнутые утверждения; регион сам утверждение не скрывает, а снимает подтверждение и атрибуции (`test_region_hides_evidence_but_keeps_mark`: отметка `sourced` остаётся). Строка «не скрытых по региону читателя» из дельты трактуется так же.
- **Английский интерфейс** (`i18n/en.ts`: «now …», «Show all»): не проверялся.
- **Тёмная тема** — для таблицы ширины панели (`test_panel_width_by_window`) только светлая; раскладка карточки на трёх размерах — обе.
- **Визуальные снимки** — эталоны только Windows, на Linux сравнение пропускается (по `AGENTS.md`).
- Полный `pytest` не запускался (по условию задачи).
