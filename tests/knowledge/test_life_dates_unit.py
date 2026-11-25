"""Юнит-тесты ``knowledge.life_dates`` (add-wikidata-life-dates, задача 2.6) на фикстурах
записей ``wd_records``; QID — только метки. Сценарные и нормативные тесты — у тестировщика."""

from __future__ import annotations

import pytest

from philograph.knowledge import schema as t
from philograph.knowledge.dates import parse, span
from philograph.knowledge.life_dates import LifeDates, ManifestError, main, validate
from philograph.knowledge.statements import Attribution
from tests.knowledge.wd_records import RecordFetch, record

HUMAN = ("Q5",)
PHILOSOPHER = "Q4964182"


def person(qid, ru=None, en=None, **times):
    return record(
        qid,
        ru=ru,
        en=en,
        classes=HUMAN,
        times={p: v for p, v in times.items()},
        items={"P106": [PHILOSOPHER, "Q193391"]},
    )


PLATO = person(
    "Q859", "Платон", "Plato", P569=("-0427-00-00T00:00:00Z", 9), P570=("-0347-00-00T00:00:00Z", 9)
)


def life(onto, fetch, **kw):
    return LifeDates(onto.statements, fetch, **kw)


def create(onto, name, type_="person", qid=None, lang="ru"):
    external = {"wikidata": qid} if qid else None
    return onto.entities.create(type_, [(lang, name, "primary")], external=external)


def entry(entity, qid, decision="accepted"):
    return {"entity": entity, "wikidata": qid, "decision": decision, "candidates": []}


def dates(onto, entity_id):
    return onto.entities.get(entity_id)["primary"].get("dates")


def test_validate_manifest_form():
    assert validate({"entities": []}) == []
    bad = {
        "entities": [
            entry("e1", None),
            entry("e1", "X1", "pending"),
            {"entity": "e2", "wikidata": None, "decision": "maybe"},
            {"entity": "e3", "candidates": [{"qid": "Q1", "holder": 5}]},
        ]
    }
    problems = validate(bad)
    assert len(problems) == 5, problems
    assert validate({}) == ["нет списка entities"]


def test_plato_bce_lifespan_and_roles(onto, events):
    plato = create(onto, "Платон", qid="Q859")
    report = life(onto, RecordFetch({"Q859": PLATO})).apply({"entities": []}, linked=True)
    d = dates(onto, plato)
    assert span(d) == (-426, -346)
    assert (d["precision"], d["original"]) == ("year", "427 до н. э. – 347 до н. э.")
    assert (report.lifespans, report.roles, report.externals) == (1, 1, 0)
    roles = onto.statements.about(plato, types=["person_role"])
    assert [r["value"] for r in roles] == ["philosopher"]
    assert all(r["attributions"][0]["who"] == "wikidata:Q859" for r in roles)
    # Повтор не добавляет утверждений; дата совпадает — unchanged.
    again = life(onto, RecordFetch({"Q859": PLATO})).apply({"entities": []}, linked=True)
    assert (again.lifespans, again.roles, again.unchanged) == (0, 0, 1)


def test_partial_bad_value_and_precision(onto, events):
    one = create(onto, "Один", qid="Q1")
    zero = create(onto, "Ноль", qid="Q2")
    rough = create(onto, "Грубо", qid="Q3")
    fetch = RecordFetch(
        {
            "Q1": person("Q1", "Один", P569=("+1600-00-00T00:00:00Z", 9)),
            "Q2": person(
                "Q2", "Ноль", P569=("+0000-00-00T00:00:00Z", 9), P570=("+1700-00-00T00:00:00Z", 9)
            ),
            "Q3": person(
                "Q3", "Грубо", P569=("+1680-00-00T00:00:00Z", 8), P570=("+1801-00-00T00:00:00Z", 7)
            ),
        }
    )
    report = life(onto, fetch).apply({"entities": []}, linked=True)
    assert dates(onto, one) is None and dates(onto, zero) is None
    skipped = {
        (e["entity"], e["property"], e["reason"])
        for e in events.where("knowledge.life_dates.skipped")
    }
    assert skipped == {(one, "P570", "partial"), (zero, "P569", "bad_value")}
    d = dates(onto, rough)
    assert (d["earliest_start"], d["latest_start"]) == (1680, 1689)
    assert (d["earliest_end"], d["latest_end"]) == (1801, 1900)
    assert d["precision"] == "century"
    assert report.lifespans == 1


