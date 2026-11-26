# Verification — add-historical-polities

## Тестировщик — 2026-11-26, коммит a0843ab + этот коммит

Тесты написаны от дельты `specs/geo-timeline/spec.md` и `owner-spec.md` (H1–H9). Ожидания считаются в тесте по входной фикстуре: наивный фильтр строк GeoJSON, правило названий по словарю Wikidata теста, своя сферическая площадь (порт d3 `geoArea`), shapely для валидности, SHA-1 в тесте, d3-geo на странице оракула для видимой площади и ширины подписи.

Файлы:
- `tests/knowledge/test_polities_build_spec.py` — «Сборка исторических границ», «Пределы исторического слоя» (замер на фикстуре), «Атрибуция» (документация и манифест);
- `tests/knowledge/test_polities_layer_spec.py` — «Слой политических образований на год», «Русские названия образований» (серверная часть);
- `tests/web/test_geo_polities.py` — глобус в историческом режиме, атрибуция на странице, новые сценарии MODIFIED-требований;
- `tests/web/knowledge_stack.py` (6.1) — `start(..., polities_env=...)`: артефакт передаётся сервису знаний через `PHILOGRAPH_POLITIES_DB` (`PolityLayer.from_env`); `polities_delay` и `polities_gate` — задержка и «ворота» ответа `/map/polities`. Без `polities_env` всё как раньше (503, запасной режим): прежние тесты глобуса не менялись.

### Матрица

