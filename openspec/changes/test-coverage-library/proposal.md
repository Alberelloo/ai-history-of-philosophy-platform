## Зачем

Аудит системы (docs/audit/2026-11-19-system-audit.md, 4.2–4.4) показал: у большинства сценариев библиотеки, источников, чтения и региона нет сценарных тестов, а у нормативных правил нет проверок журнала. Нужно покрыть тестами все `#### Scenario:` возможностей source-library, source-registry, source-processing, text-quality-check, document-structure, source-catalog, source-scope, paragraph-indexing, paragraph-search, chapter-reading, regional-access, reader-settings, first-run-notice и их инварианты.

## Что меняется

Только тесты (`skip_specs: true`): маркеры `scenario=` и `invariant=` на существующих тестах, дописанные проверки вывода и журнала, новые файлы `tests/<пакет>/test_<возможность>_spec.py`, сквозной файл `tests/e2e/test_library_flows.py`. Продуктовый код не меняется. Расхождения со спецификацией оформляются как `xfail(strict=True)` и описываются в verification.md.

## Вне изменения

Правки продукта, фикстуры `tests/conftest.py`, `tests/e2e/conftest.py`, тесты чужих групп.
