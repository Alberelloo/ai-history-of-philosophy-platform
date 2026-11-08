# Экран чтения: сводка для продолжения работы

Составлена 2026-11-08 по коду ветки `claude/reader-design` (она же `origin/claude/reader-implementation`). Источник требований: [design/features/reader-panels.md](../design/features/reader-panels.md) (v1.2). Статус по этапам: `openspec/changes/<этап>/progress.md` и `tasks.md`. Все отметки там проверены по коду, не по прежним записям.

## 1. Состояние

Работает: раскладка K1–K4 с правой панелью (сдвиг и полоска), окно карточки по щелчку с цветом семьи и настройкой вида упоминаний, полная карточка в панели (линия жизни, переключатели источников, сводка природы знания, стек «Назад»), панель ассистента с сессиями, стадиями ответа, хранилищем формата 4 и тайм-аутом, сноски на поле и в окне, номера страниц, плашки неразобранных частей по кодам, страница `/assistant` с границей «шире книги / вне книги» и переносом вопроса. Не работает или не сделано: портреты (сервер всегда отдаёт `portraits: []`), `first_paragraph_id` в «Где читать», деление запроса `/mentions` на части по 500 (в длинных главах пропадают упоминания), Alt+Q, переход между книгами с уведомлением «Вы пришли из диалога» (Р13), метка главы у обмена, масштаб rem на библиотеке, графе и настройках, эталонные снимки по схеме 14.3 (в `tests/e2e/visual/baselines/` лежат только старые). Из 48 тестов T1–T48 целиком закрыты 3, частично 31, нет 14 (раздел 4). В `main` слиты PR #28 (боковая навигация, хранилище v3) и #30 (дизайн-документ v1.2); вся реализация чтения лежит в ветке `claude/reader-implementation` (локально `claude/reader-design`), PR откроется после этой актуализации. Этапы 4 и 6 выходят к читателям одним выпуском.

## 2. Этапы

| # | Этап | Готовность | Что осталось | Зависит от | Где тесты |
| --- | --- | --- | --- | --- | --- |
| 1 | `reader-layout` | около 85% | T5, T37, T32, T4 полностью, T45 (2560 + rem на библиотеке, графе, настройках, задача 2.2), снимки S0/S5/полоски, просмотр | этап 0 (слит) | `tests/web/test_reader_layout.py`, `tests/e2e/test_visual_design.py` |
| 2 | `reader-mentions-popover` | около 70% | тесты T6–T11, T15; снимки S1/S2/S3/S3a; N11 (деление `/mentions` по 500) | этап 1 | `tests/knowledge/test_mentions_cards.py`, `tests/e2e/test_site.py::test_mention_opens_card_and_navigates` |
| 3 | `reader-full-card` | около 60% | N3 (портреты: отбор и хранение, либо решение закрыть с монограммами), N10, тесты T10, T12, T16, снимки S4 | этап 2 | `tests/knowledge/test_mentions_cards.py`, `tests/e2e/test_site.py` |
| 4 | `reader-assistant` | около 70% | Р13 (Notice «Вы пришли из диалога», «Вернуться»), Alt+Q, метка главы у обмена, N4 `chapter_title`, проверка N5, тесты T21–T23, T25, T38, T39, T40, T48, снимки S6–S10, S12 | этап 1 | `tests/web/test_assistant_panel.py`, `tests/assistant/`, `tests/e2e/test_settings.py` |
| 5 | `reader-notes` | около 90% | тест каскада и «↑» (T28), клавиатура окна сноски, номер страницы вне выделения (T29), снимки поля и окна | этап 1 | `tests/web/test_reader_notes.py`, `tests/library/test_unrendered_parts.py` |
| 6 | `assistant-page` | около 85% | T36, T41 (двойной щелчок), T42, полный T46, перепроверка round-3 тестировщиком, запись в журнал решений `docs/design/design-system.md` | этап 4 | `tests/assistant/test_handoff.py`, `tests/web/test_assistant_panel.py` |

