# Proposal

## Why

Эмбеддинги уже проходят через сервис LLM (роль «эмбеддинги», интерфейс `Provider.embed`, OpenAI-совместимый `/embeddings`), но модель и провайдер сейчас — заглушка, а размерность не передаётся провайдеру. Чтобы переключать реальные модели эмбеддингов (BGE-M3, jina, multilingual-e5, OpenAI, Voyage, Cohere, Gemini) без правки кода, нужен единый прокси-маршрут LiteLLM и поддержка `dimensions` (Matryoshka/сжатие).

## What Changes

- В `config/llm.yaml` добавляется провайдер `litellm` (openai_compatible: base_url, api_key_env) и роль «эмбеддинги» переводится на него с полем `dimensions`.
- `RoleConfig` получает необязательное поле `dimensions`; оно проходит от конфига через шлюз к провайдеру и попадает в тело запроса `/embeddings`.
- Документируются пресеты 7 моделей эмбеддингов (конфиг LiteLLM + шорт-лист).

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `llm-gateway`: добавлено «Эмбеддинги через OpenAI-совместимый прокси».

## Impact

- Код: `llm/config.py` (`dimensions`), `llm/providers.py` (`Provider.embed` + `OpenAICompatibleProvider.embed` + `FakeProvider.embed`), `llm/gateway.py` (передача размерности).
- Данные: `config/llm.yaml` (провайдер `litellm`, роль, цены).
- Документы: `docs/architecture/embeddings.md` (пресеты моделей и конфиг LiteLLM).
- Тесты: мок `/v1/embeddings` — запрос в нужный endpoint, модель и размерность передаются, ответ маппится в векторы.
