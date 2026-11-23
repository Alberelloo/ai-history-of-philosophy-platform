# Tasks

## 1. Спецификация (P0)

- [x] 1.1 OpenSpec-дельта `llm-gateway` («Эмбеддинги через OpenAI-совместимый прокси»).

## 2. Реализация (P0)

- [x] 2.1 `llm/config.py`: поле `dimensions` у `RoleConfig`.
- [x] 2.2 `llm/providers.py`: `Provider.embed`/`OpenAICompatibleProvider.embed`/`FakeProvider.embed` принимают `dimensions`; `OpenAICompatibleProvider` шлёт `dimensions` в тело, если задано.
- [x] 2.3 `llm/gateway.py`: `embed` передаёт `role_conf.dimensions` провайдеру.
- [x] 2.4 `config/llm.yaml`: провайдер `litellm`, роль `embeddings` с моделью и `dimensions`, цена модели.

## 3. Документация (P1)

- [x] 3.1 `docs/architecture/embeddings.md`: пресеты 7 моделей + конфиг LiteLLM.

## 4. Тесты и проверки (P1)

- [x] 4.1 Тесты мок `/embeddings` (`tests/llm/test_embedding_provider.py`): endpoint, модель/размерность, маппинг ответа в векторы.
- [x] 4.2 `ruff check .`, `ruff format --check .`, `lint-imports`, `check_traceability.py`.
- [ ] 4.3 `openspec archive add-embedding-gateway --yes` + PR.
