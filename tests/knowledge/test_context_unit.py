"""Юнит-тесты разработчика для исторического контекста (изменение ``add-epoch-context``).

Сценарные и нормативные тесты по спецификации пишет тестировщик; здесь — проверки модулей.
"""

from __future__ import annotations

from sqlalchemy import func, select, update

from philograph.knowledge import schema
from philograph.knowledge.statements import Attribution

from ..library.conftest import lib  # noqa: F401
from .test_filling import _all, fill, st  # noqa: F401

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
