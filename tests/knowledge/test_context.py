"""epoch-context: «Контекст эпохи», «Проверка параметров контекста», «Пометка непроверенного
контекста», «Механизм влияния», «Контекст и закрытые источники» (изменение add-epoch-context,
задача 6.1).

Тесты написаны по дельте ``openspec/changes/add-epoch-context/specs/epoch-context``. Стенд —
``svc`` (``conftest.py``): приложение сервиса знаний с маршрутом ``GET /v1/context``; библиотека
закрывает «Учебник R» для любого региона, кроме ``RU``; любой вызов модели записывается.
Каждый ответ сводится с событием журнала по ``request_id``.
"""

from __future__ import annotations

import json

import pytest

from philograph.knowledge.dates import parse
from philograph.knowledge.statements import Attribution, Evidence, Provenance, StatementError

from .conftest import TEXTBOOK_N, TEXTBOOK_R, VISITOR_ADDRESS

req = pytest.mark.req
EC = "epoch-context"
CTX = "Контекст эпохи"
PARAMS = "Проверка параметров контекста"
MARK = "Пометка непроверенного контекста"
MECH = "Механизм влияния"
CLOSED = "Контекст и закрытые источники"
SERVED = "knowledge.context.served"
REJECTED = "knowledge.context.rejected"
COMMON = [Attribution("common")]
MECHANISMS = ["political", "economic", "social", "religious", "scientific", "institutional"]
NEWTON = "Выход «Начал» Ньютона"
GLORIOUS = "Славная революция"
BUBBLE = "Южноморский пузырь"
ENCYCLOPEDIA = "Выход первого тома «Энциклопедии»"
LOCKE_DOCTRINE = "Политическая философия Локка"


# --- данные ----------------------------------------------------------------------------


@pytest.fixture
def w(svc):
    """Общие данные сценариев дельты: эпохи, четыре события, Лондон, учение Локка."""
    world = svc.world
    d = {
        "sci": world.thing("epoch", "Научная революция", "1543–1687"),
        "enl": world.thing("epoch", "Просвещение", "1680–1800"),
        "newton": world.thing("event", NEWTON, "1687"),
        "glorious": world.thing("event", GLORIOUS, "1688"),
        "bubble": world.thing("event", BUBBLE, "1720"),
        "encyclopedia": world.thing("event", ENCYCLOPEDIA, "1751"),
        "london": world.thing("place", "Лондон"),
        "locke_doctrine": world.thing("doctrine", LOCKE_DOCTRINE),
        "religion_critique": world.thing("doctrine", "Критика религии"),
        "locke": world.person("Джон Локк", "1632", "1704"),
        "textbook": world.source(TEXTBOOK_N, "Учебник N"),
        "textbook_r": world.source(TEXTBOOK_R, "Учебник R"),
    }
    for key, kind in [
        ("glorious", "political"),
        ("newton", "scientific"),
        ("encyclopedia", "intellectual"),
        ("bubble", "economic"),
    ]:
        world.statements.add(d[key], "event_kind", value=kind, attributions=COMMON)
    world.relate(d["glorious"], "happened_in", d["london"])
    return d


def sourced_link(world, w, paragraph="p_1", text="Был спрос на обучение риторике у граждан."):
    """«Славная революция стимулировала политическую философию Локка», `political`, по
    источникам, подтверждено абзацем «Учебника N»."""
    world.paragraphs[paragraph] = text
    return world.statements.add(
        w["glorious"],
        "stimulated",
        obj=w["locke_doctrine"],
        qualifiers={"mechanism": "political"},
        attributions=[Attribution("source", TEXTBOOK_N)],
        evidence=[Evidence(paragraph, "спрос на обучение риторике", source_id=TEXTBOOK_N)],
        provenance=Provenance("extracted"),
    )


def generated_link(world, subject, obj):
    return world.statements.add(
        subject, "stimulated", obj=obj, provenance=Provenance("generated", actor="graph")
    )


def extracted(world, subject, obj):
    """Связь «по источникам»: атрибуция «Учебника N», происхождение — импорт (без абзаца)."""
    return world.statements.add(
        subject,
        "stimulated",
        obj=obj,
        attributions=[Attribution("source", TEXTBOOK_N)],
        provenance=Provenance("imported"),
    )


