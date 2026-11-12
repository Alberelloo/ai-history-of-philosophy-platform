# Раунд 4 проверки: ru-only-sources (группа 4 — поиск, 8.2 — запасной регион стенда, фикс группы 1)

Роль: независимый E2E-тестировщик. Код, тесты и спецификации не менялись: `git status` показывает
только новые каталоги `qa/round-4/` и `qa/screenshots/round-4/`. Проверка шла по `qa/cases.md`
(TC-28…TC-38, EC-26…EC-33, UC-14…UC-19) и дельтам `specs/regional-access` (R14–R17),
`specs/paragraph-search`; ветка `claude/ru-only-sources`, коммит `b4dd877`.

## Как воспроизвести

```powershell
cd ai-history-of-philosophy-platform
# Chromium не стартует с системным TMP: каталог внутри репозитория обязателен.
$tmp = (Resolve-Path ".stack\tmp").Path
$env:TMP = $tmp; $env:TEMP = $tmp
$env:PYTHONIOENCODING = "utf-8"

# 1. Команда человека: весь набор без e2e (без TMP браузерные тесты уйдут в skipped)
.venv\Scripts\python.exe -m pytest -q -m "not e2e" -p no:cacheprovider

# 2. Целевые кейсы групп 4 и 1 подробно
.venv\Scripts\python.exe -m pytest -v -p no:cacheprovider tests\search\test_regions.py tests\library\test_regions.py

# 3. Независимый живой стенд (dev_stack + свои источники + HTTP + очередь + Playwright)
.venv\Scripts\python.exe openspec\changes\ru-only-sources\qa\round-4\harness\live_checks.py
```

## Результаты

| Проверка | Итог |
| --- | --- |
| `pytest -q -m "not e2e"` (команда человека, без TMP в репозитории) | 396 passed, 115 skipped, exit 0. Пропуски — `tests/web/*` из-за `EPERM mkdtemp`, не из-за продукта |
| то же с `TMP`/`TEMP` = `<repo>/.stack/tmp` | **510 passed, 1 skipped** (только PostgreSQL-тест), exit 0, 233 с |
| `tests/search/test_regions.py` + `tests/library/test_regions.py` | **27 passed**, exit 0 |
| Независимый стенд (`live_checks.py`) | **29 проверок, 0 провалов**, exit 0 |

Артефакты: скриншоты — `qa/screenshots/round-4/` (4 PNG), отчёт стенда — `qa/round-4/live-report.json`,
журналы сервисов — `qa/round-4/harness/stand/logs/`, прогоны — `qa/round-4/*.log`.

## Что проверено на живом стенде

Стенд: `scripts/dev_stack.py` в-process, демо-источники плюс два источника тестировщика
(«Ограниченный учебник [RU]» с видом `demo-ru regions=["RU"]` и открытый сборник), Qdrant в
процессе поиска, `PHILOGRAPH_REGION_FALLBACK=RU`.

- **Поиск (R14).** «рассудок и разум»: с регионом `RU` абзацы источника `[RU]` есть; с `DE` и без
  региона — нет ни по словам, ни по смыслу (`semantic_used: true`, `found_by: lexical+semantic`);
  `limit=3` из DE заполнен тремя открытыми абзацами; уникальное слово ограниченного источника
  для DE и без региона не находится, для RU находится. При выключенном сервисе LLM
  (`semantic_used: false`) фильтр региона продолжает работать.
- **Событие (R15).** `change_license` → outbox → очередь → поиск: видимость для DE меняется,
  счётчик вызовов эмбеддера (`llm.call.completed`, `role=embeddings`, `budget=filling`) не растёт
  (4 → 4); повтор того же события логируется как `search.index.duplicate` и видимость не меняет;
  `regions: []` записывает в индекс `,` и закрывает источник для RU, DE и без региона.
- **Сверка (R16).** Регионы в индексе испорчены на `*`, `POST /v1/internal/reconcile` дважды даёт
  `{missing: 0, extra: 0}`, возвращает `,RU,`, источник остаётся `active`, RU видит, DE нет.
- **Стенд 8.2 (R17).** Через шлюз без заголовков страны источник `[RU]` открыт (год, лицензия,
  «Читать»), чтение главы показывает текст; клиентские `X-Philograph-Region: DE` и
  `CF-IPCountry: DE` регион не подменяют (и в браузере, и HTTP); напрямую в библиотеке без шлюза
  тот же источник — строка «Доступен в РФ» без года и лицензии. Шлюз с заданным именем заголовка
  страны и недоверенным прокси тоже игнорирует `CF-IPCountry` и берёт запасной `RU`.
- **Фикс группы 1 (TC-38/EC-33).** У вида `[RU]` и источника без сужения `change_license` пишет в
  событие `regions: ["RU"]` (не `null`), поиск не открывает источник всем регионам.
- **Миграция 4 (TC-33/EC-32).** На базе версии 3 `upgrade` применяет только миграцию 4, столбцы
  `regions`/`external` появляются, старая строка читается как `*` и `TRUE`.

## Осталось непроверенным

- `tests/e2e` (93 deselected): нужен `web/dist` и подъём стека; поведение 8.2 проверено на живом
  стенде, а не сквозными тестами.
- Настоящий CDN и проверка конфигурации развёртывания — задача 8.6 (вне групп 3–4).
- Пункты `tasks.md` групп 5–8 (ассистент, знания, внешняя обработка, оценка, данные `licenses.yaml`,
  traceability) в этом раунде не проверялись: кода ещё нет, кейсы появятся в следующих раундах.
