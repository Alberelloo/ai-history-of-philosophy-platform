"""Замер скорости индексации абзацев: ``python -m philograph.search.bench``.

Берёт опубликованные абзацы библиотеки, которые реально ушли бы в смысловой индекс, считает
эмбеддинги на настоящем провайдере (сервис LLM) и печатает скорость, не записывая ничего в
боевой индекс. Расход бюджета «наполнение» берётся из ответов сервиса LLM.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import statistics
import sys
import time
from collections.abc import Callable
from typing import Any

from philograph.platform.client import ServiceClient
from philograph.search.clients import EmbeddingError, LibraryHttp
from philograph.search.indexing import chunks

# Вызов эмбеддингов: тексты → (векторы, стоимость в долларах бюджета «наполнение»).
Embed = Callable[[list[str]], tuple[list[list[float]], float]]


def published_paragraphs(library: LibraryHttp) -> list[dict[str, Any]]:
    """Опубликованные абзацы, которые реально ушли бы в смысловой индекс.

    Соблюдает разрешение на внешнюю обработку и берёт только показываемые в поиске разделы —
    как ``Indexer.index_version``.
    """
    paragraphs: list[dict[str, Any]] = []
    for item in library.published():
        data = library.version_paragraphs(item["version_id"])
        if not data["permissions"].get("external_processing"):
            continue
        for p in data["paragraphs"]:
            if p["searchable"]:
                paragraphs.append({**p, "source_id": data["source_id"]})
    return paragraphs


def measure(
    embed: Embed,
    paragraphs: list[dict[str, Any]],
    *,
    limit: int,
    chunk_chars: int = 2000,
    chunk_overlap: int = 200,
) -> dict[str, Any]:
    """Считает эмбеддинги для первых ``limit`` абзацев и возвращает числа для отчёта."""
    sample = paragraphs[:limit]
    per_paragraph_ms: list[float] = []
    budget_usd = 0.0
    for item in sample:
        parts = chunks(item["text"], chunk_chars, chunk_overlap)
        started = time.perf_counter()
        _, cost = embed(parts)
        per_paragraph_ms.append((time.perf_counter() - started) * 1000)
        budget_usd += cost
    median_ms = statistics.median(per_paragraph_ms) if per_paragraph_ms else 0.0
    paragraphs_per_second = 1000.0 / median_ms if median_ms > 0 else 0.0
    return {
        "measured": len(sample),
        "total": len(paragraphs),
        "median_ms": median_ms,
        "paragraphs_per_second": paragraphs_per_second,
        "budget_usd": budget_usd,
    }


def _seconds_human(seconds: float) -> str:
    if seconds >= 60:
        return f"{seconds:.1f} с ({seconds / 60:.1f} мин)"
    return f"{seconds:.1f} с"


def format_report(stats: dict[str, Any], *, model: str, dimension: int) -> str:
    """Отчёт замера по-русски."""
    total = stats["total"]
    estimate = total / stats["paragraphs_per_second"] if stats["paragraphs_per_second"] > 0 else 0.0
    return (
        f"Модель: {model} (размерность {dimension})\n"
        f"Абзацев в замере: {stats['measured']}\n"
        f"Медиана: {stats['median_ms']:.2f} мс/абзац\n"
        f"Скорость: {stats['paragraphs_per_second']:.2f} абзацев/с\n"
        f"Оценка времени на всю библиотеку ({total} абзацев): {_seconds_human(estimate)}\n"
        f"Расход бюджета «наполнение»: ${stats['budget_usd']:.6f}"
    )


def _embed_via_llm(llm: ServiceClient, dimension: int) -> Embed:
    """Эмбеддинги через сервис LLM; стоимость из ответа, размерность проверяется."""

    def embed(texts: list[str]) -> tuple[list[list[float]], float]:
        response = llm.post(
            "embed",
            json={"texts": texts, "caller": "search", "operation": "index", "budget": "filling"},
        )
        if response.status_code != 200:
            raise EmbeddingError(response.json().get("kind", str(response.status_code)))
        body = response.json()
        vectors = body["vectors"]
        for vector in vectors:
            if len(vector) != dimension:
                raise EmbeddingError(f"ожидаемая размерность {dimension}, получена {len(vector)}")
        return vectors, body.get("cost_usd", 0.0)

    return embed


def main(argv: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    env = dict(os.environ if env is None else env)
    # Вывод по-русски в UTF-8 независимо от кодовой страницы консоли Windows.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError, OSError):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="python -m philograph.search.bench",
        description="Замер скорости индексации абзацев на настоящем провайдере эмбеддингов",
    )
    parser.add_argument("--limit", type=int, default=200, help="сколько абзацев замерить")
    args = parser.parse_args(argv)

    missing_llm = [
        name
        for name in (
            "PHILOGRAPH_LLM_URL",
            "PHILOGRAPH_EMBEDDING_MODEL",
            "PHILOGRAPH_EMBEDDING_DIMENSION",
        )
        if not env.get(name)
    ]
    if missing_llm:
        print(
            "Не задан провайдер эмбеддингов: задайте PHILOGRAPH_LLM_URL, "
            "PHILOGRAPH_EMBEDDING_MODEL и PHILOGRAPH_EMBEDDING_DIMENSION",
            file=sys.stderr,
        )
        return 2
    if not env.get("PHILOGRAPH_LIBRARY_URL"):
        print("Не задан PHILOGRAPH_LIBRARY_URL для чтения библиотеки", file=sys.stderr)
        return 2
    try:
        dimension = int(env["PHILOGRAPH_EMBEDDING_DIMENSION"])
    except ValueError:
        print("PHILOGRAPH_EMBEDDING_DIMENSION должен быть целым числом", file=sys.stderr)
        return 2

    library = LibraryHttp(ServiceClient("library", env["PHILOGRAPH_LIBRARY_URL"] + "/api"))
    llm = ServiceClient("llm", env["PHILOGRAPH_LLM_URL"], timeout=30)
    embed = _embed_via_llm(llm, dimension)

    paragraphs = published_paragraphs(library)
    stats = measure(embed, paragraphs, limit=args.limit)
    print(format_report(stats, model=env["PHILOGRAPH_EMBEDDING_MODEL"], dimension=dimension))
    return 0


if __name__ == "__main__":
    sys.exit(main())