`openspec validate` для всех шести этапов даёт valid. У `assistant-page` проверка падала (два блока MODIFIED без полного набора сценариев); при актуализации блоки исправлены в `specs/visual-design/spec.md` и `specs/assistant-dialog/spec.md`. Остаётся предупреждение о длине требования «Раздел „Ассистент“».

## 3. Нужно от сервера (раздел 12.2 дока)

| # | Что | Статус | Подтверждено |
| --- | --- | --- | --- |
| N1 | `entity_type` у упоминаний | сделано | `mentions.py:323`, `test_mentions_cards.py:232` |
| N2 | 404 `entity_not_found` | сделано | `test_card_not_found_returns_404` |
| N3 | `portraits` | частично | поле есть, всегда `[]` (`cards.py:189`); отбора и хранения нет |
| N4 | `source_title`, `chapter_title`, начало абзаца | частично | `source_title` и 120 знаков есть (`service.py:405-406`), `chapter_title` нет |
| N5 | `entity_id` у ссылки на утверждение | частично | поле передаётся (`service.py:423`), значение и тест не проверены |
| N6 | `paragraph_id` в suggestions `no_answer` | сделано | `test_routing_grounding.py` |
| N7 | `detail_code`, `page` | сделано | `parse.py`, `schema.py` (миграция 4), `test_unrendered_parts.py` |
| N8 | `answer_language` в `done` | сделано | `service.py:364, 439`, `test_routing_grounding.py:174` |
| N9 | `lang` у строк и описания карточки | не сделано | в `cards.py` нет |
| N10 | `first_paragraph_id` в `where_to_read[]` | не сделано | нет ни в сервере, ни в клиенте |
| N11 | более 500 абзацев в `/mentions` | не сделано | `app.py:172` обрезает до 500, клиент не делит (`ReaderPage.tsx:515`) |
| N12 | `context`, `handoff_declined`, событие `handoff` | сделано | `tests/assistant/test_handoff.py` |
| N13 | события стадий | сделано | `test_routing_grounding.py:167` |

Итого: полностью N1, N2, N6, N7, N8, N12, N13 (7); частично N3, N4, N5 (3); нет N9, N10, N11 (3).

## 4. Тесты T1–T48

Тесты не названы по номерам Tn (grep по `T[0-9]+` находит только `T1` в докстринге `test_reader_layout.py`). Сопоставление ниже сделано по сценарию и маркеру `@req`. Всего в проекте собирается 426 тестов (`pytest --collect-only`). Выборочный запуск `-k "test_card_not_found_returns_404 or test_card_has_portraits_field or test_footnotes_on_field_in_k1 or test_layout_modes_and_text_measure or test_answer_stages_visible"` дал 5 passed. Полный прогон при актуализации не запускался.

Обозначения: **есть** — тест закрывает основное; **частично** — покрыта часть сценария или проверка косвенная; **нет** — отдельного теста нет.

| Статус | Тесты |
| --- | --- |
| есть (3) | T2, T27, T30 |
| частично (31) | T1, T3, T4, T6, T8, T11, T12, T13, T14, T17, T18, T19, T20, T21, T24, T25, T26, T28, T29, T31, T32, T33, T34, T35, T36, T40, T41, T43, T44, T46, T47 |
| нет (14) | T5, T7, T9, T10, T15, T16, T22, T23, T37, T38, T39, T42, T45, T48 |

Что именно покрыто частично и чем:

