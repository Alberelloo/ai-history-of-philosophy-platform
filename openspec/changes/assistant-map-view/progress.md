# Progress

## 2026-11-18 — предложение

- Ведёт: основная сессия Claude Code.
- Сделано: `proposal.md`, `design.md`, дельты `question-routing`, `assistant-dialog`, `knowledge-graph`, `tasks.md`. Реализация не начата.
- Основа в коде: событие `suggestion` вида `graph` (`assistant/service.py`, `AssistantPanel.tsx`) — кнопка «Открыть граф» уже ведёт на карту `/graph/<id>?recipe=…`; состояние карты в адресе — `web/src/map/types.ts` (`parseState`/`writeState`).
- Владелец ответил (2026-11-18): карта только на явную просьбу; рядом с кнопкой — короткий ответ со ссылками.
- Следующий шаг: слияние `synchro-map`, затем задачи 1.x.
- Как проверить предложение: `python scripts/check_traceability.py` (требования изменения учитываются при архивации).
