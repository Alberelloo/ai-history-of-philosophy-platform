# Раунд 1: причины расхождений и решения (redesign-foundations)

Вход: [round-1.md](round-1.md), снимки `qa/round-1/`. Ветка `claude/design-system`, коммит `ade189e`. Пути ниже даны от корня репозитория.

## Сводка

| № | Причина | Решение | Объём |
| --- | --- | --- | --- |
| D1 | Карточка показывает русские подписи сервера: заголовки разделов (`cards.py:36–66, 166`), названия связей из реестра (`cards.py:102–104`), «распространённое мнение» (`graph.py:71–72`). Клиент выводит их как есть (`CardPopup.tsx:181, 186, 203, 263`). | Сервер отдаёт коды (`section.code`, `row.type` + новый `row.inverse`, `attributions[].kind`). Клиент переводит их по каталогу `onto` (новые `ontology.{ru,en}.json`). Подпись сервера остаётся запасным вариантом. | большой |
| D2 | Названия рецептов и связей графа берутся из `spec["title"]` (`registry_data.py:478–511`, `graph.py:84, 142, 215`). Клиент выводит `r.title` и `e.title` (`GraphPage.tsx:225, 232, 263, 319, 358, 453`), а подсказку ассистента `suggestion.title` (`assist.py:218` → `AssistantPanel.tsx:287`). | Тот же каталог `onto`: рецепт ищется по `code`, связь по `type`. Подсказку ассистента клиент собирает из `recipe` и `label`. | средний |
| D3 | `repeat(auto-fill, …)` (`web/src/styles.css:400`): при ширине 1136px создаётся три дорожки, а карточек две, и третья дорожка остаётся пустой. | `auto-fill` → `auto-fit`. Добавить DOM-проверку «первый ряд доходит до правого края сетки». | малый |
| D4 | Уведомление сделано плавающей панелью: `<aside role="dialog">` в конце `App` (`App.tsx:61`, `Notice.tsx:77–92`), `position: fixed` (`styles.css:1142–1160`). Так было решено ещё в `add-onboarding-and-settings/design.md` §5. | Сделать сообщение `pg-notice` в потоке страницы под верхней панелью, без `fixed`, тени и анимации. Действие оформить `pg-btn--ghost pg-btn--sm` справа. | средний |
| D5 | В настройках подписи взяты из `t.lang.ruName / enName` (`SettingsPage.tsx:48–49`). | Взять `t.lang.ru / en`, а ключи `ruName` и `enName` удалить. | малый |
| D6 | Подпись годов собирается с пробелами: `f"{birth} – {death}"` (`src/philograph/knowledge/dates.py:102`). Результат хранится в `original` и в базе. | `f"{birth}–{death}"`, а для уже сохранённых данных добавить миграцию 5 в `knowledge/schema.py`. | малый |
| З1 | `docs/design/system/components.css:1` содержит `@import` Google Fonts. | Удалить строку и добавить `docs/design/system/*.css` в тест «шрифты без сторонних сервисов». | малый |
| З2 | Описание в карточке пишет заглушка модели. Её постоянный ответ `fake_reply` с подсказкой для разработчика (`config/llm.demo.yaml:9`) попадает в карточку читателя. | В `fake_replies` добавить свой ответ для шаблона `card.description`. Он похож на описание и не упоминает конфиг. Язык описания не менять: это контент. | малый |
| D7 | Вне раунда, решение ведущего | Медальоны в узлах графа делаются в изменении «граф по оси времени» | — |
| D8 | Вне раунда, решение ведущего | Поиск в верхней панели войдёт в отдельный экран поиска | — |

---

## D1. Карточка: русские подписи сервера в английском интерфейсе

### Как сейчас устроен язык

- Язык хранится только в браузере: `philograph:v2.lang` (`web/src/storage.ts:27, 203`). По умолчанию берётся язык браузера (`web/src/i18n/index.ts:9–16`, скрипт в `web/index.html:19–21`). Атрибут `lang` страницы ставит `web/src/theme.ts:24`.
- Язык не уходит на сервер ни в одном запросе. Ни один вызов `fetch` не передаёт ни параметр языка, ни заголовок: `web/src/api.ts:70`, `CardPopup.tsx:82, 91`, `GraphPage.tsx:128`, `AssistantPanel.tsx:132`, `ReaderPage.tsx:205`. Браузер сам шлёт `Accept-Language`, но в нём язык браузера, а не выбор читателя.
- Параметра языка нет и в API. Шлюз пробрасывает заголовки (`src/philograph/gateway/app.py:157`), но ни один сервис их не читает. Имя `?lang=` в `/api/v1/sources` уже занято: это фильтр по языку источника (`src/philograph/library/app.py:34–36`, `web/src/api.ts:118`). Имена сущностей сервер всегда берёт по-русски (`Entities.label(lang="ru")`, `src/philograph/knowledge/entities.py:134`).
- Клиент уже переводит по коду типы сущностей (`t.family`), ошибки (`t.errors`), пояснения о достройке графа (`t.graph.notices`) и позиции (`t.graph.stance`). Названия онтологии выпали из этой схемы сознательно: так написано в комментарии `web/src/i18n/ru.ts:2–3` («данные онтологии … приходят с сервера и не переводятся»). Этот комментарий противоречит документам дизайна.

