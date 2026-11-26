# Design

## Контекст (факт кода)

- `knowledge/wikidata.py` (общий модуль команд оператора) уже даёт всё, что нужно для работы с записями:
  - `check_qid`, `http_fetch` (один домен, повторы по `Retry-After`), `fetch_entity → WikidataRecord`, `search(label, lang)`;
  - `claim_date(claim) → FuzzyDate` (знак эры, точность 9/8/7/6), `format_original`, `page_url`;
  - `WikidataRecord.best(prop)` (предпочтённое, иначе обычное, устаревшее — никогда), `items(prop)`.
- `geo_enrich.PlaceEnrichment` — образец команды:
  - цели — сущности с `wikidata` по шаблону;
  - кэш записей на запуск;
  - запись через `Statements.check_value` + `find` + `add`;
  - пропуск — событие с причиной;
  - `dry_run` считает то же без записи;
  - `rollback(run_id)` через `Statements.rollback_run`;
  - CLI `run|rollback`, `--from-file`.
- `epoch_dates` — образец манифеста:
  - `suggest` пишет кандидатов, человек подтверждает;
  - `apply` не перезаписывает дату (`unchanged`/`conflict`).
- `Filling.import_wikidata(qid, fetch)` принимает упрощённую запись `{labels, claims: {P569: ["+1724-…"]}}`. Дату жизни он пишет как `lifespan(claims["P569"][0][1:5], …)`, и знак эры теряется. Роли берёт из `WIKIDATA_ROLES` (в `filling.py`).

## Контракты

### `knowledge/life_dates.py` (новый)

```
python -m philograph.knowledge.life_dates suggest [--manifest sources/person_qids.yaml] [--auto-exact] [--limit N] [--from-file F]
python -m philograph.knowledge.life_dates apply   [--manifest …] [--linked] [--dry-run] [--limit N] [--from-file F]
python -m philograph.knowledge.life_dates rollback <run_id>
```

```python
PROPERTIES = {"P569": "birth", "P570": "death", "P577": "published", "P106": "occupation"}
class LifeDates:
    def __init__(self, statements: Statements, fetch: Fetch, review: ReviewQueue | None = None)
    def suggest(self, manifest, *, auto_exact=False, limit=None) -> manifest   # в базу не пишет
    def apply(self, manifest, *, linked=False, dry_run=False, limit=None) -> Report
    def rollback(self, run_id) -> dict
```

### Манифест `sources/person_qids.yaml` (новый)

```yaml
# … шапка-комментарий: схема, порядок работы (suggest → человек → apply --dry-run → apply)
entities:
- entity: e_1a2b3c…         # id сущности (постоянный)
  label: Платон             # подпись на момент suggest, для человека
  type: person
  wikidata: null            # QID ставит человек (или --auto-exact)
  decision: pending         # pending | accepted | auto | rejected
  candidates:
  - {qid: Q859, label: {ru: Платон, en: Plato}, description: …, birth: "427 до н. э.", death: "347 до н. э."}
  # holder: e_… — если кандидат уже у другой действующей сущности того же типа (О10)
```

**Кандидат-держатель (О10).** `suggest` проверяет каждого кандидата по `external_ids`. Если QID уже у другой действующей сущности того же типа, в кандидат пишется `holder`, а пара `(entity, holder)` ставится в очередь `duplicate` (`merge_proposed`, `reason="review:qid_candidate"`), если открытого пункта по ней нет. Так «Омир» при «Гомер» (Q6691) попадает к человеку; решение `accepted` дальше ведёт к `qid_taken` → `merge:qid_confirmed`. При закрытии пункта решением о слиянии запись манифеста не нужна.

Проверка формы — до базы и сети, как в `epoch_dates.check_manifest`:
- `wikidata` по `^Q\d+$` или `null`;
- `decision` — из перечня;
- `entity` уникален;
- `holder`, если есть, — строка id.

### Правило `--auto-exact`

