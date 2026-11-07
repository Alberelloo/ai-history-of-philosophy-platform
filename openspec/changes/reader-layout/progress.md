# Progress: reader-layout

## Кто ведёт

Сессия lead (разработчик) по регламенту dev-cycle. Проверку проводит тестировщик + судья через `dev_cycle`.

## Статус задач (`tasks.md`)

- 1.1 Изменение OpenSpec — готово: `openspec validate reader-layout` → valid.
- 2.1 Токены — готово: `measure-min`, `panel-strip`; размеры и шрифты в `rem`; корневой кегль `clamp(100%, 53.1% + 0.39vw, 116%)`; `tokens.css` перегенерирован.
- 3.1–3.3, 4.1–4.4, 5.1–5.2 — готово.
- 1.2 Документы дизайна — готово (`layout.md`, `SidePanel.md`, `brandbook.md`, `Sidebar.md`).
- 6.x Тесты и проверка — готово: `check_traceability.py` 316/316, pytest (353 не-e2e + 56 e2e) зелёный, ruff зелёный, снимки обновлены.
- 2.2 — токены в `rem` и общий корневой кегль сделаны; полная зачистка px в стилях неэкранных страниц (библиотека/граф/настройки) — отдельное изменение.

## Следующий шаг

1. Раунд проверки `dev_cycle` (этап 1).
2. Дополнительные тесты T4 (привязка места), T5 (временное сворачивание), T37 (без анимации), T45 (масштаб 2560) — заложены в кейсы, реализуются при dev_cycle.
3. Этапы 2–6.

## Известные проблемы

- Браузерные тесты в этой сессии требуют перенаправления `TEMP`/`TMP` в рабочую папку (Playwright запускает Chromium, который не может создать каталог в `AppData\Local\Temp`); команда запуска: `$env:TEMP="$pwd\.stack\tmp"; $env:TMP=$env:TEMP; pytest …`.
- Визуальные снимки обновлены и проверены DOM-проверками (нет наложений, нет прокрутки, текст 62–68ch, контраст ≥ 4.5); попиксельный просмотр эталонов человеком — при слиянии PR.
- Инварианты раскладки проверены node-скриптом `web/.stack/layout-check/check.mjs` (12 случаев из 2.4) — зелёные.

## Этап 0 (предусловие)

- Слит `claude/design-system` (redesign-navigation, PR #28) в `claude/reader-design` — коммит `a40b5c0 Merge branch 'claude/design-system' into claude/reader-design`. В дереве появились `web/src/Sidebar.tsx`, `web/src/SoonPage.tsx`, хранилище формата 3, заглушки необработанных частей.

## Что сделано

1. Прочитан дизайн-документ `docs/design/features/reader-panels.md` (v1.2, разделы 1–16) целиком.
2. Прочитаны текущие спецификации (`visual-design`, `assistant-dialog`), код (`App.tsx`, `ReaderPage.tsx`, `storage.ts`), токены (`tokens.css`, `scripts/design_tokens.py`), документы дизайна (`layout.md`, `components/SidePanel.md`).
3. Заведено изменение OpenSpec `reader-layout` (этап 1): артефакты выше.

## Следующий шаг

1. Документы дизайна (1.2): `layout.md`, `components/SidePanel.md`, `brandbook.md` («Движение»), `components/Sidebar.md`.
2. Тесты (6.x): юнит-тест раскладки (инварианты 2.4), e2e T1–T5/T31–T33/T37/T45, визуальные снимки.
3. Раунд проверки `dev_cycle`.

## Известные проблемы

- Сборка `vite build` в песочнице падает на `spawn EPERM` (esbuild запускает дочерний процесс с piped stdio — задокументированная граница песочницы). `tsc --noEmit` и Python-проверки работают; для визуальных/e2e прогонов нужен запуск вне этой границы.
- Инварианты раскладки проверены node-скриптом `web/.stack/layout-check/check.mjs` (12 случаев из 2.4: режим, сумма колонок, диапазон текста/оглавления) — все зелёные.
- Эталонные снимки раскладки K1–K4 ещё не сделаны (будут после просмотра в разделе 6.2).

## Как проверить

- `openspec validate reader-layout`
- `cd web && npm run build`
- `python scripts/design_tokens.py --check`
- `python scripts/check_traceability.py`
- `ruff check .` / `ruff format --check .`
- `pytest -q -m "not e2e"` и `pytest -q tests/e2e` (с перенаправлением TEMP для Chromium)
