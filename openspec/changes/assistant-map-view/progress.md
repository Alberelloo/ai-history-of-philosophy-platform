# Progress

## 2026-11-18 — предложение

- Ведёт: основная сессия Claude Code.
- Сделано: `proposal.md`, `design.md`, дельты `question-routing`, `assistant-dialog`, `knowledge-graph`, `tasks.md`. Реализация не начата.
- Основа в коде: событие `suggestion` вида `graph` (`assistant/service.py`, `AssistantPanel.tsx`) — кнопка «Открыть граф» уже ведёт на карту `/graph/<id>?recipe=…`; состояние карты в адресе — `web/src/map/types.ts` (`parseState`/`writeState`).
- Следующий шаг: ответы владельца на открытые вопросы в `proposal.md`, затем слияние `synchro-map` и задачи 1.x.
- Как проверить предложение: `python scripts/check_traceability.py` (требования изменения учитываются при архивации).
