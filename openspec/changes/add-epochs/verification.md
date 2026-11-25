# Verification — add-epochs

## Тестировщик — 2026-11-25, ветка `claude/epochs`, тесты от коммита b0c2bee

Модель — Opus (решение ведущего, progress.md). Тесты написаны по дельтам `specs/{epochs,knowledge-graph,entity-cards,visual-design}`; код читался только для точек входа (CLI `main(..., fetch=, service=)`, `EpochDates`, маршруты, классы DOM). Сеть запрещена фикстурой `no_network` (`tests/knowledge/wd_records.py`: `httpx.HTTPTransport.handle_request` и `socket.create_connection` падают); ответы Wikidata задаёт тест (`record`/`dated`, `RecordFetch`), транспорт — `httpx.MockTransport`, ожидание — внедрённое `wait`, двигающее `ManualClock`. Браузерные — стенд `knowledge_stack` (настоящие шлюз, библиотека, сервис знаний; данные — `stack.world`; `page.route` только для 503 и задержки).

### Требования, сценарии, инварианты

| Требование | Сценарий / инвариант | Тест | Вывод | Журнал |
|---|---|---|---|---|
| Датировка эпохи | Нечёткая граница | tests/knowledge/test_epoch_dates.py::test_fuzzy_boundary | fuzzy {from:[-799,-700],to:[401,500]}, from −750, to 450, century, original | knowledge.epochs.listed epochs=1 (request_id) |
| Датировка эпохи | Предпочтённая датировка | ::test_preferred_dating | 1715–1789 | epochs.listed |
| Датировка эпохи | Первая записанная | ::test_first_recorded_dating | 1600–1750 | epochs.listed |
| Датировка эпохи | основная — первая из действующих | ::test_main_dating_only_from_active[reject,deprecated] | **[reject] ПАДАЕТ — Д1**; [deprecated] 1580–1730 | epochs.listed |
| Датировка эпохи | первая записанная, не самая сильная | ::test_first_recorded_not_strongest | 1600–1750 (первая generated) | epochs.listed |
| Датировка эпохи | пролёт — середины с округлением; чёткая — равные | ::test_span_is_rounded_middle[4] | 1543–1694, 1680, −350…50, 1600–1750 | epochs.listed |
| Доступ к Wikidata | Точности и эра | tests/knowledge/test_wikidata.py::test_precisions_and_era[9 строк таблицы] | границы и точность по таблице; нет даты — None | epoch_dates.checked added / no_dates |
| Доступ к Wikidata | знак — эра; 9+ — год | ::test_era_sign_and_year_precision[5] | −0800→−799, −0001→0, +1685-12@10→1685 | checked added |
| Доступ к Wikidata | век ⌈|год|/100⌉ | ::test_century_number[5] | +1700→1601–1700, −0701→−799…−700 | нет событий (assert_none) — чистое правило |
| Доступ к Wikidata | ниже 6, 0000, не по формату — нет даты | ::test_garbage_time_is_no_date[8] | None | checked no_dates |
| Доступ к Wikidata | Повтор при 429 | ::test_retry_after_429, ::test_four_429_fail_after_three_retries | 2 запроса, wait=[1.0], часы +1 с, UA проекта; 4×429 — 4 запроса, wait=[1,1,1], WikidataError | checked added / fetch_failed, run skipped=1 |
| Доступ к Wikidata | Retry-After, предел 30 с; 429 и 503 | ::test_retry_after_respected_and_capped[4] | wait [7], [2], [30], [30] | checked added |
| Доступ к Wikidata | UA без сведений об операторе; таймаут | ::test_user_agent_without_operator_data_and_timeout | UA == USER_AGENT, без логина/хоста/e-mail/«@»; таймауты конечны | checked added |
| Доступ к Wikidata | Неверный идентификатор | ::test_bad_id_sends_nothing, ::test_hostile_ids_never_requested[10] | 0 запросов, WikidataError | checked fetch_failed (--linked с испорченным QID в базе) |
| Доступ к Wikidata | Ранги значений; предпочтённое/первое обычное/устаревшее никогда | ::test_deprecated_value_never_taken, ::test_rank_choice[5] | начало 1685 и т. д.; только deprecated — no_dates | checked |
| Доступ к Wikidata | только перечисленные свойства | ::test_only_listed_properties_taken | у эпохи только `dating`, метка не переименована, P737/P361… не записаны | entity.created нет; checked added |
| Даты эпох из Wikidata | Дата из Wikidata | test_epoch_dates.py::test_date_from_wikidata | одно `dating` 1685–1815, sourced, атрибуция source `wikidata:Q12539` place `https://www.wikidata.org/wiki/Q12539`, provenance imported {wikidata, properties [P580,P582]}, внешний id | checked added; run {apply,1,1,0,0,0} |
| Даты эпох из Wikidata | Запасные свойства | ::test_fallback_properties | 1543–1687, properties [P571,P576] | checked added |
| Даты эпох из Wikidata | P580/P582 важнее; без начала или конца — no_dates | ::test_property_choice[5] | | checked |
| Даты эпох из Wikidata | Датировка уже есть | ::test_existing_dating_kept | одно `dating` 1543–1687; отчёт existing+dating | checked conflict; run conflicts=1 |
| Даты эпох из Wikidata | Повторный запуск | ::test_repeated_run | строки всех таблиц не изменились | checked unchanged; run skipped=1; ни statement.created, ни entity.created |
| Даты эпох из Wikidata | Проверка без записи | ::test_dry_run, ::test_dry_run_changes_no_table_for_any_result | строки всех 22 таблиц схемы равны; отчёт added | run dry_run added=1; statement.created нет |
| Даты эпох из Wikidata | Без QID; без QID — 0 вызовов | ::test_without_qid, ::test_no_qid_never_fetches[2] | fetch.calls == [] | checked no_qid qid=null |
| Даты эпох из Wikidata | Сбой загрузки и одинаковый QID | ::test_fetch_failed_and_duplicate_qid | fetch_failed, duplicate_qid, added | run checked=3 added=1 skipped=2 |
| Даты эпох из Wikidata | каждый result; checked = added+created+conflicts+skipped | ::test_every_result_and_totals | все 9 кодов в одном запуске | run {apply,10,2,1,1,6}; ambiguous epoch_id=null |
| Даты эпох из Wikidata | существующая не перезаписывается; только действующая останавливает | ::test_existing_never_overwritten[3], ::test_inactive_dating_does_not_block[2] | id, value, атрибуции, primary.dates прежние | statement.created нет |
| Даты эпох из Wikidata | повторный apply не создаёт строк; P737 не импортируется | ::test_repeated_apply_creates_no_rows, ::test_influences_not_imported | | |
| Даты эпох из Wikidata | события — только id, коды, числа | ::test_events_only_ids_codes_numbers | поля = каталог (+контекст), без названий | checked/run/suggested/epochs.listed |
| Подбор записи Wikidata | Кандидаты без применения | ::test_candidates_without_applying | один кандидат Q37853 {qid,label,description,start,end}, wikidata null, строки таблиц равны, сервис базы не вызывался | suggested epochs=1 candidates=1 |
| Подбор записи Wikidata | Повторный подбор | ::test_repeated_suggest | 0 запросов, wikidata и comment на месте | suggested epochs=0 |
| Подбор записи Wikidata | объединение по qid; фильтр классов и дат; не пишет | ::test_suggest_merges_by_qid_and_keeps_fields, ::test_candidate_filter[6], ::test_suggest_never_writes | | suggested |
| Ядро эпох | Новая эпоха из манифеста | ::test_new_epoch_from_manifest | одна эпоха ru primary + en variant, внешний id, датировка 1400–1600 | entity.created type=epoch; checked created; run created=1 |
| Ядро эпох | Две одноимённые эпохи | ::test_two_epochs_same_name | ни одна не изменена | checked ambiguous epoch_id=null |
| Ядро эпох | Неверный манифест; отклоняется до базы и сети | ::test_bad_manifest, ::test_bad_manifest_rejected_first[7×2] | код ≠ 0, stderr, 0 запросов, сервис не создан, файл не переписан | событий epoch_dates.* нет |
| Ядро эпох | сопоставление по варианту, только эпохи; без датировки не заводится | ::test_match_by_variant_and_only_epochs, ::test_not_created_without_dating[2] | | checked added/created; entity.created нет |
| Список эпох | Список эпох | tests/knowledge/test_epochs_list.py::test_epochs_list | порядок, counts.people 2/2 = facets.types.person справочника, Барокко в undated people=1 | epochs.listed epochs=2 undated=1 truncated=false; модель не вызвана |
| Список эпох | Источник датировки; правило источника | ::test_dating_source, ::test_dating_source_rule[4] | wikidata/Q12539, common/null, source, manual | epochs.listed |
| Список эпох | порядок; ≤500 и truncated; описание с пометкой без модели; пустой | ::test_order, ::test_limit_500, ::test_summary_mark_without_model[2], ::test_fuzzy_pairs_and_empty | | epochs.listed |
| Карта раздела | Нечёткая граница эпохи | tests/knowledge/test_map.py::test_fuzzy_epoch_boundary_in_map; tests/web/test_map.py::test_fuzzy_era_edge_on_map | fuzzy {from:[1543,1543],to:[1687,1700]}; DOM data-fuzzy-start="0" data-fuzzy-end="13", `.map-era__fade` 1 у нечёткой и 0 у чёткой, справа | knowledge.map.built по request_id |
| Карта раздела | Эпохи в ответе карты; правило принадлежности | test_map.py::test_epochs_in_map_answer, ::test_epochs_by_membership_rule_on_map | Локк [Просв.], Кант [Просв.], Декарт [НР]; идея без явной — []; belongs_to_epoch в базе — 1 | map.built |
| Карта раздела | Эпоха года при перекрытии; равное начало — по названию | tests/web/test_map.py::test_era_of_year_on_overlap, ::test_era_of_year_tie_by_name | data-selected-era="true" у Просвещения / «Абсолютизм» | map.built |
| Карта раздела | растушёвка не меняет раскладку | tests/web/test_map.py::test_fuzzy_edge_keeps_design_anchors[none,kant] | прямоугольники линий жизни, значков и подписей трудов, `d` линий влияния равны до и после нечёткой границы | map.built (оба ответа) |
| Выбор на карте | Явная эпоха на карте | tests/web/test_map.py::test_explicit_epoch_on_map | Локк c1–c6 при «Просвещении», is-dim при «Научной революции» | map.built |
| Фильтры и поиск карты | Фильтр «Эпоха» | ::test_epoch_filter | отмечено «Просвещение», окно 1680–1800, люди {Локк,Юм,Кант}, труды {Критика}, «Показано 3 из 4 философов · 1 из 3 трудов» | map.built |
| Фильтры и поиск карты | Окно из адреса важнее | ::test_window_from_address_wins | 1750–1800, фильтр отмечен | map.built |
| Фильтры и поиск карты | Неизвестная эпоха в адресе | ::test_unknown_epoch_in_address | адрес /graph без epochs, фильтр пуст, все 4 персоны; в фасете только датированные | map.built |
| Фильтры и поиск карты | по принадлежности, не по окну; объединение | ::test_epoch_filter_by_membership_not_window | НР: только Декарт (Локк скрыт), окно 1543–1687; +Просв.: окно 1543–1800 | map.built |
| Разделы карточки по типу | Карточка эпохи | tests/knowledge/test_mentions_cards.py::test_epoch_card | **ПАДАЕТ — Д2** | card.served |
| Разделы карточки по типу | по датам строками не показывается | ::test_epoch_card_without_date_membership | только `dating`; belongs_to_epoch не записан | card.served type=epoch sections=1 rows=1 |
| Страница эпох | Выбор эпохи | tests/web/test_epochs.py::test_select_epoch, ::test_open_address_selects_epoch | /epochs/<Просв.>, «1680–1800», «Персоны 2», Юм и Кант, событие «Энциклопедии»; ссылка счётчика /reference?epoch=&group=person; «Барокко» под лентой | epochs.listed epochs=2; 3 × catalog.listed filters=["epoch","type"] по request_id |
| Страница эпох | На карте | ::test_on_the_map | /graph?epochs=<Просв.>, отмечено, окно 1680–1800 | map.built |
| Страница эпох | Пересекающиеся эпохи; 9 эпох по дорожкам | ::test_overlapping_epochs_on_lanes, ::test_many_overlapping_epochs_packed | разные data-lane; пересечений прямоугольников пролётов и подписей нет | epochs.listed |
| Страница эпох | Растушёвка | ::test_fuzzy_edges | 0/13 и 0/0 | epochs.listed |
| Страница эпох | Эпох нет | ::test_no_epochs | сообщение, ленты нет | epochs.listed epochs=0 undated=0 |
| Страница эпох | Неизвестная эпоха и разметка в адресе; разметка в названии | ::test_unknown_epoch_and_markup_in_address, ::test_markup_in_epoch_name | «Эпоха не найдена.», без выбора, window.__xss нет, img нет | epochs.listed |
| Страница эпох | ссылка Wikidata из проверенного id | ::test_wikidata_link_from_checked_id[4] | ссылка только для Q12539, noopener; для `javascript:`, разметки, пути — нет | epochs.listed |
| Страница эпох | до 8/8/20; карточка эпохи в панели; ошибка и «Повторить»; загрузка | ::test_member_limits, ::test_epoch_card_action, ::test_service_error_and_retry, ::test_loading_state | 8, 8, первые 20 событий по времени; заголовок карточки; без pageerror/console.error | epochs.listed / card.served; при 503 — событий нет |
| Клавиатура и доступность | Выбор с клавиатуры | ::test_keyboard_select | Tab → первая, → , Enter → вторая выбрана, фокус на заголовке, адрес | epochs.listed |
| Клавиатура и доступность | Края ленты | ::test_ribbon_edges | End/→ остаётся, Esc → /epochs, Home/← остаётся | epochs.listed |
| Клавиатура и доступность | доступное имя, порядок времени | ::test_accessible_names | «Просвещение, 1680–1800», порядок фокуса по времени | epochs.listed |
| Клавиатура и доступность | Малое окно (и 1920×1080) | ::test_layout_fits[1024x576,1920x1080] | лента и заголовок в окне, scrollWidth ≤ ширины, scrollY 0, без пересечений | epochs.listed |
| Разделы в разработке | Старая закладка эпох | ::test_old_epochs_bookmark | /soon/epochs → /epochs, history +1 только за переход, «Назад» не на заглушку, h1 «Эпохи», пункт без «скоро», aria-current | epochs.listed по request_id |
| Разделы в разработке | Ассистент без метки; Пункт-заглушка | tests/web/test_reference.py::test_live_items_without_soon, ::test_future_items_keep_soon (обновлены) | «Эпохи» → /epochs без «скоро»; «Эпохи и контекст» убран из будущих | catalog.listed |

