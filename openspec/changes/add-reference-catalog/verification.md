# Verification — add-reference-catalog

## Тестировщик — 2026-11-25, тесты на коммите da2b293 (код продукта — ad07aeb, не менялся)

Тесты написаны по дельтам `specs/{entity-catalog,epochs,abuse-protection,visual-design}`. Файлы:
- `tests/knowledge/test_catalog.py` (сервис, HTTP `/v1/catalog` через `CatalogService` в `tests/knowledge/conftest.py`);
- `tests/knowledge/test_epochs_membership.py`;
- `tests/gateway/test_reference_limits.py`;
- `tests/web/test_reference.py` (стенд 4.0 `tests/web/knowledge_stack.py`);
- построитель данных `tests/knowledge/world.py`, транспорт `HostRouter` в `tests/helpers.py`.

Всего 218 тестов вместе с параметризацией, из них 4 падают (дефект Д1).

Журнал в тестах: события из фикстуры `events`, отобранные по `request_id`. В сервисных тестах `request_id` задаёт тест заголовком `X-Request-Id`. В браузерных он берётся из заголовка `x-request-id` ответа, который получила страница (`page.expect_response`).

Сырой пример события (браузер, `/reference` без фильтров):
`knowledge.catalog.listed {'request_id': '6d95466ac3df4260af00004742e6647a', 'service': 'knowledge', 'total': 5, 'returned': 5, 'page': 1, 'filters': [], 'q_len': 0, 'sort': 'label', 'snapshot': 'fresh', 'textbook_closed': False}`

### entity-catalog — сервис (`tests/knowledge/test_catalog.py`)

