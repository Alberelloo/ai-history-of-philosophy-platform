# Progress

## 2026-11-25 — создание изменения (разработчик, субагент `coder`, фаза планирования)

- Ведёт: субагент `coder` (роль разработчика) по заданию ведущего; кода нет, только артефакты OpenSpec. Коммитит ведущий.
- Ветка `claude/reference-catalog` от `origin/claude/embedding-docker` (`ec97eb8` + ТЗ). CLI `openspec` в окружении нет (Node 20) — файлы созданы вручную по образцу `archive/2026-11-18-synchro-map`, `openspec validate` не прогонялся.
- Создано: `proposal.md`, `design.md`, `tasks.md`, дельты `entity-catalog` (новая), `epochs` (новая, одно требование), `visual-design`, `abuse-protection` (MODIFIED, имена требований прежние).
- Изучено до решений: `knowledge/{app,entities,statements,registry,registry_data,map,cards,graph,dates}.py`, `filling.py` (только чтение), `gateway/{app,limits}.py`, `web/src/{App,Sidebar,SoonPage}.tsx`, `web/src/map/{types,model}.ts`, спецификации `ontology-entities`, `entity-cards`, `knowledge-graph`, `ontology-registry`, `ontology-extraction`, `visual-design`, `abuse-protection`, `regional-access`, `scripts/check_traceability.py`.

### Принятые решения (без владельца, альтернативы — в design.md «Выбор решения»)

1. Новый `GET /v1/catalog`; `GET /v1/entities?name=` не меняется (отдельное требование «Прежний поиск по названию»).
2. Данные — из общего снимка в памяти (`knowledge/snapshot.py`, вынесен из `map.py`), индекс справочника на снимок; окно устарелости 15 с только для справочника, карта — без окна.
3. Справочник — не платная операция, только общий лимит частоты.
4. Правило принадлежности к эпохе — `knowledge/epochs.py` и требование в новой возможности `epochs`; явное `belongs_to_epoch` важнее дат (О-8). `relates_to_epoch` не вводится — в реестре есть `belongs_to_epoch`.
5. Пагинация `page`/`limit` (≤ 60), устойчивый порядок по `(ключ, id)`.
6. Закрытый для региона учебник в фильтре «Раздел» → пустой ответ с `textbook_closed`.

### Замечание о прослеживаемости

`scripts/check_traceability.py` требует тест на каждое требование изменений в `openspec/changes/*` для возможностей из `enforce`. Поэтому новое поведение вынесено в новые возможности (`entity-catalog`, `epochs` — в `enforce` попадут в п. 5.1), а для `visual-design` и `abuse-protection` только MODIFIED с прежними именами — существующие маркеры их покрывают, проверка не падает на коммите с одним планом.

### Статус пунктов

- 1.1 — сделан. Остальные — не начаты. Следующий шаг: 1.2 (документы), затем 2.1.

### Окружение

- В `.venv` нет `pyyaml` и прочих зависимостей (`check_traceability.py` падает на `import yaml`): перед реализацией `pip install -e ".[dev]"`.
- e2e и визуальные снимки на машине агента (1 ГБ RAM, 1 CPU) не прогоняются — CI и Lead.

## 2026-11-25 — обсуждение плана ролями

Ветка `claude/geo-timeline` (ведущий разложит по веткам), правки без коммита. Роли прошли субагентами: ревьювер (review-plans.md), тестировщик (tester-plans.md), решения ведущего (lead-decisions.md).

### Замечания ролей (сырые, относящиеся к 2.1)

