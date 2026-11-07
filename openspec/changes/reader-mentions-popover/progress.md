# Progress: reader-mentions-popover

## Кто ведёт

Сессия lead (разработчик) по регламенту dev-cycle.

## Статус задач (`tasks.md`)

- 1.1 Изменение OpenSpec — в работе: `proposal.md`, `tasks.md`, дельты `entity-mentions`/`entity-cards`/`reader-settings`, `qa/cases.md`, `progress.md` созданы; `openspec validate` не запускался.
- 1.2–5.2 — не начаты.

## Предусловие

Этап 1 (`reader-layout`) завершён: раскладка K1–K4, каркас панели, привязка места чтения. Все тесты зелёные (353 не-e2e + 56 e2e), `check_traceability.py` 316/316.

## Следующий шаг

1. `openspec validate reader-mentions-popover`.
2. Сервер N1 (`entity_type` в `/mentions`) и N2 (404 `entity_not_found`).
3. Упоминания `span[role=button]`, цвет семьи, настройка вида.
4. Окно карточки: положение, состав, стек, загрузка/ошибки, кэш.
5. Тесты и снимки.

## Известные проблемы

- Браузерные тесты в этой сессии требуют перенаправления `TEMP`/`TMP` в рабочую папку (Chromium не создаёт каталог в `AppData\Local\Temp`).

## Как проверить

- `openspec validate reader-mentions-popover`
- `pytest -q -m "not e2e"` и `pytest -q tests/e2e` (с перенаправлением TEMP)
- `python scripts/check_traceability.py`
