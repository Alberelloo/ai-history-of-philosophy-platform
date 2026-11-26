# Progress

Ведущий: основная сессия (скилл `change-loop`). Роли — субагенты из `.claude/agents/`.

## 2026-11-26 — предложение (разработчик, субагент `coder`, круг 1)

- Ветка `claude/historical-polities` от `origin/claude/embedding-docker`, работа в корне репозитория.
- CLI `openspec` не использовался: файлы созданы вручную по образцу `archive/2026-11-26-rework-globe-political-map`. Тексты MODIFIED-требований взяты из `openspec/specs/geo-timeline/spec.md` скриптом (дословно), правки внесены точечными заменами. Каждая замена проверена на единственность вхождения.
- Сделано: 1.1 — `owner-spec.md` (копия `/root/PHILO-SPEC-POLITIES.md`; в репозитории тот же текст лежит в `docs/process/spec-historical-political-map.md`, `diff` пуст), `proposal.md`, `design.md`, `specs/geo-timeline/spec.md` (6 ADDED, 6 MODIFIED), `tasks.md`, этот журнал.
- Проверено при выборе решения (сеть, 2026-11-26):
  - Zenodo, версии концепт-записи 13363121: v0.0.1 (49,2 МБ) … v0.2.2 (запись 24518977, DOI `10.5281/zenodo.24518977`, 2026-11-25, архив 300 МБ из-за `original_map_images`). Авторы v0.2.2: Ed Chalstrey, James Bennett. Лицензия `cc-by-4.0`;
  - GitHub, тег v0.2.2: `cliopatria.geojson.zip` 47 151 553 байт;
  - сервер: 1 CPU, 1967 МБ ОЗУ, из них доступно ~667 МБ при работающем стенде; на диске свободно 13 ГБ.
- Отступления от ориентиров ведущего, с обоснованием в design.md: версия v0.2.2 вместо v0.0.1 (решение 1); записи RELATION не берутся (решение 2); кэш по интервалу постоянного набора, а не по году (выбор 3); `compose.yaml` не трогаем (решение 9). Остальные ориентиры приняты: данные в `data/cliopatria/`, метки `ru` Wikidata на сборке, фикстура в `tests/`, замеры отдельной задачей.
- Новые события журнала (по дельте): `knowledge.polities.built`, `knowledge.polities.served`, `knowledge.polities.unavailable`, `knowledge.polities.rejected`, `knowledge.polities.measured`.
- Известное: `check_traceability.py` будет красным, пока тестировщик не добавит тесты 6 новых требований (6.x).

Статус: 1.1 — сделан; 1.2 — следующий (ревью плана); 2.x–11.x — не начаты.
