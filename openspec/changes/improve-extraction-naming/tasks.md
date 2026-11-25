# Tasks

Первое изменение из четырёх (решение ведущего О2). Порядок в ветке `claude/ontology-extraction`:
1. `improve-extraction-naming`;
2. `improve-person-quality`;
3. `add-wikidata-life-dates`;
4. `migrate-ontology-quality`.

Новые возможности `entity-naming` и `entity-dating` входят в `enforce` в 3.6. Изменённые требования `ontology-extraction` уже под `enforce`, их тесты продолжают действовать.

## 1. План

- [x] 1.1 `proposal.md`, `design.md`, `tasks.md`, `progress.md`, дельты `entity-naming`, `entity-dating` (ADDED «Извлечение дат»), `ontology-extraction` (MODIFIED)
- [ ] 1.2 Ревью плана ревьювером и тестировщиком, решения ведущего, правки артефактов

## 2. Разработчик

- [ ] 2.1 `pyproject.toml`:
  - `hypothesis>=6.100` в `[project.optional-dependencies].dev` (О8);
  - `[tool.setuptools.package-data]` для `philograph/knowledge/*.yaml`.
- [ ] 2.2 `knowledge/naming_rules.yaml`: стоп-список владельца целиком, пределы по типам, частицы, шаблоны персоны, `exempt: [source]`. `knowledge/naming.py`:
  - `load_rules` с проверкой формы;
  - `script_lang`, `is_russian`;
  - `check_name` — порядок причин по design.md;
  - `InvalidName`;
  - `names_for`.

  Юнит-тесты модуля.
- [ ] 2.3 `entities.py`:
  - `create` и `add_name(kind="primary")` вызывают `check_name`, событие `knowledge.entity.rejected` (`events.define`, `label` ≤ 80);
  - `set_primary_name(entity_id, lang, text)` — прежнее основное становится вариантом с языком по письменности, событие `knowledge.entity.renamed`.
- [ ] 2.4 `knowledge/entity_items.py`:
  - `EntityItems.index`, `resolve` (кандидаты по всем написаниям; перенос логики контекста и очереди из `Filling._resolve` без изменения поведения);
  - русское основное у английской сущности;
  - `date` — проверки абзаца, цитаты, разбора, годов в цитате, `single_year`; `lifespan` или `dating`.
- [ ] 2.5 **Файлы Lead'а** (точки вызова, О3; пункт 5.1 — согласование):
  - `filling.py`: `_schema` с `entities`; `language` и `EntityItems` в `_extract_fragment`; `_resolve` делегирует; `accept_core` и `import_wikidata` ловят `InvalidName`;
  - `prompts/__init__.py`, `ontology.extract`: правила языка, валидности, дат; поле `language`.

  Прогон `tests/knowledge/test_filling.py` — прежние тесты зелёные без правки ожиданий.
- [ ] 2.6 `ruff check . && ruff format --check .`, `lint-imports`, `python scripts/check_traceability.py`, `pytest -q tests/knowledge/test_filling.py tests/knowledge/test_registry_entities.py tests/llm` (затронутые пакеты)

## 3. Тестировщик

Модель — фейковый провайдер шлюза (`FakeProvider`, ответы по шаблону `ontology.extract`), сеть запрещена (О6).

- [ ] 3.1 Профиль `hypothesis` `ci` в `tests/conftest.py`: `derandomize=True`, `max_examples=60`, `deadline=None`, `database=None`. Генераторы в `tests/knowledge/strategies.py` по таблице design.md: `numbers`, `blank`, `long_phrases`, `stopwords_perturbed`, `proper_names`, `not_names`, `labels`, `fragment_items`, `datings`.
- [ ] 3.2 Сценарные тесты `@pytest.mark.req("entity-naming", …, scenario=…)` на каждый сценарий «Язык названий сущностей» и «Валидность названий сущностей». Каждый проверяет вывод (сущности и названия в базе, ответ справочника) и событие с полями.
- [ ] 3.3 Сценарные тесты `entity-dating` «Извлечение дат» и изменённых требований `ontology-extraction`:
  - «Схема с сущностями и датировкой»: запрос к шлюзу перехватывается фейком;
  - «Ответ без сущностей»;
  - «Привязка по английскому написанию».
- [ ] 3.4 Property-тест (`invariant=`) на **каждое** требование:
  - «Язык названий»: один основной на язык, язык = письменность, сущностей = событий `created`;
  - «Валидность»: создано ⇔ нет причины, отказ ⇔ одно событие с той же причиной, `label` ≤ 80;
  - «Извлечение дат»: записанное ⇒ годы в цитате и `span` равен разбору, отказ ⇒ одно `dropped` `dating:*`;
  - «Структурированный вывод»: в базе только типы реестра;
  - «Нормализация»: найденная по любому написанию сущность не дублируется.
- [ ] 3.5 Мутации, на каждое требование хотя бы одна, результат — в `verification.md`:
  - убрать проверку `number`;
  - поменять местами `not_a_name` и `stopword`;
  - записывать язык `ru` всегда;
  - не проверять год в цитате;
  - создавать новую сущность вместо `set_primary_name`;
  - не искать кандидатов по `en`.
- [ ] 3.6 `openspec/traceability.yaml`: `entity-naming`, `entity-dating` в `enforce`. `python scripts/check_traceability.py` чисто.
- [ ] 3.7 `verification.md`, раздел «Тестировщик»:
  - сырые итоги pytest;
  - выдержки событий;
  - таблица «требование → доказывающий тест (сценарный, property) → мутация → упал ли».

## 4. Ревьювер

- [ ] 4.1 Дифф против `origin/claude/embedding-docker`:
  - правило названий только в `naming.py` и данных;
  - в файлах Lead'а только точки вызова;
  - нет подгонки тестов;
  - `lint-imports`;
  - событие без лишнего текста.

## 5. Требует Lead'а

- [ ] 5.1 Согласовать факт правки `prompts/__init__.py` (`ontology.extract`) и `filling.py` (точки вызова 2.5). Пункт «Согласовать с Lead'ом» — в описании PR.
- [ ] 5.2 Оплачиваемая проба нового промпта на стенде — `Filling.estimate` на 2 фрагментах одного русского и одного английского источника. Решение о полном проходе — за Lead'ом.
- [ ] 5.3 Замер А1–А8 на стенде после всех четырёх изменений — пункт `migrate-ontology-quality` 5.x.

## 6. Судья

- [ ] 6.1 Новый субагент без истории разработки:
  - полнота `tasks.md`;
  - каждый сценарий и инвариант в журнале тестировщика и в собственном прогоне;
  - выборочно повторить мутации из 3.5;
  - вердикт в `verification.md`.

  PR остаётся в draft до вердикта «принято».
