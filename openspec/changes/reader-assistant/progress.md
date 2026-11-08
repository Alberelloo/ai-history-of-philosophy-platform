# Progress: reader-assistant

Этап 4 из 6. Актуализировано 2026-11-08 по коду. Готовность: около 70% (хранилище, сессии, стадии и сервер работают; не хватает Alt+Q, перехода между книгами Р13, метки главы и большей части тестов T17–T48). Этапы 4 и 6 выходят к читателям вместе.

## Статус по пунктам

| Пункт | Статус | Чем подтверждено |
| --- | --- | --- |
| 1.1 OpenSpec | сделано | `openspec validate reader-assistant` — valid |
| 2.1–2.4 Хранилище v4, сессии | сделано | `web/src/storage.ts`, `tests/e2e/test_settings.py` (`test_old_format_migrated`, `test_old_dialogs_dropped_over_limit`) |
| 3.1 N13 стадии | сделано | `tests/assistant/test_routing_grounding.py:167` |
| 3.2 N4 ссылки | частично | `source_title` и начало абзаца есть (`service.py:405-406`), `chapter_title` нет |
| 3.3 N5 `entity_id` | частично | поле передаётся (`service.py:423`), значение не проверено тестом |
| 3.4 N6 `paragraph_id` в suggestions | сделано | `test_routing_grounding.py` |
| 3.5 N8 `answer_language` | сделано | `service.py:364, 439`, `test_routing_grounding.py:174` |
| 4.1 Сессии в панели | сделано | `AssistantPanel.tsx`, `test_sessions_are_separate` (переименование и удаление без теста) |
| 4.2 Стадии | сделано | `test_answer_stages_visible` |
| 4.3 Остановить, Повторить, 45 с | сделано | `AssistantPanel.tsx:47`, `test_stream_and_stop`, `test_error_mid_answer_keeps_marks` |
| 4.4 Ссылки, пометки, только по источникам, S12 | сделано | `AssistantPanel.tsx:453, 490`, `test_question_waits_for_notice` |
| 4.5 Метка главы у обмена | не начато | `chapterId`/`chapterTitle` приходят в панель, в `Turn` не сохраняются |
| 4.6 Alt+Q | не начато | `altKey` в `web/src` нет |
| 4.7 Р13 «Вы пришли из диалога» | не начато | строки в `web/src` нет |
| 5.1 Тесты критерия | частично | см. `docs/process/reader-handoff.md`, таблица T1–T48 |
| 5.2 Снимки S6–S10, S12 | не начато | эталонов по 14.3 нет |

## Сейчас

Панель ассистента и сессии работают, серверные N6, N8, N13 закрыты. Прежний текст `progress.md` и `tasks.md` считал 4.5 «нужен chapterId от lead» — теперь `chapterId` приходит, поэтому пункт переведён из блокера в обычную задачу. Остальное ниже.

## Следующий шаг

1. Р13 (T39): при переходе по ссылке на абзац другой книги переключать набор сессий и показывать `Notice` «Вы пришли из диалога по книге „…“» с «Вернуться».
2. Alt+Q и «Спросить об абзаце» (T17, T18).
3. Метка главы у обмена (4.5): поле `chapterId`/`chapterTitle` в `Turn`.
4. N4 `chapter_title` (сервис поиска) и проверка значения N5 `entity_id` (сервис знаний).
5. Тесты: T21, T22, T23, T25, T35 (reduced-motion для стадий), T38, T39, T40 полностью, T48; затем снимки S6–S10, S12.

## Известные проблемы

- Прежняя запись «317/319 прослеживаемость» устарела: сейчас 322 из 322.
- Тесты многие объединены в один и не названы по Tn; сопоставление с T1–T48 выполнено по сценариям (см. handoff).
- Нет эталонов снимков состояний ассистента по схеме 14.3.

## Как проверить

```bash
export TMP="$(pwd -W)/.stack/tmp"; export TEMP="$TMP"; mkdir -p "$TMP"
/c/Users/Ivano/AppData/Local/Programs/openspec/openspec validate reader-assistant
.venv/Scripts/python -m pytest -q tests/assistant tests/web/test_assistant_panel.py
.venv/Scripts/python -m pytest -q tests/e2e/test_settings.py
.venv/Scripts/python scripts/check_traceability.py
cd web && npx tsc --noEmit
```