| Требование | Сценарий / инвариант | Тест | Вывод | Журнал (по request_id) |
|---|---|---|---|---|
| Список справочника | Справочник без фильтров | test_list_without_filters | 5 записей, нет «Учебника N»; Кант `dates={"from":1724,"to":1804,"precision":"year","original":"1724–1804"}`, `epochs=[{Просвещение, basis=dates}]` | listed total=5 returned=5 page=1 filters=[] q_len=0 sort=label textbook_closed=false |
| Список справочника | Слитый дубль | test_merged_duplicate_hidden | один Кант, id дубля нет ни в записях, ни в эпохах; total = строки без source − 1 | listed total = то же |
| Список справочника | Сгенерированное описание помечено | test_generated_summary_marked | Причинность generated=true, Кант false | listed total=5 |
| Список справочника | Справочник без модели | test_catalog_without_model | 200, 5 записей; вызовов поддельного llm (503) — 0 | нет `llm.*` с этим request_id, есть listed |
| Список справочника | В журнале нет текста | test_no_query_text_in_journal | `q=чаадаев` → «Пётр Чаадаев» | в 3 событиях `knowledge.catalog.*` нет «чаадаев», «Чаадаев», «<script>», адреса 203.0.113.77; q_len=7 |
| Список справочника | inv: события только id, коды и числа | test_journal_has_only_ids_codes_numbers | враждебные q, регионы RU/DE, пересборки | все поля catalog.* и snapshot.built: bool/int/float или строка из перечня кодов; нет q, названий из таблицы names, адреса, региона |
| Список справочника | inv: filters — отсортированный список имён | test_filters_sorted_names | — | filters=["epoch","q","textbook","type"] |
| Список справочника | inv: не вызывает модель | test_catalog_never_calls_model | 9 разных запросов, в том числе отказы | llm_calls=[], нет `llm.*`; ровно одно listed или rejected на запрос |
| Поиск по названию | Часть названия | test_search_part_of_name, test_search_word_start_ordered_by_weight | total=3: [Георг Кантор, Иммануил Кант (равная значимость → по названию), Американский прагматизм]; с весом у Канта Кант первым | filters=["q"] q_len=3 sort=relevance |
| Поиск по названию | Точное совпадение первым | test_exact_match_first | q=кант → [Кант(1), Кантор(50)]; при sort=weight — Кантор первым | q_len=4 |
| Поиск по названию | Вариант названия | test_variant_name_match | matched_name="Kant", label="Иммануил Кант"; при совпадении основного — null | filters=["q"] |
| Поиск по названию | Ё и регистр | test_yo_and_case | q=ПЕТР → total=1 «Пётр Чаадаев» | q_len=4 |
| Поиск по названию | inv: пустая или пробельная строка — без поиска | test_blank_query_means_no_search[3] | total=5, sort=label | filters=[] q_len=0 |
| Фильтры справочника | Тип с подтипом | test_type_includes_subtypes | total=2 (событие и идейное), без Канта | filters=["type"] |
| Фильтры справочника | Несколько типов | test_several_types | total=3 | filters=["type"] |
| Фильтры справочника | Эпоха и тип | test_epoch_and_type | Юм, Кант, без Декарта | filters=["epoch","type"] |
| Фильтры справочника | Раздел через упоминание | test_textbook_by_mention | Кант есть, Беркли нет | filters=["textbook"] |
| Фильтры справочника | Раздел через подтверждение абзацем | test_textbook_by_evidence | ровно Локк и «врождённые идеи» | filters=["textbook"] total=2 |
| Фильтры справочника | inv: регион нужен только разделу | test_region_only_for_textbook | без textbook — 0 обращений к `/internal/access`, с textbook — одно с region=DE | filters=["textbook"] |
| Проверка параметров | Границы параметров | test_parameter_bounds[16] | q200 → 200 total=0; q201 → 400 bad_query; limit60 → 200; limit61/0/abc → 400 bad_query; page0/x → 400 bad_query; page99 → items=[] total=5, facets как у page=1; sort=rank → 400 bad_query; relevance без q → sort=label; dragon → unknown_type; epoch=<Кант> и несуществующий → unknown_epoch; s_unknown → unknown_textbook | у отказа ровно одно rejected с reason из таблицы и нет listed; у 200 — listed, нет rejected |
| Проверка параметров | inv: эпоха после перенаправления | test_epoch_after_redirect | id слитой эпохи → Юм, Кант | filters=["epoch","type"] |
| Счётчики | Счётчики при поиске | test_facets_with_search | total=2, types={"work":2,"group":1} | total=2 |
| Счётчики | Сумма счётчиков | test_facets_sum | {"person":2,"concept":1,"work":1,"epoch":1} = 5 | total=5 |
| Счётчики | Счётчики эпох | test_epoch_facets | [{Научная революция,1},{Просвещение,2}] | filters=["epoch","type"] |
| Счётчики | inv: эпохи без даты в конце, по названию | test_epoch_facets_order_undated_last | [НР, Просв., Античность, Барокко] | filters=["type"] |
| Счётчики | inv: сумма types = total без фильтра типа | test_facets_sum_invariant (seed 20261125, 7 запросов) | равенство, нет нулей и `source` | listed.total = total |
| Счётчики | inv: слитые и источники не в списке и не в счётчиках | test_merged_and_sources_never_counted (7 запросов) | нет id дубля, `source`, «Учебник N/R» | listed.total = total |
| Постраничная выдача | Вторая страница | test_second_page | 24 + 6, без пересечения, total=30 | returned=24 page=1; returned=6 page=2 |
| Постраничная выдача | inv: по умолчанию 24 | test_default_page_size | limit=24 | returned=24 |
| Постраничная выдача | Без даты в конце | test_sort_by_date_undated_last | Просвещение, Юм, Кант, КЧР, Причинность | sort=date |
| Постраничная выдача | inv: порядок устойчив, страницы не пересекаются | test_stable_order_and_disjoint_pages[27: seed 1/7/42 × label/date/weight × limit 5/7/24] | склейка страниц = одна страница limit=60, без повторов, ключ монотонен | returned и page каждой страницы |
| Постраничная выдача | inv: при равенстве ключа — по идентификатору | test_ties_broken_by_id[6] | **label — проходит; date, weight — ПАДАЮТ (Д1)** | — |
| Прежний поиск | Точный поиск не изменился | test_exact_name_lookup_unchanged | список из одного «Кант», ключи ровно id,type,primary,names | нет listed; http.request.completed route=/v1/entities |
| Закрытые источники | Учебник закрыт для региона | test_closed_textbook | DE: items=[], total=0, facets пусты, textbook_closed=true; RU (контроль): Кант | textbook_closed=true / false |
| Закрытые источники | Сущность видна вне РФ | test_entity_visible_outside_ru | Кант найден | textbook_closed=false |
| Закрытые источники | Текст абзаца не попадает в ответ | test_paragraph_text_not_in_body[None/DE/RU] | 4 запроса: в теле нет фразы и «a priori» | listed на каждый |
| Закрытые источники | inv: закрытый учебник пуст при любых фильтрах | test_closed_textbook_empty_for_any_filters[24 = 8 наборов × 3 региона] | пусто, textbook_closed=true | textbook_closed=true total=0 |
| Свежесть | Снимок переиспользуется | test_snapshot_reused | ответы равны | built ×1 reason=first; snapshot fresh, затем cached |
| Свежесть | Внутри окна и после | test_stale_window (ManualClock) | t+5 total=0; t+16 total=1 | stale; потом fresh и built reason=changed с тем же request_id |
| Свежесть | Карта без окна | test_map_without_window | новое утверждение в `links` карты | built reason=changed и knowledge.map.built с request_id карты |
| Свежесть | inv: таблица fresh/cached/stale | test_snapshot_status_table[5: 0, 100 без изменений; 14.9, 15.0, 15.1 с изменением] | — | cached, cached, stale, fresh, fresh; built только при fresh |
| Свежесть | inv: изменения видны после окна | test_changes_visible_after_window[entity/name/statement/merge/reject] | новая сущность, вариант «Hume», значимость +1, слияние, отклонённое явное → epochs=[] | snapshot=fresh |
| Свежесть | inv: поля события пересборки | test_snapshot_built_fields | — | entities≥5, statements = строки таблицы, took_ms≥0 |

