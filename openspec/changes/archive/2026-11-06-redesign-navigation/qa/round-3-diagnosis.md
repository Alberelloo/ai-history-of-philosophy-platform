# Раунд 3: диагноз (redesign-navigation)

Вход: `qa/round-3.md`, ветка `claude/design-system`. Код не менялся.

| № | Причина | Решение | Объём |
| --- | --- | --- | --- |
| D1 | Шлюз передаёт `request.query_params` в `httpx` как словарь, и из повторяющихся ключей остаётся только последний (`kind=textbook&kind=primary` превращается в `kind=primary`). Тесты библиотеки в браузере идут мимо шлюза, поэтому ошибку не видели. | В `proxy` передавать исходную строку запроса без разбора (`httpx.URL(...).copy_with(query=request.scope["query_string"])`). Тесты `tests/web` пустить через настоящий шлюз и добавить проверку по API с двумя видами. | 1 строка кода, около 15 строк в `tests/web/conftest.py`, 1 тест |
| D2 | `.sidebar__book-title` обрезает текст до двух строк через `-webkit-line-clamp: 2`. Проверка `clipped_text` смотрит только горизонтальное переполнение, поэтому вертикальную обрезку не заметила. | Убрать ограничение строк в CSS, исправить Sidebar.md на «полностью, переносится на нужное число строк, без многоточия», добавить в `clipped_text` вертикальную проверку. | 4 строки CSS, 1 строка документа, около 5 строк в `tests/e2e/visual.py` |

---

## D1. Фильтры по нескольким значениям (блокирует)

### Где теряется значение

Значение теряется **на шлюзе, когда он строит запрос к библиотеке**. Клиент и обработчик библиотеки работают правильно.

1. **Клиент шлёт правильно.** В `web/src/api.ts:80-83` используется `URLSearchParams` и `append("kind", k)` для каждого вида, то есть уходит `?kind=textbook&kind=primary`. Формат `kind=a,b` клиент не использует. `LibraryPage.tsx:25` передаёт массивы `kinds` и `languages` в `api.sources`.
2. **Шлюз теряет.** В `src/philograph/gateway/app.py:165-171` стоит `client.build_request(..., params=request.query_params, ...)`. `request.query_params` в Starlette имеет тип `ImmutableMultiDict`. httpx 0.28.1 разбирает его как обычный `Mapping` через `.items()`, а `.items()` у этого типа отдаёт словарь, где из повторов остаётся последнее значение. Проверено:
   ```
   QueryParams('kind=textbook&kind=primary&q=x').items()  -> [('kind','primary'), ('q','x')]
   build_request(params=q).url                           -> ?kind=primary&q=x
   build_request(params=q.multi_items()).url             -> ?kind=textbook&kind=primary&q=x
   ```
   Сквозная проверка: поддельная библиотека с `kind: list[str] = Query(default=[])` за настоящим `gateway.build_app` через `ASGITransport`:
   ```
   напрямую   ?kind=textbook&kind=primary -> {'kind': ['textbook', 'primary']}
   через шлюз ?kind=textbook&kind=primary -> {'kind': ['primary']}
   ```
3. **Библиотека принимает правильно.** `src/philograph/library/app.py:33-36`, `kind: list[str] = Query(default=[])` получает повторяющиеся ключи списком. `reading.py:128-133` фильтрует по вхождению в список. Формат `kind=a,b` FastAPI считает одним значением `'a,b'`, и такого вида нет. Поддерживать запятые не нужно: клиент их не шлёт.

Почему «Выбрать все» даёт 0. Клиент шлёт `kind=textbook&kind=primary&kind=reference`, а до библиотеки доходит только `kind=reference`. Справочных изданий в демо нет, отсюда пустой список. Пара «учебник + первоисточник» превращается в `kind=primary`, отсюда один первоисточник.

