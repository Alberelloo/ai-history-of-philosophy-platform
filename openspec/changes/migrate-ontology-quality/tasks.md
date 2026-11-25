# Tasks

Четвёртое, последнее изменение в ветке. Оно использует:
- `naming` и `set_primary_name` (`improve-extraction-naming`);
- `dedupe`, `merge_entities` и `undo_merge` (`improve-person-quality`);
- `run_actions` и записи Wikidata (`add-wikidata-life-dates`).

Возможность `ontology-migration` входит в `enforce` в 3.7.

## 1. План

- [x] 1.1 `proposal.md`, `design.md` (выбор варианта миграции с расчётом А1, снятие, сухой прогон, формулы А1–А8), `tasks.md`, `progress.md`, дельта `ontology-migration`
- [ ] 1.2 Ревью плана, решения ведущего (особенно: гибрид и оплачиваемый перевод — О5), правки

## 2. Разработчик

- [ ] 2.1 Схема `knowledge:9`:
  - `entities.retired_run`, `entities.retired_reason`;
  - `schema.active(entities)`;
  - замена четырёх копий `redirect_to IS NULL` (`snapshot.load`, `mentions.py`, `Entities.find`/`duplicate_candidates`/`externals`, индекс `dedupe`);
  - карточка снятой — 404.

  Юнит-тесты миграции схемы и фильтра.
- [ ] 2.2 `knowledge/integrity.py`: `Baseline`, `baseline`, `compare` (свёртка через `merges.moved.folded`, мусор через `retired_run`), `save`/`load`. Юнит-тесты.
- [ ] 2.3 `knowledge/ontology_migrate.py`:
  - `Action`, `View`, `STEPS`;
  - шаги `lang_fix`, `retire`, `wikidata_labels`, `translate` (пакеты, проверка ответа по порядку design.md, причины отказов), `dedupe`, `verify` (аварийный откат);
  - `Migration.plan/run/rollback`, `Report`;
  - события `knowledge.migration.*`, `knowledge.entity.retired/restored`.
- [ ] 2.4 CLI `plan|run|rollback` (`--translate off|model`, `--batch`, `--from-file`, `--estimate`, `--limit`). Шлюз LLM — `ServiceClient` из настроек сервиса знаний, как в `main.py`. Wikidata — `wikidata.http_fetch` или файл.
- [ ] 2.5 `knowledge/quality_report.py`:
  - соединение только на чтение (SQLite `mode=ro`, Postgres `default_transaction_read_only`), без `migrations.upgrade`, совместимость со схемой до `knowledge:9`;
  - `CRITERIA` — данные с формулами А1–А8;
  - таблица, `--json`, `--save`, `--baseline`, коды 0/1/2;
  - событие `knowledge.quality.measured`.
- [ ] 2.6 **Файл Lead'а** `prompts/__init__.py`: шаблон `ontology.translate_names` (поле `items`). Согласование — 5.1.
- [ ] 2.7 Юнит-тесты модулей 2.2–2.5. `ruff`, `lint-imports`, `check_traceability.py`; `pytest -q` на `tests/knowledge/test_snapshot.py`, `test_catalog*.py`, `test_map*.py`, `test_mentions_cards.py`, `test_statements.py` (фильтр действующих не ломает прежнее).

## 3. Тестировщик

Модель — фейковый провайдер (ответы по шаблону `ontology.translate_names`), Wikidata — фикстуры, сеть запрещена (О6). Стенда Lead'а на машине нет (О4б): синтетическая онтология с симптомами П1–П4.