Ревьювер, желательно:
- «2.1 design: `SectionMap(onto.statements, snapshots=None)`, `main.py` передаёт общий; `PlaceLayer` принимает `Snapshots`.»
- «2.1 память: 10× ≈ 7 тыс. сущностей (не «70 тыс.»); в 4.8 замер памяти (пик tracemalloc, два снимка одновременно); `EpochMembership` и `CatalogIndex` один раз на отпечаток, счётчики `/v1/epochs` из того же кэша.»
- «2.1 п. 5.1: `epochs` в `enforce` только в 2.2.»
- «2.1/2.2: принадлежность использует те же `_start`/`_end` (с `round`), что карта, через общий модуль.»
- «Безопасность и память: кэши `/map` и `/map/places` растут без предела (ключ — произвольный `textbook`) → LRU или проверка учебника; `/map?only_textbook` раскрывает охват закрытого учебника (существующая проблема, задача regional-access)»
- Вердикты: «15 с — да, ManualClock — да, часы в `Snapshots`. Память при 10× приемлема, замерить. `textbook_closed` — да. Фасеты «без своего фильтра» — да. `epochs` в 2.1 — да, в `enforce` в 2.2.»

Тестировщик, сквозное:
- «1. tests/web не имеет сервиса знаний (conftest поднимает библиотеку+шлюз; карта через fixture/page.route). THEN в «Найти и открыть», «Показать ещё», «Ничего не найдено», «Старая закладка» … требуют серверных событий … с page.route ненаблюдаемы, проверять заглушку = тавтология. (а) фикстура tests/web с настоящим приложением знаний в потоке (SQLite), или (б) передача в e2e. Рекомендую (а).»
- «2. Ожидания завязаны на `seed_demo`; тесты должны задавать данные сами; page.route — для крайних случаев»
- «3. Нет инварианта XSS в названиях и запросе» · «4. Нет инварианта «в событиях нет личных данных и текста запроса» для `catalog.rejected`…» · «6. «Разделы в разработке» меняется тремя изменениями — обновлять тест на каждой ступени.» · «7. `page.clock` годится (debounce 250 мс …), если код на rAF/performance.now/setTimeout, не `Date`.» · «8. Исключения журнала для интерфейсных THEN — перечислить в verification.md»

Тестировщик, add-reference-catalog:
- «статусы `snapshot` (fresh/cached/stale) неоднозначны — таблица; синтаксис `type` с несколькими кодами, `facets.types` по точному коду, сумма = total — сценарий; форма `facets.epochs`, пустые `facets` при закрытом учебнике; `reason` для page<1, неизвестной sort, неизвестного учебника; страница за концом, q 200/201, limit 60/61, page=0 — параметризованный сценарий; sort=relevance без q; «описание без цитат» — наблюдаемо (уникальная фраза абзаца не входит); фильтр «Раздел» через утверждение, подтверждённое абзацем учебника — нет сценария; как передаётся регион; debounce и гонка ответов — инвариант; округление середины, персона без даты смерти, «без эпохи», статусы «отклонённые/отвергнутые», «эпоха не относится к себе», группы — только явная.»
- Мутации: «catalog — ранжирование, debounce, `textbook_closed` для facets, статус `snapshot`; epochs — округление середины, `[from,to)`, предпочтённая датировка»

### Решения ведущего

Р1 (фикстура tests/web с настоящим приложением знаний — задача здесь, тестировщик до Opus), Р2 (XSS, события без текста запроса и личных данных, нет `pageerror`), Р3 (таймеры клиента через setTimeout/performance.now и `page.clock`, сервер — ManualClock), Р4 (исключения журнала одной фразой в спецификации), Р5 (точные THEN, перечни `reason` в спецификации), Р6 (`epochs` в `enforce` в 2.2), Р8 (одна функция начала/конца/середины), Р10 (LRU кэшей; утечка через `only_textbook` — отдельной задачей). По 2.1 — все пункты раздела «add-reference-catalog (2.1)» lead-decisions.md.

### Что изменено

