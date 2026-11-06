# Журнал работы: redesign-foundations

Ведёт: разработчик фронтенда (Claude Opus). Ветка `claude/design-system`, WIP-коммиты.

## Статус пунктов tasks.md

| Пункт | Статус |
| --- | --- |
| 1.1 Генерация tokens.css | сделан: `scripts/design_tokens.py`, `web/src/styles/tokens.css`, тесты в `tests/web/test_design_system.py` |
| 1.2 Шрифты @fontsource | сделан: импорт в `web/src/main.tsx`, «Literata Variable» первым в `--font-read` |
| 1.3 Компоненты pg-* на экранах | сделан: `web/src/styles/components.css`, `web/src/ui.tsx`, все экраны, `web/src/styles.css` только на токенах |
| 1.4 Верхняя панель | сделан: `web/src/TopBar.tsx` |
| 1.5 Тема | сделан: `storage.ts` (`theme`), `theme.ts`, скрипт в `web/index.html` |
| 1.6 Каталог RU/EN | сделан: `web/src/i18n/{ru,en,index}.ts`, коды сервера переводятся по каталогу |
| 1.7 Помощники визуальной проверки | сделан: `tests/e2e/visual.py` (DOM-проверки, `snap()`), `scripts/visual_check.py` |
| 1.8 Тесты и эталоны | сделан: `tests/e2e/test_visual_design.py`, `tests/web/test_design_system.py`, 21 эталон win32, `visual-design` в `openspec/traceability.yaml` |

## Раунд 1 визуальной проверки

Отчёт — [qa/round-1.md](qa/round-1.md), диагноз — [qa/round-1-diagnosis.md](qa/round-1-diagnosis.md). Перед раундом в ветку влит `main` (архив OpenSpec, #24).

| Пункт | Статус |
| --- | --- |
| D5 Настройки: RU / EN | сделан |
| D3 Библиотека: сетка на всю ширину (`auto-fit`) | сделан, проверка `assert_fills_width` |
| З1 `@import` Google Fonts в дизайн-системе | сделан, тест смотрит и `docs/design/system/*.css` |
| D6 Годы без пробелов вокруг тире, миграция 5 | сделан: `dates.py`, миграция `knowledge:5` (только `lifespan` и копия дат), тесты в `tests/knowledge`, `test_site.py` |
| D1 Карточка: названия онтологии по коду | сделан: сервер отдаёт `inverse`, `attributions[].kind`, `label`; клиент — `ontology.{ru,en}.json`, `onto` в каталогах, помощники в `i18n/index.ts` |
| D2 Граф и ассистент: рецепты и связи по коду | сделан: `GraphPage.tsx` (рецепты, связи, «распространённое мнение»), подсказка ассистента из `recipe` и `label` |
| З2 Описание заглушки модели в карточке | не начат |
| D4 Уведомление в потоке страницы | не начат |
| Эталоны снимков | не начат |

## Сделано

- Прежние браузерные тесты обновлены там, где имена изменены осознанно: навигация «Библиотека», «Настройки» и текущий источник — ссылки верхней панели (`topnav()` в `tests/helpers.py`), стрелки в «Следующая глава», «Назад» стали значками. `reader_context` ставит `locale="ru-RU"`.
- Место чтения: видимым считается абзац ниже закреплённой верхней панели (отступ прокрутки).
- На стендах тестов поднят запас лимита частоты шлюза (`PHILOGRAPH_RATE_BURST=2000` в `tests/e2e/conftest.py` и `compose.e2e.yaml`): шрифты добавили ~10 запросов на каждую страницу без кэша, и быстрые тесты упирались в 429.
- Решения — в [design.md](design.md).

## Следующий шаг

Цикл проверки: тестировщик снимает экраны (2 темы × ru/en × 1440/1024), следователь пишет `qa/round-N-diagnosis.md`, разработчик исправляет.

## Известные проблемы

- Упоминания в тексте приходят без типа сущности: подчёркивание нейтральное, а не цвета семьи (нужен тип в `/api/knowledge/v1/mentions`).
- Карточка у упоминания и панель ассистента перекрывают колонку текста (переделка экрана чтения — следующее изменение).
- Граф: подписи узлов могут пересекаться с линиями связей (граф по оси времени — отдельное изменение).
- Эталоны снимков есть только для Windows; в CI (Linux) снимки не сравниваются, DOM-проверки идут.

## Как проверить

Визуальная проверка одной командой (собирает клиент, сам поднимает стенд, DOM-проверки и сравнение снимков):

```
.venv/Scripts/python scripts/visual_check.py
```

- Обновить эталоны (только посмотрев снимки): `.venv/Scripts/python scripts/visual_check.py --update`
- Без пересборки клиента: `--no-build`; выбрать тесты: `.venv/Scripts/python scripts/visual_check.py -- -k theme`
- Эталоны: `tests/e2e/visual/baselines/win32/`; при расхождении фактический снимок, эталон и карта различий — в `tests/e2e/visual/results/`.
- Стенд руками: `PHILOGRAPH_RATE_BURST=2000 .venv/Scripts/python scripts/dev_stack.py --port 8099` (сначала `cd web && npm run build`).
- Всё остальное: `.venv/Scripts/python scripts/design_tokens.py --check`, `PYTHONUTF8=1 .venv/Scripts/python -m pytest -q`, `.venv/Scripts/python scripts/check_traceability.py`, `.venv/Scripts/ruff check .`
