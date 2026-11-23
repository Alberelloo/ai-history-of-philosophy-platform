"""Запись только с метаданными: без файлов, без текста, читателю не видна."""

from __future__ import annotations

import pytest

req = pytest.mark.req
SC = "source-catalog"
SR = "source-registry"


def metadata_entry(env, entry_id: str = "wittgenstein-pi") -> dict:
    return env.entry(
        entry_id,
        metadata_only=True,
        override={
            "metadata": {
                "title": "Philosophical Investigations",
                "authors": [{"name": "Ludwig Wittgenstein", "death_year": 1951, "wikidata": None}],
                "language": "en",
                "year": 1953,
                "abstract": "A work on the nature of language and meaning.",
                "toc": ["Meaning", "Rule-following"],
                "citations": ["Tractatus Logico-Philosophicus"],
            },
            "files": [],
        },
        license={
            "kind": "in-copyright",
            "basis": "in_copyright",
            "rights_tier": "in_copyright",
            "rights_evidence": "автор умер в 1951",
            "rights_jurisdiction": "DE",
            "evidence": "автор умер в 1951",
        },
    )


@req(SR, "Источник только с метаданными")
def test_metadata_only_registers_without_files(env):
    entry = metadata_entry(env)
    outcome = env.sync(entry["id"])[entry["id"]]
    assert outcome.code == "metadata"
    source = env.registry.get(outcome.source_id)
    assert source.files == []
    assert env.registry.versions(outcome.source_id) == []
    assert source.rights_tier == "in_copyright"
    assert env.registry.permissions(outcome.source_id)["display"] is False
    pending = env.registry.outbox_pending()
    registered = [p for p in pending if p["kind"] == "source.metadata_registered"]
    assert registered, "нет события source.metadata_registered"
    assert registered[-1]["payload"]["title"] == "Philosophical Investigations"
    assert registered[-1]["payload"]["citations"] == ["Tractatus Logico-Philosophicus"]


@req(SC, "Запись только с метаданными")
def test_metadata_only_requires_abstract_and_in_copyright(env):
    from philograph.library.catalog import model

    entry = metadata_entry(env)
    entry["review"]["status"] = "approved"
    # без аннотации
    entry["override"]["metadata"]["abstract"] = None
    problems = model.validate(env.catalog, year=2026)
    assert any("abstract" in p.message for p in problems)
    # не in_copyright
    entry["override"]["metadata"]["abstract"] = "text"
    entry["license"]["rights_tier"] = "open_license"
    problems = model.validate(env.catalog, year=2026)
    assert any("in_copyright" in p.message for p in problems)