### epochs — «Принадлежность к эпохе» (`tests/knowledge/test_epochs_membership.py`)

Принадлежность читается из поля `epochs` записи и фильтра `epoch` справочника, пролёт эпохи — из `eras` ответа `/v1/map`. В каждом тесте проверяется `knowledge.catalog.listed` запроса.

| Сценарий / инвариант | Тест | Вывод |
|---|---|---|
| По середине жизни | test_middle_of_life | Локк: [(НР, dates)], не в Просвещении |
| Явное важнее дат | test_explicit_over_dates | Локк: [(Просв., explicit)], не в НР |
| Отклонённое и отвергнутое явное не действует | test_rejected_and_deprecated_explicit | Локк → НР dates; Беркли → Просв. dates |
| inv: отвергнутое к другой эпохе не перекрывает даты | test_deprecated_to_other_epoch_ignored | Беркли → Просв. dates |
| Пересекающиеся эпохи | test_overlapping_epochs | 1685 → обе, dates |
| Конец эпохи не включается | test_epoch_end_excluded | 1687 → только Просв. |
| inv: [начало, конец) | test_half_open_span[32 = 8 лет × event/idea_event/work/phenomenon] | 1542 ∅, 1543 НР, 1680 обе, 1687 Просв., 1800 ∅ |
| inv: середина жизни без округления | test_person_middle_of_life_unrounded[6] | 1679,5 → только НР; 1799,5 → Просв.; 1800,5 → ∅ |
| Округление нечёткой границы | test_fuzzy_boundary_rounding | событие 1679 не в эпохе; `eras[].from=1680` в `/v1/map`; knowledge.map.built |
| Без датировки и группы | test_undated_and_groups | аноним, группа, понятие, Барокко — []; у Барокко нет участников; труд 1690 → Просв. |
| inv: идеи и группы только по явному | test_ideas_and_groups_only_explicit[6] | [] до явного; после — [(НР, explicit)] |
| inv: эпоха не относится к себе | test_epoch_not_member_of_itself | — |
| inv: несколько явных | test_several_explicit | две эпохи explicit |
| Вывод не хранится | test_derived_not_stored | число `belongs_to_epoch` не изменилось; нет `knowledge.statement.created` |

### abuse-protection (`tests/gateway/test_reference_limits.py`; настоящий шлюз + настоящий сервис знаний)

| Сценарий / инвариант | Тест | Вывод | Журнал |
|---|---|---|---|
| Справочник при исчерпанном лимите | test_catalog_when_paid_limits_exhausted | вопросы и достройка исчерпаны; без cookie токена `q=кант` → 200 [Иммануил Кант] | нет gateway.limit.triggered с request_id запроса; listed q_len=4 |
| Справочник не тратит квоту | test_catalog_does_not_spend_quota | 10 × 200; вопросы: done, done, visitor_limit | ровно одно gateway.limit.triggered, operation=ask; 10 listed |
| inv: только общий лимит частоты | test_catalog_only_rate_limited | burst 3 → [200,200,200,429,429]; через 1 с снова 200 | 2 × kind=rate без operation; нет page_token |
| inv: без токена и платных лимитов | test_catalog_never_paid[5] | при квотах 0 — 200 или 400, не page_token и не rate_limited | нет limit.triggered; listed или rejected |

Сценарий «Лимит исчерпан» (глава и карточка) уже покрыт прежним `tests/gateway/test_limits.py::test_free_operations_after_limit`.

### entity-catalog — страница и visual-design (`tests/web/test_reference.py`, Chromium)

