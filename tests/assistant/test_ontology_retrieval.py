"""Требования спецификации ontology-retrieval.

Стенд ассистента (настоящие библиотека, поиск и сервис LLM) дополнен настоящим сервисом
знаний поверх той же библиотеки: сущности, утверждения и упоминания в главах учебника.
"""

from __future__ import annotations

import re

import httpx
import pytest

from philograph.assistant.ontology import KnowledgeHttp, Ontology, OntologySteps
from philograph.knowledge import schema as knowledge_schema
from philograph.knowledge.app import build_app as knowledge_app
from philograph.knowledge.app import library_paragraphs
from philograph.knowledge.assist import AssistantKnowledge
from philograph.knowledge.dates import lifespan, parse
from philograph.knowledge.entities import Entities
from philograph.knowledge.mentions import Mentions
from philograph.knowledge.registry import OntologyRegistry
from philograph.knowledge.statements import Attribution, Evidence, Provenance, Statements
from philograph.platform.client import ServiceClient

from ..helpers import asgi_transport

req = pytest.mark.req
OR = "ontology-retrieval"


class Recorder:
    """Поиск, который запоминает запросы ассистента."""

    def __init__(self, search) -> None:
        self.inner = search
        self.queries: list[dict] = []
        self.results: list[list[dict]] = []

    def search(self, **query):
        self.queries.append(query)
        found = self.inner.search(**query)
        self.results.append(found["results"])
        return found


@pytest.fixture
def ob(bot, engine_for, clock):
    rig = bot.rig
    library = rig.indexer.library.client
    engine = engine_for(knowledge_schema.migrations)
    registry = OntologyRegistry(engine, clock)
    registry.load_defaults()
    entities = Entities(engine, registry)
    statements = Statements(engine, registry, entities, library_paragraphs(library), clock)
    textbook = rig.ids["ru"]
    entities.source_entity(textbook, "Теория познания")
    ids = {}

    def person(key, name, birth, death, *variants):
        ids[key] = entities.create(
            "person", [("ru", name, "primary"), *[("ru", v, "variant") for v in variants]]
        )
        statements.add(ids[key], "lifespan", value=lifespan(birth, death).to_json())

    person("hume", "Юм", "1711", "1776", "Хьюм")
    person("kant", "Кант", "1724", "1804")
    person("locke", "Локк", "1632", "1704")
    person("aristotle", "Аристотель", "384 до н. э.", "322 до н. э.")
    ids["habit"] = entities.create("concept", [("ru", "Привычка", "primary")])
    ids["understanding"] = entities.create(
        "concept",
        [
            ("ru", "Рассудок", "primary"),
            ("de", "Verstand", "original"),
            ("en", "understanding", "variant"),
        ],
    )
    ids["critique"] = entities.create("work", [("ru", "Критика чистого разума", "primary")])
    statements.add(ids["critique"], "dating", value=parse("1781").to_json())  # проверено
    statements.add(ids["critique"], "author", obj=ids["kant"])
    answer = rig.paragraph("ru", "Кант отвечает Юму")
    ids["kant_hume"] = statements.add(
        ids["kant"],
        "influenced_by",
        obj=ids["hume"],
        attributions=[Attribution("source", textbook)],
        evidence=[Evidence(answer, "Кант отвечает Юму", source_id=textbook)],
        provenance=Provenance("extracted"),
    )
    ids["hume_locke"] = statements.add(
        ids["hume"], "influenced_by", obj=ids["locke"], attributions=[Attribution("common")]
    )
    ids["generated"] = statements.add(
        ids["kant"], "develops", obj=ids["aristotle"], provenance=Provenance("generated")
    )
    mentions = Mentions(statements, library)
    mentions.index_version(rig.registry.get(textbook).published_version)
    knowledge = ServiceClient(
        "knowledge",
        "http://knowledge",
        transport=asgi_transport(
            knowledge_app(statements, assistant=AssistantKnowledge(statements, mentions))
        ),
    )
    bot.assistant.ontology = Ontology(KnowledgeHttp(knowledge))
    recorder = Recorder(bot.assistant.search)
    bot.assistant.search = recorder

    def prompt() -> str:
        return bot.model.requests[-1].messages[-1].content

    def block(name: str) -> str:
        match = re.search(rf'<data name="{name}">\n(.*?)\n</data>', prompt(), re.S)
        return match.group(1) if match else ""

    def number(needle: str) -> int:
        return int(re.search(rf"\[(\d+)\] [^\n]*{re.escape(needle)}", prompt()).group(1))

    return type(
        "OB",
        (),
        {
            "bot": bot,
            "ids": ids,
            "statements": statements,
            "entities": entities,
            "mentions": mentions,
            "search": recorder,
            "block": staticmethod(block),
            "number": staticmethod(number),
            "prompt": staticmethod(prompt),
            "knowledge": AssistantKnowledge(statements, mentions),
            "textbook": textbook,
        },
    )