| Требование | Сценарий / инвариант | Тест | Вывод | Журнал |
|---|---|---|---|---|
| Сборка исторических границ | Сборка фикстуры | build_spec::test_build_fixture | код 0, 8 строк, геометрия валидна, ≤ precision, площадь < 2π | built rows=10 polities=8 skipped_relation=1 skipped_invalid=1, vertices_out<vertices_in |
| | Маленькое образование остаётся | build_spec::test_tiny_polity_kept | один многоугольник — большее кольцо 0,09² | built polities=2 |
| | Вырожденное кольцо | build_spec::test_degenerate_ring_becomes_grid_cell | квадраты 0,004° (Ватикан) и 0,00004°: по одной клетке 0,01°×0,01° у центроида ([12,45; 12,46]×[41,90; 41,91] и [30,12; 30,13]×[50,45; 50,46]), ≤ 2 знаков, валидна, < 2π | built polities=3, skipped_invalid=1 (только «Broken») |
| | Одно образование — один id | build_spec::test_one_polity_one_id | 3 строки HRE, id = sha1[:12] | built polities=16 |
| | Повторная сборка | build_spec::test_rebuild_same_rows | строки равны поле в поле | второе built label_requests=0, запросов 0 |
| | Неверная контрольная сумма | build_spec::test_checksum_mismatch | код ≠ 0, SHA-256 артефакта прежняя | rejected code=checksum_mismatch, built нет |
| | Данные вне git (H9) | build_spec::test_data_outside_git | git ls-files, .gitignore, манифест | события нет по природе |
| | инв.: геометрия/точность/площадь на враждебных входах (бабочка, CW/CCW, дыра, 9 знаков, антимеридиан), precision 1–3 | build_spec::test_geometry_rules_hostile_input | все 7 строк, нарушений 0 | built polities=7 |
| | инв.: внешнее по часовой, дыры против | build_spec::test_ring_orientation | шнурок < 0 / > 0, площадь < 2π | built polities=2 |
| | инв.: ни одна строка не пропала, пропуски учтены | build_spec::test_no_row_lost_and_skips_counted | A, B, C | built 13/3/2/8 |
| | инв.: один id на Name | build_spec::test_id_is_sha1_of_name | | built polities=10 |
| | инв.: детерминированность | build_spec::test_build_deterministic_three_times | 3 сборки равны | label_requests 0, 0 |
| | инв.: потоковое чтение | build_spec::test_streaming_build | GeoJSON 12 МБ: пик tracemalloc < size/2, extract запрещён, файлов кроме артефакта и кэша нет | built polities=1200 |
| | инв.: атомарность при сбое | build_spec::test_failed_build_keeps_artifact | оборванный GeoJSON: прежний артефакт, временных файлов нет | built нет |
| | инв.: при неверной сумме артефакт не создаётся | build_spec::test_checksum_mismatch_no_artifact_created | код ≠ 0, файла нет | rejected checksum_mismatch |
| | инв.: fetch удаляет файл при расхождении | build_spec::test_fetch_mismatch_deletes_download | каталог пуст | rejected checksum_mismatch |
| | инв.: метаданные и индекс | build_spec::test_artifact_metadata | версии, sha256, source, build, индекс from_year | built dataset_version |
| Слой на год | Год 1650 | layer_spec::test_year_1650 | 3 образования, интервал | served year=1650 polities=3 cached=false (по request_id) |
| | Год без образований | layer_spec::test_year_without_polities[-3500, 2100] | [] | served polities=0 |
| | Кэш по интервалу | layer_spec::test_cache_by_interval | 2-й, 3-й cached, polities побайтно | served false, true, true |
| | Ограниченный кэш | layer_spec::test_bounded_cache | ≤ 8 интервалов | served cached=false |
| | Предел кэша по байтам | layer_spec::test_cache_byte_limit | сумма ≤ предела | served false×3 |
| | Слой больше предела кэша | layer_spec::test_layer_bigger_than_cache | | served false×2 |
| | Нет артефакта | layer_spec::test_no_artifact | 503 polities_unavailable ×2, /map/places 200 | unavailable missing, format |
| | Испорченный год | layer_spec::test_bad_year | 400 bad_year ×6 | rejected bad_year ×6, served нет |
| | Без сети и модели | layer_spec::test_no_network_no_model | соединений 0, модели 0 | served ×2 |
| | инв. H1: −3500…2100, каждый год | layer_spec::test_activity_every_year | набор = наивный фильтр, from ≤ T ≤ to | served ×5601 |
| | инв.: интервал наибольший | layer_spec::test_interval_maximal | | served valid_from/valid_to |
| | инв.: слияние строк одного id | layer_spec::test_merge_rows_same_id | MultiPolygon, from/to, поля строки с наибольшим from_year | served polities=2 |
| | инв.: порядок площадь↓, id | layer_spec::test_order_area_then_id | детерминирован | served polities=6 |
| | инв.: событие без названий и геометрии | layer_spec::test_served_event_has_no_payload | поля = дельта | served |
| | инв.: из кэша без чтения артефакта | layer_spec::test_cached_without_reading_artifact | sqlite3.connect не вызывается | served cached=true ×3 |
| | инв.: LRU | layer_spec::test_cache_lru | | served cached |
| | инв.: враждебный год | layer_spec::test_bad_year_hostile[11] | 400 | rejected bad_year |
| | инв.: цифры не ASCII | layer_spec::test_bad_year_non_ascii_digits[3] | 400 bad_year (после 2451530; до — D1: 200) | rejected bad_year |
| | инв.: границы −9999, 9999, 0, −1 | layer_spec::test_year_bounds_accepted | 200 | served year |
| Русские названия | Священная Римская империя | layer_spec::test_hre_russian_label | ru/label/Q12548 | built ru_labels = число строк с принятой меткой по словарю теста |
| | Без русской метки | layer_spec::test_without_russian_label | все original, wikidata null у 2 и 3, в запросах нет | served untranslated=3 |
| | Заголовок русской Википедии | layer_spec::test_ruwiki_title | «Речь Посполитая», «Тест (а)» | built ru_sitelinks=2 |
| | Испорченные метки | layer_spec::test_hostile_labels; на глобусе — web::test_historical_globe_flow | 3 original, «<b>Империя</b>» ru, на глобусе текст буквально, элемента `<b>` нет | built ru_labels на 3 меньше; served untranslated=3 |
| | Пачки запросов | layer_spec::test_label_batches | 3 запроса ≤ 50, адрес и параметры, без languagefallback | built label_requests=3 qids=120 |
| | Без сети | layer_spec::test_offline_build | соединений 0, кэш → метки | built label_requests=0 |
| | Пометка на глобусе | web::test_historical_globe_flow | italic + `<title>` «… — без русского названия» / normal | served по request_id |
| | инв.: name — принятая метка своего QID или original | layer_spec::test_name_rule_every_year (1500–1900) | | served untranslated |
| | инв.: QID проверяется до запроса | layer_spec::test_hostile_qids_not_requested | в Wikidata только Q12548 (после 2451530; до — D1) | built qids=1 |
| | инв.: --refresh-labels | layer_spec::test_refresh_labels | | built label_requests |
| | инв.: форма кэша меток | layer_spec::test_labels_cache_shape | | built qids |
| | инв.: эндпоинт без сети за названиями | layer_spec::test_endpoint_no_wikidata | | served |
| Исторические границы на глобусе | Смена года (H4) | web::test_historical_globe_flow | 1650 → 1800: интервал, подписи СРИ/РП, РП нет на 1800, набор подписей и data-polities различаются, навигация одна | served 1650 и 1800 по request_id |
| | Одна подпись на QID | web::test_historical_globe_flow + каждый кадр polity_faults | ≤ 1 «Испанская империя», это Spanish Empire; обводка «(Spanish Empire)» — пиксель цвета globe-border; Null West/East подписаны оба | served 1650 |
| | Год внутри интервала | web::test_historical_globe_flow | запросов 0, подписи те же | — |
| | Проигрывание | web::test_playback_one_request_at_a_time | задержка 300 мс: max в пути 1 (fetch и сеть), запросов ≤ интервалов окна, после остановки from ≤ year ≤ to, ошибок 0 | served на каждый ответ |
| | Пустой год на глобусе | web::test_historical_globe_flow | t=−3500 (окно from=−4000): polities 0, borders 0, 0 подписей | served polities=0 |
| | Подписи не перекрывают медальоны и вид (H5) | web::test_polity_labels_no_overlap[3 размера] | 10 кадров на размер (годы 1650/1800, исходный вид, центры (15,50), (30,40), приближения 1/2): пересечений 0, вне кадра 0, ≤ 24; **ДЕФЕКТ D2** data-area | served 1650, 1800 |
| | Медальоны не зависят от режима | web::test_medals_independent_of_mode | персоны и связи (id, x, y, d) равны: артефакт / 503 / без WebGL | served 1650 |
| | Граница на canvas | web::test_historical_globe_flow | пиксель середины восточной стороны РП (lon 32) ≈ globe-border, отличается от суши | — |
| Атрибуция | Подпись на глобусе (H7) | web::test_historical_globe_flow | все строки, ссылки source.url и лицензия, rel noopener, рамка в кадре, без перекрытий | served |
| | Атрибуция из данных | web::test_historical_globe_flow | «v9.9.9-test» на странице, «v0.2.2» в web/dist нет | served |
| | Документация и манифест | build_spec::test_docs_manifest_artifact_agree | | события нет по природе |
| Пределы слоя | Замер на фикстуре | build_spec::test_measure_on_fixture | measure = эндпоинт по polities, ru, bytes, gzip | measured years=3 |
| | инв.: --all-intervals | build_spec::test_measure_all_intervals_max | | measured max_gzip_bytes |
| | инв.: full_sphere ловит неверный обход | build_spec::test_measure_detects_full_sphere | | measured full_sphere=1 |
| | Замер на реальном артефакте | раздел «H1–H9» ниже | | measured years=13 |
| Вид «Глобус» (MOD) | Хронология не грузит глобус | web::test_chronology_no_polities_and_fragment_weight | /map/polities и /map/places нет | served и geo.built нет |
| Политическая карта (MOD) | modern при 503 | web::test_no_artifact_modern | data-map-mode=modern, границы и подписи стран | unavailable missing |
| Пределы глобуса (MOD) | Вес фрагмента | web::test_chronology_no_polities_and_fragment_weight | ≤ 150 КБ без /map/polities, слой запрошен | served |
| Без WebGL и сторонних (MOD) | WebGL недоступен | web::test_medals_independent_of_mode | исторический режим: те же медальоны, связи, подписи, borders > 0 | — |
| | Только свой адрес | web::test_playback_one_request_at_a_time | поворот, наведение, смена года, проигрывание; outside=[] | served на каждый ответ |
| Состояния (MOD) | Слой образований задержан | web::test_polities_delayed | до ответа modern, borders > 0, aria-busy true; после — historical, false | served year=1650 |
| | Ошибка слоя образований | web::test_polities_error_then_ok | 500: modern + пометка, 30 медальонов, ошибок 0; 1800 — historical, пометки нет | served 1800 |
| | Артефакта нет | web::test_no_artifact_modern | modern, текст источника, пометки нет, aria-busy false | unavailable reason=missing |
| Страна места (MOD) | подпись источника в обоих режимах | web::test_historical_globe_flow, web::test_no_artifact_modern | «страны мест — современные» / «Границы и береговая линия — современные» | — |

