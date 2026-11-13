"""Портреты персон: черновики отбора, проверка оператором и раздача.

Изображения живут в ``FileStore`` (адресация по sha256), сведения о них и порядок — в таблице
``portraits`` схемы знаний. Читателю отдаются только подтверждённые и нескрытые изображения;
смена главного переставляет ``position`` без потери остальных.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, and_, func, select, update

from philograph.knowledge import schema as t
from philograph.platform import events
from philograph.platform.clock import Clock, SystemClock
from philograph.platform.files import FileStore

events.define(
    "knowledge.portrait.added",
    "info",
    "Добавлен черновик портрета",
    required=("portrait_id", "entity_id"),
)
events.define(
    "knowledge.portrait.approved",
    "info",
    "Портрет подтверждён оператором",
    required=("portrait_id", "actor"),
)
events.define(
    "knowledge.portrait.hidden",
    "info",
    "Портрет скрыт оператором",
    required=("portrait_id", "actor"),
)
events.define(
    "knowledge.portrait.shown",
    "info",
    "Портрет возвращён оператором",
    required=("portrait_id", "actor"),
)
events.define(
    "knowledge.portrait.main",
    "info",
    "Портрет назначен главным",
    required=("portrait_id", "actor"),
)

VISIBLE_LIMIT = 7


class PortraitNotFound(Exception):
    def __init__(self, portrait_id: int) -> None:
        super().__init__(f"портрет {portrait_id} не найден")
        self.portrait_id = portrait_id


def content_type(data: bytes) -> str:
    """MIME по сигнатуре байтов: ``FileStore`` хранит файлы без расширения.

    Commons отдаёт JPEG, PNG, GIF и WebP; определять по первым байтам проще, чем хранить
    расширение отдельным столбцом, и не требует чтения всего файла в библиотеку изображений.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


