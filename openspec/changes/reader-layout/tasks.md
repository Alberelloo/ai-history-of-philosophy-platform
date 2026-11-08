# Tasks

Отметки актуализированы 2026-11-08 по коду и тестам (см. `progress.md`). `[x]` — подтверждено файлом или тестом.

## 1. Задача и документы

- [x] 1.1 Изменение OpenSpec: `proposal.md`, `design.md`, `tasks.md`, дельты `visual-design` и `assistant-dialog`, `progress.md`, `qa/cases.md`; `openspec validate reader-layout` — valid
- [x] 1.2 Документы дизайна: `layout.md`, `components/SidePanel.md`, `brandbook.md` («Движение»), `components/Sidebar.md` (временное сворачивание закрепления)

## 2. Токены и масштаб

- [x] 2.1 Токены `measure-min`, `panel-strip`; размеры в `rem`; корневой кегль `clamp(100%, 53.1% + 0.39vw, 116%)`; `tokens.css` перегенерирован из `tokens.json` (`tests/web/test_design_system.py`)
- [x] 2.2 Общие экраны (библиотека, граф, настройки, навигация, экран чтения) в `styles.css` — размеры в `rem` (74 строки px → rem, значения до 1920 те же); px только у линий, радиусов, теней и 1px (`test_styles_sizes_in_rem`, `test_scale_across_product` на 1280/1920/2560). Остаток вне файлов потока C — `styles/components.css` и узлы графа в `GraphPage.tsx` (см. `progress.md`)

## 3. Каркас панели

- [x] 3.1 Состояние панели выше `ReaderPage` (в `App.tsx`): `mode`, стек, открыватель; шапка панели, «Назад», «×»
- [x] 3.2 `SidePanel` с режимами «сдвиг» (≥1280) и «полоска» (1024–1279): разворот по щелчку, Esc, «Свернуть», щелчок/фокус в тексте
- [x] 3.3 Перенос `AssistantPanel` в каркас панели без изменения поведения; `CardPopup` остаётся окном у упоминания (этап 2)

## 4. Раскладка K1–K4

- [x] 4.1 Выбор раскладки по свободной ширине `A` и фактическим ширинам элементов; распределение лишней ширины (`web/src/layout.ts`; `tests/web/test_reader_layout.py::test_layout_modes_and_text_measure`)
- [x] 4.2 Оглавление: полное (K1/K2), полосой (K3), слой и кнопка «Оглавление» (K4)
- [x] 4.3 Поле сносок (`margin-col`) в K1 резервирует место
- [x] 4.4 Временное сворачивание закреплённой навигации при нехватке места; `aria-disabled` на «Закрепить»

## 5. Место чтения

- [x] 5.1 Привязка места чтения при открытии/закрытии панели и смене ширины (2.5): прежний код в `ReaderPage.tsx` запоминал опорный абзац только при перестройке, после прокрутки открытие панели отбрасывало читателя назад (T4 падал на 1500px). Исправление — `web/src/hooks/useReadingAnchor.ts` (запоминание при прокрутке), подключение — интегратор (см. `progress.md`); тест `test_reading_place_kept` (T4)
- [x] 5.2 Колонки без анимации ширины (Р7); анимируется только панель (`dur-slow`); тест `test_columns_do_not_animate` (T37)

## 6. Тесты и проверка

- [x] 6.1 Тесты по требованиям дельт. T1, T2, T3 — `tests/web/test_reader_layout.py`; T4, T5, T32, T37, T45 — `tests/e2e/test_reader_layout.py` (поток C). T4 и T32 проходят только после подключения `useReadingAnchor`, `useTocLocation` и `Toc` из `ReaderToc.tsx` в `ReaderPage.tsx` (проверено локально с подключением: все зелёные). `check_traceability.py` — 322 из 322
- [ ] 6.2 Снимки по 14.3 (S0, S5, полоска; имена `reader-<состояние>-<тема>-<язык>-<ширина>.png`): в `tests/e2e/visual/baselines/` лежат только старые эталоны (`chapter-*`, `card-*`, `assistant-*`); ширины 2560 в проверках нет; просмотр человеком не проведён
- [x] 6.3 Прогон при актуализации: `tsc --noEmit` без ошибок, `ruff check src tests scripts` и `ruff format --check` чистые, прослеживаемость 322/322; полный pytest и `vite build` в этой актуализации не запускались
