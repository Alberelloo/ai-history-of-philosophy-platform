# Verification — add-epoch-context

## Тестировщик — 2026-11-25, ветка `claude/epoch-context`, тесты от коммита f2fb2a9

Модель — Opus (решение ведущего, progress.md). Тесты написаны по дельтам `specs/{epoch-context,ontology-registry,entity-cards,knowledge-graph,visual-design}`; код читался только для точек входа (`svc.get`, `Graphs.build`, `EpochContextImport.apply`, `harvest`, `main(..., fetch=, service=)`, классы DOM блока и карты) и для мест мутаций. Модель — только фейковая (`Scripted` в `test_filling.py`, `FakeProvider` в `test_graph.py` и стенде). Сеть запрещена: `no_network` (`tests/knowledge/wd_records.py`), Wikidata — `FixtureFetch` (`tests/knowledge/fixtures/wikidata`), в браузере — ловушки стенда (`outside`, `router.unexpected`, `llm_calls`). Каждый ответ API сводится с событием журнала по `request_id`.

Стенд `tests/web/knowledge_stack.py` расширен тестировщиком: граф (`Graphs`, маршрут `/graph/build`) с фейковой моделью шлюза моделей (`stack.model`), очередь сохранения `stack.queue` (воркер запускает тест), абзацы учебников `stack.paragraph(key, needle)`, в учебник стенда добавлен абзац «Тогда парламент низложил короля.». Прежние тесты, изменённые по дельте visual-design (подпись «Эпохи и контекст»): `tests/web/test_epochs.py::test_old_epochs_bookmark` (ссылка `name="Эпохи и контекст", exact=True`), `tests/web/test_reference.py::test_live_items_without_soon` (то же, точное имя).

### Требования, сценарии, инварианты

