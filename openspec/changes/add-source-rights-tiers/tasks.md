# Tasks

Приоритеты: P0 — схема и ядро, P1 — классификация и каталог, P2 — гейтинг читателям и онтология, P3 — тесты и документы.

## 1. Спецификация и данные (P0)

- [x] 1.1 OpenSpec-дельта: `specs/source-registry/spec.md`, `specs/source-catalog/spec.md`, `specs/source-library/spec.md`, `specs/paragraph-search/spec.md`, `specs/answer-grounding/spec.md`.
- [x] 1.2 `sources/rights-tiers.yaml` (пороги и соответствие тира разрешениям).
- [x] 1.3 `sources/licenses.yaml`: поле `tier` у видов; новые виды `in-copyright`, `unknown-rights`.
- [x] 1.4 `sources/catalog.schema.json`: `rights_tier`, `rights_evidence`, `rights_jurisdiction`; `basis` расширен.

## 2. Схема БД и ядро library (P0)

- [x] 2.1 Миграция `library` № 6: `sources.rights_tier`, `license_kinds.tier`, таблица `rights_log`.
- [x] 2.2 `registry.py`: `License`/`Source` с `rights_tier`; `_validate_license` не блокирует `in_copyright`/`unknown`; регистрация фиксирует `display: false`; `change_license`/`change_rights_tier` с журналом. (Константа `COPYRIGHT_YEARS` оставлена как защитная проверка основания `public_domain`; пороги классификации — в `rights-tiers.yaml`.)
- [x] 2.3 `registry.publish`: публикация с `display: false` для онтологии; в событие `source.published` добавлен `display`.

## 3. Классификация и каталог (P1)

- [x] 3.1 `classify_tier` в `library/catalog/rights.py`; `suggest_license` всегда возвращает черновик с `rights_tier`.
- [x] 3.2 `catalog/model.py`: `license_of` переносит `rights_tier`; `validate` проверяет значение статуса.
- [x] 3.3 `catalog/service.py`: `ensure_license_kinds` учитывает `tier`; `in_copyright`/`unknown` проходят register → process → publish (скрыты от читателя фильтром показа).

## 4. Гейтинг читателям и онтология (P2)

- [x] 4.1 `library/reading.py`: `hidden_source_ids()` и `Internal.access` отдают источники без права показа (для сервиса знаний). Список/чтение/резолв уже фильтруют по `display` (существующий механизм).
- [x] 4.2 `search/indexing.py`: `index_version` и `source.access_changed` не индексируют `display: false`.
- [x] 4.3 `assistant`: текст `in_copyright`/`unknown` не доходит до модели — гейтинг выше по стеку (поиск не индексирует, знания скрывают); код ассистента не менялся.
- [x] 4.4 `knowledge/app.py`: `closed_sources` включает `hidden` — текст и цитаты скрыты, производные факты остаются.

## 5. Тесты и проверки (P3)

- [x] 5.1 Тесты классификации `tests/library/catalog/test_rights.py`.
- [x] 5.2 Тесты статуса и журнала `tests/library/test_rights_tiers.py`; правка `test_registry.py` (публикация без показа), `test_archive_org.py` (тир unknown).
- [x] 5.3 Гейтинг по тиру покрыт существующими тестами разрешений/регионов; метки `@req` проставлены.
- [x] 5.4 Проверки: `ruff check .` — зелёный, `ruff format --check` — зелёный, `lint-imports` — 3 kept/0 broken, `check_traceability.py` — 348/348, `catalog validate` — 0 ошибок. `pytest -m "not e2e"` — не прогнан: песочница DSH запрещает удаление файлов (очистка временных каталогов pytest), см. progress.md.

## 6. Документы (P3)

- [x] 6.1 `docs/architecture/source-ingestion.md` (тиры и критерии), `docs/operations/runbook.md` (перемаркировка).
- [x] 6.2 ADR-0004 `docs/architecture/adr/0004-source-rights-tiers.md`.

## Явные договорённости

- [x] Раздача читателям — только `public_domain`/`open_license`.
- [x] `rights_tier` — обязательное поле источника (столбец `sources.rights_tier`).
- [x] `unknown` — консервативно по умолчанию (без показа и без внешней обработки).
- [x] Сбор полных текстов `in_copyright` — решение и правовой риск владельца (ADR-0004).