### Точная причина

| Строка на снимке | Откуда | Где выводится |
| --- | --- | --- |
| «Годы и места жизни», «Влияния» | `src/philograph/knowledge/cards.py:48, 51` (кортежи `SECTIONS`, заголовки зашиты в код, а не в реестр) | `web/src/CardPopup.tsx:181` `{section.title}` |
| «Часто считают, но…» | `cards.py:166` | там же |
| «испытал влияние», «повлиял на», «годы жизни» | `src/philograph/knowledge/registry_data.py:107–108, 448`, в ответ попадают через `cards.py:102–104` (`title` или `inverse_title` в зависимости от направления) | `CardPopup.tsx:186` `{row.relation}` |
| «распространённое мнение» | `src/philograph/knowledge/graph.py:71–72` (`attribution_label`), в ответ попадает через `cards.py:95` | `CardPopup.tsx:203` `row.attributed_to.join` |
| «Генезис», «Последствия», «Полемика», «Контекст» (кнопки в карточке) | `registry_data.py:482, 492, 498, 499` → `graph.py:84` | `CardPopup.tsx:263` `{r.title}` |

Реестр хранится в базе: `load_defaults` переносит туда `registry_data.py` (`registry.py:45–87`). Новые типы добавляются во время работы через `add_relation`, `add_entity_type` и предложения модели (`registry.py:204–260`). У типа одна подпись, `title` по-русски. Эту же подпись видят модель (`graph.py:264, 279`, `assist.py:103`) и оператор (`review.py:187`).

### Что требуют документы

- `openspec/changes/redesign-foundations/specs/visual-design/spec.md`, «Язык интерфейса»: «Все строки интерфейса SHALL браться из каталога с одинаковыми ключами для обоих языков»; сценарий «Английский»: «навигация, кнопки и подписи на английском … тексты источников не переводятся».
- `docs/design/system/content.md`, «Правила для разработки»: «Сервер отвечает кодами (`kind`, `reason`), а клиент показывает текст на языке интерфейса. Текст сервера — только запасной вариант».
- `openspec/changes/redesign-foundations/design.md`, §5: «Сервер отвечает кодами …, клиент показывает текст из каталога, текст сервера — запасной вариант».

### Выбор архитектуры

**Решение: сервер отдаёт коды, клиент переводит по каталогу (вариант А). Язык на сервер не передаётся.**

Почему не вариант Б (сервер принимает `Accept-Language` или `?lang=` и сам отдаёт подписи):

1. Вариант Б нарушает правило, записанное в трёх документах (spec, `content.md`, `design.md` §5): часть строк интерфейса жила бы на сервере, вне каталога. Тогда проверка полноты каталога через `tsc` эти строки не покрывает.
2. Варианту Б нужна миграция реестра: подписи на двух языках для `entity_types.title` (колонка `String`), `relation_types.spec`, `recipes.spec`, а также для заголовков разделов в `cards.py`. Уже созданные базы получат английские подписи только через миграцию, потому что `load_defaults` срабатывает лишь на пустой базе (`registry.py:50`).
3. Варианту Б нужен язык в каждом запросе к трём сервисам, включая потоковые (`/graph/build`, `/assistant/v1/ask`). При смене языка пришлось бы заново запрашивать открытую карточку и граф. Ответы, которые сейчас не зависят от языка, начали бы от него зависеть (кэш, `Vary`). Имя `?lang=` к тому же уже занято фильтром библиотеки.
4. Контент (имена сущностей, описания, тексты источников) по решению ведущего не переводится. Значит, серверу язык читателя сейчас не нужен вообще.

Цена варианта А и как её снизить:

- Тип, добавленный в реестр во время работы, не найдётся в каталоге. Клиент покажет подпись сервера, то есть русскую: это и есть запасной вариант. Все типы, рецепты и разделы начального реестра покрывает тест (см. ниже). Если понадобится переводить и новые типы, реестр позже получит `title_en`, а клиент возьмёт его следующим звеном запасной цепочки. API от этого не меняется.
- Русские подписи хранятся в двух местах: в реестре (для модели, оператора и журналов) и в каталоге. Расхождение ловит тест: русский каталог онтологии должен совпадать с реестром.

### Что изменить

Сервер (добавить поля, старые не убирать: на них опираются тесты и контекст модели):

