# Progress: reader-notes

## Кто ведёт

Субагент reader-notes (разработчик) по регламенту dev-cycle.

## Статус задач (`tasks.md`)

- 1.1 — в работе: артефакты созданы, `openspec validate` не запускался.
- 2.x–5.x — не начаты.

## Предусловие

Этапы 1–2 готовы: раскладка K1–K4 с полем `.margin-col` (пустым), компактное окно карточки. Все тесты зелёные.

## Следующий шаг

1. `openspec validate reader-notes`.
2. Сервер N7 (detail_code/page + миграция + PIPELINE_VERSION 4).
3. Сноски на поле (K1) и в окне (K2–K4), номера страниц, плашки по коду.

## Как проверить

- `openspec validate reader-notes`
- `cd web && npx tsc --noEmit && npx vite build`
- `pytest -q -m "not e2e"` и `pytest -q tests/e2e` (TEMP/TMP в .stack/tmp для Chromium)
- `python scripts/check_traceability.py`
