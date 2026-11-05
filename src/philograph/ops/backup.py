"""Резервные копии: ``python -m philograph.ops.backup run | verify | restore``.

Копия — архив с выгрузкой всех таблиц всех схем (JSON Lines, по таблице на файл),
версиями миграций и файловым хранилищем. До отправки архив шифруется ключом
``PHILOGRAPH_BACKUP_KEY`` (Fernet); ключ лежит только в окружении сервера, а не рядом с
копиями. Хранилище копий — каталог, смонтированный с внешнего хранилища, или S3.

Выгрузка логическая, через то же описание таблиц, что и миграции: не зависит от версии
``pg_dump`` и одинаково работает с PostgreSQL и SQLite. Векторный и полнотекстовый индексы
и кэш LLM восстанавливать не нужно: индексы строит переиндексация, кэш наполнится сам.
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import tarfile
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Engine, delete, func, insert, select, text

from philograph.ops import schema as ops_schema
from philograph.ops.migrate import all_migrations
from philograph.platform import events
from philograph.platform.clock import Clock, SystemClock
from philograph.platform.db import Migrations, make_engine

events.define(
    "ops.backup.completed",
    "info",
    "Резервная копия создана и отправлена",
    required=("name", "bytes", "rows", "files"),
)
events.define("ops.backup.failed", "error", "Резервная копия не создана", required=("reason",))
events.define(
    "ops.backup.verified",
    "info",
    "Восстановление из копии проверено",
    required=("name", "tables", "rows"),
)
events.define(
    "ops.backup.verify_failed",
    "error",
    "Проверка восстановления не прошла",
    required=("reason",),
    optional=("name",),
)
events.define("ops.backup.rotated", "info", "Старые копии удалены", required=("removed", "kept"))

SUFFIX = ".philograph-backup"
# Кэш LLM восстанавливать не нужно: он наполнится заново.
SKIPPED_TABLES = {"llm.cache"}


class BackupError(Exception):
    pass


# --- хранилище копий ---------------------------------------------------------------


class Storage(Protocol):
    def put(self, name: str, data: bytes) -> None: ...
    def get(self, name: str) -> bytes: ...
    def names(self) -> list[str]: ...
    def delete(self, name: str) -> None: ...


class DirStorage:
    """Каталог: смонтированное внешнее хранилище (rclone, sshfs) или локальная папка в тестах."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, name: str, data: bytes) -> None:
        if not self.root.is_dir():
            raise BackupError(f"хранилище копий недоступно: {self.root}")
        partial = self.root / f"{name}.partial"
        partial.write_bytes(data)
        partial.replace(self.root / name)  # копия появляется целиком или не появляется

    def get(self, name: str) -> bytes:
        return (self.root / name).read_bytes()

    def names(self) -> list[str]:
        if not self.root.is_dir():
            raise BackupError(f"хранилище копий недоступно: {self.root}")
        return sorted(p.name for p in self.root.iterdir() if p.name.endswith(SUFFIX))

    def delete(self, name: str) -> None:
        (self.root / name).unlink(missing_ok=True)


class S3Storage:
    def __init__(self, url: str) -> None:
        import boto3  # необязательная зависимость: pip install ".[s3]"

        bucket, _, prefix = url.removeprefix("s3://").partition("/")
        self.bucket, self.prefix = bucket, prefix.rstrip("/") + "/" if prefix else ""
        self.client = boto3.client(
            "s3", endpoint_url=os.environ.get("PHILOGRAPH_BACKUP_S3_ENDPOINT")
        )

    def put(self, name: str, data: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=self.prefix + name, Body=data)

    def get(self, name: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=self.prefix + name)["Body"].read()

    def names(self) -> list[str]:
        pages = self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=self.prefix
        )
        keys = [o["Key"] for page in pages for o in page.get("Contents", [])]
        return sorted(k.removeprefix(self.prefix) for k in keys if k.endswith(SUFFIX))

    def delete(self, name: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self.prefix + name)