Сценарии MODIFIED-требований без изменений поведения (Кант, ссылка на глобус, «Границы и подписи», «Пять подписей» и др.) покрыты прежними тестами в режиме 503; они не перезапускались (см. «Не покрыто»).

### Команды и итоги

    pytest -q tests/knowledge/test_polities_build_spec.py              →  22 passed in 14.74s
    pytest -q tests/knowledge/test_polities_layer_spec.py              →  4 failed, 42 passed in 51.32s
        FAILED test_bad_year_non_ascii_digits[١٢٣], [１６５０], [١]   (D1)
        FAILED test_hostile_qids_not_requested                         (D1)
    pytest -q tests/web/test_geo_polities.py -k "not historical_globe_flow"  →  4 failed, 5 passed in 184.36s
        FAILED test_polity_labels_no_overlap[1024-576], [1366-768], [1920-1080] — только D2 (data-area)
        FAILED test_playback_one_request_at_a_time — ошибка теста (hover после поворота), исправлена:
    pytest -q tests/web/test_geo_polities.py -k playback               →  1 passed in 47.49s
    pytest -q tests/web/test_geo_polities.py -k historical_globe_flow  →  1 failed in 25.79s — только D2:
        "смена года: 1650": data-area f2d70aa305a4 (Null East) 23087 vs 22747.9; b3357e03887b (Steppe Horde) 14544 vs 14265.3
    python scripts/check_traceability.py   →  Требований с тестами: 426 из 426
    ruff check tests/ ; ruff format        →  чисто
    lint-imports                           →  Contracts: 3 kept, 0 broken

