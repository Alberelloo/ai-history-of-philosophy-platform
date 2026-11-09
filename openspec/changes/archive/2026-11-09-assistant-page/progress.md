# Progress: assistant-page

Этап 6 из 6. Ведёт поток A (`claude/reader-wt-assistant`), обновлено 2026-11-08. Готовность: около 95% (тесты критерия зелёные, журнал решений записан; остались снимки и независимая перепроверка). Выходит к читателям вместе с этапом 4.

## Статус по пунктам

| Пункт | Статус | Чем подтверждено |
| --- | --- | --- |
| 1.1–1.2 Сервер N12 | сделано | `tests/assistant/test_handoff.py` (4 теста) |
| 2.1 Страница `AssistantPage.tsx` | сделано | `test_assistant_page_and_stub`, `test_t48_sessions_on_assistant_page` |
| 2.2 Маршрут и редирект заглушки | сделано | `test_t43_nav_item_current_without_soon` |
| 2.3 Пункт в навигации | сделано | `aria-current="page"`, без «скоро» — `test_t43_…` |
| 3.1 Блок S7a | сделано | `test_t46_boundary_and_stay_in_book[broader]`, `[outside_book]` |
| 3.2 Поручение, отправка один раз | сделано | `test_t41_transfer_sends_once`, `test_t42_reload_and_direct_address_do_not_send`, `test_t42_notice_not_closed_does_not_send` |
| 3.3 i18n | сделано | `test_t36_assistant_page_and_boundary_in_english` |
| 4.1 T36, T41–T43, T46 | сделано | `tests/web/test_assistant_page.py` (7 тестов, зелёные) |
| 4.2 Прослеживаемость | сделано | 322 из 322 |
| 5.1 `openspec validate` | сделано | valid |
| 5.2 Перепроверка round-3 | не начато | нужен отдельный запуск тестировщика |
| 5.3 Журнал решений | сделано | `docs/design/design-system.md`, запись 2026-11-08 |
| 5.4 Доработки потока A | сделано | см. `tasks.md` |

## Для интегратора

- Снимки страницы «Ассистент» (пустая, с диалогом, «перенесён и не отправлен», «уже задан») и S7a по 14.3 — после слияния.
- ~~Подпись обмена в разделе — «Из книги „…“» без названия главы.~~ Сделано 2026-11-09: `from.chapterTitle`, подпись «Из книги «…», глава «…»» (`test_transfer_shows_book_and_chapter`).
- Критерий «в журнале `assistant.question.received` один вопрос на переход» проверен по запросам `/ask` в браузере (`test_t41_…`: ровно один запрос с `context: "library"`); по журналу сервиса — на стенде.

## Как проверить

```bash
export TMP="$(pwd -W)/.stack/tmp" TEMP="$TMP"; mkdir -p "$TMP"; export PYTHONPATH="$(pwd)/src"
cd web && npm run build && cd ..
python -m pytest -q tests/assistant/test_handoff.py tests/web/test_assistant_page.py
/c/Users/Ivano/AppData/Local/Programs/openspec/openspec validate assistant-page
```