| Требование | Сценарий / инвариант | Тест | Вывод | Журнал |
|---|---|---|---|---|
| Контекст эпохи | Контекст Просвещения | tests/knowledge/test_context.py::test_enlightenment_context | порядок Ньютон 1687, Славная 1688, Пузырь 1720, Энциклопедия 1751; kind political, places [{Лондон, wikidata null}], basis dates; связь political/sourced/generated false/in_textbook true/evidence [{p_1,/p/p_1}]; counts 4 ключа по 1; `svc.llm_calls == []` | context.served mode=epoch events=4 links=1 generated_links=0 truncated=false, snapshot есть (request_id) |
| Контекст эпохи | без учебника in_textbook=null; чужой — false | ::test_in_textbook_marks | None / False | served |
| Контекст эпохи | Окно времени | ::test_window | Пузырь, Энциклопедия; epoch null; window {1700,1760}; basis null | served mode=window events=2 |
| Контекст эпохи | окно [from,to) по середине | ::test_window_bounds[4], ::test_window_uses_middle_of_dating | 1751 — граница to не входит, from входит; война 1756–1763 — в [1759,1760) | served events=n |
| Контекст эпохи | Фильтр видов | ::test_kinds_filter | Славная, Пузырь; counts = без kinds | served events=2 |
| Контекст эпохи | kinds=none | ::test_kinds_none | событие без вида, kind null, counts.none=1 | served events=1 |
| Контекст эпохи | только события/явления/идейные события | ::test_only_event_types | phenomenon, idea_event есть; труд, персона нет | served |
| Контекст эпохи | basis explicit/dates | ::test_basis_explicit | explicit у явного | served |
| Контекст эпохи | порядок событий: начало, название | ::test_events_order_ties_by_label | 1688: «Акт…» раньше «Славной» | served |
| Контекст эпохи | порядок связей: проверенные, по источникам, сгенерированные, по названию | ::test_links_order | В(verified), Б, Г (sourced), А (generated) | served |
| Контекст эпохи | Отклонённое не показывается | ::test_rejected_not_shown, ::test_deprecated_not_shown | stimulated=[], id отклонённой нет в теле | served links=0 |
| Контекст эпохи | Усечение | ::test_truncation | 200 событий без «Ничтожного», 30 связей (Учение 00–29), truncated=true, sum(counts)=201, none=1 | served truncated=true events=200 links=30 |
| Контекст эпохи | усечение только по связям | ::test_truncation_by_links_only | 4 события, truncated=true | served truncated=true |
| Контекст эпохи | не вызывает модель | ::test_no_model_calls | llm_calls == [] в трёх режимах | served |
| Контекст эпохи | поля записи в обоих режимах | ::test_event_record_fields | ключи события и связи по требованию | served |
| Проверка параметров контекста | Границы параметров | ::test_parameter_bounds[7] | 400 + kind по таблице | ровно одно context.rejected с reason; served нет; «17x0», «culinary» нет в журнале |
| Проверка параметров контекста | прочие нарушения таблицы | ::test_parameter_table_more[9] | только to, from>to, 1700.5, пустое, epoch+to, нет сущности, частично неверный kinds, kinds в окне, регистр | rejected reason |
| Проверка параметров контекста | context.* — только id, коды, числа | ::test_events_without_parameter_values[5] | без «script», названий, адреса посетителя, региона; значения полей — скаляры | одно событие context.* |
| Пометка непроверенного контекста | Сгенерированная связь помечена (API) | ::test_generated_link_marked | generated=true, status generated | served generated_links=1 |
| Пометка непроверенного контекста | Только проверенные | ::test_verified_only | статусы ["sourced"], Ньютон stimulated=[] | served generated_links=0 links=1 |
| Пометка непроверенного контекста | generated всегда = status generated | ::test_generated_always_flagged[4] | 4 связи, флаг совпадает со статусом | served generated_links=2 |
| Пометка непроверенного контекста | verified=true/1: нет generated, события остаются | ::test_verified_drops_generated_keeps_events[2] | 4 события, все stimulated=[] | served generated_links=0 links=0 |
| Пометка непроверенного контекста | пометка в карточке | ::test_generated_marked_in_card | row.generated=true | card.served (request_id) |
| Механизм влияния | Механизм вне списка | ::test_manual_unknown_mechanism_refused, tests/knowledge/test_filling.py::test_manual_mechanism_refused_event | StatementError, утверждений нет | statement.refused type=stimulated, reason с «culinary» и «mechanism» |
| Механизм влияния | вне списка — не пишется (ручная запись) | test_context.py::test_manual_mechanism_outside_list[6] | "", Political, «political », разметка, число | statement.refused type=stimulated |
| Механизм влияния | шесть механизмов списка | ::test_listed_mechanisms[6] | mechanism отдаётся как есть | statement.created type=stimulated |
| Механизм влияния | Механизм не указан (API) | ::test_mechanism_missing_is_null | mechanism null | served links=1 |
| Механизм влияния | вне списка не пишется при извлечении | test_filling.py::test_extraction_never_writes_bad_mechanism[6] | stimulated нет, holds сохранён | extraction.dropped=1, fragment created=1 dropped=1 |
| Механизм влияния | импорт механизма не пишет | test_epoch_context_import.py::test_never_writes_stimulated_mechanism_influence | ни одного qualifiers.mechanism | run statements=4 |
| Механизм влияния | механизм модели отбрасывается при достройке | test_graph.py::test_model_mechanism_never_saved[4] | qualifiers {} у ребра и сохранённого, status generated | graph.saved statements=1 |
| Контекст из текста | Связь из фрагмента | test_filling.py::test_stimulated_from_fragment | одно stimulated sourced, qualifiers political, evidence quote абзаца 1, атрибуция источника, концы event→doctrine | statement.created type=stimulated; fragment created=1 dropped=0 |
| Контекст из текста | Механизм вне списка при извлечении | ::test_extraction_mechanism_outside_list | сохранена только «Славная революция» | extraction.dropped reason с «culinary»; fragment 1/1 |
| Контекст из текста | Стимулировало от персоны | ::test_extraction_stimulated_from_person | не записано | extraction.dropped reason начинается «тип stimulated не подходит концам»; fragment 0/1 |
| Контекст из текста | от персоны — и при ручной записи | ::test_manual_stimulated_from_person_refused | StatementError | statement.refused type=stimulated |
| Контекстные события из Wikidata | Кандидаты в манифест | test_epoch_context_import.py::test_harvest_candidates | 2 кандидата pending; революция political, Париж; 1755 kind null; без даты нет; строки всех таблиц схемы равны; запросы только к wikidata.org | harvested epochs=1 candidates=2 |
| Контекстные события из Wikidata | Принятый кандидат | ::test_accepted_candidate, ::test_accepted_only_candidate_skipped_zero | событие и Париж с внешними id; dating 1789, event_kind political, belongs_to_epoch (historians), happened_in; sourced, атрибуция `wikidata:Q910011` со ссылкой `https://www.wikidata.org/wiki/Q910011`, provenance imported; stimulated 0; +2 сущности | checked created; run apply created=1 statements=4 places_created=1 skipped=0 (в манифесте только принятый) |
| Контекстные события из Wikidata | Ожидающий и отклонённый | ::test_pending_and_rejected | строки таблиц равны | checked pending, rejected; run skipped=2 |
| Контекстные события из Wikidata | Повторный запуск и проверка | ::test_repeat_apply_and_dry_run | второй apply — строки равны; dry-run — строки равны, события нет | checked exists; run 0/0/0; run dry_run created=1 |
| Контекстные события из Wikidata | Повторный подбор не сбрасывает решения | ::test_repeat_harvest_keeps_decisions | accepted/rejected на месте, без задвоения | harvested candidates=2 |
| Контекстные события из Wikidata | поля человека не меняются | ::test_repeat_harvest_keeps_human_fields | кандидат равен правленому | harvested |
| Контекстные события из Wikidata | stimulated, механизм, влияние не пишутся | ::test_never_writes_stimulated_mechanism_influence | в записи P737/P1542/P828 и лишние поля манифеста — нет stimulated/influenced_by/circumstance/participated, нет mechanism | run statements=4 |
| Контекстные события из Wikidata | класс не из таблицы — вида нет | ::test_unknown_class_no_kind | только dating, belongs_to_epoch | run 1/2/0 |
| Контекстные события из Wikidata | без даты не предлагается | ::test_undated_never_offered | Q910013 нет в манифесте | — (чистое правило, проверено и в сценарии с harvested) |
| Контекстные события из Wikidata | найденные по QID: точные числа | ::test_found_by_qid | сущностей не прибавилось, happened_in → прежний Париж | run created=1 statements=4 places_created=0 |
| Контекстные события из Wikidata | no_date, fetch_failed | ::test_no_date_and_fetch_failed | строки равны | checked fetch_failed, no_date; run skipped=2 |
| Контекстные события из Wikidata | --dry-run не меняет таблиц (CLI) | ::test_cli_dry_run_changes_nothing | код 0, строки равны; затем apply меняет | run dry_run created=2 places_created=1; затем apply |
| Контекстные события из Wikidata | журнал импорта без названий | ::test_import_events_only_codes | нет «Французская», «Париж», «Просвещение» | harvested/checked/run |
| Достройка контекста моделью | Достроить контекст (сервис) | tests/knowledge/test_graph.py::test_context_extension_drops_mechanism_and_foreign_type | одно ребро stimulated → «Два трактата», qualifiers {}; сохранено qualifiers {}, generated; influenced_by не записан | graph.extended recipe=context proposed=1 dropped=1; proposal_dropped outside_recipe; graph.saved statements=1 |
| Достройка контекста моделью | Уже достраивали (сервис) | ::test_context_extension_done_before | вызовов модели не прибавилось | graph.built extension=done_before; нет graph.extended |
| Достройка контекста моделью | Связей достаточно (сервис) | ::test_context_extension_not_needed | 5 рёбер, модель не вызвана | graph.built not_needed; нет extended |
| Достройка контекста моделью | Генерация выключена (сервис) | ::test_context_extension_disabled | disabled, модель не вызвана | нет extended |
| Достройка контекста моделью | только семейство «контекст», только существующие | ::test_context_extension_only_context_family | принята одна; отброшены develops, «Левиафан», от персоны | proposal_dropped ×3 (outside_recipe, unknown_entity, …); extended dropped=3 |
| Достройка контекста моделью | scope | ::test_context_extension_scope | модель не вызвана | нет extended |
| Достройка контекста моделью | совпадающее с отклонённым | ::test_context_extension_rejected_before | ребра нет, очередь пуста | proposal_dropped rejected_before |
| Достройка контекста моделью | Достроить контекст (браузер) | tests/web/test_epochs.py::test_extend_context | строка «Два трактата…» data-unverified=true, «механизм не указан», «не проверено»; после воркера и перезагрузки — сохранённая строка так же; в базе qualifiers {}, generated | graph.extended recipe=context entity_id 1/1; proposal_dropped outside_recipe; graph.saved 1; context.served generated_links=1 (request_id перезапроса) |
| Достройка контекста моделью | Уже достраивали (браузер) | ::test_extend_done_before | «Контекст этого события уже достраивали.», вызовов модели 1 | graph.built done_before; нет нового extended |
| Достройка контекста моделью | Связей достаточно (браузер) | ::test_extend_not_needed | «Связей достаточно, достройка не нужна.», model.calls == [] | graph.built not_needed; нет extended |
| Достройка контекста моделью | Генерация выключена (браузер) | ::test_extend_hidden_without_generation | кнопок 0; в хранилище generation=false | context.served (request_id); нет graph.extended |
| Достройка контекста моделью | причина scope (браузер) | ::test_extend_scope_message | «В режиме «только выбранный учебник» достройки нет.» | graph.built extension=scope |
| Контекст на странице эпохи | Блок контекста | ::test_context_block | блок под заголовком эпохи; группы political, economic, scientific, intellectual («Политика», «Экономика», «Наука», «Идеи»); «1688 Славная революция · Лондон»; строка начинается «Политическая философия Локка · политический · по источникам · ¶», ¶ → /p/<id>; «1720 Южноморский пузырь» — «связей пока нет»; групп Общество/Религия/Биография/Прочее нет | context.served mode=epoch events=4 (request_id) |
| Контекст на странице эпохи | Фильтр групп | ::test_context_kind_filter | одно событие Ньютон, aria-pressed=true, адрес kinds=scientific | context.served events=1 |
| Контекст на странице эпохи | фильтры из адреса | ::test_context_filters_from_address | группы political, scientific; пометок нет; флажок отмечен; запрос verified=true | served events=2 generated_links=0 |
| Контекст на странице эпохи | Закрытый источник | ::test_context_closed_source | статус «по источникам», без ¶; в API evidence=[]; тела ответа и страницы без id абзаца и «парламент низложил короля» | served (request_id) |
| Контекст на странице эпохи | Контекста нет | ::test_context_empty | «Для этой эпохи контекст пока не собран.», событий 0 | served events=0 |
| Контекст на странице эпохи | Разметка в названии события | ::test_context_markup_in_event_name | название и объект буквально, img нет, `window.__xss` undefined, pageerror нет | served events=1 |
| Контекст на странице эпохи | ошибка — «Повторить», без pageerror/console.error | ::test_context_error_and_retry | 503 подменён (page.route), после «Повторить» события на месте | served нет до повтора; после — events=4 |
| Контекст на странице эпохи | показана часть | ::test_context_partial | «Показана часть событий: самые значимые 200 из 201.», 200 событий (данные — настоящие 201 событие, без page.route) | served truncated=true events=200 |
| Контекст на странице эпохи | клавиатура: aria-pressed, Tab — все ссылки и кнопки в порядке чтения | ::test_context_keyboard | Enter на «Наука» фильтрует; Tab проходит все a/button/input блока, порядок — сверху вниз, в строке слева направо | served events=1 |
| Пометка непроверенного контекста | Сгенерированная связь помечена (браузер) | ::test_generated_link_marked_on_page | data-unverified=true, «не проверено» | served generated_links=1 |
| Пометка непроверенного контекста | без пометки нигде на странице; «только проверенные» | ::test_every_generated_row_marked | 4 сгенерированные строки помечены; флажок — 0 пометок, 4 события, адрес verified=1 | served generated_links=0 |
| Механизм влияния | Механизм не указан (браузер) | ::test_mechanism_missing_on_page | «механизм не указан»; API null | served |
| Виды групп, роли персон и виды событий | Экономическое событие в существующей базе | tests/knowledge/test_registry_entities.py::test_economic_event_in_existing_database | economic сохранён; утверждений +1, прежний political на месте | registry.changed version+1, change с «дозагрузка реестра» и «event_kind», затем statement.created type=event_kind |
| Виды групп, роли персон и виды событий | семь видов допустимы; вне списка — отказ с перечнем | ::test_all_event_kinds_accepted[7], ::test_event_kind_outside_list[4] | | statement.created / statement.refused type=event_kind |
| Разделы карточки по типу | Исторический контекст учения | tests/knowledge/test_mentions_cards.py::test_doctrine_historical_context | коды ровно ["context"], «Исторический контекст»; строки: Славная (political, sourced, ¶ p_1), Ньютон (qualifiers {}, generated) | card.served sections=1 rows=2 (request_id) |
| Разделы карточки по типу | раздел у понятия, персоны, труда, учений | ::test_context_section_for_types[7] | строка с механизмом | card.served |
| Разделы карточки по типу | у события — не «Исторический контекст» | ::test_event_card_has_no_context_section | | card.served |
| Выбор на карте | Событие и то, что оно стимулировало (API) | tests/knowledge/test_map.py::test_map_event_stimulated_api | stimulated [{Основа…, false}, {Шеллинг, true}] | map.built (request_id) |
| Выбор на карте | Стимулированное вне карты | ::test_map_stimulated_outside_map | у события без объектов на карте поля нет; понятие без даты не попадает | map.built |
| Выбор на карте | ≤30, проверенные раньше сгенерированных | ::test_map_stimulated_limit_and_order | 30 проверенных, сгенерированных нет | map.built |
| Выбор на карте | отклонённая не попадает | ::test_map_stimulated_rejected | | map.built |
| Выбор на карте | Событие и то, что оно стимулировало (браузер) | tests/web/test_map.py::test_event_highlights_what_it_stimulated | **ПАДАЕТ — Д1, Д2**; прочее совпало: API stimulated по сценарию, Фихте, Шеллинг, «Основа…» data-related=true, линий 0, адрес verified=1 | map.built (request_id) |
| Выбор на карте | вне десятилетнего окна | ::test_event_stimulated_outside_window | труд 1781 при событии 1688 — data-related=true | map.built |
| Выбор на карте | «только проверенные» снимает сгенерированную | ::test_event_generated_stimulated_off_when_verified | Юм (не жил в 1688): true → false | map.built |
| Разделы в разработке | Старая закладка эпох | tests/web/test_epochs.py::test_old_epochs_bookmark | /soon/epochs → /epochs без записи, ссылка «Эпохи и контекст» (точно) без «скоро» | knowledge.epochs.listed (request_id) |
| Разделы в разработке | Ассистент без метки | tests/web/test_reference.py::test_live_items_without_soon | «Эпохи и контекст» → /epochs, без «скоро» | catalog.listed (request_id) |