class Portraits:
    """Строки ``portraits`` и действия над ними.

    Действия ``approve``, ``hide``, ``show`` и ``make_main`` принимают ``actor`` и пишут событие
    ``knowledge.portrait.*``; журнал ``ActionLog`` добавляет слой проверки оператором (задача 4.1),
    поэтому здесь сервис знаний не зависит от ``philograph.operator``.
    """

    def __init__(self, engine: Engine, files: FileStore, clock: Clock | None = None) -> None:
        self.engine = engine
        self.files = files
        self.clock = clock or SystemClock()

    def add_draft(
        self,
        entity_id: str,
        *,
        file_id: str,
        width: int,
        height: int,
        author: str | None,
        year: str | None,
        license: str,
        license_url: str | None,
        source_url: str,
        origin: str,
        phash: str,
    ) -> int:
        """Черновик в конец списка. Повтор по ``(entity_id, phash)`` возвращает существующий id:
        это делает ``sync`` идемпотентным — повторная выборка не плодит строк и не меняет порядок.
        """
        with self.engine.begin() as conn:
            existing = conn.scalar(
                select(t.portraits.c.id).where(
                    and_(t.portraits.c.entity_id == entity_id, t.portraits.c.phash == phash)
                )
            )
            if existing is not None:
                return existing
            position = conn.scalar(
                select(func.max(t.portraits.c.position)).where(t.portraits.c.entity_id == entity_id)
            )
            portrait_id = conn.execute(
                t.portraits.insert().values(
                    entity_id=entity_id,
                    file_id=file_id,
                    width=width,
                    height=height,
                    author=author,
                    year=year,
                    license=license,
                    license_url=license_url,
                    source_url=source_url,
                    origin=origin,
                    phash=phash,
                    position=position + 1 if position is not None else 0,
                    status="draft",
                    hidden=False,
                    created_at=self.clock.now(),
                )
            ).inserted_primary_key[0]
        events.emit("knowledge.portrait.added", portrait_id=portrait_id, entity_id=entity_id)
        return portrait_id

    def pending(self) -> list[dict[str, Any]]:
        """Все черновики с подписью персоны — для очереди проверки."""
        return self.queue("draft")

    def queue(self, status: str | None = None) -> list[dict[str, Any]]:
        """Изображения для проверки: по статусу (``draft`` | ``approved``) или скрытые."""
        with self.engine.begin() as conn:
            query = select(t.portraits).order_by(t.portraits.c.position, t.portraits.c.id)
            if status == "hidden":
                query = query.where(t.portraits.c.hidden.is_(True))
            elif status is not None:
                query = query.where(
                    and_(t.portraits.c.status == status, t.portraits.c.hidden.is_(False))
                )
            rows = conn.execute(query).mappings().all()
            labels = self._labels(conn, [r["entity_id"] for r in rows])
        return [
            {
                "id": r["id"],
                "entity_id": r["entity_id"],
                "label": labels.get(r["entity_id"], r["entity_id"]),
                "file_id": r["file_id"],
                "width": r["width"],
                "height": r["height"],
                "author": r["author"],
                "year": r["year"],
                "license": r["license"],
                "license_url": r["license_url"],
                "source_url": r["source_url"],
                "position": r["position"],
                "status": r["status"],
                "hidden": r["hidden"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def visible(self, entity_id: str) -> list[dict[str, Any]]:
        """Подтверждённые и нескрытые изображения персоны: главное первым, до семи."""
        with self.engine.begin() as conn:
            rows = (
                conn.execute(
                    select(t.portraits)
                    .where(
                        t.portraits.c.entity_id == entity_id,
                        t.portraits.c.status == "approved",
                        t.portraits.c.hidden.is_(False),
                    )
                    .order_by(t.portraits.c.position, t.portraits.c.id)
                    .limit(VISIBLE_LIMIT)
                )
                .mappings()
                .all()
            )
        return [
            {
                "url": f"/api/knowledge/v1/portraits/{r['id']}",
                "width": r["width"],
                "height": r["height"],
                "author": r["author"],
                "year": r["year"],
                "license": r["license"],
                "license_url": r["license_url"],
                "source_url": r["source_url"],
            }
            for r in rows
        ]

    def get(self, portrait_id: int) -> dict[str, Any] | None:
        """Сведения для раздачи: файл, статус и скрытость."""
        with self.engine.begin() as conn:
            row = (
                conn.execute(select(t.portraits).where(t.portraits.c.id == portrait_id))
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return {"file_id": row["file_id"], "status": row["status"], "hidden": row["hidden"]}

    def approve(self, portrait_id: int, actor: str) -> None:
        self._require(portrait_id)
        with self.engine.begin() as conn:
            conn.execute(
                update(t.portraits).where(t.portraits.c.id == portrait_id).values(status="approved")
            )
        events.emit("knowledge.portrait.approved", portrait_id=portrait_id, actor=actor)

    def hide(self, portrait_id: int, actor: str) -> None:
        self._require(portrait_id)
        with self.engine.begin() as conn:
            conn.execute(
                update(t.portraits).where(t.portraits.c.id == portrait_id).values(hidden=True)
            )
        events.emit("knowledge.portrait.hidden", portrait_id=portrait_id, actor=actor)

    def show(self, portrait_id: int, actor: str) -> None:
        self._require(portrait_id)
        with self.engine.begin() as conn:
            conn.execute(
                update(t.portraits).where(t.portraits.c.id == portrait_id).values(hidden=False)
            )
        events.emit("knowledge.portrait.shown", portrait_id=portrait_id, actor=actor)

    def make_main(self, portrait_id: int, actor: str) -> None:
        """Выбранному — ``position`` 0, остальные сдвигаются в прежнем порядке, без потерь."""
        with self.engine.begin() as conn:
            row = (
                conn.execute(select(t.portraits).where(t.portraits.c.id == portrait_id))
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise PortraitNotFound(portrait_id)
            ordered = [
                r["id"]
                for r in conn.execute(
                    select(t.portraits.c.id, t.portraits.c.position)
                    .where(t.portraits.c.entity_id == row["entity_id"])
                    .order_by(t.portraits.c.position, t.portraits.c.id)
                ).mappings()
            ]
            for position, pid in enumerate(
                [portrait_id, *[pid for pid in ordered if pid != portrait_id]]
            ):
                conn.execute(
                    update(t.portraits).where(t.portraits.c.id == pid).values(position=position)
                )
        events.emit("knowledge.portrait.main", portrait_id=portrait_id, actor=actor)

    def _require(self, portrait_id: int) -> None:
        if self.get(portrait_id) is None:
            raise PortraitNotFound(portrait_id)

    @staticmethod
    def _labels(conn, entity_ids: list[str]) -> dict[str, str]:
        """Подпись персоны: основное русское название, иначе первое из названий, иначе id."""
        labels: dict[str, str] = {}
        for entity_id in dict.fromkeys(entity_ids):
            name = conn.scalar(
                select(t.names.c.text)
                .where(
                    t.names.c.entity_id == entity_id,
                    t.names.c.kind == "primary",
                    t.names.c.lang == "ru",
                )
                .limit(1)
            )
            if name is None:
                name = conn.scalar(
                    select(t.names.c.text)
                    .where(t.names.c.entity_id == entity_id)
                    .order_by(t.names.c.id)
                    .limit(1)
                )
            labels[entity_id] = name or entity_id
        return labels
