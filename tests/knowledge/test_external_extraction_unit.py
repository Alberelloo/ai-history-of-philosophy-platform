"""Юнит-тесты ``knowledge.external_extraction``: задание, запись ответов, повтор, тариф,
отчёт, команда. Сценарии «Внешний извлекатель» и «Отчёт о запусках» — у тестировщика."""

from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import func, select

from philograph.knowledge import external_extraction as ext
from philograph.knowledge import schema as t

from .extraction_stand import Stand

TEXTS = [
    "Кант писал, что всякое знание начинается с опыта.",
    "Юм считал причинность привычкой ума.",
    "Локк сравнивал душу с чистой доской.",
    "Беркли отрицал существование материи.",
    "Рид отвечал Юму здравым смыслом.",
]


def st(subject, type_, obj, paragraph, quote):
    return {
        "subject": subject,
        "subject_type": "person",
        "type": type_,
        "object": obj,
        "object_type": "position",
        "paragraph": paragraph,
        "quote": quote,
    }


@pytest.fixture
def stand(onto, engine_for, clock) -> Stand:
    return Stand(onto, engine_for, clock, fragment_size=2)


@pytest.fixture
def version(stand):
    vid, ids = stand.version(TEXTS)
    return stand.filling.version(vid), ids


def runs(stand) -> list[dict]:
    with stand.onto.statements.engine.begin() as conn:
        return [dict(r) for r in conn.execute(select(t.filling_runs)).mappings()]


def count(stand, table) -> int:
    with stand.onto.statements.engine.begin() as conn:
        return conn.scalar(select(func.count()).select_from(table))


def test_task_lines(stand, version, events):
    data, ids = version
    lines = ext.task(stand.filling, data)
    head, *fragments = lines
    assert head["kind"] == "task" and head["fragments"] == 4 == len(fragments)
    assert head["template"] == "ontology.extract" and "Извлеки" in head["instructions"]
    assert "holds" in head["relations"] and "person" in head["entity_types"]
    second = fragments[1]
    assert second["fragment"] == 2 and second["paragraph_ids"] == ids[1:3]
    assert second["passages"].startswith(f"[1] {TEXTS[1]}")


def test_export_file(stand, version, tmp_path, events):
    data, _ = version
    path = ext.export(stand.filling, data, tmp_path)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert path.name == f"{data['version_id']}.jsonl" and len(rows) == 5
    assert events.one("knowledge.extraction.exported")["fragments"] == 4


def test_forbidden(stand, version, tmp_path, events):
    data, _ = version
    data["permissions"]["external_processing"] = False
    with pytest.raises(ext.Forbidden):
        ext.export(stand.filling, data, tmp_path)
    assert events.where("knowledge.extraction.skipped", reason="external_processing_forbidden")


def _ingest(stand, data, replies, **extra):
    params = dict(
        model="claude-opus-5-5",
        input_tokens=1_000_000,
        output_tokens=100_000,
        duration_seconds=120,
        cost_usd=ext.price_for("claude-opus-5-5").cost(1_000_000, 100_000),
    )
    params.update(extra)
    return ext.ingest(stand.filling, data, replies, **params)


def test_ingest_run_and_missing(stand, version, events):
    data, _ = version
    replies = {
        "1": {"statements": [st("Кант", "holds", "Опыт", 1, "всякое знание начинается с опыта")]},
        "3": {"statements": [st("Локк", "holds", "Чистая доска", 1, "душу с чистой доской")]},
        "9": {"statements": []},
    }
    row = _ingest(stand, data, replies)
    assert row["extractor"] == "external" and row["model"] == "claude-opus-5-5"
    assert row["fragments"] == 4 and row["duration_seconds"] == 120
    assert row["cost_usd"] == 6.0 and row["status"] == "done"
    assert row["created"] == 2
    assert row["drop_reasons"] == {"reply_invalid": 1, "reply_missing": 2}
    assert row["dropped"] == 3
    provenance = {s["provenance"]["model"] for s in stand.statements()}
    assert provenance == {"claude-opus-5-5"}
    assert len(events.of("knowledge.extraction.fragment")) == 2