def test_existing_dates_unchanged_and_conflict(onto, events):
    kant = create(onto, "Кант", qid="Q9312")
    other = create(onto, "Другой", qid="Q7")
    src = [Attribution("source", "s1")]
    for entity_id, text in ((kant, "1724–1804"), (other, "1600–1650")):
        onto.statements.add(entity_id, "lifespan", value=parse(text).to_json(), attributions=src)
    fetch = RecordFetch(
        {
            "Q9312": person(
                "Q9312",
                "Кант",
                P569=("+1724-04-22T00:00:00Z", 11),
                P570=("+1804-02-12T00:00:00Z", 11),
            ),
            "Q7": person(
                "Q7", "Другой", P569=("+1601-00-00T00:00:00Z", 9), P570=("+1660-00-00T00:00:00Z", 9)
            ),
        }
    )
    report = life(onto, fetch).apply({"entities": []}, linked=True)
    assert (report.unchanged, report.conflicts, report.lifespans) == (1, 1, 0)
    assert span(dates(onto, other)) == (1600, 1650)
    assert events.where("knowledge.life_dates.skipped", entity=other, reason="conflict")


def test_qid_rules_conflict_taken_twice(onto, events):
    kant = create(onto, "Кант", qid="Q9312")
    plato = create(onto, "Платон")
    plato_en = create(onto, "Plato", lang="en")
    manifest = {
        "entities": [entry(kant, "Q1"), entry(plato, "Q859"), entry(plato_en, "Q859", "auto")]
    }
    report = life(onto, RecordFetch({"Q859": PLATO})).apply(manifest)
    assert onto.entities.external_of(kant, "wikidata") == "Q9312"
    assert onto.entities.by_external("wikidata", "Q859") == plato
    reasons = [(e["entity"], e["reason"]) for e in events.where("knowledge.life_dates.skipped")]
    assert reasons == [(kant, "qid_conflict"), (plato_en, "qid_taken")]
    assert report.externals == 1
    # auto — в очередь, не слияние.
    assert events.where("knowledge.entity.merge_proposed", reason="review:qid_taken")
    assert not events.where("knowledge.entity.merged")


def test_qid_taken_accepted_merges(onto, events):
    hume = create(onto, "Hume", qid="Q41568", lang="en")
    yum = create(onto, "Юм")
    life(onto, RecordFetch()).apply({"entities": [entry(yum, "Q41568")]})
    assert onto.entities.resolve(yum) == onto.entities.resolve(hume)
    assert events.where("knowledge.entity.merged", reason="merge:qid_confirmed")


def test_dry_run_equal_report_and_no_writes(onto, events):
    plato = create(onto, "Платон")
    manifest = {"entities": [entry(plato, "Q859")]}
    before = _dump(onto)
    dry = life(onto, RecordFetch({"Q859": PLATO})).apply(manifest, dry_run=True)
    assert _dump(onto) == before
    real = life(onto, RecordFetch({"Q859": PLATO})).apply(manifest)
    strip = lambda r: {k: v for k, v in r.to_json().items() if k not in ("run_id", "dry_run")}  # noqa: E731
    assert strip(dry) == strip(real)
    summary = life(onto, RecordFetch()).rollback(real.run_id)
    assert _dump(onto) == before
    assert summary == {"run_id": real.run_id, "statements": 2, "externals": 1, "kept": 0}