def ask(svc, events, params, region=None):
    """Ответ ``/v1/context`` и события журнала этого запроса (по ``request_id``)."""
    response, rid = svc.get("/v1/context", params=params, region=region)
    mine = [e for e in events.items if e.get("request_id") == rid]
    return response, mine


def served_of(mine):
    found = [e for e in mine if e.name == SERVED]
    assert len(found) == 1, [e.name for e in mine]
    return found[0]


def by_label(body):
    return {e["label"]: e for e in body["events"]}


# --- Контекст эпохи --------------------------------------------------------------------


@req(EC, CTX, scenario="Контекст Просвещения")
def test_enlightenment_context(svc, w, events):
    svc.onto.paragraphs["p_1"] = "Был спрос на обучение риторике у граждан."
    link_id = sourced_link(svc.world, w)
    response, mine = ask(svc, events, {"epoch": w["enl"], "textbook": TEXTBOOK_N})
    assert response.status_code == 200, response.text
    body = response.json()
    assert [e["label"] for e in body["events"]] == [NEWTON, GLORIOUS, BUBBLE, ENCYCLOPEDIA]
    glorious = by_label(body)[GLORIOUS]
    assert glorious["id"] == w["glorious"] and glorious["type"] == "event"
    assert glorious["kind"] == "political"
    assert glorious["places"] == [{"id": w["london"], "label": "Лондон", "wikidata": None}]
    assert glorious["basis"] == "dates"
    assert glorious["dates"]["from"] == 1688
    [link] = glorious["stimulated"]
    assert link["statement_id"] == link_id
    assert link["target"] == {
        "id": w["locke_doctrine"],
        "label": LOCKE_DOCTRINE,
        "type": "doctrine",
    }
    assert link["mechanism"] == "political"
    assert link["status"] == "sourced"
    assert link["generated"] is False
    assert link["in_textbook"] is True
    assert link["evidence"] == [{"paragraph_id": "p_1", "link": "/p/p_1"}]
    assert body["counts"] == {"scientific": 1, "political": 1, "economic": 1, "intellectual": 1}
    served = served_of(mine)
    assert served["mode"] == "epoch"
    assert served["events"] == 4
    assert served["links"] == 1
    assert served["generated_links"] == 0
    assert served["truncated"] is False
    assert isinstance(served["snapshot"], (int, str)) and served["snapshot"] not in ("", None)
    assert svc.llm_calls == []  # контекст не вызывает модель


@req(EC, CTX, invariant="без учебника in_textbook=null; связь чужого источника — in_textbook=false")
def test_in_textbook_marks(svc, w, events):
    sourced_link(svc.world, w)
    other = svc.world.relate(w["newton"], "stimulated", w["locke_doctrine"])
    body = ask(svc, events, {"epoch": w["enl"]})[0].json()
    assert by_label(body)[GLORIOUS]["stimulated"][0]["in_textbook"] is None
    marked = ask(svc, events, {"epoch": w["enl"], "textbook": TEXTBOOK_N})[0].json()
    [newton_link] = by_label(marked)[NEWTON]["stimulated"]
    assert newton_link["statement_id"] == other and newton_link["in_textbook"] is False


