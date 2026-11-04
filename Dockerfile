# Один образ для всех сервисов: какой сервис запускать, задаёт команда в compose.yaml.
FROM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web ./
RUN npm run build

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1
WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir ".[postgres]" "uvicorn[standard]>=0.30"
COPY --from=web /web/dist ./web/dist

RUN useradd --create-home philograph
USER philograph
