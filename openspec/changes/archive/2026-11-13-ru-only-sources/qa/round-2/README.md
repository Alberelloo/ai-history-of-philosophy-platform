# Раунд 2 проверки: ru-only-sources (группы 1–2 `tasks.md`)

Роль: независимый E2E-тестировщик. Код, тесты и спецификации не менялись: `git status` показывает
только новые каталоги `qa/round-2/` и `qa/screenshots/round-2/`. Проверка шла по `qa/cases.md` и
дельтам `specs/source-registry`, `specs/source-library`, `specs/chapter-reading`,
`specs/regional-access`.

Фокус раунда: повторная проверка групп 1–2 после фиксов F-1 (`li.source--restricted` в клиентском
тесте) и F-3 (EC-4 приведён к спеке), стабильность `tests/web/test_region_restricted.py`, весь
`tests/web` и `tests/library`, регрессии списка/фильтров/ссылки на абзац.

## Как воспроизвести

```powershell
cd ai-history-of-philosophy-platform
# Chromium не стартует с системным TMP: каталог внутри репозитория обязателен.
New-Item -ItemType Directory -Force .stack/tmp | Out-Null
$env:TMP=(Resolve-Path .stack/tmp).Path; $env:TEMP=$env:TMP
$env:PYTHONPATH="src;."; $env:PYTHONIOENCODING="utf-8"

# 1. Команда человека: весь библиотечный и клиентский набор
.venv\Scripts\python -m pytest -q tests/library tests/web -p no:cacheprovider

# 2. Стабильность клиентского теста: пять прогонов подряд
1..5 | ForEach-Object { .venv\Scripts\python -m pytest -q tests/web/test_region_restricted.py -p no:cacheprovider }

# 3. Независимые проверки (стенд тестировщика: настоящий шлюз + собранный web/dist + SQLite)
.venv\Scripts\python openspec\changes\ru-only-sources\qa\round-2\harness\api_checks.py       # HTTP, учёт, события
.venv\Scripts\python openspec\changes\ru-only-sources\qa\round-2\harness\browser_checks.py   # Playwright + скриншоты
.venv\Scripts\python openspec\changes\ru-only-sources\qa\round-2\harness\extra_checks.py     # регрессии списка/фильтров/ссылки, EC-4
.venv\Scripts\python openspec\changes\ru-only-sources\qa\round-2\harness\a11y_checks.py      # контраст, раскладка, фокус
```

Стенд — как в `tests/web/conftest.py`: настоящий шлюз раздаёт собранный `web/dist` (от 10.11.2026
01:00:52, новее исходников клиента от 00:55) и проксирует запросы библиотеке через
`httpx.ASGITransport`; учёт — во временной SQLite. В список добавлен источник «Русский учебник»
(П. Д. Юркевич, 1865) с видом лицензии `public-domain-ru` и регионами показа `[RU]`.

## Результаты

| Проверка | Итог |
| --- | --- |
| `pytest -q tests/library tests/web` (команда человека) | **257 passed**, exit 0, 190.58 s (130 library + 127 web) |
| `test_region_restricted.py`, 5 прогонов подряд | **5/5 passed** (3.13, 2.94, 3.50, 3.02, 2.69 s) |
| Независимые HTTP/учёт/события (`api_checks.py`) | **58 проверок, 0 провалов** |
| Независимые браузерные сценарии (`browser_checks.py`) | **16 проверок, 0 провалов** |
| Регрессии списка/фильтров/ссылки и EC-4 (`extra_checks.py`) | **6 проверок, 0 провалов** |
| Доступность и раскладка (`a11y_checks.py`) | контраст пометки 6.71:1, прокрутки нет (1440/1440), фокусируемых элементов в закрытой строке 0, ширина строки как у открытой (368 px) |

Артефакты: скриншоты — `qa/screenshots/round-2/`, отчёты — `qa/round-2/harness/*.json`,
журналы — `qa/round-2/*.log`.

## Статус фиксов раунда 1

- **F-1 закрыт.** `tests/web/test_region_restricted.py` содержит ожидание
  `page.wait_for_selector("li.source--restricted")`; тест зелёный 5/5, весь `tests/web` зелёный
  (127 passed). Гонки не воспроизводится.
- **F-3 закрыт.** EC-4 в `qa/cases.md` теперь: «нигде: `display: false`, в чтении и в списке
  источника нет», что совпадает с R3, TC-4 и `regional-access` / «Пустое пересечение регионов».
  Независимо проверено: после сужения вида до `[RU]` у источника `[BY]` — `regions()` пусто,
  `permissions.display = false`, события с `regions: []`, в списке и в API источника нет ни для
  `RU`, ни для `DE`, ни для неизвестного региона (скриншот `EC-4-1-empty-intersection-hidden.png`).
- **F-2 перенесён, не дефект групп 1–2.** Шлюз по-прежнему пропускает клиентский
  `X-Philograph-Region` (`api-run.log`: «клиентский заголовок RU открывает закрытый источник =
  True»). Это задача **3.2** группы 3 (`tasks.md`), в охват этого PR не входит.

## Наблюдения

1. `qa/round-1/harness/browser_checks.py` и `api_checks.py` в том виде, в котором они закоммичены,
   не воспроизводят раунд 1: `ROOT = parents[2]` указывает на каталог `qa`, поэтому `DIST` —
   несуществующий `qa/web/dist`, а `SHOTS` превращается в двойной путь
   `qa/openspec/changes/ru-only-sources/qa/screenshots/round-1`. Запуск скрипта падает на
   `wait_for('.sources .source')` (страница отдаёт `{"detail":"Not Found"}`). В раунде 2 те же
   скрипты скопированы в `round-2/harness/` с поиском корня по `pyproject.toml`; доказательство —
   `qa/round-2/round1-harness-root.log`. Скриншоты раунда 1 при этом настоящие (UI в них есть).
2. Консоль браузера: 404 на `/api/knowledge/v1/mentions` — сервис знаний не поднят в стенде,
   а не дефект изменения (как и в раунде 1). Остальные 404 — ожидаемые ответы `source_unavailable`
   на оглавление и главу закрытого источника.
3. Сравнение с макетами: в `docs/design` нет эталона закрытой строки, поэтому сверялись токены и
   геометрия через DOM (цвета `rgb(232,234,228)`/`rgb(72,80,93)`, 12 px, ширина как у открытой
   строки), а не картинка с картинкой.

## Что не проверено

- EC-11 (откат старого кода на новой базе): старой версии кода нет; проверено только, что регионы
  лежат отдельным столбцом `sources.regions`, а не в JSON лицензии.
- Клиент с регионом `RU`: без группы 3 шлюз не выставляет заголовок, поэтому в браузере доступен
  только путь «регион неизвестен»; открытие источника для `RU` проверено на HTTP-слое.
- Postgres: прогон только на SQLite (как в раунде 1).
- Группы 3–8 `tasks.md` (шлюз, поиск, ассистент, знания, внешняя обработка, оценка, данные,
  развёртывание) в этот раунд не входят.
