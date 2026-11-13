# Раунд 3 проверки: ru-only-sources (группа 3 — шлюз)

Роль: независимый E2E-тестировщик. Код, тесты и спецификации не менялись: `git status` показывает
только новые каталоги `qa/round-3/` и `qa/screenshots/round-3/`. Проверка шла по `qa/cases.md`
(TC-18…TC-27, EC-16…EC-25) и дельте `specs/regional-access/spec.md`; ветка `claude/ru-only-sources`,
коммит `7a6556e`.

## Как воспроизвести

```powershell
cd ai-history-of-philosophy-platform
# Chromium не стартует с системным TMP в этой песочнице: TEMP внутри репозитория обязателен.
$tmp = (Resolve-Path "openspec\changes\ru-only-sources\qa\round-3\harness\tmp").Path
$env:TEMP = $tmp; $env:TMP = $tmp

# 1. Команда человека: весь набор без e2e
.venv\Scripts\python.exe -m pytest -q -m "not e2e" -p no:cacheprovider

# 2. Целевые тесты группы 3 подробно
.venv\Scripts\python.exe -m pytest -v -p no:cacheprovider tests\gateway tests\ops\test_alerts.py

# 3. Клиентские тесты, которые в общем прогоне пропущены из-за TMP песочницы
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\web\test_region_restricted.py tests\web\test_library_reading.py

# 4. Независимый стенд тестировщика: поддельные сервисы + четыре настоящих шлюза
#    (доверенный, недоверенный, с запасным регионом, без имени заголовка) + Playwright
.venv\Scripts\python.exe openspec\changes\ru-only-sources\qa\round-3\harness\live_checks.py
```

## Результаты

| Проверка | Итог |
| --- | --- |
| `pytest -q -m "not e2e"` (команда человека) | **385 passed, 115 skipped, 93 deselected**, exit 0, 205 с. Пропуски — `tests/web/*` из-за `EPERM mkdtemp` (TMP песочницы), не из-за продукта |
| `tests/gateway` + `tests/ops/test_alerts.py` | **27 passed**, exit 0, 1.46 с |
| `tests/web/test_region_restricted.py` + `tests/web/test_library_reading.py` с TMP внутри репозитория | **25 passed**, exit 0, 17.69 с |
| Независимый стенд (`live_checks.py`) | **32 шага, 2 нарушения** — оба TC-25 (Cache-Control), см. F-4 |

Артефакты: скриншоты — `qa/screenshots/round-3/`, отчёт стенда — `qa/round-3/live-report.json`,
журналы — `qa/round-3/*.log` и `qa/round-3/harness/logs/`.

## Находка раунда

**F-4 (major, TC-25, EC-21).** Шлюз не заменяет `Cache-Control` сервиса, а добавляет второе
одноимённое значение. Прямое доказательство (`headers_evidence.py`, `headers-evidence.log`) —
сырые заголовки ответа `/api/v1/sources`:

```text
[["cache-control", "public, max-age=300"], ["cache-control", "private"],
 ["content-type", "application/json"], ["vary", "Accept-Encoding, CF-IPCountry"]]
заголовков Cache-Control в ответе: 2
```

Причина — `src/philograph/gateway/app.py:210-212`: ключи словаря заголовков ответа различаются
регистром (`cache-control` от сервиса и новый `Cache-Control`), оба уходят в ответ; браузер
показывает `cache-control: public, max-age=300, private`. `Vary` собирается правильно
(`Accept-Encoding, CF-IPCountry`), заголовок страны сервису не передаётся, страница продукта
`Cache-Control` не получает. Тест `tests/gateway/test_region_proxy.py::test_api_response_is_private_and_varies`
дефект не ловит: поддельный сервис в тесте `Cache-Control` не ставит. Проявляется, если сервис
за шлюзом отдаёт `Cache-Control`; требование R10/EC-21 безусловно, поэтому дефект засчитан.

## Что не проверено

- Настоящий CDN и проверка конфигурации развёртывания (R13, задача 8.6) — вне группы 3.
- Запасной регион в `scripts/dev_stack.py` (задача 8.2) не сделан: на локальном стенде регион по
  умолчанию неизвестен — ожидаемо, не дефект. Запасной регион проверен на шлюзе, поднятом
  с `PHILOGRAPH_REGION_FALLBACK=RU` вручную (TC-22).
- Поиск, ассистент, знания, внешняя обработка (группы 4–7) — кейсы будут в следующих раундах.