- T1, T3: `test_layout_modes_and_text_measure`, `test_panel_strip_on_narrow_screen`; нет тем, языков, 2560, Esc, Enter на полоске, свёртки во время потока.
- T4: `test_reading_position_kept` (только открытие и закрытие ассистента, без смены ширины и карточки).
- T6: `test_chapter_without_knowledge_service`; T8, T11, T12: `test_mention_opens_card_and_navigates` (без проверки наведения, портрета, `pg-generated`).
- T13, T14: серверные `test_no_empty_sections`, `test_card_without_model_and_streamed_description`, `test_generated_description_saved`.
- T17, T18: `test_ask_about_selection`, `test_selection_toolbar` (нет Alt+Q, выделения через два абзаца, ограничения 4000 знаков).
- T19, T24: серверные `test_length_limit`, `test_unavailable_and_limits` и клиентский `test_error_mid_answer_keeps_marks`; клиентского счётчика и всех кодов 5.7 нет.
- T20, T21, T25: `test_stream_and_stop`, `tests/e2e/test_site.py::test_assistant_on_selection_through_all_services`.
- T26, T40, T47: `test_dialog_memory`, `test_old_format_migrated`, `test_sessions_are_separate`.
- T28, T29, T30: `tests/web/test_reader_notes.py`.
- T31, T32, T33, T34, T35, T36: регрессы `tests/web/test_library_reading.py`, `test_reading_journey`, `test_keyboard_focus_ring`, `test_main_screens_in_both_themes`, `test_reduced_motion_keeps_only_fade`, `test_english_interface`; для T32 нет слоя K3, для T36 нет страницы «Ассистент» и S7a.
- T41, T43, T44, T46: `test_handoff_block_and_transfer_link`, `test_assistant_page_and_stub`, `test_answer_stages_visible` и серверные `test_handoff.py`.

T39 и Р13 не реализованы в клиенте вообще (строки «Вы пришли из диалога» в `web/src` нет), поэтому и теста нет.

## 5. Как запускать

```bash
# 1. Один раз за сессию. Без этого Chromium молча пропускает браузерные тесты.
export TMP="$(pwd -W)/.stack/tmp"; export TEMP="$TMP"; mkdir -p "$TMP"

# 2. Клиент
cd web && npm run build && npx tsc --noEmit && cd ..

# 3. Визуальная проверка (сборка, DOM-проверки, сравнение снимков)
.venv/Scripts/python scripts/visual_check.py            # --update переписывает эталоны, только после просмотра

# 4. Тесты
.venv/Scripts/python -m pytest -q -m "not e2e"
.venv/Scripts/python -m pytest -q tests/e2e
.venv/Scripts/python -m pytest -q -k <имя_теста>        # точечно

# 5. Линтеры и прослеживаемость
.venv/Scripts/python -m ruff check src tests scripts
.venv/Scripts/python -m ruff format --check src tests scripts
.venv/Scripts/python scripts/check_traceability.py      # сейчас 322 из 322
lint-imports

# 6. OpenSpec
/c/Users/Ivano/AppData/Local/Programs/openspec/openspec validate <этап>

# 7. Docker (демо-модель)
docker compose -f compose.yaml -f compose.e2e.yaml up -d --build --wait   # http://127.0.0.1:8080; нужен .env из .env.example
```

Замечания:

- `ruff check .` без путей находит ошибки в неотслеживаемом каталоге `pytest-of-Ivano/` (временные файлы тестов). Это не код проекта; проверять `src tests scripts`.
- Playwright требует `TMP`/`TEMP` внутри рабочей папки (иначе Chromium не создаёт каталог в `AppData\Local\Temp`).
- Каждый тест помечается `@req("<возможность>", "<требование>")`, иначе `check_traceability.py` падает.

## 6. Процесс

Цикл на каждый этап:

1. Разработчик (Opus) пишет код и тесты, ведёт `tasks.md` и `progress.md`.
2. Тестировщик (Haiku) снимает снимки, проверяет DOM и сверяет с документами.
3. Если есть расхождения, следователь (Opus) пишет диагноз в `openspec/changes/<этап>/qa/round-N-diagnosis.md`, разработчик исправляет.
4. Повторять, пока расхождений нет. Предел `dev_cycle` — 3 раунда; после него нужна независимая перепроверка отдельным запуском (для `assistant-page` она ещё не проведена).

Контрольные точки: после каждого пункта обновлять `tasks.md` и `progress.md`, делать коммит `wip(<этап>): …` и пушить, чтобы прерванную работу можно было продолжить.

Правила репозитория ([git-workflow.md](git-workflow.md)):

