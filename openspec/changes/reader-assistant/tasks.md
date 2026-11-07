# Tasks

## 1. Задача и документы

- [ ] 1.1 Изменение OpenSpec: `proposal.md`, `design.md`, `tasks.md`, дельты `assistant-dialog` и `reader-settings`, `progress.md`, `qa/cases.md`; `openspec validate`

## 2. Хранилище формата 4

- [ ] 2.1 Типы `DialogSet`/`Session`/`Turn` и поля `dialogs`/`libraryDialogs`; `KEY = philograph:v4`
- [ ] 2.2 Перенос v3→v4: старый общий диалог — в `libraryDialogs`, поля переносятся как есть
- [ ] 2.3 `trimDialogs` под словарь с порядком вытеснения (5.8)
- [ ] 2.4 API сессий: чтение набора, запись обмена, создание/переименование/удаление/переключение

## 3. Сервер

- [ ] 3.1 N13: события `stage searching` и `stage composing found N`
- [ ] 3.2 N4: `source_title`, `chapter_title`, начало абзаца в ссылках
- [ ] 3.3 N5: `entity_id` у ссылки на утверждение
- [ ] 3.4 N6: `paragraph_id` у suggestions события `no_answer`
- [ ] 3.5 N8: `answer_language` в событии `done`

## 4. Панель ассистента

- [ ] 4.1 Сессии: список, «+», переименование (Enter/Esc), удаление с подтверждением; пустая не плодится
- [ ] 4.2 Поток со стадиями и временем (5.3); цикл индикатора; `prefers-reduced-motion`
- [ ] 4.3 «Остановить» только в потоке; «Повторить»; тайм-аут 45 с
- [ ] 4.4 Ссылки `pushState` (5.4), пометки (5.5), строка «только по источникам» (5.6), S12 с «Показать уведомление»
- [ ] 4.5 Метка главы у обмена; `aria-live` для стадий

## 5. Тесты и проверка

- [ ] 5.1 Тесты T17–T27, T35, T38–T40, T44, T48 с `@req`; `check_traceability.py`
- [ ] 5.2 Итоговый прогон: сборка, pytest, ruff, прослеживаемость
