"""Сценарии и инварианты abuse-protection, дополняющие test_limits.py (тот же стенд шлюза)."""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from philograph.gateway.limits import PAGE_COOKIE, Limits, LimitSettings, Quota, paid_operation

from .test_limits import UA, Upstreams, gw  # noqa: F401 — стенд шлюза как фикстура

req = pytest.mark.req
AP = "abuse-protection"


# --- Лимит платных операций на посетителя --------------------------------------------


@req(AP, "Лимит платных операций на посетителя", scenario="Лимит в час")
def test_hourly_limit_tells_when_to_ask_again_and_model_is_not_called(gw, events):  # noqa: F811
    reader = gw.visit()
    for _ in range(2):  # лимит стенда: два вопроса в час
        assert gw.ask(reader) == [{"type": "done"}]
    assert gw.up.count("ask") == 2
    refused = gw.ask(reader)
    assert len(refused) == 1 and refused[0]["type"] == "unavailable"
    assert refused[0]["reason"] == "visitor_limit"
    assert refused[0]["retry_after_seconds"] == 3600
    assert re.search(r"Спросите снова через", refused[0]["message"])
    assert gw.up.count("ask") == 2  # модель не вызывалась
    (fired,) = events.where("gateway.limit.triggered", kind="hourly")
    assert fired["operation"] == "ask" and fired["retry_after_seconds"] == 3600
    gw.clock.advance(minutes=30)
    assert gw.ask(reader)[0]["retry_after_seconds"] == 1800  # время ожидания убывает


@req(AP, "Лимит платных операций на посетителя", invariant="и в час, и в сутки")
def test_daily_limit_kind_and_wait_until_midnight(gw, events):  # noqa: F811
    reader = gw.visit()
    for _ in range(2):
        gw.ask(reader)
    gw.clock.advance(hours=1, seconds=1)
    gw.ask(reader)  # третий за сутки — последний
    gw.clock.advance(hours=1, seconds=1)
    refused = gw.ask(reader)[0]
    assert refused["reason"] == "visitor_limit"
    (fired,) = events.where("gateway.limit.triggered", kind="daily")
    assert fired["operation"] == "ask" and 0 < fired["retry_after_seconds"] <= 86400
    assert gw.up.count("ask") == 3


@req(
    AP,
    "Лимит платных операций на посетителя",
    invariant="посетитель — хеш адреса и признака браузера",
)
def test_visitor_is_address_and_browser_pair(gw, events):  # noqa: F811
    first = gw.visit("203.0.113.5")
    for _ in range(3):
        gw.ask(first)
    assert gw.ask(first)[0]["reason"] == "visitor_limit"
    # Тот же адрес, другой браузер — другой посетитель.
    other_browser = TestClient(
        gw.app, headers={"User-Agent": "Mozilla/5.0 other", "X-Forwarded-For": "203.0.113.5"}
    )
    other_browser.get("/read")
    assert gw.ask(other_browser) == [{"type": "done"}]
    # Другой адрес с тем же браузером — тоже.
    assert gw.ask(gw.visit("203.0.113.6")) == [{"type": "done"}]
    visitors = {e["visitor"] for e in events.of("gateway.limit.triggered")}
    assert len(visitors) == 1 and "203.0.113.5" not in visitors.pop()


@req(
    AP,
    "Лимит платных операций на посетителя",
    invariant="платные операции: вопрос, достройка графа, описание карточки",
)
@pytest.mark.parametrize(
    ("method", "path", "operation"),
    [
        ("POST", "/api/assistant/v1/ask", "ask"),
        ("POST", "/api/knowledge/v1/graph/build", "graph"),
        ("POST", "/api/knowledge/v1/entities/e1/description", "description"),
    ],
)
def test_paid_operations_are_recognised(method, path, operation):
    assert paid_operation(method, path) == operation
    assert paid_operation("GET", path) is None
    assert paid_operation(method, path + "/x") is None


@req(AP, "Лимит платных операций на посетителя", invariant="значения лимитов задаются настройкой")
def test_quota_values_come_from_settings():
    defaults = LimitSettings()
    assert defaults.quotas["ask"] == Quota(20, 100)
    configured = LimitSettings.from_env({"PHILOGRAPH_LIMIT_ASK": "7/9"})
    assert configured.quotas["ask"] == Quota(7, 9)
    assert configured.quotas["graph"] == defaults.quotas["graph"]
    with pytest.raises(ValueError):
        LimitSettings.from_env({"PHILOGRAPH_LIMIT_ASK": "много"})