1. `src/philograph/knowledge/cards.py`, метод `_row` (стр. 99–126): добавить `"inverse": not outward and not spec.get("symmetric")` и `"attributions": [{"who": attribution_label(...), "kind": a["who_kind"], "stance": a["stance"]} for a in visible]`. Поля `relation`, `attributed_to` и `disputed_by` оставить.
2. `cards.py:166`: вынести «Часто считают, но…» в константу `MISCONCEPTIONS_TITLE` рядом с `SECTIONS`, чтобы её видел тест.
3. `src/philograph/knowledge/graph.py:150–155` (`_edge`, `attributions`): добавить `"kind": a["who_kind"]`.

Клиент:

4. Новые файлы `web/src/i18n/ontology.ru.json` и `web/src/i18n/ontology.en.json`:
   ```json
   {
     "sections": { "life": "Годы и места жизни", "influence": "Влияния", "misconceptions": "Часто считают, но…" },
     "relations": { "influenced_by": { "title": "испытал влияние", "inverse": "повлиял на" }, "lifespan": { "title": "годы жизни" } },
     "recipes": { "genesis": "Генезис" }
   }
   ```
   Русский файл повторяет реестр слово в слово: все 49 связей из `registry_data.RELATIONS`, все 7 рецептов из `RECIPES`, все 18 кодов разделов из `cards.SECTIONS` и `misconceptions`. Английский файл содержит те же ключи. В `web/tsconfig.json` включить `"resolveJsonModule": true`.
5. `web/src/i18n/ru.ts`: `import ontology from "./ontology.ru.json"`, ключ `onto: ontology`. `en.ts`: `onto: ontologyEn`. Тип `typeof ru` заставит `tsc` проверять, что в английском файле есть все ключи русского. Добавить `card.commonOpinion` («распространённое мнение» / «common opinion») и `assistant.openGraph(recipe, entity)` (см. D2). Переписать комментарий `ru.ts:2–3`: названия онтологии теперь переводятся по коду, а не переводятся только тексты источников, имена сущностей и описания.
6. `web/src/i18n/index.ts`: помощники
   - `sectionTitle(t, code, fallback)`;
   - `relationTitle(t, code, inverse, fallback)`: при `inverse` берётся `inverse ?? title`, если кода нет, то `fallback`;
   - `recipeTitle(t, code, fallback)`;
   - `whoLabel(t, a)`: для `kind === "common"` возвращает `t.card.commonOpinion`, иначе `a.who`.
7. `web/src/CardPopup.tsx`: стр. 181 `sectionTitle(t, section.code, section.title)`; стр. 186 `relationTitle(t, row.type, row.inverse, row.relation)`; стр. 199 и 203 собирать списки из `row.attributions` (спорящие: `stance === "disputes"`) через `whoLabel`; стр. 263 `recipeTitle(t, r.code, r.title)`. В тип `Row` добавить `type`, `inverse` и `attributions`.

Английские подписи разделов (сверены с тоном `content.md`):

| код | RU | EN |
| --- | --- | --- |
| definitions / words / conceptions / related / problems | Определения / Происхождение слова / История: концепции / Связанные понятия / Проблемы | Definitions / Origin of the word / History: conceptions / Related concepts / Problems |
| life / biography / teachers / influence | Годы и места жизни / Биография / Учителя и ученики / Влияния | Life and places / Biography / Teachers and students / Influences |
| works / schools / positions / epoch | Произведения / Школы и направления / Позиции и учения / Контекст эпохи | Works / Schools and movements / Positions and doctrines / Historical context |
| when / effects / parts / answers / arguments | Дата и место / На что повлияло / Состав / Ответы и сторонники / Аргументы за и против | Date and place / What it influenced / Parts / Answers and proponents / Arguments for and against |
| misconceptions | Часто считают, но… | Commonly believed, but… |

Связи переводятся в нижнем регистре, как в RU. Примеры: `influenced_by` → «influenced by» / «influenced»; `studied_with` → «studied with» / «taught»; `borrows` → «borrows from» / «was a source for»; `develops` → «develops» / «developed in»; `lifespan` → «lifespan». Полный список кодов и русских подписей — `registry_data.py:104–476`.

### Тесты

- **Новый, требование «Язык интерфейса»** (`tests/web/test_design_system.py`, `@req(VD, "Язык интерфейса")`): `test_ontology_names_in_both_catalogs`. Загрузить оба JSON и проверить четыре условия:
  - ключи `relations`, `recipes`, `sections` совпадают с кодами `registry_data.RELATIONS`, `registry_data.RECIPES`, `cards.SECTIONS` и `misconceptions`;
  - русские подписи равны подписям реестра (`title`, `inverse_title`) и `cards.SECTIONS`;
  - в английском файле те же ключи, строки не пустые и без кириллицы;
  - `inverse` есть в английском файле там же, где он есть у связи в реестре.
