"""Сервис знаний как сосед: HTTP-интерфейс и события библиотеки через очередь."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from philograph.knowledge.app import build_app, library_paragraphs, subscribe
from philograph.knowledge.assist import STEPS, AssistantKnowledge
from philograph.knowledge.mentions import Mentions
from philograph.knowledge.statements import Attribution, Evidence, Provenance
from philograph.library.app import build_app as library_app
from philograph.library.reading import Reading
from philograph.platform.client import ServiceClient
from philograph.platform.queue import Queue
from philograph.platform.queue import migrations as queue_migrations

from ..helpers import asgi_transport
from ..library.conftest import lib  # noqa: F401

req = pytest.mark.req


@req("ontology-statements", "Реакция на изменения библиотеки")
def test_library_publication_reaches_ontology_via_queue(onto, lib, engine_for, clock, events):
    source = lib.register()
    lib.publish_new(source)
    library = ServiceClient(
        "library",
        "http://library/api",
        transport=asgi_transport(library_app(Reading(lib.registry, lib.registry.engine))),
    )
    onto.statements.paragraph_text = library_paragraphs(library)
    doc = lib.registry.load_document(lib.registry.get(source).published_version)
    paragraph = next(b for _, b in doc.blocks() if "Рассудок даёт" in b.text)
    kant, reason = onto.person("Кант"), onto.thing("concept", "Рассудок")
    sid = onto.statements.add(
        kant,
        "advanced",
        obj=onto.thing("position", "Рассудок даёт правила"),
        attributions=[Attribution("source", source)],
        evidence=[Evidence(paragraph.id, "Рассудок даёт правила", source_id=source)],
        provenance=Provenance("extracted"),
    )
    lib.files["book.txt"] = lib.files["book.txt"].replace(
        "Рассудок даёт правила явлениям.".encode(), "Совсем другой текст о Гегеле и духе.".encode()
    )
    lib.publish_new(source)
    queue = Queue(engine_for(queue_migrations), clock)
    subscribe(queue, onto.statements)
    lib.pipeline.dispatch_outbox(queue)
    queue.run_until_empty()
    statement = onto.statements.get(sid)
    assert statement["evidence"][0]["lost"] and statement["status"] == "generated"
    assert events.where("knowledge.library.event", kind="source.published")
    assert reason


@req("ontology-statements", "Запрос утверждений о сущности")
def test_http_interface(onto):
    kant, hume = onto.person("Кант", "1724", "1804"), onto.person("Юм", "1711", "1776")
    onto.statements.add(kant, "criticizes", obj=hume, attributions=[Attribution("common")])
    client = TestClient(build_app(onto.statements))
    assert client.get("/v1/entities", params={"name": "кант"}).json()[0]["id"] == kant
    about = client.get(f"/v1/entities/{hume}/statements").json()
    assert next(s for s in about if s["type"] == "criticizes")["direction"] == "in"
    graph = client.get("/v1/graph", params={"recipe": "genesis", "start": kant}).json()
    assert [n["id"] for n in graph["nodes"]] == [hume, kant]
    wrong = client.get("/v1/graph", params={"recipe": "answers", "start": kant})
    assert wrong.status_code == 400 and wrong.json()["kind"] == "recipe_not_applicable"


@req("regional-access", "Онтология не раскрывает текст закрытых источников")
def test_assistant_context_without_closed_source_paragraph(onto):
    """6.4: контекст ассистента не несёт текст абзацев закрытых для региона источников."""

    def unused(request: httpx.Request) -> httpx.Response:
        raise AssertionError("библиотека в этом тесте не вызывается")

    library = ServiceClient("library", "http://library", transport=httpx.MockTransport(unused))
    kant, hume = onto.person("Кант", "1724", "1804"), onto.person("Юм", "1711", "1776")
    onto.statements.add(
        kant,
        "influenced_by",
        obj=hume,
        attributions=[Attribution("source", "s_closed")],
        evidence=[Evidence("p1", "Юм пробудил его от догматического сна", source_id="s_closed")],
    )
    onto.statements.add(
        kant,
        "influenced_by",
        obj=hume,
        attributions=[Attribution("source", "s_open")],
        evidence=[Evidence("p2", "Кант испытал влияние Юма", source_id="s_open")],
    )
    assistant = AssistantKnowledge(onto.statements, Mentions(onto.statements, library))
    context = assistant.context(
        text="Кант",
        names=[],
        paragraphs=[],
        steps=list(STEPS),
        recipe="genesis",
        closed={"s_closed"},
    )
    assert {p["paragraph_id"] for p in context["paragraphs"]} == {"p2"}
    for statement in context["statements"]:
        assert "s_closed" not in statement["sources"]
        assert all(e["source_id"] != "s_closed" for e in statement["evidence"])