### Дефекты

- **Д1** (knowledge-graph, «Выбор на карте», сценарий «Событие и то, что оно стимулировало»): ожидалось — у Фихте и Шеллинга свои цвета раньше прочих участников; получено — при семи более значимых современниках Фихте (автор стимулированной «Основы…») получает `other`, Шеллинг — `c6`. `web/src/map/model.ts`: в приоритет `group(…, stim)` попадают только id из `stimulated` (труд «Основы…», Шеллинг), автор стимулированного труда приоритета не получает. Требование говорит «сначала стимулированные персоны», сценарий — «у Фихте… свои цвета раньше прочих»: либо код (автор стимулированного труда — тоже в приоритете), либо сценарий (Фихте убрать). Решение — разработчику/ведущему. Вывод теста: `AssertionError: ('fichte', {'fichte': 'other', 'schelling': 'c6'})`.
- **Д2** (там же): ожидалось — при «только проверенные» у Шеллинга `data-related="false"`; получено — `"true"`: Шеллинг (1775–1854) жил в 1789 и остаётся участником по правилу «жившие в этот год». Сценарий противоречит правилу «Выбрано событие» при данных самого сценария — дефект спецификации (или данных сценария: Шеллинг должен не жить в год события). Правило без этого противоречия подтверждено `test_event_generated_stimulated_off_when_verified`. Утверждение стоит в тесте последним; до него дойдёт после исправления Д1.

