"""Юнит-тесты разработчика для исторического контекста (изменение ``add-epoch-context``).

Сценарные и нормативные тесты по спецификации пишет тестировщик; здесь — проверки модулей.
"""

from __future__ import annotations

from sqlalchemy import func, select, update

from philograph.knowledge import schema
from philograph.knowledge.statements import Attribution

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
