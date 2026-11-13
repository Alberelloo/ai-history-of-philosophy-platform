# Раунд 1 проверки: ru-only-sources (группы 1–2 `tasks.md`)

Роль: независимый E2E-тестировщик. Код, тесты и спецификации не менялись. Проверка шла по
`qa/cases.md` и дельтам `specs/source-registry`, `specs/source-library`, `specs/chapter-reading`,
`specs/regional-access`.

## Как воспроизвести

Стенд — как в `tests/web/conftest.py`, но собран тестировщиком (не тест проекта): настоящий шлюз
раздаёт собранный `web/dist` и проксирует запросы библиотеке через `httpx.ASGITransport`; учёт —
во временной SQLite. В список добавлен источник «Русский учебник» (П. Д. Юркевич, 1865) с видом
лицензии `public-domain-ru` и регионами показа `[RU]`.

```powershell
cd ai-history-of-philosophy-platform
$env:PYTHONPATH="src;."
.venv\Scripts\python openspec\changes\ru-only-sources\qa\round-1\harness\api_checks.py      # HTTP-слой, учёт, события
.venv\Scripts\python openspec\changes\ru-only-sources\qa\round-1\harness\browser_checks.py  # Playwright + скриншоты
.venv\Scripts\python openspec\changes\ru-only-sources\qa\round-1\harness\a11y_checks.py     # контраст, прокрутка, Tab
.venv\Scripts\python openspec\changes\ru-only-sources\qa\round-1\harness\race_check.py      # гонка в тесте TC-17
```

Команды из кейсов (`cases.md`, «Как проверять»):

```powershell
.venv\Scripts\python -m pytest -q tests/library -p no:cacheprovider
.venv\Scripts\python -m pytest -q tests/library/test_regions.py tests/library/test_regions_api.py `
    tests/library/catalog/test_regions_sync.py -p no:cacheprovider
.venv\Scripts\python -m pytest -q tests/web -p no:cacheprovider
```

Для браузера нужны собранный `web/dist` (`npm run build` в `web/`) и Chromium
(`python -m playwright install chromium`). Клиент в репозитории собран: `web/dist` от 10.11.2026
01:00:52, старше исходников (`LibraryPage.tsx` 00:55), то есть проверялся текущий код.

## Результаты

| Проверка | Итог |
| --- | --- |
| `pytest tests/library` (команда человека) | 130 passed, exit 0 |
| `pytest tests/library/test_regions*.py tests/library/catalog/test_regions_sync.py` | 25 passed, exit 0 |
| `pytest tests/web` | 126 passed, **1 failed** — `test_region_restricted.py::test_restricted_source_row` |
| Независимые HTTP/учёт/события (58 проверок) | 0 провалов |
| Независимые браузерные проверки (16 проверок) | 0 провалов |
| Доступность и раскладка | контраст пометки 6.71:1, горизонтальной прокрутки нет, фокусируемых элементов в закрытой строке 0 |

Скриншоты — `qa/screenshots/round-1/`, отчёты — `api-report.json`, `browser-report.json`,
`a11y-report.json`, журналы — `*.log`, сам стенд — `harness/`.

## Расхождения

1. **`tests/web/test_region_restricted.py` красный стабильно** (5 запусков из 5), причина —
   `row.count()` сразу после `page.goto`, без ожидания списка. Продукт при этом корректен:
   в том же сценарии строка появляется через доли секунды (`race-check.log`: «сразу после goto=0,
   после ожидания=1» три раза из пяти; все 16 независимых браузерных проверок зелёные).
   Это дефект теста (test artifact), а не поведения.
2. **Шлюз пропускает клиентский `X-Philograph-Region`** — с заголовком `RU` через шлюз закрытый
   источник открывается (`api-run.log`: «клиентский заголовок RU открывает закрытый источник =
   True»). Задача 3.2 `tasks.md` (шлюз, группа 3) не сделана; в охват групп 1–2 это не входит,
   но требование `regional-access` «Заголовок `X-Philograph-Region`, пришедший от клиента, SHALL
   отбрасываться» пока не выполнено.
3. **Формулировка EC-4 в `cases.md` расходится со спецификацией.** В кейсе ожидается, что при
   пустом пересечении регионов источник остаётся в списке строкой «доступен в РФ». Спека
   (`regional-access`, «Пустое пересечение регионов»: «ведёт себя как источник без разрешения на
   показ»; `source-library`, «Лицензия не разрешает показ»: «этого источника нет в списке») и код
   дают другое: `display: false`, источник не показывается ни в одном регионе — проверено для RU
   и DE (`api-run.log`, EC-4). Код следует спеке; поправить нужно текст кейса.

## Что не проверено

- Клиент с регионом `RU`: без группы 3 шлюз не выставляет заголовок, поэтому в браузере доступен
  только путь «регион неизвестен». Открытие источника для `RU` проверено на HTTP-слое.
- EC-11 (откат старого кода на новой базе): нет старой версии кода; проверено только, что регионы
  лежат отдельным столбцом, а не в JSON лицензии.
- Сравнение с эталонами дизайна: отдельного макета закрытой строки в `docs/design` нет, поэтому
  сверялись токены через DOM (цвета, шрифт, ширина, контраст), а не картинка с картинкой.
- Стенд не поднимает сервис знаний, поэтому в консоли при чтении книги есть 404 на
  `/api/knowledge/v1/mentions` — это отсутствие сервиса в стенде, а не дефект изменения.
