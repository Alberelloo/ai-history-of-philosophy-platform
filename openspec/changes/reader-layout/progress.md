# Progress: reader-layout

## Кто ведёт

Сессия lead (разработчик) по регламенту dev-cycle. Проверку проводит тестировщик + судья через `dev_cycle`.

## Статус задач (`tasks.md`)

- 1.1 Изменение OpenSpec — готово: `openspec validate reader-layout` → valid.
- 2.1 Токены — готово: `measure-min`, `panel-strip`; размеры и шрифты в `rem`; корневой кегль `clamp(100%, 53.1% + 0.39vw, 116%)`; `tokens.css` перегенерирован (`design_tokens.py --check` → ok).
- 3.1–3.3, 4.1–4.4, 5.1–5.2 — готово (каркас панели, раскладка K1–K4, привязка места чтения).
- 1.2, 2.2, 6.x — не начаты.

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
- Полный pytest и `python scripts/check_traceability.py` после реализации.
