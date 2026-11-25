# Verification — add-geo-timeline

## Тестировщик — 2026-11-25, код продукта — bfb9134 (не менялся)

Тесты написаны по дельте `specs/geo-timeline/spec.md` и контракту `design.md` (`/v1/map/places`, события, тексты RU). Файлы:
- `tests/knowledge/test_geo_coordinates.py` — «Координаты места», «Вид места в биографии» (сервис, `onto`);
- `tests/knowledge/test_geo_enrich.py` — «Места и координаты из Wikidata» (записи задаёт тест, сеть запрещена `no_network`, команда `geo_enrich.main --from-file`);
- `tests/knowledge/test_geo_layer.py` — «Географический слой карты» (настоящий `build_app` с `SectionMap`/`PlaceLayer`, библиотека и модель — подменённые транспорты; `request_id` задаёт тест);
- `tests/web/test_geo_view.py`, `test_geo_scene.py`, `test_geo_limits.py` и помощники `tests/web/geo_helpers.py` — интерфейсные требования на стенде `knowledge_stack` (настоящий сервис знаний за шлюзом). Время — `page.clock`; `page.route` — только 320 мест, задержка, 500;
- `tests/e2e/test_geo_globe.py` — 7.7, на машине агента не прогонялся (1 ГБ RAM, без Docker): прогон в CI или у ведущего.

Покрыто: 16 требований, 58 из 58 сценариев, плюс нормативные тесты (`invariant=`). `openspec/traceability.yaml`: `geo-timeline` в `enforce`.

Журнал. Сервисные тесты — события фикстуры `events`, в `test_geo_layer.py` по `request_id` запроса. Браузерные — `knowledge.geo.built` по `x-request-id` ответа `/map/places`, полученного страницей (`geo_built`), плюс проверка, что `knowledge.map.built` с этим `request_id` нет. Клиент событий не пишет (Р4): для интерфейсных THEN якорь — `knowledge.geo.built`, остальное — DOM, адрес и сетевые запросы.

Сырой пример события (сервис, сценарий «Кант и Юм»):
`knowledge.geo.built {'request_id': 'rid-…', 'service': 'knowledge', 'entities': 2, 'places': 1, 'placements': 3, 'unplaced': 1, 'truncated': False, 'cached': False}`

### Сервис