def test_rollback_keeps_verified_and_its_qid(onto, events):
    plato = create(onto, "Платон")
    report = life(onto, RecordFetch({"Q859": PLATO})).apply({"entities": [entry(plato, "Q859")]})
    lifespan = onto.statements.about(plato, types=["lifespan"])[0]
    with onto.entities.engine.begin() as conn:
        conn.execute(
            t.statements.update()
            .where(t.statements.c.id == lifespan["id"])
            .values(status="verified")
        )
    summary = life(onto, RecordFetch()).rollback(report.run_id)
    assert summary["kept"] == 1 and summary["externals"] == 0
    assert onto.entities.external_of(plato, "wikidata") == "Q859"
    assert [s["type"] for s in onto.statements.about(plato)] == ["lifespan"]


def test_suggest_candidates_holder_and_auto(onto, events):
    plato = create(onto, "Платон")
    homer = create(onto, "Гомер", qid="Q6691")
    omir = create(onto, "Омир")
    not_human = record("Q1234567", ru="Платон", classes=("Q4167410",))
    homer_rec = person("Q6691", "Гомер", "Homer")
    fetch = RecordFetch(
        {"Q859": PLATO, "Q1234567": not_human, "Q6691": homer_rec},
        searches={
            ("Платон", "ru"): [{"id": "Q859"}, {"id": "Q1234567"}],
            ("Омир", "ru"): [{"id": "Q6691"}],
        },
    )
    before = _dump(onto)
    manifest = life(onto, fetch).suggest({"entities": []})
    assert _dump(onto) == before
    by_entity = {e["entity"]: e for e in manifest["entities"]}
    assert set(by_entity) == {plato, omir}
    assert [c["qid"] for c in by_entity[plato]["candidates"]] == ["Q859"]
    candidate = by_entity[plato]["candidates"][0]
    assert candidate["label"] == {"ru": "Платон", "en": "Plato"}
    assert (candidate["birth"], candidate["death"]) == ("427 до н. э.", "347 до н. э.")
    assert by_entity[omir]["candidates"][0]["holder"] == homer
    assert (by_entity[plato]["wikidata"], by_entity[plato]["decision"]) == (None, "pending")
    life(onto, fetch).suggest(manifest)
    assert len(events.where("knowledge.entity.merge_proposed", reason="review:qid_candidate")) == 1
    auto = life(onto, fetch).suggest({"entities": []}, auto_exact=True)
    by_entity = {e["entity"]: e for e in auto["entities"]}
    assert (by_entity[plato]["wikidata"], by_entity[plato]["decision"]) == ("Q859", "auto")
    assert by_entity[omir]["decision"] == "pending"  # подпись «Гомер» ≠ «Омир»
    assert events.where("knowledge.life_dates.suggested")[-1]["auto"] == 1


def test_work_dating(onto, events):
    work = create(onto, "Критика чистого разума", type_="work", qid="Q99")
    rec = record("Q99", ru="Критика", classes=(), times={"P577": ("+1781-00-00T00:00:00Z", 9)})
    report = life(onto, RecordFetch({"Q99": rec})).apply({"entities": []}, linked=True)
    assert span(dates(onto, work)) == (1781, 1781)
    assert report.datings == 1


def test_cli_bad_manifest_exit_2_without_service(tmp_path, capsys):
    path = tmp_path / "m.yaml"
    path.write_text("entities:\n- entity: e1\n  wikidata: null\n  decision: accepted\n")

    def service(_fetch):
        raise AssertionError("база и сеть до проверки формы")

    assert main(["apply", "--manifest", str(path)], service=service) == 2
    assert "entities[0]" in capsys.readouterr().err


def test_apply_rejects_bad_manifest(onto):
    with pytest.raises(ManifestError):
        life(onto, RecordFetch()).apply({"entities": [entry("e1", None)]})


def _dump(onto):
    from tests.knowledge.dump import dump

    return dump(onto.entities.engine)
