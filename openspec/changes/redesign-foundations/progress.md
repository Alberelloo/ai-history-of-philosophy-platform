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
| 1.8 Тесты и эталоны | в работе: тесты без браузера готовы, сквозные визуальные — следующий шаг |

## Сейчас

Прежние браузерные тесты обновлены там, где имена изменены осознанно: навигация «Библиотека», «Настройки» и текущий источник — ссылки верхней панели (`topnav()` в `tests/helpers.py`), стрелки в «Следующая глава», «Назад» стали значками. `reader_context` ставит `locale="ru-RU"`.

Место чтения: видимым считается абзац ниже закреплённой верхней панели (отступ прокрутки).

На стендах тестов поднят запас лимита частоты шлюза (`PHILOGRAPH_RATE_BURST=2000` в `tests/e2e/conftest.py` и `compose.e2e.yaml`): шрифты добавили ~10 запросов на каждую новую страницу без кэша, и быстрые тесты упирались в 429.

## Следующий шаг

`tests/e2e/test_visual_design.py`: тесты на все требования visual-design, снимки экранов в двух темах, эталоны для win32; `visual-design` в `openspec/traceability.yaml`; `design.md`.

## Известные проблемы

- Упоминания в тексте приходят без типа сущности: цвет семьи для них пока нейтральный.
- Карточка у упоминания и панель ассистента пока перекрывают колонку текста (переделка экрана чтения — следующий шаг).

## Как проверить

- `.venv/Scripts/python scripts/design_tokens.py --check`
- `cd web && npm run build`
- `PYTHONUTF8=1 .venv/Scripts/python -m pytest -q tests/web tests/e2e`
