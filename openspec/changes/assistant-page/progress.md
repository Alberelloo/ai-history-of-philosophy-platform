# Progress: assistant-page

Этап 6 из 6. Актуализировано 2026-11-08 по коду. Готовность: около 85%. Выходит к читателям вместе с этапом 4.

## Статус по пунктам

| Пункт | Статус | Чем подтверждено |
| --- | --- | --- |
| 1.1–1.2 Сервер N12 | сделано | `tests/assistant/test_handoff.py` (4 теста) |
| 2.1 Страница `AssistantPage.tsx` | сделано | `web/src/AssistantPage.tsx`, `test_assistant_page_and_stub` |
| 2.2 Маршрут и редирект заглушки | сделано | `test_assistant_page_and_stub` |
| 2.3 Пункт в навигации | сделано | `web/src/Sidebar.tsx` |
| 3.1 Блок S7a | сделано | `test_handoff_block_and_transfer_link` |
| 3.2 Поручение, отправка один раз | сделано в коде | `AssistantPanel.tsx:218, 341`; T41 и T42 отдельно не проверены |
| 3.3 i18n | сделано | `assistant.handoff.*` в `i18n/` |
| 4.1 T36, T41–T43, T46 | частично | есть по одному тесту на T43 и T46/T41; T36, T42 и полный T46 нет |
| 4.2 Прослеживаемость | сделано | 322 из 322 |
| 5.1 `openspec validate` | исправлено | было: ошибка двух MODIFIED-блоков; стало: valid |
| 5.2 Перепроверка round-3 | не начато | `dev_cycle` остановился на maxRounds=3 |
| 5.3 Журнал решений в `design-system.md` | не начато | записи о K1–K4 нет |

## Сейчас

Страница `/assistant`, граница с выбором и перенос вопроса работают. Прежний `progress.md` писал «Готово, все проверки зелёные» — это было преувеличением: валидация OpenSpec не проходила, а тесты T36, T41, T42 и полный T46 отсутствуют.

## Следующий шаг

1. Тесты: T41 (один запрос при двойном щелчке и «Назад»), T42 (перезагрузка и прямой адрес не отправляют), T46 (оба вида границы, оба выбора), T36 (EN без кириллицы), T43 с `aria-current="page"`.
2. Независимая перепроверка исправлений round-3 тестировщиком.
3. Снимки страницы (пустая, с диалогом, «перенесён и не отправлен», «уже задан») по 14.3 как эталоны и просмотр человеком.
4. Последний шаг раздела 16: запись в журнал решений `docs/design/design-system.md`.
5. Проверить критерий: в журнале `assistant.question.received` один вопрос на переход.

## Известные проблемы

- Исправление дельт: в `specs/visual-design/spec.md` и `specs/assistant-dialog/spec.md` добавлены опущенные сценарии (иначе архивирование теряло бы их).
- Предупреждение валидатора: требование «Раздел „Ассистент“» длиннее 500 знаков; стоит вынести детали в сценарии.
- Раунды `dev_cycle`: round 1 (7 замечаний), round 2 (5), round 3 (4); все исправлены автором, но независимо не проверены.
- Снимки лежат в `qa/screenshots/round-1..3`, человеческий просмотр не проводился.

## Как проверить

```bash
export TMP="$(pwd -W)/.stack/tmp"; export TEMP="$TMP"; mkdir -p "$TMP"
/c/Users/Ivano/AppData/Local/Programs/openspec/openspec validate assistant-page
.venv/Scripts/python -m pytest -q tests/assistant/test_handoff.py tests/web/test_assistant_panel.py
.venv/Scripts/python scripts/check_traceability.py
cd web && npx tsc --noEmit
```
