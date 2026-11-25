"""Юнит-тесты разработчика для исторического контекста (изменение ``add-epoch-context``).

Сценарные и нормативные тесты по спецификации пишет тестировщик; здесь — проверки модулей.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select, update

from philograph.knowledge import schema
from philograph.knowledge.statements import Attribution, Evidence, Provenance

from ..library.conftest import lib  # noqa: F401
from .conftest import TEXTBOOK_N
from .test_filling import _all, fill, st  # noqa: F401
from .wd_records import no_network  # noqa: F401

COMMON = [Attribution("common")]
OLD_EVENT_KINDS = ["political", "scientific", "religious", "intellectual", "biographical"]


def test_new_event_kinds_loaded_into_old_registry(onto, events):
    """Реестр, заполненный до 2.3: при старте дописываются ``economic`` и ``social``."""
    rt = schema.relation_types
    engine = onto.registry.engine
    revolution = onto.thing("event", "Славная революция", "1688–1689")
    onto.statements.add(revolution, "event_kind", value="political", attributions=COMMON)
    with engine.begin() as conn:
        spec = conn.execute(select(rt.c.spec).where(rt.c.code == "event_kind")).scalar_one()
        old = {**spec, "values": OLD_EVENT_KINDS}
        conn.execute(update(rt).where(rt.c.code == "event_kind").values(spec=old))
    onto.registry._cache = None
    assert "economic" not in onto.registry.relation("event_kind")["values"]
    with engine.begin() as conn:
        before_statements = conn.scalar(select(func.count()).select_from(schema.statements))
    before = onto.registry.version()
    events.clear()

    onto.registry.load_defaults()

    values = onto.registry.relation("event_kind")["values"]
    assert values == [*OLD_EVENT_KINDS, "economic", "social"]
    assert onto.registry.version() == before + 1
    changed = events.where("knowledge.registry.changed", version=before + 1)
    assert changed and "дозагрузка реестра" in changed[0]["change"]
    assert "event_kind" in changed[0]["change"]
    bubble = onto.thing("event", "Южноморский пузырь", "1720")
    onto.statements.add(bubble, "event_kind", value="economic", attributions=COMMON)
    assert events.where("knowledge.statement.created", type="event_kind")
    with engine.begin() as conn:
        after = conn.scalar(select(func.count()).select_from(schema.statements))
    assert after == before_statements + 2  # датировка и вид нового события


# --- 2.2: извлечение «стимулировало» без правки filling.py -----------------------------

QUOTE = "Всякое знание начинается с опыта"


def _stimulated(subject, obj, mechanism=None, subject_type="event", object_type="doctrine"):
    item = st(subject, "stimulated", obj, 1, QUOTE)
    item.update(subject_type=subject_type, object_type=object_type)
    if mechanism is not None:
        item["qualifiers"] = {"mechanism": mechanism}
    return item


def _stimulated_rows(fill):
    return [s for s in _all(fill) if s["type"] == "stimulated"]


def test_extraction_keeps_stimulated_with_mechanism(fill, events):
    source = fill.lib.register()
    item = _stimulated("Французская революция", "наукоучение", "political")
    fill.model.replies.append({"statements": [item]})
    fill.publish(source)
    rows = _stimulated_rows(fill)
    assert len(rows) == 1
    assert rows[0]["qualifiers"] == {"mechanism": "political"}
    assert rows[0]["status"] == "sourced" and rows[0]["evidence"]
    assert events.where("knowledge.statement.created", type="stimulated")
    fragments = events.of("knowledge.extraction.fragment")
    assert fragments[0]["created"] == 1 and fragments[0]["dropped"] == 0


def test_extraction_drops_unknown_mechanism_and_keeps_fragment(fill, events):
    source = fill.lib.register()
    bad = _stimulated("Французская революция", "наукоучение", "culinary")
    good = _stimulated("Славная революция", "политическая философия Локка", "political")
    fill.model.replies.append({"statements": [bad, good]})
    fill.publish(source)
    rows = _stimulated_rows(fill)
    assert [r["qualifiers"] for r in rows] == [{"mechanism": "political"}]
    reasons = [e["reason"] for e in events.of("knowledge.extraction.dropped")]
    assert any("culinary" in r for r in reasons), reasons
    fragments = events.of("knowledge.extraction.fragment")
    assert fragments[0]["created"] == 1 and fragments[0]["dropped"] == 1


def test_extraction_refuses_stimulated_from_person(fill, events):
    source = fill.lib.register()
    item = _stimulated("Локк", "эмпиризм", subject_type="person")
    fill.model.replies.append({"statements": [item]})
    fill.publish(source)
    assert _stimulated_rows(fill) == []
    reasons = [e["reason"] for e in events.of("knowledge.extraction.dropped")]
    assert any(r.startswith("тип stimulated не подходит концам") for r in reasons), reasons


# --- 3.1–3.2: контекст эпохи (``knowledge/context.py``, ``GET /v1/context``) ------------


@pytest.fixture
def ctx(svc):
    """Данные «Контекста Просвещения»: две эпохи, четыре события, Лондон, учение Локка."""
    w = svc.world
    d = {
        "sci": w.thing("epoch", "Научная революция", "1543–1687"),
        "enl": w.thing("epoch", "Просвещение", "1680–1800"),
        "newton": w.thing("event", "Выход «Начал» Ньютона", "1687"),
        "glorious": w.thing("event", "Славная революция", "1688–1689"),
        "bubble": w.thing("event", "Южноморский пузырь", "1720"),
        "encyclopedia": w.thing("event", "Выход первого тома «Энциклопедии»", "1751"),
        "london": w.thing("place", "Лондон"),
        "locke": w.thing("doctrine", "Политическая философия Локка"),
        "critique": w.thing("doctrine", "Критика религии"),
        "textbook": w.source(TEXTBOOK_N, "Учебник N"),
    }
    for event, kind in [
        ("newton", "scientific"),
        ("glorious", "political"),
        ("bubble", "economic"),
        ("encyclopedia", "intellectual"),
    ]:
        w.statements.add(d[event], "event_kind", value=kind, attributions=COMMON)
    w.relate(d["glorious"], "happened_in", d["london"])
    svc.onto.paragraphs["p_1"] = "Был спрос на обучение риторике у граждан."
    d["sourced"] = w.statements.add(
        d["glorious"],
        "stimulated",
        obj=d["locke"],
        qualifiers={"mechanism": "political"},
        attributions=[Attribution("source", TEXTBOOK_N)],
        evidence=[Evidence("p_1", "спрос на обучение риторике", source_id=TEXTBOOK_N)],
        provenance=Provenance("extracted"),
    )
    return d


def context(svc, params, region=None):
    response, rid = svc.get("/v1/context", params=params, region=region)
    return response, rid


def test_context_epoch_order_links_and_event(svc, ctx, events):
    events.clear()
    response, _ = context(svc, {"epoch": ctx["enl"], "textbook": TEXTBOOK_N})
    assert response.status_code == 200, response.text
    body = response.json()
    labels = [e["label"] for e in body["events"]]
    assert labels == [
        "Выход «Начал» Ньютона",
        "Славная революция",
        "Южноморский пузырь",
        "Выход первого тома «Энциклопедии»",
    ]
    glorious = body["events"][1]
    assert glorious["kind"] == "political" and glorious["basis"] == "dates"
    assert glorious["places"] == [{"id": ctx["london"], "label": "Лондон", "wikidata": None}]
    assert glorious["dates"]["from"] == 1688
    [link] = glorious["stimulated"]
    assert link["target"] == {
        "id": ctx["locke"],
        "label": "Политическая философия Локка",
        "type": "doctrine",
    }
    assert (link["mechanism"], link["status"], link["generated"]) == ("political", "sourced", False)
    assert link["in_textbook"] is True and link["attributed_to"] == ["Учебник N"]
    assert link["evidence"] == [{"paragraph_id": "p_1", "link": "/p/p_1"}]
    assert "спрос на обучение" not in response.text  # цитат нет никогда
    assert body["counts"] == {"scientific": 1, "political": 1, "economic": 1, "intellectual": 1}
    assert body["epoch"] == {"id": ctx["enl"], "label": "Просвещение", "from": 1680, "to": 1800}
    assert body["window"] is None and body["truncated"] is False
    [served] = events.of("knowledge.context.served")
    assert (served["mode"], served["events"], served["links"]) == ("epoch", 4, 1)
    assert served["generated_links"] == 0 and served["truncated"] is False


def test_context_window_kinds_and_verified(svc, ctx, events):
    body = context(svc, {"from": "1700", "to": "1760"})[0].json()
    assert [e["label"] for e in body["events"]] == [
        "Южноморский пузырь",
        "Выход первого тома «Энциклопедии»",
    ]
    assert body["epoch"] is None and body["window"] == {"from": 1700, "to": 1760}
    assert all(e["basis"] is None for e in body["events"])

    filtered = context(svc, {"epoch": ctx["enl"], "kinds": "political,economic"})[0].json()
    assert [e["label"] for e in filtered["events"]] == ["Славная революция", "Южноморский пузырь"]
    assert filtered["counts"]["scientific"] == 1  # счётчики без учёта kinds

    svc.world.statements.add(
        ctx["newton"],
        "stimulated",
        obj=ctx["locke"],
        attributions=COMMON,
        provenance=Provenance("generated"),
    )
    body = context(svc, {"epoch": ctx["enl"]})[0].json()
    [gen] = body["events"][0]["stimulated"]
    assert gen["generated"] is True and gen["status"] == "generated" and gen["mechanism"] is None
    events.clear()
    body = context(svc, {"epoch": ctx["enl"], "verified": "true"})[0].json()
    assert body["events"][0]["label"] == "Выход «Начал» Ньютона"
    assert body["events"][0]["stimulated"] == []
    assert events.of("knowledge.context.served")[0]["generated_links"] == 0


def test_context_closed_source_and_rejected_link(svc, ctx):
    svc.onto.paragraphs["p_9"] = "Тогда парламент низложил короля."
    closed_link = svc.world.statements.add(
        ctx["encyclopedia"],
        "stimulated",
        obj=ctx["locke"],
        attributions=[Attribution("source", "s_textbook_r")],
        evidence=[Evidence("p_9", "парламент низложил короля", source_id="s_textbook_r")],
        provenance=Provenance("extracted"),
    )
    rejected = svc.world.relate(ctx["encyclopedia"], "stimulated", ctx["critique"])
    svc.onto.statements.reject(rejected, "operator")
    response, _ = context(svc, {"epoch": ctx["enl"]}, region="DE")
    events_ = {e["label"]: e for e in response.json()["events"]}
    [link] = events_["Выход первого тома «Энциклопедии»"]["stimulated"]
    assert link["statement_id"] == closed_link and link["status"] == "sourced"
    assert link["evidence"] == [] and link["attributed_to"] == []
    assert "p_9" not in response.text and "парламент" not in response.text
    opened = context(svc, {"epoch": ctx["enl"]}, region="RU")[0].json()
    shown = {e["label"]: e for e in opened["events"]}["Выход первого тома «Энциклопедии»"]
    assert shown["stimulated"][0]["evidence"] == [{"paragraph_id": "p_9", "link": "/p/p_9"}]


@pytest.mark.parametrize(
    ("params", "kind", "reason"),
    [
        ({"epoch": "ENL", "from": "1700", "to": "1760"}, "bad_query", "mode"),
        ({}, "bad_query", "mode"),
        ({"from": "1700"}, "bad_query", "window"),
        ({"from": "17x0", "to": "1800"}, "bad_query", "window"),
        ({"from": "1800", "to": "1800"}, "bad_query", "window"),
        ({"epoch": "LOCKE"}, "unknown_epoch", "unknown_epoch"),
        ({"epoch": "ENL", "kinds": "culinary"}, "unknown_kind", "unknown_kind"),
    ],
)
def test_context_rejects_parameters(svc, ctx, events, params, kind, reason):
    params = {
        k: ctx["enl"] if v == "ENL" else ctx["locke"] if v == "LOCKE" else v
        for k, v in params.items()
    }
    events.clear()
    response, _ = context(svc, params)
    assert response.status_code == 400 and response.json()["kind"] == kind
    assert [e["reason"] for e in events.of("knowledge.context.rejected")] == [reason]
    assert not events.of("knowledge.context.served")
    logged = str([e.fields if hasattr(e, "fields") else e for e in events.items])
    assert "17x0" not in logged and "culinary" not in logged


def test_context_limits(svc, ctx, onto, clock):
    from philograph.knowledge.context import Context

    for i in range(3):
        svc.world.relate(ctx["bubble"], "stimulated", svc.world.thing("doctrine", f"Учение {i}"))
    small = Context(svc.catalog, max_events=2, max_links=2)
    body = small.get(epoch=ctx["enl"])
    assert body["truncated"] is True
    assert len(body["events"]) == 2
    # Самые значимые: пузырь (вид, датировка, три связи) и Славная революция.
    assert [e["label"] for e in body["events"]] == ["Славная революция", "Южноморский пузырь"]
    assert len(body["events"][1]["stimulated"]) == 2
    assert sum(body["counts"].values()) == 4  # счётчики до усечения


# --- 3.3: раздел карточки «Исторический контекст» ------------------------------------


def test_card_context_section(svc, ctx, events):
    from philograph.knowledge.cards import SECTIONS, Cards

    generated = svc.world.statements.add(
        ctx["newton"],
        "stimulated",
        obj=ctx["locke"],
        attributions=COMMON,
        provenance=Provenance("generated"),
    )
    events.clear()
    card = Cards(svc.onto.statements).card(ctx["locke"])
    assert [s["code"] for s in card["sections"]] == ["context"]
    rows = card["sections"][0]["rows"]
    assert [r["label"] for r in rows] == ["Славная революция", "Выход «Начал» Ньютона"]
    assert rows[0]["qualifiers"] == {"mechanism": "political"} and rows[0]["evidence"]
    assert rows[1]["statement_id"] == generated and rows[1]["generated"] is True
    assert rows[1]["qualifiers"] == {} and rows[0]["inverse"] is True
    [served] = events.of("knowledge.card.served")
    assert (served["sections"], served["rows"]) == (1, 2)
    for type_ in ("concept", "person", "work", "doctrine", "problem", "position", "argument"):
        assert "context" in [code for code, *_ in SECTIONS[type_]], type_


# --- 3.4: ``stimulated`` у событий карты ----------------------------------------------


def test_map_event_stimulated(svc, events):
    from philograph.knowledge.map import SectionMap

    w = svc.world
    revolution = w.thing("event", "Французская революция", "1789")
    fichte = w.person("Фихте", "1762", "1814")
    schelling = w.person("Шеллинг", "1775", "1854")
    basis = w.thing("work", "Основа общего наукоучения", "1794")
    undated = w.thing("concept", "Свобода")
    w.relate(basis, "author", fichte)
    w.relate(revolution, "stimulated", basis, qualifiers={"mechanism": "political"})
    w.statements.add(
        revolution,
        "stimulated",
        obj=schelling,
        attributions=COMMON,
        provenance=Provenance("generated"),
    )
    w.relate(revolution, "stimulated", undated)
    lonely = w.thing("event", "Южноморский пузырь", "1720")
    data = SectionMap(svc.onto.statements, snapshots=svc.snapshots).build()
    by_id = {e["id"]: e for e in data["events"]}
    assert by_id[revolution]["stimulated"] == [
        {"id": basis, "generated": False},
        {"id": schelling, "generated": True},
    ]
    assert "stimulated" not in by_id[lonely]
    assert events.of("knowledge.map.built")


# --- 3.5: демо-данные контекста ------------------------------------------------------


def test_demo_seed_context(svc):
    from types import SimpleNamespace

    from .test_map_snapshot_parity import TEXTBOOK, TEXTS, _seed_demo

    seed = _seed_demo()
    svc.onto.paragraphs.update(TEXTS)
    reading = SimpleNamespace(
        registry=SimpleNamespace(get=lambda _id: SimpleNamespace(title="Демо-учебник"))
    )
    entities, statements = svc.onto.entities, svc.onto.statements
    seed.seed_core(entities, statements, reading, TEXTBOOK, TEXTS)
    seed.seed_map(entities, statements)
    seed.seed_reference(entities, statements)
    seed.seed_epochs(entities, statements)
    seed.seed_context(entities, statements)
    enlightenment = entities.find("Просвещение")[0]["id"]
    response, _ = context(svc, {"epoch": enlightenment})
    by_label = {e["label"]: e for e in response.json()["events"]}
    glorious = by_label["Славная революция"]
    assert [p["label"] for p in glorious["places"]] == ["Лондон"]
    [link] = glorious["stimulated"]
    assert (link["mechanism"], link["status"]) == ("political", "sourced")
    [gen] = by_label["Выход первого тома «Энциклопедии»"]["stimulated"]
    assert gen["generated"] is True and gen["mechanism"] is None
    bubble = by_label["Южноморский пузырь"]
    assert bubble["kind"] == "economic" and bubble["stimulated"] == []


# --- 4.1–4.3: события эпох из Wikidata (``knowledge/epoch_context.py``) ----------------

EPOCHS_YAML = {"epochs": [{"ru": "Просвещение", "wikidata": "Q910001", "candidates": []}]}


def _rows(onto) -> dict[str, int]:
    tables = (schema.entities, schema.statements, schema.attributions, schema.external_ids)
    with onto.registry.engine.begin() as conn:
        return {tbl.name: conn.scalar(select(func.count()).select_from(tbl)) for tbl in tables}


@pytest.fixture
def importer(onto):
    from philograph.knowledge.epoch_context import EpochContextImport

    onto.thing("epoch", "Просвещение", "1680–1800")
    return EpochContextImport(onto.statements)


def test_harvest_candidates(onto, importer, events, no_network):
    from philograph.knowledge.epoch_context import harvest

    from .wikidata_fixtures import FixtureFetch

    before = _rows(onto)
    manifest = harvest(EPOCHS_YAML, {"epochs": []}, FixtureFetch())
    [entry] = manifest["epochs"]
    assert (entry["epoch"], entry["qid"]) == ("Просвещение", "Q910001")
    revolution, quake = entry["candidates"]
    assert revolution["qid"] == "Q910011" and revolution["kind"] == "political"
    assert revolution["place"] == {"qid": "Q910021", "label": {"ru": "Париж", "en": "Paris"}}
    assert revolution["decision"] == "pending"
    assert quake["qid"] == "Q910012" and quake["kind"] is None and quake["place"] is None
    assert _rows(onto) == before
    [done] = events.of("knowledge.context_import.harvested")
    assert (done["epochs"], done["candidates"]) == (1, 2)

    revolution["decision"] = "accepted"
    revolution["kind"] = "social"  # правка человека
    again = harvest(EPOCHS_YAML, manifest, FixtureFetch())
    assert [c["qid"] for c in again["epochs"][0]["candidates"]] == ["Q910011", "Q910012"]
    kept = again["epochs"][0]["candidates"][0]
    assert (kept["decision"], kept["kind"]) == ("accepted", "social")


def _accepted_manifest(**changes):
    candidate = {
        "qid": "Q910011",
        "label": {"ru": "Французская революция"},
        "kind": "political",
        "place": {"qid": "Q910021", "label": {"ru": "Париж"}},
        "decision": "accepted",
        **changes,
    }
    return {"epochs": [{"epoch": "Просвещение", "qid": "Q910001", "candidates": [candidate]}]}


def test_apply_accepted_then_exists_and_dry_run(onto, importer, events, no_network):
    from .wikidata_fixtures import FixtureFetch

    report = importer.apply(_accepted_manifest(), FixtureFetch())
    assert report.totals() == {"created": 1, "statements": 4, "places_created": 1, "skipped": 0}
    event = onto.entities.by_external("wikidata", "Q910011")
    paris = onto.entities.by_external("wikidata", "Q910021")
    assert onto.entities.label(event) == "Французская революция"
    assert onto.entities.label(paris) == "Париж"
    rows = [s for s in onto.statements.about(event, derived=False) if s["direction"] == "out"]
    assert sorted(s["type"] for s in rows) == [
        "belongs_to_epoch",
        "dating",
        "event_kind",
        "happened_in",
    ]
    assert all(s["status"] == "sourced" for s in rows)
    assert all(a["who"] == "wikidata:Q910011" for s in rows for a in s["attributions"])
    belongs = next(s for s in rows if s["type"] == "belongs_to_epoch")
    assert belongs["qualifiers"] == {"membership_basis": "historians"}
    assert not [s for s in rows if s["type"] == "stimulated"]
    assert events.where("knowledge.context_import.checked", qid="Q910011", result="created")
    [run] = events.of("knowledge.context_import.run")
    assert run["mode"] == "apply" and run["created"] == 1 and run["places_created"] == 1

    before = _rows(onto)
    again = importer.apply(_accepted_manifest(), FixtureFetch())
    assert again.candidates[0]["result"] == "exists"
    assert again.totals()["created"] == 0 and again.totals()["statements"] == 0
    assert _rows(onto) == before

    fresh = _accepted_manifest(qid="Q910012", label={"ru": "Лиссабонское землетрясение"})
    fresh["epochs"][0]["candidates"][0].update(kind=None, place=None)
    dry = importer.apply(fresh, FixtureFetch(), dry_run=True)
    assert dry.mode == "dry_run" and dry.totals()["created"] == 1
    assert dry.totals()["statements"] == 2  # датировка и эпоха: вида и места нет
    assert _rows(onto) == before


def test_apply_skips_pending_rejected_no_date_and_failed(onto, importer, events, no_network):
    from .wikidata_fixtures import FixtureFetch

    manifest = _accepted_manifest(decision="pending")
    candidates = manifest["epochs"][0]["candidates"]
    candidates.append({**candidates[0], "qid": "Q910012", "decision": "rejected"})
    candidates.append({**candidates[0], "qid": "Q910013", "decision": "accepted"})
    candidates.append({**candidates[0], "qid": "Q910099", "decision": "accepted"})
    before = _rows(onto)
    report = importer.apply(manifest, FixtureFetch())
    assert [c["result"] for c in report.candidates] == [
        "pending",
        "rejected",
        "no_date",
        "fetch_failed",
    ]
    assert report.totals()["skipped"] == 4 and _rows(onto) == before


def test_apply_refuses_unknown_kind_and_missing_epoch(onto, events):
    from philograph.knowledge.epoch_context import EpochContextImport
    from philograph.knowledge.epoch_dates import ManifestError

    from .wikidata_fixtures import FixtureFetch

    importer = EpochContextImport(onto.statements)
    with pytest.raises(ManifestError, match="нет в онтологии"):
        importer.apply(_accepted_manifest(), FixtureFetch())
    onto.thing("epoch", "Просвещение", "1680–1800")
    with pytest.raises(ManifestError, match="culinary"):
        importer.apply(_accepted_manifest(kind="culinary"), FixtureFetch())
    assert not events.of("knowledge.context_import.run")


def test_cli_harvest_writes_manifest(tmp_path, onto, no_network):
    import yaml

    from philograph.knowledge.epoch_context import EpochContextImport, main

    from .wikidata_fixtures import FixtureFetch

    epochs = tmp_path / "epochs.yaml"
    epochs.write_text(yaml.safe_dump(EPOCHS_YAML, allow_unicode=True), encoding="utf-8")
    manifest = tmp_path / "epoch_context.yaml"
    manifest.write_text("# шапка\nepochs: []\n", encoding="utf-8")
    service = lambda: EpochContextImport(onto.statements)  # noqa: E731
    code = main(
        ["harvest", "--epochs", str(epochs), "--manifest", str(manifest)],
        fetch=FixtureFetch(),
        service=service,
    )
    assert code == 0
    text = manifest.read_text(encoding="utf-8")
    assert text.startswith("# шапка\n") and "Q910011" in text
    bad = tmp_path / "bad.yaml"
    bad.write_text("epochs:\n- epoch: X\n  qid: nope\n", encoding="utf-8")
    assert main(["apply", "--manifest", str(bad)], fetch=FixtureFetch(), service=service) == 2
