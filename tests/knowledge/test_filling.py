"""Требования спецификаций ontology-extraction и ontology-review."""

from __future__ import annotations

import json
from collections import deque

import pytest
from fastapi.testclient import TestClient

from philograph.knowledge.app import build_app, library_paragraphs, subscribe
from philograph.knowledge.filling import Filling
from philograph.knowledge.review import Priority, Review
from philograph.knowledge.statements import Attribution, Provenance
from philograph.library.app import build_app as library_app
from philograph.library.reading import Reading
from philograph.library.registry import License
from philograph.llm import store as llm_store
from philograph.llm.app import build_app as llm_app
from philograph.llm.config import GatewayConfig
from philograph.llm.gateway import LLMGateway
from philograph.llm.providers import Completion, FakeProvider, Usage
from philograph.llm.templates import Template, TemplateRegistry
from philograph.operator.access import SESSION_COOKIE, ActionLog, OperatorAuth, hash_password
from philograph.operator.access import migrations as operator_migrations
from philograph.platform.client import ServiceClient
from philograph.platform.queue import Queue
from philograph.platform.queue import migrations as queue_migrations
from philograph.prompts import PROMPTS

from ..helpers import asgi_transport
from ..library.conftest import lib  # noqa: F401

req = pytest.mark.req
EX = "ontology-extraction"
RV = "ontology-review"


class Scripted(FakeProvider):
    """Структурированные ответы по очереди; пусто — нет утверждений."""

    def __init__(self) -> None:
        super().__init__()
        self.replies: deque = deque()

    def generate(self, request):
        self.calls.append(request)
        reply = self.replies.popleft() if self.replies else {"statements": []}
        return Completion(
            reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False),
            Usage(1000, 0, 200),
        )


CONFIG = {
    "providers": {"fake": {"kind": "fake"}},
    "roles": {r: {"provider": "fake", "model": "flash"} for r in ("main", "strong")},
    "prices": {"flash": {"input_cache_miss": 0.3, "input_cache_hit": 0.03, "output": 1.2}},
    "retry_base_seconds": 0.0,
    "schema_retries": 0,
}


def st(subject, type_, obj, paragraph, quote, **extra):
    return {
        "subject": subject,
        "subject_type": extra.pop("subject_type", "person"),
        "type": type_,
        "object": obj,
        "object_type": extra.pop("object_type", "position"),
        "paragraph": paragraph,
        "quote": quote,
        **extra,
    }


@pytest.fixture
def fill(onto, lib, engine_for, clock):
    engine = engine_for(llm_store.migrations, queue_migrations, operator_migrations)
    templates = TemplateRegistry()
    for spec in PROMPTS:
        templates.register(Template(spec.name, spec.instructions, spec.data_slots))
    model = Scripted()
    gateway = LLMGateway(
        GatewayConfig.model_validate(CONFIG),
        {"fake": model},
        templates,
        llm_store.Store(engine),
        clock=clock,
        sleep=lambda _s: None,
    )
    llm = ServiceClient("llm", "http://llm", transport=asgi_transport(llm_app(gateway)))
    library = ServiceClient(
        "library",
        "http://library/api",
        transport=asgi_transport(library_app(Reading(lib.registry, lib.registry.engine))),
    )
    onto.statements.paragraph_text = library_paragraphs(library)
    filling = Filling(onto.statements, llm, library, clock=clock, fragment_size=2)
    queue = Queue(engine, clock)
    subscribe(queue, onto.statements, filling)

    def publish(source_id):
        lib.publish_new(source_id)
        lib.pipeline.dispatch_outbox(queue)
        queue.run_until_empty()

    review = Review(onto.statements, ActionLog(engine, clock))
    return type(
        "Fill",
        (),
        {
            "onto": onto,
            "lib": lib,
            "model": model,
            "filling": filling,
            "publish": publish,
            "queue": queue,
            "review": review,
            "gateway": gateway,
            "engine": engine,
        },
    )


def _all(fill):
    from sqlalchemy import select

    from philograph.knowledge import schema as t

    with fill.onto.statements.engine.begin() as conn:
        ids = list(conn.scalars(select(t.statements.c.id)))
    return [fill.onto.statements.get(i) for i in ids]


# --- ontology-extraction -------------------------------------------------------------