- **Новый, сквозной** (`tests/e2e/test_visual_design.py`, `@req(VD, "Язык интерфейса")`): `test_english_card_and_graph`. Переключить язык на EN, открыть карточку «Юм». В подписях интерфейса (`.card-section h4`, `.card-row__relation`, `.card-recipe`) не должно быть кириллицы, а среди атрибуций должно быть «common opinion». Перейти по кнопке «Genesis»: `h1` начинается с «Genesis:», у `#graph-recipe option` нет кириллицы. Нажать на связь: в `.graph-who` стоит «according to». Имена сущностей и описание не проверять, это контент.
- **Существующие**: в RU подписи не меняются, поэтому `tests/e2e/test_site.py` («Генезис: Кант», «Кант — испытал влияние — Юм») и `tests/knowledge/*` проходят без правок. `test_catalog_keys_checked_by_typescript` (`tests/web/test_design_system.py:98`): копия каталога во временной папке должна включать JSON, а во временный `tsconfig.json` (стр. 107–111) нужно добавить `"resolveJsonModule": true`.

### Уверенность

Причина найдена с высокой уверенностью, решение — со средней.

Риски:

- **Пропущенное место вывода.** Если где-то не заменить `title` на перевод по коду, в интерфейсе останется русский текст. Сквозной тест ловит это только на карточке Юма и графе Канта.
- **Ошибка направления.** Неверный `inverse` перепутает «испытал влияние» и «повлиял на». Сверка: в RU у Юма должно быть «испытал влияние: Локк» и «повлиял на: Кант», как на `card-light-ru-1440.png`.
- **Страница оператора.** `ReviewPage.tsx:202` тоже выводит `open.relation`. Это внутренняя страница оператора, в этот раунд её можно не трогать. Если менять, то тем же `relationTitle` (сервер должен отдавать `type`, см. `review.py:187`).

---

## D2. Граф: рецепты и заголовок по-русски

### Точная причина

- Рецепты: `registry_data.py:478–511` (`"genesis", "Генезис"` на стр. 481–482) → `registry.py:70–85` → `graph.py:84` (`recipes_for`) и `graph.py:215` (`recipe.title`).
- Клиент:
  - `web/src/GraphPage.tsx:232` (`recipeTitle` из `state.recipes[].title`) → заголовок стр. 247 «Генезис: Кант»;
  - `<option>` стр. 261–263, в том числе запасное `{ title: recipe }`, где показывается сам код;
  - подсказки при ошибке, стр. 319;
  - «Попробовать: …», стр. 358.
- Связи: `graph.py:142` (`spec["title"]`) → `GraphPage.tsx:225` (`aria-label` и `<title>` связи), стр. 453 (заголовок панели связи).
- «Так считает: распространённое мнение» в панели связи: `GraphPage.tsx:482` выводит `a.who` из `graph.py:151`.
- Та же болезнь в ассистенте. Сервер собирает готовую строку «Открыть граф: генезис — Кант» (`src/philograph/knowledge/assist.py:218`), ассистент отправляет её событием `suggestion` (`src/philograph/assistant/service.py:496`), клиент выводит её как есть (`AssistantPanel.tsx:287`).

### Что требуют документы

- `docs/design/system/content.md`, таблица «Термины»: «Граф происхождения | Генезис | Genesis».
- Требование `spec.md` «Язык интерфейса» и правило «Сервер отвечает кодами» (цитаты в D1).

### Что изменить

На каталоге `onto` из D1:

1. `GraphPage.tsx:232`: `recipeTitle(t, recipe, state?.recipes.find(...)?.title) ?? t.graph.title`.
2. `GraphPage.tsx:263, 319, 358`: `recipeTitle(t, r.code, r.title)`.
3. `GraphPage.tsx:225, 453`: `relationTitle(t, e.type, false, e.title)`. У ребра графа направление всегда «субъект → объект», поэтому `inverse = false`.
4. `GraphPage.tsx:482`: `t.card.believes(whoLabel(t, a))`. В тип `GEdge.attributions` (стр. 25) добавить `kind`.
5. `src/philograph/knowledge/assist.py:215–219`: в `graph` добавить `"label": entity["label"]`. Поле `title` оставить как запасное. В `AssistantPanel.tsx:287`: `t.assistant.openGraph(recipeTitle(t, s.recipe, ...), s.label)` с запасным `s.title`. Русская строка не должна измениться: `` (recipe, entity) => `Открыть граф: ${recipe.toLowerCase()} — ${entity}` ``. Английская: `` `Open graph: ${recipe.toLowerCase()} — ${entity}` ``.

Английские рецепты: genesis «Genesis», consequences «Consequences», polemic «Polemic», context «Context», answers «Answers to the problem», conceptions «Comparing conceptions», path «Path between two».

