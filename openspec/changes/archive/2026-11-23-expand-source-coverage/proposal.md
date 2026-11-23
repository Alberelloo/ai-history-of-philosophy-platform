# Proposal

## Why

Библиотека сейчас собирает исторические издания (Wikisource, Gutenberg, archive.org) и русскоязычные учебники — преимущественно общественное достояние. Современная философия (XX–XXI вв.) почти целиком под охраной: полный текст легально доступен только в открытых репозиториях (PhilArchive, arXiv, DOAJ), а по охраняемым книгам доступны лишь метаданные. Чтобы корпус стал «максимально полным» по всем направлениям, нужно два легальных канала: открытые full-text репозитории и метаданные охраняемых работ (без текста, для онтологии).

## What Changes

- **Открытые каналы (full-text).** Новые адаптеры каталога: PhilArchive (OAI-PMH), arXiv (API), DOAJ (API). Каждый собирает метаданные и ссылку на PDF, классифицирует лицензию как `open_license` (CC-BY/-SA/-NC, arXiv non-exclusive и т.п.) через существующий `rights_tier`.
- **Первая партия записей** открытых работ (эпистемология и общая философия, современные открытые работы).
- **Metadata-only (без полного текста).** Новый вид записи `metadata_only` для охраняемых произведений: title, authors, year, аннотация, оглавление, цитаты. `rights_tier: in_copyright`, `display: false`, файлов нет. Запись идёт в онтологию как производные факты (сущности, связи «кто на кого ссылается»), полный текст не хранится и читателям не показывается.

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `source-catalog`: добавлены «Адаптеры открытых репозиториев» и «Запись только с метаданными».
- `source-registry`: добавлено «Источник только с метаданными»; изменено «Регистрация источника» (допускаются источники без файлов).

## Impact

- Данные: `sources/licenses.yaml` (вид `arxiv-non-exclusive`), `sources/catalog.schema.json` (`metadata_only`, `abstract`, `toc`, `citations`), `sources/catalog.yaml` (первая партия записей).
- Код: `library/catalog/adapters.py` (адаптеры PhilArchive/arXiv/DOAJ + классификация), `library/catalog/{model,service}.py` (валидация и синхронизация metadata-only), `library/registry.py` (регистрация без файлов, событие `source.metadata_registered`), `knowledge/…` (потребление события, производные факты).
- Тесты: адаптеры на мок-HTTP, классификация лицензий, metadata-only (не публикует текст, не отдаётся читателям), гейтинг.
- Документы: `docs/architecture/source-ingestion.md` (новые адаптеры и metadata-only).
