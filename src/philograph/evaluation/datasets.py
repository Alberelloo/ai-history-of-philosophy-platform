"""Наборы для оценки с версиями.

Элемент набора живёт в диапазоне версий ``[added, removed)``. Любое изменение — добавление,
правка, решение человека — поднимает версию набора; правка закрывает старую запись и открывает
новую. Поэтому прогон, сделанный на версии 3, всегда воспроизводим на версии 3.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Engine,
    Integer,
    MetaData,
    String,
    Table,
    and_,
    or_,
    select,
    update,
)

from philograph.platform import events
from philograph.platform.clock import Clock, SystemClock
from philograph.platform.db import Migrations

SCHEMA = "evaluation"
KINDS = ("questions", "mentions", "statements", "ocr_pages", "ontology_questions")
Status = Literal["draft", "confirmed", "rejected"]

metadata = MetaData()
datasets = Table(
    "datasets",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(100), nullable=False, unique=True),
    Column("kind", String(30), nullable=False),
    Column("version", Integer, nullable=False),
    # Регион, для читателя которого составлен набор: замеры повторяют его условия.
    # NULL — неизвестный регион (то, что видит читатель вне разрешённых стран).
    Column("region", String(2)),
    schema=SCHEMA,
)
items = Table(
    "items",
    metadata,
    Column("row_id", Integer, primary_key=True, autoincrement=True),
    Column("item_id", String(40), nullable=False, index=True),  # постоянный между правками
    Column("dataset_id", Integer, nullable=False, index=True),
    Column("added", Integer, nullable=False),
    Column("removed", Integer),
    Column("payload", JSON, nullable=False),
    Column("status", String(20), nullable=False),
    Column("decided_by", String(100)),
    Column("decided_at", DateTime(timezone=True)),
    schema=SCHEMA,
)


def _normalize_region(value: str | None) -> str | None:
    """Две латинские буквы в верхнем регистре; служебные ``XX``/``T1`` — неизвестный регион."""
    if not value:
        return None
    code = str(value).strip().upper()
    if code in {"XX", "T1"} or not (len(code) == 2 and code.isascii() and code.isalpha()):
        return None
    return code


migrations = Migrations(SCHEMA, metadata)
migrations.add(1, "наборы для оценки")(migrations.create_tables("datasets", "items"))


def _add_dataset_region(conn) -> None:
    """Регион набора: без него замеры шли бы без региона и не видели ограниченных источников."""
    from sqlalchemy import inspect, text

    columns = {c["name"] for c in inspect(conn).get_columns("datasets", schema=SCHEMA)}
    if "region" not in columns:  # база, созданная до этой миграции
        conn.execute(text(f"ALTER TABLE {SCHEMA}.datasets ADD COLUMN region VARCHAR(2)"))


migrations.add(3, "регион набора оценки")(_add_dataset_region)

events.define(
    "evaluation.dataset.changed",
    "info",
    "Набор для оценки изменился",
    required=("dataset", "version", "change"),
)
events.define(
    "evaluation.reference.broken",
    "warning",
    "Элемент набора ссылается на удалённый или перенаправленный абзац",
    required=("dataset", "item_id", "paragraph_id", "status"),
)


class ParagraphResolver(Protocol):
    def __call__(self, paragraph_id: str) -> dict[str, Any]: ...


class Datasets:
    def __init__(self, engine: Engine, clock: Clock | None = None) -> None:
        self.engine = engine
        self.clock = clock or SystemClock()

    def create(self, name: str, kind: str, *, region: str | None = None) -> int:
        """``region`` — для читателя какой страны составлен набор (``None`` — неизвестный)."""
        if kind not in KINDS:
            raise ValueError(f"вид набора: {', '.join(KINDS)}")
        code = _normalize_region(region)
        with self.engine.begin() as conn:
            return conn.execute(
                datasets.insert().values(name=name, kind=kind, version=0, region=code)
            ).inserted_primary_key[0]

    def region(self, dataset_id: int) -> str | None:
        with self.engine.begin() as conn:
            return conn.scalar(select(datasets.c.region).where(datasets.c.id == dataset_id))

    def _bump(self, conn, dataset_id: int, change: str) -> int:
        version = conn.scalar(select(datasets.c.version).where(datasets.c.id == dataset_id)) + 1
        conn.execute(update(datasets).where(datasets.c.id == dataset_id).values(version=version))
        name = conn.scalar(select(datasets.c.name).where(datasets.c.id == dataset_id))
        events.emit("evaluation.dataset.changed", dataset=name, version=version, change=change)
        return version

    def version(self, dataset_id: int) -> int:
        with self.engine.begin() as conn:
            return conn.scalar(select(datasets.c.version).where(datasets.c.id == dataset_id))

    def add(
        self,
        dataset_id: int,
        item_id: str,
        payload: dict[str, Any],
        *,
        status: Status = "confirmed",
        actor: str = "operator",
    ) -> int:
        """Элемент от человека — сразу подтверждён; черновик модели — ``status="draft"``."""
        with self.engine.begin() as conn:
            version = self._bump(conn, dataset_id, "add")
            conn.execute(
                items.insert().values(
                    item_id=item_id,
                    dataset_id=dataset_id,
                    added=version,
                    removed=None,
                    payload=payload,
                    status=status,
                    decided_by=None if status == "draft" else actor,
                    decided_at=None if status == "draft" else self.clock.now(),
                )
            )
        return version

    def decide(
        self,
        dataset_id: int,
        item_id: str,
        decision: Literal["confirm", "reject"],
        actor: str,
        payload: dict[str, Any] | None = None,
    ) -> int:
        """Решение человека по черновику: подтвердить (возможно, с исправлением) или отклонить."""
        status = "confirmed" if decision == "confirm" else "rejected"
        with self.engine.begin() as conn:
            current = (
                conn.execute(
                    select(items).where(
                        and_(
                            items.c.dataset_id == dataset_id,
                            items.c.item_id == item_id,
                            items.c.removed.is_(None),
                        )
                    )
                )
                .mappings()
                .one()
            )
            version = self._bump(conn, dataset_id, decision)
            conn.execute(
                update(items).where(items.c.row_id == current["row_id"]).values(removed=version)
            )
            conn.execute(
                items.insert().values(
                    item_id=item_id,
                    dataset_id=dataset_id,
                    added=version,
                    removed=None,
                    payload=payload or current["payload"],
                    status=status,
                    decided_by=actor,
                    decided_at=self.clock.now(),
                )
            )
        return version

    def snapshot(
        self, dataset_id: int, version: int | None = None, *, include_drafts: bool = False
    ) -> list[dict[str, Any]]:
        version = version if version is not None else self.version(dataset_id)
        with self.engine.begin() as conn:
            region = conn.scalar(select(datasets.c.region).where(datasets.c.id == dataset_id))
            rows = (
                conn.execute(
                    select(items)
                    .where(
                        and_(
                            items.c.dataset_id == dataset_id,
                            items.c.added <= version,
                            or_(items.c.removed.is_(None), items.c.removed > version),
                        )
                    )
                    .order_by(items.c.item_id)
                )
                .mappings()
                .all()
            )
        allowed = {"confirmed", "draft"} if include_drafts else {"confirmed"}
        # Регион набора повторяют замеры: без него запрос идёт как из неизвестного региона.
        return [
            {"item_id": r["item_id"], "status": r["status"], "region": region, **r["payload"]}
            for r in rows
            if r["status"] in allowed
        ]

    def counts(self, dataset_id: int, version: int | None = None) -> dict[str, int]:
        everything = self.snapshot(dataset_id, version, include_drafts=True)
        return {
            "confirmed": sum(i["status"] == "confirmed" for i in everything),
            "draft": sum(i["status"] == "draft" for i in everything),
        }

    def broken_references(
        self, dataset_id: int, resolve: ParagraphResolver
    ) -> list[dict[str, str]]:
        """Элементы, чьи абзацы удалены или перенаправлены в новых версиях источников."""
        with self.engine.begin() as conn:
            name = conn.scalar(select(datasets.c.name).where(datasets.c.id == dataset_id))
        broken = []
        for item in self.snapshot(dataset_id, include_drafts=True):
            for pid in item.get("relevant", []):
                resolved = resolve(pid)
                status = resolved["status"]
                if status != "found" or resolved.get("redirected"):
                    status = "redirected" if status == "found" else status
                    broken.append(
                        {"item_id": item["item_id"], "paragraph_id": pid, "status": status}
                    )
                    events.emit(
                        "evaluation.reference.broken",
                        dataset=name,
                        item_id=item["item_id"],
                        paragraph_id=pid,
                        status=status,
                    )
        return broken
