# Tasks

Отметки актуализированы 2026-11-08 по коду и тестам (см. `progress.md`). До актуализации все пункты стояли `[ ]`, хотя код и тесты уже есть.

## 1. Задача и документы

- [x] 1.1 Изменение OpenSpec: `proposal.md`, `design.md`, `tasks.md`, дельта `chapter-reading`, `progress.md`, `qa/cases.md`; `openspec validate reader-notes` — valid

## 2. Сервер (N7)

- [x] 2.1 `model.py` `Block.detail_code`, `page`; `parse.py` ставит `blank_page`/`missing`/`figure`/`table` (`parse.py:347, 364`; `tests/library/test_unrendered_parts.py:34`)
- [x] 2.2 `schema.py`: колонка `detail_code` и миграция 4 (`schema.py:142, 283`); `PIPELINE_VERSION = "4"` (`processing.py:42`, `test_unrendered_parts.py:59`)
- [x] 2.3 `registry.py` и `reading.py`: сохранение и отдача `detail_code`/`page` (`registry.py:543, 617`, `reading.py:265-266`)

## 3. Сноски на поле и в окне

- [x] 3.1 `Footnote.tsx`: сноска на поле в K1 (номер и текст, подсветка пары), окно в K2–K4 (`test_footnotes_on_field_in_k1`, `test_footnote_popup_in_compact`). Enter↔Esc между знаком и сноской тестом не проверен
- [x] 3.2 `ReaderPage.tsx`: в K1 поле `.margin-col` с номерами страниц и сносками, в K2–K4 номера страниц в тексте (`test_page_numbers_field_vs_text`)
- [ ] 3.3 Каскад сносок и «↑» при сдвиге > 240px (`ReaderPage.tsx:279`, `Footnote.tsx:103-130`) есть в коде; теста на каскад трёх сносок в одном абзаце нет (T28), поэтому не отмечено
- [x] 3.4 `styles.css`: правила поля сносок (`.field-note`, `.field-page`, `[data-nontext]`)

## 4. Неразобранные части

- [x] 4.1 Плашки по `detail_code`/`page`; EN-пояснения (`i18n/en.ts` `unrendered.*`, `test_unrendered_plate_localized`)
- [x] 4.2 `data-nontext` у плашек и номеров страниц (`ReaderPage.tsx:187, 734`; тест проверяет плашку; невхождение в выделение руками не проверялось)

## 5. Тесты и проверка

- [ ] 5.1 Тесты T28–T30. Есть: `tests/web/test_reader_notes.py` (4 теста: поле K1, окно K2/K3, страницы, плашка RU/EN) — покрывают T28 частично, T29, T30. Не хватает: три сноски в абзаце, K2 с клавиатуры, невхождения номера страницы в выделение
- [ ] 5.2 Снимки поля сносок (1920, 1440) и окна сноски (1280, 1024) по 14.3 и их просмотр: эталонов нет