Браузерные тесты гонялись частями (каждый тест — один-два прогона), полного повторного прогона файла нет по указанию Lead'а (1 CPU). После браузерных мутаций `web/dist` пересобран из чистого `web/src` (`git status` чист).

### Дефекты

- **D1 (низкая) — исправлен в 2451530, тесты зелёные (повтор ниже).** Проверки «год — целое» и «QID — `^Q\d+$`» пропускают не-ASCII цифры: в Python `\d` — любые цифры Юникода.
  - Ожидалось по дельте: `?year=١٢٣` и `?year=１６５０` — 400 `bad_year`; QID «Q１２» не проходит проверку до запроса.
  - Получено: 200 с `year=123` / `year=1650`; «Q１２» уходит в `wbgetentities` (built `qids=2`) и записывается в артефакт как `wikidata`.
  - Где: `polities.py` `YEAR`, `wikidata.py` `QID` (нужен `[0-9]` или `re.ASCII`). Тесты: `test_bad_year_non_ascii_digits`, `test_hostile_qids_not_requested`.
- **D2 (низкая) — исправлен в 2451530 (`POLITY_PRECISION = 0,2` px); тест не менялся, прогон разработчика 10 passed (повтор ниже).** `data-area` подписи образования не равна видимой площади (сверка с d3-geo, precision 0,1, допуск 1 % — как у подписей стран).
  - Получено: расхождение 1–1,5 % у образований с длинными рёбрами, в обе стороны: Null East 23087 / 22748, Steppe Horde 14544 / 14265, a1785f35eeab 24564 / 24821, 100c759fb982 10474 / 10580.
  - Похоже, причина в `COUNTRY_PRECISION = 2` px: площадь считается на грубой передискретизации. Комментарий в коде («расхождение < 0,01 %») верен для плотных контуров стран, а не для редких вершин.
  - На реальном Cliopatria контуры плотнее, так что влияние меньше. Влияет на порог 1500 px² и порядок подписей.
  - Тесты: `test_polity_labels_no_overlap[*]`, `test_historical_globe_flow`. Все прочие проверки этих тестов (H5, R8, интервалы, data-borders, data-span) — без нарушений.
- Наблюдение, не дефект: ссылки подписи источника — `rel="noopener noreferrer"` (дельта: `rel="noopener"`; токен есть).

