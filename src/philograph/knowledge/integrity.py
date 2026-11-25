"""Сохранность утверждений и атрибуций (спецификация ontology-migration, «Учёт утверждений
при проверке сохранности»): общий для шага миграции ``verify`` и замера А8.

``baseline(engine)`` запоминает действующие утверждения (не отклонённые, не «устаревшие»,
любой видимости) и их атрибуции ``(вид, автор, позиция)``. ``compare(baseline, engine)``
сопоставляет каждое с нынешним: id → (свёртка при слиянии, ``merges.moved.folded[].into``)
→ утверждение. Утверждение

- *мусор* (``dropped_garbage``), если его конец (с учётом перенаправлений) снят;
- *петля*, если стало петлёй при слиянии (``merges.moved.loops``) — не потеря;
- *потеряно* (``lost``), если иначе его нет, оно не действующее или подменено: у цели другой
  тип или её концы не равны образам исходных концов через карту перенаправлений.

Атрибуция *потеряна*, если её ``(вид, автор с учётом перенаправлений, позиция)`` нет у
утверждения, в которое попало исходное; точный повтор после свёртки и автор — снятая
сущность потерей не считаются. Только чтение базы.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from philograph.knowledge import schema as t

AttrKey = tuple[str, str | None, str]


@dataclass(frozen=True)
class Baseline:
    statements: dict[str, dict[str, Any]]  # id → {subject, object, type}
    attributions: dict[str, Counter[AttrKey]]

    def to_json(self) -> dict[str, Any]:
        return {
            "statements": self.statements,
            "attributions": {
                sid: [[*key, n] for key, n in sorted(c.items(), key=str)]
                for sid, c in self.attributions.items()
            },
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Baseline:
        return cls(
            statements=dict(data["statements"]),
            attributions={
                sid: Counter({(k, w, s): n for k, w, s, n in rows})
                for sid, rows in data["attributions"].items()
            },
        )


def _live(row: Any) -> bool:
    return row["status"] != "rejected" and row["rank"] != "deprecated"


def _attributions(conn: Any) -> dict[str, list[AttrKey]]:
    found: dict[str, list[AttrKey]] = {}
    for r in conn.execute(select(t.attributions)).mappings():
        found.setdefault(r["statement_id"], []).append((r["who_kind"], r["who"], r["stance"]))
    return found


def baseline(engine: Any) -> Baseline:
    with engine.begin() as conn:
        rows = conn.execute(select(t.statements)).mappings().all()
        attrs = _attributions(conn)
    live = [r for r in rows if _live(r)]
    return Baseline(
        statements={
            r["id"]: {"subject": r["subject"], "object": r["object"], "type": r["type"]}
            for r in live
        },
        attributions={r["id"]: Counter(attrs.get(r["id"], [])) for r in live},
    )


def _state(engine: Any) -> dict[str, Any]:
    with engine.begin() as conn:
        query = [t.entities.c.id, t.entities.c.redirect_to]
        has_retired = t.has_retired(conn)  # схема до knowledge:9 — снятых нет
        if has_retired:
            query.append(t.entities.c.retired_run)
        entities = conn.execute(select(*query)).all()
        statements = {r["id"]: r for r in conn.execute(select(t.statements)).mappings()}
        attrs = _attributions(conn)
        merges = conn.execute(
            select(t.merges.c.moved).where(t.merges.c.undone.is_(False))
        ).scalars()
        folded: dict[str, str] = {}
        loops: set[str] = set()
        for moved in merges:
            for f in (moved or {}).get("folded") or []:
                folded[f["id"]] = f["into"]
            loops.update((moved or {}).get("loops") or [])
    redirect = {row[0]: row[1] for row in entities if row[1]}
    retired = {row[0] for row in entities if has_retired and row[2]}
    return {
        "redirect": redirect,
        "retired": retired,
        "statements": statements,
        "attributions": attrs,
        "folded": folded,
        "loops": loops,
    }


def _same(row: Any, content: dict[str, Any], ends: list[str | None], resolve: Any) -> bool:
    """Цель — то же утверждение: тот же тип, концы — образы исходных через перенаправления."""
    return (
        row["type"] == content["type"]
        and [
            resolve(row["subject"]),
            resolve(row["object"]),
        ]
        == ends
    )


def _follow(mapping: dict[str, str], key: str | None) -> str | None:
    seen = set()
    while key in mapping and key not in seen:
        seen.add(key)
        key = mapping[key]
    return key


def compare(base: Baseline, engine: Any) -> dict[str, Any]:
    """Потери относительно базы сравнения: ``lost`` (id утверждений), ``lost_attributions``
    (``[id, вид, автор, позиция]``), ``folded``, ``dropped_garbage``, ``loops`` — числа."""
    state = _state(engine)
    redirect, retired = state["redirect"], state["retired"]
    lost: list[str] = []
    lost_attributions: list[list[Any]] = []
    folded = garbage = loops = 0

    def resolve(entity_id: str | None) -> str | None:
        return _follow(redirect, entity_id)

    for sid, content in sorted(base.statements.items()):
        target = _follow(state["folded"], sid)
        if target != sid:
            folded += 1
        ends = [resolve(content["subject"]), resolve(content["object"])]
        if any(e in retired for e in ends if e):
            garbage += 1
            continue
        if sid in state["loops"] or target in state["loops"]:
            loops += 1
            continue
        row = state["statements"].get(target)
        if row is None or not _live(row) or not _same(row, content, ends, resolve):
            lost.append(sid)
            continue
        have = {
            (kind, resolve(who) if kind == "entity" else who, stance)
            for kind, who, stance in state["attributions"].get(target, [])
        }
        for kind, who, stance in sorted(base.attributions.get(sid, Counter()), key=str):
            who_now = resolve(who) if kind == "entity" else who
            if kind == "entity" and who_now in retired:
                continue  # автор снят — не потеря
            if (kind, who_now, stance) not in have:
                lost_attributions.append([sid, kind, who, stance])
    return {
        "lost": lost,
        "lost_attributions": lost_attributions,
        "folded": folded,
        "dropped_garbage": garbage,
        "loops": loops,
    }


def save(base: Baseline, path: Path) -> None:
    path.write_text(json.dumps(base.to_json(), ensure_ascii=False, sort_keys=True), "utf-8")


def load(path: Path) -> Baseline:
    return Baseline.from_json(json.loads(path.read_text(encoding="utf-8")))