- [ ] 3.1 Фикстура «синтетическая онтология стенда» (сценарий спецификации: номера, стоп-слова, пустое, мусорные персоны, склейка, Berkeley×3, Hume/Юм с QID, Гомер/Омир, латинские понятия с `ru`, 40 утверждений с атрибуциями, 3 на мусор). Генераторы `ontologies`, `wd_label_records`, `translation_replies` в `tests/knowledge/strategies.py`. Функция дампа таблиц.
- [ ] 3.2 Сценарные тесты на каждый сценарий пяти требований `ontology-migration`. Каждый проверяет вывод (база, справочник, карта, карточка, JSON отчёта, таблица замера, код выхода) и события с полями.
- [ ] 3.3 Property-тест на каждое требование:
  - «Миграция»: нет потерь, нет действующих с причиной отказа, `plan` = `run --translate off`, `plan` не меняет дамп;
  - «Снятие»: показанное ∩ снятое = ∅, число строк утверждений не меняется;
  - «Перевод»: записанное русское, проходит правило, свой пакет; без флага запросов нет;
  - «Откат»: дамп равен исходному;
  - «Замер»: дамп не меняется, каждое Аi равно независимому расчёту по дампу, итог ⇔ все пороги.
- [ ] 3.4 Мутации, на каждое требование хотя бы одна, результат — в `verification.md`:
  - `verify` без аварийного отката;
  - `retire` без фильтра в снимке;
  - принимать латиницу в переводе;
  - не проверять номер пакета;
  - откат без `undo_merge`;
  - замер с записью (без `mode=ro`);
  - А1 без исключения `source`;
  - А4 по вариантам вместо основных.
- [ ] 3.5 Тест «Только чтение»: попытка `INSERT` через соединение замера падает. Время изменения файла SQLite не меняется.
- [ ] 3.6 Прежние тесты `entity-catalog`, `knowledge-graph`, `entity-cards`, `entity-mentions`, `geo-timeline` проходят без правки ожиданий.
- [ ] 3.7 `ontology-migration` в `enforce`, `check_traceability.py` чисто.
- [ ] 3.8 `verification.md`: сырые итоги, события, таблица «требование → доказывающий тест → мутация» по пяти требованиям.

## 4. Ревьювер

- [ ] 4.1 Проверить:
  - условие «действующая» в одном месте;
  - нет удаления сущностей и утверждений;
  - перевод не применяется без проверки;
  - замер не пишет;
  - сухой прогон тем же планировщиком;
  - нет подгонки под цифры А1–А8 (особые случаи под симптомы стенда);
  - нет названий в событиях.

## 5. Требует Lead'а

- [ ] 5.1 Согласовать новый шаблон `ontology.translate_names` в `prompts/__init__.py`. Пункт PR «Согласовать с Lead'ом» — вместе с остальными правками промпта и `filling.py`.
- [ ] 5.2 На стенде (данные `.stack` не коммитятся), по шагам:
  1. `quality_report --save before.json` — замер «до»;
  2. `add-wikidata-life-dates` 5.2 — QID, даты, роли;
  3. `ontology_migrate plan --from-file …` — проверить `retired` по причинам и `to_translate`.
- [ ] 5.3 **Оплачиваемо:** `ontology_migrate plan --estimate` (одна проба), решение о `run --translate model`. Ожидаемая стоимость ≈ $0,06 по ценам `config/llm.yaml`.
- [ ] 5.4 `ontology_migrate run --translate model`, отчёт JSON — к PR. Выборочная проверка переводов человеком (не меньше 50 из `renamed.model`).
- [ ] 5.5 `quality_report --baseline before.json` — таблица А1–А8 к PR. Цель: А1 ≥ 0,90, А2 = А3 = А4 = А7 = 0, А5 ≥ 20, А6 ≥ 10, А8 = 0. Если А5/А6 не достигнуты — какие персоны без QID и без дат (справочная часть замера), решение по манифесту QID.
- [ ] 5.6 Очередь проверки `duplicate` после миграции (Гомер/Омир, совпадения не-персон) — решение человека.

## 6. Судья

- [ ] 6.1 Новый субагент:
  - полнота;
  - каждый сценарий и инвариант в журнале тестировщика и в собственном прогоне;
  - сам запустить `plan`, `run --translate model` (фейк), `rollback` и `quality_report` на синтетической онтологии и сверить дампы;
  - повторить мутации «`verify` без отката» и «замер с записью»;
  - вердикт в `verification.md`.

  Вердикт по этому изменению — последний перед выводом PR из draft.
