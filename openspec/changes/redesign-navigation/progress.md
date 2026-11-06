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
| 6.3 Визуальные эталоны | не начат |
| 6.4 Итоговый прогон | не начат |

## Решения

- Порог закрепления панели — 1280px, а не 1024px из плана: на 1024px закреплённая панель сжимает колонку текста уже 60 знаков (design.md, решение 1).
- Хранилище — новый ключ `philograph:v3` с переносом из `v2`.
- Прослеживаемость учитывает `RENAMED`: иначе для «Верхней панели» нужен тест до архива.

## Сейчас

Пункт 6.2 закрыт. Все тесты, кроме сравнения снимков, зелёные (tests/web, tests/e2e, tests/library). Язык и тема в панели — одни и те же кнопки в свёрнутом и раскрытом виде (Sidebar.md, design.md); фокус раскрывает панель только с клавиатуры.

## Следующий шаг

6.3 — посмотреть снимки, обновить эталоны и эталонные снимки компонентов.

## Известные проблемы

Нет.

## Как проверить

- `/c/Users/Ivano/AppData/Local/Programs/openspec/openspec validate redesign-navigation`