### Интерфейсные THEN без серверного события (якорь — серверное событие с request_id ответа страницы)

- адрес `kinds=scientific`, `verified=1` — якорь `knowledge.context.served` (test_context_kind_filter, test_every_generated_row_marked);
- порядок Tab, aria-pressed, фокус — `knowledge.context.served` (test_context_keyboard);
- текст «связей пока нет», группы и их порядок, буквальный вывод названия, отсутствие `window.__xss` — `knowledge.context.served` (test_context_block, test_context_markup_in_event_name);
- сообщения причин «уже достраивали», «связей достаточно», «только выбранный учебник» — `knowledge.graph.built` с `extension`;
- кнопок «Достроить контекст» 0 — `knowledge.context.served` и отсутствие `knowledge.graph.extended`;
- «Повторить» после 503 — якорь только у повторного запроса (первый подменён `page.route`, до сервиса не дошёл);
- data-related и цвета на карте — `knowledge.map.built`;
- замена адреса `/soon/epochs` — `knowledge.epochs.listed`.

### Команды и итоги

    cd web && npm run build                                   →  ✓ built in 4.95s
    pytest -q -p no:cacheprovider tests/knowledge             →  777 passed, 1 skipped in 614.83s (skip — гонка PostgreSQL, прежний)
    pytest -q tests/knowledge/test_context.py                 →  78 passed (отдельный прогон)
    pytest -q tests/knowledge/test_epoch_context_import.py    →  14 passed in 6.26s
    pytest -q tests/knowledge/test_graph.py                   →  24 passed in 24.29s
    pytest -q tests/web/test_epochs.py                        →  1 failed, 39 passed in 172.90s
        FAILED test_accessible_names — TimeoutError: Page.expect_response 8000ms "**/api/knowledge/v1/epochs*"
        (прежний тест, не менялся); отдельно: 1 passed in 4.66s, 1 passed in 4.44s; на коде без моих
        правок тестов (git stash) — 1 passed in 4.35s → нестабильность под нагрузкой машины, не регрессия
    pytest -q tests/web/test_map.py                           →  1 failed, 50 passed in 306.48s
        FAILED test_event_highlights_what_it_stimulated — AssertionError: ('fichte', {'fichte': 'other', 'schelling': 'c6'})  (Д1)
        дизайн-якоря карты (линии жизни, узлы, anchorOn, test_fuzzy_edge_keeps_design_anchors) — passed
    pytest -q tests/web/test_reference.py                     →  31 passed in 86.52s
    python scripts/check_traceability.py (epoch-context в enforce) →  Требований с тестами: 387 из 387
    ruff check tests src → All checks passed!; ruff format --check . → все отформатированы; lint-imports → 3 kept, 0 broken
    ruff check . → 1 ошибка E501 в scripts/dev_stack.py:100 (не из этого круга тестировщика, файл не менялся мной)

