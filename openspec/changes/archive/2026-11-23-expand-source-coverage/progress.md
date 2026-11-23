# Progress

## 2026-11-23 — планирование

- Ведёт: субагент `claude` (разработчик), по поручению Lead. Ветка `claude/expand-source-coverage` от `origin/main`.
- Сеть из песочницы недоступна (philarchive.org, arxiv.org, doaj.org, philpapers.org — все FAIL): адаптеры и тесты — на мок-HTTP, массовый harvest откладывается на сервер.
- Написан план: proposal, design (с «Выбор решения»), tasks, дельты спек. `openspec validate` — valid.

## 2026-11-23 — реализация

- **Открытые каналы:** адаптеры `arxiv` (Atom API), `philarchive` (OAI-PMH), `doaj` (bibjson) в `adapters.py`; вид лицензии `arxiv-non-exclusive`; классификация `open_license` (arXiv добавлен в `classify_tier`/`LICENSE_HINTS`). Тесты на мок-HTTP.
- **Metadata-only:** схема каталога (`metadata_only`, `abstract`, `toc`, `citations`), `validate` (без файлов + `in_copyright` + аннотация), `registry.register` (без файлов, метаданные в `settings`, событие `source.metadata_registered`), `service._desired`/`_sync_entry` (без конвейера), `knowledge/metadata.py` (`MetadataIngest`: персоны, произведения, связи `authored`/`cites`), подписка в `knowledge/app.py`/`main.py`.
- **Данные каталога:** первая партия записей отложена на сервер — сеть недоступна, точные URL/лицензии нужны с сервера.

## Проверки

- `openspec validate expand-source-coverage` — valid.
- `ruff check .` — All checks passed; `ruff format --check src tests` — 209 files formatted.
- `lint-imports` — 3 kept, 0 broken.
- `python scripts/check_traceability.py` — 355/355.
- `python -m philograph.library.catalog validate` — 0 ошибок, 6 предсуществующих warning.
- Смоук-тесты в памяти: регистрация metadata-only (outbox `source.metadata_registered`, files=[], display:false), классификация arXiv, `MetadataIngest` (сущности + связи) — OK.

## Блокеры

- **`pytest` в сессии субагента не идёт** (песочница запрещает удаление файлов): тесты написаны, прогнаны только смоук-тесты в памяти; полный прогон — у Lead в полном доступе.
- Сеть недоступна: harvest и данные каталога — на сервере.
- `docker compose` v2 нет → `tests/ops/test_deploy.py` (предсуществующее).
