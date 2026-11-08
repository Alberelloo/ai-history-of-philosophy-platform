# Задачи: assistant-page

Отметки актуализированы 2026-11-08 по коду и тестам (см. `progress.md`).

## 1. Сервер

- [x] 1.1 N12: поле `context: "book" | "library"` в `AskRequest` (по умолчанию `"library"`), `handoff_declined`/`handoff_reason` (`tests/assistant/test_handoff.py`)
- [x] 1.2 Событие `{"type": "handoff", "reason": "broader" | "outside_book"}` при `context: "book"` (`test_handoff_broader_for_other_authors`, `test_handoff_outside_book`, `test_library_context_never_handsoff`)

## 2. Страница раздела

- [x] 2.1 `AssistantPage.tsx`: диалог `libraryDialogs`, сессии, стадии, пометки, прилепленная форма, строка «только по источникам»
- [x] 2.2 Маршрут `/assistant` в `App.tsx`, `/soon/assistant` → `/assistant` (`test_assistant_page_and_stub`)
- [x] 2.3 `Sidebar.tsx`: пункт «Ассистент» ведёт на `/assistant`

## 3. Граница и поручение

- [x] 3.1 Блок S7a в `AssistantPanel.tsx` (`test_handoff_block_and_transfer_link`: текст, ссылка с `/assistant?q=`, «Продолжить в рамках этого источника»)
- [x] 3.2 Поручение перехода в памяти вкладки, отправка один раз, `handoffId` (`AssistantPanel.tsx:218, 341`); двойной щелчок, «Назад», Ctrl+щелчок и перезагрузка (T41, T42) отдельным тестом не проверены
- [x] 3.3 i18n: `assistant.handoff.*`

## 4. Тесты

- [ ] 4.1 T36, T41–T43, T46. Есть: `test_assistant_page_and_stub` (T43 частично), `test_handoff_block_and_transfer_link` (T46 частично, T41 частично) и серверные тесты границы. Нет: T36 (страница «Ассистент» и S7a в EN без кириллицы), T41 (двойной щелчок), T42 (перезагрузка и прямой адрес не отправляют), T46 (оба вида границы и оба выбора в браузере). Снимки страницы лежат только в `qa/screenshots/round-1..3`, не как эталоны `reader-*`
- [x] 4.2 Прослеживаемость 322 из 322 (`scripts/check_traceability.py`)

## 5. Доработки актуализации

- [x] 5.1 `openspec validate assistant-page` падал: в дельтах `visual-design` («Разделы в разработке») и `assistant-dialog` («Общий вопрос») в блоках MODIFIED были опущены сценарии текущей спецификации. Исправлено копированием полного блока; результат — valid (предупреждение о длинном тексте требования «Раздел „Ассистент“» осталось)
- [ ] 5.2 Независимая перепроверка фиксов round-3 (FND-1…FND-4) тестировщиком — не проведена
- [ ] 5.3 Запись в журнал решений `docs/design/design-system.md` о раскладке K1–K4, полоске, 62ch, колонках без анимации, стадиях ответа и диалогах (последний шаг раздела 16): записи нет
