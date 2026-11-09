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
- [x] 3.4 Подпись перенесённого вопроса «Из книги «…», глава «…»» (`assistantPage.fromBookChapter`, EN “From the book “…”, chapter “…””): название главы хранится в `Turn.from.chapterTitle`; без него — прежнее «Из книги «…»» (`test_transfer_shows_book_and_chapter`)

## 4. Тесты

- [x] 4.1 T36, T41–T43, T46: `tests/web/test_assistant_page.py` — `test_t41_transfer_sends_once` (двойной щелчок, «Назад», «Вперёд», «Открыть ответ…»), `test_t42_reload_and_direct_address_do_not_send` (перезагрузка, прямой адрес в новой вкладке, Ctrl+щелчок), `test_t42_notice_not_closed_does_not_send`, `test_t43_nav_item_current_without_soon` (`aria-current="page"`, без «скоро», `/soon/assistant` без записи в историю), `test_t46_boundary_and_stay_in_book[broader|outside_book]` (до выбора запросов нет, запрос с `handoff_declined`, `handoff_reason`, тем же вопросом и фрагментом), `test_t36_assistant_page_and_boundary_in_english`; T48 на странице — `tests/web/test_assistant_dialogs.py::test_t48_sessions_on_assistant_page`. Снимки страницы и S7a: сценарии есть в `tests/e2e/test_reader_snapshots.py` (`test_assistant_page`, `test_answer_states`), эталоны и просмотр — за интегратором
- [x] 4.2 Прослеживаемость 322 из 322 (`scripts/check_traceability.py`)

## 5. Доработки актуализации

- [x] 5.4 Поток A: поручение перехода при незакрытом уведомлении не отправляется и после его закрытия (вопрос в поле, «не отправлено», S12); у обмена книги отметка `handoff.sent`, по ней «Открыть ответ…» отличается от «Ответ удалён в разделе „Ассистент“»; Ctrl/⌘ + щелчок и средняя кнопка открывают новую вкладку без поручения; ссылка неактивна до конца перехода (двойной щелчок)

- [x] 5.1 `openspec validate assistant-page` падал: в дельтах `visual-design` («Разделы в разработке») и `assistant-dialog` («Общий вопрос») в блоках MODIFIED были опущены сценарии текущей спецификации. Исправлено копированием полного блока; результат — valid. 2026-11-09: текст требования «Раздел „Ассистент“» сокращён до двух фраз, подробности — в сценарии «Тот же диалог, что в панели», «Свои сессии», «Без выделения и окна карточки», «После перезагрузки»; `openspec validate assistant-page` без предупреждений
- [ ] 5.2 Независимая перепроверка фиксов round-3 (FND-1…FND-4) тестировщиком — не проведена
- [x] 5.3 Запись в журнал решений `docs/design/design-system.md` («2026-11-08. Экран чтения: колонки, панель, ассистент»): K1–K4, полоска, 62ch, колонки без анимации, ход ответа, диалоги, граница книги