def answer_with(ob, make):
    """Ответ модели строится по фактическому запросу: номера абзацев и утверждений."""
    ob.bot.model.answers.append(lambda prompt: [make(prompt)])


def fragments(items):
    return [i for i in items if i["type"] == "fragment"]


@req(OR, "Сущности вопроса")
def test_entities_of_question_and_ambiguity(ob, events):
    ob.bot.ask(question="что Хьюм говорил о привычке?")
    used = events.one("assistant.ontology.used")
    assert {"Юм", "Привычка"} <= set(used["entities"])
    # Неоднозначное название: без главы — оба кандидата с пониженным весом, в главе — один.
    other = ob.entities.create("person", [("ru", "Локк", "primary")])
    ob.statements.add(other, "lifespan", value=lifespan("1900", "1990").to_json())
    ob.statements.add(ob.ids["locke"], "borrows", obj=ob.ids["aristotle"])
    ob.mentions.index_version(
        ob.bot.rig.registry.get(ob.textbook).published_version
    )  # Аристотель упомянут в главе о Локке
    loose = {e["id"]: e["weight"] for e in ob.knowledge.resolve("что Локк думал об уме?", [], [])}
    assert loose == {ob.ids["locke"]: 0.5, other: 0.5}
    in_chapter = ob.knowledge.resolve("что Локк думал об уме?", [], [ob.bot.para("tabula rasa")])
    weights = {e["id"]: e["weight"] for e in in_chapter}
    assert weights.get(ob.ids["locke"]) == 1.0 and other not in weights


@req(OR, "Расширение запроса")
def test_query_expanded_with_names_and_translations(ob, events):
    ob.bot.ask(question="что Кант называл рассудком?")
    terms = events.one("assistant.ontology.expanded")["terms"]
    assert {"Verstand", "understanding"} <= set(terms)
    assert {"Verstand", "understanding"} <= set(ob.search.queries[-1]["extra_terms"])


@req(OR, "Приоритет абзацев по упоминаниям")
def test_paragraphs_with_mentions_first(ob):
    ob.bot.assistant.ontology = Ontology(
        ob.bot.assistant.ontology.knowledge, OntologySteps.parse("none")
    )
    ob.bot.ask(question="причинность и категория рассудка у Юма")
    plain = [r["paragraph_id"] for r in ob.search.results[-1]]
    ob.bot.assistant.ontology = Ontology(
        ob.bot.assistant.ontology.knowledge, OntologySteps.parse("priority")
    )
    ob.bot.ask(question="причинность и категория рассудка у Юма")
    query = ob.search.queries[-1]
    hume = set(ob.mentions.paragraphs_of([ob.ids["hume"]]))
    assert hume <= set(query["priority"])
    boosted = [r["paragraph_id"] for r in ob.search.results[-1]]
    first_plain = next(i for i, p in enumerate(plain) if p in hume)
    first_boosted = next(i for i, p in enumerate(boosted) if p in hume)
    assert first_boosted <= first_plain and boosted[0] in hume


@req(OR, "Утверждения в контексте")
def test_statements_cited_and_generated_not_grounding(ob):
    answer_with(
        ob,
        lambda prompt: (
            f"Кант испытал влияние Юма [{ob.number('Кант — испытал влияние — Юм')}]. "
            f"Кант развивал Аристотеля [{ob.number('Кант — развивает — Аристотель')}]."
        ),
    )
    items = ob.bot.ask(question="как Кант связан с Юмом и Аристотелем?")
    statements = ob.block("statements")
    assert (
        "Кант — испытал влияние — Юм (так считает: Теория познания; статус: по источникам)"
        in statements
    )
    assert (
        "Кант — развивает — Аристотель (так считает: не указано; статус: сгенерировано)"
        in statements
    )
    sourced, generated = fragments(items)
    assert sourced["grounded"] is True
    citation = sourced["citations"][0]
    assert citation["kind"] == "statement" and citation["statement_id"] == ob.ids["kant_hume"]
    assert citation["paragraph_id"] == ob.bot.para("Кант отвечает Юму")
    assert generated["grounded"] is False  # сгенерированное не подтверждает


@req(OR, "Другие авторы через атрибуцию")
def test_other_authors_grouped_by_source(ob):
    ob.bot.model.routes.append({"type": "other_authors", "confidence": 0.9, "names": ["Локк"]})
    ob.bot.ask(question="как разные учебники описывают чистую доску Локка?")
    passages = ob.block("passages")
    headers = re.findall(r"^Источник: (.+)$", passages, re.M)
    assert sorted(headers) == ["Empiricism", "Теория познания"]  # по источникам, без повторов
    for title, part in zip(
        headers, re.split(r"^Источник: .+$", passages, flags=re.M)[1:], strict=True
    ):
        expected = "blank slate" if title == "Empiricism" else "чистой доской"
        assert expected in part


