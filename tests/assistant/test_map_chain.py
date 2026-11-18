"""Цепочка «карта» (question-routing) и «Карта по запросу» (assistant-dialog).

Стенд ассистента с онтологией из ``test_ontology_retrieval`` дополнен картой раздела: сервис
знаний отвечает настоящими ``/v1/map/view`` и ``map-options``. Модель — по сценарию: черновик
вида строится по фактическому запросу (ключи кандидатов c1, c2… известны только из него).
"""

from __future__ import annotations

import re

import httpx
import pytest

from philograph.assistant.ontology import KnowledgeHttp, Ontology
from philograph.assistant.service import AssistantSettings
from philograph.knowledge.app import build_app as knowledge_app
from philograph.knowledge.assist import AssistantKnowledge
from philograph.knowledge.map import SectionMap
from philograph.knowledge.statements import Attribution
from philograph.platform.client import ServiceClient

from ..helpers import asgi_transport
from .test_ontology_retrieval import ob  # noqa: F401 — стенд с онтологией

req = pytest.mark.req
QR = "question-routing"
AD = "assistant-dialog"


@pytest.fixture
def mb(ob):
    common = [Attribution("common")]
    ids = ob.ids
    ids["empiricism"] = ob.entities.create("group", [("ru", "Эмпиризм", "primary")])
    ob.statements.add(ids["empiricism"], "group_kind", value="direction", attributions=common)
    for member in ("locke", "hume"):
        ob.statements.add(ids[member], "member_of", obj=ids["empiricism"], attributions=common)
    ob.mentions.index_version(ob.bot.rig.registry.get(ob.textbook).published_version)
    app = knowledge_app(
        ob.statements,
        assistant=AssistantKnowledge(ob.statements, ob.mentions),
        section_map=SectionMap(ob.statements),
    )
    ob.calls = []

    def record(request: httpx.Request) -> None:
        ob.calls.append(request.url.path)

    knowledge = ServiceClient("knowledge", "http://knowledge", transport=asgi_transport(app))
    knowledge._http.event_hooks["request"].append(record)
    ob.bot.assistant.ontology = Ontology(KnowledgeHttp(knowledge))
    return ob


def key_of(prompt: str, label: str) -> str:
    """Ключ кандидата в блоке candidates запроса подбора вида."""
    match = re.search(rf"(c\d+) — [^«\n]*«{re.escape(label)}»", prompt)
    assert match, f"нет кандидата «{label}» в запросе"
    return match.group(1)


def draft(**fields):
    """Черновик вида; ``groups`` и ``sel`` — подписи кандидатов, ключи берутся из запроса."""

    def make(prompt: str) -> dict:
        value = {
            "sel": None,
            "groups": [],
            "from": None,
            "to": None,
            "roles": [],
            "kinds": [],
            "ekinds": [],
            "verified": False,
            "lens": [],
            "caption": "Вид",
            **fields,
        }
        if value["sel"]:
            value["sel"] = key_of(prompt, value["sel"])
        value["groups"] = [key_of(prompt, g) for g in value["groups"]]
        return value

    return make


def route(names: list[str]) -> dict:
    return {"type": "map", "confidence": 0.9, "names": names}


def of(items, type_, kind=None):
    return [i for i in items if i["type"] == type_ and (kind is None or i.get("kind") == kind)]


def calls(bot, operation: str) -> list[dict]:
    return [c for c in bot.gateway.store.calls() if c["operation"] == operation]


