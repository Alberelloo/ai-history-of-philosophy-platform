# Tasks

Приоритеты: P0 — схема и ядро (без этого ничего не работает), P1 — классификация и каталог, P2 — гейтинг читателям и онтология, P3 — тесты и документы. На этом этапе код НЕ пишем, источники НЕ скачиваем: задачи — план реализации.

## 1. Спецификация и данные (P0)

- [ ] 1.1 OpenSpec-дельта: `specs/source-registry/spec.md` (новое требование «Правовой статус источника», правки «Лицензия с основанием и разрешениями», «Права на перевод», «Разрешения управляют обработкой и показом»), `specs/source-catalog/spec.md` (поле тира, доказательство, перемаркировка), `specs/source-library/spec.md`, `specs/paragraph-search/spec.md`, `specs/answer-grounding/spec.md` (гейтинг по тиру).
- [ ] 1.2 Новый `sources/rights-tiers.yaml` (+ при необходимости `rights-tiers.schema.json`): юрисдикционные пороги (70, США pre-1930/95/120, РФ ст. 1281–1282), список открытых лицензий, соответствие тира разрешениям (таблица из design.md п. 2.3).
- [ ] 1.3 `sources/licenses.yaml`: поле `tier` у каждого вида; новые виды `in-copyright` и `unknown-rights` с `display: false`.
- [ ] 1.4 `sources/catalog.schema.json`: поле `license.rights_tier` (enum из 4), `rights_evidence`, `rights_jurisdiction`; расширить `license.basis` значениями `in_copyright`, `unknown`.

## 2. Схема БД и ядро library (P0)

- [ ] 2.1 Миграция `library` № 6: `sources.rights_tier` (NOT NULL, значение по умолчанию для старых строк — по `basis`/`kind`), `license_kinds.tier`, таблица `rights_log`.
- [ ] 2.2 `registry.py`: удалить `COPYRIGHT_YEARS`; `License`/`Source` с `rights_tier`; `_validate_license` считает по тиру (не по 70 годам); регистрация `in_copyright`/`unknown` не блокирует обработку, а фиксирует `display: false`; `change_license`/перемаркировка с evidence и записью в `rights_log`.
- [ ] 2.3 `registry.publish`: читательская публикация только при `display: true`; новый outbox-событие `source.processed` (с `external_processing` и изменениями) для версий `display: false`, чтобы их видела онтология.

## 3. Классификация и каталог (P1)

- [ ] 3.1 `classify_rights(harvest, year, jurisdiction)` в `library/catalog/rights.py` (или `adapters.py`): по подсказке лицензии, годам смерти, году издания и порогам из `rights-tiers.yaml`; выводит `rights_tier` + `rights_evidence`.
- [ ] 3.2 `catalog/model.py`: `license_of`/`validate` — тир обязателен; `in_copyright` требует evidence-примечания; `unknown` требует решения оператора (warning/error в review); убрать ошибки «70 лет».
- [ ] 3.3 `catalog/service.py`: `_sync_entry`/`ensure_license_kinds` учитывают тир; `in_copyright`/`unknown` проходят register → process → `source.processed` (без читательской публикации).

## 4. Гейтинг читателям и онтология (P2)

- [ ] 4.1 `library/reading.py` и `library/app.py`: список источников, чтение и `resolve_paragraph` скрывают источники `display: false` (тир + регион); ссылка на их абзац — «источник недоступен».
- [ ] 4.2 `search`: читательский индекс/выдача только по `display: true`; внутренние интерфейсы видят всё (прецедент регионов).
- [ ] 4.3 `assistant`: не отправлять модели и не цитировать текст `in_copyright`/`unknown`; опора на производные утверждения онтологии и ссылки на легальные абзацы.
- [ ] 4.4 `knowledge`: потреблять `source.processed` для извлечения онтологии по всему корпусу; полные тексты наружу не отдавать (карточки/граф/`where_to_read` — только легальные источники).

## 5. Тесты и проверки (P3)

- [ ] 5.1 Тесты классификации: юрисдикции (автор +70, США pre-1930/95/120, РФ +74/реабилитация), переводы/редакции, `unknown`, CC0/CC/OGL.
- [ ] 5.2 Тесты миграции № 6 (старая база → тир по `basis`/`kind`) и журнала `rights_log` (перемаркировка с evidence, расширение требует доказательства).
- [ ] 5.3 Тесты гейтинга: library/search/assistant не отдают `in_copyright`/`unknown`; knowledge строит онтологию по `in_copyright` без раздачи текста; метки `@req` и `check_traceability.py`.
- [ ] 5.4 Проверки: `ruff check .`, `ruff format --check .`, `pytest -q`, `python scripts/check_traceability.py`.

## 6. Документы (P3)

- [ ] 6.1 `docs/architecture/source-ingestion.md` (тиры и критерии), `docs/operations/runbook.md` (ручная перемаркировка тира).
- [ ] 6.2 ADR: сбор полных текстов `in_copyright` — решение и правовой риск владельца; граница «раздача читателям = только легальные тиры».

## Явные договорённости (проверяются на всех шагах)

- [ ] Раздача читателям — только `public_domain`/`open_license`.
- [ ] `rights_tier` — обязательное поле источника.
- [ ] `unknown` — консервативно по умолчанию (без показа и без внешней обработки).
- [ ] Сбор полных текстов `in_copyright` — решение и правовой риск владельца.
