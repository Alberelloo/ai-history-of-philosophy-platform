"""Метрики в памяти процесса: счётчики и распределения с перцентилями.

Для первой версии достаточно одного процесса на сервис; экспорт наружу добавится вместе
с оповещениями (этап 6), интерфейс при этом не меняется.
"""

from __future__ import annotations

import math
import threading
from collections import defaultdict


def _key(name: str, labels: dict[str, str]) -> tuple[str, tuple[tuple[str, str], ...]]:
    return name, tuple(sorted(labels.items()))


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple, float] = defaultdict(float)
        self._samples: dict[tuple, list[float]] = defaultdict(list)
        self._gauges: dict[tuple, float] = {}

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        with self._lock:
            self._counters[_key(name, labels)] += value

    def observe(self, name: str, value: float, **labels: str) -> None:
        with self._lock:
            self._samples[_key(name, labels)].append(value)

    def gauge(self, name: str, value: float, **labels: str) -> None:
        with self._lock:
            self._gauges[_key(name, labels)] = value

    def counter(self, name: str, **labels: str) -> float:
        return self._counters.get(_key(name, labels), 0.0)

    def gauge_value(self, name: str, **labels: str) -> float | None:
        return self._gauges.get(_key(name, labels))

    def percentile(self, name: str, q: float, **labels: str) -> float | None:
        """Перцентиль методом ближайшего ранга; ``q`` от 0 до 100."""
        samples = sorted(self._samples.get(_key(name, labels), []))
        if not samples:
            return None
        rank = max(1, math.ceil(q / 100 * len(samples)))
        return samples[rank - 1]

    def summary(self, name: str, **labels: str) -> dict[str, float | None]:
        return {
            "count": len(self._samples.get(_key(name, labels), [])),
            "p50": self.percentile(name, 50, **labels),
            "p95": self.percentile(name, 95, **labels),
        }


metrics = Metrics()
