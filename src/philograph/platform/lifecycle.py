"""Старт и остановка процесса сервиса: версия в журнале и признак перезапуска после сбоя.

При старте процесс пишет ``service.started`` с версией. В ``PHILOGRAPH_STATE_DIR`` он кладёт
маркер, который штатная остановка убирает. Если при старте маркер уже есть, прошлый запуск
оборвался (падение, нехватка памяти), и процесс пишет ещё ``service.restarted``: по журналу
видно и какая версия работает, и что сервис падал.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from philograph.platform import context, events

events.define(
    "service.started",
    "info",
    "Сервис запущен",
    required=("version", "restarted"),
)
events.define(
    "service.restarted",
    "warning",
    "Сервис перезапущен после сбоя",
    required=("version", "previous_version"),
)
events.define("service.stopped", "info", "Сервис остановлен штатно", required=("version",))


def state_dir() -> Path | None:
    value = os.environ.get("PHILOGRAPH_STATE_DIR")
    return Path(value) if value else None


@contextmanager
def running(service: str, version: str, directory: Path | None = None) -> Iterator[None]:
    directory = directory if directory is not None else state_dir()
    marker = directory / f"{service}.running" if directory else None
    with context.scope(service=service):
        previous = marker.read_text(encoding="utf-8") if marker and marker.exists() else None
        if previous is not None:
            events.emit("service.restarted", version=version, previous_version=previous)
        events.emit("service.started", version=version, restarted=previous is not None)
        if marker:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(version, encoding="utf-8")
    try:
        yield
    finally:
        with context.scope(service=service):
            if marker:
                marker.unlink(missing_ok=True)
            events.emit("service.stopped", version=version)