| Требование | Сценарий / инвариант | Тест | Вывод | Журнал |
|---|---|---|---|---|
| Координаты места | Координаты Кёнигсберга | test_konigsberg_coordinates_rounded_and_same_key | value {lat 54.71, lon 20.51}; повтор 54.71/20.51 → тот же id; 1 утверждение | нет refused |
| Координаты места | Границы и мусор | test_bounds_and_garbage | (90,180), (−90,−180) приняты; 6 отказов, коды по сценарию | по одному refused type=coordinates code=… на отказ |
| Координаты места | Без атрибуции | test_without_attribution_refused | StatementError code=attribution_required | refused type=coordinates code=attribution_required |
| Координаты места | Не для модели | test_coordinates_not_in_model_output_schema | нет coordinates в enum схемы ни для одного семейства и без семейств | — (нет refused) |
| Координаты места | inv: порядок проверок и коды code (13 входов) | test_check_order_and_codes | «не число» раньше «пределов»; 90.004 → out_of_range (по исходному) | refused с тем же code |
| Координаты места | inv: значение без lat/lon | test_malformed_value_refused (5) | отказ | один refused, code ∈ {None, geo_not_number} |
| Координаты места | inv: хранится только округлённое (5) | test_only_rounded_value_stored | round(x,2), ключ по округлённому, find по сырому находит то же | нет refused |
| Координаты места | inv: без атрибуции никогда (18) | test_never_without_attribution | статус/происхождение/ранг/evidence не спасают | refused attribution_required |
| Координаты места | inv: флаг реестра, не код типа | test_attribution_rule_is_registry_flag | новый тип с флагом — отказ; снятый флаг у coordinates — принято | refused type=observatory_at |
| Координаты места | inv: одна координата | test_one_coordinate_chosen | раньше записанная → сильнее статус → preferred | geo.built places=1 |
| Вид места в биографии | Место деятельности со временем | test_activity_with_time | qualifiers {place_role: activity, time 1628–1649} | нет refused |
| Вид места в биографии | Вид вне списка | test_role_outside_list_refused | отказ | refused type=lived_in, reason содержит place_role и «отпуск» |
| Вид места в биографии | Заполненный реестр | test_filled_registry_gets_place_role | qualifiers [time, place_role], тип конца оператора settlement сохранён, версия +1, birth принят | нет refused |
| Вид места в биографии | inv: список значений (5), вне списка (6), повторная загрузка | test_roles_in_list_and_without_role, test_roles_outside_list, test_filled_registry_idempotent_and_keeps_operator | — | refused type=lived_in |
| Места и координаты из Wikidata | Кант из Wikidata | test_kant_from_wikidata (CLI --from-file) | 2 lived_in birth 1724 / death 1804, координаты; атрибуция source `wikidata:Q…`, place `https://www.wikidata.org/wiki/Q…`, sourced, imported, run_id | enriched coordinates=1 placements=2 places_created=1 skipped=0 failed=0 dry_run=false; skipped нет |
| Места и координаты из Wikidata | Повторный запуск | test_rerun_adds_nothing | число утверждений и сущностей то же | enriched 0/0/0 |
| Места и координаты из Wikidata | Влияние и чужие свойства | test_influence_and_foreign_properties_not_imported | нет influenced_by/citizenship, место гражданства не создано | skipped о P737/P27 нет |
| Места и координаты из Wikidata | Сухой прогон | test_dry_run_writes_nothing | база не изменилась | enriched dry_run=true 1/2/1 |
| Места и координаты из Wikidata | Пропуски | test_skips_reasons_and_counters | `<script>` не запрашивался | skipped: Декарт bad_qid, Юм refused, Декарт/P20 fetch_failed; enriched skipped=2 failed=1 entities=2 |
| Места и координаты из Wikidata | Откат | test_rollback_keeps_verified_and_places | осталось проверенное, место осталось | rolled_back statements=2 places_kept=1 |
| Места и координаты из Wikidata | Не из пути читателя | test_not_from_reader_path | `/map/places`, `/map` — fetch 0, `fetch_entity`/`http_fetch`/`run` 0 | geo.built ×2 |
| Места и координаты из Wikidata | inv: новых персон и событий нет; только свойства таблицы; P937 со временем; QID только `^Q\d+$` (9 внешних id, 7 значений); атрибуция у каждой записи; поля событий; файл без сети; существующее место не дублируется | test_no_new_people_or_events, test_only_table_properties, test_activity_from_p937, test_bad_external_id_never_fetched, test_bad_value_id_not_fetched_or_written, test_every_record_attributed, test_event_fields_only_ids_codes_numbers, test_file_run_without_network, test_existing_place_reused | — | поля трёх событий = перечень design.md, значения int/bool/`[A-Za-z0-9_]+`, без названий |
| Географический слой карты | Кант и Юм | test_kant_and_hume | places [Кёнигсберг 54.71/20.51], 3 размещения (birth 1724–1724, activity null, death 1804–1804), unplaced [Юм] | geo.built entities=2 places=1 placements=3 unplaced=1 cached=false; map.built нет |
| Географический слой карты | Кэш и его сброс | test_cache_and_reset | 2-й = 1-му; 3-й — 2 места | cached false/true/false, places=2 unplaced=0 |
| Географический слой карты | Сущность вне карты | test_entity_outside_map | X нет в placements/unplaced, truncated=true, limit=2 | truncated=true entities=2 |
| Географический слой карты | Запись без вида и с видом | test_role_record_displaces_plain | одна запись birth | placements=1 |
| Географический слой карты | Только без вида | test_only_plain_record | Эдинбург, role/from/to null | placements=1 unplaced=0 |
| Географический слой карты | Ограниченный кэш | test_cache_is_bounded | 100 несуществующих `textbook` с `only_textbook=true` — каждый ответ пустой слой; областей в кэше ≤ 8 после каждого запроса, в конце ровно 8 (предел стенда) | geo.built 0/0/0 |
| Географический слой карты | inv: ⊆ /map при любом пределе (18: 6 пределов × 3 области), событие с видом event, отклонённые/устаревшие (3), без цитат и абзацев, generated, без модели и сети, нет map.built, поля только числа, LRU | test_layer_subset_of_map, test_event_placement, test_rejected_not_in_layer, test_no_quotes_or_paragraphs, test_generated_marked, test_no_model_and_no_network, test_no_map_built_from_layer, test_built_fields_numbers_only, test_cache_evicts_least_recent | слой = люди и события карты (placed ∪ unplaced), без лишних ключей | одно geo.built на request_id |

