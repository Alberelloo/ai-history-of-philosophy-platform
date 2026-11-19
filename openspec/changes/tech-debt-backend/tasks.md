# Tasks

## 1. Предложение

- [x] 1.1 proposal, design («Выбор решения» по каждому пункту), дельты `service-runtime`, `observability`, `source-catalog`, `deployment`

## 2. Настройки сервисов и секрет посетителя (1.1, 1.5)

- [ ] 2.1 `platform.settings`: чтение из словаря окружения, пустое значение — отсутствие, необязательные зависимости (`optional`) и событие `service.settings.optional_absent`, общий `fail`
- [ ] 2.2 Классы настроек и фабрики `create()` у llm, library, search, assistant, knowledge, gateway; секрет посетителя без значения по умолчанию
- [ ] 2.3 Команды: исполнитель, `ops`, миграции, CLI каталога и портретов — через классы настроек
- [ ] 2.4 Запуск: `uvicorn --factory` в compose и `scripts/dev_stack.py`; тесты, собирающие ассистента, передают секрет
- [ ] 2.5 Тесты: отказ без секрета, неверное значение, событие о необязательной зависимости, все настройки заданы

## 3. Ошибки, границы, мелочи (1.12, 1.13, 1.15)

- [ ] 3.1 События `knowledge.portraits.download_failed`, `library.catalog.lookup_failed`, `ops.backup.record_failed`; тесты
- [ ] 3.2 `philograph.knowledge` в контракте независимости
- [ ] 3.3 Лямбды в `evaluation/runs.py`, `type: ignore` в CLI каталога

## 4. Еженедельная проверка обновлений

- [ ] 4.1 Планировщик `ops` ставит `library.catalog.check_updates` раз в неделю (журнал `ops.runs`, ключ — неделя ISO), исполнитель выполняет `check-updates` каталога; события; тесты
- [ ] 4.2 Runbook: расписание и как проверить

## 5. Сборка (1.2, 1.3, 1.8, 1.14)

- [ ] 5.1 `uv.lock`, extra `server`, установка по lock в Dockerfile
- [ ] 5.2 Точные теги и digest образов в Dockerfile и compose
- [ ] 5.3 Цели `runtime` и `e2e`; `compose.e2e.yaml` собирает `e2e`; `.dockerignore`
- [ ] 5.4 Проверка закреплённости образов и состава прод-образа (тест)
- [ ] 5.5 ADR-0001: OCR вне сервера

## 6. CI (1.4, 1.15)

- [ ] 6.1 `checks`: `-m "not e2e"`, PostgreSQL без `tests/web`, без мёртвого шага, uv по lock, `uv lock --check`
- [ ] 6.2 Actions по SHA, `.github/dependabot.yml`
- [ ] 6.3 Замер времени до и после, предел `timeout-minutes`

## 7. Лимиты шлюза

- [ ] 7.1 ADR-0004: счётчики лимитов в памяти одной реплики, условие пересмотра; runbook

## 8. Передача

- [ ] 8.1 ruff, lint-imports, прослеживаемость, тесты затронутых пакетов, полный прогон без e2e
- [ ] 8.2 Draft-PR