1. `specs/entity-catalog/spec.md`: таблица статусов свежести (`fresh`/`cached`/`stale`, сценарии t+5 и t+16); `type` — повтором параметра; `facets.types` по точному коду с суммой = `total`; форма `facets.epochs` `[{id,label,count}]`; пустые `facets` при `textbook_closed`; новое требование «Проверка параметров справочника» с таблицей `kind`/`reason` и параметризованным сценарием границ (q 200/201, limit 60/61, page 0, страница за концом, неизвестные sort/type/epoch/textbook, relevance без q → label); «описание без цитат» — через уникальную фразу; сценарий «Раздел через подтверждение абзацем»; регион — заголовок `X-Philograph-Region`; сценарии debounce и «Устаревший ответ»; новое требование «Безопасный вывод справочника» (XSS, нет `pageerror`); `q` в журнал не пишется — только `q_len`; фраза Р4.
2. `specs/epochs/spec.md`: общая функция границ с округлением, середина без округления, `[начало, конец)`, «устаревшее» исключено, группы/идеи и персоны без дат — только явно; сценарии «Округление нечёткой границы», «Без датировки и группы»; пометка, что `epochs` в `enforce` с 2.2.
3. `specs/abuse-protection/spec.md`: точный сценарий «Справочник не тратит квоту».
4. `specs/visual-design/spec.md`: фраза Р4 в «Старой закладке справочника».
5. `design.md`: `SectionMap(statements, settings=None, snapshots=None)`, LRU 32 для кэша карты, `Snapshots(engine, clock)`, `dates.span`/`dates.middle`, память 10× ≈ 7 тыс. сущностей (пик — два снимка), раздел «Тестируемость», безопасность (вывод текстом, события только id/коды/числа, утечка охвата — вне объёма).
6. `tasks.md`: 2.0 (`dates.span`/`middle`), 4.0 фикстура `tests/web` с настоящим приложением знаний (переиспользуют 2.2–2.4), тестировщик — Opus, замер tracemalloc, перенос `epochs` в `enforce` в 2.2, пункт «Вне объёма» regional-access; `proposal.md` — то же кратко.

### Не принято

- Предел `q`: в первой версии плана было 100 символов; принят перечень тестировщика (200/201). Отклонений от решений ведущего нет.
- Синтаксис `type` через запятую не выбран: повтор параметра — штатная форма FastAPI (`list[str] = Query()`), без своего разбора строки (ведущий оставил выбор за разработчиком).
- Утечка охвата закрытого учебника через `/map?only_textbook` не чинится здесь (Р10): отдельная задача regional-access.

## 2026-11-25 — второй круг ревью плана (ревьювер), ведущий

Вердикт ревьювера: «можно к коду» по всем четырём изменениям стека; блокирующие 1–7 первого круга закрыты. Сырой отчёт:

> # Ревью планов, круг 2 (ревьювер) — 2026-11-25, коммит d22c131 (ветка claude/geo-timeline)
> 
> **Можно к коду:** add-reference-catalog — да; add-epochs — да; add-epoch-context — да; add-geo-timeline — да. Правки ниже мелкие, первым пунктом реализации.
> 
> **Блокирующие 1–7 первого круга закрыты по существу** (по артефактам и запуском):
> 1. Прослеживаемость: `check_traceability.py` на d22c131, 42d1cc4, 2f97fc5, ca3608b, 088fe23, 45f4fba, 8348210, d35bd66 — «356 из 356», код 0. Код 1 — на промежуточных 277ccae и 936c46b (вторая ветка слияния d22c131, при squash в main не попадает).
> 2. Объединение `qualifiers` в `_add_missing_defaults`: требование и сценарий «Заполненный реестр» (spec 2.4), задача 2.1 с тестом, мутация. registry.py:120 сейчас перебирает только `subject_types/object_types/values`.
> 3. «Жил в» без вида: правило 3 spec 2.4, сценарии «Только без вида», «Юм без вида места».
> 4. `knowledge/wikidata.py` описан в design 2.2 (стр. 28–70); 2.3 и 2.4 пользуются только им.
> 5. Код раздела карточки эпохи — `dating`.
> 6. Основная датировка — «предпочтённая, иначе первая записанная» (= `_update_primary`).
> 7. Субъект `stimulated` в 2.3 — «Выход „Начал“ Ньютона» 1687, при `[from, to)` — Просвещение (1680–1800).
> 
> **«Не принято» согласно с решениями ведущего.** Противоречий по существу нет. Устаревшие ссылки поправить до реализации:
> 1. `add-epochs/design.md:69`: `partial(http_fetch, clock=SystemClock())` противоречит сигнатуре (стр. 42, ожидание через `wait`) → `partial(http_fetch)` или `partial(http_fetch, wait=time.sleep)`.
> 2. `add-geo-timeline/design.md:12`: «имена в design.md 2.2 ещё не обновлены» → «сверено».
> 3. `add-epoch-context/tasks.md:3`: `epoch_dates.wikidata_time`/`http_fetch` → `knowledge/wikidata.py`; `design.md:85` `fetch_entity(qid)` → `fetch_entity(qid, fetch)`; для P585 — `claim_date` без interval.
> 4. `add-epochs/design.md:3`: «2.4 использует через HTTP» → 2.4 импортирует `wikidata.py` и `eraOf`.
> 5. `add-reference-catalog/proposal.md:59`: «~70 тыс. записей» → ≈7 тыс.
> 
> **Желательно (design 2.4):** `StatementError.code` теряется при перевыбросе в `Statements.add` (statements.py:206–208) — сохранять код исходного исключения; отказ по `geo` при нормализации до `_key` вне `try` вокруг `_check` — перенести внутрь `try`, чтобы на каждый отказ было одно `knowledge.statement.refused`; место ищется по внешнему id `wikidata` и только потом создаётся (не задваивать места 2.3).
> 
> Выбор решения: соответствует. Подгонка: не найдена (кода нет).

