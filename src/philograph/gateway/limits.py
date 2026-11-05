"""Лимиты запросов и защита бюджета (system-design.md, блок 8).

Аккаунтов нет, а каждый вопрос ассистенту стоит денег, поэтому шлюз:

- ограничивает частоту всех запросов с одного адреса (корзина токенов);
- пускает к платным операциям только запросы со страницы продукта: страница получает
  подписанный токен в cookie, прямой вызов без него отклоняется;
- считает платные операции посетителя в час и в сутки. Посетитель — необратимый хеш адреса
  и признака браузера с суточной солью (``platform.privacy``).

Счётчики живут в памяти шлюза: на одном сервере шлюз один. Чтение, библиотека, карточки и
граф из сохранённых связей от лимитов платных операций не зависят.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field

from philograph.platform import events
from philograph.platform.clock import Clock, SystemClock
from philograph.platform.privacy import visitor_hash

events.define(
    "gateway.limit.triggered",
    "warning",
    "Сработал лимит запросов",
    required=("kind", "visitor"),
    optional=("operation", "retry_after_seconds"),
)

PAGE_COOKIE = "pg_page"

# Платные операции: метод, путь за шлюзом, имя.
PAID: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("POST", re.compile(r"^/api/assistant/v1/ask$"), "ask"),
    ("POST", re.compile(r"^/api/knowledge/v1/graph/build$"), "graph"),
    ("POST", re.compile(r"^/api/knowledge/v1/entities/[^/]+/description$"), "description"),
)


@dataclass(frozen=True)
class Quota:
    per_hour: int
    per_day: int

    @classmethod
    def parse(cls, value: str) -> Quota:
        """«20/100» — в час и в сутки."""
        hour, day = value.split("/")
        return cls(int(hour), int(day))


@dataclass(frozen=True)
class LimitSettings:
    rate_per_second: float = 20.0
    burst: int = 60
    quotas: dict[str, Quota] = field(
        default_factory=lambda: {
            "ask": Quota(20, 100),
            "graph": Quota(30, 200),
            "description": Quota(60, 300),
        }
    )
    token_ttl_seconds: int = 12 * 3600
    trusted_proxy: bool = False  # за обратным прокси адрес берётся из X-Forwarded-For

    @classmethod
    def from_env(cls, env: dict[str, str]) -> LimitSettings:
        base = cls()
        quotas = dict(base.quotas)
        for name in quotas:
            value = env.get(f"PHILOGRAPH_LIMIT_{name.upper()}")
            if value:
                quotas[name] = Quota.parse(value)
        return cls(
            rate_per_second=float(env.get("PHILOGRAPH_RATE_PER_SECOND", base.rate_per_second)),
            burst=int(env.get("PHILOGRAPH_RATE_BURST", base.burst)),
            quotas=quotas,
            trusted_proxy=env.get("PHILOGRAPH_TRUSTED_PROXY") == "1",
        )


def paid_operation(method: str, path: str) -> str | None:
    for m, pattern, name in PAID:
        if method == m and pattern.match(path):
            return name
    return None


class Limits:
    def __init__(
        self,
        settings: LimitSettings,
        secret: str,
        clock: Clock | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.secret = secret.encode()
        self.clock = clock or SystemClock()
        self.monotonic = monotonic
        self._buckets: dict[str, tuple[float, float]] = {}  # адрес → (токены, время)
        self._hour: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._day: dict[tuple[str, str, str], int] = defaultdict(int)

    # --- кто спрашивает ---

    def address(self, client_host: str | None, forwarded: str | None) -> str:
        if self.settings.trusted_proxy and forwarded:
            return forwarded.split(",")[0].strip()
        return client_host or "unknown"

    def visitor(self, address: str, user_agent: str) -> str:
        return visitor_hash(address, user_agent, self.clock.now(), self.secret.decode())

    # --- частота ---

    def rate(self, address: str) -> float | None:
        """``None`` — можно; иначе через сколько секунд."""
        now = self.monotonic()
        tokens, last = self._buckets.get(address, (float(self.settings.burst), now))
        tokens = min(self.settings.burst, tokens + (now - last) * self.settings.rate_per_second)
        if tokens < 1:
            self._buckets[address] = (tokens, now)
            return (1 - tokens) / self.settings.rate_per_second
        self._buckets[address] = (tokens - 1, now)
        if len(self._buckets) > 50_000:  # давно не заходившие адреса
            cutoff = now - 3600
            self._buckets = {a: b for a, b in self._buckets.items() if b[1] > cutoff}
        return None

    # --- токен страницы ---

    def _sign(self, issued: int, user_agent: str) -> str:
        message = f"{issued}\x00{user_agent}".encode()
        return hmac.new(self.secret, message, hashlib.sha256).hexdigest()[:32]

    def page_token(self, user_agent: str) -> str:
        issued = int(self.clock.now().timestamp())
        return f"{issued}.{self._sign(issued, user_agent)}"

    def check_token(self, token: str | None, user_agent: str) -> bool:
        if not token or "." not in token:
            return False
        issued_text, signature = token.split(".", 1)
        if not issued_text.isdigit():
            return False
        issued = int(issued_text)
        age = self.clock.now().timestamp() - issued
        if age < 0 or age > self.settings.token_ttl_seconds:
            return False
        return hmac.compare_digest(signature, self._sign(issued, user_agent))

    # --- платные операции ---

    def paid(self, visitor: str, operation: str) -> tuple[str, int] | None:
        """``None`` — можно и учтено; иначе вид лимита и через сколько секунд."""
        quota = self.settings.quotas[operation]
        now = self.clock.now()
        moment = now.timestamp()
        window = self._hour[(visitor, operation)]
        while window and moment - window[0] >= 3600:
            window.popleft()
        day_key = (visitor, operation, now.date().isoformat())
        if self._day[day_key] >= quota.per_day:
            tomorrow = (now.replace(hour=0, minute=0, second=0, microsecond=0)).timestamp() + 86400
            return "daily", math.ceil(tomorrow - moment)
        if len(window) >= quota.per_hour:
            return "hourly", math.ceil(3600 - (moment - window[0]))
        window.append(moment)
        self._day[day_key] += 1
        if len(self._day) > 100_000:  # вчерашние счётчики больше не нужны
            today = now.date().isoformat()
            self._day = defaultdict(int, {k: v for k, v in self._day.items() if k[2] == today})
        return None
