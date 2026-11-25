# Tasks

Второе в стеке: начинается после `add-reference-catalog` (нужны `knowledge/snapshot.py`, `knowledge/epochs.py`, `GET /v1/catalog`). Ветка — `claude/epochs` от ветки или слияния `add-reference-catalog`. После каждого пункта: отметка, `progress.md`, коммит `wip(add-epochs): …`, push.

## 1. Задача и документы

- [x] 1.1 Изменение OpenSpec: `proposal.md`, `design.md`, `tasks.md`, дельты `epochs`, `knowledge-graph`, `entity-cards`, `visual-design`, `progress.md`
- [ ] 1.2 `docs/product/ontology.md` — эпоха: датировка из Wikidata, ядро эпох в `sources/epochs.yaml`; `docs/product/system-design.md` — команда оператора `epoch_dates`; `sources/README` (если есть) — манифест эпох

## 2. Даты и Wikidata

- [ ] 2.1 `dates.py`: `interval(start, end, original)`; `epoch_dates.wikidata_time(value, precision)` — год, десятилетие, век (обе записи века), тысячелетие, эра (юнит-тесты на каждую точность и до н. э.)
- [ ] 2.2 `entities.py`: `add_external(entity_id, system, value)` с `DuplicateEntity` (юнит-тест)
- [ ] 2.3 `knowledge/epoch_dates.py`: `fetch_entity`, `epoch_dating` (P580/P582, запасные P571/P576), `EpochDates.apply` (манифест + `--linked`, сопоставление и заведение эпох, `unchanged`/`conflict`/`no_dates`/`no_qid`/`fetch_failed`/`ambiguous`/`duplicate_qid`, `--dry-run` без записи), отчёт JSON, события `knowledge.epoch_dates.checked`/`run`
- [ ] 2.4 `suggest`: поиск кандидатов, отбор по `PERIOD_CLASSES` и датам, запись в манифест без `wikidata`, событие `knowledge.epoch_dates.suggested`
- [ ] 2.5 CLI `python -m philograph.knowledge.epoch_dates suggest|apply`; `http_fetch` (`User-Agent`, таймаут, `Retry-After`, предел попыток) — единственное место с сетью
- [ ] 2.6 `sources/epochs.yaml` — эпохи раздела RU/EN с `wikidata: null`; проверка манифеста
- [ ] 2.7 Фикстуры ответов Wikidata `tests/knowledge/fixtures/wikidata/*.json` (`wbgetentities`, `wbsearchentities`) — офлайн

## 3. Сервис знаний

- [ ] 3.1 `epochs.py`: список эпох (пролёт, `fuzzy`, точность, источник датировки, Wikidata, описание, счётчики по видам), `undated`
- [ ] 3.2 Маршрут `GET /v1/epochs`, событие `knowledge.epochs.listed`
- [ ] 3.3 `map.py`: `epochs` у персон, трудов/идей, событий; `fuzzy` у эпох (прежние тесты карты без правок)
- [ ] 3.4 `cards.py`: разделы эпохи «Датировка», «Относятся к эпохе»
- [ ] 3.5 Демо: в `scripts/seed_demo.py` — эпоха без датировки с явным участником, явная принадлежность Локка к Просвещению, датировка с нечётким концом у «Научной революции»; эталоны чтения не меняются

## 4. Клиент

- [ ] 4.1 Карта: `types.ts` (`epochs`, `fuzzy`, `Filter.epochs`, адрес `epochs`), `model.ts` (фильтр, выбор эпохи по `epochs`, удалить `midLife`/`eraOf` для эпох), `MapPanel.tsx` (фасет «Эпоха», окно по пролёту), `MapCanvas.tsx`/`layout.ts` (растушёвка), `packIntervals` вынесен из `packPeople`
- [ ] 4.2 `web/src/epochs/{EpochsPage,Timeline,api}.tsx/ts`: лента, дорожки, растушёвка, описание выбранной (счётчики, персоны, труды, события через `/v1/catalog`), действия, `/epochs/<id>`, состояния, клавиатура
- [ ] 4.3 `App.tsx` (маршруты, `/soon/epochs` → `/epochs`), `Sidebar.tsx` (`LIVE.epochs`, подпись «Эпохи»), `ReferencePage` — эпоха в записи ссылкой на `/epochs/<id>`; строки RU/EN; стили `styles/epochs.css`
- [ ] 4.4 `cd web && npm run build`

