# Один образ для всех сервисов: какой сервис запускать, задаёт команда в compose.yaml.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1
WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir ".[postgres]" "uvicorn[standard]>=0.30"

RUN useradd --create-home philograph
USER philograph
