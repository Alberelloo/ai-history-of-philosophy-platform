"""Замер скорости индексации (``python -m philograph.search.bench``)."""

from __future__ import annotations

import pytest

from philograph.library.registry import License
from philograph.search.bench import format_report, measure, published_paragraphs


def test_measure_reports_speed_and_budget():
    def embed(texts):
        return ([[0.1, 0.2] for _ in texts], 0.05)

    paragraphs = [{"id": f"p{i}", "text": "текст абзаца"} for i in range(10)]
    stats = measure(embed, paragraphs, limit=4)
    assert stats["measured"] == 4
    assert stats["total"] == 10
    assert stats["median_ms"] >= 0
    assert stats["paragraphs_per_second"] >= 0
    assert stats["budget_usd"] == pytest.approx(0.2)

    report = format_report(stats, model="concept-v1", dimension=2)
    assert "абзацев/с" in report
    assert "мс/абзац" in report
    assert "Оценка времени на всю библиотеку" in report
    assert "наполнение" in report


def test_bench_without_provider_exits_2(capsys):
    from philograph.search.bench import main

    assert main([], env={}) == 2
    err = capsys.readouterr().err
    assert "PHILOGRAPH_LLM_URL" in err
    assert "PHILOGRAPH_EMBEDDING_MODEL" in err
    assert "PHILOGRAPH_EMBEDDING_DIMENSION" in err


def test_published_paragraphs_respect_permissions(rig):
    """Замер читает только опубликованное с разрешением на внешнюю обработку."""
    rig.registry.add_license_kind(
        "show-only",
        "Только показ",
        None,
        {"display": True, "external_processing": False, "quoting": True},
    )
    lic = License("show-only", "public_domain", author_death_years=[1900])
    source_id = rig.registry.register(
        "operator",
        title="Закрытый источник",
        authors=["З"],
        language="ru",
        kind="textbook",
        license=lic,
        scope="public",
        files=[{"name": "z", "path": "z.txt"}],
    )
    rig.files["z.txt"] = "Глава 1\n\nРассудок есть способность правил.\n".encode()
    rig.ids["z"] = source_id
    rig.publish("ru")
    rig.publish("z")

    paragraphs = published_paragraphs(rig.indexer.library)
    assert {p["source_id"] for p in paragraphs} == {rig.ids["ru"]}
