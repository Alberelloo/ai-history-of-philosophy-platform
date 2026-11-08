# Progress: reader-notes

Этап 5 из 6. Ведёт поток C (`claude/reader-wt-layout`). Обновлено 2026-11-08. Готовность: код и тесты закрыты, осталось подключение `MarginCol` интегратором и снимки.

## Статус по пунктам

| Пункт | Статус | Чем подтверждено |
| --- | --- | --- |
| 1.1 OpenSpec | сделано | `openspec validate reader-notes` — valid |
| 2.1 N7 коды и страница в разборе | сделано | `parse.py:347, 364`, `tests/library/test_unrendered_parts.py:34` |
| 2.2 Схема, миграция 4, конвейер 4 | сделано | `schema.py:142, 283`, `processing.py:42`, `test_unrendered_parts.py:59` |
| 2.3 Хранение и отдача | сделано | `registry.py:543, 617`, `reading.py:265-266` |
| 3.1 Сноски на поле и в окне, клавиатура | сделано | `web/src/Footnote.tsx`; `test_field_note_keyboard`, `test_footnote_popup_keyboard` |
| 3.2 Поле и номера страниц | сделано | `test_page_numbers_field_vs_text`, `test_page_numbers_level_and_not_selected` |
| 3.3 Каскад и «↑» | сделано в `Footnote.tsx`, ждёт подключения | `test_three_notes_cascade_on_field`, `test_field_notes_follow_width_change` |
| 3.4 Стили | сделано | `styles.css` (`.field-note`, `.field-page`, `[data-nontext]`), новый `styles/notes.css` (фокус сноски и окна, номер на поле вне выделения) |
| 4.1 Плашки по коду, EN | сделано | `i18n/en.ts` `unrendered.*`, `test_unrendered_plate_localized` |
| 4.2 `data-nontext` | сделано | `ReaderPage.tsx:187, 734`, `test_page_numbers_level_and_not_selected` |
| 5.1 Тесты T28–T30 | сделано | 9 тестов в `tests/web/test_reader_notes.py` |
| 5.2 Снимки | не начато | эталоны пересоздаёт интегратор после слияния (правило 6) |

## Найденная ошибка

Поле сносок в K1 не работало: в `ReaderPage.tsx` у `<aside className="margin-col">` нет `ref={root}`, поэтому `MarginCol` не находил ни одного элемента и все сноски и номера страниц стояли наверху колонки (translateY(0)). Прежний тест `test_footnotes_on_field_in_k1` этого не ловил: он проверял только «верх сноски не ниже верха знака + 4px», что выполняется и для сноски на самом верху. Тест исправлен (сноска не выше своей строки и без «↑»).

## Для интегратора: подключение в `ReaderPage.tsx` (файл потока B)

Исправленные `MarginCol`, `fieldItems` и тип `FieldItem` экспортируются из `web/src/Footnote.tsx` с той же сигнатурой. В `ReaderPage.tsx`:

1. Строку `import { FieldNote } from "./Footnote";` заменить на `import { fieldItems, MarginCol } from "./Footnote";`.
2. Удалить локальные `type FieldItem`, `function fieldItems` и `function MarginCol` (между «// Что стоит на поле сносок в K1» и `function copyLink`, функцию `unrenderedDetail` между ними оставить).

Вызов `<MarginCol items={fieldItems(chapter)} noteActive={noteActive} onActive={setNoteActive} />` не меняется. Проверено локально: с этой правкой `tsc --noEmit` чистый, `tests/web/test_reader_notes.py` — 9 passed. Без неё 4 теста поля падают (`test_footnotes_on_field_in_k1`, `test_three_notes_cascade_on_field`, `test_field_notes_follow_width_change`, `test_page_numbers_level_and_not_selected`).

Что изменилось в новом `MarginCol`: `ref` на `<aside>`; отсчёт от верха самого поля, а не статьи; якорь сноски ищется внутри `article.chapter` (`.note-ref[data-note-id]`), а не первым совпадением в документе; пересчёт после `document.fonts.ready` и по `ResizeObserver` колонки текста (6.1: смена ширины и высоты текста); состояние обновляется только при изменении положений (без цикла отрисовок, хотя `fieldItems` пересоздаёт список); промежуток 12px и порог 240px растут с корневым кеглем (9.7).

Подключение CSS: `import "./styles/notes.css";` в `web/src/main.tsx` после `./styles.css` (сделано в ветке потока).

## Следующий шаг

1. Интегратор: подключение выше, затем снимки поля сносок (1920, 1440) и окна сноски (1280, 1024) по 14.3 и их просмотр.

## Известные проблемы

- Сквозной `test_reading_journey` в `tests/e2e/test_site.py` тоже трогает сноски; после подключения нового `MarginCol` его стоит прогнать.
- Окно сноски (K2–K4) ставится под знаком от левого края `.note`; правила 4.3 (над строкой при нехватке места снизу, не заходить под панель) не реализованы.

## Как проверить

```bash
export TMP="$(pwd -W)/.stack/tmp"; export TEMP="$TMP"; mkdir -p "$TMP"
/c/Users/Ivano/AppData/Local/Programs/openspec/openspec validate reader-notes
.venv/Scripts/python -m pytest -q tests/web/test_reader_notes.py tests/library/test_unrendered_parts.py
.venv/Scripts/python scripts/check_traceability.py
```