- В `main` не пушить, все изменения через PR. Ветки `claude/<кратко>`.
- Заголовок PR: `<тип>: <что сделано>`, по-русски. Описание: «Что изменилось», «Зачем», «Как проверить».
- Конец описания PR: `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- Коммиты заканчиваются строкой `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Файл `.env` не коммитить. Хуки не обходить (`--no-verify` не использовать).
- Автослияние в этом репозитории включает бот GitHub сразу после открытия PR. PR, которые нельзя сливать без решения владельца, открывать черновиками (draft).
- Не добавлять в коммит неотслеживаемые файлы вне `docs` и `openspec` без причины (`.dockerignore`, `.dsh/`, `pytest-of-Ivano/`).

## 7. Порядок продолжения

Рекомендация:

1. **Закончить этап 4 и довести до выпуска вместе с 6.** Р13 и T39 (уведомление «Вы пришли из диалога» и «Вернуться»), Alt+Q (T17), метка главы у обмена, затем тесты T21, T22, T23, T25, T38, T40, T48 и T41, T42, T46, T36. Этапы 4 и 6 выходят к читателям вместе, так что это блокирует выпуск.
2. **Закрыть дыры в этапах 1–3 и 5.** N11 (деление `/mentions` по 500; это реальная потеря упоминаний), N10, тесты T5, T37, T32, T6–T11, T15, T10, T12, T16, T28/T29 полностью. Решить судьбу N3: отдельной серверной задачей или закрыть этап с монограммами.
3. **Снимки и просмотр человеком.** Эталоны по схеме 14.3 для всех состояний, просмотр владельцем, затем запись в журнал решений `docs/design/design-system.md` (последний шаг раздела 16), 2.2 (rem на общих экранах) и T45. После этого открыть PR из `claude/reader-implementation` в `main`; пока владелец не принял снимки, открывать черновиком.

Решения владельца Р1–Р13 приняты и не пересматриваются (подробности в начале дока): Р1 свой набор сессий на книгу; Р2 полоска на 1024–1279; Р3 общие вопросы уходят в раздел «Ассистент» только при переходе; Р4 отдельной метки непроверенной карточки нет; Р5 окно только по щелчку; Р6 панель и окно не восстанавливаются после перезагрузки, `?card=` не вводится; Р7 колонки без анимации; Р8 стадии без процента и счётчика слов; Р9 плавный масштаб везде; Р10 выбор при выходе за источник; Р11 сессии у книг и раздела; Р12 диалоги закрытых книг сохраняются; Р13 ссылка на абзац другой книги переключает диалог.

## 8. Известные проблемы и спорное

- N11: упоминания пропадают в главах с более чем 500 блоками.
- Портреты: пока `[]`, галерея проверена только на пустом списке; формат лицензий и источник изображений не решены.
- Р13 не реализован, хотя решение принято.
- Прежние `progress.md` преувеличивали: у `reader-mentions-popover` тесты T6–T11, T15 были отмечены готовыми без самих тестов; `assistant-page` значился «готов» при невалидном OpenSpec; `reader-notes` значился «не начат» при готовом коде. Теперь исправлено, но отмечать «готово» стоит только по тесту.
- Независимая перепроверка исправлений round-3 в `assistant-page` не проведена; пиксельный просмотр снимков человеком не проводился ни для одного этапа (модель изображения не заменяет просмотр).
- Эталоны снимков называются не по схеме 14.3 и существуют только для платформы `win32`.
- Сопоставление тестов с T1–T48 здесь выполнено вручную: в самих тестах номеров нет. При написании новых тестов стоит указывать Tn в имени или докстринге.
- В дельтах OpenSpec `assistant-page` MODIFIED-блоки должны содержать все сценарии текущей спецификации (иначе валидация падает); это нужно помнить и при новых изменениях.
- В `reader-panels.md` (15) открытых вопросов нет; сомнения остаются у реализации, а не у дизайна: производительность поля сносок (один проход после `document.fonts.ready`) и загрузка упоминаний больших глав.
