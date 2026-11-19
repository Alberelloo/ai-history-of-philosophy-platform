# Задачи

## 1. Прослеживаемость до сценариев и журнала

- [x] 1.1 Скрипт разбирает `#### Scenario:` под требованиями (с учётом ADDED/MODIFIED/REMOVED/RENAMED) и печатает четыре строки итога
- [x] 1.2 Параметры маркера `scenario=`, `invariant=`, `nolog=`; опечатка в `scenario=`, нерешённый аргумент, неизвестный параметр, пустой `nolog` — ошибки
- [x] 1.3 Считаются только тесты, которые соберёт pytest (`test_*` модуля, `test_*` классов `Test*`, маркеры класса и `pytestmark`); маркер не на тесте — ошибка
- [x] 1.4 Статическое определение проверки журнала с обходом помощников; режимы `enforce_scenarios` и `enforce_log` в `traceability.yaml` (пока пустые), флаг `--report`
- [x] 1.5 `--junit` (несколько отчётов) и `--junit-report`; юнит-тесты скрипта и мутационная проверка
- [ ] 1.6 Шаги CI: pytest пишет JUnit, скрипт сверяет в режиме отчёта; XML — артефакт

## 2. Снимки экрана в CI

- [x] 2.1 Эталоны `tests/e2e/visual/baselines/linux/` и два прогона сравнения подряд без расхождений
- [ ] 2.2 `PHILOGRAPH_REQUIRE_SNAPSHOTS=1`: нет эталона — тест падает; переменная в шагах pytest CI (новые шаги не нужны — переменная задания)
- [ ] 2.3 `.github/workflows/snapshots.yml`: ручной запуск собирает эталоны Linux в образе CI артефактом
- [ ] 2.4 Сверка эталонов с рендером `ubuntu-latest` по прогону CI этого PR; при расхождении — эталоны из артефакта 2.3

## 3. Одна фикстура стенда e2e

- [x] 3.1 `site` на сессию в `tests/e2e/conftest.py`; копии в трёх модулях удалены; каталожный тест — свой стенд через общий `start_dev_stack`
- [x] 3.2 Окружение стенда через `MonkeyPatch.context()`, без `os.environ.setdefault`

## 4. `openspec validate` в CI

- [ ] 4.1 Шаг `npx -y @fission-ai/openspec@2.1.0 validate --all --no-interactive`; проверено локально на Node 24

## 5. События без проверки

- [x] 5.1 `test_every_catalog_event_is_emitted_somewhere` предупреждает о событиях, которых не называет ни один тест с проверкой журнала; тот же список в `--report`

## 6. Документы

- [ ] 6.1 AGENTS.md (ловушки окружения, команды), working-principles / скилл тестировщика — про `--report`, `nolog`, `PHILOGRAPH_REQUIRE_SNAPSHOTS`
