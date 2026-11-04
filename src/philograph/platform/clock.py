"""Часы как зависимость: код берёт время отсюда, а тесты подставляют управляемые часы."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class ManualClock:
    """Часы для тестов: время меняется только явно."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 11, 4, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs: float) -> None:
        self._now += timedelta(**kwargs)

    def set(self, value: datetime) -> None:
        self._now = value