### Мутации

Скрипт ломает файл, гоняет тесты, возвращает `git checkout -- <файл>`; после каждой — `git diff --stat -- src` пусто.

    (а) context.py "generated": False                 → упали test_generated_link_marked, test_generated_always_flagged[4]   (5 failed)
    (б) verified не фильтрует (links = list(...))     → упали test_verified_only, test_verified_drops_generated_keeps_events[2] (3 failed)
    (в) в evidence добавлена "quote"                   → упали test_no_quotes_ever[None,RU,DE,US] (4 failed)
    (г) закрытый источник не снимается из evidence     → упали test_closed_source_stripped — 9 failed
    (г2) атрибуции закрытого источника не снимаются    → test_closed_source_stripped — 9 failed
    (д) apply пишет pending (оба места выбора)         → упал test_pending_and_rejected: entities 3 != 1, statements 5 != 1
        (первая попытка — только одно место — давала KeyError, тоже падение; засчитана вторая)
    (е) apply пишет stimulated из P737 с механизмом    → упал test_never_writes_stimulated_mechanism_influence: ('stimulated', [... 'stimulated'])
    (ж) механизм не проверяется (registry.check_qualifiers) → упали test_extraction_mechanism_outside_list, test_extraction_never_writes_bad_mechanism[6] (8 failed)
    (з) карта рисует линии при выборе события (model.ts, сборка web) → упал test_event_highlights_what_it_stimulated: `.map-thread` count 1 == 0
        (падение на утверждении линий, до Д1); model.ts возвращён, web пересобран
    (и) counts после kinds                             → упал test_kinds_filter (1 failed)
    (к) механизм модели сохраняется (_proposal + _save) → упали test_context_extension_drops_mechanism_and_foreign_type, test_model_mechanism_never_saved[political, economic] (3 failed)
        (первая попытка — механизм только в _proposal, _save его не читает — выжила: 5 passed; мутация была неполной, засчитана вторая)
    (л) в context.rejected значения kinds и from       → упали test_parameter_bounds[4 из 7 — где значение есть], test_events_without_parameter_values (10 failed)

### Не прогонялось

- e2e (`tests/e2e`), Docker, визуальные эталоны снимков (эталоны только Windows) — CI/Lead; полный `pytest` — не по силам машине (1 ГБ, 1 CPU).
- Инвариант «Сгенерированная связь MUST NOT показываться без пометки … карта»: на карте связи «стимулировало» линиями не рисуются; пометка «не проверено» на карте для подсветки по сгенерированной связи спецификацией не задана — проверено только снятие подсветки при «только проверенные».
- Лимиты `limit`/`visitor_limit`/`unavailable` в блоке: тексты — `NOTICES` графа (существующее поведение, `tests/knowledge/test_graph.py::test_no_extension_when_disabled_or_limit`); в браузере для блока контекста не проверены — стенд без лимитов шлюза.

## Тестировщик — повторный прогон после исправлений, 2026-11-25, от коммита 519b1e5

Решения ведущего (progress.md): Д1 — дефект кода, исправлен (519b1e5), требование уточнено («стимулированные напрямую и авторы стимулированных трудов»); Д2 — сценарий изменён: адресат сгенерированной связи — Маркс (1818–1883), GIVEN — не меньше семи более значимых современников.

Тесты обновлены строго по новой формулировке, проверки не ослаблены: `tests/web/test_map.py::test_event_highlights_what_it_stimulated` (Шеллинг → Маркс; свои цвета c1…c6 у Фихте и Маркса при семи более значимых современниках; линий 0; `stimulated` в `/v1/map`; «только проверенные» → у Маркса `data-related="false"`; `knowledge.map.built` по request_id), `tests/knowledge/test_map.py::_revolution_world` (то же для API).

    cd web && npm run build                                        →  ✓ built in 5.49s
    pytest -q tests/knowledge/test_map.py tests/knowledge/test_map_snapshot_parity.py  →  19 passed in 21.80s
    pytest -q tests/web/test_map.py                                →  51 passed in 313.33s
    pytest -q tests/web/test_epochs.py                             →  40 passed in 137.83s (test_accessible_names прошёл, таймаута нет)

Мутация: в `web/src/map/model.ts` приоритет цветов только по id из `stimulated` (`group(..., stim)` вместо `stimPeople`), сборка web →
    test_event_highlights_what_it_stimulated: AssertionError: ('fichte', {'fichte': 'other', 'marx': 'c6'})  — 1 failed
    возвращено `git checkout -- web/src/map/model.ts`, пересобрано, `git diff --stat -- src web/src` пусто; тест — 1 passed.

Д1 и Д2 закрыты.

## Тестировщик — повторный прогон после ревью, круг 1, 2026-11-25, от коммита 55b6fb6

Правки разработчика d470065; дельта `epoch-context` дополнена по решению ведущего (поле `events[].wikidata`, `result=duplicate_qid`). Новые тесты:

