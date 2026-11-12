# Журнал: ru-only-sources

- Кто ведёт: ведущий инженер (роль: разработчик), сессия DSH.
- Ветка: `claude/ru-only-sources` (от `main` 3cc63b4); черновой PR #39.
- Статус: **группы 1–3 сделаны** (учёт регионов, миграция, каталог, событие, библиотека,
  HTTP-слой, служебные интерфейсы, клиентская строка списка, шлюз: регион читателя, заголовки,
  счётчик неизвестных). Группы 4–8 не начаты.
- Кейсы: `qa/cases.md` (UC-1…UC-13, TC-1…TC-27, EC-1…EC-25).

## Что сделано (2026-11-10)

- Миграция библиотеки **5** (`schema.py`): столбцы `license_kinds.regions`, `sources.regions`
  (JSON, NULL). Номер 5, а не 4: миграция 4 уже занята кодом страницы неразобранной части.
- `registry.py`: `License.regions`, `normalize_regions`, `effective_regions`,
  `effective_permissions`; `add_license_kind(..., regions=None)`, `Registry.regions()`,
  `Registry.license_kinds()`; запрет расширять регионы относительно вида; пустое пересечение —
  запрет показа; `change_license` пишет регионы и событие `source.access_changed` в outbox;
  смена регионов вида рассылает события по источникам этого вида.
- `catalog/`: `license.regions` в `sources/catalog.schema.json`, разбор в `catalog/model.py`,
  сравнение регионов в `ensure_license_kinds`.
- `reading.py`: `Reader.region`, `Reader.ALL_REGIONS`, `parse_region`, правило видимости в одном
  месте; закрытый источник остаётся в списке строкой `{id,title,authors,restricted,regions}`,
  не становится по умолчанию/текущим/запомненным; `resolve_paragraph` отвечает
  `source_unavailable` + `reason: region` + название и авторы; `Internal.access`,
  `regions`/`external_processing` в ответе версии, `published()` видит закрытые источники.
- `library/app.py`: `Reader` из заголовка `X-Philograph-Region`, эндпоинт
  `GET /api/v1/internal/access`.
- Клиент: `SourceItem | RestrictedSourceItem`, строка `li.source--restricted` с пометкой
  «Доступен в РФ» без кнопки «Читать»; `ParagraphLink` показывает «доступен только в России».
- Тесты: `tests/library/test_regions.py` (16), `tests/library/test_regions_api.py` (6),
  `tests/library/catalog/test_regions_sync.py` (3), `tests/web/test_region_restricted.py` (1).

## Прогоны

- `pytest -m "not e2e"`: 363 passed (было 322 требования к traceability), в т.ч. все новые.
- `tests/web` с `TMP`/`TEMP` внутри репозитория: 25 passed (Chromium работает).
- `ruff check`, `ruff format --check`: чисто. `lint-imports`: 3 contracts kept.
- `scripts/check_traceability.py`: 322 из 322.
- `python -m philograph.library.catalog validate`: 0 ошибок, 6 предупреждений о дублях названий.
- `openspec validate ru-only-sources`: valid (3 предупреждения о длинных требованиях).

## Что сделано (2026-11-12): группа 3 — шлюз

- Кейсы группы 3 дописаны до кода: `qa/cases.md` — R10–R13, UC-9…UC-13, TC-18…TC-27,
  EC-16…EC-25; R13 (проверка конфигурации развёртывания) отнесена к задаче 8.6.
- `src/philograph/gateway/region.py`: `RegionSettings.from_env` (`PHILOGRAPH_REGION_HEADER`,
  `PHILOGRAPH_TRUSTED_PROXY`, `PHILOGRAPH_REGION_FALLBACK`), `normalize_region` (две латинские
  буквы, верхний регистр, служебные `XX`/`T1` — неизвестный регион, неверный запасной регион
  игнорируется), `RegionResolver.region/dropped_headers/vary`.
- `src/philograph/gateway/app.py`: `build_app(..., regions=...)`; прокси удаляет клиентский
  `X-Philograph-Region` и заголовок страны, ставит свой `X-Philograph-Region`, считает
  `gateway.region` (`known`/`unknown` — без стран и посетителей), ответы `/api/*` получают
  `Cache-Control: private` и `Vary` на заголовок страны (прежние значения `Vary` сохраняются).
- `src/philograph/ops/alerts.py`: `UnknownRegionRule` над счётчиками шлюза, пороги
  `unknown_region_ratio` (0.10) и `unknown_region_min_requests` (100), правило `region`
  в `standard_rules`; общий сборщик метрик шлюза для правил ошибок и региона.
- `docs/operations/runbook.md`: строка правила «Регион читателя», пояснение про
  `PHILOGRAPH_REGION_HEADER`, доверенный прокси, счётчик и запасной регион.
- Закрыт finding F-2 раунда 1 («шлюз не отбрасывает клиентский `X-Philograph-Region`») — это
  была задача 3.2.