| Требование | Сценарий / инвариант | Тест | DOM | Журнал (request_id ответа страницы) |
|---|---|---|---|---|
| Страница | Найти и открыть | test_find_and_open | 5 → 1 запись «Дэвид Юм», адрес `/reference?q=юм`, в `aside#side-panel` «Дэвид Юм» | listed filters=["q"] q_len=2; card.served entity_id=Юм |
| Страница | Группа и эпоха из адреса | test_group_and_epoch_from_address | «Персоны» aria-pressed=true, счётчик 2; выбор эпохи — «Просвещение»; Юм и Кант | filters=["epoch","type"] |
| Страница | Показать ещё | test_show_more | 24 → 30 разных записей, кнопки нет, фокус на 25-й («Понятие 24») | listed page=2 |
| Страница | Задержка ввода | test_input_debounce (page.clock: 100+100+250 мс) | ушёл один запрос `q=кан`; 2 записи | одно listed с q_len>0, и у него q_len=3 |
| Страница | Устаревший ответ | test_stale_response_discarded (page.clock + удержанный page.route) | показан «кан», адрес `?q=кан`; после развязки «ка» список не изменился | listed q_len=3 |
| Страница | На карте | test_on_the_map | `/graph/<Кант>`, `.map-selected` содержит «Иммануил Кант» | knowledge.map.built |
| Страница | Пометка сгенерированного | test_generated_mark | у «Причинности» `[data-generated=true]` с подписью «Сгенерировано», у Канта пометки нет | listed total=5 |
| Страница | inv: состояние в адресе восстанавливается | test_state_round_trip_through_address | q, group, epoch, textbook, sort из адреса; смена сортировки попадает в адрес, «Назад» возвращает прежнюю | filters=["epoch","q","textbook","type"] sort=date |
| Состояния | Ничего не найдено | test_nothing_found | «Ничего не найдено по запросу «зззз».», «Сбросить фильтры» → `/reference` и 5 записей | total=0, затем filters=[] |
| Состояния | Сервис недоступен | test_service_unavailable (page.route 503) | «Справочник временно недоступен.», «Повторить»; поиск вводится, пункт панели виден и переходит; после «Повторить» — список | до сервиса не дошло ни одного listed; после повтора listed q_len=4 |
| Состояния | inv: при ошибке показанные записи остаются | test_error_keeps_shown_records | 5 записей остались под сообщением | одно listed (первое) |
| Состояния | Пустая онтология | test_empty_ontology | «Справочник пока пуст…», 0 записей, нет `.reference__count` | total=0 |
| Состояния | Учебник закрыт | test_closed_textbook | «Этот учебник недоступен в вашем регионе.», «Все источники» → 5 записей | textbook_closed=true, затем false |
| Состояния | inv: загрузка | test_loading_state | заполнители, aria-busy=true, поиск доступен | listed после ответа |
| Безопасный вывод | Разметка в названии и запросе | test_markup_in_name_and_query | название и значение поиска буквальны (`<img`), нет `img` в списке, `window.__xss` не определён, эпохи нет в адресе | rejected reason=unknown_epoch (400), затем listed filters=["q"] |
| Безопасный вывод | inv: id из адреса — текст | test_hostile_address_parameters[4] | нет img/script/svg/b, `__xss` не определён | на каждый ответ ровно одно listed или rejected |
| Безопасный вывод | inv: любая ошибка без pageerror и console.error | test_any_load_failure_handled[abort/html/500] | сообщение об ошибке и «Повторить» | listed нет (запросы подменены) |
| Клавиатура | Клавиатура | test_keyboard | «/» → фокус в поиске; ↓ → «Иммануил Кант»; Enter → карточка | card.served entity_id=Кант |
| Клавиатура | inv: стрелки, «/» в поле, Esc | test_keyboard_navigation_rules | ↓↓↑ по записям; «а/б» вводится как текст; Esc очищает поиск | q_len=3, затем 0 |
| Клавиатура | inv: роли | test_accessibility_roles | role=group с подписью, 9 кнопок с aria-pressed; ul с aria-label; aria-live=polite «Найдено: 5» | total=5 |
| Клавиатура | Малое окно | test_layout_fits_window[1024×576, 1920×1080] | поиск, ряд групп и первая запись в окне, прямоугольники не пересекаются, scrollWidth ≤ innerWidth, scrollY=0 | total=35 |
| visual-design | Ассистент без метки | test_live_items_without_soon | у «Ассистент», «Граф», «Справочник» нет «скоро», href /assistant, /graph, /reference | listed |
| visual-design | Пункт-заглушка | test_future_items_keep_soon | у 5 будущих пунктов «скоро» | listed |
| visual-design | Старая закладка справочника | test_old_reference_bookmark | `/soon/reference` → `/reference`, history.length +1 (только переход), «Назад» → `/` | listed total=5 |

Каждый браузерный тест проверяет ещё и то, что фикстура стенда завершилась без запросов наружу, без вызовов модели и без `pageerror`/`console.error`.

### Интерфейсные THEN без серверного события и их якорь

| THEN | Тест | Серверный якорь |
|---|---|---|
| адрес `/reference?q=…`, `?q=кан`, `/reference` после сброса, адрес состояния | test_find_and_open, test_stale_response_discarded, test_nothing_found, test_state_round_trip_through_address | listed запроса страницы |
| фокус: строка поиска, первая запись, 25-я запись, стрелки | test_keyboard, test_keyboard_navigation_rules, test_show_more | listed (и card.served для Enter) |
| открыта карточка справа | test_find_and_open, test_keyboard | knowledge.card.served |
| aria-pressed, aria-live, aria-busy, подписи | test_group_and_epoch_from_address, test_accessibility_roles, test_loading_state | listed |
| раскладка 1024×576 и 1920×1080 | test_layout_fits_window | listed |
| замена `/soon/reference` без записи в истории | test_old_reference_bookmark | listed запроса страницы |
| сообщение «Справочник временно недоступен.» (ответ подменён `page.route`) | test_service_unavailable, test_any_load_failure_handled | события нет — запрос до сервиса не дошёл; якорь — listed после «Повторить» |
| буквальный вывод, отсутствие `img`, `window.__xss` | test_markup_in_name_and_query | rejected unknown_epoch и listed |