### Тесты

Сквозной `test_english_card_and_graph` из D1 проверяет и граф. Тест каталога из D1 проверяет и рецепты. Русские сквозные тесты (`tests/e2e/test_site.py:261–362`) не меняются.

### Уверенность

Высокая. Риск: в `<select>` до загрузки графа показывается запасной вариант. Сейчас это код рецепта (`genesis`), после правки будет перевод по коду. Проверить, что в EN до ответа сервера не мелькает русское слово.

---

## D3. Библиотека: сетка не заполняет ширину

### Точная причина

`web/src/styles.css:400`: `grid-template-columns: repeat(auto-fill, minmax(320px, 1fr))`. Ширина области — `.page` с `max-width: 1200px` минус отступы `2 × space-8` (`styles.css:245–249`), то есть 1136px при ширине окна от 1200px. `auto-fill` создаёт ⌊(1136 + 16) / (320 + 16)⌋ = 3 дорожки по 368px, хотя карточек всего две. Третья дорожка остаётся пустой: это и есть пустые ~390px справа. При ширине 1024 области 960px хватает на две дорожки, и сетка заполнена.

Дефект есть и при 1280: область та же, 1136px. Значит, утверждённые эталоны `library-*-1280.png` сняты с дефектом.

### Что требует документ

`docs/design/system/layout.md`, «Библиотека»: «Сетка источников заполняет ширину: колонки `minmax(320px, 1fr)`, карточки одной высоты в ряду, без одиночной карточки на последней строке там, где это можно избежать выбором числа колонок».

### Что изменить

`styles.css:400`: `repeat(auto-fit, minmax(320px, 1fr))`. `auto-fit` схлопывает пустые дорожки, и две карточки делят ширину поровну. Карточки одной высоты в ряду уже обеспечивает `display: grid` (по умолчанию `align-items: stretch`).

### Тесты

- В `tests/e2e/visual.py` добавить `assert_fills_width(page, selector)`: правый край последнего элемента первого ряда совпадает с правым краем сетки с точностью ±1px.
- Вызвать её в `test_layout_at_supported_widths` (`tests/e2e/test_visual_design.py:175`) после `library(...)` для всех ширин `visual.WIDTHS`. Требование «Раскладка без наложений»; если спецификацию дополнять, то там же.
- Пересоздать эталоны `library-light-1280.png` и `library-dark-1280.png`.

### Уверенность

Высокая.

Риски:

- **Один источник.** Если после фильтра остался один источник, карточка растянется на все 1136px. Это не противоречит `layout.md`, но выглядит широко. Проверить снимком с фильтром.
- **Одиночная карточка.** Правило «без одиночной карточки на последней строке» не выполнено: при четырёх источниках и трёх колонках последний ряд будет 3 + 1. В демо два источника, поэтому тестировщик этого не видел. Правило нужно записать в «Известное» или сделать отдельно: выбирать число колонок скриптом или задать `max-width` сетки.

---

## D4. Уведомление при первом входе перекрывает контент

### Точная причина

- `web/src/App.tsx:61`: `<FirstRunNotice />` стоит после `<Page>`, вне потока страницы.
- `web/src/Notice.tsx:77–92`: `<aside role="dialog">`, основное действие сделано кнопкой `pg-btn--primary`.
- `web/src/styles.css:1142–1160`: `.first-run { position: fixed; left; bottom; z-index: var(--z-popover); box-shadow: var(--shadow-pop); animation: pg-pop-in … }`. Панель висит над контентом в левом нижнем углу и закрывает первую карточку источника.
- Такое решение принято ещё до дизайн-системы: `openspec/changes/add-onboarding-and-settings/design.md` §5 («Уведомление — панель в левом нижнем углу»). Документ дизайна `Notice.md` его отменяет, но решение не пересмотрели.

### Что требуют документы

- `docs/design/system/components/Notice.md`: «Сообщение в потоке страницы: что произошло и что можно сделать. Не всплывает и не исчезает само.» и «Действие одно, справа, кнопкой `pg-btn--ghost pg-btn--sm`».
- `openspec/changes/add-onboarding-and-settings/specs/first-run-notice/spec.md` сохраняет силу: уведомление показывается при первом входе, в нём есть переключатели, оно показывается один раз, ассистент ждёт его закрытия. Про всплывающую панель требования нет, это только решение в `design.md`.

### Что изменить

1. `App.tsx`: перенести `<FirstRunNotice />` сразу под `storage-warning`, перед `<Page>`. Тогда уведомление стоит в потоке на любом экране первого входа: в библиотеке, в главе, на графе.
2. `Notice.tsx:77–92`: разметка `<section className="pg-notice first-run" aria-label={t.notice.label} tabIndex={-1}>`:
   - слева значок `<Icon name="info" />`;
   - в середине `<div>`: заголовок, `NoticeText`, `GenerationSettings`;
   - справа кнопка `pg-btn pg-btn--ghost pg-btn--sm` «Понятно».

   `role="dialog"` убрать: это не диалог. У `section` с `aria-label` роль `region`.