def storage_from(target: str) -> Storage:
    return S3Storage(target) if target.startswith("s3://") else DirStorage(Path(target))


# --- выгрузка и загрузка таблиц ----------------------------------------------------


def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"$dt": value.isoformat()}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    if isinstance(value, bytes):
        return {"$b64": base64.b64encode(value).decode()}
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict) and len(value) == 1:
        if "$dt" in value:
            return datetime.fromisoformat(value["$dt"])
        if "$date" in value:
            return date.fromisoformat(value["$date"])
        if "$b64" in value:
            return base64.b64decode(value["$b64"])
    return value


def _tables(sets: list[Migrations]):
    for m in sets:
        yield m, m._version_table
        for table in m.metadata.sorted_tables:
            if f"{m.schema}.{table.name}" not in SKIPPED_TABLES:
                yield m, table


def dump(engine: Engine, sets: list[Migrations]) -> tuple[dict[str, bytes], dict[str, int]]:
    """Содержимое таблиц: имя файла → JSON Lines; и число строк по таблицам."""
    files: dict[str, bytes] = {}
    counts: dict[str, int] = {}
    with engine.connect() as conn:
        for m, table in _tables(sets):
            key = f"{m.schema}.{table.name}"
            lines = [
                json.dumps({k: _encode(v) for k, v in row._mapping.items()}, ensure_ascii=False)
                for row in conn.execute(select(table))
            ]
            files[f"data/{key}.jsonl"] = ("\n".join(lines) + ("\n" if lines else "")).encode()
            counts[key] = len(lines)
    return files, counts


def load(engine: Engine, sets: list[Migrations], files: dict[str, bytes]) -> dict[str, int]:
    """Загружает выгрузку в базу с применёнными миграциями. Таблицы перед загрузкой очищаются."""
    counts: dict[str, int] = {}
    with engine.begin() as conn:
        tables = list(_tables(sets))
        for _m, table in reversed(tables):
            conn.execute(delete(table))
        for m, table in tables:
            key = f"{m.schema}.{table.name}"
            raw = files.get(f"data/{key}.jsonl", b"").decode()
            rows = [
                {k: _decode(v) for k, v in json.loads(line).items()}
                for line in raw.splitlines()
                if line.strip()
            ]
            for start in range(0, len(rows), 500):
                conn.execute(insert(table), rows[start : start + 500])
            counts[key] = len(rows)
            if conn.dialect.name == "postgresql" and rows:
                _advance_sequences(conn, m.schema, table)
    return counts


def _advance_sequences(conn, schema: str, table) -> None:
    """Счётчики идентификаторов PostgreSQL после загрузки строк с явными id."""
    for column in table.primary_key.columns:
        if column.autoincrement is True or (
            column.autoincrement == "auto" and column.type.python_type is int
        ):
            seq = conn.scalar(
                text("SELECT pg_get_serial_sequence(:t, :c)"),
                {"t": f'"{schema}"."{table.name}"', "c": column.name},
            )
            if seq:
                top = conn.scalar(select(func.max(column)))
                conn.execute(text("SELECT setval(:s, :v)"), {"s": seq, "v": max(int(top or 1), 1)})


def ensure_database(url: str) -> None:
    """Проверочная база PostgreSQL создаётся при первой проверке восстановления."""
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    target = make_url(url)
    if not target.drivername.startswith("postgresql"):
        return
    server = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with server.connect() as conn:
            exists = conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": target.database}
            )
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    finally:
        server.dispose()


def _migration_versions(engine: Engine, sets: list[Migrations]) -> dict[str, list[int]]:
    result = {}
    with engine.connect() as conn:
        for m in sets:
            result[m.schema] = sorted(conn.scalars(select(m._version_table.c.version)))
    return result


# --- архив ---------------------------------------------------------------------------