Выдержки журнала (сервис знаний, `request_id` из заголовка ответа):

    knowledge.epoch_dates.checked {"epoch_id": "e_6ceb16508240", "qid": "Q12539", "result": "added"}
    knowledge.epoch_dates.run {"mode": "apply", "checked": 1, "added": 1, "created": 0, "conflicts": 0, "skipped": 0}
    knowledge.epochs.listed {"request_id": "rid-0d12c81cb2", "service": "knowledge", "epochs": 1, "undated": 1, "truncated": false, "snapshot": "fresh"}
    knowledge.map.built {"request_id": "rid-5e7d6eb992", "service": "knowledge", "entities": 0, "links": 0, "truncated": false, "cached": false}
    knowledge.card.served {"request_id": "rid-e00c701521", "service": "knowledge", "entity_id": "e_6ceb16508240", "type": "epoch", "sections": 1, "rows": 1}

### Дефекты

- **Д1 — «Датировка эпохи», инвариант «основная — предпочтённая, иначе первая записанная из действующих».** GIVEN две датировки «Барокко» 1600–1750 (первая) и 1580–1730, первая отклонена оператором (`Statements.reject`). Ожидалось: `/v1/epochs` — `from=1580, to=1730`. Получено: `from=1600, to=1750`; `entities.primary.dates` остаётся отклонённой датировкой (`reject` не пересчитывает основное значение; `set_rank(deprecated)` пересчитывает — этот случай проходит). Тест `test_epoch_dates.py::test_main_dating_only_from_active[reject]`.
- **Д2 — «Разделы карточки по типу», сценарий «Карточка эпохи».** Ожидалось: строка раздела `dating` 1685–1815 «с атрибуцией «Wikidata»». Получено: `attributions[].who == "wikidata:Q12539"` (подпись атрибуции не переводит источник `wikidata:…`; клиент `/v1/entities/{id}/card` тоже показывает его как есть). Остальное в сценарии совпадает (коды разделов, «Локк», нет «Канта»). Тест `test_mentions_cards.py::test_epoch_card`.

