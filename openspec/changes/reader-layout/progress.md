# Progress: reader-layout

## Кто ведёт

Сессия lead (разработчик) по регламенту dev-cycle. Проверку проводит тестировщик + судья через `dev_cycle`.

## Статус задач (`tasks.md`)

- 1.1 Изменение OpenSpec — в работе: созданы `proposal.md`, `design.md`, `tasks.md`, дельты `visual-design` и `assistant-dialog`, `qa/cases.md`, `progress.md`. `openspec validate` не запускался.
- 1.2–6.3 — не начаты.

## Этап 0 (предусловие)

- Слит `claude/design-system` (redesign-navigation, PR #28) в `claude/reader-design` — коммит `a40b5c0 Merge branch 'claude/design-system' into claude/reader-design`. В дереве появились `web/src/Sidebar.tsx`, `web/src/SoonPage.tsx`, хранилище формата 3, заглушки необработанных частей.

## Что сделано

1. Прочитан дизайн-документ `docs/design/features/reader-panels.md` (v1.2, разделы 1–16) целиком.
2. Прочитаны текущие спецификации (`visual-design`, `assistant-dialog`), код (`App.tsx`, `ReaderPage.tsx`, `storage.ts`), токены (`tokens.css`, `scripts/design_tokens.py`), документы дизайна (`layout.md`, `components/SidePanel.md`).
3. Заведено изменение OpenSpec `reader-layout` (этап 1): артефакты выше.

## Следующий шаг

1. `openspec validate reader-layout` и правка замечаний.
2. Реализация этапа 1 по `tasks.md` (токены → каркас панели → раскладка K1–K4 → привязка места чтения → тесты).
3. Раунд проверки `dev_cycle`.

## Известные проблемы

- `pnpm` не установлен; сборка клиента — `cd web && npm run build` (npm есть, node v24).
- Эталонные снимки раскладки K1–K4 ещё не сделаны (будут после просмотра в разделе 6.2).

## Как проверить

- `openspec validate reader-layout`
- `cd web && npm run build`
- `python scripts/design_tokens.py --check`
- Полный pytest и `python scripts/check_traceability.py` после реализации.