Ведущий: устаревшие ссылки 1–5 исправлены мелкой правкой без цикла (здесь — proposal.md: «~70 тыс.» → «≈7 тыс.»). Пожелания по design 2.4 переданы разработчику 2.4 первым пунктом реализации.

## 2026-11-25 — реализация (разработчик)

- **1.2** system-design.md: сервис знаний — карта раздела и справочник, снимок в памяти; поток «Справочник» (снимок, окно устарелости, epochs.py, textbook_closed). ontology.md О-8: ссылка на требование «Принадлежность к эпохе» возможности epochs. Отличий от дизайна нет.

- **2.0** `dates.span`/`dates.middle` в `knowledge/dates.py` (принимают JSON датировки и `FuzzyDate`); `map._start`/`_end` вызывают `span`. Юнит-тесты `tests/knowledge/test_dates_span.py` (округление .5 к чётному, до н. э., середина без округления); `test_map.py`, `test_map_view.py` зелёные без правок. Заметка: `round` — банковское округление (как было на карте): 1680,5 → 1680, −449,5 → −450; спецификация называет только пример 1679,5 → 1680, ему это соответствует. `ruff format --check .` сообщает о двух файлах Lead'а (`platform/queue.py`, `prompts/__init__.py`) — не трогаю.

- **2.1** `knowledge/snapshot.py`: `fingerprint(engine)` и `load(...)` — перенос `SectionMap._fingerprint`/`_load` без изменения правил; в снимок дополнительно читаются упоминания по источникам (`mentions`) и внешние id `library` (`library`: источник → сущность-источник) — для фильтра «Раздел» и проверки `unknown_textbook`; таблицы `mentions`/`entities` уже входят в отпечаток. `Snapshots(engine, clock).get(max_stale)` → `(snapshot, fresh|cached|stale)`; пересборка под `threading.Lock` с повторной проверкой отпечатка после ожидания; событие `knowledge.snapshot.built` (`entities`, `statements`, `took_ms` по `perf_counter`, `reason`). Производные снимка (`Snapshot.derived(key, build)`) строятся один раз на снимок — так индекс справочника и принадлежность к эпохам живут только для текущего снимка. Юнит-тесты `tests/knowledge/test_snapshot.py` (6): first/cached, stale в окне и fresh на границе окна (возраст = окну → пересборка), окно 0, правила загрузки (слитые, отклонённые), derived, две параллельные пересборки → одна. Карта переходит на снимок в 2.2.

