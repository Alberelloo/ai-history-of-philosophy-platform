# Progress

## 2026-11-23 — планирование

- Ведёт: субагент `claude` (аналитик/планировщик), по поручению Lead.
- Собран анализ текущего состояния (см. design.md): правило «70 лет / public domain» в `registry.py`, `catalog/{model,adapters}.py`, `sources/{licenses.yaml,catalog.schema.json}`, спеках `source-registry`/`source-catalog`.
- Написан план (`proposal.md`, `design.md`, `tasks.md`), дельты спецификаций, `openspec validate add-source-rights-tiers` — valid.

## 2026-11-23 — реализация

- Ведёт: субагент `claude` (разработчик), ветка `claude/add-source-rights-tiers` от `claude/synchro-map`.
- Реализовано P0–P3 по `tasks.md`:
  - данные: `sources/rights-tiers.yaml`, `licenses.yaml` (поле `tier`, виды `in-copyright`/`unknown-rights`), `catalog.schema.json`;
  - схема: миграция `library` № 6 (`sources.rights_tier`, `license_kinds.tier`, `rights_log`);
  - ядро: `registry.py` (`resolve_tier`, `change_rights_tier`, публикация с `display: false`, событие `library.rights_tier.changed`);
  - классификация: `catalog/rights.py` (`classify_tier`), `adapters.suggest_license` всегда возвращает черновик с тиром, `model.validate`, `service.ensure_license_kinds`;
  - гейтинг: `reading.hidden_source_ids` + `Internal.access`, `search.indexing` (пропуск `display: false`), `knowledge.closed_sources` (+ `hidden`);
  - тесты: `tests/library/test_rights_tiers.py`, `tests/library/catalog/test_rights.py`, правки `test_registry.py`, `test_archive_org.py`;
  - доки: `source-ingestion.md`, `runbook.md`, ADR-0004.
- Отклонение от плана (осознанно): вместо отдельного события `source.processed` использована публикация с `display: false` + фильтры на краях (`Internal.published` и так не отдаёт `display: false`, поиск это закрепляет). Это проще и переиспользует существующий механизм разрешений; зафиксировано в ADR-0004 и design.md (см. ниже). Константа `COPYRIGHT_YEARS` оставлена как защитная проверка основания `public_domain`.

## Проверки

- `openspec validate add-source-rights-tiers` — valid.
- `ruff check .` — All checks passed; `ruff format --check src tests` — 202 files already formatted.
- `lint-imports` — 3 kept, 0 broken.
- `python scripts/check_traceability.py` — 348 из 348.
- `python -m philograph.library.catalog validate` — ошибок 0, предупреждений 6 (предсуществующие дубли названий).
- Смоук-тест в памяти: регистрация `in_copyright`, `change_rights_tier` + журнал, миграция — OK.
- Полный прогон `pytest -q -m "not e2e"` (в окружении с полным доступом): **531 passed, 150 skipped, 95 deselected, 1 failed**. 150 skip — окружение (Chromium/Playwright, 1 PostgreSQL), кода не касаются. Единственный сбой — регрессия `tests/library/test_regions_api.py::test_internal_access_lists_closed`: эндпоинт `internal/access` стал отдавать ещё поле `hidden`, а тест сверял весь словарь. Исправлено: ожидание `{"region","closed","hidden"}`.

## Блокеры и известные вопросы

- **В локальной сессии субагента `pytest` не прогоняется**: песочница DSH (workspace-write) запрещает удаление файлов, и pytest падает на очистке временных каталогов (`shutil.rmtree`/`cleanup_dead_symlinks` → PermissionError). Полный прогон выполнен Lead'ом с полным доступом (см. выше).
- `docker compose` v2 нет → `tests/ops/test_deploy.py` (3 падения) — предсуществующее, не от этого изменения.
- e2e/визуальный стенд (Postgres/Docker) при ~1 ГБ памяти не поднимался.
- `openspec archive` не выполнялся: по решению Lead — только после зелёных проверок и слияния `claude/synchro-map` в `main`.

## Следующий шаг

- Прогнать `pytest -q -m "not e2e"` в окружении с полным доступом (вне песочницы) и при необходимости поправить.
- После зелёных тестов — `openspec archive add-source-rights-tiers --yes` и PR в `main`.
