# Tasks

Второе изменение в ветке (после `improve-extraction-naming`, использует его `naming.py` и `EntityItems`). Возможность `person-quality` входит в `enforce` в 3.6. MODIFIED-требования `ontology-entities` уже под `enforce`.

## 1. План

- [x] 1.1 `proposal.md`, `design.md`, `tasks.md`, `progress.md`, дельты `person-quality` (ADDED), `ontology-entities` (MODIFIED «Поиск дублей», «Слияние с перенаправлением»)
- [ ] 1.2 Ревью плана, решения ведущего, правки артефактов

## 2. Разработчик

- [ ] 2.1 `knowledge/dedupe.py`: `Verdict`, `same_person` (порядок проверок design.md, допуск дат 2 года по интервалам), `choose_kept`, `clusters` (индекс по основным названиям и QID), `Dedupe.run`. Юнит-тесты.
- [ ] 2.2 `entities.py`, `merge` переносит:
  - `attributions.who` (`who_kind="entity"`);
  - `portraits` (конфликт `phash` — остаётся за удалённой);
  - вид названий (основное → вариант, `moved.kinds`).

  Также `merge` удаляет `graph_extensions` удалённой. `undo_merge` симметрично. Формат `moved` — с умолчаниями для старых записей.
- [ ] 2.3 `statements.py`:
  - `merge_entities` — пересчёт ключей, свёртка с архивом строки, перенос атрибуций и подтверждений, согласие, `_update_primary`, событие с новыми полями;
  - `undo_merge`;
  - `get` по свёрнутому id отдаёт `survivor`;
  - `events.define` — `optional` поля `knowledge.entity.merged`, событие `knowledge.entity.merge_proposed`.
- [ ] 2.4 `review.py`: `resolve_duplicate` вызывает `merge_entities`. `refresh_duplicates` использует `duplicate_candidates` с новыми условиями (общее основное, один QID) через индекс, без O(n²).
- [ ] 2.5 `entity_items.py`: несколько кандидатов-персон от разных написаний одного элемента — `same_person(paired_by_model=True)`, затем слияние, очередь или прежняя неоднозначность.
- [ ] 2.6 **Файл Lead'а** `prompts/__init__.py`: определение персоны с отрицательными примерами в `ontology.extract`. Согласование — 5.1.
- [ ] 2.7 `ruff`, `lint-imports`, `check_traceability.py`; `pytest -q` на `tests/knowledge/test_filling.py`, `tests/knowledge/test_registry_entities.py`, `tests/knowledge/test_statements.py` и тесты очереди проверки (`tests/knowledge` по `review`). Прежние тесты слияния (`undo_merge`) зелёные без правки ожиданий.

## 3. Тестировщик

- [ ] 3.1 Генераторы в `tests/knowledge/strategies.py`: `persons_with_variants`, `ontology_with_duplicates`, `not_persons`. Функция дампа таблиц для сравнения «до/после».
- [ ] 3.2 Сценарные тесты на каждый сценарий `person-quality` и MODIFIED-требований `ontology-entities`. Проверяются вывод (база, карточка по старому id, очередь проверки) и события с полями.
- [ ] 3.3 Property-тест на каждое требование:
  - «Качество персон»: ни одной персоны с отклоняемым основным названием, событие на каждый отказ;
  - «Слияние вариантов»: слито ⇔ условия 1–3, разные QID никогда, одно основное на язык;
  - «Поиск дублей»: общее основное или QID ⇒ кандидат, разные типы никогда;
  - «Слияние с перенаправлением»: сохранение утверждений, атрибуций, подтверждений; отмена ⇒ дамп равен исходному.
- [ ] 3.4 Мутации, на каждое требование, результат — в `verification.md`:
  - не переносить `attributions.who`;
  - не пересчитывать ключ;
  - разрешить слияние при разных QID;
  - убрать проверку дат;
  - оставлять два основных;
  - не восстанавливать свёрнутые при отмене;
  - сливать при совпадении варианта.
- [ ] 3.5 Прежние тесты `ontology-entities` («Старая ссылка», «Отмена», «Кандидаты») проходят без правки ожиданий.
- [ ] 3.6 `person-quality` в `enforce`, `check_traceability.py` чисто.
- [ ] 3.7 `verification.md`: сырые итоги, события, таблица «требование → доказывающий тест → мутация».

## 4. Ревьювер

- [ ] 4.1 Правило тождества только в `dedupe.py`. Свёртка только в `Statements`. Нет второго пути слияния. `moved` обратно совместим. Нет O(n²) на пути извлечения.

## 5. Требует Lead'а

- [ ] 5.1 Согласовать правку `ontology.extract` (определение персоны). Объединяется с `improve-extraction-naming` 5.1 в один пункт PR.
- [ ] 5.2 На стенде: просмотр очереди `duplicate` после миграции (пары `variant`/`dates`, «Гомер»/«Омир») — решение человека.

## 6. Судья

- [ ] 6.1 Новый субагент:
  - полнота;
  - сценарии и инварианты в журнале тестировщика и в собственном прогоне;
  - выборочно мутации из 3.4, обязательно «разные QID» и «отмена со свёрткой»;
  - вердикт в `verification.md`.
