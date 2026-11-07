# Progress: reader-assistant

## Кто ведёт

Субагент reader-assistant (разработчик) по регламенту dev-cycle.

## Статус задач (`tasks.md`)

- 1.1, 2.1–2.4, 3.1–3.5, 4.1–4.4 — готово.
- 4.5 (метка главы у обмена) — нужен `chapterId` из `ReaderPage`, вне зоны записи.
- 5.x — серверные тесты готовы; браузерные T17–T27/T38–T48 — частично.

## Сделано

1. Изменение OpenSpec `reader-assistant` (proposal/design/tasks/cases/progress + дельты), `openspec validate` → valid.
2. Хранилище формата 4 (`storage.ts`): `dialogs: Record<sourceId, DialogSet>`, `libraryDialogs`, типы `Session`/`Turn`, перенос v3→v4, `trimDialogs` по порядку вытеснения 5.8, API сессий.
3. `AssistantPanel.tsx`: сессии (список/«+»/переименование/удаление с подтверждением), поток со стадиями и временем, «Остановить» только в потоке, «Повторить», тайм-аут 45 с, строка «только по источникам», S12, ключи i18n.
4. Сервер: N13 (стадии), N4 (`source_title` + начало абзаца), N5 (поле `entity_id`), N6 (`paragraph_id` в suggestions), N8 (`answer_language` в `done`).
5. Серверные тесты стадий и переноса; `tests/assistant` 25 passed.

## Известные ограничения (вне зоны записи)

- `chapter_title` у ссылок (N4) и значение `entity_id` (N5) требуют изменений сервисов поиска/знаний — вне зоны записи (`src/philograph/assistant/` только).
- Панель действий над выделением (7), «Спросить об абзаце», Alt+Q — в `ReaderPage.tsx` (ведёт lead); дельта заведена, тест T18 — у lead.
- `check_traceability.py` 317/319: нет тестов «Панель действий над выделением» (ReaderPage, lead) и «Портреты в карточке» (этап 3, lead).

## Следующий шаг

1. Браузерные тесты T17–T27, T38–T48 в `tests/web/test_assistant_panel.py`.
2. Итоговый прогон после сборки lead (App.tsx/ReaderPage.tsx ещё в работе — tsc падает на ReaderPage).

## Как проверить

- `openspec validate reader-assistant`
- `cd web && npx tsc --noEmit && npx vite build` (после завершения lead App.tsx/ReaderPage.tsx)
- `pytest -q tests/assistant` и `pytest -q -m "not e2e"` (TEMP/TMP → `.stack/tmp`)
- `python scripts/check_traceability.py`