@req(QR, "Цепочка «карта»")
def test_view_by_school(mb, events):
    """«Покажи на карте эмпиристов XVIII века»: группа и годы, ответ со ссылками, ≤ 3 вызова."""
    bot = mb.bot
    bot.model.routes.extend(
        [
            route(["эмпиризм"]),
            draft(groups=["Эмпиризм"], caption="  Эмпиристы\nXVIII века ", **{"from": 1700}),
        ]
    )
    bot.model.answers.append(
        lambda prompt: [f"Юм развивал эмпиризм Локка [{bot.number(prompt, 'Юм')}]."]
    )
    items = bot.ask(question="покажи на карте эмпиристов XVIII века")
    [suggestion] = of(items, "suggestion", "map")
    empiricism = mb.ids["empiricism"]
    assert suggestion["href"] == f"/graph?from=1700&groups={empiricism}&via=assistant"
    assert suggestion["caption"] == "Эмпиристы XVIII века"  # пробелы и переводы строк сжаты
    assert suggestion["shown"] == {"people": 2, "works": 0}  # Юм и Локк (умер в 1704)
    assert suggestion["dropped"] == []
    assert of(items, "fragment") and of(items, "fragment")[0]["grounded"] is True
    assert {"type": "stage", "name": "map_view"} in items
    assert items[-1]["kind"] == "map" and items[-1]["llm_calls"] == 3
    # Подбор вида — быстрая модель со структурированным выводом; ответ знает вид.
    [view_call] = calls(bot, "map_view")
    assert view_call["role"] == "fast" and view_call["kind"] == "structured"
    assert "Направления и школы: Эмпиризм" in mb.block("map_view")
    assert "Годы: 1700–…" in mb.block("map_view")
    drafted = events.one("assistant.map_view.drafted")
    assert drafted["fields"] == ["from", "groups"] and drafted["dropped"] == 0
    assert events.one("assistant.answer.completed")["llm_calls"] <= 3
    assert "/v1/map/view" in mb.calls and "/v1/internal/assistant/map-options" in mb.calls


@req(QR, "Цепочка «карта»")
def test_candidates_only_from_map(mb):
    """Модель видит только сущности вопроса, которые есть на карте, и коды фильтров карты."""
    bot = mb.bot
    bot.model.routes.extend([route(["Кант", "привычка"]), draft(sel="Кант")])
    bot.ask(question="собери карту вокруг Канта и привычки")
    prompt = next(
        r.messages[-1].content for r in bot.model.requests if r.template == "assistant.map.view"
    )
    candidates = re.search(r'<data name="candidates">\n(.*?)\n</data>', prompt, re.S).group(1)
    assert "персона «Кант», 1724–1804" in candidates
    assert "Привычка" not in candidates  # понятие без датированного труда — не на карте
    assert "roles: —" in prompt  # ролей у персон стенда нет — фильтр пуст
    # Аристотель на карте: начало раздела — до н. э., модель видит и число, и подпись.
    assert "-383 (384 до н. э.)–1804" in prompt
    # Схема вывода не даёт выбрать что-то вне списка кандидатов.
    schema = calls(bot, "map_view")[0]
    assert schema["status"] == "ok"


@req(AD, "Карта по запросу")
def test_part_of_choice_dropped(mb):
    """Сущности нет на карте — ответ говорит об этом, кнопка ведёт на вид без неё."""
    bot = mb.bot
    bot.model.routes.extend([route(["Кант", "привычка"]), draft(sel="Кант")])
    items = bot.ask(question="собери карту вокруг Канта и привычки")
    [suggestion] = of(items, "suggestion", "map")
    assert suggestion["href"] == f"/graph/{mb.ids['kant']}?via=assistant"
    assert suggestion["dropped"] == [
        {"field": "sel", "value": mb.ids["habit"], "label": "Привычка", "reason": "not_on_map"}
    ]
    assert "Не вошло: Привычка — нет на карте" in mb.block("map_view")


@req(AD, "Карта по запросу")
def test_server_dropped_reaches_answer(mb):
    """Отброшенное сервером (пустая карта при годах) — в кнопке и в данных ответа."""
    bot = mb.bot
    bot.model.routes.extend(
        [route(["эмпиризм"]), draft(groups=["Эмпиризм"], **{"from": 1790, "to": 1800})]
    )
    items = bot.ask(question="эмпиристы 1790-х на карте")
    [suggestion] = of(items, "suggestion", "map")
    assert suggestion["href"] == f"/graph?groups={mb.ids['empiricism']}&via=assistant"
    assert [(d["field"], d["reason"]) for d in suggestion["dropped"]] == [
        ("from", "empty_result"),
        ("to", "empty_result"),
    ]
    assert "1790 — карта вышла бы пустой" in mb.block("map_view")


