# Журнал работы: redesign-foundations

Ведёт: разработчик фронтенда (Claude Opus). Ветка `claude/design-system`, WIP-коммиты.

## Статус пунктов tasks.md

| Пункт | Статус |
| --- | --- |
| 1.1 Генерация tokens.css | в работе: генератор `scripts/design_tokens.py` и `web/src/styles/tokens.css` готовы, теста ещё нет |
| 1.2 Шрифты @fontsource | в работе: пакеты поставлены, импорт в main.tsx ещё не сделан |
| 1.3 Компоненты pg-* на экранах | в работе: `web/src/styles/components.css`, `web/src/ui.tsx`; экраны ещё не переведены |
| 1.4 Верхняя панель | не начат |
| 1.5 Тема | в работе: поле `theme` в storage.ts |
| 1.6 Каталог RU/EN | в работе: `web/src/i18n/{ru,en,index}.ts`; экраны ещё не переведены |
| 1.7 Помощники визуальной проверки | не начат |
| 1.8 Тесты и эталоны | не начат |

## Сейчас

Каркас: токены, стили компонентов, каталог строк, общие компоненты. Сборка клиента ещё не проверялась (экраны не используют новые модули).

## Следующий шаг

Переписать экраны (App, TopBar, Library, Reader, Card, Graph, Assistant, Settings, Review, Notice) на каталог и компоненты, переписать `web/src/styles.css` на токены, inline-скрипт темы в `web/index.html`.

## Известные проблемы

- Упоминания в тексте приходят без типа сущности: цвет семьи для них пока нейтральный.

## Как проверить

- `.venv/Scripts/python scripts/design_tokens.py --check`
- `cd web && npm run build`
