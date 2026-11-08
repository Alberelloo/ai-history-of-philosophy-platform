# Progress: reader-full-card

Этап 3 из 6. Актуализировано 2026-11-08 по коду (файл создан впервые). Готовность: около 60% (клиент готов, серверные N3 и N10 и тесты нет).

## Статус по пунктам

| Пункт | Статус | Чем подтверждено |
| --- | --- | --- |
| 1.1 OpenSpec | сделано | `openspec validate reader-full-card` — valid |
| 1.2 Документы Portrait/PortraitGallery | сделано | `docs/design/system/components/Portrait.md`, `PortraitGallery.md`, `Lifeline.md` |
| 2.1 N3 `portraits` | частично | поле есть, но всегда `[]`: `src/philograph/knowledge/cards.py:189`; `test_card_has_portraits_field` |
| 2.2 N10 `first_paragraph_id` | не начато | grep по `src/` и `web/src` не находит |
| 3.1 PortraitGallery | сделано в коде | `web/src/ui.tsx:378`, `FullCard.tsx:181`; на данных не проверялась |
| 3.2 Lifeline | сделано | `FullCard.tsx:197` |
| 3.3 Переключатели источников | сделано | `FullCard.tsx:107, 200`; `test_textbook_scope_shared_by_graph_card_and_assistant` |
| 3.4 Сводка природы знания | сделано в коде | `FullCard.tsx:80, 204` |
| 3.5 Стек «Назад» до 20 | сделано | `App.tsx:95-102`, `ReaderPage.tsx:91` |
| 4.1 Тесты T10, T12–T14, T16 | частично | серверные аналоги T13/T14 и сквозной тест; T10, T12, T16 нет |
| 4.2 Снимки S4 | не начато | эталонов нет |

## Сейчас

Полная карточка в панели работает со всеми блоками. Портретов нет вовсе: сервер всегда отдаёт пустой список, клиент показывает монограмму и «Изображений нет». Это допустимо по разделу 16 дока (этап закрывается с монограммами), но T16 и S4 с портретами проверить нечем.

## Следующий шаг

1. Решить судьбу N3: отдельная серверная задача (отбор и хранение портретов с лицензиями, до 7 без дублей) или закрыть этап с монограммами и записать решение.
2. N10: `first_paragraph_id` в `where_to_read[]` (сервер знаний, `mentions.py`) и переход к абзацу в `FullCard`.
3. Тесты: T10 в панели, T12 (проверенная, сгенерированная, спорная строка), T16 (галерея через подмену `route` ответа карточки с `portraits`), T13/T14 в браузере.
4. Снимки S4 и их просмотр человеком.

## Известные проблемы

- N9 (`lang` у строк карточки) не сделан: у строк нет языка, EN-интерфейс показывает серверный текст как есть.
- Нет проверки, что для сущности без портрета в окне показывается монограмма 56px без счётчика (T11).

## Как проверить

```bash
export TMP="$(pwd -W)/.stack/tmp"; export TEMP="$TMP"; mkdir -p "$TMP"
/c/Users/Ivano/AppData/Local/Programs/openspec/openspec validate reader-full-card
.venv/Scripts/python -m pytest -q tests/knowledge/test_mentions_cards.py
.venv/Scripts/python -m pytest -q -k "test_textbook_scope_shared or test_mention_opens_card"
.venv/Scripts/python scripts/check_traceability.py
```
