"""Доступ к реляционной базе: схема на каждый сервис и миграции с версиями.

Таблицы объявляются с ``schema=<сервис>``. В PostgreSQL это настоящие схемы. В SQLite
(тесты и локальная разработка) каждая схема подключается как отдельная база через ATTACH,
поэтому тот же код работает без изменений.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import (
    Column,
    Connection,
    DateTime,
    Engine,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    event,
    select,
    text,
)
from sqlalchemy.pool import StaticPool

from philograph.platform import events

events.define(
    "db.migration.applied",
    "info",
    "Применена миграция схемы сервиса",
    required=("schema", "version", "name"),
)


def make_engine(url: str, schemas: list[str]) -> Engine:
    """Создаёт подключение. Для SQLite подключает каждую схему как базу в памяти."""
    if url.startswith("sqlite"):
        path = url.removeprefix("sqlite:///") if url.startswith("sqlite:///") else None
        if path:
            # Файловая база: у каждой схемы свой файл рядом, соединений может быть несколько.
            engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
            targets = {s: str(Path(path).with_suffix(f".{s}.db")) for s in schemas}
        else:
            engine = create_engine(
                url, connect_args={"check_same_thread": False}, poolclass=StaticPool
            )
            targets = {s: ":memory:" for s in schemas}

        @event.listens_for(engine, "connect")
        def _attach(dbapi_conn, _record) -> None:  # pragma: no cover - вызывается драйвером
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA busy_timeout = 30000")
            for schema, target in targets.items():
                cur.execute(f"ATTACH DATABASE '{target}' AS {schema}")
            cur.close()

        return engine
    engine = create_engine(url, pool_pre_ping=True)
    with engine.begin() as conn:
        # Параллельный запуск сервисов: создание схем тоже под блокировкой.
        advisory_lock(conn, "philograph-schemas")
        for schema in schemas:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    return engine


def advisory_lock(conn: Connection, name: str) -> None:
    """Блокировка до конца транзакции для «проверить, затем записать» при параллельном старте.

    В PostgreSQL — рекомендательная блокировка транзакции. В SQLite не нужна: пишущие
    транзакции там и так идут по одной.
    """
    if conn.dialect.name == "postgresql":
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:s))"), {"s": name})


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[Connection], None]


class Migrations:
    """Упорядоченные миграции одной схемы. Применённые версии хранятся в самой схеме."""

    def __init__(self, schema: str, metadata: MetaData) -> None:
        self.schema = schema
        self.metadata = metadata
        self._items: list[Migration] = []
        self._version_table = Table(
            "schema_migrations",
            MetaData(),
            Column("version", Integer, primary_key=True),
            Column("name", String(200), nullable=False),
            Column("applied_at", DateTime(timezone=True)),
            schema=schema,
        )

    def add(self, version: int, name: str) -> Callable[[Callable[[Connection], None]], None]:
        def register(fn: Callable[[Connection], None]) -> None:
            if any(m.version == version for m in self._items):
                raise ValueError(f"миграция {self.schema}:{version} уже есть")
            self._items.append(Migration(version, name, fn))
            self._items.sort(key=lambda m: m.version)

        return register

    def create_tables(self, *names: str) -> Callable[[Connection], None]:
        """Миграция, создающая перечисленные таблицы из метаданных сервиса."""

        def apply(conn: Connection) -> None:
            tables = [self.metadata.tables[f"{self.schema}.{n}"] for n in names]
            self.metadata.create_all(conn, tables=tables)

        return apply

    def pending(self, engine: Engine) -> list[Migration]:
        with engine.begin() as conn:
            self._version_table.create(conn, checkfirst=True)
            done = set(conn.scalars(select(self._version_table.c.version)))
        return [m for m in self._items if m.version not in done]

    def upgrade(self, engine: Engine) -> list[int]:
        """Применяет недостающие миграции по порядку в одной транзакции.

        Сервисы стартуют одновременно и могут мигрировать одну схему параллельно. В PostgreSQL
        транзакция берёт блокировку на схему и пересчитывает недостающие миграции уже под ней:
        второй процесс дождётся первого и ничего не применит повторно.
        """
        from datetime import UTC, datetime

        applied = []
        with engine.begin() as conn:
            advisory_lock(conn, f"philograph-migrations:{self.schema}")
            self._version_table.create(conn, checkfirst=True)
            done = set(conn.scalars(select(self._version_table.c.version)))
            for migration in [m for m in self._items if m.version not in done]:
                migration.apply(conn)
                conn.execute(
                    self._version_table.insert().values(
                        version=migration.version, name=migration.name, applied_at=datetime.now(UTC)
                    )
                )
                applied.append(migration)
        for migration in applied:
            events.emit(
                "db.migration.applied",
                schema=self.schema,
                version=migration.version,
                name=migration.name,
            )
        return [m.version for m in applied]

    def current(self, engine: Engine) -> int | None:
        with engine.begin() as conn:
            self._version_table.create(conn, checkfirst=True)
            versions = list(conn.scalars(select(self._version_table.c.version)))
        return max(versions) if versions else None

    def latest(self) -> int | None:
        return self._items[-1].version if self._items else None