| Требование | Сценарий / инвариант | Тест | Вывод | Журнал |
|---|---|---|---|---|
| Пометка непроверенного контекста | «только проверенные» скрывает и только что достроенное | tests/web/test_epochs.py::test_verified_hides_just_extended | `?verified=1` → «Достроить контекст» (FakeProvider предлагает stimulated) → строки «Два трактата…» 0, `data-unverified="true"` 0; перезапрос verified=true; после снятия фильтра строка видна с `data-unverified="true"` | graph.extended recipe=context proposed=1 по request_id потока; context.served generated_links=0 (request_id первого ответа и перезапроса); model.calls=1 |
| Контекст эпохи | events[].wikidata — только Q<число>, иначе null | tests/knowledge/test_context.py::test_event_wikidata_field, ::test_event_wikidata_hostile[5] | "Q6534" в обоих режимах, без внешнего id — null; «Q12<script>», «q6534», «Q», «P31», адрес — null и не в теле | context.served |
| Контекст на странице эпохи | ссылка «Wikidata ↗» из проверенного QID | tests/web/test_epochs.py::test_event_wikidata_link | href https://www.wikidata.org/wiki/Q6534; у испорченного QID (с кавычкой и onmouseover) и без QID ссылки нет | context.served events=3 |
| Контекстные события из Wikidata | duplicate_qid (QID события у места / QID места у события) | tests/knowledge/test_epoch_context_import.py::test_duplicate_qid_other_type[event, place] | строки всех таблиц схемы равны | checked result=duplicate_qid; run 0/0/0, skipped=2 (duplicate_qid + pending) |
| Контекст на странице эпохи | вид из адреса без событий | tests/web/test_epochs.py::test_kind_from_address_without_events | `?kinds=social`: кнопка «Общество 0» aria-pressed=true, событий 0, «Событий выбранных видов в этой эпохе нет.»; отжатие — 4 события | context.served events=0, затем events=4 |

Команды и итоги (после `cd web && npm run build` → ✓ built in 5.08s; файлы по одному):
    tests/knowledge/test_catalog.py:  125 passed, 1 warning in 139.45s (0:02:19)
    tests/knowledge/test_catalog_route.py:  7 passed, 1 warning in 3.28s
    tests/knowledge/test_catalog_unit.py:  29 passed in 13.90s
    tests/knowledge/test_context.py:  84 passed, 1 warning in 100.52s (0:01:40)
    tests/knowledge/test_context_unit.py:  25 passed, 1 warning in 22.16s
    tests/knowledge/test_dates_span.py:  9 passed in 0.09s
    tests/knowledge/test_entities_external.py:  4 passed in 1.36s
    tests/knowledge/test_epoch_card_unit.py:  1 passed in 0.63s
    tests/knowledge/test_epoch_context_import.py:  16 passed in 7.76s
    tests/knowledge/test_epoch_dates.py:  66 passed, 1 warning in 24.77s
    tests/knowledge/test_epoch_dates_unit.py:  19 passed in 4.55s
    tests/knowledge/test_epochs_list.py:  11 passed, 1 warning in 31.40s
    tests/knowledge/test_epochs_list_unit.py:  3 passed, 1 warning in 1.33s
    tests/knowledge/test_epochs_membership.py:  55 passed, 1 warning in 36.48s
    tests/knowledge/test_epochs_unit.py:  8 passed in 4.87s
    tests/knowledge/test_external_processing.py:  2 passed in 1.13s
    tests/knowledge/test_filling.py:  30 passed, 1 warning in 35.10s
    tests/knowledge/test_graph.py:  24 passed, 1 warning in 24.18s
    tests/knowledge/test_map.py:  16 passed, 1 warning in 17.71s
    tests/knowledge/test_map_snapshot_parity.py:  3 passed, 1 warning in 3.94s
    tests/knowledge/test_map_view.py:  10 passed, 1 warning in 8.80s
    tests/knowledge/test_mentions_cards.py:  32 passed, 1 warning in 31.42s
    tests/knowledge/test_portrait_source.py:  35 passed in 0.55s
    tests/knowledge/test_portraits.py:  13 passed, 1 warning in 4.59s
    tests/knowledge/test_reference_groups.py:  1 passed in 0.02s
    tests/knowledge/test_regions.py:  10 passed, 1 warning in 3.91s
    tests/knowledge/test_registry_entities.py:  33 passed, 1 skipped in 12.64s
    tests/knowledge/test_service.py:  3 passed, 1 warning in 2.60s
    tests/knowledge/test_snapshot.py:  6 passed in 2.25s
    tests/knowledge/test_statements.py:  19 passed in 7.98s
    tests/knowledge/test_wikidata.py:  52 passed in 12.65s
    tests/knowledge/test_wikidata_unit.py:  36 passed in 0.15s
    tests/web/test_epochs.py:  43 passed, 1 warning in 148.46s (0:02:28)
    tests/web/test_map.py:  51 passed, 1 warning in 308.61s (0:05:08)
    check_traceability → Требований с тестами: 387 из 387; ruff check/format tests — чисто

Мутация (блок. 1 ревью): в ContextBlock.tsx `build.added` показывается без `shownLink` (фильтр только у ответа сервера), сборка web →
    test_verified_hides_just_extended: `expect(...target has_text «Два трактата…»).to_have_count(0)` — AssertionError, 1 failed
    возвращено `git checkout -- web/src/epochs/ContextBlock.tsx`, пересобрано, `git diff --stat -- src web/src` пусто; тест — 1 passed.

`test_accessible_names` в этом прогоне прошёл (таймаута нет).

## Судья — 2026-11-25, коммит 032b3d5

Ветка `claude/epoch-context`, рабочее дерево чистое, HEAD = origin. Продуктовый код (`src`, `web/src`, `scripts`, `sources`) с последнего прогона тестировщика (55b6fb6) не менялся (`git diff --stat 55b6fb6 HEAD` — только `openspec/…`, тесты круга 1). Модель везде фейковая, сети нет. Ограничения машины: 1 ГБ RAM, 1 CPU, без Docker. Поэтому `pytest` гонялся по файлам и пакетам последовательно, а не одной командой.