@req(OR, "Генезис и контекст через рецепты")
def test_genesis_line_by_time_and_graph_suggestion(ob):
    ob.bot.model.routes.append({"type": "genesis", "confidence": 0.9, "names": ["Кант"]})
    answer_with(
        ob,
        lambda prompt: f"Линия идёт от Локка к Юму [{ob.number('Юм — испытал влияние — Локк')}].",
    )
    items = ob.bot.ask(question="откуда взялась идея Канта о причинности?")
    lines = ob.block("statements").splitlines()
    order = [i for i, line in enumerate(lines) if "испытал влияние" in line]
    assert "Юм — испытал влияние — Локк" in lines[order[0]]  # раньше по времени
    assert "Кант — испытал влияние — Юм" in lines[order[1]]
    assert "Кант отвечает Юму" in ob.block("passages")  # подтверждающий абзац линии
    suggestion = next(i for i in items if i["type"] == "suggestion")
    assert suggestion["recipe"] == "genesis" and suggestion["entity_id"] == ob.ids["kant"]


@req(OR, "Проверка ответа по онтологии")
def test_answer_checked_against_verified_dates(ob, events):
    answer_with(
        ob,
        lambda prompt: (
            "«Критика чистого разума» вышла в 1790 году. "
            "Кант написал «Критику чистого разума» в 1781 году. "
            "Кант повлиял на Локка."
        ),
    )
    items = ob.bot.ask(
        question="когда вышла Критика чистого разума Канта и как он связан с Локком?"
    )
    wrong, right, influence = fragments(items)
    assert (
        wrong["contradicts"][0]["kind"] == "date" and wrong["contradicts"][0]["expected"] == "1781"
    )
    assert wrong["grounded"] is False
    assert right["contradicts"] == []
    assert influence["contradicts"][0]["kind"] == "influence_against_time"
    logged = events.of("assistant.ontology.contradiction")
    assert {e["kind"] for e in logged} == {"date", "influence_against_time"}


@req(OR, "Включение шагов по отдельности")
def test_steps_enabled_separately(ob, events):
    ob.bot.assistant.ontology = Ontology(
        ob.bot.assistant.ontology.knowledge, OntologySteps.parse("expansion")
    )
    ob.bot.ask(question="что Кант называл рассудком?")
    assert events.one("assistant.ontology.used")["steps"] == ["expansion"]
    assert "Verstand" in ob.search.queries[-1]["extra_terms"]
    assert ob.block("statements") == ""  # утверждения модели не переданы
    with pytest.raises(ValueError):
        OntologySteps.parse("expansion,magic")


@req(OR, "Без онтологии при сбое")
def test_answers_without_ontology_when_knowledge_down(ob, events):
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет связи", request=request)

    ob.bot.assistant.ontology = Ontology(
        KnowledgeHttp(
            ServiceClient(
                "knowledge", "http://knowledge", transport=httpx.MockTransport(down), retries=0
            )
        )
    )
    items = ob.bot.ask(question="что Юм думал о причинности?")
    assert items[-1]["type"] == "done"
    assert events.one("assistant.ontology.skipped")["reason"] == "knowledge_unavailable"
    assert not events.of("assistant.ontology.used")


def _kant_statement_answer(ob):
    answer_with(ob, lambda prompt: f"Кант испытал влияние Юма [{ob.number('влияние — Юм')}]. ")
    items = ob.bot.ask(question="как Кант связан с Юмом и Аристотелем?")
    return next(c for f in fragments(items) for c in f["citations"] if c["kind"] == "statement")


@req("answer-grounding", "Ссылки на абзацы")
def test_statement_citation_carries_entity_id(ob):
    """N5: entity_id утверждения доходит до ссылки — по нему клиент откроет карточку (5.4)."""
    knowledge = ob.bot.assistant.ontology.knowledge
    original = knowledge.context

    def with_subject(**body):
        data = original(**body)
        for s in data["statements"]:
            s.setdefault("entity_id", ob.ids["kant"])
        return data

    knowledge.context = with_subject
    citation = _kant_statement_answer(ob)
    assert citation["statement_id"] == ob.ids["kant_hume"]
    assert citation["entity_id"] == ob.ids["kant"]


@req("answer-grounding", "Ссылки на абзацы")
def test_knowledge_service_sends_statement_entity_id(ob):
    """N5 по настоящему сервису знаний: у ссылки на утверждение — сущность-подлежащее."""
    assert _kant_statement_answer(ob)["entity_id"] == ob.ids["kant"]