- Тесты: `tests/gateway/test_region.py` (9), `tests/gateway/test_region_proxy.py` (8),
  `tests/ops/test_alerts.py::test_unknown_region_rule` (1); в `test_rules_from_settings`
  ожидаемый набор правил дополнен `region`.

## Прогоны (2026-11-12)

- `pytest -q -m "not e2e"`: 367 passed, 115 skipped (Chromium без `TMP` в репозитории);
- `pytest -q tests/web` с `TMP`/`TEMP` = `<repo>/.tmp`: 127 passed;
- `pytest -q tests/gateway tests/ops`: 38 passed;
- `ruff check`, `ruff format --check`: чисто; `lint-imports`: 3 контракта; traceability 322/322;
  `openspec validate ru-only-sources`: valid (3 предупреждения о длине требований).

## Раунд dev_cycle 1 (2026-11-10)

- Вердикт: `fix`. Тестировщик: все UC-1…UC-8, TC-1…TC-17, EC-1…EC-15 прошли по поведению;
  13 скриншотов и отчёты — `qa/screenshots/round-1/`, `qa/round-1/`.
- F-1 (`test-artifact`, major): `tests/web/test_region_restricted.py` считал строки сразу после
  `page.goto` без ожидания отрисовки списка — гонка. **Исправлено**: добавлен
  `page.wait_for_selector("li.source--restricted")`; 5 прогонов подряд зелёные.
- F-3 (`test-artifact`, minor): EC-4 в `qa/cases.md` ожидал строку «доступен в РФ» при пустом
  пересечении регионов, что противоречит спеке (пустое пересечение = нет разрешения на показ).
  **Исправлено**: кейс приведён к R3/TC-4 и `source-library`.
- F-2 (`product-bug`, minor): шлюз не отбрасывает клиентский `X-Philograph-Region` — это задача
  **3.2 группы 3**, а не групп 1–2. В охват этого PR не входит; переносится в следующий шаг
  (группа 3 целиком: `RegionSettings`, доверие только прокси, `Vary`, счётчик неизвестных).
  Доказательство расхождения — `qa/round-1/api-run.log`.
- Не проверено: Postgres (только SQLite), реальная доставка `source.access_changed` в поиск и
  знания (группы 4–6), откат старого кода на новой базе (задача 8).

## Раунд dev_cycle 2 (2026-11-10)

- Вердикт: **`pass`**. Тестировщик: 257 passed командой
  `.venv/Scripts/python -m pytest -q tests/library tests/web -p no:cacheprovider` (130 + 127),
  `tests/web/test_region_restricted.py` — 5/5 зелёных (гонка F-1 не воспроизводится).
  Независимый стенд: 58 HTTP/учёт/события, 16 браузерных сценариев, 6 регрессионных, доступность
  и раскладка — 0 провалов. Артефакты: `qa/round-2/`, `qa/screenshots/round-2/` (19 PNG).
- F-4 (`test-artifact`, minor): harness раунда 1 искал корень по `parents[2]` и попадал в каталог
  `qa`, поэтому скриншоты раунда 1 не воспроизводились. **Исправлено**: `_repo_root()` ищет вверх
  до `pyproject.toml` (как в round-2); `diag.py` теперь отдаёт HTML библиотеки (13140 байт, 4 строки
  списка) вместо `{"detail":"Not Found"}`.
- F-2 (шлюз не отбрасывает клиентский `X-Philograph-Region`) остаётся запланированной задачей 3.2
  группы 3 — в охват групп 1–2 не входит, судья подтвердил, что дефектом этих групп не является.
- Поведенческих расхождений по группам 1–2 нет.

## Следующий шаг

- Группа 4 (поиск): миграция 4 (`docs.regions`, `docs.external`), регион в запросе и фильтре,
  обработчик `source.access_changed`, шаг сверки.
- Затем 8.2 (запасной регион в стенде) и 8.4 (данные `licenses.yaml`), группы 6 и 5 параллельно,
  группа 7 (внешняя обработка), 8.1/8.3/8.5/8.6.
- Раунд `dev_cycle` по группам 1–3 — тестировщик и судья.

## Проблемы и замечания

- Environment: браузерные тесты (`tests/web`) и Playwright проходят только если `TMP`/`TEMP`
  указывают внутрь репозитория — иначе Chromium падает с `EPERM mkdtemp`; при работе в песочнице
  DSH тесты без этого падают полностью (`PermissionError` на временных каталогах).
- В `tasks.md` задача 1.1 называет миграцию 4, фактически применена 5 (4 занята). Число в задаче
  исправлять не стал: история изменений важнее, отметка стоит.
- Старое замечание `progress.md` о расхождении кода и спецификации (ассистент и разбор упоминаний
  не проверяют `external_processing`) относится к группе 7 — не закрыто.
- Клиентская проверка строки списка идёт через шлюз без заголовка региона: для браузера регион
  неизвестен, поэтому источник `[RU]` закрыт. Настоящий CDN — группа 3 и 8.3.