3. `Notice.tsx:66–69` (`show`): после `focus()` вызвать `box.current?.scrollIntoView({ block: "nearest" })`, чтобы подсвеченное уведомление было видно, когда ассистента открывают из глубины главы.
4. `styles.css:1142–1178`:
   - убрать `position`, `left`, `bottom`, `z-index`, `width`, `max-height`, `overflow`, `box-shadow`, `animation` и фон `surface`. Фон и сетку даёт `pg-notice` (`accent-soft`, `components.css:357–361`);
   - оставить ширину содержимого: `max-width: 1200px; margin: var(--space-4) auto 0;` и внутренние отступы, как у `.page`;
   - `.first-run.attention` оставить: рамка `accent` и кольцо `accent-soft`, без `shadow-pop`.
5. `styles.css:1315–1320`: убрать `.first-run` из списка анимаций в блоке `prefers-reduced-motion`.
6. В `openspec/changes/redesign-foundations/design.md` добавить решение: «Уведомление при первом входе — сообщение `Notice` в потоке под верхней панелью. Заменяет §5 `add-onboarding-and-settings/design.md`».

### Тесты

- **Новый** (`test_visual_design.py`, `@req(VD, "Раскладка без наложений")`): `test_first_run_notice_in_flow` на 1024 и 1280. Открыть библиотеку и главу без принятого уведомления, затем `visual.assert_no_overlap(page, [".topbar", ".first-run", "main"])`. Прокрутить страницу на 400px и проверить, что уведомление ушло вместе с контентом (`getBoundingClientRect().top < 0`).
- **Поправить роль**: `get_by_role("dialog", name=NOTICE)` → `get_by_role("region", name=NOTICE)`:
  - `tests/e2e/test_settings.py:54, 103, 163, 176, 194, 206`;
  - `tests/e2e/test_visual_design.py:417`.

  Проверка подсветки `.first-run.attention` (`test_settings.py:98`) остаётся.
- Пересоздать эталон `notice-light-1280.png`. Добавить снимок `notice-dark-1024` (тестировщик снимал и тёмную тему).

### Уверенность

Средняя.

Риски:

- **Сдвиг главы.** В главе уведомление в потоке сдвигает текст вниз, а после «Понятно» текст прыгает вверх на высоту уведомления. Если читатель уже прокрутил страницу, его место сместится. Смягчить: при закрытии, если `window.scrollY > 0`, вызвать `window.scrollBy(0, -height)`.
- **Панель ассистента.** Она закреплена справа и при открытии закроет правую часть уведомления. Это то же известное наложение панели на текст («Известное», п. 2), в этом раунде не исправляется.
- **Прокрутка к уведомлению.** Прокрутка по `requestNotice` уводит читателя к началу страницы. Это осознанно: вопрос не уйдёт, пока уведомление не закрыто.

---

## D5. Настройки: подписи языка «Русский / English»

### Точная причина

`web/src/SettingsPage.tsx:48–49`: `label: t.lang.ruName` / `t.lang.enName` («Русский» / «English», `ru.ts:37–38`, `en.ts:27–28`). В верхней панели правильно стоят `t.lang.ru` / `t.lang.en` (`TopBar.tsx:89–90`).

### Что требует документ

`docs/design/system/components/SegmentedControl.md`, таблица: «Язык | RU / EN | RU / EN». `spec.md`, «Язык интерфейса»: «переключатель RU / EN SHALL быть в верхней панели и в настройках».

### Что изменить

`SettingsPage.tsx:48–49` → `t.lang.ru`, `t.lang.en`. Удалить `ruName` и `enName` из `ru.ts` и `en.ts`, больше нигде они не используются.

### Тесты

- `tests/e2e/test_visual_design.py:316`: `get_by_role("button", name="English")` → `get_by_role("button", name="EN", exact=True)` в пределах `get_by_role("main")`.
- Пересоздать эталоны `settings-light-1280.png`, `settings-dark-1280.png`, `settings-en-light-1280.png`.

### Уверенность

Высокая. Риск: на экране настроек будут две группы с одинаковым `aria-label` «Язык интерфейса»: в панели и в `main`. Тесты уже ищут в пределах `main`.

---

## D6. Годы жизни: пробелы вокруг тире

### Точная причина

`src/philograph/knowledge/dates.py:102`: `f"{birth} – {death}"`. Строка попадает в `FuzzyDate.original` и хранится в базе дважды: в значении утверждения `lifespan` (`statements.value`) и в копии `entities.primary.dates`. Сервер отдаёт её как есть: `cards.py:176` → `CardPopup.tsx:161`, строка `value.original` → `CardPopup.tsx:49`, `graph.py:131` → `GraphPage.tsx:417`. Те же годы через `lifespan` получает импорт из Wikidata (`filling.py:504`). Демо-данные создаёт `scripts/seed_demo.py:111–122`.

