# Эмбеддинги через LiteLLM

Эмбеддинги идут через сервис LLM в один OpenAI-совместимый endpoint `/embeddings` — прокси
LiteLLM. Модель, размерность и провайдера переключают в `config/llm.yaml` (роль `embeddings`) и
в конфиге LiteLLM; код не меняется.

## Наш конфиг (`config/llm.yaml`)

```yaml
providers:
  litellm:
    kind: openai_compatible
    base_url: http://localhost:4000      # self-hosted litellm server
    api_key_env: LITELLM_API_KEY
roles:
  embeddings: {provider: litellm, model: bge-m3, dimensions: 1024, timeout_seconds: 60}
prices:
  bge-m3: {input_cache_miss: 0.0, input_cache_hit: 0.0}
```

`dimensions` не обязателен: без него запрос идёт без поля, векторы — той длины, что вернул
провайдер. Для Matryoshka (openai/text-embedding-3-large) размерность задаёт сжатие.

## Пресеты моделей (конфиг LiteLLM)

`config.yaml` LiteLLM (`litellm` self-hosted):

```yaml
model_list:
  # 1. BGE-M3 — self-host, размерность 1024
  - model_name: bge-m3
    litellm_params:
      model: huggingface/BAAI/bge-m3
      api_base: http://bge-m3:80
  # 2. jina-embeddings-v3 — self-host, 1024
  - model_name: jina-v3
    litellm_params:
      model: huggingface/jinaai/jina-embeddings-v3
      api_base: http://jina-v3:80
  # 3. multilingual-e5-large — self-host, 1024
  - model_name: e5-large
    litellm_params:
      model: huggingface/intfloat/multilingual-e5-large
      api_base: http://e5-large:80
  # 4. OpenAI text-embedding-3-large — 3072, Matryoshka (можно dimensions)
  - model_name: openai-3-large
    litellm_params:
      model: openai/text-embedding-3-large
      api_key: os.environ/OPENAI_API_KEY
  # 5. Voyage voyage-3-large (или voyage-multilingual-2)
  - model_name: voyage-3-large
    litellm_params:
      model: voyage/voyage-3-large
      api_key: os.environ/VOYAGE_API_KEY
  # 6. Cohere embed-multilingual-v3.0 — 1024
  - model_name: cohere-multilingual
    litellm_params:
      model: cohere/embed-multilingual-v3.0
      api_key: os.environ/COHERE_API_KEY
  # 7. Gemini text-embedding-004 — 768
  - model_name: gemini-embed
    litellm_params:
      model: gemini/text-embedding-004
      api_key: os.environ/GEMINI_API_KEY
```

Шорт-лист:

| # | Модель | Развёртывание | Размерность | Примечание |
|---|---|---|---|---|
| 1 | BGE-M3 | self-host | 1024 | мультиязычный, плотные+разреженные |
| 2 | jina-embeddings-v3 | self-host | 1024 | Matryoshka, task адаптеры |
| 3 | multilingual-e5-large | self-host | 1024 | только нужен префикс query/passage |
| 4 | openai/text-embedding-3-large | API | 3072 | Matryoshka (сжатие через dimensions) |
| 5 | voyage/voyage-3-large | API | 1024 | или voyage-multilingual-2 |
| 6 | cohere/embed-multilingual-v3.0 | API | 1024 | мультиязычный |
| 7 | gemini/text-embedding-004 | API | 768 | мультиязычный |

Смена модели: в `config/llm.yaml` поменять `roles.embeddings.model` (+ `dimensions`), а в
`config.yaml` LiteLLM — соответствующий `model_name`. Ключи и бюджеты — на стороне LiteLLM и
`.env`, в репозиторий не попадают.
