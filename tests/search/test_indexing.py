"""Требования спецификации paragraph-indexing."""

from __future__ import annotations

import pytest

from philograph.platform import context
from philograph.search import schema as t
from philograph.search.clients import EmbeddingError

req = pytest.mark.req
PI = "paragraph-indexing"


def docs(rig, **where):
    from sqlalchemy import select

    with rig.indexer.engine.begin() as conn:
        rows = conn.execute(select(t.docs)).mappings().all()
    return [r for r in rows if all(r[k] == v for k, v in where.items())]


@req(PI, "Индексация по событиям")
def test_indexing_follows_library_events(rig, events):
    rig.publish("ru")
    indexed = docs(rig, source_id=rig.ids["ru"])
    assert indexed and all(d["embedded"] and d["active"] for d in indexed)
    event = events.one("search.index.event")
    assert event["kind"] == "source.published" and event["indexed"] == len(indexed)

    payload = {
        "event_id": events.of("library.outbox.recorded")[-1]["event_id"],
        "source_id": rig.ids["ru"],
        "version_id": indexed[0]["version_id"],
    }
    calls = len(rig.provider.calls)
    rig.indexer.handle("source.published", payload)  # повтор события
    assert len(rig.provider.calls) == calls and len(docs(rig, source_id=rig.ids["ru"])) == len(
        indexed
    )
    events.one("search.index.duplicate")


@req(PI, "Только изменённое")
def test_only_changed_paragraphs_reembedded(rig, events):
    rig.publish("ru")
    first = sum(len(c) for c in rig.provider.calls)
    rig.files["ru.txt"] = rig.files["ru.txt"].replace(
        "Кантом сформулированы".encode(), "Кантом впервые сформулированы".encode()
    )
    rig.publish("ru")
    second = [t for c in rig.provider.calls[-1:] for t in c]
    assert len(second) == 1 and "впервые" in second[0]
    assert first > 1
    assert events.of("search.index.event")[-1]["embedded"] == 1


@req(PI, "Соблюдение разрешений")
def test_no_external_processing_means_lexical_only(rig, events):
    from philograph.library.registry import License

    rig.registry.change_license("operator", rig.ids["ru"], License("local", "open_license"))
    rig.publish("ru")
    assert rig.provider.calls == []  # провайдер эмбеддингов не вызывался
    indexed = docs(rig, source_id=rig.ids["ru"])
    assert indexed and not any(d["embedded"] for d in indexed)
    assert rig.search("привычка ума")["results"]  # по словам находится
    events.one("search.index.external_forbidden")


@req(PI, "Какие разделы индексируются")
def test_index_section_not_indexed(rig):
    rig.publish("ru")
    assert not [d for d in docs(rig) if "Юм 12, 15" in d["text"]]


@req(PI, "Снятие и удаление")
def test_unpublish_and_republish(rig, events):
    rig.publish("ru")
    assert rig.search("привычка ума")["results"]
    rig.registry.unpublish("operator", rig.ids["ru"])
    rig.sync()
    assert rig.search("привычка ума")["results"] == []

    def index_calls():
        return [c for c in rig.llm.store.calls() if c["operation"] == "index"]

    before = len(index_calls())
    rig.registry.republish("operator", rig.ids["ru"])
    rig.sync()
    assert rig.search("привычка ума")["results"]
    assert len(index_calls()) == before  # эмбеддинги абзацев не пересчитывались

    rig.registry.unpublish("operator", rig.ids["ru"])
    rig.pipeline.delete_source("operator", rig.ids["ru"])
    rig.sync()
    assert docs(rig, source_id=rig.ids["ru"]) == []
    assert [e["kind"] for e in events.of("search.index.event")][-1] == "source.deleted"


@req(PI, "Фрагменты для длинных абзацев")
def test_long_paragraph_chunks_one_result(rig):
    long = " ".join(["Юм пишет о привычке и будущем опыте."] * 12)
    rig.files["ru.txt"] = f"Глава 1\n\n{long}\n".encode()
    rig.publish("ru")
    assert len(rig.provider.calls[-1]) > 1  # абзац разбит на фрагменты
    results = rig.search("будущее и прошлое")["results"]
    assert len([r for r in results if r["source_id"] == rig.ids["ru"]]) == 1


