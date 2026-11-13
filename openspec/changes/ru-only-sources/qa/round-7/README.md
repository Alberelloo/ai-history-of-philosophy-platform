# Раунд 7 проверки: ru-only-sources (исправление F-1 и регресс панели ассистента)

Роль: независимый E2E-тестировщик. Код, тесты и спецификации не менялись: `git status` показывает
только новые каталоги `qa/round-7/` и `qa/screenshots/round-7/`. Ветка `claude/ru-only-sources`,
коммит `16e19fa` (исправление F-1 — `570b559`). Проверка по `qa/cases.md` (TC-65, TC-56…TC-64,
UC-28/UC-30, EC-47…EC-52) и дельте `specs/regional-access` (R24–R26).

## Как воспроизвести

```powershell
cd ai-history-of-philosophy-platform
# Chromium не стартует с системным TMP: каталог внутри репозитория обязателен.
New-Item -ItemType Directory -Force .stack\tmp-round7 | Out-Null
$env:TMP = (Resolve-Path ".stack\tmp-round7").Path; $env:TEMP = $env:TMP
$env:PYTHONIOENCODING = "utf-8"

# 1. Команда человека: весь набор без e2e
.venv\Scripts\python.exe -m pytest -q -m "not e2e" -p no:cacheprovider

# 2. Кейс TC-65 подробно
.venv\Scripts\python.exe -m pytest -v -p no:cacheprovider `
  tests\web\test_assistant_dialogs.py::test_t22b_notice_not_retold_with_links `
  tests\web\test_assistant_dialogs.py::test_t22c_two_notices_keep_both_with_link `
  tests\web\test_assistant_dialogs.py::test_t22d_legacy_single_message_session_opens `
  tests\web\test_assistant_dialogs.py::test_t22_notice_without_library_support

# 3. Независимый живой стенд (dev_stack + свои источники + HTTP + Playwright)
.venv\Scripts\python.exe openspec\changes\ru-only-sources\qa\round-7\harness\live_checks.py
```

## Результаты

| Проверка | Итог |
| --- | --- |
| `pytest -q -m "not e2e"` (команда человека) | **543 passed, 1 skipped**, exit 0 (`pytest-full.log`); пропуск — гонка на PostgreSQL |
| Целевые тесты пометок (TC-65) | **4 passed**, exit 0 (`pytest-targeted.log`) |
| Независимый стенд (`live_checks.py`) | **25 из 25 проверок пройдены**, exit 0 (`live-report.json`) |

Артефакты: отчёт стенда — `live-report.json`, ран — `live-run.log`, журналы сервисов —
`harness/stand/logs/`, прогоны `pytest` — `pytest-*.log`, скриншоты — `qa/screenshots/round-7/`.

## Стенд

`scripts/dev_stack.py` в-process без демо-источников, плюс свой шлюз с
`PHILOGRAPH_REGION_HEADER=CF-IPCountry` и `PHILOGRAPH_TRUSTED_PROXY=1` (как в раунде 6).
Источник «Закрытый учебник без внешней обработки» зарегистрирован с **настоящим** видом
`public-domain-ru` из `sources/licenses.yaml` (регионы `[RU]`, `external_processing: false`) через
`CatalogService.ensure_license_kinds()`. Клиент — собранный `web/dist` (сборка 13.11 00:18,
позже правки `AssistantPanel.tsx`/`storage.ts`).

## Что проверено в браузере

- **TC-65, две пометки.** Читатель из РФ, глава источника `public-domain-ru`, включено «Только
  выбранный учебник», вопрос «Что такое Каллистика и какие у неё правила?». Сервер прислал
  `found_not_retold` и `no_library_support`; в ходе ровно **две** пометки `role="status"` над
  ответом: «Найдено в источниках, не пересказывается.» со ссылкой на абзац и «Ответ составлен без
  опоры на библиотеку.» (`TC-65-1-two-notices.png`). Вторая пометка первую не затирает.
- **TC-65, ссылка.** Клик ведёт на
  `/read/<источник>/<глава>#p-<абзац>`, абзац подсвечен и в окне просмотра
  (`TC-65-2-link-opened.png`).
- **TC-65, старая сессия.** В `localStorage` положен формат 3 (`philograph:v3`) с двумя ходами и
  единственным полем `message`; `/assistant` открывается без ошибок, пометки и ссылка на месте
  (`TC-65-3-legacy-v3-session.png`, `legacy-v3-state.json`).
- **Обычные пометки.** `no_library_support` (`TC-65-4-ordinary-notices.png`), `no_answer` с
  «Близкое в библиотеке» (`TC-65-6-no-answer-notice.png`, подставной поток —
  `notices-stub-no-answer.ndjson`), ошибка соединения «Ответ оборвался. Можно повторить.» с
  кнопкой «Повторить» (`TC-65-5-error-notice.png`).
- **Консоль.** В сценариях двух пометок, перехода по ссылке и старой сессии ошибок консоли и
  исключений страницы нет. Единственный `net::ERR_FAILED` — от намеренно оборванного запроса в
  проверке ошибки соединения.

## Регресс группы 7 (живой стенд)

Текст источника без `external_processing` не встречается ни в одном запросе к модели (TC-58,
TC-61/no-text, TC-63 — «ДЕЛЬТА-5» уходит модели, «СИГМА-3» нет); пометка `found_not_retold` для РФ
приходит со ссылкой (TC-58, EC-50); для DE источник закрыт целиком: `restricted: true`,
`regions: ["RU"]`, поиск его не отдаёт, в промпте текста нет (UC-28/DE); запрос без региона —
как DE (TC-60); индексация без внешней обработки: `external=false`, `embedded=false` (TC-56,
EC-48); поиск по регионам (TC-57); «только по источникам» — `found_not_retold` + `no_answer`
(EC-47); повтор вопроса детерминирован (EC-49); неоднозначное упоминание не разрешается моделью
(TC-61); данные 8.4 — `catalog validate` и `sync` (TC-8.4).

## Осталось непроверенным

- `no_answer` живьём: на подставном провайдере эмбеддингов смысловая выдача находится на любой
  вопрос, поэтому «поиск ничего не нашёл» не воспроизводится; отрисовка пометки проверена
  клиентом по подставному потоку NDJSON.
- `tests/e2e` (реальные процессы) не прогонялись — команда человека их исключает; сквозной путь
  проверен на живом стенде и тестом `tests/gateway/test_region_scope.py`.
- Настоящий CDN и проверка конфигурации развёртывания — задача 8.6, вне этого раунда.
- EC-51 (клавиатурный обход ссылки пометки) отдельно не проверялся: ссылка — обычный `<a href>`,
  роль `status` у пометок проверена; фокус с клавиатуры — на следующем раунде.
