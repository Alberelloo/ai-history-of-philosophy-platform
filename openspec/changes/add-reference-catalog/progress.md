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