def _pack(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _unpack(blob: bytes) -> dict[str, bytes]:
    result = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for member in tar.getmembers():
            if member.isfile():
                result[member.name] = tar.extractfile(member).read()  # type: ignore[union-attr]
    return result


def _files_archive(root: Path) -> tuple[bytes, int]:
    buffer = io.BytesIO()
    count = 0
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        if root.is_dir():
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    tar.add(path, arcname=str(path.relative_to(root)))
                    count += 1
    return buffer.getvalue(), count


def _restore_files(blob: bytes, root: Path) -> int:
    root.mkdir(parents=True, exist_ok=True)
    count = 0
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for member in tar.getmembers():
            if member.isfile():
                tar.extract(member, root, filter="data")  # без выхода за пределы каталога
                count += 1
    return count


# --- копия, ротация, проверка --------------------------------------------------------


@dataclass
class Backups:
    database_url: str
    files_root: Path
    storage: Storage
    key: bytes
    clock: Clock | None = None

    def __post_init__(self) -> None:
        self.clock = self.clock or SystemClock()
        self.fernet = Fernet(self.key)

    def _engine(self, url: str | None = None) -> Engine:
        sets = all_migrations()
        return make_engine(url or self.database_url, [m.schema for m in sets])

    def _record(self, kind: str, ok: bool, name: str | None, detail: dict[str, Any]) -> None:
        """Итог — в схему ops, по нему оповещения видят неудачу и давность копии."""
        try:
            engine = make_engine(self.database_url, [ops_schema.SCHEMA])
            ops_schema.migrations.upgrade(engine)
            with engine.begin() as conn:
                conn.execute(
                    ops_schema.runs.insert().values(
                        kind=kind, ok=ok, time=self.clock.now(), name=name, detail=detail
                    )
                )
            engine.dispose()
        except Exception:  # запись итога не должна скрыть саму ошибку
            pass

    def run(self) -> str:
        try:
            name = self._run()
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            events.emit("ops.backup.failed", reason=reason, error_kind=type(exc).__name__)
            self._record("backup", False, None, {"reason": reason})
            raise
        return name

    def _run(self) -> str:
        sets = all_migrations()
        engine = self._engine()
        try:
            tables, counts = dump(engine, sets)
            versions = _migration_versions(engine, sets)
        finally:
            engine.dispose()
        files_blob, files = _files_archive(self.files_root)
        moment = self.clock.now()
        manifest = {
            "created": moment.isoformat(),
            "counts": counts,
            "migrations": versions,
            "files": files,
        }
        blob = _pack(
            {"manifest.json": json.dumps(manifest).encode(), "files.tar.gz": files_blob, **tables}
        )
        encrypted = self.fernet.encrypt(blob)
        name = f"{moment.strftime('%Y%m%dT%H%M%SZ')}{SUFFIX}"
        self.storage.put(name, encrypted)
        rows = sum(counts.values())
        events.emit("ops.backup.completed", name=name, bytes=len(encrypted), rows=rows, files=files)
        self._record("backup", True, name, {"bytes": len(encrypted), "rows": rows})
        self.rotate()
        return name

    def open(self, name: str) -> dict[str, bytes]:
        try:
            return _unpack(self.fernet.decrypt(self.storage.get(name)))
        except InvalidToken as exc:
            raise BackupError("копию нельзя расшифровать этим ключом") from exc

    def latest(self) -> str:
        names = self.storage.names()
        if not names:
            raise BackupError("копий нет")
        return names[-1]

    def restore(self, name: str, database_url: str, files_root: Path) -> dict[str, Any]:
        """Разворачивает копию в базу и каталог: миграции, затем данные."""
        content = self.open(name)
        manifest = json.loads(content["manifest.json"])
        sets = all_migrations()
        engine = self._engine(database_url)
        try:
            for m in sets:
                m.upgrade(engine)
            counts = load(engine, sets, content)
            versions = _migration_versions(engine, sets)
        finally:
            engine.dispose()
        files = _restore_files(content["files.tar.gz"], files_root)
        return {"manifest": manifest, "counts": counts, "versions": versions, "files": files}

    def verify(self, database_url: str) -> dict[str, Any]:
        """Плановая проверка: копия разворачивается в отдельной базе и сверяется."""
        name = None
        try:
            name = self.latest()
            ensure_database(database_url)
            with tempfile.TemporaryDirectory() as tmp:
                result = self.restore(name, database_url, Path(tmp))
            manifest = result["manifest"]
            if result["versions"] != manifest["migrations"]:
                raise BackupError("версии миграций не совпадают с копией")
            differ = {
                k: (v, result["counts"].get(k))
                for k, v in manifest["counts"].items()
                if result["counts"].get(k) != v
            }
            if differ:
                raise BackupError(f"число строк не совпадает: {sorted(differ)[:5]}")
            main = [k for k in ("library.sources", "library.versions") if k in manifest["counts"]]
            if not any(result["counts"].get(k) for k in main):
                raise BackupError("основные таблицы пусты")
            if result["files"] != manifest["files"]:
                raise BackupError("число файлов не совпадает")
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            events.emit(
                "ops.backup.verify_failed", reason=reason, name=name, error_kind=type(exc).__name__
            )
            self._record("verify", False, name, {"reason": reason})
            raise
        rows = sum(result["counts"].values())
        events.emit("ops.backup.verified", name=name, tables=len(result["counts"]), rows=rows)
        self._record("verify", True, name, {"rows": rows})
        return result

    def rotate(self) -> list[str]:
        names = self.storage.names()
        keep = retained(names, self.clock.now())
        removed = [n for n in names if n not in keep]
        for n in removed:
            self.storage.delete(n)
        events.emit("ops.backup.rotated", removed=len(removed), kept=len(keep))
        return removed


def created(name: str) -> datetime:
    return datetime.strptime(name.removesuffix(SUFFIX), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def retained(names: Iterable[str], now: datetime) -> set[str]:
    """Ежедневные за неделю, по одной на неделю за месяц, по одной на месяц за год."""
    stamped = sorted(((created(n), n) for n in names), reverse=True)
    keep: set[str] = set()
    rules = (
        (timedelta(days=7), lambda d: d.date()),
        (timedelta(days=31), lambda d: d.isocalendar()[:2]),
        (timedelta(days=366), lambda d: (d.year, d.month)),
    )
    for window, bucket in rules:
        seen = set()
        for moment, name in stamped:
            if now - moment > window:
                continue
            b = bucket(moment)
            if b not in seen:  # самая свежая копия в своём дне, неделе или месяце
                seen.add(b)
                keep.add(name)
    if stamped:
        keep.add(stamped[0][1])  # последняя копия остаётся всегда
    return keep


def from_env(env: dict[str, str]) -> Backups:
    key = env.get("PHILOGRAPH_BACKUP_KEY")
    if not key:
        raise BackupError("не задан PHILOGRAPH_BACKUP_KEY")
    return Backups(
        env["PHILOGRAPH_DATABASE_URL"],
        Path(env["PHILOGRAPH_FILES_ROOT"]),
        storage_from(env["PHILOGRAPH_BACKUP_TARGET"]),
        key.encode(),
    )


def main(argv: list[str]) -> int:
    events.configure(sinks=[events.json_sink()])
    command = argv[0] if argv else "run"
    backups = from_env(dict(os.environ))
    try:
        if command == "run":
            backups.run()
        elif command == "verify":
            backups.verify(os.environ["PHILOGRAPH_BACKUP_VERIFY_DATABASE_URL"])
        elif command == "restore":
            name = argv[1] if len(argv) > 1 else backups.latest()
            backups.restore(name, backups.database_url, backups.files_root)
        else:
            print("команды: run | verify | restore [имя]", file=sys.stderr)
            return 2
    except Exception as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
