# Tasks

Отметки актуализированы 2026-11-08 по коду и тестам (см. `progress.md`). До актуализации все пункты стояли `[ ]`, хотя код и тесты уже есть.

## 1. Задача и документы

- [x] 1.1 Изменение OpenSpec: `proposal.md`, `design.md`, `tasks.md`, дельта `chapter-reading`, `progress.md`, `qa/cases.md`; `openspec validate reader-notes` — valid

## 2. Сервер (N7)

- [x] 2.1 `model.py` `Block.detail_code`, `page`; `parse.py` ставит `blank_page`/`missing`/`figure`/`table` (`parse.py:347, 364`; `tests/library/test_unrendered_parts.py:34`)
- [x] 2.2 `schema.py`: колонка `detail_code` и миграция 4 (`schema.py:142, 283`); `PIPELINE_VERSION = "4"` (`processing.py:42`, `test_unrendered_parts.py:59`)
- [x] 2.3 `registry.py` и `reading.py`: сохранение и отдача `detail_code`/`page` (`registry.py:543, 617`, `reading.py:265-266`)

## 3. Сноски на поле и в окне

- [x] 3.1 `Footnote.tsx`: сноска на поле в K1 (номер и текст, подсветка пары), окно в K2–K4 (`test_footnotes_on_field_in_k1`, `test_footnote_popup_in_compact`). Клавиатура (поток C): K1 — Enter на знаке ставит фокус на сноску (`tabindex=-1`), Esc и Shift+Tab — обратно (`test_field_note_keyboard`); K2–K4 — Enter переводит фокус в окно со ссылками (`dialog`), Esc из окна закрывает и возвращает фокус на знак (`test_footnote_popup_keyboard`)
- [x] 3.2 `ReaderPage.tsx`: в K1 поле `.margin-col` с номерами страниц и сносками, в K2–K4 номера страниц в тексте (`test_page_numbers_field_vs_text`)
- [x] 3.3 Каскад сносок и «↑» при сдвиге > 240px: прежний `MarginCol` в `ReaderPage.tsx` не работал (у `<aside>` не было `ref`, все элементы поля стояли наверху колонки). Исправленный `MarginCol` и `fieldItems` перенесены в `Footnote.tsx` (пересчёт после `document.fonts.ready` и по `ResizeObserver` колонки текста); подключение в `ReaderPage.tsx` делает интегратор (см. `progress.md`). Тесты `test_three_notes_cascade_on_field`, `test_field_notes_follow_width_change`
- [x] 3.4 `styles.css`: правила поля сносок (`.field-note`, `.field-page`, `[data-nontext]`)
- [x] 3.5 Окно сноски по 4.3 (K2–K4): под строкой знака; не помещается — над ней (`note-popup--above`); не помещается и там — на большей стороне с прокруткой; правый край не заходит под правую панель или полоску (−16px), левый — не левее колонки текста; строку знака не закрывает (`Footnote.tsx` `popupPlace`; `test_footnote_popup_flips_above_near_bottom`, `test_footnote_popup_below_near_top`, `test_footnote_popup_clear_of_panel[1280/1024]`)

## 4. Неразобранные части

- [x] 4.1 Плашки по `detail_code`/`page`; EN-пояснения (`i18n/en.ts` `unrendered.*`, `test_unrendered_plate_localized`)
- [x] 4.2 `data-nontext` у плашек и номеров страниц (`ReaderPage.tsx:187, 734`); номер на поле K1 — `user-select: none` в `styles/notes.css`; невхождение в выделение — `test_page_numbers_level_and_not_selected`

## 5. Тесты и проверка

- [x] 5.1 Тесты T28–T30: `tests/web/test_reader_notes.py`, 9 тестов (поле K1, три сноски каскадом на 1920 и 1440, пересчёт при смене ширины, клавиатура K1 и K2, окно K3, страницы на поле и в тексте, невхождение номера в выделение, плашка RU/EN). 4 из них (`test_footnotes_on_field_in_k1`, `test_three_notes_cascade_on_field`, `test_field_notes_follow_width_change`, `test_page_numbers_level_and_not_selected`) проходят только после подключения `MarginCol` из `Footnote.tsx` в `ReaderPage.tsx`; с подключением проверено локально — 9 passed
- [ ] 5.2 Снимки поля сносок (1920, 1440) и окна сноски (1280, 1024) по 14.3 и их просмотр: сценарии есть в `tests/e2e/test_reader_snapshots.py` (`test_notes`), эталоны и просмотр — за интегратором