- **2.2** `SectionMap(statements, settings=None, snapshots=None)` берёт `snapshots.get(max_stale=0)`; `_fingerprint`/`_load`/`_textbook_entities` из `map.py` удалены (область учебника — `snapshot.mentions`, то же множество, что прежний запрос к `mentions`). Кэш ответов — `OrderedDict` LRU на `CACHE_KEYS=32` под блокировкой; ключ кэша и поле `cached` события `knowledge.map.built` — прежние. `main.py`: один `Snapshots(engine)` на процесс, в `Components.snapshots`. Проверки: `tests/knowledge/test_map.py` и `test_map_view.py` — 19 passed без правок; `tests/assistant/test_map_chain.py` зелёный. Новый `tests/knowledge/test_map_snapshot_parity.py`: эталон `fixtures/map/demo_map.json` записан кодом карты ДО перехода на снимок (`git stash` правки `map.py`, `PHILOGRAPH_WRITE_MAP_GOLDEN=1`) на данных `seed_core`+`seed_map` из `scripts/seed_demo.py` плюс упоминание в учебнике, ответы `/v1/map` (все, `textbook`, `only_textbook`) совпадают после рефакторинга; id детерминированы подменой `uuid4` в тесте. Юнит-тесты: 33-й учебник вытесняет самый давний ключ, карта берёт общий снимок без окна.

- **2.3** `knowledge/epochs.py`: `EpochMembership(snapshot, registry)` с `of`, `members`, `epochs` (порядок: начало датировки, без даты в конце, название, id), `span`; `membership(snapshot, registry)` — одна на снимок через `Snapshot.derived`. Явное — `belongs_to_epoch` и подтипы по реестру, самоотнесение эпохи отбрасывается; по датам — типы `person`/`work`/`event`(с `idea_event`)/`phenomenon` через `registry.is_a`, `dates.middle` в `[span)`. Даты сущности — `primary.dates`, как на карте. Юнит-тесты `tests/knowledge/test_epochs_unit.py` (8): середина жизни, явное важнее дат, отклонённое и «устаревшее» не действуют, пересечение и полуинтервал, округление нечёткой границы, без дат/группы/идеи/термин/эпоха — только явно, несколько явных с порядком, вывод не пишет утверждений.

- **2.4** `knowledge/catalog.py`: `CatalogIndex` на снимок (одна на снимок через `Snapshot.derived`; блокировка производных — `RLock`, т. к. индекс строит принадлежность к эпохам внутри своего производного): записи без типа `source` и его подтипов; датировка `dates.span` + `precision`/`original`; значимость — число действующих утверждений субъектом или объектом; описание — лучшее действующее `description` (предпочтённое, затем по силе статуса), 200 знаков по слову с «…», `generated` по статусу; эпохи — `EpochMembership.of`; источники раздела — упоминания + атрибуции `who_kind=source` не скрытые + подтверждения не потерянные (как `Statements._attributed`). «Известный онтологии учебник» = упомянутый, атрибутированный, подтверждающий или имеющий сущность-источник (`external_ids.library`) — это моё уточнение формулировки спецификации. `Catalog.list`: проверка параметров в одном месте (`CatalogRejected(kind, reason)` по таблице требования; `page`/`limit` принимаются строкой, чтобы «не число» давало 400 `bad_query`, а не 422 FastAPI), событие `knowledge.catalog.rejected` (только `reason`) / `knowledge.catalog.listed` (поля спецификации). Регион (`closed`) запрашивается лениво — только при фильтре `textbook`. Ранжирование 0/1/2, `matched_name` — если лучший ранг дал не основное название; сортировки с `id` последним ключом; `lang` — основное название на языке, иначе русское, затем любое; неизвестный `lang` не ошибка (в таблице отказов его нет). Юнит-тесты `tests/knowledge/test_catalog_unit.py` (27).

