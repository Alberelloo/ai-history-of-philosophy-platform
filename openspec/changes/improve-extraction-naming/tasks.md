# Tasks

Первое изменение из четырёх (решение ведущего О2). Порядок в ветке `claude/ontology-extraction`:
1. `improve-extraction-naming`;
2. `improve-person-quality`;
3. `add-wikidata-life-dates`;
4. `migrate-ontology-quality`.

Новая возможность `entity-naming` входит в `enforce` в 3.6. `entity-dating` описывают два изменения (здесь «Извлечение дат», в `add-wikidata-life-dates` — даты из Wikidata), поэтому она входит в `enforce` в `add-wikidata-life-dates` 3.6, когда тесты есть у всех её требований. Изменённые требования `ontology-extraction` уже под `enforce`, их тесты продолжают действовать.

## 1. План

- [x] 1.1 `proposal.md`, `design.md`, `tasks.md`, `progress.md`, дельты `entity-naming`, `entity-dating` (ADDED «Извлечение дат»), `ontology-extraction` (MODIFIED)
- [x] 1.2 Ревью плана ревьювером и тестировщиком, решения ведущего, правки артефактов

## 2. Разработчик

- [x] 2.1 `pyproject.toml`:
  - `hypothesis>=6.100` в `[project.optional-dependencies].dev` (О8);
  - `[tool.setuptools.package-data]` для `philograph/knowledge/*.yaml`.
- [x] 2.2 `knowledge/naming_rules.yaml`: стоп-список владельца целиком, пределы по типам (6/80, 12/160), частицы, шаблоны персоны, `exempt: [source]`. `knowledge/naming.py` — определения из спецификации `entity-naming`:
  - `load_rules` (проверка формы);
  - `script_of`, `lang_for`, `is_russian` (слова из римских цифр не считаются);
  - `check_name` (NFC, знаки, слова, порядок `empty` → `number` (нет букв, есть цифра) → `sentence` → `not_a_name` (частицы с `-`/`'`/`’`, шаблоны по нормализованному названию без учёта регистра, склейка) → `stopword`);
  - `event_label`, `InvalidName`, `names_for`.

  Юнит-тесты модуля.
- [x] 2.3 `entities.py`:
  - `normalize` с NFC;
  - `create` и `add_name` ставят язык `lang_for` для любого пути;
  - `create` и `add_name(kind="primary")` вызывают `check_name`, событие `knowledge.entity.rejected` ровно с `type`, `label` (`event_label`), `reason`;
  - `set_primary_name(entity_id, lang, text)` — прежнее основное становится вариантом, событие `knowledge.entity.renamed` ровно с `entity_id`, `lang`, `previous_lang`.
- [x] 2.4 `knowledge/dating.py`: белый список форматов по таблице `entity-dating`, порядок причин `paragraph` → `quote` → `unparsed` → `not_in_quote` (целые числа по границам цифр, римский век словом) → `era` → `single_year`. `dates.parse` не меняется. Юнит-тесты.
- [x] 2.5 `knowledge/entity_items.py`:
  - `EntityItems.index`;
  - `resolve`: тип вне реестра → `entity:type`; кандидаты по всем написаниям; разные кандидаты от разных написаний → неоднозначность; перенос логики контекста и очереди из `Filling._resolve` без изменения поведения;
  - русское основное у английской сущности;
  - `date` через `dating.check` → `lifespan` или `dating`.
- [x] 2.6 **Файлы Lead'а** (точки вызова, О3; согласование — пункт 5.1):
  - `filling.py`: `_schema` с `entities`; `language` и `EntityItems` в `_extract_fragment`; `_resolve` делегирует; `accept_core_report` (отказы в ответе), `accept_core` через него; `import_wikidata` ловит `InvalidName`;
  - `prompts/__init__.py`, `ontology.extract`: правила языка, валидности, дат; поле `language`.

  Прогон `tests/knowledge/test_filling.py` — прежние тесты зелёные без правки ожиданий.
- [x] 2.7 `ruff check . && ruff format --check .`, `lint-imports`, `python scripts/check_traceability.py`; `pytest -q tests/knowledge/test_filling.py tests/knowledge/test_registry_entities.py tests/knowledge/test_snapshot.py tests/knowledge/test_geo_enrich.py tests/knowledge/test_epoch_dates.py`. Язык по письменности в `create` затрагивает все пути создания.
- [x] 2.8 Пути из внешних данных: `geo_enrich`, `epoch_dates`, `epoch_context`, `metadata` обрабатывают отказ названия пропуском (design.md, «Пути из внешних данных»), дельты MODIFIED `epochs`, `epoch-context`, `geo-timeline`; `knowledge.extraction.dropped`/`ambiguous` описаны в `entity_items.py`. Юнит-проверки `tests/knowledge/test_invalid_name_paths_unit.py`.

## 3. Тестировщик

Модель — фейковый провайдер шлюза с записью запросов, сеть запрещена фикстурой (О6). Инфраструктура — раздел «Тестовая инфраструктура» design.md. Её создаёт это изменение, остальные три переиспользуют.

- [x] 3.1 **Инфраструктура:**
  - профили `hypothesis` `ci` (60), `pure` (400), `heavy` (25) в `tests/conftest.py`;
  - автофикстура запрета сети в `tests/knowledge/conftest.py`;
  - `tests/knowledge/dump.py`;
  - `scripts/mutation_check.py` с форматом `tests/mutations/<изменение>/mutations.yaml` и режимом `--coverage <изменение>` (О11);
  - `tests/test_mutation_coverage.py` — `--coverage` для каждого изменения с отмеченным пунктом мутационной проверки;
  - стратегии «вход + ожидание» в `tests/knowledge/strategies.py` (`numbers`, `blank`, `long_phrases`, `stopwords_perturbed`, `proper_names`, `not_names`, `scripts_mix`, `fragment_items`, `datings`). Оракул не импортирует `naming`, `dating`, `dates.parse`.
