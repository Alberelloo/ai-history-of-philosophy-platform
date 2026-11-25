# Tasks

Третье в стеке: после `add-reference-catalog` и `add-epochs` (нужны `snapshot.py`, `epochs.py`, `knowledge/wikidata.py` (`http_fetch`, `fetch_entity`, `claim_date`), страница `/epochs/<id>`, `sources/epochs.yaml`). Ветка — `claude/epoch-context`. После каждого пункта: отметка, `progress.md`, коммит `wip(add-epoch-context): …`, push.

## 1. Задача и документы

- [x] 1.1 Изменение OpenSpec: `proposal.md`, `design.md`, `tasks.md`, дельты `epoch-context`, `ontology-registry`, `entity-cards`, `knowledge-graph`, `visual-design`, `progress.md`
- [x] 1.2 `docs/product/ontology.md` — виды событий (+ экономическое, социальное), источники контекста; `docs/product/system-design.md` — `GET /v1/context`, команда `epoch_context`

## 2. Реестр и извлечение

- [x] 2.1 `registry_data.py`: `EVENT_KINDS` + `economic`, `social`; дозагрузка в существующую базу (тест на базе, заполненной прежним реестром); `ontology.{ru,en}.json` — названия видов, отдельная группа `qualifiers.mechanism` (не в `values`), заголовок раздела `context`; `web/src/map/types.ts` — `EventKind`
- [x] 2.2 Подтверждение извлечения без правки `filling.py`: юнит-тесты на фейковой модели — `stimulated` с механизмом сохраняется, с неверным — отбрасывается, фрагмент продолжается (если тест выявит, что поведение иное, — остановиться и вынести в «Требует согласования Lead'а», а не править файл)

## 3. Сервис знаний

- [x] 3.1 `knowledge/context.py`: режимы эпоха/окно, события из снимка по `EpochMembership`, места, связи `stimulated` (порядок по статусу, механизм, `generated`, `in_textbook`, подтверждения без цитат с фильтром закрытых источников), середина — `dates.middle`, фильтры `kinds`/`verified`, `counts` без учёта `kinds` и до усечения, пределы 200/30 в порядке значимости и статуса и `truncated`, проверка параметров по таблице (`knowledge.context.rejected`, `reason` = `mode`/`window`/`unknown_epoch`/`unknown_kind`, без значений параметров), событие `knowledge.context.served`
- [x] 3.2 Маршрут `GET /v1/context` в `app.py` (регион — `region_closed`)
- [x] 3.3 `cards.py`: раздел `context` («Исторический контекст», `stimulated`, in) у понятия, персоны, произведения, учений
- [x] 3.4 `map.py`: `stimulated` у событий (`id`, `generated`; только объекты на карте, ≤ 30, проверенные раньше сгенерированных); клиент — свои цвета сначала стимулированным персонам
- [x] 3.5 Демо: в `scripts/seed_demo.py` — место «Лондон» у «Славной революции», связи `stimulated` с механизмом (одна по источникам, одна сгенерированная), экономическое событие без связей; эталоны чтения не меняются

## 4. Wikidata

- [x] 4.1 `knowledge/epoch_context.py` поверх общего `knowledge/wikidata.py` из 2.2 (без своего httpx, разбора времени и проверки QID): `harvest` (P793 → кандидаты с датой, видом по `EVENT_CLASSES`, местом; без даты — нет; решения и поля человека не перезаписываются, кандидаты не задваиваются), событие `knowledge.context_import.harvested`
- [x] 4.2 `apply` (только `accepted`; событие и место по QID или новые; `dating`, `event_kind`, `belongs_to_epoch`, `happened_in` — `sourced`, атрибуция Wikidata; `stimulated` никогда; `--dry-run`; идемпотентность через формат дат `FuzzyDate.to_json`), события `checked` (`created`/`exists`/`pending`/`rejected`/`no_date`/`fetch_failed`) и `run` (`created`, `statements`, `places_created`, `skipped`)
- [x] 4.3 CLI `python -m philograph.knowledge.epoch_context harvest|apply`; `sources/epoch_context.yaml` — пустой манифест со схемой в комментарии; фикстуры Wikidata в `tests/knowledge/fixtures/wikidata/`

## 5. Клиент

- [x] 5.1 `web/src/epochs/ContextBlock.tsx`: виды со счётчиками, «только проверенные», события по видам и времени, связи с механизмом, статусом и ¶, ссылки на карточки, состояния, адрес (`kinds`, `verified`)
- [x] 5.2 «Достроить контекст»: поток `/graph/build` (рецепт `context`, старт — событие) через `map/stream.ts`, строки «не проверено», сообщения причин без вызова модели (`not_needed`, `done_before`, `scope`, `disabled`, `unavailable`, `limit`, `visitor_limit`), перезапрос после `done`; кнопка скрыта при выключенной генерации
- [x] 5.3 Карточка: подписи механизма в строках раздела «Исторический контекст»; `map/model.ts` — выбор события добавляет `stimulated` (с учётом «только проверенные»)
- [x] 5.3а Вывод названий текстом, ссылка Wikidata из проверенного QID, ошибка загрузки без `pageerror`/`console.error`; группы видов по таблице спецификации (включая «Биография» и «Прочее»)
- [x] 5.4 Подпись раздела «Эпохи и контекст»; строки RU/EN; `npm run build`

## 6. Задачи тестировщика

- [ ] 6.1 `tests/knowledge/test_context.py` — сценарные и нормативные на «Контекст эпохи», «Пометка непроверенного контекста», «Механизм влияния»: вывод API и `knowledge.context.served`; инварианты: сгенерированное всегда с `generated=true`; при `verified=true` ни одной `generated`; ни одной цитаты в ответе; подтверждения закрытых источников не отдаются ни в одном режиме; ровно один режим; отклонённые не отдаются; не больше 200/30; «Проверка параметров контекста» — параметризованно по таблице, в событиях нет значений параметров
- [ ] 6.2 `tests/knowledge/test_filling.py` — «Контекст из текста» (фейковая модель); инвариант: механизм вне списка не записывается ни из извлечения, ни из `Statements.add` (`knowledge.statement.refused` с `type`, `reason`), ни из импорта, ни из достройки (механизм модели отброшен); «Стимулировало от персоны» — `reason` «тип stimulated не подходит концам»
- [ ] 6.3 `tests/knowledge/test_epoch_context_import.py` — «Контекстные события из Wikidata»: офлайн-фикстуры, сеть запрещена; инварианты: `stimulated` и влияние никогда не пишутся; `pending`/`rejected` не пишутся; `--dry-run` не меняет таблиц; повторный `apply` идемпотентен (`exists`); повторный `harvest` не меняет решений; класс P31 не из таблицы — вид не пишется; точные `statements`/`places_created`
- [ ] 6.4 «Достройка контекста моделью» — `tests/knowledge/test_graph.py` (рецепт `context` от события: тип вне рецепта отброшен, сохранено со статусом `generated`, без механизма) и `tests/web/test_epochs.py` (кнопка, пометка, уже достраивали, связей достаточно, генерация выключена — кнопки нет и `knowledge.graph.extended` нет)
- [ ] 6.5 `tests/knowledge/test_registry_entities.py` — «Виды групп, роли персон и виды событий» (экономическое в существующей базе); `tests/knowledge/test_mentions_cards.py` — «Исторический контекст учения»
- [ ] 6.6 `tests/web/test_epochs.py` — «Контекст на странице эпохи» (блок, фильтр видов, закрытый источник, пусто), разметка в названии события (XSS, нет `pageerror`), «Старая закладка эпох» с подписью «Эпохи и контекст»; на фикстуре `tests/web` с настоящим приложением знаний из 2.1, `page.route` — только для 201 события и 503; `tests/web/test_map.py` — «Событие и то, что оно стимулировало» (без линий между стратами — проверка по DOM)
- [ ] 6.7 Мутационные: (а) `generated` не выставляется; (б) `verified` не фильтрует; (в) цитата попадает в ответ; (г) закрытый источник не снимается; (д) `apply` пишет `pending`; (е) `apply` пишет `stimulated` из Wikidata; (ж) механизм не проверяется; (з) карта рисует линию событие→персона; (и) `counts` считаются после `kinds`; (к) механизм модели сохраняется при достройке; (л) в `knowledge.context.rejected` попадает значение параметра
- [ ] 6.8 `verification.md`: перечень интерфейсных THEN без серверного события с их якорем; команды, сырой вывод; что не прогонялось (e2e, визуальные эталоны — CI/Lead)

## 7. Завершение

- [ ] 7.1 `openspec/traceability.yaml`: `epoch-context` в `enforce`; `python scripts/check_traceability.py` без пропусков
- [ ] 7.2 `ruff check . && ruff format --check . && lint-imports`; `pytest -q tests/knowledge tests/web/test_epochs.py tests/web/test_map.py`
- [ ] 7.3 Ревьювер: дифф против спецификации и «Выбора решения» (один эндпоинт, манифест Wikidata, достройка через граф, подсветка вместо линий, виды событий), признаки костылей и подгонки
- [ ] 7.4 Судья (новый субагент): вердикт в `verification.md`; PR в draft до «принято»
- [ ] 7.5 Архив вручную, перенос дельт

## Требует согласования Lead'а

- **Подсказка уточнителей модели при извлечении** (`registry.output_schema()` → `x-relations[*].qualifiers` с допустимыми значениями `mechanism`). Файлы Lead'а не меняются, но меняются данные запроса `ontology.extract` → новые ключи кэша, иной расход токенов в текущем прогоне. Делать только после согласования; до этого механизм из текста приходит, только если модель укажет его сама.
- **Механизм и новые события в достройке:** новый шаблон в `src/philograph/prompts/__init__.py` (файл Lead'а) — «предложи события эпохи и как они стимулировали идеи», с проверкой: механизм из списка, события — с датой внутри эпохи, создаются со статусом `generated`. Отдельное изменение OpenSpec после согласования.
- **Запуск на данных Lead'а:** `epoch_context harvest` → разметка `sources/epoch_context.yaml` → `apply --dry-run` → `apply`. Отчёт — в `progress.md`.
