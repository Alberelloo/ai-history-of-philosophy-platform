# Progress: reader-layout

Этап 1 из 6 (`docs/design/features/reader-panels.md`, раздел 16). Актуализировано 2026-11-08 по коду. Готовность: около 85%.

## Статус по пунктам

| Пункт | Статус | Чем подтверждено |
| --- | --- | --- |
| 1.1 Изменение OpenSpec | сделано | `openspec validate reader-layout` — valid |
| 1.2 Документы дизайна | сделано | `docs/design/system/layout.md`, `components/SidePanel.md` |
| 2.1 Токены и rem | сделано | `web/src/styles/tokens.css` (`--margin-col: 18rem`), `tests/web/test_design_system.py` |
| 2.2 Общие экраны на rem | не начато | в стилях библиотеки, графа, настроек остались px; Р9 и T45 не закрыты |
| 3.1–3.3 Каркас панели | сделано | `web/src/SidePanel.tsx`, `App.tsx` (стек `panel.stack`), `test_panel_strip_on_narrow_screen` |
| 4.1–4.4 Раскладка K1–K4 | сделано | `web/src/layout.ts`, `test_layout_modes_and_text_measure` (1920/1440 K1, 1280 K2, 1024 K3, 62–68ch) |
| 5.1 Место чтения | частично | код есть; `test_reading_position_kept` не проверяет смену ширины и полную карточку (T4) |
| 5.2 Колонки без анимации | частично | в коде; теста T37 нет |
| 6.1 Тесты | частично | есть T1–T3; нет T5, T37, T45, T32 |
| 6.2 Снимки S0/S5/полоска | не начато | эталонов `reader-*` нет, 2560 не снимается |
| 6.3 Итоговый прогон | частично | tsc, ruff, прослеживаемость 322/322 зелёные; полный pytest не перезапускался |

## Сейчас

Раскладка и каркас панели работают и лежат в ветке `claude/reader-implementation`. Расхождение документов с кодом было в отметках тестов и снимков: в тексте они значились как готовые, а их нет.

## Следующий шаг

1. Тесты T5 (временное сворачивание навигации при открытой панели на 1440), T37 (ширина `article.chapter` во время открытия панели принимает два значения), T32 (слой оглавления на 1024), T4 в полном виде (20-й абзац, смена ширины 1440 → 1280).
2. 2.2 и T45: перевести библиотеку, граф, настройки на rem-токены, добавить 2560 в `visual.WIDTHS`.
3. Эталоны S0, S5, полоски по 14.3 и их просмотр человеком.

## Известные проблемы

- Без `TMP`/`TEMP` в рабочей папке Chromium не запускается, браузерные тесты молча пропускаются.
- Пиксельный просмотр снимков человеком не проводился.
- Старые эталоны (`chapter-light-1920.png` и др.) названы не по схеме 14.3.

## Как проверить

```bash
export TMP="$(pwd -W)/.stack/tmp"; export TEMP="$TMP"; mkdir -p "$TMP"
/c/Users/Ivano/AppData/Local/Programs/openspec/openspec validate reader-layout
.venv/Scripts/python -m pytest -q tests/web/test_reader_layout.py
.venv/Scripts/python scripts/check_traceability.py
cd web && npx tsc --noEmit
```
