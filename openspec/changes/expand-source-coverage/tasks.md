# Tasks

## 1. Спецификация (P0)

- [ ] 1.1 OpenSpec-дельта: `source-catalog` («Адаптеры открытых репозиториев», «Запись только с метаданными»), `source-registry` («Источник только с метаданными», правка «Регистрация источника»).

## 2. Адаптеры открытых репозиториев (P0)

- [ ] 2.1 `sources/licenses.yaml`: вид `arxiv-non-exclusive` (тир `open_license`).
- [ ] 2.2 `library/catalog/adapters.py`: адаптеры `arxiv`, `philarchive` (OAI-PMH), `doaj` (API); `matches` + `harvest` (метаданные, abstract, PDF, license_hint).
- [ ] 2.3 Классификация лицензий: паттерн arXiv non-exclusive в `LICENSE_HINTS`/`classify_tier`; `suggest_license` → `open_license`.
- [ ] 2.4 Тесты адаптеров на мок-HTTP (`tests/library/catalog/test_open_adapters.py`).

## 3. Metadata-only (P1)

- [ ] 3.1 `sources/catalog.schema.json`: `metadata_only`, `abstract`, `toc`, `citations`; `files` допускает пустой список.
- [ ] 3.2 `library/catalog/model.py`: `validate` — metadata-only допускает `files: []` и требует `rights_tier: in_copyright`.
- [ ] 3.3 `library/registry.py`: регистрация без файлов (`metadata_only`), метаданные в `settings`, событие `source.metadata_registered`; удаление без версии.
- [ ] 3.4 `library/catalog/service.py`: синхронизация metadata-only (без конвейера, регистрация + событие).
- [ ] 3.5 `knowledge`: обработчик `source.metadata_registered` — сущности `person`/`work`, связи `authored`/`cites` (новые типы связей в `registry_data.py`).
- [ ] 3.6 Тесты: metadata-only не публикует текст и не отдаётся читателям; гейтинг.

## 4. Данные каталога (P1)

- [ ] 4.1 Первая партия записей открытых работ (эпистемология + общая философия) — черновики.
- [ ] 4.2 Первая партия metadata-only записей (философия XX века, аналитическая и континентальная эпистемология) — черновики.

## 5. Проверки и PR (P2)

- [ ] 5.1 `ruff check .`, `ruff format --check .`, `pytest -q -m "not e2e"`, `lint-imports`, `check_traceability.py`, `catalog validate`.
- [ ] 5.2 `docs/architecture/source-ingestion.md` (новые адаптеры и metadata-only).
- [ ] 5.3 `openspec archive expand-source-coverage --yes` + PR в `main`.
