## 1. Основа

- [x] 1.1 Учёт: миграция 3 (`catalog_links`, `fetch_state`), `Registry.replace_files`
- [x] 1.2 Формат каталога: `sources/catalog.schema.json`, `sources/licenses.yaml`, модель записи, чтение и запись YAML, итоговые метаданные (сайт ⊕ правки)
- [x] 1.3 `validate`: схема, повторы, одобренные без лицензии, исчезнувшие записи (`sources/catalog.lock.json`)

## 2. Загрузка

- [x] 2.1 `Fetcher`: User-Agent, 1 запрос/с на сайт, robots.txt, повторы, предел размера, условные запросы, учёт неудач и перенаправлений
- [x] 2.2 Адаптеры: gutenberg (RDF, EPUB, очистка служебных частей), wikisource (ws-export EPUB, Wikidata), archive_org, direct; Wikidata для годов смерти
- [x] 2.3 `add` и `harvest`

## 3. Синхронизация

- [x] 3.1 `sync`: регистрация и связь, обновление описания и файлов, запуск обработки, отзыв
- [x] 3.2 Правило публикации (auto, 2%, тот же текст), предупреждения
- [x] 3.3 `status`, `check-updates`, задача очереди через загрузчик каталога

## 4. Документы и проверки

- [x] 4.1 `docs/architecture/source-ingestion.md`, ADR-0002, ссылки из `docs/README.md`
- [x] 4.2 Тесты требований `source-catalog` (без сети), трассировка
- [x] 4.3 Сквозной тест: локальный HTTP → `sync` → источник в читалке
- [x] 4.4 `catalog validate` в CI

## 5. Настоящие данные

- [x] 5.1 Поиск открытых источников (агент Haiku): 15–25 первоисточников, не меньше 3 учебников, справочники; `sources/discovery-report.md`
- [x] 5.2 Пробная загрузка на стенде, отладка, итоги в `validation.md`
- [ ] 5.3 Полный pytest, архивирование изменения, PR
