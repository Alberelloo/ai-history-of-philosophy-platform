"""Региональный доступ сервиса знаний (группа 6 задач ru-only-sources).

Источник, закрытый для региона читателя, скрывается на всех путях сервиса знаний: карточка,
граф, упоминания («где читать» и выделения) и контекст ассистента. Сами утверждения онтологии
остаются, статус утверждения не пересчитывается.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from philograph.knowledge import schema as ks
from philograph.knowledge.app import REGION_HEADER, build_app, closed_sources
from philograph.knowledge.cards import Cards
from philograph.knowledge.graph import Graphs
from philograph.knowledge.mentions import Mentions
from philograph.platform.client import ServiceClient

req = pytest.mark.req
RA = "regional-access"
REQ = "Онтология не раскрывает текст закрытых источников"


def access_client(closed: list[str] | None = None, *, fail: bool = False) -> ServiceClient:
    """Фиктивная библиотека: ``internal/access`` отдаёт заданный список закрытых источников."""
    if closed is None:
        closed = ["s_closed"]

    def handler(request: httpx.Request) -> httpx.Response:
        if fail:
            raise httpx.ConnectError("нет связи", request=request)
        assert request.url.path.endswith("/internal/access")
        region = request.url.params.get("region")
        # Как настоящая библиотека: для РФ ограниченный источник открыт, иначе закрыт.
        closed_for = [] if region == "RU" else closed
        return httpx.Response(200, json={"region": region, "closed": closed_for})

    return ServiceClient(
        "library", "http://library/api", transport=httpx.MockTransport(handler), retries=0
    )


@req(RA, REQ)
def test_closed_sources_from_library():
    """6.1: единая функция берёт множество закрытых источников из ``internal/access``."""
    assert closed_sources(access_client(["s_closed", "s_other"]), "DE") == frozenset(
        {"s_closed", "s_other"}
    )


@req(RA, REQ)
def test_region_header_reaches_library(onto):
    """6.1: регион из заголовка ``X-Philograph-Region`` передаётся в ``internal/access``."""
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["region"] = request.url.params.get("region")
        return httpx.Response(200, json={"region": seen["region"], "closed": []})

    library = ServiceClient("library", "http://library/api", transport=httpx.MockTransport(handler))
    kant = onto.person("Кант", "1724", "1804")
    app = build_app(onto.statements, cards=Cards(onto.statements), library=library)
    TestClient(app).get(f"/v1/entities/{kant}/card", headers={REGION_HEADER: "DE"})
    assert seen["region"] == "DE"


@req(RA, REQ)
def test_card_hides_closed_source_confirmation(onto):
    """6.2: утверждение, подтверждённое только закрытым источником, показано без подтверждения."""
    kant = onto.person("Кант", "1724", "1804")
    hume = onto.person("Юм", "1711", "1776")
    sid = onto.sourced(kant, "influenced_by", hume, who="s_closed")
    app = build_app(
        onto.statements, cards=Cards(onto.statements), library=access_client(["s_closed"])
    )
    card = TestClient(app).get(f"/v1/entities/{kant}/card", headers={REGION_HEADER: "DE"}).json()
    rows = {r["statement_id"]: r for s in card["sections"] for r in s["rows"]}
    row = rows[sid]
    assert row["status"] == "sourced"  # статус не пересчитывается
    assert row["evidence"] == []  # цитата и ссылка /p/<id> скрыты
    assert row["attributed_to"] == []  # атрибуция источника скрыта
    assert row["attributions"] == []
    assert row["label"] == "Юм"  # само утверждение (факт) остаётся


@req(RA, REQ)
def test_card_keeps_open_source_confirmation(onto):
    """6.2: подтверждения открытых источников остаются; чужие идентификаторы не влияют."""
    kant = onto.person("Кант", "1724", "1804")
    hume = onto.person("Юм", "1711", "1776")
    sid = onto.sourced(kant, "influenced_by", hume, who="s_open")
    cards = Cards(onto.statements)
    # Закрыты только неизвестные источники — открытое подтверждение остаётся.
    row = {
        r["statement_id"]: r
        for s in cards.card(kant, closed={"s_other"})["sections"]
        for r in s["rows"]
    }[sid]
    assert [e["paragraph_id"] for e in row["evidence"]] == ["p2"]
    assert row["attributed_to"] == ["s_open"]


@req(RA, REQ)
def test_graph_hides_closed_source_evidence(onto):
    """6.2: у связей графа нет подтверждений из закрытых источников; узлы и связи те же."""
    kant = onto.person("Кант", "1724", "1804")
    hume = onto.person("Юм", "1711", "1776")
    sid = onto.sourced(kant, "influenced_by", hume, who="s_closed")
    graphs = Graphs(onto.statements)
    items = list(graphs.build(kant, "genesis", generation=False, closed={"s_closed"}))
    graph = next(i for i in items if i["type"] == "graph")
    edge = next(e for e in graph["edges"] if e["id"] == sid)
    assert edge["status"] == "sourced"  # статус не пересчитывается
    assert edge["evidence"] == []
    assert edge["attributions"] == []
    assert [n["id"] for n in graph["nodes"]] == [hume, kant]  # узлы и связь на месте


@req(RA, REQ)
def test_for_targets_hides_closed_sources(onto):
    """6.3: выделения абзацев из закрытых источников не отдаются."""
    kant = onto.person("Кант")
    with onto.statements.engine.begin() as conn:
        conn.execute(
            ks.mentions.insert(),
            [
                {
                    "target_id": "p_closed",
                    "target_kind": "paragraph",
                    "source_id": "s_closed",
                    "chapter_id": "c1",
                    "entity_id": kant,
                    "start": 0,
                    "end": 4,
                    "method": "name",
                },
                {
                    "target_id": "p_open",
                    "target_kind": "paragraph",
                    "source_id": "s_open",
                    "chapter_id": "c1",
                    "entity_id": kant,
                    "start": 0,
                    "end": 4,
                    "method": "name",
                },
            ],
        )
    mentions = Mentions(onto.statements, access_client())
    found = mentions.for_targets(["p_closed", "p_open"], closed={"s_closed"})
    assert [m["target_id"] for m in found] == ["p_open"]


@req(RA, REQ)
def test_where_to_read_hides_closed_sources(onto):
    """6.3: «где читать» показывает только открытые источники."""
    kant = onto.person("Кант")
    with onto.statements.engine.begin() as conn:
        conn.execute(
            ks.mentions.insert(),
            [
                {
                    "target_id": "p_closed",
                    "target_kind": "paragraph",
                    "source_id": "s_closed",
                    "chapter_id": "c1",
                    "source_title": "Закрытый источник",
                    "chapter_title": "Глава",
                    "entity_id": kant,
                    "start": 0,
                    "end": 4,
                    "method": "name",
                    "position": 0,
                },
                {
                    "target_id": "p_open",
                    "target_kind": "paragraph",
                    "source_id": "s_open",
                    "chapter_id": "c2",
                    "source_title": "Открытый источник",
                    "chapter_title": "Глава",
                    "entity_id": kant,
                    "start": 0,
                    "end": 4,
                    "method": "name",
                    "position": 0,
                },
            ],
        )
    mentions = Mentions(onto.statements, access_client())
    where = mentions.where_to_read(kant, closed={"s_closed"})
    assert [w["source_id"] for w in where] == ["s_open"]


@req(RA, REQ)
def test_library_unavailable_is_503(onto):
    """Недоступная библиотека — безопасный отказ: знания не отдаются без фильтра."""
    kant = onto.person("Кант", "1724", "1804")
    app = build_app(onto.statements, cards=Cards(onto.statements), library=access_client(fail=True))
    response = TestClient(app).get(f"/v1/entities/{kant}/card", headers={REGION_HEADER: "DE"})
    assert response.status_code == 503
    assert response.json()["kind"] == "knowledge_unavailable"


@req(RA, REQ)
def test_raw_statements_hide_closed_sources(onto):
    """Сырой маршрут утверждений доступен через шлюз: цитаты закрытых источников скрыты."""
    kant = onto.person("Кант", "1724", "1804")
    hume = onto.person("Юм", "1711", "1776")
    closed_id = onto.sourced(kant, "influenced_by", hume, who="s_closed")
    open_id = onto.sourced(hume, "influenced_by", kant, who="s_open")
    app = build_app(onto.statements, cards=Cards(onto.statements), library=access_client())
    response = TestClient(app).get(f"/v1/entities/{kant}/statements", headers={REGION_HEADER: "DE"})
    rows = {row["id"]: row for row in response.json()}
    assert rows[closed_id]["status"] == "sourced"  # статус не пересчитывается
    assert rows[closed_id]["evidence"] == []
    assert rows[closed_id]["attributions"] == []
    assert [e["paragraph_id"] for e in rows[open_id]["evidence"]] == ["p2"]


@req(RA, REQ)
def test_raw_graph_hides_closed_sources(onto):
    """Сырой маршрут графа доступен через шлюз: у связей нет подтверждений закрытых источников."""
    kant = onto.person("Кант", "1724", "1804")
    hume = onto.person("Юм", "1711", "1776")
    closed_id = onto.sourced(kant, "influenced_by", hume, who="s_closed")
    app = build_app(onto.statements, cards=Cards(onto.statements), library=access_client())
    client = TestClient(app)
    result = client.get(
        "/v1/graph", params={"recipe": "genesis", "start": kant}, headers={REGION_HEADER: "DE"}
    ).json()
    edge = next(e for e in result["edges"] if e["id"] == closed_id)
    assert edge["evidence"] == []
    assert edge["attributions"] == []
    # Читатель из РФ видит то же утверждение с подтверждением.
    allowed = client.get(
        "/v1/graph", params={"recipe": "genesis", "start": kant}, headers={REGION_HEADER: "RU"}
    ).json()
    edge_ru = next(e for e in allowed["edges"] if e["id"] == closed_id)
    assert edge_ru["evidence"] and edge_ru["attributions"]
