"""Ядро сервиса LLM без привязки к HTTP.

Каждый вызов проходит одни и те же шаги: роль → шаблон → кэш → резерв в бюджете →
вызов провайдера с повторами → фактическая стоимость → журнал → проверка порогов.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from philograph.llm import store as st
from philograph.llm.config import Budget, GatewayConfig, Price, RoleConfig
from philograph.llm.providers import (
    Completion,
    Message,
    PermanentProviderError,
    Provider,
    ProviderRequest,
    TransientProviderError,
    Usage,
)
from philograph.llm.templates import Template, TemplateRegistry, UnknownTemplate, render_data
from philograph.platform import context, events
from philograph.platform.clock import Clock, SystemClock
from philograph.platform.metrics import metrics

_CALL_FIELDS = (
    "caller",
    "operation",
    "role",
    "model",
    "budget",
    "kind",
    "attempt",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "duration_ms",
    "cache_hit",
    "template",
    "template_version",
)
events.define(
    "llm.call.completed",
    "info",
    "Вызов модели выполнен",
    required=_CALL_FIELDS,
    optional=("cached_input_tokens",),
)
events.define(
    "llm.call.failed",
    "error",
    "Вызов модели не удался",
    required=("caller", "operation", "role", "model", "kind", "attempt", "retryable"),
)
events.define(
    "llm.call.retry",
    "warning",
    "Временная ошибка провайдера, вызов повторяется",
    required=("role", "model", "attempt", "reason"),
)
events.define(
    "llm.call.rejected",
    "warning",
    "Вызов отклонён до обращения к провайдеру",
    required=("reason", "caller", "operation"),
    optional=("role", "budget", "template"),
)
events.define(
    "llm.stream.interrupted",
    "error",
    "Поток ответа модели оборвался",
    required=("role", "model", "chunks"),
)
events.define(
    "llm.schema.mismatch",
    "warning",
    "Ответ модели не соответствует схеме",
    required=("role", "model", "attempt", "problem"),
)
events.define(
    "llm.budget.near_limit",
    "warning",
    "Расход бюджета близок к лимиту",
    required=("budget", "period", "spent_usd", "limit_usd"),
)
events.define(
    "llm.texts.purged",
    "info",
    "Удалены тексты запросов старше срока хранения",
    required=("count", "older_than"),
)


class UnknownRole(Exception):
    pass


class BudgetExhausted(Exception):
    def __init__(self, scope: str, budget: str) -> None:
        super().__init__(f"лимит исчерпан: {scope}")
        self.scope = scope  # day | run
        self.budget = budget


class ProviderFailed(Exception):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class SchemaMismatch(Exception):
    pass


@dataclass(frozen=True)
class Call:
    """Что сервис просит у модели."""

    role: str
    template: str
    caller: str
    operation: str
    budget: Budget
    data: dict[str, str] = field(default_factory=dict)
    history: tuple[Message, ...] = ()
    temperature: float = 0.0
    use_cache: bool = True
    max_output_tokens: int | None = None


@dataclass(frozen=True)
class Result:
    text: str
    usage: Usage
    cost_usd: float
    cache_hit: bool
    model: str
    template_version: str


@dataclass(frozen=True)
class StreamEvent:
    type: str  # delta | done | error
    text: str = ""
    result: Result | None = None
    error: str | None = None


M = TypeVar("M", bound=BaseModel)


def cost_of(price: Price, usage: Usage, minute_of_day: int | None) -> float:
    """Стоимость в долларах. ``minute_of_day=None`` — без ночной скидки (верхняя оценка)."""
    miss = max(0, usage.input_tokens - usage.cached_input_tokens)
    total = (
        miss * price.input_cache_miss
        + usage.cached_input_tokens * price.input_cache_hit
        + usage.output_tokens * price.output
    ) / 1_000_000
    if minute_of_day is not None and price.night is not None and price.night.active(minute_of_day):
        total *= price.night.multiplier
    return round(total, 8)


def _parser(schema: Any) -> Callable[[str], Any]:
    if isinstance(schema, dict):
        import jsonschema

        validator = jsonschema.Draft202012Validator(schema)

        def parse_json(text: str) -> dict[str, Any]:
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError("неверный JSON") from exc
            errors = sorted(validator.iter_errors(value), key=lambda e: e.path)
            if errors:
                raise ValueError(errors[0].message)
            return value

        return parse_json
    return schema.model_validate_json


def _problem(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return exc.errors()[0]["msg"] if exc.errors() else "неверный JSON"
    return str(exc) or "неверный JSON"


class LLMGateway:
    def __init__(
        self,
        config: GatewayConfig,
        providers: dict[str, Provider],
        templates: TemplateRegistry,
        store: st.Store,
        *,
        clock: Clock | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.providers = providers
        self.templates = templates
        self.store = store
        self.clock = clock or SystemClock()
        self.sleep = sleep
        self._budget_lock = threading.Lock()

    # --- подготовка ---

    def _role(self, role: str, caller: str, operation: str) -> RoleConfig:
        try:
            return self.config.roles[role]
        except KeyError:
            events.emit(
                "llm.call.rejected",
                reason="unknown_role",
                role=role,
                caller=caller,
                operation=operation,
            )
            raise UnknownRole(role) from None

    def _template(self, call: Call) -> Template:
        try:
            return self.templates.get(call.template)
        except UnknownTemplate:
            events.emit(
                "llm.call.rejected",
                reason="unknown_template",
                template=call.template,
                caller=call.caller,
                operation=call.operation,
            )
            raise

    @staticmethod
    def _messages(template: Template, call: Call) -> tuple[Message, ...]:
        user = render_data(template, call.data)
        return (Message("system", template.instructions), *call.history, Message("user", user))

    def _cache_key(
        self,
        kind: str,
        role: RoleConfig,
        template: Template,
        messages: tuple[Message, ...],
        call: Call,
    ) -> str | None:
        if not call.use_cache or call.temperature != 0:
            return None
        payload = json.dumps(
            {
                "kind": kind,
                "provider": role.provider,
                "model": role.model,
                "template": template.name,
                "version": template.version,
                "messages": [(m.role, m.content) for m in messages],
                "max": call.max_output_tokens or role.max_output_tokens,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _minute(self) -> int:
        now = self.clock.now()
        return now.hour * 60 + now.minute

    # --- бюджет ---

    def _estimate(self, role: RoleConfig, messages: tuple[Message, ...], max_out: int) -> float:
        # Верхняя оценка: символ не меньше трети токена, ответ максимальной длины.
        prompt_tokens = sum(len(m.content) for m in messages) // 2 + 16
        usage = Usage(prompt_tokens, 0, max_out)
        return cost_of(self.config.prices[role.model], usage, minute_of_day=None)

    def _reserve(self, call: Call, estimate: float) -> int:
        now = self.clock.now()
        day = st.day_of(now)
        run = context.run_id()
        with self._budget_lock:
            limit = self.config.budgets.get(call.budget)
            if limit and limit.daily_limit_usd is not None:
                spent = self.store.spent(call.budget, day)
                if spent + estimate > limit.daily_limit_usd:
                    events.emit(
                        "llm.call.rejected",
                        reason="budget_exhausted",
                        budget=call.budget,
                        caller=call.caller,
                        operation=call.operation,
                    )
                    raise BudgetExhausted("day", call.budget)
            if run is not None:
                run_limit = self.store.run_limit(run)
                if run_limit is not None and self.store.run_spent(run) + estimate > run_limit:
                    events.emit(
                        "llm.call.rejected",
                        reason="run_limit_exhausted",
                        budget=call.budget,
                        caller=call.caller,
                        operation=call.operation,
                    )
                    raise BudgetExhausted("run", call.budget)
            return self.store.reserve(call.budget, day, run, estimate, now)

    def _check_alerts(self, budget: str) -> None:
        conf = self.config.budgets.get(budget)  # type: ignore[call-overload]
        if conf is None:
            return
        now = self.clock.now()
        checks = []
        if conf.daily_limit_usd:
            day = st.day_of(now)
            checks.append(("day", day, self.store.spent(budget, day), conf.daily_limit_usd))
        if conf.monthly_limit_usd:
            first, last = st.month_bounds(now)
            checks.append(
                (
                    "month",
                    first[:7],
                    self.store.spent_between(budget, first, last),
                    conf.monthly_limit_usd,
                )
            )
        for period, label, spent, limit in checks:
            if spent >= conf.alert_ratio * limit and self.store.mark_alert(
                f"{budget}:{period}:{label}"
            ):
                events.emit(
                    "llm.budget.near_limit",
                    budget=budget,
                    period=period,
                    spent_usd=round(spent, 6),
                    limit_usd=limit,
                )

    # --- журнал ---

    def _record(
        self,
        *,
        call: Call,
        kind: str,
        role: RoleConfig,
        template: Template,
        attempt: int,
        usage: Usage,
        cost: float,
        duration_ms: float,
        cache_hit: bool,
        status: str,
        error_kind: str | None,
        prompt: str | None,
        response: str | None,
    ) -> None:
        self.store.record_call(
            time=self.clock.now(),
            caller=call.caller,
            operation=call.operation,
            kind=kind,
            role=call.role,
            model=role.model,
            budget=call.budget,
            run_id=context.run_id(),
            request_id=context.request_id(),
            template=template.name,
            template_version=template.version,
            attempt=attempt,
            input_tokens=usage.input_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=cost,
            duration_ms=duration_ms,
            cache_hit=cache_hit,
            status=status,
            error_kind=error_kind,
            prompt_text=prompt,
            response_text=response,
        )
        if status == "ok":
            events.emit(
                "llm.call.completed",
                caller=call.caller,
                operation=call.operation,
                role=call.role,
                model=role.model,
                budget=call.budget,
                kind=kind,
                attempt=attempt,
                input_tokens=usage.input_tokens,
                cached_input_tokens=usage.cached_input_tokens,
                output_tokens=usage.output_tokens,
                cost_usd=cost,
                duration_ms=duration_ms,
                cache_hit=cache_hit,
                template=template.name,
                template_version=template.version,
            )
            metrics.inc("llm.cost_usd", cost, budget=call.budget)

    @staticmethod
    def _prompt_text(messages: tuple[Message, ...]) -> str:
        return "\n\n".join(f"[{m.role}]\n{m.content}" for m in messages)

    # --- вызовы ---

    def _prepare(
        self, call: Call, kind: str
    ) -> tuple[RoleConfig, Template, tuple[Message, ...], str | None, int]:
        role = self._role(call.role, call.caller, call.operation)
        template = self._template(call)
        messages = self._messages(template, call)
        key = self._cache_key(kind, role, template, messages, call)
        return role, template, messages, key, call.max_output_tokens or role.max_output_tokens

    def _from_cache(
        self,
        call: Call,
        kind: str,
        role: RoleConfig,
        template: Template,
        key: str | None,
        messages: tuple[Message, ...],
    ) -> Result | None:
        if key is None:
            return None
        cached = self.store.cache_get(key)
        if cached is None:
            return None
        usage = Usage(
            cached["input_tokens"], cached["cached_input_tokens"], cached["output_tokens"]
        )
        self._record(
            call=call,
            kind=kind,
            role=role,
            template=template,
            attempt=1,
            usage=usage,
            cost=0.0,
            duration_ms=0.0,
            cache_hit=True,
            status="ok",
            error_kind=None,
            prompt=self._prompt_text(messages),
            response=cached["text"],
        )
        return Result(cached["text"], usage, 0.0, True, role.model, template.version)

    def _provider_request(
        self,
        role: RoleConfig,
        messages: tuple[Message, ...],
        max_out: int,
        call: Call,
        json_mode: bool = False,
    ) -> ProviderRequest:
        return ProviderRequest(
            model=role.model,
            messages=messages,
            max_output_tokens=max_out,
            temperature=call.temperature,
            timeout_seconds=role.timeout_seconds,
            json_mode=json_mode,
        )

    def _complete(
        self,
        call: Call,
        kind: str,
        role: RoleConfig,
        template: Template,
        messages: tuple[Message, ...],
        max_out: int,
        key: str | None,
        json_mode: bool = False,
    ) -> Result:
        reservation = self._reserve(call, self._estimate(role, messages, max_out))
        provider = self.providers[role.provider]
        request = self._provider_request(role, messages, max_out, call, json_mode)
        prompt = self._prompt_text(messages)
        attempt = 0
        try:
            while True:
                attempt += 1
                started = time.perf_counter()
                try:
                    completion: Completion = provider.generate(request)
                except TransientProviderError as exc:
                    self._fail(
                        call,
                        kind,
                        role,
                        template,
                        attempt,
                        started,
                        prompt,
                        retryable=True,
                        reason=str(exc),
                    )
                    if attempt > self.config.max_retries:
                        raise ProviderFailed(str(exc), retryable=True) from exc
                    events.emit(
                        "llm.call.retry",
                        role=call.role,
                        model=role.model,
                        attempt=attempt,
                        reason=str(exc),
                    )
                    self.sleep(self.config.retry_base_seconds * 2 ** (attempt - 1))
                    continue
                except PermanentProviderError as exc:
                    self._fail(
                        call,
                        kind,
                        role,
                        template,
                        attempt,
                        started,
                        prompt,
                        retryable=False,
                        reason=str(exc),
                    )
                    raise ProviderFailed(str(exc), retryable=False) from exc
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                break
        except BaseException:
            self.store.release(reservation)
            raise
        cost = cost_of(self.config.prices[role.model], completion.usage, self._minute())
        self.store.settle(reservation, cost)
        self._record(
            call=call,
            kind=kind,
            role=role,
            template=template,
            attempt=attempt,
            usage=completion.usage,
            cost=cost,
            duration_ms=duration_ms,
            cache_hit=False,
            status="ok",
            error_kind=None,
            prompt=prompt,
            response=completion.text,
        )
        if key is not None:
            self.store.cache_put(
                key,
                {
                    "text": completion.text,
                    "input_tokens": completion.usage.input_tokens,
                    "cached_input_tokens": completion.usage.cached_input_tokens,
                    "output_tokens": completion.usage.output_tokens,
                },
                self.clock.now(),
            )
        self._check_alerts(call.budget)
        return Result(completion.text, completion.usage, cost, False, role.model, template.version)

    def _fail(
        self,
        call: Call,
        kind: str,
        role: RoleConfig,
        template: Template,
        attempt: int,
        started: float,
        prompt: str,
        *,
        retryable: bool,
        reason: str,
    ) -> None:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        error_kind = "provider_transient" if retryable else "provider_permanent"
        self._record(
            call=call,
            kind=kind,
            role=role,
            template=template,
            attempt=attempt,
            usage=Usage(0, 0, 0),
            cost=0.0,
            duration_ms=duration_ms,
            cache_hit=False,
            status="error",
            error_kind=error_kind,
            prompt=prompt,
            response=None,
        )
        events.emit(
            "llm.call.failed",
            caller=call.caller,
            operation=call.operation,
            role=call.role,
            model=role.model,
            kind=kind,
            attempt=attempt,
            retryable=retryable,
            error_kind=error_kind,
        )

    def generate(self, call: Call) -> Result:
        role, template, messages, key, max_out = self._prepare(call, "generate")
        cached = self._from_cache(call, "generate", role, template, key, messages)
        if cached is not None:
            return cached
        return self._complete(call, "generate", role, template, messages, max_out, key)

    def structured(self, call: Call, schema: type[M] | dict[str, Any]) -> M | dict[str, Any]:
        """Ответ, прошедший проверку по схеме. После повторов — ``SchemaMismatch``.

        Схема — класс pydantic (вызов внутри процесса) или JSON Schema (вызов по HTTP).
        """
        parse = _parser(schema)
        role, template, messages, key, max_out = self._prepare(call, "structured")
        cached = self._from_cache(call, "structured", role, template, key, messages)
        if cached is not None:
            return parse(cached.text)
        problem = ""
        for attempt in range(1, self.config.schema_retries + 2):
            # Повтор не должен брать из кэша неудачный ответ, поэтому ключ только у успеха.
            result = self._complete(
                call, "structured", role, template, messages, max_out, key=None, json_mode=True
            )
            try:
                parsed = parse(result.text)
            except (ValidationError, ValueError) as exc:
                problem = _problem(exc)
                events.emit(
                    "llm.schema.mismatch",
                    role=call.role,
                    model=role.model,
                    attempt=attempt,
                    problem=problem,
                )
                continue
            if key is not None:
                self.store.cache_put(
                    key,
                    {
                        "text": result.text,
                        "input_tokens": result.usage.input_tokens,
                        "cached_input_tokens": result.usage.cached_input_tokens,
                        "output_tokens": result.usage.output_tokens,
                    },
                    self.clock.now(),
                )
            return parsed
        raise SchemaMismatch(f"ответ не соответствует схеме: {problem}")

    def stream(self, call: Call) -> Iterator[StreamEvent]:
        """Поток фрагментов. Обрыв — событие ``error`` после полученных фрагментов."""
        role, template, messages, key, max_out = self._prepare(call, "stream")
        cached = self._from_cache(call, "stream", role, template, key, messages)
        if cached is not None:
            yield StreamEvent("delta", text=cached.text)
            yield StreamEvent("done", result=cached)
            return
        reservation = self._reserve(call, self._estimate(role, messages, max_out))
        provider = self.providers[role.provider]
        request = self._provider_request(role, messages, max_out, call)
        prompt = self._prompt_text(messages)
        attempt = 0
        text = ""
        chunks = 0
        usage: Usage | None = None
        started = time.perf_counter()

        def produced_text() -> str:
            return text  # текст, полученный к моменту остановки

        while True:
            attempt += 1
            try:
                for chunk in self._guard_stop(
                    provider.stream(request), reservation, role, messages, produced_text
                ):
                    if chunk.text:
                        text += chunk.text
                        chunks += 1
                        yield StreamEvent("delta", text=chunk.text)
                    if chunk.usage is not None:
                        usage = chunk.usage
                break
            except (TransientProviderError, PermanentProviderError) as exc:
                retryable = isinstance(exc, TransientProviderError)
                self._fail(
                    call,
                    "stream",
                    role,
                    template,
                    attempt,
                    started,
                    prompt,
                    retryable=retryable,
                    reason=str(exc),
                )
                # Повторять можно, только пока читатель ничего не получил.
                if chunks == 0 and retryable and attempt <= self.config.max_retries:
                    events.emit(
                        "llm.call.retry",
                        role=call.role,
                        model=role.model,
                        attempt=attempt,
                        reason=str(exc),
                    )
                    self.sleep(self.config.retry_base_seconds * 2 ** (attempt - 1))
                    continue
                if chunks:
                    events.emit(
                        "llm.stream.interrupted",
                        role=call.role,
                        model=role.model,
                        chunks=chunks,
                        error_kind="stream_interrupted",
                    )
                partial = Usage(sum(len(m.content) for m in messages) // 4, 0, len(text) // 4)
                cost = cost_of(self.config.prices[role.model], partial, self._minute())
                if chunks:
                    self.store.settle(reservation, cost)
                else:
                    self.store.release(reservation)
                yield StreamEvent("error", text=text, error=str(exc))
                return
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        usage = usage or Usage(sum(len(m.content) for m in messages) // 4, 0, len(text) // 4)
        cost = cost_of(self.config.prices[role.model], usage, self._minute())
        self.store.settle(reservation, cost)
        self._record(
            call=call,
            kind="stream",
            role=role,
            template=template,
            attempt=attempt,
            usage=usage,
            cost=cost,
            duration_ms=duration_ms,
            cache_hit=False,
            status="ok",
            error_kind=None,
            prompt=prompt,
            response=text,
        )
        if key is not None:
            self.store.cache_put(
                key,
                {
                    "text": text,
                    "input_tokens": usage.input_tokens,
                    "cached_input_tokens": usage.cached_input_tokens,
                    "output_tokens": usage.output_tokens,
                },
                self.clock.now(),
            )
        self._check_alerts(call.budget)
        yield StreamEvent(
            "done", result=Result(text, usage, cost, False, role.model, template.version)
        )

    def _guard_stop(
        self,
        chunks,
        reservation: int,
        role: RoleConfig,
        messages: tuple[Message, ...],
        produced: Callable[[], str],
    ):
        """Если получатель закрыл поток (читатель нажал «остановить»), резерв закрывается
        стоимостью уже полученной части, а не висит оценкой до конца суток."""
        try:
            yield from chunks
        except GeneratorExit:
            partial = Usage(sum(len(m.content) for m in messages) // 4, 0, len(produced()) // 4)
            self.store.settle(
                reservation, cost_of(self.config.prices[role.model], partial, self._minute())
            )
            raise

    def embed(
        self,
        texts: list[str],
        *,
        caller: str,
        operation: str,
        budget: Budget,
        role: str = "embeddings",
    ) -> tuple[list[list[float]], float]:
        role_conf = self._role(role, caller, operation)
        template = Template("embeddings", "", ())
        call = Call(
            role=role, template="embeddings", caller=caller, operation=operation, budget=budget
        )
        usage_estimate = Usage(sum(len(t) for t in texts) // 2 + 1, 0, 0)
        estimate = cost_of(self.config.prices[role_conf.model], usage_estimate, None)
        reservation = self._reserve(call, estimate)
        provider = self.providers[role_conf.provider]
        attempt = 0
        try:
            while True:
                attempt += 1
                started = time.perf_counter()
                try:
                    vectors, usage = provider.embed(
                        role_conf.model, texts, role_conf.timeout_seconds
                    )
                    break
                except TransientProviderError as exc:
                    self._fail(
                        call,
                        "embed",
                        role_conf,
                        template,
                        attempt,
                        started,
                        "",
                        retryable=True,
                        reason=str(exc),
                    )
                    if attempt > self.config.max_retries:
                        raise ProviderFailed(str(exc), retryable=True) from exc
                    self.sleep(self.config.retry_base_seconds * 2 ** (attempt - 1))
                except PermanentProviderError as exc:
                    self._fail(
                        call,
                        "embed",
                        role_conf,
                        template,
                        attempt,
                        started,
                        "",
                        retryable=False,
                        reason=str(exc),
                    )
                    raise ProviderFailed(str(exc), retryable=False) from exc
        except BaseException:
            self.store.release(reservation)
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        cost = cost_of(self.config.prices[role_conf.model], usage, self._minute())
        self.store.settle(reservation, cost)
        self._record(
            call=call,
            kind="embed",
            role=role_conf,
            template=template,
            attempt=attempt,
            usage=usage,
            cost=cost,
            duration_ms=duration_ms,
            cache_hit=False,
            status="ok",
            error_kind=None,
            prompt=None,
            response=None,
        )
        self._check_alerts(budget)
        return vectors, cost

    # --- обслуживание ---

    def set_run_limit(self, run_id: str, limit_usd: float) -> None:
        self.store.set_run_limit(run_id, limit_usd)

    def purge_old_texts(self) -> int:
        border = self.clock.now() - timedelta(days=self.config.text_retention_days)
        count = self.store.purge_texts(border)
        events.emit("llm.texts.purged", count=count, older_than=border.isoformat())
        return count

    def spend_summary(
        self, days: int = 1, group_by: tuple[str, ...] = ("budget",)
    ) -> list[dict[str, Any]]:
        allowed = {"budget", "caller", "operation", "role", "run_id", "model"}
        if not set(group_by) <= allowed:
            raise ValueError(f"группировка только по: {', '.join(sorted(allowed))}")
        now = self.clock.now()
        return self.store.spend_summary(
            now - timedelta(days=days), now + timedelta(seconds=1), group_by
        )
