# Покрытие тестами: ассистент, шлюзы, платформа, эксплуатация

skip_specs: true

## Что
Тесты без изменения поведения: у каждого `#### Scenario:` возможностей assistant-dialog, question-routing, answer-grounding, llm-gateway, abuse-protection, observability, service-runtime, evaluation-datasets, quality-evaluation, operational-alerts, backup-and-recovery, deployment, visual-design есть тест с маркером `scenario=`, у нормативных правил — `invariant=`, каждый тест проверяет вывод и журнал (или имеет `nolog=` с причиной).

## Зачем
Аудит 2026-11-19 (разделы 4.2–4.4): прослеживаемость считала только требования, часть сценариев и событий не проверялась, снимочные тесты раздували покрытие.
