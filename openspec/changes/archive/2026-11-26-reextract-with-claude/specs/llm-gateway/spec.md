## MODIFIED Requirements

### Requirement: Сводка расходов

Сервис LLM SHALL отдавать оператору сводку расходов за период по бюджетам, сервисам, операциям, ролям и запускам. При достижении заданной доли дневного или месячного лимита SHALL создаваться событие для оповещения.

В каждой строке сводки, кроме `cost_usd` и `calls`, SHALL быть суммы `input_tokens` и `output_tokens` вызовов группы (по ним сервис знаний считает токены запуска извлечения).

#### Scenario: Приближение к лимиту

- **GIVEN** порог оповещения 80 % дневного лимита
- **WHEN** расход за день его переходит
- **THEN** создаётся событие «бюджет близок к лимиту» с бюджетом и суммой

#### Scenario: Токены в сводке по запуску

- **WHEN** в запуске `run-1` два вызова по 1000 входных и 200 выходных токенов
- **THEN** строка сводки с `group_by=run_id` для `run-1` содержит `calls=2`, `input_tokens=2000`, `output_tokens=400`

## ADDED Requirements

### Requirement: Сведения о роли

Маршрут `GET /v1/roles/{role}` SHALL отдавать `role`, `model` (идентификатор модели роли) и `call_budget_seconds` — наибольшее время структурированного вызова со всеми попытками: `(schema_retries + 1) · ((max_retries + 1) · timeout_seconds + Σ_{k=1..max_retries} retry_base_seconds · 2^(k−1))`. Неизвестная роль SHALL давать 404 `unknown_role`. Ключи провайдеров и цены MUST NOT попадать в ответ.

#### Scenario: Роль извлечения

- **WHEN** у роли `strong` `timeout_seconds=120`, `max_retries=2`, `retry_base_seconds=0.5`, `schema_retries=2`
- **THEN** ответ `{"role": "strong", "model": "deepseek-v4-pro", "call_budget_seconds": 1084.5}`

#### Scenario: Неизвестная роль

- **WHEN** запрошена роль `nope`
- **THEN** ответ 404 с `kind="unknown_role"`