### Что требует документ

`docs/design/system/content.md`, «Числа и даты»: «Годы жизни через короткое тире без пробелов: 1724–1804».

### Что изменить

1. `dates.py:102` → `f"{birth}–{death}"`.
2. Миграция 5 в `src/philograph/knowledge/schema.py` (по образцу `migrations.add`, стр. 181–277): «даты: короткое тире без пробелов». Она заменяет `" – "` на `"–"` в `entities.primary["dates"]["original"]` и в `statements.value["original"]` у утверждений типа `lifespan`. Без миграции рабочая база и стенд `.stack` останутся со старой записью: `seed_demo.py:103` не пересеивает существующие данные.
3. Перед пересъёмкой стенд руками нужно поднимать с чистой папкой: удалить `.stack`. Это же нужно для З2.

### Тесты

- `tests/knowledge/test_registry_entities.py`: `lifespan("1724", "1804").original == "1724–1804"`. Отдельный тест миграции: утверждение со старой записью после `upgrade` читается как «1724–1804».
- Сквозной (`tests/e2e/test_site.py:173`): заменить `"1711" in ...` на `card.locator(".card-dates").inner_text() == "1711–1776"`. В графе (`test_site.py`, после `h1:text('Генезис: Кант')`) проверить `.graph-dates` с текстом «1724–1804».
- Эталоны пересоздаются вместе с D1/D2: `card-*`, `graph-*`.

### Уверенность

Причина найдена с высокой уверенностью, решение — со средней из-за миграции данных.

Риски:

- **Чужие записи.** Миграция не должна трогать `original` у дат, записанных вручную или из источника. Менять только тип `lifespan` и только точное `" – "`.
- **Даты до нашей эры.** Формат «ок. 428–348 до н. э.» / «c. 428–348 BCE» из `content.md` не выполнен: сейчас получится «ок. 428 до н. э.–348 до н. э.», и на английском подпись не переводится. В демо таких дат нет. Записать в «Известное»: форматирование дат из структурных полей на клиенте — вместе с графом по оси времени.

---

## З1. `@import` Google Fonts в `docs/design/system/components.css`

### Точная причина

`docs/design/system/components.css:1`: `@import url("https://fonts.googleapis.com/css2?family=Literata…&family=Onest…")`. Клиентская копия `web/src/styles/components.css` собрана вручную, импорт в ней вырезан (комментарий на стр. 1–3). Ни тест, ни скрипт не сверяют копию с источником, поэтому при следующем копировании импорт может вернуться в клиент. Тест `test_fonts_bundled_without_external_services` (`tests/web/test_design_system.py:89–95`) смотрит только `web/src` и `web/index.html`.

### Что требуют документы

`spec.md`, «Шрифты»: «запросов к сторонним сервисам шрифтов MUST NOT быть». `docs/design/design-system.md`, «Шрифты»: «В продукте шрифты подключаются локально из @fontsource, без запросов к Google Fonts».

### Что изменить

1. Удалить стр. 1 из `docs/design/system/components.css`.
2. Поправить комментарий в `web/src/styles/components.css:1–3`: копия отличается от источника только раскладкой превью (`.pg-demo*`). В `design.md` §3 убрать «без подключения Google Fonts».

### Тесты

В `test_fonts_bundled_without_external_services` добавить `docs/design/system/*.css` в список проверяемых файлов.

### Уверенность

Высокая. Риск: превью дизайн-системы в артефакте claude.ai могли брать шрифты через этот импорт. Тогда без него превью покажут запасной шрифт. Превью в `docs/design/system/previews/*.html` сами `components.css` не подключают. Если артефакт перестанет показывать Literata и Onest, подключить шрифты в самом артефакте, а не в `components.css`.

---

## З2. Русский служебный текст в карточке в английском интерфейсе

### Точная причина

На демо-стенде описание карточки пишет заглушка модели. `config/llm.demo.yaml:9`: у поставщика `demo-answer` один постоянный ответ `fake_reply` на все шаблоны, включая `card.description` (вызов в `cards.py:231–241`). Ответ «Это демонстрационный ответ… Настоящая модель подключается в config/llm.yaml» сохраняется как описание (`cards.py:262–268`) и показывается читателю. Это подсказка для разработчика, а не описание сущности.

Сам язык описания не дефект. Рабочая модель пишет описание по русскому заданию (`src/philograph/prompts/__init__.py:31–36`). Описание сохраняется один раз для всех читателей: это контент, а контент по решению ведущего не переводится (см. также `content.md`: «Тексты источников не переводятся»).