### Обновлённые прежние тесты (решение ведущего, progress.md п. 1–2)

- `tests/knowledge/test_map.py::test_contemporaries_on_time_axis` — точное сравнение персоны дополнено `"epochs": [Просвещение]`; эпоха — `"fuzzy": {"from":[1680,1680],"to":[1800,1800]}`; событие — `"epochs": [Просвещение]`. `::test_work_and_idea_on_year` — у труда `epochs` [Просвещение], множество полей идеи дополнено `epochs`, у «Причинности» `epochs == []`. `::test_epoch_span_on_map` — `fuzzy` {from:[1050,1150], to:[1400,1500]}. Основание — дельта `knowledge-graph` «Карта раздела» («Ответ карты SHALL сообщать … эпохи … а у каждой эпохи — нечёткие границы») и действующее «Принадлежность к эпохе». Сравнения остались точными (`==`).
- `tests/knowledge/fixtures/map/demo_map.json` — перезаписан (`PHILOGRAPH_WRITE_MAP_GOLDEN=1`). Сверка: эталон без полей `people[].epochs`, `works[].epochs`, `events[].epochs`, `eras[].fuzzy` **равен** прежнему (скрипт: удалить эти четыре поля из нового и сравнить с `git show HEAD:…` → `rest equal: True`); добавленные ключи — ровно `{('people','epochs'),('works','epochs'),('events','epochs'),('eras','fuzzy')}`. Значения согласуются с правилом: Декарт, Локк — [НР]; Лейбниц (середина 1681) — [НР, Просв.]; Славная революция 1688 — [Просв.]; идеи — [].
- `tests/web/test_reference.py::test_live_items_without_soon` (+ «Эпохи» → `/epochs`), `::test_future_items_keep_soon` (без «Эпохи и контекст»); `tests/e2e/test_visual_design.py::test_future_sections_marked_and_described` (то же; **не прогонялся**, e2e — CI/Lead). Основание — дельта `visual-design` «Разделы в разработке».

