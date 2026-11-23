# Progress

## 2026-11-24 — планирование

- Ведёт: субагент `claude` (разработчик), по поручению Lead. Ветка `claude/add-embedding-gateway` от `origin/main`.
- Разобрано: эмбеддинги уже через `llm` (роль «эмбеддинги», `Provider.embed`, OpenAI-совместимый `/embeddings`); не хватало `dimensions` и провайдера `litellm`.
- Написан план: proposal, design (с «Выбор решения»), tasks, дельта спека.

## 2026-11-24 — реализация

- `llm/config.py`: `RoleConfig.dimensions`.
- `llm/providers.py`: `Provider.embed`/`OpenAICompatibleProvider.embed`/`FakeProvider.embed` принимают `dimensions`; `OpenAICompatibleProvider` шлёт `dimensions` в тело `/embeddings`, если задано; `FakeProvider` записывает `embed_dimensions`.
- `llm/gateway.py`: `embed` передаёт `role_conf.dimensions`.
- `config/llm.yaml`: провайдер `litellm`, роль `embeddings` (`bge-m3`, `dimensions: 1024`), цена `bge-m3`.
- `docs/architecture/embeddings.md`: пресеты 7 моделей + конфиг LiteLLM.
- Тесты `tests/llm/test_embedding_provider.py` (мок `/embeddings`).

## Проверки

- `openspec validate add-embedding-gateway` — valid.
- `ruff check .` — All checks passed; `ruff format --check` — 9 files formatted.
- `lint-imports` — 3 kept, 0 broken.
- `check_traceability.py` — 356/356.
- Смоук-тест в памяти: `OpenAICompatibleProvider.embed` с `dimensions` + загрузка `config/llm.yaml` — OK.

## Блокеры

- `pytest` в сессии субагента не идёт (песочница запрещает удаление файлов): тесты написаны, полный прогон — у Lead.
- Сеть к внешним провайдерам закрыта: реальные эмбеддинги — на сервере.
