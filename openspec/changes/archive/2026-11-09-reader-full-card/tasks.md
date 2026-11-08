# Tasks

Отметки актуализированы 2026-11-08 по коду и тестам (см. `progress.md`). `[x]` — подтверждено файлом или тестом.

## 1. Задача и документы

- [x] 1.1 Изменение OpenSpec: `proposal.md`, `tasks.md`, дельта `entity-cards`, `progress.md`, `qa/cases.md`; `openspec validate reader-full-card` — valid
- [x] 1.2 Документы дизайна: `components/Portrait.md`, `components/PortraitGallery.md`, `components/Lifeline.md` существуют

## 2. Сервер

- [x] 2.1 N3: закрыто монограммами (2026-11-08, разрешено разделом 16 дока). Сервер отдаёт `portraits: []`, клиент показывает монограмму и «Изображений нет»; галерея и медальон готовы принять данные (T16 на подменённом ответе). Отбор, хранение и лицензии — отдельный черновик `openspec/changes/portrait-sourcing/` (proposal.md, tasks.md, без реализации)
- [x] 2.2 N10: `first_paragraph_id` в `where_to_read[]` — первый абзац главы с упоминанием по порядку в версии (`mentions.position`, миграция `knowledge` 6; строки без порядка — по порядку вставки; упоминание только в заголовке или сноске даёт `null`). Клиент ведёт «Где читать» к `#p-<абзац>`, без него — к началу главы (`FullCard.tsx`, `whereToReadLink`). Тесты `test_where_to_read_first_paragraph`, `test_where_to_read_without_position`, `test_migration_6_adds_mention_position`, `test_n10_where_to_read_opens_first_paragraph`

## 3. Полная карточка

- [x] 3.1 `PortraitGallery` (`web/src/ui.tsx:378`, использование `FullCard.tsx:181`): до 7 изображений, счётчик, точки, листание, заглушка «Изображений нет». Проверена только на пустом списке, на реальных данных не проверялась
- [x] 3.2 `Lifeline` у персон с датами (`FullCard.tsx:197`)
- [x] 3.3 Переключатели источников «Только выбранный учебник» и «Нет в моём учебнике» (`FullCard.tsx:107, 200`); сквозной тест `test_textbook_scope_shared_by_graph_card_and_assistant`
- [x] 3.4 Сводка природы знания (`FullCard.tsx:80, 204`)
- [x] 3.5 Стек «Назад» в панели, глубина до 20 (`App.tsx:95-102`, `ReaderPage.tsx` `pushPanelItem`, `slice(-20)`)
- [x] 3.6 Переход по связи в панели: значение-сущность открывает её в той же панели, «Назад: <прежняя>» (событие `philograph:open-card` из `FullCard.tsx`, обработчик в `ReaderPage.tsx`; раньше кнопка ничего не делала)
- [x] 3.7 Состояния панели по 4.7: «Загружаем карточку…», «Повторить» при сбое; сгенерированная строка — `pg-generated` с ромбом (4.5); стили в новом `web/src/styles/card.css`

## 4. Тесты и проверка

- [x] 4.1 Тесты T10, T12, T16 (+ T13/T14 серверные в `tests/knowledge/test_mentions_cards.py`): T10 `test_t10_link_and_back_in_popover_and_panel`; T12 `test_t12_nature_of_each_row[light|dark]`; T16 `test_t16_portrait_gallery` (5, 1 и 0 изображений на подменённом ответе); Р6 (после перезагрузки панель и окно не восстанавливаются) — в `test_n10_where_to_read_opens_first_paragraph`. Всё в `tests/web/test_reader_cards.py`
- [ ] 4.2 Снимки S4 по 14.3 и просмотр: сценарии есть в `tests/e2e/test_reader_snapshots.py`, эталоны и просмотр — за интегратором (`test_s1_s4_card`)