- **2.5** `app.py`: `build_app(..., catalog=None)`, `GET /v1/catalog` (`type` — `list[str]` с `alias="type"`, повтор параметра; `page`/`limit` строкой), `CatalogRejected` → `UserFacingError` 400 с `kind`; регион — `region_closed(request)` лениво, только при `textbook` (недоступная библиотека → 503 `knowledge_unavailable`, без раздела — 200). `main.py`: `Catalog(snapshots, registry, entities, CatalogSettings(PHILOGRAPH_CATALOG_MAX_STALE_SECONDS, 15))` на том же `Snapshots`, что карта (проверено сборкой `components`: `section_map.snapshots is catalog.snapshots`). Шлюз не менялся: `/api/knowledge/v1/catalog` не входит в `PAID` (limits.py), только общий лимит частоты. `docs/operations/runbook.md` — переменная окна. Юнит-тесты маршрута `tests/knowledge/test_catalog_route.py` (7): повтор `type`, 400 по `kind`, заголовок региона уходит в `/internal/access`, закрытый учебник, 503 библиотеки, прежний `/v1/entities?name=`.

- **2.6** `scripts/seed_demo.py`: `seed_reference` (запускается, если нет «Кёнигсберг», — поэтому дописывается и в уже засеянную базу): вариант `en` «Kant» у Канта, `belongs_to_epoch` Локк → Просвещение (`membership_basis=historians`; по датам Локк — «Научная революция», так видно «явное важнее дат»), термин «Эпистемология», место «Кёнигсберг». Названия проверены по `demo/textbook.html` и `demo/primary_en.txt` — не встречаются (новых упоминаний нет; «tabula rasa» отброшено — в учебнике есть якорь `tabula-rasa`). Проверка скриптом (в scratchpad, не в репозитории) на данных `seed_core`+`seed_map`: карточки Канта и Юма (без поля `names`, которое клиент не выводит) и их `about` до и после `seed_reference` совпадают; `q=kant` → Кант с `matched_name="Kant"`; Локк — Просвещение `explicit`. Тесты `tests/web` демо-данные не читают (grep `seed_demo` — только e2e и `test_dev_stack`), поэтому браузерный прогон чтения здесь не запускал (1 ГБ RAM); e2e/визуальные снимки чтения — за CI и Lead. Отличие от задачи: поле `names` в JSON карточки Канта получает «Kant» — на экране не видно.

- **3.1** `web/src/reference/types.ts` (`TYPE_GROUPS` из `groups.json`, `groupCount`, `onMap`, типы ответа, `readState`/`writeState` адреса), `reference/api.ts` (`fetchCatalog` с `AbortSignal`, ошибка — `CatalogError(kind, status)`, нет ответа/не JSON — `kind=unavailable`, отмена пробрасывается как `AbortError`). Отличие от дизайна: группы — JSON с точными кодами, `events` = [event, idea_event, phenomenon] — потому что `facets.types` приходят по точному коду и счётчик группы иначе потерял бы идейные события; сервер подтипы включает и сам, повтор `type=idea_event` безвреден. Сверка с реестром — `tests/knowledge/test_reference_groups.py` (Python читает тот же JSON; без браузера). `tsc --noEmit` без ошибок.

- **3.2** `web/src/reference/ReferencePage.tsx`: состояние из адреса (`readState`), ввод — `setTimeout` 250 мс → `replaceState`, смена группы/эпохи/раздела/сортировки — сразу и `pushState`; «Назад/Вперёд» — собственный слушатель `popstate` (App не видит `pushState` без события, поэтому страница читает `window.location` сама). Запрос: `AbortController` для предыдущего и номер запроса — поздний ответ отбрасывается. «Показать ещё» — следующая страница, повторы по `id` убираются, фокус на первую новую запись. Выбор записи — `openCardInPanel` (тот же `OPEN_CARD_EVENT`), запись подсвечена; «На карте» — `navigate('/graph/<id>')` для типов карты. Список учебников раздела — `api.sources({kinds:[textbook]})`, закрытые для региона видны с пометкой. Таймеров на `Date` нет (grep). Пункт 3.3 сделан в том же файле, отметка — следующим коммитом.

