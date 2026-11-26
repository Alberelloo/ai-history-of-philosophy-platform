"""Юнит-тест разделов карточки эпохи (``cards.py:SECTIONS["epoch"]``)."""

from __future__ import annotations

from philograph.knowledge.cards import Cards
from philograph.knowledge.statements import Attribution


def test_epoch_card_sections(onto, events):
    enl = onto.thing("epoch", "Просвещение", "1680–1800")
    locke = onto.person("Локк", "1632", "1704")
    onto.person("Кант", "1724", "1804")  # только по датам — в карточке не показывается
    onto.statements.add(locke, "belongs_to_epoch", obj=enl, attributions=[Attribution("common")])
    card = Cards(onto.statements).card(enl)
    assert [(s["code"], s["title"]) for s in card["sections"]] == [
        ("dating", "Датировка"),
        ("members", "Относятся к эпохе"),
    ]
    assert [r["label"] for r in card["sections"][1]["rows"]] == ["Локк"]
    [event] = events.of("knowledge.card.served")
    assert (event["type"], event["sections"], event["rows"]) == ("epoch", 2, 2)