### Свой прогон

    ruff check .                → 1 ошибка E501 scripts/dev_stack.py:100
    ruff format --check .       → 3 файла: scripts/dev_stack.py, platform/queue.py, prompts/__init__.py
        все три файла изменением не тронуты (git diff claude/epochs...HEAD по ним пуст); на копии
        из claude/epochs те же файлы дают 2 ошибки check и 3 файла format — прежний долг базы
    lint-imports                → Contracts: 3 kept, 0 broken
    check_traceability.py       → Требований с тестами: 387 из 387
    cd web && npm run build     → ✓ built in 5.11s
    tests/knowledge/* по файлам → все зелёные, числа совпадают с журналом тестировщика файл в файл
        (test_context 84, test_context_unit 25, test_epoch_context_import 16, test_filling 30,
         test_graph 24, test_map 16, test_mentions_cards 32, test_registry_entities 33 + 1 skip —
         прежний skip «гонка PostgreSQL»; остальные 25 файлов — как в журнале)
    tests/web/* по файлам       → test_epochs 43 passed, test_map 51, test_reference 31, остальные 15 файлов зелёные
    tests/gateway 41, tests/assistant 51, tests/platform 21, tests/llm 20, tests/search 39,
    tests/library 170, tests/operator 5, tests/evaluation 17 — все passed, падений 0

Не прогонялось: `tests/e2e` и `tests/ops` (нужны Docker / `docker compose`), визуальные эталоны (только Windows), `dev_stack.py --demo` и `seed_demo.py` (память машины). Полного `pytest -q` одной командой не было: те же пакеты пройдены по частям.

### Итоговый вывод системы

Стенд `tests/web/knowledge_stack.py` поднят в процессе (`max_stale=0`): шлюз, библиотека, сервис знаний, граф с `FakeProvider`. Браузер — Chromium, как в наборе тестов. Данные: эпохи «Научная революция» и «Просвещение»; четыре события сценария и Лондон; «Славная революция → Политическая философия Локка» (political, по источникам, абзац Учебника N); «Ньютон → учение Локка» (сгенерировано); «Пузырь → Два трактата» (economic, только абзац Учебника R, закрытого вне РФ); отклонённая «Энциклопедия → Критика религии». Скрипты и сырой вывод — в scratchpad судьи (`walk.py`, `walk2.py`).

| Требование | Сценарий / инвариант | Журнал тестировщика | Мой прогон | Вывод системы | Итог |
|---|---|---|---|---|---|
| Контекст эпохи | Контекст Просвещения | test_enlightenment_context passed; served epoch/4/1/0/false | passed | `GET /api/knowledge/v1/context?epoch=…&textbook=N` → 200; порядок 1687 Ньютон, 1688 Славная (political, Лондон wikidata null, basis dates, связь political/sourced/in_textbook true/evidence `[{p_…, /p/p_…}]`), 1720, 1751; counts — 4 вида по 1. Событие `knowledge.context.served` с тем же `request_id`: mode=epoch, events=4, links=3, generated_links=1 — в моих данных на 2 связи больше, чем в сценарии | подтверждено |
| Контекст эпохи | Окно времени | test_window passed | passed | `from=1700&to=1760` → Пузырь, Энциклопедия; epoch null; window {1700,1760}; basis null; served mode=window events=2 | подтверждено |
| Контекст эпохи | Фильтр видов | test_kinds_filter passed | passed | `kinds=political,economic` → Славная, Пузырь; counts те же, что без kinds; served events=2 | подтверждено |
| Контекст эпохи | Отклонённое не показывается | test_rejected_not_shown passed | passed | у Энциклопедии stimulated=[], id отклонённой связи в теле нет | подтверждено |
| Контекст эпохи | Усечение; без вызова модели | test_truncation, test_no_model_calls passed | passed | на стенде `llm_calls=[]`, `router.unexpected=[]` | подтверждено (усечение — только тестом) |
| Проверка параметров | Границы параметров (7 случаев) | test_parameter_bounds[7] passed | passed | 400 и kind/reason по таблице: mode, mode, window, window, window, unknown_epoch, unknown_kind. На каждый запрос ровно одно `knowledge.context.rejected` с полями только `reason`/`request_id`/`service`, `served` нет, «17x0» и «culinary» в журнал не попали | подтверждено |
| Пометка непроверенного | Сгенерированная связь помечена | passed (API и страница) | passed | API: generated=true, status generated. Страница: строка «→ Политическая философия Локка · механизм не указан · не проверено», `data-unverified="true"` у 1 строки; served generated_links=1 | подтверждено |
| Пометка непроверенного | Только проверенные | test_verified_only passed | passed | `verified=true` → статусы только sourced, у Ньютона stimulated=[], событие осталось; served generated_links=0 | подтверждено |
| Механизм влияния | вне списка / не указан | passed | passed | карточка и блок: «механизм не указан» при qualifiers {}; после достройки в базе qualifiers {} (механизм модели `political` отброшен) | подтверждено |
| Контекст из текста | 3 сценария | test_filling passed | 30 passed | только тесты на фейковой модели (извлечение на стенде не запускалось) | подтверждено тестами |
| Контекстные события из Wikidata | Кандидаты, принятый, ожидающий/отклонённый, повтор, dry-run, повторный harvest | test_epoch_context_import 16 passed | 16 passed | CLI `main([...], fetch=FixtureFetch())` на SQLite. `harvest` → кандидаты Q910011 (political, место Q910021) и Q910012 (kind null), без даты нет; событие harvested epochs=1 candidates=2; строки таблиц не менялись. `apply --dry-run` → строки не менялись; run dry_run created=1 statements=4 places_created=1 skipped=1. `apply` → +2 сущности, +4 утверждения (dating, event_kind, belongs_to_epoch, happened_in — все sourced); checked created/rejected. Повторный `apply` → exists, run 0/0/0, строки равны. Повторный `harvest` → решения accepted/rejected на месте, без задвоения. `stimulated` 0. Запросы только к wikidata.org через фикстуру | подтверждено |
| Достройка контекста моделью | Достроить контекст | test_extend_context passed | passed | клик «Достроить контекст» у Славной → строка «Два трактата о правлении · механизм не указан · не проверено (сохраняется)». По request_id потока: `graph.built` extension=pending, `graph.proposal_dropped` influenced_by/outside_recipe, `graph.extended` recipe=context proposed=1 dropped=1. Очередь — 1 задание, `graph.saved` statements=1; в базе status generated, qualifiers {}. После перезагрузки строка помечена, served generated_links=2 | подтверждено |
| Достройка контекста моделью | Связей достаточно / Уже достраивали / выключено / scope | passed (сервис и браузер) | passed | повторный клик: модель не вызвана (calls 1→1). В блоке «Связей достаточно, достройка не нужна.» (снимок), `graph.built` extension=not_needed — у события стало 5 связей семейства, поэтому порог сработал раньше однократности. «Уже достраивали», «выключено» и scope — только тестами | подтверждено |
| Контекст на странице эпохи | Блок, фильтр групп, закрытый источник, XSS, пусто | passed (test_epochs 43) | 43 passed | Блок под описанием эпохи: группы Политика/Экономика/Наука/Идеи со счётчиками, «1688 Славная революция · Лондон», строка «Политическая философия Локка · политический · по источникам · ¶», «связей пока нет» у Энциклопедии. «Наука» → адрес `?kinds=scientific`, 1 событие, served events=1. Закрытый источник: строка Пузыря «по источникам» без ¶ и без «Учебник R», в теле ответа нет id абзаца; прямой запрос к сервису с `X-Philograph-Region: RU` отдаёт evidence и атрибуцию «Учебник R», с DE — `[]`. Цитат в теле нет. pageerror 0 | подтверждено |
| Контекст и закрытые источники | Цитат нет никогда | test_no_quotes_ever passed | passed | тело ответа без текста абзацев ни в одном регионе | подтверждено |
| Виды событий (ontology-registry) | Экономическое в существующей базе | passed | passed | economic принят и показан в блоке группой «Экономика» | подтверждено |
| Разделы карточки (entity-cards) | Исторический контекст учения | test_doctrine_historical_context passed | passed | `GET …/entities/<учение>/card` → разделы ровно `context` «Исторический контекст»; строки по порядку: Славная (political, sourced), Ньютон (qualifiers {}, generated=true); `knowledge.card.served` type=doctrine sections=1 rows=2 | подтверждено |
| Выбор на карте (knowledge-graph) | Событие и то, что оно стимулировало; вне карты | test_map 51 passed, knowledge/test_map 16 | passed | `/graph/<Французская революция>`: `stimulated=[{basis,false},{marx,true}]`; data-related=true у Фихте, Маркса (вне окна) и «Основы…»; `.map-thread` 0; `knowledge.map.built` по request_id. В `/v1/map` первого стенда у Славной и Ньютона `stimulated` нет (объект — учение, не на карте), у Пузыря `[{Два трактата,false}]`. Цвета при ≥7 современниках и «только проверенные» — только тестами | подтверждено |
| Разделы в разработке (visual-design) | Старая закладка эпох / без метки | passed | passed | подпись в навигации «Эпохи и контекст», ведёт на /epochs | подтверждено |

### Сверка с журналом тестировщика

Числа passed по всем файлам совпали с последним прогоном тестировщика. События и поля на стенде совпали с журналом. Необъяснённых расхождений нет. Мелочь: в первой таблице журнала (строка `test_map_event_stimulated_api`) ещё упомянут «Шеллинг». Сценарий потом переписан на Маркса (решение ведущего по Д2 в progress.md), тест уже проверяет Маркса. Это устаревшая подпись в журнале, а не расхождение.

Полный pytest: по частям, все пакеты, кроме `e2e` и `ops`, зелёные, 0 failed (1 прежний skip). Прослеживаемость: 387 из 387.

Мутации (повторены судьёй, код возвращён `git checkout`, `git diff` по `src` пуст):
- (б) в `context.py` `verified` не фильтрует (`links = list(record.links)`) → 3 failed: `test_verified_only`, `test_verified_drops_generated_keeps_events[true,1]` — как в журнале;
- (г) в `_link` подтверждения закрытого источника не снимаются → 9 failed: `test_closed_source_stripped[epoch|window|textbook × None|DE|US]` — как в журнале.

Подгонка: не найдена. Изменения прежних тестов — только усиление (`exact=True`) по дельте visual-design. `skip`/`xfail`/пауз в новых тестах нет. Стенд подменяет только модель (`FakeProvider` за настоящим шлюзом) и сеть. Правки спецификации после реализации записаны в progress.md как решения ведущего: уточнение требования карты (Д1), смена сценария на Маркса (Д2), поле `events[].wikidata`, `duplicate_qid`.

Задачи: 1.1–7.1 сделаны (проверено по коду и прогону). 7.2 — выполнено этим прогоном; ruff по трём файлам Lead'а — прежний долг базы. 7.3 — ревью круга 2 в progress.md. 7.5 — после вердикта.

Не проверено судьёй: e2e и Docker, `tests/ops`, визуальные эталоны, демо-стенд `dev_stack --demo` с `seed_demo`; на стенде не проверялись сообщения `limit`/`visitor_limit`/`unavailable` в блоке. Это совпадает с «Не прогонялось» тестировщика; закрывается CI.

Вердикт: **принято**.
