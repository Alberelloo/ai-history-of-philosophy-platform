# Progress: reader-mentions-popover

Этап 2 из 6. Ведёт поток B (`claude/reader-wt-cards`). Актуализировано 2026-11-08. Готовность: около 90% (код и тесты готовы; снимки S1/S2/S3/S3a и просмотр — за интегратором).

## Статус по пунктам

| Пункт | Статус | Чем подтверждено |
| --- | --- | --- |
| 1.1 OpenSpec | сделано | `openspec validate reader-mentions-popover` — valid |
| 1.2 Popover.md | сделано | `docs/design/system/components/Popover.md` |
| 2.1 N1 `entity_type` | сделано | `mentions.py`, `tests/knowledge/test_mentions_cards.py` |
| 2.2 N2 404 `entity_not_found` | сделано | `test_card_not_found_returns_404` |
| 3.1–3.3 Упоминания и настройка | сделано | `ReaderPage.tsx` (`renderText`), `storage.ts`, `SettingsPage.tsx`; T6, T7 |
| 4.1–4.5 Окно карточки | сделано | `web/src/CardPopup.tsx`; T8–T11, T15 |
| 5.1 Тесты T6–T11, T15 | сделано | `tests/web/test_reader_cards.py`, 16 тестов (с параметрами) зелёные |
| 5.2 Снимки S1/S2/S3/S3a | не начато | эталоны пересоздаёт интегратор после слияния (правило 6 раздела 9 сводки) |
| 5.3 N11 деление `/mentions` по 500 | сделано | `ReaderPage.tsx` (`MENTIONS_CHUNK`), `test_n11_mentions_requested_in_parts_of_500` |
| 5.4 Доводка 4.2–4.7 по тестам | сделано | см. `tasks.md` 5.4 |

## Сейчас

Код и тесты этапа готовы. Тесты T6–T11, T15 и N11 браузерные, сервер знаний в них подменён (`page.route`), поэтому они идут без стенда за ~20 с. Серверная часть (N1, N2) проверяется `tests/knowledge/test_mentions_cards.py`.

## Следующий шаг

1. Интегратор: снимки S1 (4 ширины × 2 темы), S2, S3, S3a по схеме 14.3 и просмотр человеком.

## Замечания для интегратора

- Переход по связи в полной карточке (панель) сделан событием `philograph:open-card` (`FullCard.tsx` → `openCardInPanel`), его ловит `ReaderPage.tsx` и кладёт карточку в стек панели. `App.tsx` (чужой файл) не правился. Если хочется прямого колбэка, в `App.tsx` у `<FullCard>` можно передать `title={top.title}` (голова панели при загрузке показывает имя) — одна строка, необязательно.
- Окно больше не показывает «…» вместо имени (4.7): имя берётся из текста упоминания.
- Тест `tests/e2e/test_site.py::test_mention_opens_card_and_navigates` не правился и с новым поведением совместим (до двух утверждений, `h3` с именем).
- Playwright, дожидаясь неподвижной цели в появляющемся окне, иногда прокручивает страницу; окно по 4.3 закрывается, когда строка упоминания уходит из вида. В тестах после открытия окна ждём конца анимации (`opened()` в `test_reader_cards.py`).

## Как проверить

```bash
export TMP="$(pwd -W)/.stack/tmp" TEMP="$(pwd -W)/.stack/tmp"; mkdir -p "$TMP"
cd web && npm run build && npx tsc --noEmit && cd ..
PYTHONPATH="$(pwd)/src" <репозиторий>/.venv/Scripts/python -m pytest -q tests/web/test_reader_cards.py tests/knowledge/test_mentions_cards.py
/c/Users/Ivano/AppData/Local/Programs/openspec/openspec validate reader-mentions-popover
```
