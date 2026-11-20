# Progress

Ведёт: субагент-разработчик, поток C0, ветка `claude/traceability-scenarios`.

## 2026-11-19 — предложение и скрипт (1.1–1.5, 5.1)

- Изменение заведено: proposal, design («Выбор решения» по шести решениям), дельты `service-runtime` («Прослеживаемость требований тестами») и `visual-design` («Визуальная проверка»), tasks.
- `scripts/check_traceability.py` переписан:
  - разбирает сценарии, параметры маркера, тесты, которые соберёт pytest, и проверку журнала (AST с обходом помощников до глубины 3);
  - флаги `--report`, `--junit`, `--junit-report`;
  - `main()` принимает список аргументов: старые тесты в `tests/platform/test_runtime.py` зовут `tr.main()` без аргументов и проходят.
- Итог на репозитории: `Требований с тестами: 350 из 350`, `Сценариев с тестами: 0 из 611`, `Требований с проверкой журнала: 155 из 350`, `Нормативных тестов: 0`, код возврата 0. Ошибок нового разбора (маркер не на тесте, нерешённый маркер) в репозитории нет. В аудите было 156 из 350: правило подсчёта немного другое, расхождение в одно требование.
- `--report`: событий каталога без проверки в тестах 29 из 145, список совпадает с аудитом 4.3.
- Статический каталог по `define("…")` совпадает с каталогом после загрузки всех модулей `philograph`: 145 и 145, разница пустая. Это проверяет юнит-тест.
- `openspec/traceability.yaml`: `enforce_scenarios: []`, `enforce_log: []`.
- `tests/platform/test_traceability.py`: 17 юнит-тестов, все прошли. Маркеры только на требование, без `scenario=`: сценарные тесты пишет тестировщик.
- Мутации (сценарий `/tmp/.../scratchpad/c0_mutate.sh`), каждая роняет тесты:
  - опечатка сценария не проверяется — 1 failed;
  - `events.*` не считается журналом — 3 failed;
  - маркеры не на тестах молча — 1 failed;
  - пропуск в junit не ошибка — 1 failed;
  - помощники не обходятся — 1 failed.
- `test_every_catalog_event_is_emitted_somewhere` выдаёт предупреждение со списком 29 событий и проходит.

## 2026-11-19 — фикстура стенда (3.1–3.2)

- `tests/e2e/conftest.py`: `start_dev_stack()` (окружение через `MonkeyPatch.context()`), `stack` на сессию, `site` на сессию = `stack`. Копии `site` удалены из `test_visual_design.py`, `test_reader_snapshots.py`, `test_reader_layout.py`. В `test_catalog_ingest.py` `own_stack` поднимается через `start_dev_stack`, а локальный сайт-источник переименован в `book_site`.
- Снимочные модули прошли на общей фикстуре (см. ниже).

## 2026-11-19 — эталоны Linux (2.1)

- `PHILOGRAPH_UPDATE_SNAPSHOTS=1 python scripts/visual_check.py --no-build`: `2 failed, 62 passed` за 9:50. Оба падения — тайм-ауты Playwright (элемент «не стабилен», заголовок главы не появился за 15 с) при load average около 17 на одном ядре: параллельно работали другие агенты.
- Повтор двух упавших с `UPDATE=1`: `3 passed`. Всего эталонов: 180.
- Два прогона сравнения подряд с `PHILOGRAPH_REQUIRE_SNAPSHOTS=1` (`test_visual_design.py`, `test_reader_snapshots.py`):
  - прогон 1: `1 failed, 55 passed` за 12:57;
  - прогон 2: `5 failed, 51 passed` за 27:41.
  
  Все падения — `TimeoutError` (goto или wait_for_selector), ни одного «отличается … пикселей», ни одного «нет эталона». `tests/e2e/visual/results/` после прогонов пуст: каждый снятый снимок совпал с эталоном.
- Находка: эталоны `win32` устарели. В них есть `chapter-light-1600`, которого тесты больше не снимают, и нет шести снимков карты (`map-*`).

## 2026-11-20 — CI, обязательные снимки, документы (1.6, 2.2, 2.3, 4.1, 6.1)

- `tests/e2e/visual.py`: `PHILOGRAPH_REQUIRE_SNAPSHOTS=1` — без эталона `SnapshotMissing` (подкласс `SnapshotMismatch`, поэтому `Snaps` собирает его в общий список), снимок остаётся в `results/`. Юнит-тесты без браузера — `tests/e2e/test_visual_helpers.py`, 3 passed.
- `.github/workflows/ci.yml` — только новые шаги:
  - в начале `checks` и `e2e`: `PHILOGRAPH_REQUIRE_SNAPSHOTS=1` и `PYTEST_ADDOPTS=--junitxml=…` через `$GITHUB_ENV`;
  - переключение файла JUnit перед вторым прогоном (PostgreSQL) и перед проверками развёртывания;
  - шаг «Спецификации OpenSpec» (`npx -y @fission-ai/openspec@2.1.0 validate --all --no-interactive`);
  - шаг «Прослеживаемость по прогону pytest» (`--junit-report`, оба XML);
  - выгрузка отчётов и `tests/e2e/visual/results/` артефактом.
- `openspec validate`: локально Node 20, поэтому Node 24 поставлен npm-пакетом `node@24` в папку scratchpad, CLI 2.1.0 запущен им. Итог: `Totals: 39 passed, 0 failed (39 items)`, только предупреждения. Требования движка: 1.17.0 — Node ≥ 22.12, 2.1.0 — Node ≥ 22.20 (`npm view`).
- Сверка JUnit на настоящем отчёте: `pytest tests/platform --junitxml` дал `38 passed`. После этого `check_traceability.py --junit-report --junit …` не назвал ни одного теста из `tests/platform`. Остальные 690 помеченных тестов в этот прогон не входили: соответствие classname и имени верное.
- `.github/workflows/snapshots.yml` — ручной запуск: `visual_check.py --update --no-build` в образе CI, артефакт `baselines-linux`.
- AGENTS.md: команда `--report`, правило `nolog`, ловушка «эталоны только Windows» заменена описанием эталонов Linux и `PHILOGRAPH_REQUIRE_SNAPSHOTS`.