### Интерфейсные THEN без события и их серверный якорь

- Адрес `/epochs/<id>`, выбор, фокус на заголовке, Esc → `/epochs`, края ленты, доступное имя — якорь `knowledge.epochs.listed` (request_id ответа страницы); списки описания — `knowledge.catalog.listed` ×3.
- `/soon/epochs` → `/epochs` (replaceState) — `knowledge.epochs.listed`.
- Карта: `data-fuzzy-*`, `data-selected-era`, отметка фасета, окно, «Показано …», замена адреса без `epochs`, цвета/приглушение — `knowledge.map.built` (request_id).
- Раскладка (дорожки, отсутствие наложений, 1024×576/1920×1080, неизменность линий жизни/значков/линий влияния) — чисто визуально-DOM, якорь тот же.
- Карточка эпохи в панели — `knowledge.card.served` (request_id).

### Мутации (временно сломано → тест упал → `git checkout -- <файл>`; `git status src web/src` чист)

Сервер (`/tmp/…/scratchpad/mutate.py`):

    (а) epoch_dates._date: `if existing:` → `if False:`           → 4 failed: test_existing_dating_kept, test_existing_never_overwritten[differs,same,preferred]
    (б) wikidata._astro: `1 - year if bce else year` → `year`     → 4 failed: test_precisions_and_era[-0800@7], test_era_sign_and_year_precision[-0800,-0001,-0384]
    (в) wikidata._bounds: `ceil(year/100)` → `year // 100`         → 3 failed: test_precisions_and_era[+1701@7], test_century_number[+1601,-0701]
    (г) epoch_dates._date: `if not dry_run:` → `if True:`          → 2 failed: test_dry_run, test_dry_run_changes_no_table_for_any_result
    (ж) suggest: после merge `entry["wikidata"] = merged[0]["qid"]` → 5 failed: test_candidates_without_applying, test_suggest_never_writes, test_candidate_filter[start,end,founded]
    (з) WikidataRecord.best: ранги (deprecated, normal, preferred)  → 5 failed: test_deprecated_value_never_taken, test_rank_choice[pref,skip-dep,pref-first,only-dep]
    (и) wikidata._retry_after: всегда DEFAULT_RETRY_AFTER           → 4 failed: test_retry_after_respected_and_capped[все 4]
    (м) Statements._update_primary: после ранга — сильнейший статус → 1 failed: test_first_recorded_not_strongest

