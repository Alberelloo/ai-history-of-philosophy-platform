# Progress

Ведущий: основная сессия (скилл `change-loop`). Роли — субагенты из `.claude/agents/`.

## 2026-11-25 — предложение (разработчик, субагент `coder`, круг 1)

- Ветка `claude/globe-political-map`, рабочая копия — git worktree `.claude/worktrees/globe`, основа — `origin/claude/embedding-docker`. В корень репозитория не заходил: там параллельная сессия по онтологии.
- CLI `openspec` не использовался: файлы созданы вручную по образцу `archive/2026-11-25-add-geo-timeline`. `openspec validate` не прогонялся, формат сверен чтением с `docs/process/openspec-workflow.md`. Имена MODIFIED-требований скопированы из `openspec/specs/geo-timeline/spec.md` дословно.
- Сделано: 1.1 — `proposal.md`, `design.md`, `specs/geo-timeline/spec.md` (5 ADDED, 9 MODIFIED), `tasks.md`, этот журнал.
- Замеры для выбора решения (на этой ветке):
  - `gzip -9c` файлов `world-atlas@2.0.2`: `land-110m` 20 722 Б, `countries-110m` 38 495 Б, `countries-50m` 229 996 Б;
  - `npm run build`: `GlobeView-*.js` 36 789 Б gzip -9, основной `index-*.js` 155 747 Б;
  - `countries-110m`: 177 стран, у 3 нет `id` (N. Cyprus, Somaliland, Kosovo), объекты `countries` и `land`;
  - `d3.geoContains` на 28 городах: 26 попали в многоугольник. Женева и Самос попали не в ту страну (Франция, Турция). Сиракузы вне многоугольников, ближайшая вершина — Италия, 6 км. Кос вне многоугольников, ближайшая вершина — Турция, 41 км, неверно. Точка (0, −30) в океане: ближайшая вершина в 841 км.
- Бэкенд не меняется: `portrait`, `label` и `short` есть в `/map` (`knowledge/map.py::_with_portraits`), страна определяется на клиенте. Новых событий журнала нет.
- Решения без владельца — в `design.md`, одноимённый раздел (13 пунктов).
- Известное: `check_traceability.py` будет красным, пока тестировщик не добавит тесты 5 новых требований (5.x).

Статус: 1.1 — сделан; 1.2 — следующий (ревью плана); 2.x–8.x — не начаты.