Кандидат ставится в `wikidata` с `decision: auto`, только если выполнены все условия:
- кандидат ровно один после фильтра класса;
- нормализованная подпись `ru` или `en` равна нормализованному основному названию или варианту сущности;
- если у сущности есть `primary.dates`, даты кандидата не противоречат им по правилу `dedupe.same_person`.

Иначе остаётся `pending`.

### `apply`

1. Цели:
   - записи манифеста с `wikidata` и `decision ∈ {accepted, auto}`;
   - с `--linked` — ещё и все персоны и произведения базы с внешним `wikidata`.
2. Записи манифеста обходятся по порядку, правило 1–4 требования «Подтверждение QID»:
   - есть тот же QID → ничего;
   - другой QID → `qid_conflict`;
   - QID у другой сущности, в том числе у записанной раньше в этом запуске → `qid_taken`. Для `accepted` пара `(entity, holder)` копится в `confirmed`, для `auto` — пункт `duplicate` с событием `merge_proposed` (`reason="review:qid_taken"`);
   - иначе `add_external`, в `run_actions` пишется `{kind: "external", entity, qid}`.

   После обхода `Dedupe(...).run(confirmed=confirmed, run_id=…)` (`improve-person-quality`) сливает пары по `merge:qid_confirmed`, если даты не противоречат, иначе ставит их в очередь (ревью, желательное 1). В сухом прогоне ничего не пишется, слияния считаются через `dedupe.plan`.
3. Запись Wikidata загружается (`fetch_entity`, кэш на запуск). Сбой — `fetch_failed`.
4. Персона:
   - `b = claim_date(best("P569"))`, `d = claim_date(best("P570"))`;
   - есть обе — `interval(b, d, format_original(b, d))` → `lifespan`;
   - одна — пропуск `partial`;
   - нет — `no_dates`.

   Произведение: `claim_date(best("P577"))` → `dating`, нет — `no_dates`.
5. Существующее действующее `lifespan`/`dating` сущности:
   - `span` равен → `unchanged`, без записи;
   - `span` различается → `conflict`, без записи, событие `skipped` с `reason="conflict"`.
6. Роли: `{WIKIDATA_ROLES[q] for q in items("P106")}` → `person_role`. Повтор находит `Statements.find`.
7. Каждая запись идёт так же, как в `geo_enrich._write`: `check_value` (отказ — `refused`) → `find` → `add`. Атрибуция `Attribution("source", "wikidata:<QID>", place=page_url(qid))`, `status="sourced"`, `Provenance("imported", run_id, extra={"wikidata": qid, "property": prop})`.

### `rollback(run_id)`

- `Statements.rollback_run(run_id)`: утверждения запуска, кроме проверенных человеком.
- Слияния запуска (`merges.moved.run_id`) отменяются `Statements.undo_merge` в обратном порядке.
- По `run_actions` запуска удаляются записанные им внешние QID. QID не удаляется, если его сущность с тех пор получила утверждения с атрибуцией этой записи от другого запуска: тогда `kept`.
- Событие `knowledge.life_dates.rolled_back`.

### Схема: `knowledge:8` — таблица `run_actions`

`(id, run_id, seq, kind, payload JSON, created_at)` с индексом по `run_id`. Общий журнал действий запуска вне утверждений: QID здесь, переименования и снятия — в `migrate-ontology-quality`.

### Файлы Lead'а (минимальные точки, О3)

`filling.py`:
- `WIKIDATA_ROLES` импортируется из `wikidata.py`;
- в `import_wikidata` оба блока дат — P569/P570 (`lifespan`) и P577 (`dating`, сейчас тоже срез `[1:5]`, `filling.py:535`) — заменяются вызовами `wikidata.simple_time(value)` (это `wikidata_time(value, 9)` для упрощённой записи) и `interval(...)`. Персона с одной датой не получает `lifespan`, для неё пишется событие `knowledge.import.skipped` с `property`, `reason="partial"`.

## События журнала

