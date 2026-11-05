"""Требования спецификации backup-and-recovery: настоящая база, файлы и выгрузка."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy.engine import make_url

from philograph.ops import schema as ops_schema
from philograph.ops.__main__ import Scheduler
from philograph.ops.alerts import Alerts, AlertSettings, BackupRule, WebhookChannel
from philograph.ops.backup import (
    SUFFIX,
    BackupError,
    Backups,
    DirStorage,
    dump,
    retained,
)
from philograph.ops.migrate import all_migrations, upgrade_all
from philograph.platform.db import make_engine

from ..library.conftest import lib  # noqa: F401

req = pytest.mark.req
BR = "backup-and-recovery"


@pytest.fixture
def clean_schemas(engine_for):
    """Все схемы с нуля: в PostgreSQL итоги и данные прошлых тестов иначе остаются."""
    engine_for(*all_migrations())


@pytest.fixture
def bk(clean_schemas, lib, database_url, tmp_path, clock):
    source = lib.register(title="Критика чистого разума")
    lib.publish_new(source)
    upgrade_all(database_url)
    storage_dir = tmp_path / "backups"
    storage_dir.mkdir()
    key = Fernet.generate_key()
    backups = Backups(database_url, tmp_path / "files", DirStorage(storage_dir), key, clock)
    ops = make_engine(database_url, [ops_schema.SCHEMA])
    url = make_url(database_url)
    if url.drivername.startswith("sqlite"):
        verify_url = f"sqlite:///{(tmp_path / 'verify.db').as_posix()}"
    else:
        verify_url = url.set(database=f"{url.database}_verify").render_as_string(
            hide_password=False
        )
    return type(
        "BK",
        (),
        {
            "backups": backups,
            "dir": storage_dir,
            "key": key,
            "ops": ops,
            "verify_url": verify_url,
            "clock": clock,
            "source": source,
            "lib": lib,
            "database_url": database_url,
        },
    )


@req(BR, "Ежедневные копии")
def test_daily_backup_and_rotation(bk, events):
    bk.clock.set(datetime(2026, 11, 4, 2, 0, tzinfo=UTC))
    scheduler = Scheduler(bk.ops, lambda: None, bk.backups.run, None, bk.clock)
    assert scheduler.tick() == ["alerts"]  # ночное окно ещё не началось
    bk.clock.set(datetime(2026, 11, 4, 3, 5, tzinfo=UTC))
    assert scheduler.tick() == ["alerts", "backup"]
    bk.clock.advance(minutes=1)
    assert scheduler.tick() == ["alerts"]  # в тот же день — не повторяется
    bk.clock.advance(days=1)
    assert scheduler.tick() == ["alerts", "backup"]
    assert len(list(bk.dir.glob(f"*{SUFFIX}"))) == 2
    completed = events.of("ops.backup.completed")
    assert completed[-1]["rows"] > 0 and completed[-1]["files"] >= 1
    # Хранение: ежедневные за неделю, недельные за месяц, месячные за год.
    now = datetime(2026, 11, 4, 3, 0, tzinfo=UTC)
    names = [f"{(now - timedelta(days=d)):%Y%m%dT%H%M%SZ}{SUFFIX}" for d in range(400)]
    keep = retained(names, now)
    ages = sorted(
        (now - datetime.strptime(n[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)).days for n in keep
    )
    assert ages[:7] == list(range(7))  # каждый день последней недели
    assert max(ages) <= 366 and 18 <= len(keep) <= 26


@req(BR, "Шифрование копий")
def test_backup_is_encrypted(bk):
    name = bk.backups.run()
    raw = (bk.dir / name).read_bytes()
    assert "Критика".encode() not in raw and not raw.startswith(b"\x1f\x8b")  # не открытый gzip
    assert all(bk.key not in p.read_bytes() for p in bk.dir.iterdir())  # ключа рядом нет
    stranger = Backups(
        bk.database_url, bk.backups.files_root, bk.backups.storage, Fernet.generate_key()
    )
    with pytest.raises(BackupError, match="расшифровать"):
        stranger.open(name)
    assert "manifest.json" in bk.backups.open(name)


@req(BR, "Проверка восстановления")
def test_restore_verified_in_separate_database(bk, events):
    bk.backups.run()
    result = bk.backups.verify(bk.verify_url)
    assert result["counts"]["library.sources"] == 1 and result["files"] >= 1
    assert result["versions"] == result["manifest"]["migrations"]
    assert events.one("ops.backup.verified")["rows"] > 0
    restored = make_engine(bk.verify_url, [m.schema for m in all_migrations()])
    _, counts = dump(restored, all_migrations())
    assert counts["library.sources"] == 1
    # Испорченная копия: проверка падает, итог записан, правило оповещения срабатывает.
    latest = bk.backups.latest()
    (bk.dir / latest).write_bytes((bk.dir / latest).read_bytes()[:-20])
    with pytest.raises(BackupError):
        bk.backups.verify(bk.verify_url)
    assert events.one("ops.backup.verify_failed")["name"] == latest
    check = BackupRule(bk.ops, AlertSettings(), bk.clock)()
    assert check.firing and "проверка восстановления не прошла" in check.summary


@req(BR, "Восстановление производных данных")
def test_cache_not_backed_up_and_index_rebuilt(bk):
    tables, _ = dump(
        make_engine(bk.database_url, [m.schema for m in all_migrations()]), all_migrations()
    )
    assert "data/llm.cache.jsonl" not in tables and "data/llm.calls.jsonl" in tables


@req(BR, "Неудачная копия")
def test_failed_backup_alerts_operator(bk, events):
    bk.backups.run()
    bk.clock.advance(hours=1)
    bk.backups.storage = DirStorage(bk.dir / "отключённое")  # хранилище недоступно
    with pytest.raises(BackupError):
        bk.backups.run()
    assert "недоступно" in events.one("ops.backup.failed")["reason"]
    sent = []

    def webhook(request: httpx.Request) -> httpx.Response:
        sent.append(request.read().decode())
        return httpx.Response(200)

    alerts = Alerts(
        {"backup": ("Резервные копии", BackupRule(bk.ops, AlertSettings(), bk.clock))},
        WebhookChannel(
            "https://alerts.example/hook", httpx.Client(transport=httpx.MockTransport(webhook))
        ),
    )
    alerts.evaluate()
    assert len(sent) == 1 and "копия не создана" in sent[0]
