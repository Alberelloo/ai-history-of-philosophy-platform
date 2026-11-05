"""Требования спецификаций knowledge-graph и source-scope."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from philograph.knowledge.app import build_app
from philograph.knowledge.cards import Cards
from philograph.knowledge.graph import Graphs, GraphSettings, RecipeNotApplicable
from philograph.knowledge.statements import Attribution, Evidence
from philograph.llm import store as llm_store
from philograph.llm.app import build_app as llm_app
from philograph.llm.config import GatewayConfig
from philograph.llm.gateway import LLMGateway
from philograph.llm.providers import FakeProvider
from philograph.llm.templates import Template, TemplateRegistry
from philograph.platform.client import ServiceClient
from philograph.platform.queue import Queue
from philograph.platform.queue import migrations as queue_migrations
from philograph.prompts import PROMPTS

from ..helpers import asgi_transport

req = pytest.mark.req
KG = "knowledge-graph"
SS = "source-scope"
TEXTBOOK = "s_textbook"


def proposals(*items: tuple[str, str, str]) -> str:
    return json.dumps(
        {"statements": [{"subject": s, "relation": r, "object": o} for s, r, o in items]},
        ensure_ascii=False,
    )


@pytest.fixture
def gx(onto, engine_for, clock):
    ids = {
        "aristotle": onto.person("Аристотель", "384 до н. э.", "322 до н. э."),
        "locke": onto.person("Локк", "1632", "1704"),
        "leibniz": onto.person("Лейбниц", "1646", "1716"),
        "hume": onto.person("Юм", "1711", "1776"),
        "kant": onto.person("Кант", "1724", "1804"),
        "causality": onto.thing("concept", "Причинность"),
        "experience": onto.thing("concept", "Опыт"),
    }
    onto.entities.source_entity(TEXTBOOK, "Учебник N")
    kant_hume = onto.sourced(ids["kant"], "influenced_by", ids["hume"])
    # Та же связь со слов самого Канта, подтверждённая другим источником, — одно утверждение.
    onto.statements.add(
        ids["kant"],
        "influenced_by",
        obj=ids["hume"],
        attributions=[Attribution("entity", ids["kant"])],
        evidence=[Evidence("p1", "Юм пробудил его от догматического сна", source_id="s_other")],
    )
    hume_locke = onto.statements.add(
        ids["hume"],
        "influenced_by",
        obj=ids["locke"],
        attributions=[Attribution("source", "s_other")],
    )
    engine = engine_for(llm_store.migrations, queue_migrations)
    templates = TemplateRegistry()
    for spec in PROMPTS:
        templates.register(Template(spec.name, spec.instructions, spec.data_slots))
    provider = FakeProvider(default=proposals())
    gateway = LLMGateway(
        GatewayConfig.model_validate(
            {
                "providers": {"fake": {"kind": "fake"}},
                "roles": {"main": {"provider": "fake", "model": "flash"}},
                "prices": {
                    "flash": {"input_cache_miss": 0.3, "input_cache_hit": 0.03, "output": 1.2}
                },
                "budgets": {"site": {"daily_limit_usd": 2.0}, "filling": {}},
            }
        ),
        {"fake": provider},
        templates,
        llm_store.Store(engine),
        clock=clock,
    )
    llm = ServiceClient("llm", "http://llm", transport=asgi_transport(llm_app(gateway)))
    queue = Queue(engine, clock)
    graphs = Graphs(onto.statements, llm, queue, GraphSettings(min_edges=5, max_nodes=60))

    def build(entity, recipe="genesis", **kw):
        return list(graphs.build(ids.get(entity, entity), recipe, **kw))

    return type(
        "GX",
        (),
        {
            "onto": onto,
            "ids": ids,
            "graphs": graphs,
            "provider": provider,
            "queue": queue,
            "build": staticmethod(build),
            "kant_hume": kant_hume,
            "hume_locke": hume_locke,
            "llm": llm,
        },
    )


def graph_of(items):
    graph = next(i for i in items if i["type"] == "graph")
    edges = graph["edges"] + [i["edge"] for i in items if i["type"] == "edge"]
    return graph, edges


def failing_llm(status: int | None = None, kind: str = "") -> ServiceClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if status is None:
            raise httpx.ConnectError("нет связи", request=request)
        return httpx.Response(status, json={"error": "x", "kind": kind})

    return ServiceClient("llm", "http://llm", transport=httpx.MockTransport(handler), retries=0)


# --- knowledge-graph ---------------------------------------------------------------


@req(KG, "Запрос графа")
def test_recipes_by_type_and_not_applicable(gx, events):
    concept = {r["code"] for r in gx.graphs.recipes_for(gx.ids["causality"])}
    assert {"genesis", "consequences", "conceptions"} <= concept and "path" not in concept
    person = {r["code"] for r in gx.graphs.recipes_for(gx.ids["kant"])}
    assert "answers" not in person
    with pytest.raises(RecipeNotApplicable) as exc:
        gx.build("kant", "answers")
    assert {s["code"] for s in exc.value.suggestions} == person
    client = TestClient(build_app(gx.onto.statements, graphs=gx.graphs))
    response = client.post(
        "/v1/graph/build", json={"entity_id": gx.ids["kant"], "recipe": "answers"}
    )
    assert response.status_code == 400 and response.json()["kind"] == "recipe_not_applicable"
    assert {s["code"] for s in response.json()["suggestions"]} == person
    graph, _ = graph_of(gx.build("causality", generation=False))
    assert graph["recipe"]["code"] == "genesis" and graph["nodes"][0]["id"] == gx.ids["causality"]


@req(KG, "Сохранённые связи сразу")
def test_saved_edges_first_without_model(gx, events):
    gx.graphs.llm = failing_llm()
    stream = gx.graphs.build(gx.ids["kant"], "genesis")
    first = next(stream)
    assert first["type"] == "graph" and len(first["edges"]) == 2 and first["extension"] == "pending"
    assert gx.provider.calls == []  # модель ещё не вызывалась
    rest = list(stream)
    assert rest[0] == {
        "type": "notice",
        "extension": "unavailable",
        "message": "Достройка временно недоступна, показаны сохранённые связи.",
    }
    assert events.where("knowledge.graph.built", edges=2, extension="pending")


@req(KG, "Достройка")
def test_extension_only_recipe_types_and_integrity(gx, events):
    gx.provider.push(
        proposals(
            ("Кант", "develops", "Лейбниц"),  # годится
            ("Кант", "lived_in", "Юм"),  # тип вне рецепта
            ("Кант", "influenced_by", "Мальбранш"),  # такой сущности нет
            ("Локк", "influenced_by", "Кант"),  # против времени: Локк умер до рождения Канта
            ("Юм", "influenced_by", "Локк"),  # уже сохранено
            ("Аристотель", "influenced_by", "Причинность"),  # не касается узлов графа
        )
    )
    items = gx.build("kant")
    assert [i["type"] for i in items] == ["graph", "edge", "done"]
    added = items[1]
    assert added["edge"]["type"] == "develops" and added["edge"]["generated"]
    assert [n["id"] for n in added["nodes"]] == [gx.ids["leibniz"]]  # новый узел вместе со связью
    reasons = sorted(e["reason"] for e in events.where("knowledge.graph.proposal_dropped"))
    assert reasons == [
        "disconnected",
        "exists",
        "integrity:influence_against_time",
        "outside_recipe",
        "unknown_entity",
    ]
    assert events.where("knowledge.graph.extended", proposed=1, dropped=5)
    request = gx.provider.calls[-1]
    assert request.template == "graph.extend" and "lived_in" not in request.messages[-1].content


@req(KG, "Пометка достроенного")
def test_generated_mark_survives_rebuild_and_depth(gx):
    gx.provider.push(proposals(("Кант", "develops", "Лейбниц")))
    _, first = graph_of(gx.build("kant"))
    proposed = next(e for e in first if e["type"] == "develops")
    assert proposed["generated"] and proposed["pending"] and proposed["evidence"] == []
    gx.queue.run_until_empty()
    for depth in (1, 3):
        _, edges = graph_of(gx.build("kant", depth=depth))
        saved = next(e for e in edges if e["type"] == "develops")
        assert saved["generated"] and not saved["pending"] and saved["status"] == "generated"
        assert saved["attributions"] == [] and saved["evidence"] == []


@req(KG, "Отложенное сохранение")
def test_deferred_save_and_no_regeneration(gx, events):
    rejected = gx.onto.statements.add(gx.ids["kant"], "borrows", obj=gx.ids["leibniz"])
    gx.onto.statements.reject(rejected, "operator")
    gx.provider.push(proposals(("Кант", "develops", "Лейбниц"), ("Кант", "borrows", "Лейбниц")))
    _, edges = graph_of(gx.build("kant"))
    assert [e["type"] for e in edges if e["pending"]] == ["develops"]
    assert events.where("knowledge.graph.proposal_dropped", reason="rejected_before")
    assert gx.queue.run_until_empty() == 1
    saved = events.where("knowledge.graph.saved", statements=1)
    assert saved
    stored = gx.onto.statements.about(gx.ids["kant"], types=["develops"])[0]
    assert stored["status"] == "generated"
    assert stored["provenance"]["template"] == "graph.extend"
    calls = len(gx.provider.calls)
    graph, edges = graph_of(gx.build("kant"))
    assert graph["extension"] == "done_before" and len(gx.provider.calls) == calls
    assert any(e["type"] == "develops" and not e["pending"] for e in edges)


@req(KG, "Без достройки при выключенной генерации")
def test_no_extension_when_disabled_or_limit(gx):
    graph, _ = graph_of(gx.build("kant", generation=False))
    assert graph["extension"] == "disabled" and gx.provider.calls == []
    assert graph["notice"] == "Достройка моделью выключена в настройках."
    gx.graphs.llm = failing_llm(429, "budget_exhausted")
    items = gx.build("kant")
    assert items[1]["extension"] == "limit" and "лимит" in items[1]["message"]


@req(KG, "Показ графа")
def test_nodes_typed_and_ordered_by_time(gx):
    aristotle = gx.onto.statements.add(
        gx.ids["locke"],
        "influenced_by",
        obj=gx.ids["aristotle"],
        attributions=[Attribution("common")],
    )
    rejected = gx.onto.statements.add(
        gx.ids["hume"], "influenced_by", obj=gx.ids["leibniz"], attributions=[Attribution("common")]
    )
    gx.onto.statements.reject(rejected, "operator")
    deprecated = gx.onto.statements.add(
        gx.ids["kant"], "borrows", obj=gx.ids["locke"], attributions=[Attribution("common")]
    )
    gx.onto.statements.set_rank(deprecated, "deprecated", "operator")
    graph, edges = graph_of(gx.build("kant", generation=False))
    order = [n["label"] for n in graph["nodes"]]
    assert order == ["Аристотель", "Локк", "Юм", "Кант"]
    assert graph["recipe"]["order"] == "time"
    assert {n["type"] for n in graph["nodes"]} == {"person"}
    assert graph["nodes"][0]["year"] < 0  # до нашей эры
    shown = {e["id"] for e in edges}
    assert aristotle in shown and rejected not in shown and deprecated not in shown


@req(KG, "Подробности связи")
def test_edge_details(gx):
    _, edges = graph_of(gx.build("kant", generation=False, textbook=TEXTBOOK))
    edge = next(e for e in edges if e["id"] == gx.kant_hume)
    assert edge["title"] == "испытал влияние" and edge["status"] == "sourced"
    assert {a["who"] for a in edge["attributions"]} == {"Учебник N", "Кант"}
    quotes = {e["quote"] for e in edge["evidence"]}
    assert quotes == {"Кант испытал влияние Юма", "Юм пробудил его от догматического сна"}
    assert all(e["link"] == f"/p/{e['paragraph_id']}" for e in edge["evidence"])
    assert edge["consensus"] and edge["qualifiers"] == {}


@req(KG, "Ограничение размера")
def test_size_limit_and_expand(gx, events):
    gx.onto.statements.add(
        gx.ids["locke"],
        "influenced_by",
        obj=gx.ids["aristotle"],
        attributions=[Attribution("common")],
    )
    gx.graphs.settings = GraphSettings(min_edges=5, max_nodes=2)
    graph, _ = graph_of(gx.build("kant", generation=False))
    assert graph["truncated"] and [n["label"] for n in graph["nodes"]] == ["Юм", "Кант"]
    assert events.where("knowledge.graph.built", truncated=True)
    # Раскрытие узла — граф от него: читатель видит, что было за пределом.
    expanded, _ = graph_of(gx.build("hume", generation=False, depth=1))
    assert "Локк" in [n["label"] for n in expanded["nodes"]]


@req(KG, "Пустой граф")
def test_empty_graph_offers_ways_out(gx):
    graph, edges = graph_of(gx.build("experience", generation=False))
    assert edges == [] and graph["extension"] == "disabled"
    assert {r["code"] for r in graph["recipes"]} >= {"genesis", "polemic"}  # другой рецепт


# --- source-scope ------------------------------------------------------------------


@req(SS, "Фильтр по атрибуции")
def test_textbook_only_filters_graph_and_card(gx):
    _, edges = graph_of(gx.build("kant", textbook=TEXTBOOK, only_textbook=True))
    assert [e["id"] for e in edges] == [gx.kant_hume]
    cards = Cards(gx.onto.statements)
    card = cards.card(gx.ids["hume"], attributed_to=TEXTBOOK)
    rows = [r["statement_id"] for s in card["sections"] for r in s["rows"]]
    assert gx.kant_hume in rows and gx.hume_locke not in rows


@req(SS, "Достройка в режиме учебника")
def test_no_extension_in_textbook_mode(gx):
    graph, _ = graph_of(gx.build("kant", textbook=TEXTBOOK, only_textbook=True))
    assert graph["extension"] == "scope" and gx.provider.calls == []
    assert "только выбранный учебник" in graph["notice"]


@req(SS, "Сравнение с другими")
def test_in_textbook_marks(gx):
    _, edges = graph_of(gx.build("kant", generation=False, textbook=TEXTBOOK))
    marks = {e["id"]: e["in_textbook"] for e in edges}
    assert marks == {gx.kant_hume: True, gx.hume_locke: False}
    card = Cards(gx.onto.statements).card(gx.ids["hume"], textbook=TEXTBOOK)
    rows = {r["statement_id"]: r["in_textbook"] for s in card["sections"] for r in s["rows"]}
    assert rows[gx.kant_hume] is True and rows[gx.hume_locke] is False
    assert (
        Cards(gx.onto.statements).card(gx.ids["hume"])["sections"][0]["rows"][0]["in_textbook"]
        is None
    )