def test_repeat_requires_replace(stand, version):
    data, _ = version
    replies = {"1": {"statements": [st("Кант", "holds", "Опыт", 1, "всякое знание")]}}
    first = _ingest(stand, data, replies)
    counts = [count(stand, tb) for tb in (t.statements, t.evidence, t.attributions)]
    with pytest.raises(ext.CommandError):
        _ingest(stand, data, replies)
    assert len(runs(stand)) == 1
    _ingest(stand, data, replies, replace=True)
    assert [count(stand, tb) for tb in (t.statements, t.evidence, t.attributions)] == counts
    statuses = {r["run_id"]: r["status"] for r in runs(stand)}
    assert statuses[first["run_id"]] == "rolled_back"
    assert sorted(statuses.values()) == ["done", "rolled_back"]


def test_price():
    assert ext.price_for("claude-opus-5-5").cost(1_000_000, 1_000_000, 1_000_000) == 24.2
    assert ext.price_for("x", 1.0, 2.0).cost(1_000_000, 500_000) == 2.0
    with pytest.raises(ext.CommandError):
        ext.price_for("unknown-model")


def test_read_replies_both_formats(tmp_path):
    whole = tmp_path / "a.json"
    whole.write_text(json.dumps({"1": {"statements": []}}), encoding="utf-8")
    lines = tmp_path / "b.jsonl"
    lines.write_text(
        '{"fragment": 2, "reply": {"statements": []}}\n\n{"fragment": 3, "reply": {}}\n',
        encoding="utf-8",
    )
    assert ext.read_replies(whole) == {"1": {"statements": []}}
    assert ext.read_replies(lines) == {"2": {"statements": []}, "3": {}}
    bad = tmp_path / "c.jsonl"
    bad.write_text("{не json}\n", encoding="utf-8")
    with pytest.raises(ext.CommandError):
        ext.read_replies(bad)


def test_report(stand, version, tmp_path, events, clock):
    data, _ = version
    replies = {"1": {"statements": [st("Кант", "holds", "Опыт", 1, "всякое знание")]}}
    first = _ingest(stand, data, replies)
    _ingest(stand, data, replies, replace=True)
    out = tmp_path / "audit" / "run.md"
    day = clock.now().date()
    n = ext.write_report(stand.onto.statements.engine, stand.onto.entities, day, day, out)
    text = out.read_text(encoding="utf-8")
    assert n == 1 and first["run_id"] not in text
    assert "Учебник" in text and "claude-opus-5-5" in text and "**Итого**" in text
    assert "reply_missing 3" in text
    assert events.one("knowledge.extraction.report")["runs"] == 1
    assert ext.report(stand.onto.statements.engine, stand.onto.entities, date(2100, 1, 1))


def test_main_ingest_and_codes(stand, version, tmp_path, onto):
    data, _ = version
    service = ext.Service(stand.filling, onto.statements.engine, ext._Texts(stand.filling.library))
    replies = tmp_path / "r.json"
    replies.write_text(json.dumps({"1": {"statements": []}}), encoding="utf-8")
    argv = [
        "ingest",
        "--version",
        data["version_id"],
        "--replies",
        str(replies),
        "--model",
        "claude-opus-5-5",
        "--input-tokens",
        "10",
        "--output-tokens",
        "5",
        "--duration",
        "1.5",
    ]
    assert ext.main(argv, service=service) == 0
    assert ext.main(argv, service=service) == 2  # повтор без --replace
    assert ext.main([*argv, "--replace"], service=service) == 0
    unknown = [*argv[:6], "nope-model", *argv[7:], "--replace"]
    assert ext.main(unknown, service=service) == 2
