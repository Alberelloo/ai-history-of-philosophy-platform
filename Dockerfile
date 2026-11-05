# Один образ для всех сервисов: какой сервис запускать, задаёт команда в compose.yaml.
FROM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web ./
RUN npm run build

FROM python:3.13-slim

# Маркеры запуска: по ним сервис после падения пишет в журнал, что его перезапустили.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 \
    PHILOGRAPH_STATE_DIR=/tmp/philograph-state
WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir ".[postgres]" "uvicorn[standard]>=0.30"
COPY --from=web /web/dist ./web/dist
COPY config ./config
COPY scripts ./scripts
COPY demo ./demo

# Именованный том при первом подключении берёт владельца каталога из образа.
RUN useradd --create-home philograph && mkdir -p /data/files && chown philograph /data/files
USER philograph