- [x] 3.2 Сценарные тесты на **каждый** сценарий `entity-naming` (2 требования), `entity-dating` («Извлечение дат») и MODIFIED `ontology-extraction` («Структурированный вывод по реестру», «Нормализация сущностей»). Каждый проверяет:
  - вывод — база, ответ справочника, перехваченный запрос к шлюзу;
  - событие с точным множеством ключей.
- [x] 3.3 Property-тест (`invariant=`) на **каждое** требование, с явными `@example` на границы и сторожевым токеном журнала (design.md, «Границы и сторожевые токены»):
  - «Язык названий»: язык = ожидание стратегии `scripts_mix`, один основной на язык, сущностей = событий `created`;
  - «Валидность»: создано ⇔ нет ожидаемой причины, одно событие с ожидаемой причиной, `label` по правилу обрезки;
  - «Извлечение дат»: `span`/`precision` = ожидание по таблице, иначе одно `dropped` с ожидаемой причиной;
  - «Структурированный вывод»: в базе только типы реестра для любых типов элементов;
  - «Нормализация»: найденная по любому написанию сущность не дублируется.
- [x] 3.3а Сценарные тесты новых сценариев дельт MODIFIED: «Название эпохи не прошло проверку», «Название события не прошло проверку», «Подпись места не прошла проверку».
- [x] 3.4 Мутации — по одной и больше на **каждое** требование. В `tests/mutations/improve-extraction-naming/mutations.yaml` указан ожидаемый упавший тест:

  | Требование | Мутация | Ожидаемый упавший тест |
  |---|---|---|
  | Язык названий | `lang_for` всегда возвращает переданный язык | сценарий «Язык по письменности на любом пути» + property языка |
  | Язык названий | `set_primary_name` заменён созданием новой сущности | «Существующая английская сущность» |
  | Валидность | `number` по `^[\d.\s]+$` | «Номер со знаками» |
  | Валидность | шаблоны с учётом регистра | «Описание с заглавной» |
  | Валидность | `not_a_name` и `stopword` поменяны местами | «Роль вместо имени» |
  | Валидность | `event_label` без обрезки | «Границы предела» (label 80) |
  | Извлечение дат | числа ищутся подстрокой | «Число внутри другого числа» |
  | Извлечение дат | эра не проверяется | «Эра не совпадает» |
  | Извлечение дат | римский век не ищется в цитате | «Века нет в цитате» |
  | Извлечение дат | тип без датировки в реестре не проверяется (отказ текстом реестра) | `dating:type` (О15, тест — тестировщик) |
  | Структурированный вывод | тип элемента не проверяется сервером | «Тип вне реестра в сущностях» |
  | Нормализация | кандидаты не ищутся по `en` | «Привязка по английскому написанию» |
  | Даты эпох из Wikidata | `invalid_name` не проверяется (создание падает) | «Название эпохи не прошло проверку» |
  | Контекстные события из Wikidata | место создаётся до проверки названия события | «Название события не прошло проверку» |
  | Места и координаты из Wikidata | подпись места не проверяется | «Подпись места не прошла проверку» |

- [x] 3.5 `python scripts/mutation_check.py --change improve-extraction-naming` — таблица в `verification.md`; `--coverage improve-extraction-naming` чисто.
- [x] 3.6 `openspec/traceability.yaml`: `entity-naming` в `enforce` (`entity-dating` — в `add-wikidata-life-dates` 3.6). `python scripts/check_traceability.py` чисто.
- [x] 3.7 `verification.md`, раздел «Тестировщик»:
  - сырые итоги pytest;
  - `--durations` property-слоя (бюджет ≤ 3 мин на все четыре изменения);
  - выдержки событий;
  - таблица «требование → сценарный тест → property-тест → мутация → упал»;
  - непроверяемое и его проверяемая часть (design.md).

## 4. Ревьювер

- [x] 4.1 Дифф против `origin/claude/embedding-docker`:
  - правило названий только в `naming.py` и данных;
  - в файлах Lead'а только точки вызова;
  - нет подгонки тестов;
  - `lint-imports`;
  - событие без лишнего текста.

## 5. Требует Lead'а

- [ ] 5.1 Согласовать факт правки `prompts/__init__.py` (`ontology.extract`) и `filling.py` (точки вызова 2.5). Пункт «Согласовать с Lead'ом» — в описании PR.
- [ ] 5.2 Оплачиваемая проба нового промпта на стенде — `Filling.estimate` на 2 фрагментах одного русского и одного английского источника. Решение о полном проходе — за Lead'ом.
- [ ] 5.3 Замер А1–А8 на стенде после всех четырёх изменений — пункт `migrate-ontology-quality` 5.x.
- [ ] 5.4 В описание PR — расхождения со спекой владельца на подтверждение (О9):
  - пятая причина `empty`;
  - пределы 12/160 для произведений и событий;
  - `number` — «нет букв, есть цифра»;
  - `dating:single_year`;
  - астрономический счёт (Платон −426/−346 вместо −427/−347);
  - русское основное и для английских источников.

## 6. Судья

- [x] 6.1 Новый субагент без истории разработки (вердикт 2026-11-25: не принято; повторно 2026-11-25: не принято — J1, J3 тестировщику, см. verification.md):
  - полнота `tasks.md`;
  - каждый сценарий и инвариант в журнале тестировщика и в собственном прогоне;
  - выборочно повторить мутации из 3.5;
  - вердикт в `verification.md`.

  PR остаётся в draft до вердикта «принято».