@req(QR, "Цепочка «карта»")
def test_no_candidates_falls_back(mb, events):
    bot = mb.bot
    bot.model.routes.append(route(["философия Древнего Китая"]))
    items = bot.ask(question="покажи на карте философию Древнего Китая")
    [notice] = of(items, "notice", "map_no_candidates")
    assert notice["message"].startswith("Собрать карту не из чего")
    assert not of(items, "suggestion", "map")
    assert items[-1]["kind"] == "knowledge" and items[-1]["llm_calls"] == 2
    assert not calls(bot, "map_view")  # без кандидатов модель вид не подбирает
    assert events.one("assistant.map_view.failed")["reason"] == "no_candidates"
    assert events.of("assistant.searched")  # ответ по цепочке «база знаний»


@req(QR, "Цепочка «карта»")
def test_knowledge_down_falls_back(mb, events):
    bot = mb.bot

    def down(request):
        raise httpx.ConnectError("сервис знаний не отвечает")

    bot.assistant.ontology = Ontology(
        KnowledgeHttp(
            ServiceClient("knowledge", "http://knowledge", transport=httpx.MockTransport(down))
        )
    )
    bot.model.routes.append(route(["эмпиризм"]))
    items = bot.ask(question="покажи на карте эмпиристов")
    assert of(items, "notice", "map_unavailable")
    assert not of(items, "suggestion", "map") and items[-1]["kind"] == "knowledge"
    assert events.one("assistant.map_view.failed")["reason"] == "ontology_unavailable"
    assert of(items, "fragment")  # ответ всё равно есть


@req(QR, "Цепочка «карта»")
def test_map_service_down_after_context(mb, events):
    """Контекст онтологии есть, а карты в сервисе знаний нет — сбой подбора вида в журнале."""
    bot = mb.bot
    app = knowledge_app(
        mb.statements, assistant=AssistantKnowledge(mb.statements, mb.mentions)
    )  # без карты: map-options отвечает 404
    bot.assistant.ontology = Ontology(
        KnowledgeHttp(ServiceClient("knowledge", "http://k", transport=asgi_transport(app)))
    )
    bot.model.routes.append(route(["эмпиризм"]))
    items = bot.ask(question="покажи на карте эмпиристов")
    assert of(items, "notice", "map_unavailable")
    failed = events.one("assistant.map_view.failed")
    assert failed["reason"] == "knowledge_unavailable" and "404" in failed["error"]


@req(QR, "Цепочка «карта»")
def test_draft_error_and_call_limit(mb, events):
    from philograph.llm.providers import TransientProviderError

    bot = mb.bot
    # Модель подбора вида не ответила по схеме ни разу — ответ без карты.
    bot.model.routes.extend([route(["эмпиризм"])] + [TransientProviderError("сбой")] * 3)
    items = bot.ask(question="покажи на карте эмпиристов")
    assert of(items, "notice", "map_unavailable") and not of(items, "suggestion", "map")
    assert events.one("assistant.map_view.failed")["reason"] == "draft_failed"
    assert items[-1]["llm_calls"] == 3
    events.clear()
    # Предел вызовов 2: подбор вида не помещается вместе с ответом — модель не вызывается.
    bot.assistant.settings = AssistantSettings(max_llm_calls=2, visitor_per_hour=50)
    before = len(calls(bot, "map_view"))
    bot.model.routes.append(route(["эмпиризм"]))
    items = bot.ask(question="покажи на карте эмпиристов")
    assert events.one("assistant.map_view.failed")["reason"] == "call_limit"
    assert len(calls(bot, "map_view")) == before and items[-1]["llm_calls"] == 2


@req(AD, "Карта по запросу")
def test_model_text_never_in_href(mb):
    """Адрес строит сервер из проверенного вида: подпись модели в адрес не попадает."""
    bot = mb.bot
    bot.model.routes.extend(
        [route(["Кант"]), draft(sel="Кант", caption="<script>alert(1)</script>&via=evil")]
    )
    items = bot.ask(question="карта вокруг Канта")
    [suggestion] = of(items, "suggestion", "map")
    assert suggestion["href"] == f"/graph/{mb.ids['kant']}?via=assistant"
    assert "evil" not in suggestion["href"] and "script" not in suggestion["href"]