Происхождение. Строка появилась в `db519cc` («шлюз, стенд одной командой…», #14), а не в `2a9d35b`. Сейчас она есть и в `main` (`main:src/philograph/gateway/app.py:168`).

Почему тесты не поймали. `tests/web/test_library_reading.py:75-101` (`test_kind_filter`, `test_kind_filter_select_all_clear_all_and_closing`) проверяют ровно эти сценарии и проходят, потому что `tests/web/conftest.py:152` запускает `library.app.build_app(reading, web_root=DIST)` **без шлюза**. `tests/e2e/test_site.py:24-41` идёт через шлюз (стенд `dev_stack`), но проверяет только один вид.

### Какие ещё эндпоинты страдают

Через шлюз проксируются три сервиса: `library`, `assistant`, `knowledge` (`gateway/app.py:188-208`). Сервис поиска наружу не выходит.

| Эндпоинт | Параметр-список | Сейчас через шлюз | Задет |
| --- | --- | --- | --- |
| `GET /api/v1/sources` (library, `library/app.py:34`) | `kind`, `lang` | клиент шлёт повторы | **да, D1**: фильтр «Вид» и фильтр «Язык» |
| `GET /api/knowledge/v1/entities/{id}/statements` (`knowledge/app.py:103-107`) | `family: list[str]` | клиент не вызывает | скрыто: при двух семействах останется одно |
| `GET /api/knowledge/v1/graph` (`knowledge/app.py:109-119`) | `start: list[str] = Query()` | клиент не вызывает, страница графа использует `POST /graph/build` | скрыто: несколько начальных узлов сократятся до одного |
| `GET /api/knowledge/v1/mentions?targets=a,b` (`knowledge/app.py:168-171`) | один параметр через запятую | `ReaderPage.tsx:264` | нет: ключ один, сервер сам делит по запятой |
| `POST /api/assistant/v1/ask`, `POST /api/knowledge/v1/graph/build` | списки в JSON-теле | | нет: тело передаётся как есть |
| `POST /v1/search` (search, `search/app.py:20-39`) | списки в JSON-теле `SearchBody` | шлюз этот сервис не проксирует | нет |

Сам шлюз читает параметры только в одном месте: `request.query_params.get("generation")` (`gateway/app.py:123`), это одно значение, его исправление не затрагивает.

### Решение

Шлюз должен передавать строку запроса **как есть, не разбирая и не собирая заново**. Тогда повторы, порядок и кодировка сохраняются для всех сервисов одинаково, и в шлюзе не нужно знать, какие параметры списковые.

`src/philograph/gateway/app.py`, в `proxy`:
```python
url = httpx.URL(f"{upstreams[target].rstrip('/')}/{path}").copy_with(
    query=request.scope["query_string"]
)
...
upstream = client.build_request(request.method, url, headers=headers, content=body)
```
Аргумент `params=` убрать совсем: если его оставить, httpx смешает его со строкой запроса. Проверено на httpx 0.28.1: `copy_with(query=b'kind=textbook&kind=primary&q=%D0%B4')` даёт тот же адрес без изменений, пустой `query_string` даёт адрес без `?`. Допустимая замена: `params=request.query_params.multi_items()`. Повторы она тоже сохраняет, но строку перекодирует; исходная строка надёжнее.

Соглашение остаётся прежним: несколько значений передаются повторяющимся ключом (`kind=a&kind=b`, как требует FastAPI `list[str]`). `mentions?targets=a,b` остаётся исключением, оно уже работает. Клиент и библиотеку менять не нужно.

### Тесты

1. **Тесты `tests/web` идут через настоящий шлюз** (`tests/web/conftest.py:150-153`). Вместо `build_app(reading, web_root=DIST)` uvicorn должен обслуживать
   ```python
   gateway.build_app(
       {"library": "http://library", "assistant": "http://assistant"},
       DIST,
       transport=httpx.ASGITransport(app=library_build_app(reading)),
   )
   ```
   Шлюз сам раздаёт `index.html` и `/assets`, а `/api/{path}` направляет в `library` на `api/{path}`. Так же собран `tests/gateway/test_limits.py:81-90`. После этого существующие тесты требований `test_kind_filter` (учебник + первоисточник → 2, «Вид · 2») и `test_kind_filter_select_all_clear_all_and_closing` («Выбрать все» → 3) начнут проверять настоящий путь и до исправления упадут. Если для `test_assistant_panel.py` нужна своя сборка, её можно не трогать: там свой `site`.

2. **Новый тест требования «Фильтр по виду источника», сценарий «Несколько видов»**, в `tests/web/test_library_reading.py`. Один запрос с двумя значениями, проверяется только ответ:
   ```python
   @req(SL, "Фильтр по виду источника")
   def test_several_kinds_in_one_request(site):
       """Учебник и первоисточник одним запросом: в ответе оба, справочника нет."""
       response = httpx.get(
           site.url + "/api/v1/sources",
           params=[("kind", "textbook"), ("kind", "primary")],
       )
       assert response.status_code == 200
       titles = {s["title"] for s in response.json()["sources"]}
       assert titles == {"История теории познания", "Critique of Pure Reason"}
   ```
   Тест работает через шлюз из пункта 1. До исправления он получит только `{"Critique of Pure Reason"}`. Тест не зависит от того, как шлюз устроен внутри, и проверяет то, что видит читатель.

3. По желанию в `tests/e2e/test_site.py::test_library_search_filter_and_choose` (через стенд со шлюзом) после «Первоисточник» отметить ещё «Учебник» и ждать `.source` = 2.

Уверенность: **высокая**. Потеря воспроизведена и в отдельном httpx, и через настоящий `gateway.build_app`.

---

## D2. Название книги в боковой панели обрезано (заметно)

### Где и почему

- `web/src/styles.css:400-406`:
  ```css
  .sidebar__book-title {
    display: -webkit-box;
    overflow: hidden;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow-wrap: anywhere;
  }
  ```
  Ширина подписи постоянна (`--sidebar-label`, `styles.css:169`, и `.sidebar__book .sidebar__label` минус `--control-sm`, `styles.css:390-392`). Поэтому «Теория познания: демонстрационный учебник» занимает три строки и в раскрытой панели (260px), и в закреплённой (280px), а третья строка уходит под многоточие.
- `docs/design/system/components/Sidebar.md:31` разрешает это явно: «название шрифтом интерфейса до двух строк (без многоточия по ширине)».
- Почему тест не поймал. `tests/e2e/visual.py:239-252` (`clipped_text`) отмечает элемент, только если `overflowX` равен hidden/clip и `scrollWidth > clientWidth`. Обрезка через line-clamp вертикальная (`scrollHeight` 54 при `clientHeight` 36), поэтому `assert_no_clipped_text` в `test_sidebar_on_every_screen` (1024, раскрыта, `test_visual_design.py:432`) и в `test_sidebar_never_covers_chapter` (1440, закреплена, `test_visual_design.py:515`) проходят.

Свёрнутая панель не затронута: `.sidebar__books` показывается только при `:not([data-state="collapsed"])` (`styles.css:372-374`). В свёрнутом виде виден только значок «Открытые книги» со счётчиком.

### Решение (по решению ведущего: полное название, сколько нужно строк)

1. **CSS**, `web/src/styles.css:400-406`: оставить в правиле только `overflow-wrap: anywhere;`, убрать `display: -webkit-box`, `overflow: hidden`, `-webkit-line-clamp: 2`, `-webkit-box-orient: vertical`. Строка вырастет сама: у `.sidebar__item` задан `min-height`, а не высота (`styles.css:284-291`). Кнопка «×» выравнивается по центру строки (`top: 50%`, `styles.css:416-422`) и останется на месте. Если список не поместится по высоте, средняя часть панели прокручивается (`.sidebar__scroll`), это уже описано в Sidebar.md.
2. **Sidebar.md:31**: заменить «до двух строк (без многоточия по ширине)» на «название целиком шрифтом интерфейса; длинное переносится на нужное число строк, без многоточия и обрезки». Попутно: там же написано, что автор показан цветом `ink-3`, а в CSS `ink-2` с пояснением (`styles.css:410`). Это стоит согласовать в той же правке, но к D2 не относится.
3. **Тест**, `tests/e2e/visual.py:239-252`. В `clipped_text` добавить вертикальную обрезку, чтобы проверка соответствовала сценарию «подписи не обрезаны»:
   ```js
   const clipsX = ['hidden','clip'].includes(st.overflowX) || st.textOverflow === 'ellipsis';
   const clipsY = ['hidden','clip'].includes(st.overflowY)
       || (st.webkitLineClamp && st.webkitLineClamp !== 'none');
   ...
   return hasText && ((clipsX && el.scrollWidth > el.clientWidth + 1)
                   || (clipsY && el.scrollHeight > el.clientHeight + 1));
   ```
   Новые тесты не нужны: уже существующие вызовы в `test_sidebar_on_every_screen` (1024, раскрыта) и `test_sidebar_never_covers_chapter` (1024, 1280, 1440, 1920, закреплена) упадут на текущем CSS с `sidebar__book-title: Теория познания: демонстрационный учебник` и пройдут после исправления. Название в демо-стенде то же, что в отчёте (`TEXTBOOK`, `test_visual_design.py:25`). Риск: вертикальная проверка применяется ко всей странице и может найти другие элементы с `overflow-y: hidden`, у которых текст выходит на 1–2px из-за межстрочного интервала. Если такие найдутся, допуск поднять до `+ 2` или ограничить вертикальную проверку элементами внутри `.sidebar`, не ослабляя её для подписей книг.

Эталоны снимков менять не нужно: в `baselines/win32` панель на всех снимках свёрнута, список книг скрыт.

Уверенность: **высокая** для причины и CSS. **Средняя** для того, что расширенная `clipped_text` не даст ложных срабатываний на других экранах: это нужно проверить прогоном.

---

## Порядок исправлений

1. D1, тесты: перевести `tests/web/conftest.py` на шлюз и добавить `test_several_kinds_in_one_request`. Убедиться, что падают `test_kind_filter`, `test_kind_filter_select_all_clear_all_and_closing` и новый тест.
2. D1, код: `gateway/app.py` `proxy`, передавать исходную строку запроса, убрать `params=`. Тесты из шага 1 становятся зелёными.
3. D2, тест: вертикальная проверка в `tests/e2e/visual.py::clipped_text`. Убедиться, что падает на подписи книги.
4. D2, CSS и Sidebar.md. Тест становится зелёным.
5. Повторный раунд у тестировщика: «Выбрать все», учебник + первоисточник, язык ×2 на стенде `dev_stack.py`.

## Команды проверки

```sh
.venv/Scripts/python -m pytest tests/gateway tests/web/test_library_reading.py -q
.venv/Scripts/python -m pytest tests/web -q
.venv/Scripts/python -m pytest tests/e2e/test_site.py -q
.venv/Scripts/python -m pytest tests/e2e/test_visual_design.py -q -k "sidebar"
.venv/Scripts/python scripts/visual_check.py
```
Ручная проверка D1 на стенде: `GET /api/v1/sources?kind=textbook&kind=primary` должен вернуть 2 источника, а запрос с тремя видами должен вернуть все.
