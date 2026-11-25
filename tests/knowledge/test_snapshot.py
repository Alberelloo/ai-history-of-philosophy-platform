"""Юнит-тесты снимка данных онтологии (``knowledge/snapshot.py``)."""

from __future__ import annotations

import threading

from philograph.knowledge import snapshot as snapshot_module
from philograph.knowledge.snapshot import Snapshots
from philograph.knowledge.statements import Attribution


def test_first_then_cached(onto, clock, events):
    onto.person("Кант", "1724", "1804")
    snapshots = Snapshots(onto.statements.engine, clock)
    first, status = snapshots.get(max_stale=15)
    assert status == "fresh"
    again, status = snapshots.get(max_stale=15)
    assert status == "cached" and again is first
    built = events.one("knowledge.snapshot.built")
    assert built.get("reason") == "first"
    assert built.get("entities") == 1 and built.get("statements") == 1
    assert isinstance(built.get("took_ms"), float)
    assert first.built_at == clock.now()


def test_stale_inside_window_fresh_after(onto, clock, events):
    snapshots = Snapshots(onto.statements.engine, clock)
    first, _ = snapshots.get(max_stale=15)
    clock.advance(seconds=1)
    fichte = onto.person("Фихте")
    clock.advance(seconds=4)
    same, status = snapshots.get(max_stale=15)
    assert status == "stale" and same is first and fichte not in same.entities
    clock.advance(seconds=10)  # снимку ровно 15 с — окно кончилось
    fresh, status = snapshots.get(max_stale=15)
    assert status == "fresh" and fichte in fresh.entities
    assert [e.get("reason") for e in events.of("knowledge.snapshot.built")] == ["first", "changed"]


def test_zero_window_rebuilds_on_any_change(onto, clock):
    snapshots = Snapshots(onto.statements.engine, clock)
    kant = onto.person("Кант")
    snapshots.get()
    onto.statements.add(
        kant,
        "description",
        value="Немецкий философ",
        attributions=[Attribution("common")],
    )
    snap, status = snapshots.get(max_stale=0)
    assert status == "fresh"
    assert [s["type"] for s in snap.statements] == ["description"]


def test_snapshot_rules(onto, clock):
    kant = onto.person("Кант", "1724", "1804")
    dup = onto.person("Кант (дубль)")
    onto.entities.add_name(kant, "de", "Kant")
    onto.entities.merge(kant, dup)
    rejected = onto.statements.add(
        kant, "description", value="плохое", attributions=[Attribution("common")]
    )
    onto.statements.reject(rejected, "operator")
    snap, _ = Snapshots(onto.statements.engine, clock).get()
    assert set(snap.entities) == {kant}
    assert snap.labels[kant] == "Кант"
    # Названия — по порядку записи.
    assert [n["text"] for n in snap.names[kant]] == ["Кант", "Кант (дубль)", "Kant"]
    assert [s["type"] for s in snap.statements] == ["lifespan"]


def test_derived_built_once_per_snapshot(onto, clock):
    snapshots = Snapshots(onto.statements.engine, clock)
    snap, _ = snapshots.get()
    calls = []

    def build(s):
        calls.append(s)
        return object()

    assert snap.derived("x", build) is snap.derived("x", build)
    assert len(calls) == 1


def test_parallel_requests_build_once(onto, clock, events, monkeypatch):
    onto.person("Кант")
    snapshots = Snapshots(onto.statements.engine, clock)
    entered = threading.Event()
    release = threading.Event()
    real_load = snapshot_module.load

    def slow_load(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return real_load(*args, **kwargs)

    monkeypatch.setattr(snapshot_module, "load", slow_load)
    results = []

    def request():
        results.append(snapshots.get(max_stale=15))

    first = threading.Thread(target=request)
    first.start()
    assert entered.wait(5)
    second = threading.Thread(target=request)
    second.start()
    second.join(0.2)  # второй ждёт блокировку, а не строит свой снимок
    assert second.is_alive()
    release.set()
    first.join(5)
    second.join(5)
    assert sorted(status for _, status in results) == ["cached", "fresh"]
    assert results[0][0] is results[1][0]
    assert len(events.of("knowledge.snapshot.built")) == 1