### Мутации (6.9)

    скрипт: точечная замена → прогон одного теста → git checkout; git diff src пуст после всех
    M1  < вместо ≤ в правиле активности        → test_activity_every_year        упал
    M2  valid_to + 1                           → test_interval_maximal           упал
    M3a кэш отдаёт соседний интервал ±50       → test_activity_every_year        упал
    M3b кэш по году без учёта интервала        → test_cache_by_interval          упал
    M4  пропуск orient                          → test_ring_orientation, hostile  НЕ упали — эквивалентная мутация:
        shapely.set_precision сам нормализует обход (exterior CW); проверено отдельно
    M4c orient(sign=+1) (обратный обход)        → test_ring_orientation           упал
    M4d то же                                   → test_geometry_rules_hostile_input  упал (3 из 3)
    M5  потеря самого большого кольца (min)     → test_tiny_polity_kept           упал
    M6  метка en как запасная                   → test_without_russian_label      упал
    M7  languagefallback=1                      → test_label_batches              упал
    M8  нет сверки SHA-256 в build              → test_checksum_mismatch          упал
    M9  предел года +1                          → test_bad_year                   НЕ упал — эквивалентна: регулярка ^-?\d{1,4}$ уже не пускает 10000
    M9c запрос без year не отклоняется          → test_bad_year                   упал
    M10 снимаются все уточнения заголовка       → test_ruwiki_title               упал
    M11 id зависит от строки                    → test_one_polity_one_id          упал
    M12 предел кэша по байтам не действует      → test_cache_byte_limit           упал
    M13 предел числа интервалов не действует    → test_bounded_cache              упал
    Браузер (одна сборка web с двумя мутациями, затем чистая пересборка):
    B1  PolityStore без проверки inflight       → test_playback_one_request_at_a_time  упал: {'open': 0, 'max': 14, 'total': 71}
    B3  версия датасета константой «v0.2.2»     → test_historical_globe_flow  упал: 'атрибуция': нет 'v9.9.9-test'; 'web/dist': GlobeView-*.js
    Не делались (предел 2–3 браузерных мутации): подпись без проверки [data-geo-overlay], рисование устаревшего ответа.

### H1–H9