@req(
    AP,
    "Лимит платных операций на посетителя",
    invariant="счётчики операций раздельны: исчерпанные вопросы не закрывают граф",
)
def test_quotas_are_per_operation(gw, events):  # noqa: F811
    reader = gw.visit()
    for _ in range(2):
        gw.ask(reader)
    assert gw.ask(reader)[0]["reason"] == "visitor_limit"
    graph = reader.post(
        "/api/knowledge/v1/graph/build", json={"entity_id": "e1", "generation": True}
    )
    assert json.loads(graph.text)["request"]["generation"] is True
    assert [e["operation"] for e in events.of("gateway.limit.triggered")] == ["ask"]


# --- Бесплатное без ограничений платных ----------------------------------------------


@req(AP, "Бесплатное без ограничений платных", scenario="Лимит исчерпан")
def test_chapter_and_card_open_after_limit_exhausted(gw, events):  # noqa: F811
    gw.up.app.get("/library/api/v1/sources/s1/chapters/c1")(lambda: {"blocks": ["текст главы"]})
    reader = gw.visit()
    for _ in range(2):
        gw.ask(reader)
    assert gw.ask(reader)[0]["reason"] == "visitor_limit"
    chapter = reader.get("/api/v1/sources/s1/chapters/c1")
    card = reader.get("/api/knowledge/v1/entities/e1/card")
    assert chapter.status_code == 200 and chapter.json() == {"blocks": ["текст главы"]}
    assert card.status_code == 200 and card.json() == {"id": "e1"}
    # Бесплатное не считается и не порождает срабатываний.
    assert len(events.of("gateway.limit.triggered")) == 1


@req(
    AP,
    "Бесплатное без ограничений платных",
    invariant="чтение не требует токена страницы и не считается в платных",
)
def test_free_reads_work_without_page_token_and_do_not_consume_quota(gw, events):  # noqa: F811
    script = TestClient(gw.app, headers={**UA, "X-Forwarded-For": "198.51.100.9"})
    for _ in range(10):
        assert script.get("/api/v1/sources").status_code == 200
        assert script.get("/api/knowledge/v1/entities/e1/card").status_code == 200
    events.assert_none("gateway.limit.triggered")


# --- Общий лимит частоты -------------------------------------------------------------


@req(AP, "Общий лимит частоты", scenario="Скрипт")
def test_hundreds_of_requests_per_second_mostly_refused_site_serves_others(gw, events):  # noqa: F811
    gw.limits.settings = LimitSettings(rate_per_second=20.0, burst=50, trusted_proxy=True)
    bot = TestClient(gw.app, headers={**UA, "X-Forwarded-For": "192.0.2.50"})
    statuses = [bot.get("/api/v1/sources").status_code for _ in range(400)]  # время стоит
    assert statuses.count(200) == 50 and statuses.count(429) == 350
    limited = bot.get("/api/v1/sources")
    assert limited.status_code == 429 and limited.json()["kind"] == "rate_limited"
    assert int(limited.headers["Retry-After"]) >= 1
    assert gw.up.count("map") == 0
    other = TestClient(gw.app, headers={**UA, "X-Forwarded-For": "192.0.2.51"})
    assert other.get("/api/v1/sources").status_code == 200  # сайт отвечает остальным
    rate_events = events.where("gateway.limit.triggered", kind="rate")
    assert len(rate_events) == 351 and all(e["retry_after_seconds"] >= 1 for e in rate_events)
    assert "192.0.2.50" not in repr([e.fields for e in rate_events])


@req(AP, "Общий лимит частоты", invariant="ограничение действует на все запросы, не только платные")
@pytest.mark.parametrize(
    "path", ["/read", "/assets/x.js", "/api/v1/sources", "/api/knowledge/v1/entities/e1/card"]
)
def test_rate_limit_covers_every_route(gw, events, path):  # noqa: F811
    gw.limits.settings = LimitSettings(rate_per_second=1.0, burst=1, trusted_proxy=True)
    client = TestClient(gw.app, headers={**UA, "X-Forwarded-For": "192.0.2.60"})
    client.get(path)
    second = client.get(path)
    assert second.status_code == 429 and second.json()["kind"] == "rate_limited"
    assert len(events.where("gateway.limit.triggered", kind="rate")) == 1


# --- Защита от автоматических запросов -----------------------------------------------


@req(AP, "Защита от автоматических запросов", scenario="Прямой вызов")
def test_direct_call_without_page_token_rejected_and_logged(gw, events):  # noqa: F811
    script = TestClient(gw.app, headers=UA)
    response = script.post("/api/assistant/v1/ask", json={"question": "?"})
    assert response.status_code == 403 and response.json()["kind"] == "page_token_required"
    assert gw.up.count("ask") == 0  # модель не вызывалась
    (fired,) = events.where("gateway.limit.triggered", kind="page_token")
    assert fired["operation"] == "ask" and re.fullmatch(r"[0-9a-f]{20}", fired["visitor"])