## 5. Задачи тестировщика

- [ ] 5.1 `tests/knowledge/test_epoch_dates.py` — сценарные и нормативные на «Датировка эпохи», «Даты эпох из Wikidata», «Подбор записи Wikidata», «Ядро эпох»: вывод (утверждения, атрибуция, отчёт) и события; функция загрузки — фикстуры, сеть запрещена (фикстура, падающая при обращении к `httpx`)
- [ ] 5.2 Нормативные: существующая датировка никогда не перезаписывается; `--dry-run` не меняет ни одной таблицы (сравнение счётчиков всех таблиц); `suggest` не пишет в базу и не заполняет `wikidata`; связи влияния (P737) не импортируются; без QID — ни одного вызова `fetch`
- [ ] 5.3 `tests/knowledge/test_epochs_list.py` — «Список эпох»: порядок, `undated`, `counts` совпадают со справочником (`/v1/catalog?epoch=&type=`), источник датировки, событие
- [ ] 5.4 `tests/knowledge/test_map.py` — новые сценарии «Нечёткая граница эпохи», «Эпохи в ответе карты»; `tests/knowledge/test_mentions_cards.py` — «Карточка эпохи» (вывод по датам строкой не показан)
- [ ] 5.5 `tests/web/test_map.py` — «Явная эпоха на карте», «Фильтр «Эпоха»», «Неизвестная эпоха в адресе»; прежние сценарии карты без правок
- [ ] 5.6 `tests/web/test_epochs.py` — «Страница эпох», «Клавиатура и доступность страницы эпох», «Старая закладка эпох»; раскладка 1024×576 и 1920×1080 без наложений (пролёты и подписи по прямоугольникам)
- [ ] 5.7 Мутационные: (а) `apply` перезаписывает существующую датировку; (б) знак эры теряется; (в) век по `год // 100`; (г) `dry_run` пишет; (д) карта считает эпоху по середине жизни при явной связи; (е) фильтр «Эпоха» как одно окно времени; (ж) `suggest` заполняет `wikidata`
- [ ] 5.8 Защита дизайн-якорей карты: линии жизни, узлы, маршруты связей (`anchorOn`) — проверки DOM `tests/web/test_map.py` зелёные; визуальные эталоны (win32) — отметить в `verification.md`, что прогоняет Lead/CI
- [ ] 5.9 `verification.md`: команды и сырой вывод; что не прогонялось на машине агента

## 6. Завершение

- [ ] 6.1 `python scripts/check_traceability.py` без пропусков (`epochs` уже в `enforce` после 2.1)
- [ ] 6.2 `ruff check . && ruff format --check . && lint-imports`; `pytest -q tests/knowledge tests/web/test_map.py tests/web/test_epochs.py`
- [ ] 6.3 Ревьювер: дифф против спецификации и «Выбора решения» (модуль-команда, политика конфликтов, правило на сервере, фильтр, страница), костыли, подгонка тестов
- [ ] 6.4 Судья (новый субагент): вердикт в `verification.md`; PR в draft до «принято»
- [ ] 6.5 Архив вручную, перенос дельт в `openspec/specs/`

## Требует согласования Lead'а

- **Запуск на данных Lead'а:** `suggest`, ручное подтверждение QID в `sources/epochs.yaml`, `apply --dry-run`, `apply`. Делает Lead у себя; результат (отчёт JSON) — в `progress.md`.
- **(Необязательно) `filling.import_wikidata`:** у персон до нашей эры год теряет знак (`[1:5]`). Исправление — в файле Lead'а; здесь не делается, предлагается отдельной задачей.