### Интерфейс (якорь — `knowledge.geo.built` по request_id ответа `/map/places` страницы в каждом тесте)

| Требование | Сценарии | Тесты |
|---|---|---|
| Вид «Глобус» | Переключение с выбранным Кантом; Ссылка на глобус; Хронология не грузит глобус; inv: линзы скрыты | test_switch_keeps_selection_filters_window (одно geo.built за вход-выход), test_link_to_globe, test_chronology_does_not_load_globe (нет `/map/places`, `GlobeView`, суши; событий нет), test_lenses_hidden_on_globe |
| Вращение и масштаб | Исходный вид детерминирован; Клавиши (15,50 → 45,80 → 1.56 → 15,50/1); Дальнее полушарие; inv: шаги/Shift/зажимы/1–8, колесо, перетаскивание, граница 90° | test_initial_view_deterministic, test_keys_rotate_zoom_reset, test_far_hemisphere_hidden, test_key_steps_and_bounds, test_wheel_zoom, test_drag_rotates, test_hidden_boundary_90 |
| Год и проигрывание | Без автозапуска (1711 · Просвещение); Шаг клавишей (1791, t=1791, «1791 год: 2 места, 2 человека»); Год вне окна; Проигрывание в окне; Скрытая вкладка; inv: год в окне (9 входов), клавиши, щелчок по шкале, эпоха года, середина жизни, равенство, скорости (3), пробел | test_no_autoplay, test_page_up_step_and_announce, test_year_outside_window, test_playback_in_window, test_hidden_tab_pauses, test_year_always_in_window, test_year_keys, test_click_on_scale (Д1), test_year_label_era, test_default_year_mid_life, test_default_year_tie_earlier, test_playback_speeds, test_space_toggles_playback |
| Люди, события и связи во времени | Декарт переезжает; Юм без вида; Связь Юм → Кант (дуга от Эдинбурга к Кёнигсбергу ±2 px); Только проверенные; inv: событие 150 вкл., не родившийся, непрозрачность 1 → 0,15, связь без главного места, фильтры карты | test_descartes_moves, test_hume_without_role, test_link_hume_kant_lifetime, test_only_verified_hides_generated_arcs, test_event_visible_150_inclusive, test_not_born_not_shown, test_opacity_by_age, test_link_without_main_place_not_drawn, test_links_follow_map_filters |
| Размещение | Счётчик без места (geo.built unplaced=1); Непроверенное место; Название как текст; inv: нет отметок без размещения (unplaced=3), смешанное место проверено, одна отметка на место | test_unplaced_counter, test_unverified_place, test_place_name_as_text, test_no_marks_without_placement, test_mixed_place_is_verified, test_people_merged_in_one_mark |
| Выбор | Выбран Кант; Отметка места («Париж, 1750», 2 кнопки); Выбран без места; inv: приглушённые выбираемы, событие, группа c1…c6 | test_kant_selected, test_place_mark_selection, test_selected_without_place, test_dimmed_still_selectable, test_event_selection, test_group_selection_c1_c6 |
| Текстовая альтернатива | Список совпадает с глобусом; Только клавиатурой; Живая область не частит (Д2); inv: скрытые в списке, объявление после шага, атрибуты доступности, Esc | test_list_matches_globe, test_keyboard_only, test_live_region_not_chatty, test_list_includes_hidden, test_live_region_announces_after_step, test_globe_accessibility_attributes, test_escape_clears_selection |
| Пределы | Много мест (route: 320 мест, у места i — i людей, 51 360 человек); Много связей (260 настоящих влияний); Подписи без наложений 1280/1920 (Д3); Вес фрагмента; inv: равенство по id, порядок связей по весу концов | test_many_places, test_many_links, test_labels_do_not_overlap, test_fragment_weight, test_place_limit_tie_by_id, test_link_limit_order |
| Без WebGL и сторонних запросов | WebGL недоступен (не засчитывается за другие сценарии); Только свой адрес (вращение, год, проигрывание) | test_without_webgl, test_only_own_address |
| Без лишнего движения | Уменьшенное движение (центр одной записью, год +10/+20/+30); Плавный поворот; inv: клавиши сразу, покой 5 с (2) | test_reduced_motion, test_smooth_turn, test_reduced_motion_keys_immediate, test_still_without_action |
| Глобус на листе | Вечер при лампе (2 темы); Три кадра (3 размера × 2 темы); Токены и покой; inv: токены одинаковы в темах | test_contrast_in_both_themes, test_three_frames, test_tokens_and_calm, test_tokens_same_in_themes |

