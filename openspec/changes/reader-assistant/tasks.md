# Tasks

Отметки актуализированы 2026-11-08 по коду и тестам (см. `progress.md`). `[x]` — подтверждено файлом или тестом.

## 1. Задача и документы

- [x] 1.1 Изменение OpenSpec: `proposal.md`, `design.md`, `tasks.md`, дельты `assistant-dialog` и `reader-settings`, `progress.md`, `qa/cases.md`; `openspec validate reader-assistant` — valid

## 2. Хранилище формата 4

- [x] 2.1 Типы `DialogSet`/`Session`/`Turn` и поля `dialogs`/`libraryDialogs`; `KEY = philograph:v4` (`web/src/storage.ts`; `tests/e2e/test_settings.py`)
- [x] 2.2 Перенос v3→v4: старый общий диалог — в `libraryDialogs` (`test_old_format_migrated`; прямого теста T40 с проверкой `positions`/`settings`/`openSources` нет)
- [x] 2.3 `trimDialogs` под словарь с порядком вытеснения 5.8 (`test_old_dialogs_dropped_over_limit`)
- [x] 2.4 API сессий: чтение набора, запись обмена, создание/переименование/удаление/переключение (`storage.ts`)

## 3. Сервер

- [x] 3.1 N13: события `stage searching` и `stage composing found N` (`tests/assistant/test_routing_grounding.py:167`)
- [x] 3.2 N4: `source_title`, `chapter_title` и начало абзаца (120 знаков) в ссылках. Название главы ассистент берёт из оглавления библиотеки (`LibraryHttp` в `assistant/clients.py`, запоминается на источник; при сбое библиотеки не приходит). Тесты `tests/assistant/test_citation_details.py`. Для работы на стенде ассистенту нужен `PHILOGRAPH_LIBRARY_URL` (строка для `compose.yaml` — в `progress.md`)
- [ ] 3.3 N5: ассистент передаёт `entity_id` утверждения в ссылку (`test_statement_citation_carries_entity_id`), но сервис знаний его не отдаёт: `knowledge/assist.py`, `describe()` без `entity_id` (файл потока B). Тест по настоящему сервису — `xfail` (`test_knowledge_service_sends_statement_entity_id`)
- [x] 3.4 N6: `paragraph_id` у suggestions события `no_answer` (`test_routing_grounding.py`)
- [x] 3.5 N8: `answer_language` в событии `done` (`service.py:364, 439`; `test_routing_grounding.py:174`)

## 4. Панель ассистента

- [x] 4.1 Сессии: список, «+», переименование (Enter/Esc), удаление с подтверждением; пустая не плодится (`AssistantPanel.tsx`, `test_sessions_are_separate`; переименование и удаление тестом не покрыты)
- [x] 4.2 Поток со стадиями и временем (5.3) (`test_answer_stages_visible`)
- [x] 4.3 «Остановить» только в потоке; «Повторить»; тайм-аут 45 с (`AssistantPanel.tsx:47`; `test_stream_and_stop`, `test_error_mid_answer_keeps_marks`)
- [x] 4.4 Ссылки, пометки, строка «только по источникам», S12 с «Показать уведомление» (`AssistantPanel.tsx:453, 490`; `test_question_waits_for_notice`)
- [x] 4.5 Метка главы у обмена: `Turn.chapterId`/`chapterTitle` (глава по адресу, название — из панели или заголовка главы); у вопроса из другой главы подпись «Глава „…“» (`.assistant__chapter-label`)
- [x] 4.6 Alt+Q: хук `web/src/hooks/useAssistantShortcut.ts` (подключение в `ReaderPage` — интегратор, строка в `progress.md`). «Спросить об абзаце» — кнопка в разметке абзаца `ReaderPage` (поток B), не сделана
- [x] 4.7 Р13: ссылка на абзац другой книги — переход с `pushState` и `assistantFrom` в состоянии истории; панель показывает диалог новой книги и `Notice` «Вы пришли из диалога по книге „…“» с «Вернуться» (`history.back()`); у прежней записи — опорный абзац, «Назад» возвращает на место ±4px (`test_t39_link_to_other_book_switches_dialog_and_back`)

## 4a. Найдено при работе потока A

- [x] 4.8 Наборы сессий читаются и пишутся через хранилище (`storage.updateDialogs`, `useDialogSet`), а не через состояние панели: панель в `App.tsx` не пересоздаётся при смене книги, и прежде набор книги A записывался в книгу B. Потоки ответов живут на уровне модуля и дописывают ответ в сессию своей книги после закрытия панели и смены книги
- [x] 4.9 Удаление сессии с идущим ответом отменяло не тот запрос (ключ сессии вместо обмена); исправлено, «самая свежая» при удалении активной — по `updatedAt`
- [x] 4.10 Итог хода ответа одной строкой («Ответ за N с · абзацев: M», «Остановлено на стадии …», «Оборвалось на стадии …»), «Остановить» на месте «Спросить», Enter — отправить, лимит посетителя делает «Спросить» неактивной, «Близкое в библиотеке» со ссылками на абзацы (N6), черновики вопроса и фрагмента отдельно на сессию

## 5. Тесты и проверка

- [ ] 5.1 Тесты критерия (поток A, `tests/web/test_assistant_dialogs.py`): T21, T22, T23, T24 (коды и тайм-аут по часам Playwright), T25, T38, T39, T40, T48 — зелёные. Осталось: T17 полностью (Alt+Q после подключения хука; выделение через два абзаца), T18–T20, T35. Прежняя запись: T17–T27, T35, T38–T40, T44, T48. Есть частично (одним-двумя тестами каждый): T17, T18, T19, T20, T24 (серверная часть), T26, T27, T44, T47 (частично). Нет: T21, T22, T23, T25, T35 для ассистента, T38, T39, T40 в полном виде, T48. Подробно — `docs/process/reader-handoff.md`
- [ ] 5.2 Итоговый прогон и снимки S6–S10, S12 и стадий в обеих темах и языках: эталонов по 14.3 нет; прослеживаемость 322/322
