"""Журнал как поток событий с каталогом.

Код пишет не строки, а события из каталога: ``emit("llm.call.completed", role=..., ...)``.
Каталог задаёт уровень, обязательные и допустимые поля каждого события. Поля вне каталога
запрещены: так в журнал не попадают персональные данные, о которых никто не договаривался.
В строгом режиме (тесты) нарушение каталога — исключение, в работе — отдельное событие.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from philograph.platform import context
from philograph.platform.clock import Clock, SystemClock

Level = Literal["debug", "info", "warning", "error"]

# Поля контекста подставляются автоматически и разрешены у всех событий.
CONTEXT_FIELDS = frozenset({"request_id", "run_id", "service"})


@dataclass(frozen=True)
class EventSpec:
    name: str
    level: Level
    description: str
    required: frozenset[str] = frozenset()
    optional: frozenset[str] = frozenset()

    @property
    def allowed(self) -> frozenset[str]:
        return self.required | self.optional | CONTEXT_FIELDS


class CatalogViolation(Exception):
    """Событие не соответствует каталогу."""


_CATALOG: dict[str, EventSpec] = {}


def define(
    name: str,
    level: Level,
    description: str,
    required: Iterable[str] = (),
    optional: Iterable[str] = (),
) -> EventSpec:
    """Регистрирует событие в каталоге. Повторная регистрация того же описания допустима."""
    required_set = frozenset(required)
    if level == "error":
        required_set |= {"error_kind"}
    spec = EventSpec(name, level, description, required_set, frozenset(optional))
    existing = _CATALOG.get(name)
    if existing is not None and existing != spec:
        raise ValueError(f"событие {name} уже описано иначе")
    _CATALOG[name] = spec
    return spec


def catalog() -> dict[str, EventSpec]:
    return dict(_CATALOG)


# --- скрытие секретов ---------------------------------------------------------------

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),
]
_known_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    """Значение из настроек, которое нельзя показывать в журнале ни в каком виде."""
    if value and len(value) >= 6:
        _known_secrets.add(value)


def redact(text: str) -> str:
    for secret in _known_secrets:
        text = text.replace(secret, "[скрыто]")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[скрыто]", text)
    return text


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_redact_value(v) for v in value]
    return value


# --- приёмники ----------------------------------------------------------------------


@dataclass
class Event:
    name: str
    level: Level
    time: str
    fields: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        return self.fields[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.fields.get(key, default)


Sink = Callable[[Event], None]


class _Journal:
    def __init__(self) -> None:
        self.sinks: list[Sink] = []
        self.strict = False
        self.clock: Clock = SystemClock()

    def write(self, event: Event) -> None:
        for sink in list(self.sinks):
            sink(event)


_journal = _Journal()

VIOLATION = define(
    "observability.catalog.violation",
    "warning",
    "Код записал событие, которое не соответствует каталогу",
    required=("event", "problem"),
)


def configure(
    *, sinks: list[Sink] | None = None, strict: bool | None = None, clock: Clock | None = None
) -> None:
    if sinks is not None:
        _journal.sinks = list(sinks)
    if strict is not None:
        _journal.strict = strict
    if clock is not None:
        _journal.clock = clock


def add_sink(sink: Sink) -> None:
    _journal.sinks.append(sink)


def remove_sink(sink: Sink) -> None:
    if sink in _journal.sinks:
        _journal.sinks.remove(sink)


def _check(name: str, fields: dict[str, Any]) -> tuple[EventSpec | None, str | None]:
    spec = _CATALOG.get(name)
    if spec is None:
        return None, "события нет в каталоге"
    missing = spec.required - fields.keys()
    if missing:
        return spec, f"нет обязательных полей: {', '.join(sorted(missing))}"
    extra = fields.keys() - spec.allowed
    if extra:
        return spec, f"поля вне каталога: {', '.join(sorted(extra))}"
    return spec, None


def emit(name: str, /, **fields: Any) -> Event | None:
    """Записывает событие. Контекст запроса подставляется автоматически."""
    spec, problem = _check(name, fields)
    if problem is not None:
        if _journal.strict:
            raise CatalogViolation(f"{name}: {problem}")
        _write(VIOLATION, {"event": name, "problem": problem})
        if spec is None:
            return None
        # Пишем только то, что разрешено каталогом: лишнее может быть персональными данными.
        fields = {k: v for k, v in fields.items() if k in spec.allowed}
    assert spec is not None
    return _write(spec, fields)


def _write(spec: EventSpec, fields: dict[str, Any]) -> Event:
    payload = {**context.current(), **_redact_value(fields)}
    event = Event(spec.name, spec.level, _journal.clock.now().isoformat(), payload)
    _journal.write(event)
    return event


def json_sink() -> Sink:
    """Приёмник для работы: событие одной строкой JSON через structlog."""
    import structlog

    logger = structlog.get_logger()

    def sink(event: Event) -> None:
        getattr(logger, event.level)(event.name, time=event.time, **event.fields)

    return sink
