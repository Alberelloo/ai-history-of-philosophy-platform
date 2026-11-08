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
- [ ] 3.2 N4: `source_title` и начало абзаца (120 знаков) в ссылках сделаны (`service.py:405-406`); `chapter_title` не заполняется (в `src/philograph/search` его нет)
- [ ] 3.3 N5: поле `entity_id` у ссылки на утверждение передаётся (`service.py:423`), но значение зависит от сервиса знаний; тест значения не найден
- [x] 3.4 N6: `paragraph_id` у suggestions события `no_answer` (`test_routing_grounding.py`)
- [x] 3.5 N8: `answer_language` в событии `done` (`service.py:364, 439`; `test_routing_grounding.py:174`)

## 4. Панель ассистента

- [x] 4.1 Сессии: список, «+», переименование (Enter/Esc), удаление с подтверждением; пустая не плодится (`AssistantPanel.tsx`, `test_sessions_are_separate`; переименование и удаление тестом не покрыты)
- [x] 4.2 Поток со стадиями и временем (5.3) (`test_answer_stages_visible`)
- [x] 4.3 «Остановить» только в потоке; «Повторить»; тайм-аут 45 с (`AssistantPanel.tsx:47`; `test_stream_and_stop`, `test_error_mid_answer_keeps_marks`)
- [x] 4.4 Ссылки, пометки, строка «только по источникам», S12 с «Показать уведомление» (`AssistantPanel.tsx:453, 490`; `test_question_waits_for_notice`)
- [ ] 4.5 Метка главы у обмена: `chapterId` и `chapterTitle` уже приходят в панель из `ReaderPage` (`App.tsx:66, 116`), но в хранимом `Turn` и в разметке обмена метки главы нет
- [ ] 4.6 Alt+Q и «Спросить об абзаце» (T17): `altKey` в `web/src` не найден
- [ ] 4.7 Р13: переход по ссылке на абзац другой книги переключает диалог, над историей `Notice` «Вы пришли из диалога по книге „…“» и «Вернуться» (T39): строки «пришли» в `web/src` нет

## 5. Тесты и проверка

- [ ] 5.1 Тесты критерия: T17–T27, T35, T38–T40, T44, T48. Есть частично (одним-двумя тестами каждый): T17, T18, T19, T20, T24 (серверная часть), T26, T27, T44, T47 (частично). Нет: T21, T22, T23, T25, T35 для ассистента, T38, T39, T40 в полном виде, T48. Подробно — `docs/process/reader-handoff.md`
- [ ] 5.2 Итоговый прогон и снимки S6–S10, S12 и стадий в обеих темах и языках: эталонов по 14.3 нет; прослеживаемость 322/322
