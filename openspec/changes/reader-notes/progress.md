# Progress: reader-notes

Этап 5 из 6. Актуализировано 2026-11-08 по коду. Готовность: около 90% (прежний `progress.md` говорил «не начато», это было неверно).

## Статус по пунктам

| Пункт | Статус | Чем подтверждено |
| --- | --- | --- |
| 1.1 OpenSpec | сделано | `openspec validate reader-notes` — valid |
| 2.1 N7 коды и страница в разборе | сделано | `parse.py:347, 364`, `tests/library/test_unrendered_parts.py:34` |
| 2.2 Схема, миграция 4, конвейер 4 | сделано | `schema.py:142, 283`, `processing.py:42`, `test_unrendered_parts.py:59` |
| 2.3 Хранение и отдача | сделано | `registry.py:543, 617`, `reading.py:265-266` |
| 3.1 Сноски на поле и в окне | сделано | `web/src/Footnote.tsx`, `test_footnotes_on_field_in_k1`, `test_footnote_popup_in_compact` |
| 3.2 Поле и номера страниц | сделано | `ReaderPage.tsx:286-299`, `test_page_numbers_field_vs_text` |
| 3.3 Каскад и «↑» | частично | в коде (`ReaderPage.tsx:279`, `Footnote.tsx:103-130`); теста на три сноски нет |
| 3.4 Стили | сделано | `styles.css` (`.field-note`, `.field-page`, `[data-nontext]`) |
| 4.1 Плашки по коду, EN | сделано | `i18n/en.ts` `unrendered.*`, `test_unrendered_plate_localized` |
| 4.2 `data-nontext` | сделано | `ReaderPage.tsx:187, 734` |
| 5.1 Тесты T28–T30 | частично | 4 теста в `tests/web/test_reader_notes.py` покрывают T29, T30 и часть T28 |
| 5.2 Снимки | не начато | эталонов поля сносок и окна сноски нет |

## Сейчас

Функциональность этапа в коде и тестах закрыта, осталась проверка каскада, клавиатуры и снимки.

## Следующий шаг

1. Расширить T28: абзац с тремя сносками (каскад, подсветка пары), K2 с клавиатуры (Enter и Esc), «↑» при сдвиге больше 240px.
2. T29: проверить, что номер страницы не попадает в выделение и копирование.
3. Снимки поля сносок (1920, 1440) и окна сноски (1280, 1024), просмотр человеком.

## Известные проблемы

- Сквозной `test_reading_journey` в `tests/e2e/test_site.py` тоже трогает сноски; изменения вёрстки поля могут ломать его.
- Положение сносок считается один раз после загрузки шрифтов; при смене ширины пересчёт не проверялся тестом.

## Как проверить

```bash
export TMP="$(pwd -W)/.stack/tmp"; export TEMP="$TMP"; mkdir -p "$TMP"
/c/Users/Ivano/AppData/Local/Programs/openspec/openspec validate reader-notes
.venv/Scripts/python -m pytest -q tests/web/test_reader_notes.py tests/library/test_unrendered_parts.py
.venv/Scripts/python scripts/check_traceability.py
```
