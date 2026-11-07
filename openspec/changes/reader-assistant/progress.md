# Progress: reader-assistant

## Кто ведёт

Субагент reader-assistant (разработчик) по регламенту dev-cycle.

## Статус задач (`tasks.md`)

- 1.1 Изменение OpenSpec — в работе: `proposal.md`, `design.md`, `tasks.md`, дельты `assistant-dialog`/`reader-settings`, `qa/cases.md`, `progress.md` созданы; `openspec validate` не запускался.
- 2.x–5.x — не начаты.

## Предусловие

Этапы 1–2 готовы (раскладка, каркас панели, компактное окно карточки). Хранилище — формат 3 с полем `mentions`.

## Зона записи

`web/src/AssistantPanel.tsx`, `web/src/storage.ts`, `src/philograph/assistant/`, `openspec/changes/reader-assistant/`, `tests/web/test_assistant_panel.py`, `tests/knowledge/…` (assistant), `web/src/styles.css` (только в конец). Панель действий над выделением и Alt+Q — в `ReaderPage.tsx` (ведёт lead).

## Следующий шаг

1. `openspec validate reader-assistant`.
2. Хранилище формата 4 (`storage.ts`).
3. Сервер N13, N4, N5, N6, N8.
4. `AssistantPanel` (сессии, стадии, остановка/повтор/тайм-аут).
5. Тесты.

## Как проверить

- `openspec validate reader-assistant`
- `cd web && npx tsc --noEmit && npx vite build`
- `pytest -q -m "not e2e"` и `pytest -q tests/e2e` (TEMP/TMP → `.stack/tmp` для Chromium)
- `python scripts/check_traceability.py`