@req(EC, CTX, scenario="Окно времени")
def test_window(svc, w, events):
    response, mine = ask(svc, events, {"from": "1700", "to": "1760"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert [e["label"] for e in body["events"]] == [BUBBLE, ENCYCLOPEDIA]
    assert body["epoch"] is None
    assert body["window"] == {"from": 1700, "to": 1760}
    assert body["mode"] == "window"
    assert all(e["basis"] is None for e in body["events"])
    served = served_of(mine)
    assert served["mode"] == "window" and served["events"] == 2


@req(EC, CTX, invariant="окно — полуоткрытый интервал [from, to) по середине датировки")
@pytest.mark.parametrize(
    ("window", "expected"),
    [
        (("1720", "1751"), [BUBBLE]),  # 1751 — граница to, не входит
        (("1751", "1752"), [ENCYCLOPEDIA]),  # граница from входит
        (("1688", "1689"), [GLORIOUS]),
        (("-100", "1600"), []),  # до нашей эры, событий нет
    ],
)
def test_window_bounds(svc, w, events, window, expected):
    response, mine = ask(svc, events, {"from": window[0], "to": window[1]})
    assert response.status_code == 200, response.text
    assert [e["label"] for e in response.json()["events"]] == expected
    assert served_of(mine)["events"] == len(expected)


@req(EC, CTX, invariant="середина датировки — общая функция: событие-интервал по середине")
def test_window_uses_middle_of_dating(svc, w, events):
    war = svc.world.thing("event", "Семилетняя война", "1756–1763")  # середина 1759,5
    assert [
        e["id"] for e in ask(svc, events, {"from": "1759", "to": "1760"})[0].json()["events"]
    ] == [war]
    assert ask(svc, events, {"from": "1756", "to": "1759"})[0].json()["events"] == []


@req(EC, CTX, scenario="Фильтр видов")
def test_kinds_filter(svc, w, events):
    full = ask(svc, events, {"epoch": w["enl"]})[0].json()
    response, mine = ask(svc, events, {"epoch": w["enl"], "kinds": "political,economic"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert [e["label"] for e in body["events"]] == [GLORIOUS, BUBBLE]
    assert body["counts"] == full["counts"]
    assert served_of(mine)["events"] == 2


@req(EC, CTX, invariant="kinds=none — события без вида; counts.none — их число")
def test_kinds_none(svc, w, events):
    plain = svc.world.thing("event", "Основание Лондонского королевского общества", "1690")
    body, mine = ask(svc, events, {"epoch": w["enl"], "kinds": "none"})
    data = body.json()
    assert [e["id"] for e in data["events"]] == [plain]
    assert data["events"][0]["kind"] is None
    assert data["counts"]["none"] == 1
    assert served_of(mine)["events"] == 1
    both = ask(svc, events, {"epoch": w["enl"], "kinds": "none,economic"})[0].json()
    assert [e["label"] for e in both["events"]] == [
        "Основание Лондонского королевского общества",
        BUBBLE,
    ]


@req(EC, CTX, invariant="только события, явления и идейные события; персоны и труды — нет")
def test_only_event_types(svc, w, events):
    phenomenon = svc.world.thing("phenomenon", "Кофейни Лондона", "1700")
    idea_event = svc.world.thing("idea_event", "Спор Лейбница и Кларка", "1715")
    svc.world.thing("work", "Опыт о человеческом разумении", "1690")
    body = ask(svc, events, {"epoch": w["enl"]})[0].json()
    types = {e["label"]: e["type"] for e in body["events"]}
    assert (
        types["Кофейни Лондона"] == "phenomenon" and types["Спор Лейбница и Кларка"] == "idea_event"
    )
    assert "Опыт о человеческом разумении" not in types and "Джон Локк" not in types
    ids = {e["id"] for e in body["events"]}
    assert {phenomenon, idea_event} <= ids


@req(EC, CTX, invariant="явная принадлежность — basis=explicit, по датам — basis=dates")
def test_basis_explicit(svc, w, events):
    # «Выход «Начал» Ньютона» (1687) явно отнесён к Просвещению.
    svc.world.belongs(w["newton"], w["enl"])
    body = ask(svc, events, {"epoch": w["enl"]})[0].json()
    assert by_label(body)[NEWTON]["basis"] == "explicit"
    assert by_label(body)[GLORIOUS]["basis"] == "dates"


@req(EC, CTX, invariant="события — по началу датировки, затем по названию")
def test_events_order_ties_by_label(svc, w, events):
    svc.world.thing("event", "Акт о веротерпимости", "1688")
    body = ask(svc, events, {"epoch": w["enl"]})[0].json()
    assert [e["label"] for e in body["events"]][:3] == [NEWTON, "Акт о веротерпимости", GLORIOUS]


@req(
    EC,
    CTX,
    invariant="связи — проверенные, по источникам, сгенерированные; внутри — по названию объекта",
)
def test_links_order(svc, w, events):
    world = svc.world
    a = world.thing("doctrine", "А-учение")
    b = world.thing("doctrine", "Б-учение")
    c = world.thing("doctrine", "В-учение")
    d = world.thing("doctrine", "Г-учение")
    gen_a = generated_link(world, w["bubble"], a)
    sourced_d = extracted(world, w["bubble"], d)
    sourced_b = extracted(world, w["bubble"], b)
    verified_c = extracted(world, w["bubble"], c)
    world.statements.confirm(verified_c, "operator")
    body = ask(svc, events, {"epoch": w["enl"]})[0].json()
    links = by_label(body)[BUBBLE]["stimulated"]
    assert [link["statement_id"] for link in links] == [verified_c, sourced_b, sourced_d, gen_a]
    assert [link["status"] for link in links] == ["verified", "sourced", "sourced", "generated"]


@req(EC, CTX, scenario="Отклонённое не показывается")
def test_rejected_not_shown(svc, w, events):
    rejected = svc.world.relate(w["encyclopedia"], "stimulated", w["religion_critique"])
    svc.onto.statements.reject(rejected, "operator")
    response, mine = ask(svc, events, {"epoch": w["enl"]})
    assert by_label(response.json())[ENCYCLOPEDIA]["stimulated"] == []
    assert rejected not in response.text
    assert served_of(mine)["links"] == 0


@req(EC, CTX, invariant="отклонённые и устаревшие связи не отдаются")
def test_deprecated_not_shown(svc, w, events):
    deprecated = svc.world.relate(w["encyclopedia"], "stimulated", w["religion_critique"])
    svc.onto.statements.set_rank(deprecated, "deprecated", "operator")
    response, mine = ask(svc, events, {"epoch": w["enl"]})
    assert by_label(response.json())[ENCYCLOPEDIA]["stimulated"] == []
    assert served_of(mine)["links"] == 0


@req(EC, CTX, scenario="Усечение")
def test_truncation(svc, w, events):
    world = svc.world
    # 197 событий с датировкой и видом (вместе с четырьмя из общих данных — 201); у самого
    # незначимого («Ничтожное») — только датировка, вида нет.
    for i in range(196):
        event = world.thing("event", f"Событие {i:03d}", str(1700 + i % 90))
        world.statements.add(event, "event_kind", value="social", attributions=COMMON)
    weak = world.thing("event", "Ничтожное", "1790")
    targets = [world.thing("doctrine", f"Учение {i:02d}") for i in range(31)]
    for target in targets:
        world.relate(w["bubble"], "stimulated", target)
    response, mine = ask(svc, events, {"epoch": w["enl"]})
    assert response.status_code == 200, response.text
    body = response.json()
    ids = [e["id"] for e in body["events"]]
    assert len(ids) == 200
    assert weak not in ids
    links = by_label(body)[BUBBLE]["stimulated"]
    assert len(links) == 30
    assert [link["target"]["label"] for link in links] == [f"Учение {i:02d}" for i in range(30)]
    assert body["truncated"] is True
    assert sum(body["counts"].values()) == 201
    assert body["counts"]["none"] == 1 and body["counts"]["social"] == 196
    served = served_of(mine)
    assert served["truncated"] is True and served["events"] == 200 and served["links"] == 30


@req(EC, CTX, invariant="усечение только по связям — тоже truncated=true")
def test_truncation_by_links_only(svc, w, events):
    for i in range(31):
        svc.world.relate(w["bubble"], "stimulated", svc.world.thing("doctrine", f"Учение {i:02d}"))
    response, mine = ask(svc, events, {"epoch": w["enl"]})
    body = response.json()
    assert len(body["events"]) == 4 and body["truncated"] is True
    assert served_of(mine)["truncated"] is True


@req(EC, CTX, invariant="контекст не вызывает модель")
def test_no_model_calls(svc, w, events):
    generated_link(svc.world, w["newton"], w["locke_doctrine"])
    for params in (
        {"epoch": w["enl"]},
        {"from": "1600", "to": "1800"},
        {"epoch": w["enl"], "verified": "true"},
    ):
        assert ask(svc, events, params)[0].status_code == 200
    assert svc.llm_calls == []


@req(EC, CTX, invariant="режимы эпоха и окно дают одни поля записи события")
def test_event_record_fields(svc, w, events):
    sourced_link(svc.world, w)
    keys = {"id", "label", "type", "kind", "dates", "places", "basis", "stimulated"}
    link_keys = {
        "statement_id",
        "target",
        "mechanism",
        "status",
        "generated",
        "in_textbook",
        "attributed_to",
        "evidence",
    }
    for params in ({"epoch": w["enl"]}, {"from": "1600", "to": "1800"}):
        body = ask(svc, events, params)[0].json()
        for event in body["events"]:
            assert keys <= set(event), set(event)
        [link] = by_label(body)[GLORIOUS]["stimulated"]
        assert link_keys <= set(link), set(link)


# --- Проверка параметров контекста -----------------------------------------------------


BOUNDS = [
    ({"epoch": "ENL", "from": "1700", "to": "1760"}, "bad_query", "mode"),
    ({}, "bad_query", "mode"),
    ({"from": "1700"}, "bad_query", "window"),
    ({"from": "17x0", "to": "1800"}, "bad_query", "window"),
    ({"from": "1800", "to": "1800"}, "bad_query", "window"),
    ({"epoch": "LOCKE"}, "unknown_epoch", "unknown_epoch"),
    ({"epoch": "ENL", "kinds": "culinary"}, "unknown_kind", "unknown_kind"),
]


def _resolve(params, w):
    names = {"ENL": w["enl"], "LOCKE": w["locke"]}
    return {k: names.get(v, v) for k, v in params.items()}


@req(EC, PARAMS, scenario="Границы параметров")
@pytest.mark.parametrize(("params", "kind", "reason"), BOUNDS)
def test_parameter_bounds(svc, w, events, params, kind, reason):
    response, mine = ask(svc, events, _resolve(params, w))
    assert response.status_code == 400, response.text
    assert response.json()["kind"] == kind
    rejected = [e for e in mine if e.name == REJECTED]
    assert len(rejected) == 1, [e.name for e in mine]
    assert rejected[0]["reason"] == reason
    assert not [e for e in events.items if e.name == SERVED]
    logged = json.dumps([e.fields for e in events.items], ensure_ascii=False, default=str)
    assert "17x0" not in logged and "culinary" not in logged


@req(EC, PARAMS, invariant="таблица отказов: прочие нарушения")
@pytest.mark.parametrize(
    ("params", "kind", "reason"),
    [
        ({"to": "1760"}, "bad_query", "window"),  # только to
        ({"from": "1760", "to": "1700"}, "bad_query", "window"),  # from > to
        ({"from": "1700.5", "to": "1760"}, "bad_query", "window"),  # не целое
        ({"from": "", "to": "1760"}, "bad_query", "window"),
        ({"epoch": "ENL", "to": "1760"}, "bad_query", "mode"),  # epoch и to
        ({"epoch": "nope_entity"}, "unknown_epoch", "unknown_epoch"),  # нет такой сущности
        ({"epoch": "ENL", "kinds": "political,culinary"}, "unknown_kind", "unknown_kind"),
        ({"from": "1700", "to": "1760", "kinds": "culinary"}, "unknown_kind", "unknown_kind"),
        ({"epoch": "ENL", "kinds": "Political"}, "unknown_kind", "unknown_kind"),
    ],
)
def test_parameter_table_more(svc, w, events, params, kind, reason):
    response, mine = ask(svc, events, _resolve(params, w))
    assert response.status_code == 400, response.text
    assert response.json()["kind"] == kind
    assert [e["reason"] for e in mine if e.name == REJECTED] == [reason]
    assert not [e for e in events.items if e.name == SERVED]


HOSTILE = '<script>alert("x")</script>'


@req(
    EC,
    PARAMS,
    invariant="события knowledge.context.* — только id, коды и числа: без значений параметров, "
    "названий и сведений о посетителе",
)
@pytest.mark.parametrize(
    "params",
    [
        {"epoch": "ENL", "kinds": HOSTILE},
        {"from": HOSTILE, "to": "1800"},
        {"epoch": HOSTILE},
        {"epoch": "ENL", "textbook": "Учебник-тайна", "lang": "ru"},
        {"from": "1600", "to": "1800", "textbook": "Учебник-тайна"},
    ],
)
def test_events_without_parameter_values(svc, w, events, params):
    sourced_link(svc.world, w)
    events.clear()
    response, _ = ask(svc, events, _resolve(params, w), region="DE")
    ours = [e for e in events.items if e.name.startswith("knowledge.context")]
    assert len(ours) == 1, [e.name for e in events.items]
    logged = json.dumps([e.fields for e in ours], ensure_ascii=False, default=str)
    for needle in (
        "script",
        "Учебник-тайна",
        "Просвещение",
        GLORIOUS,
        LOCKE_DOCTRINE,
        "Лондон",
        VISITOR_ADDRESS,
        "DE",
    ):
        assert needle not in logged, (needle, logged)
    for key, value in ours[0].fields.items():
        assert isinstance(value, (str, int, float, bool)) or value is None, (key, value)
    if response.status_code == 200:
        assert response.json()["events"]


# --- Пометка непроверенного контекста --------------------------------------------------


@req(EC, MARK, scenario="Сгенерированная связь помечена")
def test_generated_link_marked(svc, w, events):
    generated = generated_link(svc.world, w["newton"], w["locke_doctrine"])
    response, mine = ask(svc, events, {"epoch": w["enl"]})
    [link] = by_label(response.json())[NEWTON]["stimulated"]
    assert link["statement_id"] == generated
    assert link["generated"] is True
    assert link["status"] == "generated"
    assert served_of(mine)["generated_links"] == 1


@req(EC, MARK, scenario="Только проверенные")
def test_verified_only(svc, w, events):
    generated_link(svc.world, w["newton"], w["locke_doctrine"])
    sourced_link(svc.world, w)
    response, mine = ask(svc, events, {"epoch": w["enl"], "verified": "true"})
    body = response.json()
    statuses = [link["status"] for e in body["events"] for link in e["stimulated"]]
    assert "generated" not in statuses and statuses == ["sourced"]
    assert by_label(body)[NEWTON]["stimulated"] == []
    assert served_of(mine)["generated_links"] == 0
    assert served_of(mine)["links"] == 1


@req(EC, MARK, invariant="сгенерированная связь всегда с generated=true (API, все режимы)")
@pytest.mark.parametrize(
    "params",
    [
        {"epoch": "ENL"},
        {"epoch": "ENL", "textbook": TEXTBOOK_N},
        {"from": "1600", "to": "1800"},
        {"epoch": "ENL", "kinds": "scientific,economic"},
    ],
)
def test_generated_always_flagged(svc, w, events, params):
    world = svc.world
    generated_link(world, w["newton"], w["locke_doctrine"])
    generated_link(world, w["bubble"], world.thing("doctrine", "Меркантилизм"))
    world.relate(w["bubble"], "stimulated", world.thing("doctrine", "Физиократия"))
    verified = world.relate(w["newton"], "stimulated", world.thing("doctrine", "Ньютонианство"))
    world.statements.confirm(verified, "operator")
    response, mine = ask(svc, events, _resolve(params, w))
    links = [link for e in response.json()["events"] for link in e["stimulated"]]
    assert len(links) == 4
    for link in links:
        assert link["generated"] is (link["status"] == "generated"), link
    assert served_of(mine)["generated_links"] == 2


@req(EC, MARK, invariant="verified=true: ни одной generated; события без связей остаются")
@pytest.mark.parametrize("flag", ["true", "1"])
def test_verified_drops_generated_keeps_events(svc, w, events, flag):
    generated_link(svc.world, w["newton"], w["locke_doctrine"])
    generated_link(svc.world, w["glorious"], w["locke_doctrine"])
    generated_link(svc.world, w["bubble"], w["locke_doctrine"])
    response, mine = ask(svc, events, {"epoch": w["enl"], "verified": flag})
    body = response.json()
    assert [e["label"] for e in body["events"]] == [NEWTON, GLORIOUS, BUBBLE, ENCYCLOPEDIA]
    assert all(e["stimulated"] == [] for e in body["events"])
    assert served_of(mine)["generated_links"] == 0 and served_of(mine)["links"] == 0


@req(EC, MARK, invariant="сгенерированная связь помечена в карточке (generated=true)")
def test_generated_marked_in_card(svc, w, events):
    generated = generated_link(svc.world, w["newton"], w["locke_doctrine"])
    response, rid = svc.get(f"/v1/entities/{w['locke_doctrine']}/card")
    assert response.status_code == 200, response.text
    rows = [r for s in response.json()["sections"] for r in s["rows"]]
    [row] = [r for r in rows if r["statement_id"] == generated]
    assert row["generated"] is True
    assert events.where("knowledge.card.served", request_id=rid)


# --- Механизм влияния ------------------------------------------------------------------


@req(EC, MECH, scenario="Механизм вне списка")
def test_manual_unknown_mechanism_refused(svc, w, events):
    with pytest.raises(StatementError):
        svc.world.statements.add(
            w["glorious"],
            "stimulated",
            obj=w["locke_doctrine"],
            qualifiers={"mechanism": "culinary"},
            attributions=COMMON,
        )
    assert svc.world.statements.about(w["glorious"], types=["stimulated"]) == []
    [refused] = events.where("knowledge.statement.refused", type="stimulated")
    assert "culinary" in refused["reason"] and "mechanism" in refused["reason"]


@req(EC, MECH, invariant="механизм — только из списка реестра или отсутствует")
@pytest.mark.parametrize("value", ["culinary", "", "Political", "political ", "<b>x</b>", 1])
def test_manual_mechanism_outside_list(svc, w, events, value):
    with pytest.raises(StatementError):
        svc.world.statements.add(
            w["glorious"],
            "stimulated",
            obj=w["locke_doctrine"],
            qualifiers={"mechanism": value},
            attributions=COMMON,
        )
    assert svc.world.statements.about(w["glorious"], types=["stimulated"]) == []
    assert events.where("knowledge.statement.refused", type="stimulated")


@req(EC, MECH, invariant="все шесть механизмов списка принимаются и отдаются как есть")
@pytest.mark.parametrize("mechanism", MECHANISMS)
def test_listed_mechanisms(svc, w, events, mechanism):
    svc.world.relate(
        w["glorious"], "stimulated", w["locke_doctrine"], qualifiers={"mechanism": mechanism}
    )
    assert events.where("knowledge.statement.created", type="stimulated")
    [link] = by_label(ask(svc, events, {"epoch": w["enl"]})[0].json())[GLORIOUS]["stimulated"]
    assert link["mechanism"] == mechanism


@req(EC, MECH, scenario="Механизм не указан")
def test_mechanism_missing_is_null(svc, w, events):
    svc.world.relate(w["glorious"], "stimulated", w["locke_doctrine"])
    response, mine = ask(svc, events, {"epoch": w["enl"]})
    [link] = by_label(response.json())[GLORIOUS]["stimulated"]
    assert link["mechanism"] is None
    assert served_of(mine)["links"] == 1


# --- Контекст и закрытые источники -----------------------------------------------------


@req(EC, CLOSED, scenario="Цитат нет никогда")
@pytest.mark.parametrize("region", [None, "RU", "DE", "US"])
def test_no_quotes_ever(svc, w, events, region):
    svc.onto.paragraphs["p_1"] = "Был спрос на обучение риторике у граждан."
    sourced_link(svc.world, w)
    for params in ({"epoch": w["enl"]}, {"from": "1600", "to": "1800"}):
        response, mine = ask(svc, events, params, region=region)
        assert response.status_code == 200, response.text
        assert "спрос на обучение риторике" not in response.text
        assert "quote" not in response.text
        [link] = by_label(response.json())[GLORIOUS]["stimulated"]
        assert link["evidence"] == [{"paragraph_id": "p_1", "link": "/p/p_1"}]
        assert all(set(e) == {"paragraph_id", "link"} for e in link["evidence"])
        served_of(mine)


def _closed_link(svc, w):
    svc.onto.paragraphs["p_9"] = "Тогда парламент низложил короля."
    return svc.world.statements.add(
        w["glorious"],
        "stimulated",
        obj=w["locke_doctrine"],
        attributions=[Attribution("source", TEXTBOOK_R)],
        evidence=[Evidence("p_9", "парламент низложил короля", source_id=TEXTBOOK_R)],
        provenance=Provenance("extracted"),
    )


@req(
    EC,
    CLOSED,
    invariant="закрытый для региона источник: без id абзацев, ссылок и атрибуций "
    "ни в одном режиме; связь и статус видны",
)
@pytest.mark.parametrize("region", [None, "DE", "US"])
@pytest.mark.parametrize("mode", ["epoch", "window", "textbook"])
def test_closed_source_stripped(svc, w, events, region, mode):
    link_id = _closed_link(svc, w)
    params = {
        "epoch": {"epoch": w["enl"]},
        "window": {"from": "1600", "to": "1800"},
        "textbook": {"epoch": w["enl"], "textbook": TEXTBOOK_R},
    }[mode]
    response, mine = ask(svc, events, params, region=region)
    assert response.status_code == 200, response.text
    [link] = by_label(response.json())[GLORIOUS]["stimulated"]
    assert link["statement_id"] == link_id and link["status"] == "sourced"
    assert link["evidence"] == [] and link["attributed_to"] == []
    for needle in ("p_9", "/p/p_9", "парламент низложил короля", "Учебник R"):
        assert needle not in response.text, needle
    assert served_of(mine)["links"] == 1


@req(EC, CLOSED, invariant="регион берётся из заголовка X-Philograph-Region")
def test_region_from_header(svc, w, events):
    _closed_link(svc, w)
    opened, mine = ask(svc, events, {"epoch": w["enl"]}, region="RU")
    [link] = by_label(opened.json())[GLORIOUS]["stimulated"]
    assert link["evidence"] == [{"paragraph_id": "p_9", "link": "/p/p_9"}]
    assert link["attributed_to"] == ["Учебник R"]
    assert "парламент низложил короля" not in opened.text  # цитаты нет и для открытого
    served_of(mine)
    access = [c for c in svc.library_calls if c["path"].endswith("/internal/access")]
    assert access and access[-1].get("region") == "RU"


# --- после ревью, круг 1: поле events[].wikidata (дельта «Контекст эпохи») ---------------------


@req(EC, CTX, invariant="events[].wikidata — только идентификатор Q<число>, иначе null")
def test_event_wikidata_field(svc, w, events):
    with_qid = svc.onto.entities.create(
        "event", [("ru", "Французская революция", "primary")], external={"wikidata": "Q6534"}
    )
    svc.world.statements.add(with_qid, "dating", value=parse("1789").to_json(), attributions=COMMON)
    for params in ({"epoch": w["enl"]}, {"from": "1600", "to": "1800"}):
        response, mine = ask(svc, events, params)
        records = {e["id"]: e for e in response.json()["events"]}
        assert records[with_qid]["wikidata"] == "Q6534"
        assert records[w["glorious"]]["wikidata"] is None
        served_of(mine)


@req(EC, CTX, invariant="events[].wikidata: испорченный внешний идентификатор не отдаётся")
@pytest.mark.parametrize("value", ["Q12<script>", "q6534", "Q", "P31", "https://evil.example/Q1"])
def test_event_wikidata_hostile(svc, w, events, value):
    from sqlalchemy import insert

    from philograph.knowledge import schema

    event = svc.world.thing("event", "Событие с испорченным QID", "1720")
    with svc.onto.statements.engine.begin() as conn:  # запись в обход проверок — как старые данные
        conn.execute(
            insert(schema.external_ids).values(entity_id=event, system="wikidata", value=value)
        )
    response, mine = ask(svc, events, {"epoch": w["enl"]})
    record = {e["id"]: e for e in response.json()["events"]}[event]
    assert record["wikidata"] is None
    if len(value) > 1:  # «Q» как подстрока есть в любом теле
        assert value not in response.text
    served_of(mine)