@req(PI, "Версия модели эмбеддингов")
def test_model_switch_builds_side_by_side(rig, events):
    from philograph.search.clients import LlmEmbedder

    rig.publish("ru")
    old = rig.indexer.active_collection
    new_embedder = LlmEmbedder(
        rig.indexer.embedder.client, "concept-v2", rig.indexer.embedder.dimension
    )
    seen_during: list[str] = []
    original = rig.indexer._embed

    def spy(*args, **kwargs):
        seen_during.append(rig.indexer.active_collection)
        return original(*args, **kwargs)

    rig.indexer._embed = spy
    new = rig.indexer.rebuild_with(new_embedder)
    assert seen_during and set(seen_during) == {old}  # до конца построения — старый индекс
    assert rig.indexer.active_collection == new != old
    assert events.one("search.index.switched")["model"] == "concept-v2"


@req(PI, "Стоимость и лимит индексации")
def test_indexing_cost_estimate_and_run_limit(rig, events):
    rig.publish("ru")
    calls = rig.llm.store.calls()
    assert calls and {c["budget"] for c in calls if c["operation"] == "index"} == {"filling"}
    estimate = rig.indexer.estimate()
    assert estimate["paragraphs"] > 0 and estimate["estimate_usd"] > 0
    events.one("search.index.estimate")

    rig.indexer.settings.batch_size = 1
    rig.llm.set_run_limit("run-x", 0.0)
    rig.files["en.txt"] = rig.files["en.txt"] + b"\nAnother paragraph on causation.\n"
    version = rig.pipeline.start("operator", rig.ids["en"])
    rig.registry.publish("operator", version)
    with context.scope(run_id="run-x"), pytest.raises(EmbeddingError) as info:
        rig.indexer.index_version(version)
    assert str(info.value) == "run_limit_exhausted"
    assert events.where("llm.call.rejected", reason="run_limit_exhausted")
    indexed = docs(rig, source_id=rig.ids["en"])
    assert indexed and not any(d["embedded"] for d in indexed)  # по словам уже есть


@req(PI, "Согласованность индексов с библиотекой")
def test_reconcile_after_lost_event(rig, events):
    version = rig.pipeline.start("operator", rig.ids["ru"])
    rig.registry.publish("operator", version)  # событие не передано в очередь
    assert docs(rig) == []
    assert rig.indexer.reconcile() == {"missing": 1, "extra": 0}
    assert docs(rig, source_id=rig.ids["ru"])
    events.one("search.index.reconciled")


@req(PI, "Версия модели эмбеддингов")
def test_dimension_mismatch_fails_before_writing(rig, events):
    """Смена размерности эмбеддера при прежней коллекции: ошибка до записи, без лживой пометки."""
    from dataclasses import dataclass

    from philograph.search.vectors import DimensionMismatch

    rig.publish("ru")  # коллекция paragraphs__concept-v1 с размерностью len(CONCEPTS) + 1

    @dataclass
    class WrongDim:
        model: str = "concept-v1"
        dimension: int = 4
        called: bool = False

        def embed(self, texts, *, budget):
            self.called = True
            return [[0.0] * self.dimension for _ in texts]

    embedder = WrongDim()
    item = {"id": "p-new", "text": "Новый абзац про индукцию.", "hash": "hash-new"}
    data = {
        "source_id": rig.ids["ru"],
        "scope": "public",
        "permissions": {"external_processing": True, "quoting": True},
        "regions": None,
    }
    collection = rig.indexer.active_collection
    with pytest.raises(DimensionMismatch) as info:
        rig.indexer._embed([item], data, embedder, collection)
    assert "7" in str(info.value) and "4" in str(info.value)
    assert embedder.called is False  # размерность проверяется до вызова эмбеддера
    event = events.one("search.index.dimension_mismatch")
    assert event["collection"] == collection
    assert event["collection_dimension"] == 7
    assert event["embedder_dimension"] == 4

    from sqlalchemy import func, select

    with rig.indexer.engine.begin() as conn:
        done = conn.scalar(
            select(func.count())
            .select_from(t.vectors_done)
            .where(t.vectors_done.c.text_hash == "hash-new")
        )
    assert done == 0  # «лживой» записи в vectors_done нет