@req(EX, "Извлечение по событиям библиотеки")
def test_extraction_on_publication_only_changed(fill, events):
    source = fill.lib.register()
    fill.model.replies.append(
        {
            "statements": [
                st(
                    "Кант",
                    "holds",
                    "Всякое знание начинается с опыта",
                    1,
                    "Всякое знание начинается с опыта",
                )
            ]
        }
    )
    fill.publish(source)
    assert len(_all(fill)) == 1
    first_calls = len(fill.model.calls)
    fill.lib.files["book.txt"] = fill.lib.files["book.txt"].replace(
        "Рассудок даёт правила явлениям.".encode(),
        "Рассудок даёт правила явлениям природы.".encode(),
    )
    fill.publish(source)
    assert len(fill.model.calls) - first_calls == 1  # только фрагмент с изменённым абзацем
    forbidden = fill.lib.register(
        title="Без внешней обработки",
        license=License("cc-by", "open_license", narrowed={"external_processing": False}),
    )
    fill.publish(forbidden)
    assert events.where("knowledge.extraction.skipped", reason="external_processing_forbidden")


@req(EX, "Фрагменты из нескольких абзацев")
def test_overlapping_fragments_no_duplicates(fill):
    paragraphs = [
        {"id": f"p{i}", "chapter_id": "c1", "text": "t", "searchable": True} for i in range(5)
    ]
    windows = fill.filling.fragments(paragraphs, None)
    assert [[p["id"] for p in w] for w in windows] == [
        ["p0", "p1"],
        ["p1", "p2"],
        ["p2", "p3"],
        ["p3", "p4"],
    ]
    source = fill.lib.register()
    shared = st("Кант", "holds", "Опыт", 2, "Но не всё оно происходит из опыта")
    fill.model.replies.extend(
        [{"statements": [shared]}, {"statements": [{**shared, "paragraph": 1}]}]
    )
    fill.publish(source)
    assert len([s for s in _all(fill) if s["type"] == "holds"]) == 1


@req(EX, "Структурированный вывод по реестру")
def test_general_type_and_schema_mismatch(fill, events):
    source = fill.lib.register()
    fill.model.replies.extend(
        [
            {
                "statements": [
                    st(
                        "Кант",
                        "studied_with",
                        "Всякое знание начинается с опыта",
                        1,
                        "Всякое знание начинается с опыта",
                    )
                ]
            },
            "{не JSON",
        ]
    )
    fill.publish(source)
    kinds = {s["type"] for s in _all(fill)}
    assert kinds == {"influenced_by"}  # частный тип не подошёл концам — общий
    assert events.where("knowledge.extraction.dropped")
    schema = fill.filling._schema()["properties"]["statements"]["items"]["properties"]
    assert "lived_in" in schema["type"]["enum"] and "lifespan" not in schema["type"]["enum"]


@req(EX, "Цитата у каждого утверждения")
def test_quote_must_exist(fill, events):
    source = fill.lib.register()
    fill.model.replies.append(
        {"statements": [st("Кант", "holds", "Опыт", 1, "Кант это никогда не писал")]}
    )
    fill.publish(source)
    assert _all(fill) == []
    assert any(
        "цитата не найдена" in e["reason"] for e in events.of("knowledge.extraction.dropped")
    )


@req(EX, "Атрибуция при извлечении")
def test_attribution_to_quoted_author(fill):
    source = fill.lib.register()
    fill.model.replies.append(
        {
            "statements": [
                st(
                    "Кант",
                    "holds",
                    "Знание начинается с опыта",
                    1,
                    "говорит Кант",
                    attributed_to="Кант",
                    stance="asserts",
                )
            ]
        }
    )
    fill.publish(source)
    attributions = _all(fill)[0]["attributions"]
    assert {(a["who_kind"], a["stance"]) for a in attributions} == {
        ("entity", "asserts"),
        ("source", "mentions"),
    }


@req(EX, "Нормализация сущностей")
def test_entity_resolution(fill, events):
    hume = fill.onto.person("Юм")
    fill.onto.entities.add_name(hume, "ru", "Хьюм")
    fill.onto.person("Бэкон", "1214", "1292")
    fill.onto.person("Бэкон", "1561", "1626")
    source = fill.lib.register()
    fill.model.replies.append(
        {
            "statements": [
                st("Хьюм", "holds", "Опыт", 2, "Но не всё оно происходит из опыта"),
                st("Бэкон", "holds", "Опыт", 2, "Но не всё оно происходит из опыта"),
            ]
        }
    )
    fill.publish(source)
    holds = [s for s in _all(fill) if s["type"] == "holds"]
    assert [s["subject"] for s in holds] == [hume]
    assert events.one("knowledge.extraction.ambiguous")["candidates"] == 2
    assert [i for i in fill.review.queue(kind="ambiguous_link")]


