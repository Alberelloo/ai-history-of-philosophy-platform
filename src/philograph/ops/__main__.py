"""Сервис эксплуатации: ``python -m philograph.ops``.

Раз в минуту вычисляет оповещения, раз в сутки делает резервную копию, раз в неделю
проверяет восстановление. Когда что делалось, планировщик узнаёт из журнала запусков в схеме
``ops``, поэтому перезапуск сервиса не приводит к лишней копии и не пропускает плановую.
"""

from __future__ import annotations

import contextlib
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import Engine, func, select

from philograph import __version__
from philograph.ops import schema as ops_schema
from philograph.platform import events
from philograph.platform.clock import Clock, SystemClock
from philograph.platform.lifecycle import running


@dataclass
class Scheduler:
    engine: Engine
    alerts: Callable[[], object]
    backup: Callable[[], object]
    verify: Callable[[], object] | None
    clock: Clock
    backup_hour: int = 3  # UTC: ночью, когда читателей меньше
    backup_every: timedelta = timedelta(hours=23)
    verify_every: timedelta = timedelta(days=7)

    def _last(self, kind: str):
        runs = ops_schema.runs
        with self.engine.connect() as conn:
            moment = conn.scalar(select(func.max(runs.c.time)).where(runs.c.kind == kind))
        if moment is not None and moment.tzinfo is None:
            moment = moment.replace(tzinfo=self.clock.now().tzinfo)
        return moment

    def _due(self, kind: str, every: timedelta) -> bool:
        now = self.clock.now()
        last = self._last(kind)
        if last is not None and now - last < every:
            return False
        return now.hour >= self.backup_hour  # в своё окно, а не сразу после полуночи

    def tick(self) -> list[str]:
        """Одна минута работы; возвращает, что было запущено."""
        done = []
        self.alerts()
        done.append("alerts")
        # Неудача копии или проверки уже в журнале и в итогах — о ней оповестит правило.
        if self._due("backup", self.backup_every):
            with contextlib.suppress(Exception):
                self.backup()
            done.append("backup")
        elif self.verify is not None and self._due("verify", self.verify_every):
            with contextlib.suppress(Exception):
                self.verify()
            done.append("verify")
        return done


def main() -> None:
    from philograph.ops import alerts, backup
    from philograph.platform.db import make_engine

    events.configure(sinks=[events.json_sink()])
    env = dict(os.environ)
    engine = make_engine(env["PHILOGRAPH_DATABASE_URL"], [ops_schema.SCHEMA])
    ops_schema.migrations.upgrade(engine)
    watcher = alerts.from_env(env)
    backups = backup.from_env(env) if env.get("PHILOGRAPH_BACKUP_KEY") else None
    verify_url = env.get("PHILOGRAPH_BACKUP_VERIFY_DATABASE_URL")
    scheduler = Scheduler(
        engine,
        watcher.evaluate,
        backups.run if backups else (lambda: None),
        (lambda: backups.verify(verify_url)) if backups and verify_url else None,
        SystemClock(),
        backup_hour=int(env.get("PHILOGRAPH_BACKUP_HOUR", "3")),
    )
    stop = threading.Event()
    with running("ops", __version__):
        while not stop.is_set():
            scheduler.tick()
            stop.wait(60)


if __name__ == "__main__":
    main()
