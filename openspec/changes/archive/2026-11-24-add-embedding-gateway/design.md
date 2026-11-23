# Design: эмбеддинги через LiteLLM

## Текущее состояние

Эмбеддинги уже идут через сервис LLM: `search/main.py` читает `PHILOGRAPH_EMBEDDING_MODEL`/`PHILOGRAPH_EMBEDDING_DIMENSION`, создаёт `LlmEmbedder` → HTTP `/embed` в сервис LLM → `gateway.embed` (роль «эмбеддинги») → `Provider.embed(model, texts, timeout)` → `OpenAICompatibleProvider.embed` шлёт POST `/embeddings` `{"model", "input"}`. В `config/llm.yaml` роль «эмбеддинги» — заглушка `embeddings-stub`. Размерность в тело запроса не передаётся, поля `dimensions` в конфиге нет.

## Целевой дизайн

- Единый OpenAI-совместимый endpoint `/embeddings` — прокси LiteLLM. Наш код ходит в один адрес; модель, провайдера, ключи и бюджеты переключают в конфиге LiteLLM.
- `config/llm.yaml`: провайдер `litellm` (`kind: openai_compatible`, `base_url`, `api_key_env`), роль `embeddings` с `model` и `dimensions`.
- `RoleConfig.dimensions: int | None` → `gateway.embed` → `provider.embed(..., dimensions)` → тело запроса `{"model", "input", "dimensions": N}` (только если задано).

## Выбор решения

Как подключать эмбеддинги (критерии: оптимальность, архитектурная правильность, поддерживаемость):

| Вариант | Оценка |
|---|---|
| **А. Прокси LiteLLM (выбрано)** | Один endpoint, переключение моделей/провайдеров/ключей в конфиге LiteLLM без правки кода; централизует бюджеты и ключи. Плюс своя `dimensions`-поддержка |
| Б. SDK LiteLLM в процессе | Тянет тяжёлую зависимость, смешивает прокси-логику с нашим кодом; тестировать сложнее |
| В. Прямые провайдеры (по одному классу на провайдера) | Дублирует `OpenAICompatibleProvider`, больше кода на каждый провайдер, переключение = правка кода |

## Явные договорённости

1. Модель и размерность — конфиг, не код; без `dimensions` поле не отправляется.
2. Ключи и бюджеты провайдеров — на стороне LiteLLM/`.env`, не в репозитории.
3. Сеть к внешним провайдерам из среды разработки закрыта: тесты на мок-эндпоинте, реальные прогоны — на сервере.