@req(EX, "Проверки и сведение")
def test_second_source_merges(fill):
    item = st("Кант", "holds", "Опыт", 2, "Но не всё оно происходит из опыта")
    first = fill.lib.register()
    fill.model.replies.append({"statements": [item]})
    fill.publish(first)
    second = fill.lib.register(title="Второй учебник", confirm_duplicate=True)
    fill.model.replies.append({"statements": [item]})
    fill.publish(second)
    holds = [s for s in _all(fill) if s["type"] == "holds"]
    assert len(holds) == 1 and len(holds[0]["attributions"]) == 2
    assert holds[0]["consensus"] == "prevailing"


@req(EX, "Повышение статуса")
def test_generated_promoted_by_new_source(fill, events):
    kant = fill.onto.person("Кант")
    position = fill.onto.thing("position", "Опыт")
    generated = fill.onto.statements.add(
        kant, "holds", obj=position, provenance=Provenance("generated")
    )
    source = fill.lib.register()
    fill.model.replies.append(
        {"statements": [st("Кант", "holds", "Опыт", 2, "Но не всё оно происходит из опыта")]}
    )
    fill.publish(source)
    assert fill.onto.statements.get(generated)["status"] == "sourced"
    assert events.where("knowledge.statement.status", new="sourced")


@req(EX, "Ядро вручную")
def test_core_from_model_draft(fill):
    fill.model.replies.append(
        {
            "items": [
                {"name": "Причинность", "type": "concept", "note": "центральное понятие раздела"},
                {"name": "Лишнее", "type": "concept"},
            ]
        }
    )
    draft = fill.filling.propose_core("теория познания")
    created = fill.filling.accept_core(draft[:1], "operator")
    entity = fill.onto.entities.get(created[0])
    assert entity["names"][0]["text"] == "Причинность"
    description = fill.onto.statements.about(created[0])[0]
    assert description["provenance"]["method"] == "manual"
    assert description["provenance"]["extra"] == {"draft": "model"}


@req(EX, "Импорт из Wikidata")
def test_wikidata_simple_facts(fill, events):
    records = {
        "Q9312": {
            "labels": {"ru": "Иммануил Кант"},
            "claims": {
                "P569": ["+1724-04-22"],
                "P570": ["+1804-02-12"],
                "P19": ["Q4120832"],
                "P1066": ["Q57193"],
                "P737": ["Q37160"],
            },
        },
        "Q4120832": {"labels": {"ru": "Кёнигсберг"}, "claims": {}},
        "Q57193": {"labels": {"ru": "Мартин Кнутцен"}, "claims": {}},
    }
    created = fill.filling.import_wikidata("Q9312", records.__getitem__)
    statements = [fill.onto.statements.get(i) for i in created]
    assert {s["type"] for s in statements} == {"lifespan", "lived_in", "studied_with"}
    assert all(s["status"] == "sourced" for s in statements)
    assert all(s["attributions"][0]["who"] == "wikidata:Q9312" for s in statements)
    assert events.where("knowledge.import.skipped", property="P737")
    kant = fill.onto.entities.by_external("wikidata", "Q9312")
    assert fill.onto.entities.get(kant)["primary"]["dates"]["earliest_start"] == 1724


@req(EX, "Запуски наполнения")
def test_runs_estimate_and_rollback(fill, events):
    source = fill.lib.register()
    fill.lib.publish_new(source)
    version = fill.lib.registry.get(source).published_version
    fill.model.replies.append(
        {"statements": [st("Кант", "holds", "Опыт", 1, "Всякое знание начинается с опыта")]}
    )
    estimate = fill.filling.estimate(version, sample_fragments=1)
    assert (
        estimate["sample_cost_usd"] > 0 and estimate["estimate_usd"] >= estimate["sample_cost_usd"]
    )
    run = next(r for r in fill.filling.runs() if r["run_id"] == estimate["run_id"])
    assert run["created"] == 1 and run["status"] == "done"
    fill.filling.rollback(estimate["run_id"])
    assert _all(fill) == []
    assert events.one("knowledge.run.rolled_back")


# --- ontology-review -----------------------------------------------------------------


def _warned(fill):
    locke = fill.onto.person("Локк", "1632", "1704")
    essays = fill.onto.thing("work", "Новые опыты", "1765")
    return fill.onto.statements.add(
        locke, "influenced_by", obj=essays, attributions=[Attribution("common")]
    )


@req(RV, "Очередь проверки")
def test_queue_kinds_and_filters(fill):
    warned = _warned(fill)
    fill.onto.registry.propose("relation", {"code": "ridiculed"})
    kinds = {i["kind"] for i in fill.review.queue()}
    assert {"warning", "proposal"} <= kinds
    filtered = fill.review.queue(relation="criticizes")
    assert all(i.get("type") == "criticizes" for i in filtered)
    assert warned in [i["statement_id"] for i in fill.review.queue(kind="warning")]