| Событие | Уровень | Поля |
|---|---|---|
| `knowledge.life_dates.suggested` | info | `entities` (без QID обработано), `candidates`, `auto` |
| `knowledge.life_dates.run` | info | `run_id`, `entities`, `externals`, `lifespans`, `datings`, `roles`, `unchanged`, `conflicts`, `skipped`, `failed`, `dry_run` |
| `knowledge.life_dates.skipped` | warning | `entity`, `property`, `reason` (`bad_qid`, `fetch_failed`, `bad_value`, `partial`, `no_dates`, `conflict`, `refused`, `qid_taken`, `qid_conflict`) |
| `knowledge.life_dates.rolled_back` | info | `run_id`, `statements`, `externals`, `kept` |
| `knowledge.import.skipped` (есть) | debug | `property`, `reason="partial"` — `import_wikidata`, одна дата |

## Выбор решения

| Вариант | Оптимальность | Архитектура | Поддержка и масштаб |
|---|---|---|---|
| А. Дописать P569/P570/P577 в `geo_enrich` | Меньше файлов | `geo_enrich` — возможность `geo-timeline`; смешение мест и дат в одном запуске и откате | Отчёт и причины одного запуска о двух вещах; правка чужой спецификации |
| Б. Исправить и расширить `Filling.import_wikidata` | Код уже есть | Упрощённый формат записи, без кэша, без сухого прогона и отката по запуску; файл Lead'а растёт | Нет `run_id` у импорта — откат невозможен |
| В. Отдельная команда `life_dates` по образцу `geo_enrich` + манифест QID по образцу `epoch_dates` (выбрано) | Один запрос на запись, кэш, сухой прогон | Время, сеть, QID — только `wikidata.py`; запись — через `Statements`; правило противоречия дат — из `dedupe` | Новые свойства — строка в `PROPERTIES`; 10× персон — тот же код, `--limit` |

**Выбрано В.** Платим новым модулем (~300 строк) и манифестом. `import_wikidata` чиним минимально, чтобы не держать две ошибки разбора времени. Костыли, которых избегаем:
- срез строки даты;
- свой httpx;
- QID «на глаз» без отметки решения;
- перезапись дат, которые записал человек.

## Генераторы для property-тестов (О7)

- `wd_times()` — строки времени Wikidata:
  - знак `+`/`-`, годы 1…3000;
  - точность 6–11;
  - год `0000` и мусор.

  Инвариант: записанный `span` равен `span(claim_date(...))`. Для `-NNNN` начало ≤ 0, то есть до н. э. в астрономическом счёте −(N−1).
- `wd_person_records()` — записи с P569/P570 в любых сочетаниях: оба, одно, ни одного, устаревший ранг, несколько значений с предпочтённым. Ещё P106 из таблицы и вне её, P31 человек и не человек.
- `manifests()` — манифесты с `pending`/`accepted`/`auto`/`rejected`, с верными и неверными QID, с QID, уже занятым другой сущностью.
- Инварианты:
  - повторный `apply` на тех же данных не добавляет утверждений;
  - `dry_run` ничего не пишет: дамп таблиц до и после равен, а отчёт равен отчёту настоящего запуска;
  - `rollback` возвращает дамп таблиц `statements`/`attributions`/`external_ids` к состоянию до запуска;
  - запуск без `decision ∈ {accepted, auto}` не записывает QID.

## Риски

- QID стенда. Без подтверждения человеком (или `--auto-exact`) у большинства персон QID не появится, и А5/А6 из Wikidata не вырастут. Вклад даёт и извлечение дат из текста (`improve-extraction-naming`). Замер — у Lead'а.
- Роли P106 — единственный источник `philosopher` для А6 («философ на таймлайне»). Персона без QID и без роли на таймлайне есть, но философом в смысле А6 не считается (определение — в `migrate-ontology-quality`).
- Частота запросов: `suggest` делает по 2 поиска (ru и en) и до 10 загрузок на сущность. При ~100 персонах это ~1200 запросов. `http_fetch` ждёт `Retry-After`, а `--limit` дробит работу.
