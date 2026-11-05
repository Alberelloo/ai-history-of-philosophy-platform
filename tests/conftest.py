"""Общие фикстуры: журнал событий в строгом режиме, база в памяти, управляемые часы."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest

from philograph.platform import events as ev
from philograph.platform.clock import ManualClock
from philograph.platform.db import make_engine


class EventLog:
    """События, записанные во время теста, и проверки по ним."""

    def __init__(self) -> None:
        self.items: list[ev.Event] = []

    def __call__(self, event: ev.Event) -> None:
        self.items.append(event)

    def names(self) -> list[str]:
        return [e.name for e in self.items]

    def of(self, name: str) -> list[ev.Event]:
        return [e for e in self.items if e.name == name]

    def one(self, name: str) -> ev.Event:
        found = self.of(name)
        assert len(found) == 1, f"ожидалось одно событие {name}, есть {len(found)}: {self.names()}"
        return found[0]

    def assert_sequence(self, *names: str) -> None:
        """События идут в этом порядке (между ними могут быть другие)."""
        position = 0
        seen = self.names()
        for name in names:
            try:
                position = seen.index(name, position) + 1
            except ValueError:
                raise AssertionError(f"нет {name} после позиции {position}: {seen}") from None

    def assert_none(self, name: str) -> None:
        assert not self.of(name), f"не ожидалось {name}: {[e.fields for e in self.of(name)]}"

    def where(self, name: str, **fields: Any) -> list[ev.Event]:
        return [e for e in self.of(name) if all(e.get(k) == v for k, v in fields.items())]

    def clear(self) -> None:
        self.items.clear()


@pytest.fixture(autouse=True)
def events() -> Iterator[EventLog]:
    log = EventLog()
    ev.configure(sinks=[log], strict=True)
    yield log
    ev.configure(sinks=[], strict=False)


@pytest.fixture
def clock() -> ManualClock:
    clk = ManualClock()
    ev.configure(clock=clk)
    return clk


@pytest.fixture
def database_url(tmp_path) -> str:
    """Файловая SQLite во временной папке; в CI — PostgreSQL через PHILOGRAPH_TEST_DATABASE_URL."""
    return os.environ.get(
        "PHILOGRAPH_TEST_DATABASE_URL", f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    )


@pytest.fixture
def engine_for(database_url: str):
    created = []

    def factory(*migration_sets):
        schemas = [m.schema for m in migration_sets]
        engine = make_engine(database_url, schemas)
        if not database_url.startswith("sqlite"):
            from sqlalchemy import text

            with engine.begin() as conn:
                for schema in schemas:
                    conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
                    conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        for m in migration_sets:
            m.upgrade(engine)
        created.append(engine)
        return engine

    yield factory
    for engine in created:
        engine.dispose()


@pytest.fixture(scope="session")
def browser():
    """Один Chromium на весь прогон: два экземпляра синхронного Playwright не уживаются."""
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            instance = p.chromium.launch(headless=True)
        except Exception as exc:  # браузер не установлен
            pytest.skip(f"Chromium недоступен: {exc}")
        yield instance
        instance.close()
