# Журнал: ru-only-sources

- Кто ведёт: ведущий инженер (роль: разработчик), сессия DSH.
- Ветка: `claude/ru-only-sources` (от `main` 3cc63b4).
- Статус: **группы 1–2 сделаны** (учёт регионов, миграция, каталог, событие, библиотека, HTTP-слой,
  служебные интерфейсы, клиентская строка списка). Группы 3–8 не начаты.
- Кейсы: `qa/cases.md` (UC-1…UC-8, TC-1…TC-17, EC-1…EC-15).

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

## Следующий шаг

- Группа 3 (шлюз): `gateway/region.py`, настройки, удаление клиентских заголовков, `Vary`,
  предупреждение о доле неизвестных регионов.
- Затем группы 4 (поиск), 5–6 (ассистент, знания), 7 (внешняя обработка), 8 (данные `licenses.yaml`
  — задача 8.4, `traceability.yaml` — 8.5, документация и архив — 8.6–8.7).
- Раунд `dev_cycle` по группам 1–2 — тестировщик и судья.

## Проблемы и замечания

- В `tasks.md` задача 1.1 называет миграцию 4, фактически применена 5 (4 занята). Число в задаче
  исправлять не стал: история изменений важнее, отметка стоит.
- Старое замечание `progress.md` о расхождении кода и спецификации (ассистент и разбор упоминаний
  не проверяют `external_processing`) относится к группе 7 — не закрыто.
- Клиентская проверка строки списка идёт через шлюз без заголовка региона: для браузера регион
  неизвестен, поэтому источник `[RU]` закрыт. Настоящий CDN — группа 3 и 8.3.
