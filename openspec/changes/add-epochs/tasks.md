# Tasks

Второе в стеке: начинается после `add-reference-catalog` (нужны `knowledge/snapshot.py`, `knowledge/epochs.py`, `GET /v1/catalog`). Ветка — `claude/epochs` от ветки или слияния `add-reference-catalog`. После каждого пункта: отметка, `progress.md`, коммит `wip(add-epochs): …`, push.

## 1. Задача и документы

- [x] 1.1 Изменение OpenSpec: `proposal.md`, `design.md`, `tasks.md`, дельты `epochs`, `knowledge-graph`, `entity-cards`, `visual-design`, `progress.md`
- [x] 1.2 `docs/product/ontology.md` — эпоха: датировка из Wikidata, ядро эпох в `sources/epochs.yaml`; `docs/product/system-design.md` — команда оператора `epoch_dates`; `sources/README` (если есть) — манифест эпох

## 2. Даты и Wikidata

- [x] 2.1 `dates.py`: `interval(start, end)`. **Общий модуль `knowledge/wikidata.py`** (интерфейс — design.md): `check_qid`, `page_url`, `http_fetch` (`User-Agent` без личных данных, таймаут, `Retry-After` ≤ 30 с, ≤ 3 повторов, внедряемое `wait`), `fetch_entity`, `search`, `WikidataRecord.best/items` (ранги), `wikidata_time` (11…6, эра, `+0000`, мусор), `claim_date`, `format_original`; формат дат — `FuzzyDate.to_json` (юнит-тесты на каждую точность, ранги, 429, неверный QID). 2.3 и 2.4 переиспользуют его, своего httpx и разбора времени не пишут
- [x] 2.2 `entities.py`: `add_external(entity_id, system, value)` с `DuplicateEntity` (юнит-тест)
- [x] 2.3 `knowledge/epoch_dates.py` поверх `wikidata.py`: `epoch_dating` (P580/P582, запасные P571/P576), `EpochDates.apply` (манифест + `--linked`, сопоставление и заведение эпох, `added`/`created`/`unchanged`/`conflict`/`no_dates`/`no_qid`/`fetch_failed`/`ambiguous`/`duplicate_qid`, `skipped` и равенство `checked = added + created + conflicts + skipped`, `--dry-run` без записи, идемпотентность повторного запуска), отчёт JSON, события `knowledge.epoch_dates.checked`/`run`
- [x] 2.4 `suggest`: поиск кандидатов, отбор по `PERIOD_CLASSES` и датам, объединение кандидатов по `qid` при повторе, поля человека не трогаются, запись в манифест без `wikidata`, событие `knowledge.epoch_dates.suggested`
- [x] 2.5 CLI `python -m philograph.knowledge.epoch_dates suggest|apply [--linked] [--dry-run]`; сеть — только `wikidata.http_fetch`
- [x] 2.6 `sources/epochs.yaml` — эпохи раздела RU/EN с `wikidata: null` (QID не выдумываются); проверка манифеста (повтор `ru`, шаблон QID) до обращения к базе и сети
- [x] 2.7 Фикстуры ответов Wikidata `tests/knowledge/fixtures/wikidata/*.json` (`wbgetentities`, `wbsearchentities`) — офлайн

## 3. Сервис знаний

- [x] 3.1 `epochs.py`: список эпох (пролёт через `dates.span`, `fuzzy`, предел 500 и `truncated`, точность, источник датировки, Wikidata, описание, счётчики по видам), `undated`
- [x] 3.2 Маршрут `GET /v1/epochs`, событие `knowledge.epochs.listed`
- [ ] 3.3 `map.py`: `epochs` у персон, трудов/идей, событий; `fuzzy` у эпох (прежние тесты карты без правок; поля `knowledge.map.built` не меняются)
- [ ] 3.4 `cards.py`: разделы эпохи с кодами `dating` («Датировка») и `members` («Относятся к эпохе»); заголовки — в `ontology.{ru,en}.json`
- [ ] 3.5 Демо: в `scripts/seed_demo.py` — эпоха без датировки с явным участником, явная принадлежность Локка к Просвещению, датировка с нечётким концом у «Научной революции»; эталоны чтения не меняются

## 4. Клиент

- [ ] 4.1 Карта: `types.ts` (`epochs`, `fuzzy`, `Filter.epochs`, адрес `epochs`), `model.ts` (фильтр — идеи без явной эпохи скрываются; выбор эпохи по `epochs`; удалить `midLife` в `related` для эпохи; `eraOf` остаётся для эпохи года с правилом «самое позднее начало, затем название»), `MapPanel.tsx` (фасет «Эпоха», окно по пролёту, если в адресе нет `from`/`to`; без датированных — без пункта), `MapCanvas.tsx`/`layout.ts` (растушёвка только в страте эпох, `data-fuzzy-start/end`, `data-selected-era`; линии жизни, узлы, `anchorOn` не трогаются), `packIntervals` вынесен из `packPeople`
- [ ] 4.2 `web/src/epochs/{EpochsPage,Timeline,api}.tsx/ts`: лента, дорожки, растушёвка, описание выбранной (счётчики, персоны, труды, события через `/v1/catalog`), до 8 персон и до 8 трудов, до 20 событий, действия, `/epochs/<id>`, ссылка Wikidata из проверенного QID, состояния, клавиатура (края без перехода по кругу, Home/End, Esc), `data-lane`, `data-fuzzy-start/end`; вывод текстом, без `pageerror`
- [ ] 4.3 `App.tsx` (маршруты, `/soon/epochs` → `/epochs`), `Sidebar.tsx` (`LIVE.epochs`, подпись «Эпохи»), `ReferencePage` — эпоха в записи ссылкой на `/epochs/<id>`; строки RU/EN; стили `styles/epochs.css`
- [ ] 4.4 `cd web && npm run build`

