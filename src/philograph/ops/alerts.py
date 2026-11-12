"""Оповещения оператора: правила над состоянием сервисов, метриками и итогами копий.

Раз в минуту ``Alerts.evaluate`` вычисляет правила. У каждого правила есть состояние: при
переходе в «сработало» уходит одно сообщение, при возврате — одно сообщение о
восстановлении, повторные срабатывания между ними не отправляются. Сообщения собираются
только из чисел, названий сервисов и видов ошибок: вопросов, адресов и других данных
посетителей в них нет.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from sqlalchemy import Engine, func, select

from philograph.ops import schema as ops_schema
from philograph.platform import events
from philograph.platform.clock import Clock, SystemClock
from philograph.platform.queue import jobs

events.define(
    "ops.alert.fired",
    "warning",
    "Сработало правило оповещения",
    required=("rule", "summary"),
)
events.define(
    "ops.alert.resolved",
    "info",
    "Условие правила оповещения больше не выполняется",
    required=("rule", "summary"),
)
events.define(
    "ops.alert.delivery_failed",
    "error",
    "Оповещение не доставлено",
    required=("rule", "channel", "reason"),
)


@dataclass(frozen=True)
class AlertSettings:
    not_ready_minutes: float = 5.0
    error_rate: float = 0.05  # доля ответов 5xx
    error_min_requests: int = 20  # меньше запросов за интервал — доля не считается
    budget_ratio: float = 0.8
    queue_age_minutes: float = 30.0
    backup_age_hours: float = 26.0
    unknown_region_ratio: float = 0.10  # доля запросов шлюза без определённой страны
    unknown_region_min_requests: int = 100  # меньше запросов за интервал — доля не считается

    @classmethod
    def from_env(cls, env: dict[str, str]) -> AlertSettings:
        raw = env.get("PHILOGRAPH_ALERT_RULES")
        return cls(**json.loads(raw)) if raw else cls()


@dataclass
class Check:
    firing: bool
    summary: str  # без данных посетителей: числа, названия сервисов, виды ошибок
    details: dict[str, Any] = field(default_factory=dict)


Rule = Callable[[], Check]


class Channel(Protocol):
    name: str

    def send(self, text: str) -> None: ...


class LogChannel:
    """Канал по умолчанию: только журнал (события ``ops.alert.*``)."""

    name = "log"

    def send(self, text: str) -> None:
        return None


class WebhookChannel:
    name = "webhook"

    def __init__(self, url: str, client: httpx.Client | None = None) -> None:
        self.url = url
        self.client = client or httpx.Client(timeout=10)

    def send(self, text: str) -> None:
        self.client.post(self.url, json={"text": text}).raise_for_status()


class TelegramChannel:
    name = "telegram"

    def __init__(self, token: str, chat: str, client: httpx.Client | None = None) -> None:
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat = chat
        self.client = client or httpx.Client(timeout=10)

    def send(self, text: str) -> None:
        self.client.post(self.url, json={"chat_id": self.chat, "text": text}).raise_for_status()


def channel_from(env: dict[str, str]) -> Channel:
    if env.get("PHILOGRAPH_ALERT_TELEGRAM_TOKEN") and env.get("PHILOGRAPH_ALERT_TELEGRAM_CHAT"):
        return TelegramChannel(
            env["PHILOGRAPH_ALERT_TELEGRAM_TOKEN"], env["PHILOGRAPH_ALERT_TELEGRAM_CHAT"]
        )
    if env.get("PHILOGRAPH_ALERT_WEBHOOK"):
        return WebhookChannel(env["PHILOGRAPH_ALERT_WEBHOOK"])
    return LogChannel()


class Alerts:
    def __init__(self, rules: dict[str, tuple[str, Rule]], channel: Channel) -> None:
        """``rules``: код → (название для оператора, проверка)."""
        self.rules = rules
        self.channel = channel
        self.firing: dict[str, Check] = {}

    def evaluate(self) -> list[str]:
        """Вычисляет все правила; возвращает отправленные сообщения."""
        sent = []
        for code, (title, rule) in self.rules.items():
            try:
                check = rule()
            except Exception as exc:  # само правило не смогло проверить — тоже повод сообщить
                check = Check(True, f"проверка не выполнилась: {type(exc).__name__}")
            was = code in self.firing
            if check.firing and not was:
                self.firing[code] = check
                events.emit("ops.alert.fired", rule=code, summary=check.summary)
                sent.append(self._send(code, f"⚠ {title}: {check.summary}"))
            elif not check.firing and was:
                del self.firing[code]
                events.emit("ops.alert.resolved", rule=code, summary=check.summary)
                sent.append(self._send(code, f"✓ {title}: восстановлено. {check.summary}"))
        return sent

    def _send(self, code: str, text: str) -> str:
        try:
            self.channel.send(text)
        except Exception as exc:
            events.emit(
                "ops.alert.delivery_failed",
                rule=code,
                channel=self.channel.name,
                reason=type(exc).__name__,
                error_kind="delivery",
            )
        return text


# --- правила -------------------------------------------------------------------------


class ReadinessRule:
    """Сервис не готов дольше заданного времени: короткие перезапуски не беспокоят."""

    def __init__(
        self,
        service: str,
        probe: Callable[[], tuple[bool, str]],
        minutes: float,
        clock: Clock,
    ) -> None:
        self.service, self.probe, self.minutes, self.clock = service, probe, minutes, clock
        self.since = None

    def __call__(self) -> Check:
        ready, reason = self.probe()
        now = self.clock.now()
        if ready:
            self.since = None
            return Check(False, f"{self.service} готов")
        self.since = self.since or now
        down = (now - self.since).total_seconds() / 60
        return Check(
            down >= self.minutes,
            f"{self.service} не готов {round(down)} мин: {reason}",
            {"service": self.service, "minutes": round(down, 1)},
        )


def http_probe(url: str, client: httpx.Client) -> Callable[[], tuple[bool, str]]:
    def probe() -> tuple[bool, str]:
        try:
            response = client.get(url)
        except httpx.HTTPError as exc:
            return False, f"нет ответа ({type(exc).__name__})"
        if response.status_code == 200:
            return True, ""
        problems = response.json().get("problems", {}) if response.content else {}
        return False, ", ".join(sorted(problems)) or f"ответ {response.status_code}"

    return probe


class ErrorRateRule:
    """Доля ответов 5xx шлюза за интервал между проверками (по счётчикам метрик)."""

    def __init__(self, metrics: Callable[[], dict], settings: AlertSettings) -> None:
        self.metrics, self.settings = metrics, settings
        self.previous: dict[str, float] | None = None

    def __call__(self) -> Check:
        snapshot = self.metrics()
        current: dict[str, float] = {}
        for c in snapshot.get("counters", []):
            if c["name"] == "http.requests":
                key = c["labels"].get("status", "?")
                current[key] = current.get(key, 0) + c["value"]
        previous, self.previous = self.previous, current
        if previous is None:
            return Check(False, "первое измерение")
        delta = {k: v - previous.get(k, 0) for k, v in current.items()}
        if any(v < 0 for v in delta.values()):  # шлюз перезапускался — счётчики обнулились
            return Check(False, "счётчики сброшены")
        total = sum(delta.values())
        errors = sum(v for k, v in delta.items() if k.startswith("5"))
        if total < self.settings.error_min_requests:
            return Check(False, f"мало запросов: {int(total)}")
        rate = errors / total
        kinds = ", ".join(
            f"{k}: {int(v)}" for k, v in sorted(delta.items()) if k.startswith("5") and v
        )
        return Check(
            rate > self.settings.error_rate,
            f"доля ошибок {rate:.1%} из {int(total)} запросов" + (f" ({kinds})" if kinds else ""),
            {"rate": round(rate, 4), "requests": int(total)},
        )


class UnknownRegionRule:
    """Доля запросов шлюза без определённой страны (счётчик ``gateway.region``).

    Страны и посетителя в счётчике нет — только «известен / неизвестен». Высокая доля
    неизвестных означает, что CDN не присылает страну или шлюз смотрит не туда: тогда
    ограниченные источники закрыты всем читателям, и это надо заметить до жалоб.
    """

    def __init__(self, metrics: Callable[[], dict], settings: AlertSettings) -> None:
        self.metrics, self.settings = metrics, settings
        self.previous: dict[str, float] | None = None

    def __call__(self) -> Check:
        current: dict[str, float] = {}
        for c in self.metrics().get("counters", []):
            if c["name"] == "gateway.region":
                key = c["labels"].get("kind", "?")
                current[key] = current.get(key, 0) + c["value"]
        previous, self.previous = self.previous, current
        if previous is None:
            return Check(False, "первое измерение")
        delta = {k: v - previous.get(k, 0) for k, v in current.items()}
        if any(v < 0 for v in delta.values()):  # шлюз перезапускался — счётчики обнулились
            return Check(False, "счётчики сброшены")
        total = sum(delta.values())
        if total < self.settings.unknown_region_min_requests:
            return Check(False, f"мало запросов: {int(total)}")
        unknown = delta.get("unknown", 0.0)
        rate = unknown / total if total else 0.0
        return Check(
            rate > self.settings.unknown_region_ratio,
            f"регион не определён у {rate:.1%} из {int(total)} запросов",
            {"rate": round(rate, 4), "requests": int(total), "unknown": int(unknown)},
        )


class BudgetRule:
    def __init__(self, budgets: Callable[[], list[dict]], settings: AlertSettings) -> None:
        self.budgets, self.settings = budgets, settings

    def __call__(self) -> Check:
        close = [
            b
            for b in self.budgets()
            if b["limit_usd"] and b["spent_usd"] / b["limit_usd"] >= self.settings.budget_ratio
        ]
        if not close:
            return Check(False, "расход в пределах")
        text = "; ".join(
            f"{b['budget']} за {'сутки' if b['period'] == 'day' else 'месяц'}: "
            f"${b['spent_usd']:.2f} из ${b['limit_usd']:.2f}"
            for b in close
        )
        return Check(True, text, {"budgets": [b["budget"] for b in close]})


class QueueRule:
    """Самая старая ожидающая задача старше порога: исполнитель завис или упал."""

    def __init__(self, engine: Engine, settings: AlertSettings, clock: Clock) -> None:
        self.engine, self.settings, self.clock = engine, settings, clock

    def __call__(self) -> Check:
        with self.engine.connect() as conn:
            oldest, count = conn.execute(
                select(func.min(jobs.c.enqueued_at), func.count()).where(jobs.c.status == "pending")
            ).one()
        if oldest is None:
            return Check(False, "очередь пуста")
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=self.clock.now().tzinfo)
        age = (self.clock.now() - oldest).total_seconds() / 60
        return Check(
            age > self.settings.queue_age_minutes,
            f"задач в очереди: {count}, самой старой {round(age)} мин",
            {"pending": count, "minutes": round(age, 1)},
        )


class BackupRule:
    """Последняя копия неудачна или слишком старая; последняя проверка восстановления упала."""

    def __init__(self, engine: Engine, settings: AlertSettings, clock: Clock) -> None:
        self.engine, self.settings, self.clock = engine, settings, clock

    def __call__(self) -> Check:
        runs = ops_schema.runs
        with self.engine.connect() as conn:

            def last(kind: str):
                return conn.execute(
                    select(runs)
                    .where(runs.c.kind == kind)
                    .order_by(runs.c.time.desc(), runs.c.id.desc())
                    .limit(1)
                ).first()

            backup, verify = last("backup"), last("verify")
            good = conn.scalar(
                select(func.max(runs.c.time)).where((runs.c.kind == "backup") & runs.c.ok)
            )
        problems = []
        if backup is not None and not backup.ok:
            problems.append(f"копия не создана: {backup.detail.get('reason', '?')[:120]}")
        if good is not None:
            if good.tzinfo is None:
                good = good.replace(tzinfo=self.clock.now().tzinfo)
            hours = (self.clock.now() - good).total_seconds() / 3600
            if hours > self.settings.backup_age_hours:
                problems.append(f"последней удачной копии {round(hours)} ч")
        elif backup is None:
            return Check(False, "копий ещё не было")
        if verify is not None and not verify.ok:
            problems.append(
                f"проверка восстановления не прошла: {verify.detail.get('reason', '?')[:120]}"
            )
        return Check(bool(problems), "; ".join(problems) or "копии в порядке")


def standard_rules(
    env: dict[str, str],
    engine: Engine,
    settings: AlertSettings,
    clock: Clock | None = None,
    client: httpx.Client | None = None,
) -> dict[str, tuple[str, Rule]]:
    clock = clock or SystemClock()
    client = client or httpx.Client(timeout=5)
    token = env.get("PHILOGRAPH_INTERNAL_TOKEN", "")
    rules: dict[str, tuple[str, Rule]] = {}
    for service in ("library", "search", "assistant", "knowledge", "llm", "gateway"):
        url = env.get(f"PHILOGRAPH_{service.upper()}_URL")
        if url:
            rules[f"ready:{service}"] = (
                f"Сервис {service}",
                ReadinessRule(
                    service,
                    http_probe(f"{url}/health/ready", client),
                    settings.not_ready_minutes,
                    clock,
                ),
            )
    if env.get("PHILOGRAPH_GATEWAY_URL"):
        gateway = env["PHILOGRAPH_GATEWAY_URL"]

        def gateway_metrics() -> dict:
            return client.get(
                f"{gateway}/internal/metrics", headers={"X-Internal-Token": token}
            ).json()

        rules["errors:gateway"] = (
            "Ошибки на сайте",
            ErrorRateRule(gateway_metrics, settings),
        )
        rules["region"] = ("Регион читателя", UnknownRegionRule(gateway_metrics, settings))
    if env.get("PHILOGRAPH_LLM_URL"):
        llm = env["PHILOGRAPH_LLM_URL"]
        rules["budget"] = (
            "Бюджет на модели",
            BudgetRule(lambda: client.get(f"{llm}/v1/budgets").json(), settings),
        )
    rules["queue"] = ("Очередь задач", QueueRule(engine, settings, clock))
    rules["backup"] = ("Резервные копии", BackupRule(engine, settings, clock))
    return rules


def from_env(env: dict[str, str] | None = None) -> Alerts:
    from philograph.platform.db import make_engine
    from philograph.platform.queue import migrations as queue_migrations

    env = env if env is not None else dict(os.environ)
    engine = make_engine(
        env["PHILOGRAPH_DATABASE_URL"], [ops_schema.SCHEMA, queue_migrations.schema]
    )
    ops_schema.migrations.upgrade(engine)
    queue_migrations.upgrade(engine)
    return Alerts(standard_rules(env, engine, AlertSettings.from_env(env)), channel_from(env))