Исключения из проверки журнала: все интерфейсные THEN наблюдаются в DOM, адресе и запросах — клиентского журнала в продукте нет (design.md, Р4); в каждом браузерном тесте проверено одно `knowledge.geo.built` по request_id ответа страницы. Исключения: test_many_places, test_place_limit_tie_by_id (ответы подменены `page.route`, событие пишет прямой запрос теста — проверено, что оно одно), test_layer_error до «Повторить» (ответ 500 подменён — серверного события нет, после «Повторить» — одно).

Команды и итоги:

    pytest -q tests/knowledge/test_geo_coordinates.py  →  62 passed in 23.72s
    pytest -q tests/knowledge/test_geo_enrich.py       →  30 passed in 14.64s
    pytest -q tests/knowledge/test_geo_layer.py        →  34 passed in 44.67s
    pytest -q tests/web/test_geo_view.py               →  2 failed, 32 passed in 252.27s
        FAILED test_click_on_scale (Д1)
        FAILED test_playback_in_window — в прогоне всего файла; отдельно 3 из 3 passed
               (10.5/11.3/10.9 с). Причина не установлена, нестабильность под нагрузкой
               машины (1 CPU); в прогоне до этого — passed. Судье: прогнать отдельно.
    pytest -q tests/web/test_geo_scene.py              →  1 failed, 32 passed in 213.77s
        FAILED test_live_region_not_chatty (Д2)
    pytest -q tests/web/test_geo_limits.py             →  1 failed, 23 passed in 234.67s
        FAILED test_labels_do_not_overlap[1280-720] (Д3; [1920-1080] падал в двух прогонах
               из трёх — пересечение зависит от раскладки шрифта)
    python scripts/check_traceability.py               →  Требований с тестами: 403 из 403
    ruff check src tests                               →  All checks passed!
    lint-imports                                       →  Contracts: 3 kept, 0 broken.

Мутации (скрипт в scratchpad; продуктовый код возвращён, `git diff -- src web` пуст, клиент пересобран):

    [1] сведение «с видом вытесняет без вида» убрано (geo.py)  → упал test_role_record_displaces_plain
    [2] слой отдаёт сущности вне /map (geo.py)                → упали test_entity_outside_map, test_layer_subset_of_map ×14
    [3] импорт P737 (geo_enrich.PROPERTIES)                   → упали test_influence_and_foreign_properties_not_imported, test_only_table_properties
    [4] координаты не округляются до ключа (statements.py)    → упали test_konigsberg_coordinates_rounded_and_same_key, test_only_rounded_value_stored ×4
    [5] qualifiers не дописываются (_add_missing_defaults)    → упал test_filled_registry_gets_place_role
    [6] запись без вида — не проживание на всю жизнь (timeline.ts startOf) → упал test_hume_without_role
    [7] сущность без места в (0, 0) (timeline.ts geoModel)    → упал test_no_marks_without_placement (test_unplaced_counter прошёл)
    [8] MAX_PLACES/MAX_LINKS = 100000                         → упали test_many_places, test_many_links
    [9] граница 150 исключительно (visibleAt, люди)           → упал test_descartes_moves
    [10] linkYear без ADULT_AGE                               → упал test_link_hume_kant_lifetime
    [11] eraOf: более раннее начало при перекрытии (model.ts) → упал test_year_label_era
    [12] clampYear без зажима                                 → упал test_year_outside_window
    [13] isNear: π/2 + 0.01                                   → упал test_hidden_boundary_90
    [14] useState(true) в usePlayback (автозапуск)            → упал test_no_autoplay
    [15] поворот анимируется при reduced motion (GlobeView)   → упал test_reduced_motion
    [16] void import("./geo/GlobeView") в MapPage             → упал test_chronology_does_not_load_globe
    [17] fetch суши с cdn.jsdelivr.net (land.ts)              → упал test_only_own_address (и ловушка стенда outside)
    Клиентские мутации — с пересборкой `npx vite build`; после всех — чистая сборка.

