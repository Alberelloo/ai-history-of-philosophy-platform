"""Проверки состояния: жив ли сервис и готов ли он обслуживать запросы."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

Probe = Callable[[], None]  # бросает исключение, если зависимость недоступна


@dataclass
class Dependency:
    name: str
    probe: Probe
    required: bool


@dataclass
class HealthReport:
    ready: bool
    version: str
    problems: dict[str, str] = field(default_factory=dict)
    degraded: dict[str, str] = field(default_factory=dict)


class Health:
    def __init__(self, service: str, version: str) -> None:
        self.service = service
        self.version = version
        self._deps: list[Dependency] = []

    def depends_on(self, name: str, probe: Probe, *, required: bool = True) -> None:
        """Обязательная зависимость делает сервис неготовым, необязательная — только деградацию."""
        self._deps.append(Dependency(name, probe, required))

    def live(self) -> dict[str, str]:
        return {"status": "live", "service": self.service, "version": self.version}

    def check(self) -> HealthReport:
        report = HealthReport(ready=True, version=self.version)
        for dep in self._deps:
            try:
                dep.probe()
            except Exception as exc:  # причина нужна оператору в любом виде
                reason = str(exc) or type(exc).__name__
                if dep.required:
                    report.ready = False
                    report.problems[dep.name] = reason
                else:
                    report.degraded[dep.name] = reason
        return report