- **3.3** Состояния в `ReferencePage.tsx`: загрузка (6 заполнителей при первом запросе, `aria-busy` у списка, счётчики «…»), онтология пуста (`total=0` без фильтров — сообщение и «К библиотеке», счётчиков нет), ничего не найдено (сообщение с запросом / «в этой группе…» и «Сбросить фильтры» → `/reference`), ошибка (`pg-notice--warning`, «Повторить», показанные записи остаются), учебник закрыт («Все источники»). `unknown_epoch`/`unknown_textbook` от сервера (например, `epoch=<script>` из адреса) — фильтр снимается `replaceState`, пояснение и список без фильтра. Вывод — только текстовые узлы React (нет `dangerouslySetInnerHTML`), ошибки сети/JSON ловятся в `fetchCatalog`, отмена молча; `console.*` нет. Клавиатура: «/» (кроме полей ввода), Esc в поиске — очистка сразу, ↓ из поиска — первая запись, ↑/↓ — roving tabindex (↑ с первой — в поиск), Enter — карточка, Shift+Enter — «На карте». Группы — `role=group` с подписью, `aria-pressed`; эпоха/раздел/сортировка — нативные `select` с подписями; «Найдено: N» — `aria-live=polite`, текст пуст во время загрузки. Доступное имя записи — «название, тип, даты». Отличие: кнопка «На карте» с `tabIndex=-1` (вторичное действие в roving-списке; с клавиатуры — Shift+Enter), если тестировщик/ревьювер сочтёт это нарушением доступности — вернуть в порядок Tab.

- **3.4** `App.tsx`: маршрут `/reference` (`ReferencePage search=…`), `/soon/reference` → `replaceState('/reference')` (как у графа и ассистента), `activeItem` → `reference`. `Sidebar.tsx`: `LIVE.reference = '/reference'` — метка «скоро» снята. `styles/reference.css` (подключён в `main.tsx`): только токены (`var(--…)`), без литералов цвета; на ≤1279px подзаголовок скрыт, ряд групп — одна строка с собственной горизонтальной прокруткой и кнопками ‹ ›, описание — одна строка, подпись «На карте» — только стрелка; `prefers-reduced-motion` — без пульсации заполнителей. Иконок шеврона/стрелки в `ui.tsx` нет — использованы символы ‹ › → в `aria-hidden`. `npm run build` — ✓ built. Визуально в браузере не проверял: на машине агента kitesurf/Chromium с продуктом не поднимал (1 ГБ RAM); раскладку 1024×576 и 1920×1080 проверяет тест 4.5 тестировщика.

- **3.5** Раздел `reference` в `i18n/ru.ts` и `i18n/en.ts` (тексты из таблиц дизайна: заголовок, подзаголовок, поиск, «Найдено», группы, эпоха/раздел/сортировка, состояния, «Показать ещё», «Показаны все», доступное имя записи, пояснения к снятому фильтру `unknown_epoch`/`unknown_textbook`). Пометка «сгенерировано» — общий `t.status.generated` через `StatusMark`, как в карточке (отдельного ключа `reference.generated` не заводил). EN типизирован `Catalog = typeof ru` — `tsc --noEmit` без ошибок. Сверка групп с реестром — `tests/knowledge/test_reference_groups.py` (сделана в 3.1): 1 passed.

