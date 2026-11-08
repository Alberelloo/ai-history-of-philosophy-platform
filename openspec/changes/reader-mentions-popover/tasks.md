# Tasks

Отметки актуализированы 2026-11-08 по коду и тестам (см. `progress.md`). `[x]` — подтверждено файлом или тестом.

## 1. Задача и документы

- [x] 1.1 Изменение OpenSpec: `proposal.md`, `tasks.md`, дельты `entity-mentions`, `entity-cards`, `reader-settings`, `progress.md`, `qa/cases.md`; `openspec validate reader-mentions-popover` — valid
- [x] 1.2 Документ дизайна: `components/Popover.md`

## 2. Сервер

- [x] 2.1 N1: `/mentions` отдаёт `entity_type` (`src/philograph/knowledge/mentions.py:323`, `tests/knowledge/test_mentions_cards.py:232`)
- [x] 2.2 N2: `/entities/{id}/card` отвечает 404 `kind: "entity_not_found"` (`test_card_not_found_returns_404`)

## 3. Упоминания

- [x] 3.1 Упоминание — `span role="button" tabindex="0"` (`ReaderPage.tsx:146`); Enter/Space открывают
- [x] 3.2 Цвет семьи через `familyOf(entity_type)` (`ReaderPage.tsx:150`)
- [x] 3.3 Настройка `mentions: "underline" | "hover"` в `storage.ts` и на экране настроек (`SettingsPage.tsx`), `data-mentions="quiet"`

## 4. Окно карточки

- [x] 4.1 Положение по 4.3 в `CardPopup.tsx`
- [x] 4.2 Состав по 4.4: строка действий, голова, описание, до двух утверждений, «Открыть карточку»
- [x] 4.3 Стек «Назад» в окне; повторный щелчок закрывает окно
- [x] 4.4 Загрузка и ошибки по 4.7: S2, S3, S3a с «Повторить»
- [x] 4.5 Кэш карточек до 50 (`CardPopup.tsx:62`) и `AbortController`

## 5. Тесты и проверка

- [ ] 5.1 Тесты T6–T11, T15. Есть только сквозной `tests/e2e/test_site.py::test_mention_opens_card_and_navigates` (щелчок, до 2 утверждений, нет переключателей, описание, полная карточка) и серверные N1/N2. Нет: T6 (отказ сервиса знаков), T7 (цвет семьи), T8 (наведение не открывает), T9 (переворот вверх), T10 («Назад» в окне), T11 (портрет в окне), T15 (S2/S3/S3a через `route`)
- [ ] 5.2 Снимки S1, S2, S3, S3a по 14.3: эталонов `reader-*` нет; просмотр не проведён
