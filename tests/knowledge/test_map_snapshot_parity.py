"""Карта на общем снимке: ответ ``/v1/map`` на демо-данных не изменился, кэш ограничен.

Эталон ``fixtures/map/demo_map.json`` записан кодом карты до перехода на снимок
(``SectionMap._load``/``_fingerprint``) на тех же данных, что строит ``scripts/seed_demo.py``
(``seed_core`` + ``seed_map``). Обновлять эталон — только если карта меняется намеренно."""

from __future__ import annotations

import importlib.util
import itertools
import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select

from philograph.knowledge import schema as t
from philograph.knowledge.app import build_app
from philograph.knowledge.map import CACHE_KEYS, SectionMap
from philograph.knowledge.snapshot import Snapshots

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).parent / "fixtures" / "map" / "demo_map.json"
TEXTBOOK = "s_demo_textbook"
TEXTS = {
    "p_sleep": "Кант признавал, что Юм пробудил его от догматического сна.",
    "p_category": "Для Канта причинность — априорная категория рассудка.",
}


def _seed_demo():
    spec = importlib.util.spec_from_file_location("seed_demo", ROOT / "scripts" / "seed_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def demo_ontology(onto) -> None:
    seed = _seed_demo()
    onto.paragraphs.update(TEXTS)
    reading = SimpleNamespace(
        registry=SimpleNamespace(get=lambda _id: SimpleNamespace(title="Демо-учебник"))
    )
    seed.seed_core(onto.entities, onto.statements, reading, TEXTBOOK, TEXTS)
    seed.seed_map(onto.entities, onto.statements)
    # Упоминание в учебнике: область ``only_textbook`` берёт его из упоминаний.
    with onto.statements.engine.begin() as conn:
        conn.execute(
            t.mentions.insert().values(
                target_id="p_locke",
                target_kind="paragraph",
                source_id=TEXTBOOK,
                entity_id=onto.entities.find("Локк")[0]["id"],
                start=0,
                end=4,
                method="name",
            )
        )


def _stable(data, ids: dict[str, str]):
    """Идентификаторы сущностей и утверждений — случайные: заменяются подписями."""
    text = json.dumps(data, ensure_ascii=False, sort_keys=True)
    for raw, name in sorted(ids.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(raw, name)
    return json.loads(text)


def _ids(onto) -> dict[str, str]:
    snap_ids: dict[str, str] = {}
    with onto.statements.engine.begin() as conn:
        for entity_id, text in conn.execute(
            select(t.names.c.entity_id, t.names.c.text).where(t.names.c.kind == "primary")
        ):
            snap_ids.setdefault(entity_id, f"<{text}>")
        for statement_id, subject, type_, obj in conn.execute(
            select(
                t.statements.c.id,
                t.statements.c.subject,
                t.statements.c.type,
                t.statements.c.object,
            )
        ):
            snap_ids[statement_id] = f"<{snap_ids.get(subject)}:{type_}:{snap_ids.get(obj)}>"
    return snap_ids


def test_demo_map_unchanged_by_snapshot_refactor(onto, monkeypatch):
    # Идентификаторы по порядку создания: порядок связей и участников групп (по id) устойчив.
    counter = itertools.count(1)
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(int=next(counter) << 80))
    demo_ontology(onto)
    client = TestClient(build_app(onto.statements, section_map=SectionMap(onto.statements)))
    ids = _ids(onto)
    answers = {
        "all": client.get("/v1/map").json(),
        "textbook": client.get("/v1/map", params={"textbook": TEXTBOOK}).json(),
        "only_textbook": client.get(
            "/v1/map", params={"textbook": TEXTBOOK, "only_textbook": True}
        ).json(),
    }
    stable = _stable(answers, ids)
    if os.environ.get("PHILOGRAPH_WRITE_MAP_GOLDEN"):
        GOLDEN.write_text(json.dumps(stable, ensure_ascii=False, indent=1, sort_keys=True))
    assert stable == json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_map_cache_keeps_32_textbooks(onto, events):
    onto.person("Кант", "1724", "1804")
    section_map = SectionMap(onto.statements)
    for n in range(CACHE_KEYS):
        section_map.build(textbook=f"s_{n}")
    section_map.build(textbook="s_0")  # первый снова самый свежий
    section_map.build(textbook="s_new")  # 33-й ключ вытесняет давний — s_1
    assert len(section_map._cache) == CACHE_KEYS
    events.clear()
    section_map.build(textbook="s_0")
    section_map.build(textbook="s_1")
    assert [e.get("cached") for e in events.of("knowledge.map.built")] == [True, False]


def test_map_uses_shared_snapshot(onto, clock, events):
    onto.person("Кант", "1724", "1804")
    snapshots = Snapshots(onto.statements.engine, clock)
    snapshots.get(max_stale=15)
    SectionMap(onto.statements, snapshots=snapshots).build()
    assert len(events.of("knowledge.snapshot.built")) == 1  # карта взяла собранный снимок
    onto.person("Юм", "1711", "1776")
    data = SectionMap(onto.statements, snapshots=snapshots).build()
    assert [p["label"] for p in data["people"]] == ["Юм", "Кант"]  # без окна устарелости
    assert events.of("knowledge.snapshot.built")[-1].get("reason") == "changed"