## 5. Задачи тестировщика

- [ ] 5.0 `tests/knowledge/test_wikidata.py` — «Доступ к Wikidata»: параметризованный разбор времени по таблице сценария, ранги, 429/`Retry-After` через `httpx.MockTransport` и внедрённое `wait`, неверный QID — 0 запросов, `User-Agent` без личных данных
- [ ] 5.1 `tests/knowledge/test_epoch_dates.py` — сценарные и нормативные на «Датировка эпохи», «Даты эпох из Wikidata» (каждый `result` таблицы, `skipped`, запасные P571/P576, повторный запуск), «Подбор записи Wikidata», «Ядро эпох»: вывод (утверждения, атрибуция, отчёт) и события; функция загрузки — фикстуры, сеть запрещена (фикстура, падающая при обращении к `httpx`)
- [ ] 5.2 Нормативные: существующая датировка никогда не перезаписывается; `--dry-run` не меняет ни одной таблицы (сравнение счётчиков всех таблиц); `suggest` не пишет в базу и не заполняет `wikidata`; связи влияния (P737) не импортируются; без QID — ни одного вызова `fetch`; повторный `apply` не создаёт строк; события `knowledge.epoch_dates.*` и `knowledge.epochs.listed` содержат только id, коды и числа
- [ ] 5.3 `tests/knowledge/test_epochs_list.py` — «Список эпох»: порядок, `undated`, `counts` совпадают со справочником (`/v1/catalog?epoch=&type=`), источник датировки, событие
- [ ] 5.4 `tests/knowledge/test_map.py` — новые сценарии «Нечёткая граница эпохи», «Эпохи в ответе карты»; `tests/knowledge/test_mentions_cards.py` — «Карточка эпохи» (вывод по датам строкой не показан)
- [ ] 5.5 `tests/web/test_map.py` на фикстуре с настоящим приложением знаний (из 2.1; данные задаёт тест, противоречащие эпохи — данными, а не `page.route`) — «Явная эпоха на карте», «Эпоха года при перекрытии», «Нечёткая граница эпохи» (`data-fuzzy-*`), «Фильтр «Эпоха»», «Окно из адреса важнее», «Неизвестная эпоха в адресе»; прежние сценарии карты без правок
- [ ] 5.6 `tests/web/test_epochs.py` — «Страница эпох», «Клавиатура и доступность страницы эпох», «Старая закладка эпох» (тест навигации обновляется на этой ступени), XSS в адресе `/epochs/<…>` и названии эпохи, нет `pageerror`/`console.error`; раскладка 1024×576 и 1920×1080 без наложений (пролёты и подписи по прямоугольникам)
- [ ] 5.7 Мутационные: (а) `apply` перезаписывает существующую датировку; (б) знак эры теряется; (в) век по `год // 100`; (г) `dry_run` пишет; (д) карта считает эпоху по середине жизни при явной связи; (е) фильтр «Эпоха» как одно окно времени; (ж) `suggest` заполняет `wikidata`; (з) значения `deprecated` берутся; (и) `Retry-After` игнорируется; (к) эпоха года при перекрытии — самое раннее начало; (л) идеи без явной эпохи проходят фильтр «Эпоха»; (м) основная датировка — самая сильная по статусу вместо «первая»
- [ ] 5.8 Защита дизайн-якорей карты: линии жизни, узлы, маршруты связей (`anchorOn`) — проверки DOM `tests/web/test_map.py` зелёные; визуальные эталоны (win32) — отметить в `verification.md`, что прогоняет Lead/CI
- [ ] 5.9 `verification.md`: перечень интерфейсных THEN без серверного события с их якорем; команды и сырой вывод; что не прогонялось на машине агента

## 6. Завершение

- [ ] 6.1 `openspec/traceability.yaml`: `epochs` в `enforce` (решение ведущего Р6); `python scripts/check_traceability.py` без пропусков
- [ ] 6.2 `ruff check . && ruff format --check . && lint-imports`; `pytest -q tests/knowledge tests/web/test_map.py tests/web/test_epochs.py`
- [ ] 6.3 Ревьювер: дифф против спецификации и «Выбора решения» (модуль-команда, политика конфликтов, правило на сервере, фильтр, страница), костыли, подгонка тестов
- [ ] 6.4 Судья (новый субагент): вердикт в `verification.md`; PR в draft до «принято»
- [ ] 6.5 Архив вручную, перенос дельт в `openspec/specs/`

## Требует согласования Lead'а

- **Запуск на данных Lead'а:** `suggest`, ручное подтверждение QID в `sources/epochs.yaml`, `apply --dry-run`, `apply`. Делает Lead у себя; результат (отчёт JSON) — в `progress.md`.
- **(Необязательно) `filling.import_wikidata`:** у персон до нашей эры год теряет знак (`[1:5]`). Исправление — в файле Lead'а; здесь не делается, предлагается отдельной задачей.
