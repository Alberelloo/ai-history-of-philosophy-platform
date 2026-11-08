# Progress: reader-mentions-popover

Этап 2 из 6. Актуализировано 2026-11-08 по коду. Готовность: около 70% (код около 90%, тесты и снимки около 20%).

## Статус по пунктам

| Пункт | Статус | Чем подтверждено |
| --- | --- | --- |
| 1.1 OpenSpec | сделано | `openspec validate reader-mentions-popover` — valid |
| 1.2 Popover.md | сделано | `docs/design/system/components/Popover.md` |
| 2.1 N1 `entity_type` | сделано | `mentions.py:323`, `tests/knowledge/test_mentions_cards.py:232` |
| 2.2 N2 404 `entity_not_found` | сделано | `test_card_not_found_returns_404` |
| 3.1–3.3 Упоминания и настройка | сделано | `ReaderPage.tsx:146-150, 699`, `storage.ts:86`, `SettingsPage.tsx:155` |
| 4.1–4.5 Окно карточки | сделано | `web/src/CardPopup.tsx` (кэш 50, `AbortController`) |
| 5.1 Тесты T6–T11, T15 | частично | есть один сквозной `test_mention_opens_card_and_navigates` и серверные тесты; отдельных T6–T11, T15 нет |
| 5.2 Снимки S1/S2/S3/S3a | не начато | в `tests/e2e/visual/baselines/` эталонов окна карточки по схеме 14.3 нет |

## Сейчас

Клиент и сервер этапа работают. Раньше в `tasks.md` пункты 5.1 и 5.2 были отмечены без подтверждения тестами; отметки сняты.

## Следующий шаг

1. Тесты в `tests/web/` (например `test_reader_popover.py`): T6 (503 на `/mentions`: текст без упоминаний), T7 (цвет `people`/`ideas`), T8 (наведение 2 с и проход по пяти упоминаниям ничего не открывают), T9 (переворот вверх на 1280), T10 (переход «Кант» и «Назад»), T11 (до двух утверждений, нет счётчика), T15 (`route`: задержка, 404, 503; «Повторить»).
2. Снимки S1, S2, S3, S3a и их просмотр человеком.
3. Проверить критерий: на всех ширинах окно не пересекает строку упоминания.

## Известные проблемы

- N11: `/mentions` обрезает `targets[:500]` (`src/philograph/knowledge/app.py:172`), а клиент отправляет все абзацы главы одним запросом (`ReaderPage.tsx:515`). В главах больше 500 блоков упоминания пропадают. Нужно делить запрос на части по 500 в клиенте (раздел 13 дока).
- Пока нет T8, правило «наведение ничего не открывает» тестом не закреплено.

## Как проверить

```bash
export TMP="$(pwd -W)/.stack/tmp"; export TEMP="$TMP"; mkdir -p "$TMP"
/c/Users/Ivano/AppData/Local/Programs/openspec/openspec validate reader-mentions-popover
.venv/Scripts/python -m pytest -q tests/knowledge/test_mentions_cards.py
.venv/Scripts/python -m pytest -q -k test_mention_opens_card_and_navigates
.venv/Scripts/python scripts/check_traceability.py
```