@req(RV, "Приоритет")
def test_priority_by_views(fill):
    a = _warned(fill)
    kant, hume = fill.onto.person("Кант", "1724", "1804"), fill.onto.person("Юм", "1711", "1776")
    b = fill.onto.statements.add(
        hume, "studied_with", obj=kant, attributions=[Attribution("common")]
    )
    fill.onto.statements._warn(b, "lives_do_not_overlap")
    fill.review.record_views([b] * 100)
    order = [i["statement_id"] for i in fill.review.queue(kind="warning")]
    assert order.index(b) < order.index(a)
    custom = Review(fill.onto.statements, fill.review.actions, Priority(views=0, warning=1))
    assert custom.priority.views == 0


@req(RV, "Контекст для решения")
def test_context_highlights_quote(fill):
    source = fill.lib.register()
    fill.model.replies.append({"statements": [st("Кант", "holds", "Опыт", 1, "говорит Кант")]})
    fill.publish(source)
    statement = _all(fill)[0]
    ctx = fill.review.context(statement["id"])
    evidence = ctx["evidence"][0]
    start, end = evidence["highlight"]
    assert evidence["paragraph_text"][start:end] == "говорит Кант"
    assert evidence["link"].startswith("/p/") and ctx["subject"] == "Кант"
    assert ctx["relation"] == "придерживается"


@req(RV, "Решения")
def test_decisions_with_journal(fill, events):
    warned = _warned(fill)
    fill.review.decide(warned, "edit", "operator", {"type": "knew_work"})
    s = fill.onto.statements.get(warned)
    assert s["type"] == "knew_work" and s["status"] == "verified"
    journal = fill.onto.statements.journal(warned)
    assert any(j["change"].get("before", {}).get("type") == "influenced_by" for j in journal)
    other = _warned(fill)
    fill.review.decide(other, "reject", "operator")
    assert fill.onto.statements.get(other)["status"] == "rejected"
    assert {e["decision"] for e in events.of("knowledge.review.decided")} == {"edit", "reject"}
    assert [a["action"] for a in fill.review.actions.entries()] == [
        "statement_edit",
        "statement_reject",
    ]


@req(RV, "Решения по сущностям")
def test_entity_decisions(fill):
    a = fill.onto.person("Дж. Локк", "1632", "1704")
    b = fill.onto.person("Джон Локк", "1632", "1704")
    fill.review.refresh_duplicates()
    item = next(i for i in fill.review.queue(kind="duplicate"))
    fill.review.resolve_duplicate(item["item_id"], True, "operator")
    assert fill.onto.entities.get(b)["id"] == a
    proposal = fill.onto.registry.propose("relation", {"code": "ridiculed"})
    fill.review.resolve_proposal(
        proposal,
        True,
        "operator",
        {
            "code": "ridiculed",
            "title": "высмеивал",
            "subject_types": ["person"],
            "object_types": ["person"],
        },
    )
    assert fill.onto.registry.relation("ridiculed")["title"] == "высмеивал"


@req(RV, "Выборка для метрик")
def test_sample_into_evaluation_dataset(fill, engine_for):
    from philograph.evaluation.datasets import Datasets
    from philograph.evaluation.datasets import migrations as eval_migrations

    kant = fill.onto.person("Кант")
    for name in ("Юм", "Лейбниц", "Вольф"):
        fill.onto.statements.add(
            kant, "criticizes", obj=fill.onto.person(name), attributions=[Attribution("common")]
        )
    sample = fill.review.sample("criticizes", 2, seed=1)
    items = fill.review.sample_items(sample)
    assert len(items) == 2
    fill.review.decide_sample(sample, items[0]["statement_id"], True, "operator")
    fill.review.decide_sample(sample, items[1]["statement_id"], False, "operator")
    datasets = Datasets(engine_for(eval_migrations))
    dataset = datasets.create("утверждения", "statements")
    for row in fill.review.export_sample(sample):
        datasets.add(dataset, row["item_id"], row)
    assert sorted(i["correct"] for i in datasets.snapshot(dataset)) == [False, True]


@req(RV, "Доступ")
def test_review_requires_operator(fill, clock):
    auth = OperatorAuth(hash_password("пароль", iterations=1000), clock=clock)
    client = TestClient(build_app(fill.onto.statements, review=fill.review, auth=auth))
    assert client.get("/v1/review/queue").status_code == 404
    assert client.post("/v1/operator/login", json={"password": "не тот"}).status_code == 401
    assert client.post("/v1/operator/login", json={"password": "пароль"}).status_code == 200
    assert SESSION_COOKIE in client.cookies
    assert client.get("/v1/review/queue").status_code == 200