- **3.6** `cd web && npm run build` (tsc + vite) — ✓ built in 4.22s. Перед передачей: `ruff check .` — 1 ошибка E501 в `scripts/dev_stack.py:100` (файл Lead'а, не менялся); `ruff format --check .` — 3 файла Lead'а (`scripts/dev_stack.py`, `platform/queue.py`, `prompts/__init__.py`) — не менялись, `git diff origin/claude/embedding-docker` по ним пуст; мои файлы чистые. `lint-imports` — Contracts: 3 kept, 0 broken. `check_traceability.py` — 356 из 356 (`entity-catalog` в `enforce` — задача 5.1). `pytest -q tests/knowledge` — 233 passed, 1 skipped (116 с); `pytest -q tests/gateway tests/assistant/test_map_chain.py` — 42 passed. `tests/web` и e2e не запускал (1 ГБ RAM; задачи 4.x тестировщика). Известное, требующее обновления тестировщиком: тест навигации, ожидающий метку «скоро» у «Справочника» (4.5).

## 2026-11-25 — ведущий: итог круга разработчика, передача тестировщику

- Разработчик закрыл 1.2, 2.0–2.6, 3.1–3.6 (коммиты 47cea50…52d473d). Его отличия от дизайна (раздел выше) ведущий принимает: группы типов в `groups.json` по точным кодам; «известный онтологии учебник» — уточнение разработчика, проверит ревьювер на соответствие спецификации; неизвестный `lang` — русское название; `RLock` в снимке; банковское `round`, как было на карте. Кнопка «На карте» вне порядка Tab — передано ревьюверу на оценку по требованию «Клавиатура и доступность справочника».
- `ruff format --check .` падает на трёх файлах Lead'а (`scripts/dev_stack.py`, `platform/queue.py`, `prompts/__init__.py`) — так в базовой ветке `claude/embedding-docker`, дифф с базой по ним пуст; не чиним (файлы Lead'а), фиксируем как ограничение базы.
- Тестировщик запущен на модели Opus (не Sonnet): ему нужна новая тестовая инфраструктура `tests/web` с настоящим приложением знаний (решение ведущего Р1, working-principles, раздел 4).

## 2026-11-25 — тестировщик (Opus)

- **4.1–4.2** `tests/knowledge/test_catalog.py` (через HTTP-маршрут `/v1/catalog`, фикстура `svc` = `CatalogService` в `tests/knowledge/conftest.py`: поддельная библиотека закрывает «Учебник R» вне `RU`, поддельный шлюз моделей отвечает 503 и записывает вызовы; построитель данных `tests/knowledge/world.py`). Сценарии всех требований сервиса + инварианты. Дефект: `test_ties_broken_by_id[date-*]`, `[weight-*]` — при равном ключе `date`/`weight` порядок по названию, а не по идентификатору (спецификация: «при равенстве ключа сортировки — по идентификатору»); устойчивость и непересечение страниц держатся.
- **4.3** `tests/knowledge/test_epochs_membership.py` — принадлежность к эпохе через поле `epochs` и фильтр `epoch` справочника, пролёт — через `/v1/map`. Все зелёные.
- **4.4** `tests/gateway/test_reference_limits.py` — настоящий шлюз + настоящее приложение знаний (`HostRouter` в `tests/helpers.py`). Все зелёные.
- **4.0** `tests/web/knowledge_stack.py` + фикстуры `knowledge_stack`, `knowledge_context` в `tests/web/conftest.py`: шлюз (раздаёт `web/dist`) → `HostRouter` → настоящие библиотека (учебники N — открыт, R — только РФ) и сервис знаний (SQLite, справочник, карта, карточки) в потоке процесса; данные — `stack.world` (`tests/knowledge/world.py`). Ловушки в конце теста: запросы шлюза к неизвестному хосту, вызовы модели (`http://llm` → 503 и запись), запросы браузера не к стенду. `console.error` ловится обёрткой в init-скрипте (сообщения браузера о статусе ответа — не вызов `console.error`), `pageerror` — событием. Событие запроса страницы — по `X-Request-Id` ответа.
- **4.5** `tests/web/test_reference.py` (30 тестов) — все зелёные. Навигация: `tests/e2e/test_visual_design.py::test_future_sections_marked_and_described` — «Справочник» перенесён из «скоро» в реализованные (e2e не прогонялся: 1 ГБ RAM). Замечания: подпись пометки — «Сгенерировано» (общий `StatusMark`, как в карточке), спецификация цитирует строчными; гонка ответов — страница отменяет устаревший запрос (`ERR_ABORTED`), поэтому поздний ответ до страницы не доходит и проверка по номеру запроса браузером не изолируется.
