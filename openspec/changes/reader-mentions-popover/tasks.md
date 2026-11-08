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
- [x] 4.3 Стек «Назад» в окне; повторный щелчок закрывает окно (повторный щелчок сделан в 5.4)
- [x] 4.4 Загрузка и ошибки по 4.7: S2, S3, S3a с «Повторить»
- [x] 4.5 Кэш карточек до 50 (`CardPopup.tsx:62`) и `AbortController`

## 5. Тесты и проверка

- [x] 5.1 Тесты T6–T11, T15 — `tests/web/test_reader_cards.py` (сервер знаний подменён `page.route`): T6 `test_t6_mentions_are_buttons_and_absent_without_service`; T7 `test_t7_family_colour[light|dark]`; T8 `test_t8_hover_never_opens_card`, `test_t8_popover_beside_mention_line[1920|1440|1280|1024]`, `test_t8_close_by_esc_outside_and_repeated_click`, `test_t8_drag_selection_from_mention_does_not_open`; T9 `test_t9_popover_flips_above_line_at_bottom`; T10 `test_t10_link_and_back_in_popover_and_panel`; T11 `test_t11_popover_contents`; T15 `test_t15_loading_not_found_and_failure[ru-RU|en-US]`
- [x] 5.3 N11: клиент делит `/mentions` на части по 500 параллельно, ответ прежней главы отбрасывается (`ReaderPage.tsx`, `MENTIONS_CHUNK`); тест `test_n11_mentions_requested_in_parts_of_500` (глава 1100 абзацев → 3 запроса)
- [x] 5.4 Доведено по 4.2–4.7, найдено тестами: Esc закрывает окно и возвращает фокус на упоминание; щелчок мимо закрывает; повторный щелчок по упоминанию закрывает; протяжка с упоминания не открывает окно; Enter/Space переводят фокус на заголовок окна; Tab из последнего элемента закрывает окно, Shift+Tab из первого — на упоминание; `aria-haspopup`, `aria-expanded`, `aria-controls`; опорная строка — `getClientRects()` под указателем; K2–K4 — переворот вверх и `max-height` по большей стороне, строка не перекрывается никогда; пересчёт при изменении ширины и колонок; уход строки из вида закрывает окно; S2 — имя из упоминания вместо «…», «Загружаем карточку…» через 300 мс; «Повторить» действительно повторяет запрос (раньше эффект не перезапускался); до двух утверждений — по порядку «проверенные, по источникам, остальные», а не только из первой непустой группы
- [ ] 5.2 Снимки S1, S2, S3, S3a по 14.3: эталонов `reader-*` нет; просмотр не проведён