### Дефекты и расхождения

- **Д1. Щелчок по шкале не выбирает год.** Требование «Год и проигрывание»: «Год SHALL выбираться … щелчком по шкале». Ожидалось: щелчок по засечке 1775 при окне 1700–1800 ставит год ≈ 1775. Получено: `data-year` остаётся 1700. Прямоугольник окна времени `.map-overview__window` лежит поверх шкалы на всей ширине окна и забирает нажатие (сдвиг окна), до выбора года оно не доходит. Тест: test_click_on_scale.
- **Д2. Живая область меняется дважды.** Сценарий «Живая область не частит»: пять `]` за 0,5 с, затем проигрывание 3 с — «сменила текст не больше одного раза». Получено (page.clock): `[[1389, '1782 год: 5 мест, 7 человек'], [2405, '1786 год: 5 мест, 7 человек']]` — первое объявление сразу после первого шага, второе — отложенное, через секунду. Правило «не чаще раза в секунду» соблюдено, предел сценария — нет. Тест: test_live_region_not_chatty.
- **Д3. Подписи мест пересекаются.** Сценарий «Подписи без наложений» (30 мест, 1280×720 и 1920×1080): прямоугольники `[data-geo-label]` попарно пересекаются на 3–4 px (например, «Городок-00» x 696.6–766.6, y 549–568 и «Городок-06» x 762.4–831, y 565.5–584.5). Допуск теста — 0,5 px, как в `label_clashes` хронологии. Похоже, раскладка меряет текст без ореола (`stroke-width` 3,2 px) и без нижних выносных. Тест: test_labels_do_not_overlap[1280-720], [1920-1080].
- **Д4 (спецификация). «Ограниченный кэш» противоречит требованию.** Сценарий ждёт пустой слой для 100 несуществующих `textbook`. Но без `only_textbook` область карты не сужается (как у `/map`: `textbook` только помечает связи), а требование говорит, что `unplaced` — сущности карты. Значит, пустой слой возможен только с `only_textbook=true`. **Закрыт (55164bc):** WHEN уточнён — `only_textbook=true`; тест проверяет только это чтение.
- **Д5 (спецификация, формулировка). Выбор в адресе.** Сценарий «Переключение с выбранным Кантом» говорит «адрес содержит `sel=<Кант>`», а продукт держит выбор в пути `/graph/<id>` (принятое правило карты, сценарий «Ссылка на глобус» сам открывает `/graph/<Кант>`). **Закрыт (55164bc):** THEN — путь `/graph/<Кант>`; тест строгий: путь ровно `/graph/<Кант>`, `sel` в адресе нет (на глобусе и после возврата).
- **Наблюдение (не тест).** До первого объявления живая область содержит устаревшую сводку: на `/graph/<Кант>?view=globe` — «1764 год: 0 мест, 0 человек», когда `aria-label` глобуса уже «2 места, 2 человека».
- **Наблюдение.** «Участники события» на глобусе — как на хронологии: все живые в год события (и стимулированные), а не только связь «участвовал». Спецификация слова не определяет; тест проверяет то, что верно при обоих чтениях.

### Повторная проверка — код продукта beb18eb, спецификация 55164bc (2026-11-25)

Клиент пересобран (`npm run build`) после beb18eb. Тесты изменены только под уточнённые сценарии: `test_cache_is_bounded` (Д4, убрана ветка без `only_textbook`), `selection_in_address` в `test_geo_view.py` (Д5, только путь). Прогоны — по одному файлу, последовательно:

    pytest tests/knowledge/test_geo_layer.py                      → 34 passed
    pytest tests/web/test_geo_view.py                             → 34 passed (220 s)
    pytest tests/web/test_geo_scene.py                            → 33 passed (219 s)
    pytest tests/web/test_geo_limits.py                           → 24 passed (219 s)
    pytest tests/web/test_geo_view.py -k test_playback_in_window  ×3 → 1 passed, 1 passed, 1 passed

