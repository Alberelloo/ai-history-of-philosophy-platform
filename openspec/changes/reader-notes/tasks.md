# Tasks

## 1. Задача и документы

- [ ] 1.1 Изменение OpenSpec: `proposal.md`, `design.md`, `tasks.md`, дельта `chapter-reading`, `progress.md`, `qa/cases.md`; `openspec validate`

## 2. Сервер (N7)

- [ ] 2.1 `model.py` `Block`: поля `detail_code`, `page`; `parse.py` ставит коды `blank_page`/`missing`/`figure`/`table` и номер страницы
- [ ] 2.2 `schema.py`: колонки `detail_code`/`page` + миграция 4; `processing.py` `PIPELINE_VERSION` 4
- [ ] 2.3 `registry.py` и `reading.py`: сохранение и отдача `detail_code`/`page`

## 3. Сноски на поле и в окне

- [ ] 3.1 `Footnote.tsx`: сноска на поле в K1 (номер + текст, подсветка пары, Enter↔Esc), окно в K2–K4 по 4.3 (22rem, role tooltip/dialog)
- [ ] 3.2 `ReaderPage.tsx`: в K1 поле `.margin-col` с номерами страниц и сносками в порядке строк; в K2–K4 номера страниц в тексте
- [ ] 3.3 Каскад сносок (сдвиг вниз при наезде) и «↑» при сдвиге > 240px; положения — один проход после `document.fonts.ready`
- [ ] 3.4 `styles.css` (только в конец): правила поля сносок

## 4. Неразобранные части

- [ ] 4.1 Плашки по `detail_code`/`page`; EN-пояснения по каталогу (`unrendered.*`)
- [ ] 4.2 `data-nontext` у плашек и номеров страниц (не попадают в выделение)

## 5. Тесты и проверка

- [ ] 5.1 Тесты T28–T30 с `@req`; `check_traceability.py`
- [ ] 5.2 Итоговый прогон: сборка, pytest, ruff, прослеживаемость; снимки поля/окна сноски
