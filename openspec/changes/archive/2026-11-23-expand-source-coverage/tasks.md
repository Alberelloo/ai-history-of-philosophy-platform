# Tasks

## 1. Спецификация (P0)

- [x] 1.1 OpenSpec-дельта: `source-catalog`, `source-registry`.

## 2. Адаптеры открытых репозиториев (P0)

- [x] 2.1 `sources/licenses.yaml`: вид `arxiv-non-exclusive`.
- [x] 2.2 `library/catalog/adapters.py`: адаптеры `arxiv`, `philarchive`, `doaj`.
- [x] 2.3 Классификация лицензий: паттерн arXiv в `LICENSE_HINTS`/`classify_tier`.
- [x] 2.4 Тесты адаптеров на мок-HTTP (`tests/library/catalog/test_open_adapters.py`).

## 3. Metadata-only (P1)

- [x] 3.1 `sources/catalog.schema.json`: `metadata_only`, `abstract`, `toc`, `citations`.
- [x] 3.2 `library/catalog/model.py`: `validate` — metadata-only допускает `files: []`, требует `in_copyright` + аннотацию.
- [x] 3.3 `library/registry.py`: регистрация без файлов, метаданные в `settings`, событие `source.metadata_registered`.
- [x] 3.4 `library/catalog/service.py`: синхронизация metadata-only (без конвейера).
- [x] 3.5 `knowledge`: `metadata.py` (`MetadataIngest`), связи `authored`/`cites`, подписка `source.metadata_registered`.
- [x] 3.6 Тесты (`tests/library/catalog/test_metadata_only.py`).

## 4. Данные каталога (P1)

- [ ] 4.1 Первая партия записей открытых работ — отложено на сервер (сеть из песочницы недоступна).
- [ ] 4.2 Первая партия metadata-only записей — отложено на сервер (нужны точные метаданные).

## 5. Проверки и PR (P2)

- [x] 5.1 `ruff check .`, `ruff format --check`, `lint-imports`, `check_traceability.py`, `catalog validate`.
- [x] 5.2 `docs/architecture/source-ingestion.md`.
- [ ] 5.3 `openspec archive expand-source-coverage --yes` + PR в `main`.
