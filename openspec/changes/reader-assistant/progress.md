# Progress: reader-assistant

Этап 4 из 6. Ведёт поток A (`claude/reader-wt-assistant`), обновлено 2026-11-08. Готовность: около 90% (Р13, Alt+Q, метка главы, N4 сделаны, тесты T21–T25, T38–T40, T48 зелёные; ждут подключения интегратором Alt+Q и правки сервиса знаний для N5). Этапы 4 и 6 выходят к читателям вместе.

## Статус по пунктам

| Пункт | Статус | Чем подтверждено |
| --- | --- | --- |
| 1.1 OpenSpec | сделано | `openspec validate reader-assistant` — valid |
| 2.1–2.4 Хранилище v4, сессии | сделано | `web/src/storage.ts`; `test_t40_v3_to_v4_migration` (v3, v2, v1) |
| 3.1 N13 стадии | сделано | `tests/assistant/test_routing_grounding.py` |
| 3.2 N4 ссылки | сделано | `chapter_title` из оглавления библиотеки, `tests/assistant/test_citation_details.py` (3 теста) |
| 3.3 N5 `entity_id` | ждёт поток B | ассистент передаёт поле (`test_statement_citation_carries_entity_id`); сервис знаний не отдаёт (`xfail` `test_knowledge_service_sends_statement_entity_id`) |
| 3.4 N6, 3.5 N8 | сделано | `test_routing_grounding.py`; «Близкое в библиотеке» со ссылками — `test_t23_sources_only_line_and_nearby` |
| 4.1 Сессии | сделано | `test_t48_sessions_in_book_panel`, `test_t48_sessions_on_assistant_page` |
| 4.2 Стадии | сделано | `test_answer_stages_visible`; итог хода ответа — `.assistant__summary` |
| 4.3 Остановить, Повторить, 45 с | сделано | `test_stream_and_stop`, `test_t24_messages_by_code`, `test_t24_client_timeout` |
| 4.4 Ссылки, пометки, S12 | сделано | `test_t21_…`, `test_t22_…`, `test_t25_…`, `test_question_waits_for_notice` |
| 4.5 Метка главы | сделано | `Turn.chapterId/chapterTitle`, `.assistant__chapter-label` |
| 4.6 Alt+Q | сделано, ждёт подключения | `web/src/hooks/useAssistantShortcut.ts`; `test_t17_alt_q_with_and_without_selection` пропускается, пока хук не подключён (с подключением проверен локально: зелёный) |
| 4.7 Р13 | сделано | `test_t39_link_to_other_book_switches_dialog_and_back` |
| 4.8–4.10 Найдено при работе | сделано | см. `tasks.md` |
| 5.1 Тесты критерия | частично | зелёные T21–T25, T38–T40, T48; остались T17 (после подключения), T18–T20 полностью, T35 |
| 5.2 Снимки S6–S10, S12 | не начато | снимки делает интегратор после слияния |

## Для интегратора

Строки подключения (файлы не потока A):

- `web/src/ReaderPage.tsx` (поток B): `import { useAssistantShortcut } from "./hooks/useAssistantShortcut";` и в теле `ReaderPage` после `openAssistant`: `useAssistantShortcut(textRef, openAssistant);`
- `compose.yaml`, сервис `assistant`, `environment`: `PHILOGRAPH_LIBRARY_URL: http://library:8001` (без него ассистент работает, но `chapter_title` в ссылках пустой).
- `web/src/main.tsx`: уже добавлено `import "./styles/assistant.css";` после `./styles.css`.
- `src/philograph/knowledge/assist.py` (поток B), `describe()`: добавить `"entity_id": s["subject"]` — тогда N5 закрыт, и `xfail` в `tests/assistant/test_ontology_retrieval.py` нужно снять.
- `ReaderPage` (поток B): `panel.chapterId/chapterTitle` обновляются только при смене книги (эффект по `[sourceId]`, `chapter` в нём ещё прежний). Панель поэтому берёт главу из адреса и заголовка `article.chapter h1`; правильнее обновлять их при смене главы.
- Кнопка «Спросить об абзаце» (5.1) — разметка абзаца в `ReaderPage` (поток B); панель принимает фрагмент как от выделения (`openAssistant({text, paragraphs: [id]})`).

## Известные проблемы

- `useDialogSet` читает и разбирает хранилище при каждой отрисовке панели (до 200 000 знаков). На потоке это раз на фрагмент; при заметных задержках — кэшировать разобранное состояние в `storage.ts`.
- Обмен в статусе `streaming`, чей поток идёт в другой вкладке, в этой вкладке показывается «остановлено» (поток виден только своей вкладке); по `done` статус исправляется.
- Ссылка на утверждение онтологии пока не нажимается: нужен N5 и открытие карточки в стеке панели (`App.tsx`).

## Как проверить

```bash
export TMP="$(pwd -W)/.stack/tmp" TEMP="$TMP"; mkdir -p "$TMP"; export PYTHONPATH="$(pwd)/src"
cd web && npx tsc --noEmit && npm run build && cd ..
python -m pytest -q tests/assistant tests/web/test_assistant_panel.py tests/web/test_assistant_dialogs.py
python scripts/check_traceability.py
```