### Что изменить

1. `config/llm.demo.yaml`, `demo-answer.fake_replies`: добавить `card.description` с текстом, похожим на описание, без упоминания конфигурации и заглушки. Например: «Философ, чьи идеи обсуждаются в главах учебника. Описание написано моделью и помечено как сгенерированное.» Ответ ассистента (`fake_reply`) не трогать: он показывается в окне ассистента как демо-ответ.
2. Стенд поднимать с чистой папкой `.stack`, иначе останется старое сохранённое описание.

### Тесты

`tests/e2e/test_site.py:178`: `"демонстрационный" in …` проверяет текст заглушки. Заменить на проверку требования: описание не пустое, помечено как сгенерированное (стр. 177 уже это проверяет) и не содержит `config/`.

### Уверенность

Средняя: решение опирается на толкование. Текст ведущего «серверный текст по-русски» понят так: служебная строка заглушки в интерфейсе читателя. Если ведущий хотел и английское описание в EN, нужно описание на каждом языке. Это меняет модель данных (по описанию на язык) и противоречит решению «контент не переводится». В этот раунд не включено.

---

## Вне раунда (решения ведущего)

- **D7. Узлы графа — медальоны.** Делается в изменении «граф по оси времени», следующий шаг. В этом раунде не исправляется.
- **D8. Поиск в верхней панели.** Требования поиска в спецификации основы нет, экран поиска будет отдельно. Сюда же относится путь до главы в панели. В этом раунде не исправляется.

Оба пункта, а также из D3 «одиночную карточку в последнем ряду» и из D6 «даты до н. э. и их перевод», занести в `progress.md`, раздел «Известные проблемы». Тогда тестировщик следующего раунда не запишет их снова.

Попутно замечено, не входит в раунд:

- уточнители связи выводятся сырыми кодами `polarity: criticism` (`GraphPage.tsx:471–475`);
- в EN цитата берётся в «ёлочки» (`GraphPage.tsx:490`).

## Порядок исправлений

1. D5, D3, З1: малые правки без зависимостей.
2. D6: `dates.py`, миграция 5, тест даты.
3. D1, сервер: поля `inverse` и `attributions[].kind` в `cards.py` и `graph.py`, константа `MISCONCEPTIONS_TITLE`, `label` в `assist.py`.
4. D1, клиент: `ontology.{ru,en}.json`, `resolveJsonModule`, ключ `onto` в каталогах, помощники в `i18n/index.ts`, `CardPopup.tsx`.
5. D2: `GraphPage.tsx`, `AssistantPanel.tsx`.
6. Тесты D1/D2: тест каталога онтологии, сквозной EN-тест, правка временного `tsconfig` в тесте каталога.
7. З2: `fake_replies.card.description`, правка `test_site.py:178`.
8. D4: `App.tsx`, `Notice.tsx`, `styles.css`, роли в тестах, новый тест «в потоке».
9. Документы: `design.md` (§3, §5, новое решение об уведомлении), комментарий `ru.ts:2–3`, «Известные проблемы» в `progress.md`. По желанию в `spec.md`, требование «Язык интерфейса», сценарий «названия разделов, связей и рецептов на языке интерфейса; имена сущностей и описания не переводятся».
10. Эталоны. Сначала запустить проверку без `--update`. Упасть должны только эти снимки:
    - `library-light-1280`, `library-dark-1280`;
    - `settings-light-1280`, `settings-dark-1280`, `settings-en-light-1280`;
    - `card-light-1280`, `card-dark-1280`, `card-dark-1024`;
    - `graph-light-1280`, `graph-dark-1280`, `graph-dark-1024`;
    - `notice-light-1280`.

    Если упал другой снимок, это сигнал о регрессии. Посмотреть снимки в `tests/e2e/visual/results/`, потом выполнить `--update`.

## Команды проверки

```
cd web && npm run typecheck && cd ..
.venv/Scripts/python scripts/design_tokens.py --check
PYTHONUTF8=1 .venv/Scripts/python -m pytest -q tests/web/test_design_system.py tests/knowledge tests/assistant/test_ontology_retrieval.py
PYTHONUTF8=1 .venv/Scripts/python -m pytest -q tests/e2e/test_site.py tests/e2e/test_settings.py
.venv/Scripts/python scripts/visual_check.py
.venv/Scripts/python scripts/visual_check.py --update        # только после просмотра снимков
PYTHONUTF8=1 .venv/Scripts/python -m pytest -q               # всё
.venv/Scripts/python scripts/check_traceability.py
.venv/Scripts/ruff check .
```

Стенд для пересъёмки тестировщиком: удалить `.stack`, затем `cd web && npm run build`, затем `PHILOGRAPH_RATE_BURST=2000 .venv/Scripts/python scripts/dev_stack.py --port 8099`.