| # | Критерий | Доказательство | Результат |
|---|---|---|---|
| H1 | активность 100 % | layer_spec::test_activity_every_year (фикстура, 5601 год); measure на реальном артефакте `inactive=0` (13 лет); ASGI-замер ниже: у всех образований всех 13 лет from ≤ T ≤ to | выполнен |
| H2 | gzip слоя ≤ 512 000 Б | собственный `measure` на пересобранном артефакте (14:13): max 138 836 Б (2000); до пересборки 139 104 Б; разработчик `--all-intervals` (прежняя сборка): 147 926 Б (1919) | выполнен |
| H3 | русские названия ≥ 0,90 | собственный `measure` на пересобранном артефакте: `ru_share` 0,9442 | выполнен |
| H4 | набор меняется по году | web::test_historical_globe_flow (подписи и data-polities 1650 ≠ 1800); layer_spec::test_activity_every_year | выполнен |
| H5 | 0 наложений, в т. ч. 1024×576 | web::test_polity_labels_no_overlap[3 размера × 10 кадров] — пересечений 0; после D2 файл зелёный (прогон разработчика 10 passed) | выполнен |
| H6 | слой ≤ 1 с | ASGI-клиент на пересобранном артефакте, без стенда (указание Lead'а): холодный max 57,2 мс, из кэша ≤ 7,9 мс (прежний прогон: 935,8 мс у первого запроса процесса) | выполнен; браузерный замер не делался |
| H7 | атрибуция видна | web::test_historical_globe_flow («Подпись на глобусе», «Атрибуция из данных»), build_spec::test_docs_manifest_artifact_agree | выполнен |
| H8 | lint-imports, traceability, ruff | 3 kept / 426 из 426 / чисто | выполнен |
| H9 | данные не в git | build_spec::test_data_outside_git | выполнен |

Сырые данные замера на реальном артефакте (тестировщик, этот прогон):

    python -m philograph.knowledge.polities_build measure → exit 0
    {"event": "knowledge.polities.measured", "years": 13, "max_gzip_bytes": 139104, "max_gzip_year": 2000, "ru_share": 0.9442, "inactive": 0, "full_sphere": 0}
    год:      −500  −300    0   400   800  1000  1300  1500  1650  1700  1800   1900   2000
    polities:   47    40   43    51    80   131   150   136   124   111   128     93    191
    ru:         44    39   40    50    77   123   141   131   115   102   115     86    188
    gzip -9: 11749 14132 18836 22631 30301 40271 49171 58256 69536 78646 86795 120264 139104

    H6, ASGI TestClient (build_app + PolityLayer(data/cliopatria/polities.sqlite)), мс холодный / из кэша:
    −500 935.8/12.2  −300 16.1/5.2  0 18.3/6.5  400 22.9/7.8  800 27.0/22.1  1000 20.5/6.2  1300 23.8/4.3
    1500 31.7/11.5  1650 22.7/4.5  1700 21.1/3.9  1800 22.7/4.0  1900 26.9/4.5  2000 29.9/4.4
    served: 26 событий, cached чередуется false/true

Сборка (память, `knowledge.polities.built` полного датасета) — из записи разработчика 8.2 в `progress.md`: maxrss 74 312 КБ (предел 600 МБ), `rows=13246 polities=12869 skipped_relation=377`. Повторно не запускалась: сервер 1 CPU.

### Исключения из проверки журнала

Сценарии «Год внутри интервала», «Граница на canvas», «WebGL недоступен», подпись источника «Страна места» — клиентские: событий нет по дельте, проверяются DOM, пиксели и сетевые запросы.

### Не покрыто

- **8.4 браузерная часть H6** (время от смены года до слоя в браузере на стенде) и **8.5 снимки** пропущены по указанию Lead'а: полный стенд `dev_stack.py` слишком тяжёл для сервера. Стенд был запущен на ~3 мин и остановлен без замеров. H6 доказан ASGI-замером эндпоинта.
- Повторный полный прогон `tests/web/test_geo_polities.py` одним вызовом не делался (тесты прогнаны частями, см. выше). Прежние браузерные файлы глобуса (режим 503) не перезапускались; `knowledge_stack.start` без `polities_env` ведёт себя как раньше.
- Сценарий «Подписи не перекрывают…»: 30 персон в 30 местах, из них 2 места — точно в центрах (15, 50) и (30, 40) вместо двух городов из `CITIES`: так центр вида ставится строкой списка мест.
- «Пустой год на глобусе»: адрес с окном `from=-4000&to=1900`, иначе год −3500 прижимается к окну данных (1600).
- Не-ASCII цифры года: 400 или нет — дельта прямо не говорит. Тест исходит из того, что «целое» — десятичная запись ASCII (D1); если ведущий решит иначе, тест надо снять вместе с правкой дельты.

## Тестировщик — повтор после круга 3 (коммит 2451530), 2026-11-26

Новый сценарий дельты «Вырожденное кольцо» — `build_spec::test_degenerate_ring_becomes_grid_cell` (матрица выше). Мои тест-файлы разработчик не правил (`git diff d9c6672..HEAD -- tests/web tests/knowledge/test_polities_*_spec.py` пуст).

    pytest -q tests/knowledge/test_polities_build_spec.py  →  23 passed in 14.42s
    pytest -q tests/knowledge/test_polities_layer_spec.py  →  46 passed in 50.45s   (D1 закрыт: 4 прежних падения прошли)
    pytest -q tests/knowledge/test_wikidata_unit.py        →  36 passed in 0.21s
    tests/web/test_geo_polities.py — не перезапускался: проверка D2 в тесте не менялась, прогон разработчика после npm run build — 10 passed за 3:43 (progress.md, круг 3)

Мутации нового сценария:

    M14 клетка через round вместо floor           → test_degenerate_ring_becomes_grid_cell  упал
    M15 вырожденный — исходный квадрат без сетки  → test_degenerate_ring_becomes_grid_cell  упал
    git diff src пуст

Замер на пересобранном артефакте (data/cliopatria/polities.sqlite, 14:13):

    measure → exit 0
    {"event": "knowledge.polities.measured", "years": 13, "max_gzip_bytes": 138836, "max_gzip_year": 2000, "ru_share": 0.9442, "inactive": 0, "full_sphere": 0}
    год:      −500  −300    0   400   800  1000  1300  1500  1650  1700  1800   1900   2000
    polities:   47    40   43    51    80   131   150   136   124   111   128     93    191
    ru:         44    39   40    50    77   123   141   131   115   102   115     86    188
    gzip -9: 11749 14120 18836 22631 30286 40254 49157 58241 69519 78630 86795 120264 138836

    H6, ASGI TestClient, мс холодный / из кэша:
    −500 57.2/4.5  −300 14.5/3.6  0 34.3/7.9  400 20.8/3.6  800 17.2/3.9  1000 18.1/4.2  1300 20.1/3.9
    1500 17.0/3.5  1650 19.9/4.7  1700 23.3/4.9  1800 19.2/4.7  1900 18.5/5.3  2000 27.7/5.3
    served: 26 событий; у всех образований всех 13 лет from ≤ T ≤ to (H1)

Итог: H1–H9 выполнены, открытых дефектов нет. Не покрыто по-прежнему: браузерная часть 8.4 и 8.5 (указание Lead'а).

## Судья — 2026-11-26, коммит c14fb70

Проверял по дельте, `tasks.md`, `owner-spec.md` (H1–H9), этому журналу, своим прогонам и выводу работающего сервиса знаний. Перед прогоном коммит тот же, `git status` чист. База `origin/claude/embedding-docker` ушла вперёд (merge-base 2c4c171), на результат это не влияет.

### Свои прогоны (по одному файлу, по указанию Lead'а)

    pytest -q tests/knowledge/test_polities_build_spec.py   → 23 passed in 13.99s
    pytest -q tests/knowledge/test_polities_unit.py         → 40 passed in 2.85s
    pytest -q tests/knowledge/test_wikidata_unit.py         → 36 passed in 0.17s
    pytest -q tests/knowledge/test_polities_layer_spec.py   → 46 passed in 53.86s
    cd web && npm run build                                 → tsc чисто, built; GlobeView gzip 20.65 kB
    pytest -q tests/web/test_geo_units.py                   → 7 passed (unit/geo, в т. ч. polities.test.ts: passed 12, failed 0)
    pytest -q tests/web/test_geo_polities.py                → 10 passed in 216.00s (один прогон, после npm run build)
    pytest -q tests/web/test_geo_political.py               → 32 passed in 612.53s (регресс прежних сценариев «Политической карты» в режиме 503)
    lint-imports                                            → Contracts: 3 kept, 0 broken
    python scripts/check_traceability.py                    → Требований с тестами: 426 из 426
    ruff check . / ruff format --check .                    → 1 ошибка / 2 файла: scripts/dev_stack.py:100, src/philograph/platform/queue.py:168.
                                                              Оба файла из базы, в диффе ветки их нет (git diff merge-base..HEAD пуст); в базе dev_stack уже поправлен (a1df8a4)

Полный `pytest -q` и `dev_stack.py` не запускал (указание Lead'а: 1 CPU / 1,9 ГБ). Полный набор прогонит CI `checks` на PR.

### Вывод системы

Запустил настоящий процесс сервиса знаний: `uvicorn philograph.knowledge.main:app`, `PHILOGRAPH_POLITIES_DB=data/cliopatria/polities.sqlite`, SQLite-база во временном каталоге. Запросы через curl с `X-Request-Id`:

    year=1650  200  0.0198 s  273565 B   served year=1650 polities=124 untranslated=9 valid_from=1648 valid_to=1652 cached=false (judge-1650)
    year=1650  200  0.0038 s             served ... cached=true
    year=1700  200  0.0154 s             served polities=111 1700–1701
    year=1800  200  0.0192 s  343312 B   served polities=128 untranslated=13 1800–1802
    year=-500  200  0.0138 s             served polities=47
    year=2000  200  0.0202 s  484885 B   served polities=191
    year=2100  200                       served polities=0 valid_from=2025 valid_to=9999 — пустой список, не ошибка
    year=abc / пусто / %D9%A1%D9%A2%D9%A3 (١٢٣)  400 bad_year   rejected code=bad_year (judge-abc, judge-, judge-arabic)
    артефакта нет (другой путь)  503 polities_unavailable       unavailable reason=missing (judge-missing)

- 1650: «Священная Римская империя» (Q12548, ru), «Речь Посполитая» (Q172107), «Русское царство», «Республика Соединённых провинций». На 1800 «Речи Посполитой» нет, есть «Российская империя» и «Королевство Пруссия» (H4).
- Блок `source`: Cliopatria, Seshat, Ed Chalstrey и James Bennett, v0.2.2, CC BY 4.0, ссылки https (H7).
- Активность сверил своим SQL по артефакту (`from_year ≤ T ≤ to_year`), года 1650, 1800, −500 и 2000. Набор id совпадает с ответом. На всём `valid_from…valid_to` набор строк постоянный, на `valid_from−1` и `valid_to+1` он другой: интервал наибольший (H1).
- H6: ответ сервиса 4–20 мс по HTTP, это гораздо меньше 1 с.
- `measure` на артефакте (сам, exit 0, 1,0 с, maxrss 44 МБ): `max_gzip_bytes` 138836 (2000), `ru_share` 0,9442, `inactive` 0, `full_sphere` 0. Совпадает с журналом тестировщика по всем 13 годам, по каждому числу polities/ru/gzip (H2, H3).

Наблюдение о качестве данных, а не о коде: у Q3300409 русская метка «история Швеции (1772–1809)» (Kingdom of Sweden, 1800). По правилу дельты это принятая метка `ru`, так что поведение верное.

### Сверка

| Требование | Сценарий / инвариант | Журнал тестировщика | Мой прогон | Вывод системы | Итог |
|---|---|---|---|---|---|
| Сборка исторических границ | 7 сценариев + 10 инвариантов | build_spec 23 passed | 23 passed; мутация M4c повторена | артефакт: координаты ≤ 2 знаков, full_sphere 0 | подтверждено |
| Слой на год | 9 сценариев + 11 инвариантов, H1 | layer_spec 46 passed, served/rejected/unavailable | 46 passed; мутация M1 повторена | 200/400/503 и события served/rejected/unavailable с request_id; SQL-сверка активности | подтверждено |
| Русские названия | 7 сценариев + 5 инвариантов, H3 | layer_spec + web flow | passed | ru_share 0,9442; СРИ, Речь Посполитая по-русски | подтверждено |
| Исторические границы на глобусе | 8 сценариев, H4, H5 (3 размера × 10 кадров) | web 10 passed (разработчик), тестировщик частями | 10 passed одним прогоном | — (браузер, на фикстуре) | подтверждено |
| Атрибуция | 3 сценария, H7 | web flow, build_spec docs | passed | блок `source` в ответе | подтверждено |
| Пределы слоя | замер на фикстуре и реальном артефакте, H2 | measure 138836 / 0,9442 | passed; свой measure — те же числа | — | подтверждено |
| MODIFIED (Вид «Глобус», Политическая карта, Пределы, Без WebGL, Состояния, Страна места) | новые сценарии | web polities | 10 passed; прежние сценарии — test_geo_political 32 passed | 503 → modern (событие unavailable) | подтверждено |
| H8 / H9 | lint, traceability, данные вне git | 3 kept / 426 / test_data_outside_git | то же; ruff по диффу чист | — | подтверждено |

Мутации (повторил сам, код возвращён, `git diff` пуст):
- `orient(sign=+1.0)` в `polities_build.py:327`. Упали `test_ring_orientation`, `test_geometry_rules_hostile_input` и `test_measure_detects_full_sphere`: сферическая площадь 12,5652 > 2π.
- `from_year < ?` вместо `<=` в двух запросах `polities.py`. `test_activity_every_year` упал на году 697 (нет `eb367fed203b`). Сценарные `test_year_1650`, `test_interval_maximal` и `test_merge_rows_same_id` на этой мутации проходят: границу ловит инвариант H1, сценарии её не ловят.

Подгонка: не найдена. В `git diff merge-base..HEAD -- tests openspec` один `skip` («клиент не собран», как в прежних файлах). `except Exception` есть только в тестовом наблюдателе ответов, при разборе тела. Допуски объяснены. Тестов тестировщика разработчик не правил: после d9c6672 коммит 2451530 трогает только `test_polities_unit.py`, это юниты разработчика. Две правки дельты в 2451530 (ASCII-цифры, вырожденное кольцо) делают требования строже. Они записаны в `progress.md` как решения ведущего, тесты им соответствуют. Код круга 3 я прочитал: особых случаев по имени или QID нет, флагов ради тестов нет.

Открытое, но не возврат роли:
- `tasks.md`: 7.1/7.2 не отмечены, хотя ревью сделано (progress.md, «Ревью (задача 7)»). Код круга 3 повторно не ревьюили, я прочитал его сам. 10.1 закрывают мои прогоны выше. 9.2 по плану вынесен в отдельный PR. Ведущему — отметить.
- 8.4 (H6 в браузере на стенде) и 8.5 (снимки и H5 на реальных данных в браузере) пропущены по указанию Lead'а. H6 подтверждён замером работающего сервиса. H5 доказан на фикстуре: 3 размера × 10 кадров, правило раскладки от данных не зависит. Ведущему — записать снятие пунктов как решение Lead'а, вынести их владельцу при приёмке или на сервере мощнее.
- Полный `pytest` не запускался (ограничение сервера). Его прогонит CI `checks` до слияния.

Вердикт: **принято**. Каждый сценарий и инвариант дельты подтверждён и журналом тестировщика, и моим прогоном. Числа H1–H3 и H6 совпадают с выводом работающего сервиса. Подгонки нет. Пункты выше — работа ведущего по `tasks.md`, а не возврат роли.
