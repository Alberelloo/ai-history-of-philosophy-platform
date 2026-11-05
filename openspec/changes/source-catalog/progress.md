# Журнал работы: source-catalog

Ведёт: основная сессия (Claude Opus). Рабочая копия `../philograph-sources`, ветка `claude/source-catalog` (основана на `claude/openspec-archive`, после слияния PR #24 перебазировать на main). После каждого пункта — WIP-коммит и пуш.

План целиком: `C:\Users\Ivano\.claude\plans\warm-shimmying-umbrella.md` (части A и B).

## Статус пунктов tasks.md

| Пункт | Статус |
| --- | --- |
| 1.1–4.4 | не начат |
| 5.1–5.3 | не начат |

## Решения

- Каталог в git, а не автоматический обход сайтов: лицензию и качество подтверждает человек или ревью PR.
- Пользователь разрешил для пробной загрузки брать любые легально открытые источники (общественное достояние, открытые лицензии) и одобрять записи без него: это проверка работоспособности, потом всё перезагрузят.
- Wikisource — через ws-export (EPUB со всеми подстраницами), Gutenberg — EPUB с очисткой `pg-header`/`pg-footer`.

## Сейчас

Завожу изменение OpenSpec.

## Следующий шаг

1.1 миграция и `replace_files`.

## Известные проблемы

- Нет ключа модели: онтология и смысловой поиск на настоящих данных не проверяются.

## Как проверить

- `PYTHONPATH=src ../ai-history-of-philosophy-platform/.venv/Scripts/python -m pytest tests/library/catalog -q`
- `... -m philograph.library.catalog validate`
