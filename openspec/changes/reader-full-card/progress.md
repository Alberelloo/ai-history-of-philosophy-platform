# Progress: reader-full-card

Этап 3 из 6. Ведёт поток B (`claude/reader-wt-cards`). Актуализировано 2026-11-08. Готовность: около 90% (код и тесты готовы; снимки S4 и просмотр — за интегратором).

## Статус по пунктам

| Пункт | Статус | Чем подтверждено |
| --- | --- | --- |
| 1.1 OpenSpec | сделано | `openspec validate reader-full-card` — valid |
| 1.2 Документы Portrait/PortraitGallery | сделано | `docs/design/system/components/Portrait.md`, `PortraitGallery.md`, `Lifeline.md` |
| 2.1 N3 `portraits` | закрыто монограммами | сервер отдаёт `[]`; отбор и хранение — черновик `openspec/changes/portrait-sourcing/` |
| 2.2 N10 `first_paragraph_id` | сделано | `mentions.py` (`where_to_read`, `position`), миграция `knowledge` 6, `FullCard.tsx` (`whereToReadLink`); тесты в `tests/knowledge/test_mentions_cards.py` и `tests/web/test_reader_cards.py` |
| 3.1 PortraitGallery | сделано | T16 на подменённом ответе (5, 1, 0 изображений) |
| 3.2 Lifeline | сделано | `FullCard.tsx` |
| 3.3 Переключатели источников | сделано | `test_textbook_scope_shared_by_graph_card_and_assistant` |
| 3.4 Сводка природы знания | сделано | T12 |
| 3.5 Стек «Назад» до 20 | сделано | T10 |
| 3.6 Переход по связи в панели | сделано | T10 («Назад: Кант») |
| 3.7 Состояния панели, `pg-generated` у строки | сделано | T12; `web/src/styles/card.css` |
| 4.1 Тесты T10, T12, T16 | сделано | `tests/web/test_reader_cards.py` |
| 4.2 Снимки S4 | не начато | эталоны пересоздаёт интегратор (правило 6 раздела 9 сводки) |

## Решение по N3

Этап закрыт с монограммами (раздел 16 дока: «если не успевает — этап закрывается с монограммами»). Монограмма и «Изображений нет» — штатное состояние. Клиент готов к данным: галерея проверена T16 на ответе с портретами. Чего не хватает до полной поддержки, записано в черновике `portrait-sourcing`:

- `Portrait` в `web/src/ui.tsx` не принимает изображение: в окне у упоминания даже при непустом `portraits` показывается монограмма (T11 проверяет медальон 56px без счётчика, но не изображение).
- Подпись `PortraitGallery` — автор и год; лицензии и ссылки на источник нет (требование «Портреты в карточке» и T16 их ждут).

`web/src/ui.tsx` — общий файл, не потока B; правки — после решений владельца, через интегратора.

## Замечания для интегратора

- Миграция `knowledge` 6 (`position` у `mentions`). Старые строки без порядка: «Где читать» берёт порядок вставки; точный порядок появится после пересчёта упоминаний (новая публикация версии или `recompute_entity`).
- `App.tsx` (чужой): у `<FullCard>` можно добавить `title={top.title}`, тогда при загрузке панель показывает имя, а не только «Загружаем карточку…». Необязательно.
- `web/src/main.tsx`: добавлена одна строка `import "./styles/card.css";` в конце импортов стилей.

## Как проверить

```bash
export TMP="$(pwd -W)/.stack/tmp" TEMP="$(pwd -W)/.stack/tmp"; mkdir -p "$TMP"
cd web && npm run build && npx tsc --noEmit && cd ..
PYTHONPATH="$(pwd)/src" <репозиторий>/.venv/Scripts/python -m pytest -q tests/web/test_reader_cards.py tests/knowledge
/c/Users/Ivano/AppData/Local/Programs/openspec/openspec validate reader-full-card
```
