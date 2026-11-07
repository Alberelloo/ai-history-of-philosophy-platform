# Задачи: assistant-page

## 1. Сервер

- [x] 1.1 N12: поле `context: "book" | "library"` в `AskRequest` (по умолчанию `"library"`), `handoff_declined`/`handoff_reason`
- [x] 1.2 Событие `{"type": "handoff", "reason": "broader" | "outside_book"}` при `context: "book"` (`broader` — вид `other_authors` без составления; `outside_book` — ответ без фрагментов на абзацы книги)

## 2. Страница раздела

- [x] 2.1 `AssistantPage.tsx`: диалог `libraryDialogs`, сессии, стадии, пометки, `ScopeToggle`, прилепленная форма, строка «только по источникам»
- [x] 2.2 Маршрут `/assistant` в `App.tsx`, `activeItem` отмечает `assistant`, `/soon/assistant` → `/assistant` (`replaceState`), `SoonPage` для `assistant` удалён
- [x] 2.3 `Sidebar.tsx`: пункт «Ассистент» ведёт на `/assistant`

## 3. Граница и поручение

- [x] 3.1 Блок S7a в `AssistantPanel.tsx`: текст по причине, «Продолжить в рамках этого источника» (`handoff.choice="book"`), ссылка «Перейти в «Ассистент»…» (`handoff.choice="library"`)
- [x] 3.2 Поручение перехода в памяти вкладки, отправка один раз по условиям 5.10, `handoffId` в `libraryDialogs`
- [x] 3.3 i18n: `assistant.handoff.*`

## 4. Тесты

- [x] 4.1 T36, T41–T43, T46 зелёные; снимки страницы «Ассистент» 1024 и 1920, обе темы
- [x] 4.2 Прослеживаемость 100%