Мутация к изменённому тесту Д4: [18] вытеснение кэша `while len(self._cache) > self.cache_size * 100` (geo.py) → упал test_cache_is_bounded (`assert 9 <= 8`); код восстановлен.

Д1 (test_click_on_scale), Д2 (test_live_region_not_chatty), Д3 (test_labels_do_not_overlap[1280-720], [1920-1080]) — проходят, дефекты закрыты. Наблюдение об устаревшей сводке «0 мест, 0 человек» — не воспроизводится (живая область пуста до первого объявления, test_geo_scene зелёный). test_playback_in_window — зелёный в прогоне файла и 3/3 отдельно.

### Дополнение после ревью — код 4eb7bf0, спецификация 38bb63e (2026-11-25)

Новые и дополненные тесты:
- `test_geo_enrich.py::test_enrich_refusal_writes_one_event` ×6 («Координаты места», inv «при каждом отказе — refused»): P625 Эдинбурга (95, 0) → одно `knowledge.statement.refused` `type=coordinates`, `code=geo_out_of_range`; (10**400, 0) и (0, −10**400) → одно событие с `code=geo_not_number`, исключения нет; всё в обычном прогоне и в dry-run; одно `geo.skipped reason=refused`, `coordinates=0`, координат в базе нет.
- `test_geo_coordinates.py::test_check_order_and_codes` + 2 значения: `lat=10**400`, `lon=-10**400` → `StatementError geo_not_number`, одно событие, записей нет.
- `test_geo_enrich.py::test_rollback_leaves_other_run` («Откат»): два запуска (Кант, затем Юм); откат первого удаляет его 3 утверждения, 2 утверждения второго запуска остаются; `geo.rolled_back statements=3`.
- `test_geo_layer.py::test_cache_is_bounded` (Ж8): после 100 областей с `only_textbook=true` — ещё 100 разных `textbook` без `only_textbook`; `cached=False`, областей в кэше ≤ 8 после каждого, в конце 8.
- «Вращение и масштаб» (приближение 1 — глобус целиком в кадре): тесты проверяли только `data-zoom="1"` в исходном виде, прежнюю формулировку («места помещаются») не утверждали — правка не затронула. Новое утверждение «глобус целиком в кадре» отдельным тестом не покрыто.

Прогоны (по одному файлу):

    pytest tests/knowledge/test_geo_coordinates.py → 64 passed
    pytest tests/knowledge/test_geo_enrich.py      → 37 passed
    pytest tests/knowledge/test_geo_layer.py       → 34 passed

Мутации (код восстановлен после каждой):

    [19] check_value(..., emit=False) в geo_enrich           → упали 6/6 test_enrich_refusal_writes_one_event
    [20] _finite ловит ZeroDivisionError вместо OverflowError → упали 4 enrich (10**400) + 2 test_check_order_and_codes
    [18] вытеснение кэша × 100 (geo.py)                      → упал test_cache_is_bounded (assert 9 <= 8)
    [21] rollback_run без всех фильтров run_id (attributions, evidence, provenance) → упал test_rollback_leaves_other_run
    [21a] снят только один фильтр run_id (provenance или attributions) → тест проходит: эквивалентный мутант,
          второй фильтр (утверждение с атрибуцией другого запуска не удаляется) сохраняет поведение.

Не покрыто:
- «Вращение и масштаб»: «при приближении 1 глобус целиком в кадре» — нет отдельного теста (браузерные файлы в этом шаге не менялись).
- 7.7 e2e (`tests/e2e/test_geo_globe.py`) — написан, на машине агента не прогнан: нужен Docker или `dev_stack` с памятью больше 1 ГБ.
- «без границ государств» у суши — визуально по снимку (сетка, суша, берег без границ видны глазами), автоматической проверки нет: суша растровая (canvas, вариант Б).
- Время кадра 16 мс — замер разработчика (5.6), не утверждение теста.
- Снимки-эталоны — только win32, на Linux проверки по DOM.
