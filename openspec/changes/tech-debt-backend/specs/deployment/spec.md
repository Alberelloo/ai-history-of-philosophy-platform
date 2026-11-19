## ADDED Requirements

### Requirement: Воспроизводимая сборка

Образ сервисов SHALL собираться по lock-файлу Python-зависимостей без нового разрешения версий, а базовые образы и образы зависимостей в compose SHALL указываться точным тегом и digest. CI SHALL ставить зависимости по тому же lock-файлу и падать, если lock-файл расходится с `pyproject.toml`. Действия CI SHALL быть закреплены полным SHA коммита.

#### Scenario: Lock-файл устарел

- **WHEN** в `pyproject.toml` добавили зависимость, а lock-файл не обновили
- **THEN** проверка lock-файла в CI падает

#### Scenario: Плавающий тег

- **WHEN** в Dockerfile или compose-файле образ указан без точного тега и digest
- **THEN** проверка сборки называет этот образ

### Requirement: Рабочий образ без отладочных частей

Рабочий образ MUST NOT содержать отладочные скрипты (`scripts/crash_service.py`, `scripts/seed_demo.py`) и демо-данные (`demo/`). Они SHALL быть только в образе стенда сквозных тестов, который собирается отдельной целью.

#### Scenario: Прод-образ

- **WHEN** собирается рабочий образ
- **THEN** в нём нет `scripts/` и `demo/`, а в образе стенда e2e есть `scripts/seed_demo.py`, `scripts/crash_service.py` и `demo/`