@req(
    AP,
    "Защита от автоматических запросов",
    invariant="каждая платная операция с токеном страницы; без него отклоняется",
)
@pytest.mark.parametrize(
    ("path", "operation", "upstream"),
    [
        ("/api/assistant/v1/ask", "ask", "ask"),
        ("/api/knowledge/v1/graph/build", "graph", "graph"),
        ("/api/knowledge/v1/entities/e1/description", "description", "description"),
    ],
)
def test_every_paid_operation_needs_page_token(gw, events, path, operation, upstream):  # noqa: F811
    script = TestClient(gw.app, headers=UA)
    response = script.post(path, json={})
    assert response.status_code == 403 and response.json()["kind"] == "page_token_required"
    assert gw.up.count(upstream) == 0
    assert events.where("gateway.limit.triggered", kind="page_token", operation=operation)
    page = gw.visit()
    assert page.post(path, json={}).status_code == 200  # со страницы — проходит
    assert gw.up.count(upstream) == 1


@req(
    AP,
    "Защита от автоматических запросов",
    invariant="токен подписан, привязан к браузеру и устаревает",
)
@pytest.mark.parametrize(
    "mutate",
    ["empty", "no_dot", "letters", "future", "tampered", "other_browser", "expired"],
)
def test_page_token_rejects_corrupted_and_hostile_tokens(clock, mutate):
    limits = Limits(LimitSettings(), "секрет", clock)
    token = limits.page_token("UA-1")
    assert limits.check_token(token, "UA-1")
    issued, signature = token.split(".")
    cases = {
        "empty": ("", "UA-1"),
        "no_dot": (issued, "UA-1"),
        "letters": (f"abc.{signature}", "UA-1"),
        "future": (f"{int(issued) + 99999}.{signature}", "UA-1"),
        "tampered": (f"{issued}.{'0' * len(signature)}", "UA-1"),
        "other_browser": (token, "UA-2"),
    }
    if mutate == "expired":
        clock.advance(hours=13)
        assert not limits.check_token(token, "UA-1")
    else:
        value, agent = cases[mutate]
        assert not limits.check_token(value, agent)
    assert not limits.check_token(None, "UA-1")


# --- Журнал срабатываний -------------------------------------------------------------


@req(AP, "Журнал срабатываний", scenario="Срабатывание")
def test_hourly_trigger_logged_with_kind_and_visitor_hash_only(gw, events):  # noqa: F811
    reader = gw.visit("203.0.113.5")
    for _ in range(3):
        gw.ask(reader)
    (fired,) = events.where("gateway.limit.triggered", kind="hourly")
    expected = gw.limits.visitor("203.0.113.5", UA["User-Agent"])
    assert fired["visitor"] == expected and fired["kind"] == "hourly"
    text = repr(fired.fields)
    assert "203.0.113.5" not in text and "Mozilla" not in text and "что такое опыт" not in text
    # Хеш с суточной солью: назавтра тот же посетитель выглядит иначе.
    gw.clock.advance(days=1)
    assert gw.limits.visitor("203.0.113.5", UA["User-Agent"]) != expected


@req(
    AP,
    "Журнал срабатываний",
    invariant="каждый вид лимита пишет событие: частота, токен, час, сутки",
)
def test_every_limit_kind_emits_event(gw, events):  # noqa: F811
    gw.limits.settings = LimitSettings(
        rate_per_second=1000.0, burst=1000, quotas={"ask": Quota(1, 2)}, trusted_proxy=True
    )
    TestClient(gw.app, headers=UA).post("/api/assistant/v1/ask", json={})  # без токена
    reader = gw.visit()
    gw.ask(reader)
    gw.ask(reader)  # час
    gw.clock.advance(hours=1, seconds=1)
    gw.ask(reader)  # ok — второй за сутки
    gw.ask(reader)  # сутки
    gw.limits.settings = LimitSettings(rate_per_second=1.0, burst=1, trusted_proxy=True)
    burst = TestClient(gw.app, headers={**UA, "X-Forwarded-For": "192.0.2.70"})
    burst.get("/read")
    burst.get("/read")
    kinds = [e["kind"] for e in events.of("gateway.limit.triggered")]
    assert {"page_token", "hourly", "daily", "rate"} <= set(kinds)
    assert all(
        re.fullmatch(r"[0-9a-f]{20}", e["visitor"]) for e in events.of("gateway.limit.triggered")
    )