### Команды и итоги

    pytest -q tests/knowledge                     →  4 failed, 409 passed, 1 skipped in 282.84s
        FAILED test_catalog.py::test_ties_broken_by_id[date-1|date-7|weight-1|weight-7]
    pytest -q tests/gateway tests/web/test_reference.py  →  71 passed in 84.21s
    pytest -q tests/knowledge/test_map.py tests/knowledge/test_map_view.py  →  19 passed in 18.11s
        (git diff origin/claude/embedding-docker по обоим файлам пуст — 4.6)
    pytest -q tests/web/test_map.py::test_soon_graph_bookmark_leads_to_map tests/web/test_assistant_page.py::test_t43_nav_item_current_without_soon (+ test_reference.py)  →  32 passed
    ruff check .                                  →  1 ошибка: scripts/dev_stack.py:100 E501 (файл Lead'а, база)
    ruff format --check .                         →  3 files would be reformatted: scripts/dev_stack.py, src/philograph/platform/queue.py, src/philograph/prompts/__init__.py (файлы Lead'а, база); tests/ — чисто
    ruff check tests/                             →  All checks passed!
    lint-imports                                  →  Contracts: 3 kept, 0 broken.
    python scripts/check_traceability.py          →  Требований с тестами: 369 из 369 (entity-catalog в enforce, 5.1)
    cd web && npm run build                       →  ✓ built in 4.21s

### Дефекты

- **Д1. «Постраничная выдача»: при равном ключе порядок по идентификатору.** Спецификация: «при равенстве ключа сортировки — по идентификатору». При `sort=date` и `sort=weight` записи с равным ключом идут по названию, затем по id (`catalog.py`, `keys["date"]` и `keys["weight"]` вставляют `sort_label` перед `id`). Падающий тест: `test_ties_broken_by_id[date-*]`, `[weight-*]`; пример: `date`, обе записи 1700 года — «Бета Один» (`e_f47f…`) перед «Гамма Два» (`e_2127…`). Устойчивость и непересечение страниц от этого не страдают (`test_stable_order_and_disjoint_pages` зелёный). Решить: либо поправить код, либо записать в спецификацию вторичный ключ «по названию» для `date`/`weight`, как он уже записан для `relevance`.
- **Замечание (не падает).** Пометка сгенерированного подписана «Сгенерировано» (общий `StatusMark`, тот же, что в карточке). Спецификация цитирует «сгенерировано» строчными. Тест сравнивает подпись без учёта регистра.

### Мутации (4.7): сломал → упало; код возвращён `git checkout`, `git diff -- src web/src` пуст

    (а) epochs.py: явное не прерывает расчёт по датам        → 8 failed: test_explicit_over_dates, test_ideas_and_groups_only_explicit[*]…
    (б) epochs.py: start <= mid <= end                        → 10 failed: test_epoch_end_excluded, test_half_open_span[*-1687|1800]…
    (в) catalog.py: source не исключается                     → 3 failed: test_list_without_filters, test_merged_and_sources_never_counted, test_facets_sum
    (г) catalog.py: поле q в каталоге событий и в listed      → 2 failed: test_no_query_text_in_journal ('чаадаев' в событии), test_journal_has_only_ids_codes_numbers
    (д) catalog.py: счётчик types с фильтром типа             → 1 failed: test_facets_with_search
    (е) catalog.py: is_closed = False                         → 25 failed: test_closed_textbook, test_closed_textbook_empty_for_any_filters[*]
    (ж) catalog.py: id убран из ключа label                   → test_ties_broken_by_id[label-1], [label-7] упали (date/weight падают и без мутации — Д1)
    (з) catalog.py: get() без max_stale                       → 2 failed: test_stale_window, test_snapshot_status_table[14.9-True-stale]
    (и) catalog.py: начало слова ранг 2, вхождение — 1        → 2 failed: test_search_part_of_name, test_search_word_start_ordered_by_weight
    (к) ReferencePage.tsx: DEBOUNCE_MS = 0 (+ npm run build)   → test_input_debounce: [['к'], ['ка'], ['кан']] != [['кан']]; после возврата web/dist пересобран
    (л) catalog.py: snapshot="fresh" всегда                    → 2 failed: test_snapshot_reused, test_stale_window
    (м) dates.py: round убран из span                          → 1 failed: test_fuzzy_boundary_rounding (eras.from 1679.5)
    (н) epochs.py: группа получает эпохи участников (member_of) → 2 failed: test_undated_and_groups, test_ideas_and_groups_only_explicit[group]

### Замер 4.8 (скрипт в scratchpad, не тест; SQLite в памяти, 1 CPU, `random.Random(10)`)

    данные: сущностей 7000, названий 20976, утверждений 3998; наполнение 17.4 с
    первый запрос (снимок + индекс + эпохи): 555 мс; snapshot.built took_ms=339.3 entities=7000 statements=3998
    без поиска, снимок cached, мс: [18.6, 14.3, 25.6, 18.9, 12.5]
    поиск q='ка', мс: [23.1, 23.5, 22.5, 25.2, 26.7] total 6026
    поиск q='кант', мс: [9.3, 12.1, 11.3, 11.1, 11.8] total 222
    поиск q='линг', мс: [21.9, 18.0, 16.3, 16.7, 23.6] total 4335
    поиск q='зззз', мс: [8.5, 10.7, 18.5, 19.4, 16.8] total 0
    поиск+тип+эпоха+date, мс: [18.3, 17.5, 19.1, 18.6, 22.8]
    пересборка (changed) + индекс + запрос под tracemalloc: 2472 мс; took_ms=1675.7 reason=changed
    tracemalloc при двух снимках (старый удержан): прирост пика 36.8 МиБ, после 36.1 МиБ
    ru_maxrss процесса: 187 МиБ

Пересборка под `tracemalloc` медленнее, чем без него: 1675 мс против 339 мс у первой сборки, это накладные расходы трассировки.

### Исключения из проверки журнала

- Сообщения об ошибке при подменённом 503 и обрыве (test_service_unavailable, test_any_load_failure_handled): запрос до сервиса не доходит, поэтому серверного события нет. Проверяется, что `listed` нет.
- test_stale_response_discarded: страница сама отменяет устаревший запрос (`net::ERR_ABORTED`), поэтому поздний ответ на «ка» до страницы физически не доходит. Отбрасывание по номеру запроса браузером отдельно не изолируется — защита сейчас держится на `AbortController`.

### Не прогонялось на машине агента

- `tests/e2e`. Это касается и обновлённого `tests/e2e/test_visual_design.py::test_future_sections_marked_and_described`: «Справочник» перенесён из «скоро» в реализованные. Тесты не запускались — 1 ГБ RAM.
- Визуальные снимки win32.
- Полный `pytest -q` и `tests/web` целиком: прогнаны только `test_reference.py` и два теста навигации.
- Это остаётся за CI и Lead.

### Повторный прогон после исправлений — 2026-11-25, код 24b4147 (Д1 — f1812e7, ревью 1 — 24b4147)

Мои прежние тесты не менялись. Добавлен один сценарный тест по замечанию ревью (смена снимка между страницами):

| Требование | Сценарий | Тест | DOM | Журнал |
|---|---|---|---|---|
| Страница справочника | Показать ещё | tests/web/test_reference.py::test_show_more_after_snapshot_change (стенд с `max_stale=0`) | 50 понятий → 24; в базу добавлено «Аарон понятие» (по названию первое); щелчок → 47 записей (старая 24-я пришла повтором и убрана), кнопка видна; щелчок → 50 разных записей «Понятие 00…49», кнопки нет | listed page=2 returned=24 total=51 snapshot=fresh; затем listed page=3 returned=3 total=51 |

Для этого теста стенд `knowledge_stack` получил параметр `max_stale` (косвенная параметризация), по умолчанию 15.

Команды и итоги:

    cd tests/knowledge && pytest -q test_catalog.py test_epochs_membership.py test_catalog_unit.py test_catalog_route.py test_snapshot.py test_epochs_unit.py test_dates_span.py test_map_snapshot_parity.py test_reference_groups.py test_map.py test_map_view.py
        →  262 passed in 191.98s   (test_ties_broken_by_id[date-*|weight-*] теперь зелёные — Д1 исправлен)
    pytest -q tests/gateway/test_reference_limits.py tests/web/test_reference.py tests/web/test_reference_paging.py tests/web/test_map.py::test_soon_graph_bookmark_leads_to_map tests/web/test_assistant_page.py::test_t43_nav_item_current_without_soon
        →  42 passed in 83.12s
    python scripts/check_traceability.py  →  Требований с тестами: 369 из 369
    ruff check tests                      →  All checks passed!
    lint-imports                          →  Contracts: 3 kept, 0 broken.

Мутация:

    ReferencePage.tsx: onClick → load(Math.floor(items.length / paging.limit) + 1 + 0 * nextPage(paging)), npm run build
        →  1 failed: test_show_more_after_snapshot_change (ждали ответ page=3, ушёл повторный page=2: Page.expect_response Timeout)
    код возвращён `git checkout`, `git diff -- src web/src` пуст, web/dist пересобран.
    Первая попытка без `0 * nextPage(...)` не собралась (TS6133, неиспользуемый импорт): dist не изменился, тест прошёл. Эта попытка не засчитана.

Не прогонялось: e2e (в том числе обновлённый тест навигации tests/e2e/test_visual_design.py), визуальные снимки win32, полный pytest.

## Судья — 2026-11-25, коммит f384b02

Код продукта на f384b02 совпадает с тем, на котором тестировщик делал повторный прогон (24b4147): после него менялись только `tests/web` (66e7796, тест тестировщика) и `progress.md`. Мои прогоны — последовательно на машине 1 ГБ RAM, 1 CPU, без Docker.

### Полнота

- `tasks.md`: 1.1–5.1 отмечены и сделаны (проверено по диффу: `dates.span/middle`, `snapshot.py`, `epochs.py`, `catalog.py`, маршрут и сборка в `app.py`/`main.py`, `seed_demo.seed_reference`, `web/src/reference/*`, `App.tsx`, `Sidebar.tsx`, строки RU/EN, `traceability.yaml`). 5.2 выполнен этим прогоном; 5.3 — круги ревью в `progress.md`; 5.4 — этот раздел; 5.5 (архив) — после вердикта.
- Каждое требование и сценарий дельт `entity-catalog`, `epochs`, `abuse-protection`, `visual-design` есть в таблицах тестировщика, кроме неизменённых сценариев MODIFIED-требований: «Лимит исчерпан» — прежний `tests/gateway/test_limits.py` (прошёл), «Граф по сущности» — `tests/web/test_map.py::test_soon_graph_bookmark_leads_to_map` (прошёл), «Страница раздела» — `tests/e2e/test_visual_design.py` (e2e, здесь не запускался).
- Тела тестов прочитаны выборочно (`test_list_without_filters`, `test_merged_duplicate_hidden`, `test_generated_summary_marked`, `test_catalog_without_model`, `test_input_debounce`, `test_old_reference_bookmark`): проверяют каждое утверждение THEN и событие по `request_id`.

### Мой прогон

    git log -1                                → f384b02, рабочее дерево чистое
    cd web && npm run build                   → ✓ built in 4.87s
    ruff check .                              → 1 ошибка: scripts/dev_stack.py:100 E501
    ruff format --check .                     → 3 files would be reformatted: scripts/dev_stack.py, src/philograph/platform/queue.py, src/philograph/prompts/__init__.py
        все три файла в ветке не менялись; в базе origin/claude/embedding-docker проверены отдельно (git show … | ruff format --check -) — так же не проходят, E501 тоже есть в базе
    lint-imports                              → Contracts: 3 kept, 0 broken.
    python scripts/check_traceability.py      → Требований с тестами: 369 из 369
    pytest -q tests/knowledge                 → 415 passed, 1 skipped in 277.99s (skip — test_registry_entities.py:281, только PostgreSQL, файл вне диффа)
    pytest -q tests/gateway                   → 41 passed in 15.98s
    pytest -q tests/assistant tests/evaluation → 68 passed in 124.21s (используют statements/карту)
    pytest -q tests/web                       → 215 passed in 523.73s (весь пакет, включая test_reference.py, test_reference_paging.py и прежние тесты чтения, карты, навигации)

Расхождение с журналом тестировщика: в `tests/knowledge` у него 413 + 1 skip (первый прогон), у меня 415 + 1 skip. Объяснено: после первого прогона разработчик добавил два юнит-теста (24b4147: `test_label_cache_bounded_by_interface_languages`, сверка `attributed_sources`); 4 падения Д1 исправлены в f1812e7, тест тестировщика `test_ties_broken_by_id` не менялся.

Не запускались: `tests/library`, `tests/llm`, `tests/operator`, `tests/ops`, `tests/platform`, `tests/search` — дифф их кода не трогает, ни один из них не импортирует `philograph.knowledge` и `seed_demo` (grep пуст); `tests/e2e` и визуальные снимки win32 — нет Docker и памяти. Это остаётся за CI (`checks`).

### Итоговый вывод системы

Вместо `dev_stack.py` (файл базы, на машине не помещается) поднят стенд `tests/web/knowledge_stack.start`: настоящий шлюз (uvicorn), библиотека с учебниками N (открыт) и R (только РФ), сервис знаний на SQLite; данные — `World`: Кант (вариант «Kant», упомянут в N), Юм (упомянут в R), Кантор, Локк (явно «Просвещение»), «Научная революция», «Просвещение», «Причинность» (сгенерированное описание), 30 понятий. Скрипт — в scratchpad судьи, не в репозитории. Запросы через шлюз `/api/knowledge/v1/catalog` с `X-Request-Id`, события собраны по `request_id`:

| Запрос | Ответ | События по request_id |
|---|---|---|
| без фильтров | 200, total=38, 24 записи, нет «Учебника N/R», facets.types сумма 38 | snapshot.built reason=first entities=40; listed total=38 returned=24 page=1 filters=[] q_len=0 sort=label snapshot=fresh textbook_closed=False |
| `q=кан` | [Георг Кантор, Иммануил Кант] | listed filters=["q"] q_len=3 sort=relevance snapshot=cached |
| `q=kant` | Иммануил Кант, matched_name="Kant" | listed q_len=4 |
| `type=person&epoch=<Просвещение>` | Локк (explicit), Юм, Кант (dates); Локк не в «Научной революции», хотя середина жизни 1668 в ней | listed filters=["epoch","type"] |
| `textbook=<N>` | только Кант | `/v1/internal/access` с тем же request_id; listed filters=["textbook"] |
| `type=concept&page=2` | total=31, 7 записей «Понятие 24…29», «Причинность» | listed page=2 returned=7 |
| `sort=date&limit=5` | НР 1543, Локк, Просвещение 1680, Юм, Кант | listed sort=date |
| `limit=61` / `q` из 201 знака / `type=dragon` | 400 bad_query / bad_query / unknown_type | одно rejected reason=limit / query_too_long / unknown_type, listed нет |
| сервис знаний, `textbook=<R>`, регион DE / RU | items=[], facets пусты, textbook_closed=true / Юм | listed textbook_closed=True total=0 / False total=1 |
| `/v1/entities?name=Кант` | [] (точный поиск, «Иммануил Кант» не совпадает — прежний контракт) | только http.request.completed, listed нет |
| `/reference`, `/soon/reference` | 200, клиент | — |

Ни в одном событии нет текста запроса, названий или региона. Вызовов модели — 0, запросов наружу — 0. Страницу в браузере сам не проходил: браузерные сценарии подтверждены прогоном `tests/web` целиком (215 passed).

### Сверка по требованиям

| Требование | Сценарии / инварианты | Журнал тестировщика | Мой прогон | Вывод системы | Итог |
|---|---|---|---|---|---|
| Список справочника | 5 сценариев, 3 инварианта | test_list_without_filters … test_catalog_never_calls_model; listed total=5 filters=[] | passed (tests/knowledge) | список без источников, поля события те же, llm 0 | подтверждено |
| Поиск по названию | 4 сценария, пустая строка | test_search_part_of_name … test_blank_query_means_no_search | passed | `кан` → Кантор, Кант; `kant` → matched_name | подтверждено |
| Фильтры справочника | 5 сценариев, регион только для раздела | test_type_includes_subtypes … test_region_only_for_textbook | passed | epoch+type, textbook; access только при textbook | подтверждено |
| Проверка параметров | Границы параметров, эпоха после перенаправления | test_parameter_bounds[16], test_epoch_after_redirect | passed | 400 и одно rejected с reason по таблице | подтверждено |
| Счётчики | 3 сценария, 3 инварианта | test_facets_* , test_epoch_facets* | passed | сумма types = total без фильтра типа | подтверждено |
| Постраничная выдача | 2 сценария, 3 инварианта (Д1 исправлен) | test_second_page … test_ties_broken_by_id | passed | page=2 без пересечения, date по началу | подтверждено |
| Прежний поиск по названию | Точный поиск не изменился | test_exact_name_lookup_unchanged | passed | точный поиск, listed нет | подтверждено |
| Закрытые источники | 3 сценария, пусто при любых фильтрах | test_closed_textbook … [24] | passed | DE пусто, textbook_closed=True; RU — Юм | подтверждено |
| Свежесть справочника | 3 сценария, 3 инварианта | test_snapshot_* , test_stale_window (ManualClock) | passed | built first, затем cached | подтверждено |
| Страница справочника | 7 сценариев + «Показать ещё» при смене снимка, адрес | tests/web/test_reference.py | passed (tests/web 215) | `/reference` отдаётся шлюзом | подтверждено |
| Состояния / Безопасный вывод / Клавиатура | все сценарии и инварианты, 1024×576 и 1920×1080 | tests/web/test_reference.py | passed | — (браузер — только тестами) | подтверждено тестами; визуальные снимки — CI/Lead |
| epochs: Принадлежность к эпохе | 8 сценариев, 6 инвариантов | test_epochs_membership.py | passed | Локк explicit важнее дат | подтверждено |
| abuse-protection: Бесплатное без ограничений платных | 3 сценария, 2 инварианта | test_reference_limits.py, test_limits.py | passed (tests/gateway 41) | — | подтверждено |
| visual-design: Разделы в разработке | Пункт-заглушка, Ассистент без метки, Старая закладка, Граф по сущности | test_reference.py, test_map.py, test_assistant_page.py | passed | `/soon/reference` 200 | подтверждено; «Страница раздела» и обновлённый e2e-тест навигации — только CI |

### Мутации (свои)

    epochs.py:71  start <= mid < end → start <= mid <= end
        → 10 failed: test_epoch_end_excluded, test_half_open_span[*-1687|1800] (8), test_person_middle_of_life_unrounded[1660-1714]  (как в журнале — 10)
    catalog.py:465  is_closed = False
        → 25 failed в test_catalog.py -k closed (как в журнале — 25)
    код возвращён git checkout; git status пуст

### Подгонка

Не найдена. `git diff origin/claude/embedding-docker...HEAD -- tests openspec`: новых `skip`/`xfail` нет, кроме пропуска при несобранном клиенте и отсутствии node (условия окружения, тесты у меня выполнились); один `time.sleep(0.02)` — ожидание запуска сервера стенда, не проверка отсутствия. Тесты тестировщика после передачи не менял никто, кроме самого тестировщика (66e7796); разработчик правил только свой юнит-тест (f1812e7) в сторону спецификации. Дельты `specs/` не менялись после d35bd66/8348210 (до кода). Числа мутаций совпадают с журналом.

Полный pytest: не запускался целиком (ограничение машины); запущены все пакеты, которые дифф затрагивает или которые импортируют изменённый код, — зелёные. e2e и визуальные снимки — за CI.
Прослеживаемость: 369 из 369.
Вердикт: **принято** — при условии зелёного `checks` в CI (полный набор и e2e, включая обновлённый `tests/e2e/test_visual_design.py::test_future_sections_marked_and_described`); падение там — вернуть тестировщику и разработчику для разбора.
