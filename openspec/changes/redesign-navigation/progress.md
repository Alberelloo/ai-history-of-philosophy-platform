# Журнал работы: redesign-navigation

Ведёт: субагент-разработчик (Claude Opus) по плану `C:\Users\Ivano\.claude\plans\warm-shimmying-umbrella.md`. Ветка `claude/design-system` (PR #25). После каждого пункта `tasks.md` — коммит `wip(redesign-navigation): …` и пуш. После разработчика изменение проверяет тестировщик; архивировать не нужно.

## Статус пунктов tasks.md

| Пункт | Статус |
| --- | --- |
| 1.1 Изменение OpenSpec | сделан |
| 1.2 Документы дизайна | сделан: layout.md, Sidebar.md, FilterMenu.md, журнал в design-system.md, content.md |
| 2.1 Токены | сделан: sidebar, sidebar-open, sidebar-pinned, dur-sidebar, z-sidebar; tokens.css перегенерирован |
| 2.2 Хранилище v3 | сделан: ключ philograph:v3, openSources, sidebarPinned, перенос из v2 и v1, скрипт темы читает v3/v2 и ставит data-sidebar |
| 2.3 Боковая панель | сделан |
| 2.4 Заглушки разделов | сделан |
| 3.1 Настройки | сделан |
| 4.1 Фильтры библиотеки | сделан: FilterMenu в ui.tsx, поиск 360px, сброс всегда на месте (неактивен без фильтров) |
| 5.1 Сервер: глава по разделу, first_chapter_id | сделан: Reading.chapter отдаёт главу раздела с anchor, ChapterNotFound → 404 с first_chapter_id; тесты tests/library/test_reading_resilience.py |
| 5.2 Клиент: устойчивое чтение | сделан: ReaderPage на chapter_not_found ищет сохранённый абзац (или абзац из адреса), иначе первую главу; уведомление в потоке; раздел по адресу → глава с прокруткой; ApiError.details |
| 5.3 Заглушки необработанных частей | сделан: extract — blank_page и missing, parse — блоки unrendered с пояснением, Wikisource v3 пишет красные ссылки с missing, CatalogFetch отдаёт заглушку, схема каталога; оформление unrendered в клиенте; PIPELINE_VERSION 3, STEP_VERSIONS 3; тесты tests/library/test_unrendered_parts.py, tests/library/catalog/test_missing_subpages.py |
| 6.1 Прослеживаемость RENAMED/REMOVED | сделан: check_traceability понимает RENAMED (FROM) и REMOVED; тест tests/platform/test_runtime.py::test_traceability_follows_renamed_and_removed |
| 6.2 | сделан: helpers sidenav/via_sidebar и ключ v3; test_settings (разделы и оглавление, перенос v2); test_site (открытые книги); test_visual_design (панель на каждом экране, клавиатура и Esc, закрепление, 1024/1280/1440/1920, тема по кругу, разделы в разработке); tests/web (фильтры, ширина поиска, регресс устаревшей главы, заглушка в тексте); tests/library (сервер, PDF, Wikisource). Прослеживаемость 315 из 315 |
| 6.3 Визуальные эталоны | сделан: все 22 снимка просмотрены и сверены с layout.md, Sidebar.md, FilterMenu.md, затем visual_check.py --update; проверка без --update — 35 passed; эталоны компонентов docs/design/reference/Sidebar-{light,dark}.png, FilterMenu-{light,dark}.png |
| 6.4 Итоговый прогон | сделан: npm run build, visual_check.py — 35 passed, pytest — 401 passed, 1 skipped, ruff check и format — чисто, прослеживаемость 315 из 315, openspec validate — valid |

## Решения

- Порог закрепления панели — 1280px, а не 1024px из плана: на 1024px закреплённая панель сжимает колонку текста уже 60 знаков (design.md, решение 1).
- Хранилище — новый ключ `philograph:v3` с переносом из `v2`.
- Прослеживаемость учитывает `RENAMED`: иначе для «Верхней панели» нужен тест до архива.

## Сейчас

Все пункты tasks.md закрыты. Изменение не архивировано: его проверяет тестировщик.

## Следующий шаг

Проверка тестировщиком (e2e, снимки, сверка с документами дизайна); затем Docker-стенд на настоящих данных и архив.

## Известные проблемы

- Пояснения заглушек (`detail`: «страница N: текст не распознан», «глава не оцифрована на сайте») сервер пишет по-русски: в английском интерфейсе подпись «Not rendered as text» переведена, пояснение — нет.
- Порог закрепления панели 1280px вместо 1024px из плана (design.md, решение 1): на 1024px закреплённая панель сжимает колонку текста уже 60 знаков.
- Сегментные переключатели языка и темы в раскрытой панели заменены кнопками по кругу: наведение раскрывает панель, и свёрнутая кнопка исчезала из-под указателя. Прямой выбор — в настройках.
- Эталоны снимков только для Windows (`baselines/win32`), как и раньше.
- Не сделано из плана (за пределами задачи разработчика): проверка на настоящих данных в Docker, обновление артефакта «Основа интерфейса PhiloGraph», архив изменения.

## Как проверить

- `/c/Users/Ivano/AppData/Local/Programs/openspec/openspec validate redesign-navigation`
- `cd web && npm run build`
- `.venv/Scripts/python scripts/visual_check.py` — сборка, проверки DOM и сравнение снимков (`--update` — переписать эталоны, только после просмотра)
- `.venv/Scripts/python -m pytest -q` (401 passed, 1 skipped)
- `.venv/Scripts/ruff.exe check .` и `.venv/Scripts/ruff.exe format --check .`
- `.venv/Scripts/python scripts/check_traceability.py` (315 из 315)
- Стенд: `.venv/Scripts/python scripts/dev_stack.py`
