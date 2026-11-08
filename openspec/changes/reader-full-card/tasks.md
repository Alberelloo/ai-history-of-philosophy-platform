# Tasks

Отметки актуализированы 2026-11-08 по коду и тестам (см. `progress.md`). `[x]` — подтверждено файлом или тестом.

## 1. Задача и документы

- [x] 1.1 Изменение OpenSpec: `proposal.md`, `tasks.md`, дельта `entity-cards`, `progress.md`, `qa/cases.md`; `openspec validate reader-full-card` — valid
- [x] 1.2 Документы дизайна: `components/Portrait.md`, `components/PortraitGallery.md`, `components/Lifeline.md` существуют

## 2. Сервер

- [ ] 2.1 N3: `portraits` в ответе карточки — до 7, первое главное, без дублей. Сделан только пустой каркас: `src/philograph/knowledge/cards.py:189` отдаёт `"portraits": []`, `test_card_has_portraits_field` проверяет пустой список. Отбор, хранение и отдача портретов не реализованы (допустимо по разделу 16: этап закрывается с монограммами)
- [ ] 2.2 N10: `first_paragraph_id` в `where_to_read[]` — в коде сервера и клиента не найдено; «Где читать» ведёт к началу главы

## 3. Полная карточка

- [x] 3.1 `PortraitGallery` (`web/src/ui.tsx:378`, использование `FullCard.tsx:181`): до 7 изображений, счётчик, точки, листание, заглушка «Изображений нет». Проверена только на пустом списке, на реальных данных не проверялась
- [x] 3.2 `Lifeline` у персон с датами (`FullCard.tsx:197`)
- [x] 3.3 Переключатели источников «Только выбранный учебник» и «Нет в моём учебнике» (`FullCard.tsx:107, 200`); сквозной тест `test_textbook_scope_shared_by_graph_card_and_assistant`
- [x] 3.4 Сводка природы знания (`FullCard.tsx:80, 204`)
- [x] 3.5 Стек «Назад» в панели, глубина до 20 (`App.tsx:95-102`, `ReaderPage.tsx:91` `slice(-20)`)

## 4. Тесты и проверка

- [ ] 4.1 Тесты T10, T12–T14, T16. Есть: серверные аналоги T13/T14 в `tests/knowledge/test_mentions_cards.py` («Пустые разделы», «Описание моделью», «Скорость карточки») и сквозной `test_mention_opens_card_and_navigates` (частично T12). Нет: T10 в панели («Назад: Юм»), T12 целиком (`pg-generated`, ромб, `StatusMark`), T16 (галерея); `check_traceability.py` — 322 из 322
- [ ] 4.2 Снимки S4 по 14.3 и просмотр: эталонов нет