Клиент (`web/src/map/model.ts`, после каждой мутации `npm run build`; в конце сборка без мутаций):

    (д) related для эпохи: персоны по середине жизни вместо epochs   → failed: tests/web/test_map.py::test_explicit_epoch_on_map
    (е) inEpochs → всегда true (фильтр только окном)                → failed: test_epoch_filter, test_epoch_filter_by_membership_not_window
    (к) eraOf: самое раннее начало (`e.from < best.from`)           → failed: test_era_of_year_on_overlap, test_era_of_year_tie_by_name
    (л) inEpochs пропускает сущности без epochs                     → failed: test_epoch_filter

### Команды и итоги

    pytest -q tests/knowledge/test_wikidata.py                 →  52 passed in 11.89s
    pytest -q tests/knowledge/test_epoch_dates.py              →  1 failed (Д1), 63 passed
    pytest -q tests/knowledge/test_epochs_list.py              →  11 passed in 25.36s
    pytest -q tests/knowledge/test_map.py                      →  12 passed in 10.57s
    pytest -q tests/knowledge/test_mentions_cards.py -k epoch_card  →  1 failed (Д2), 1 passed
    pytest -q tests/web/test_map.py                            →  48 passed in 287.54s (5.8: прежние DOM-проверки линий жизни, узлов, маршрутов — зелёные)
    pytest -q tests/web/test_epochs.py                         →  23 passed (после правки двух ожиданий-помощников теста; последний полный прогон 21 passed + 2 passed)
    pytest -q tests/web/test_reference.py                      →  31 passed in 75.10s
    python scripts/check_traceability.py                       →  Требований с тестами: 378 из 378 (epochs в enforce)
    pytest -q tests/knowledge                                  →  2 failed (Д1, Д2), 606 passed, 1 skipped in 379.00s
    lint-imports                                               →  Contracts: 3 kept, 0 broken
    ruff check tests && ruff format --check tests              →  All checks passed! / 133 files already formatted
    ruff check . ; ruff format --check .                       →  1 error (E501 scripts/dev_stack.py:100); 3 files would be reformatted
                                                                  (scripts/dev_stack.py, src/philograph/platform/queue.py, src/philograph/prompts/__init__.py) —
                                                                  продуктовый код, не правился тестировщиком; передаётся разработчику (6.2)

### Не прогонялось на машине агента

- `tests/e2e` (в том числе обновлённый `test_visual_design.py`) и визуальные эталоны win32 (`scripts/visual_check.py`) — прогоняет Lead/CI; на Linux сравнение снимков пропускается.
- Полный `pytest -q`, `tests/ops`, Docker — по ограничению машины (1 ГБ, 1 CPU).

### Не покрыто / оговорки

- «Повторный подбор»: «комментарий» проверен как поле `comment` манифеста; YAML-комментарии внутри записей `save_manifest` не сохраняет (сохраняется только шапка файла) — спецификация неоднозначна, дефектом не считаю.
- `dating.wikidata` проверяется во вложенном объекте `dating` (форма из design.md); в спецификации поле названо `wikidata` без места.
- Порядок «первая записанная» опирается на порядок строк `Statements._raw` без `ORDER BY`; на SQLite это порядок вставки, на PostgreSQL не гарантирован — риск для ревьювера, тестом на SQLite не ловится.
