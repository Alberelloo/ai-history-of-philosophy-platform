"""ontology-extraction (reextract-with-claude): «Запуски наполнения» и «Таймаут вызова модели
при извлечении».

По дельте ``specs/ontology-extraction``. Запуск идёт настоящим ``Filling.extract_version`` на
стенде (шлюз — настоящий ``LLMGateway`` на фейковом провайдере) либо поверх поддельного
транспорта шлюза, когда нужны ответы 429/502/503, таймаут или сведения о роли. Вывод —
строка ``filling_runs`` и утверждения; журнал — ``knowledge.run.*`` и
``knowledge.extraction.dropped``.
"""

from __future__ import annotations

import contextlib
import json

import httpx
import pytest
from sqlalchemy import inspect, select, text

from philograph.knowledge import schema as ks
from philograph.platform.client import ServiceClient
from philograph.platform.db import make_engine

from .extraction_stand import Stand
from .reextract_common import (
    FRAGMENT,
    check_run_accounting,
    dropped_codes,
    no_context,
    one_run,
    runs,
)
from .reextract_common import st as stmt

req = pytest.mark.req
EO = "ontology-extraction"
RUNS = "Запуски наполнения"
TIMEOUT = "Таймаут вызова модели при извлечении"

TEXTS = [
    "Кант писал, что всякое знание начинается с опыта.",
    "Юм считал причинность привычкой ума.",
    "Локк отвергал врождённые идеи и сравнивал душу с чистой доской.",
]
Q = ["всякое знание начинается с опыта", "причинность привычкой ума", "отвергал врождённые идеи"]


@pytest.fixture
def stand(onto, engine_for, clock) -> Stand:
    return Stand(onto, engine_for, clock, fragment_size=2)


class GatewayDouble(httpx.BaseTransport):
    """Шлюз моделей на моках: ``GET roles/strong``, ``POST structured``, ``GET spend``."""

    def __init__(self, role=None, structured=None, spend=None) -> None:
        self.role = role  # httpx.Response | Exception | dict | None (404)
        self.structured = structured or []  # по вызовам: ответ, исключение или dict-значение
        self.spend = spend
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/roles/strong"):
            if isinstance(self.role, Exception):
                raise self.role
            if isinstance(self.role, httpx.Response):
                return self.role
            if self.role is None:
                return httpx.Response(404, json={"kind": "unknown_role"})
            return httpx.Response(200, json=self.role)
        if path.endswith("/structured"):
            index = sum(1 for r in self.requests if r.url.path.endswith("/structured")) - 1
            item = self.structured[index] if index < len(self.structured) else {"statements": []}
            if isinstance(item, Exception):
                raise item
            if isinstance(item, httpx.Response):
                return item
            return httpx.Response(200, json={"value": item})
        if path.endswith("/spend"):
            if isinstance(self.spend, httpx.Response):
                return self.spend
            return httpx.Response(200, json=self.spend or [])
        return httpx.Response(404)

    def structured_calls(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path.endswith("/structured")]


def with_double(stand, double: GatewayDouble) -> GatewayDouble:
    stand.filling.llm = ServiceClient("llm", "http://llm", transport=double)
    return double


def one_statement_reply(n=0):
    return {"statements": [stmt("Кант", "holds", "Опыт", 1, Q[n])]}


# --- сценарии ----------------------------------------------------------------------------


@req(EO, RUNS, scenario="Проба")
def test_sample_run_cost_and_estimate(onto, engine_for, clock, events):
    stand = Stand(onto, engine_for, clock, fragment_size=30)
    vid, _ = stand.version([f"Абзац {i} с короткой фразой." for i in range(200)])
    total = len(stand.filling.version_fragments(stand.filling.version(vid)))
    estimate = stand.filling.estimate(vid, sample_fragments=2)
    assert estimate["fragments"] == total == 7  # [1..30], [30..59], …
    per_call = (1000 * 0.3 + 200 * 1.2) / 1_000_000  # тариф flash и токены вызова
    assert estimate["sample_cost_usd"] == pytest.approx(2 * per_call, abs=1e-9)
    assert estimate["estimate_usd"] == pytest.approx(per_call * total, abs=1e-6)
    row = one_run(stand)
    assert row["run_id"] == estimate["run_id"] and row["status"] == "done"
    assert row["fragments"] == 2 and row["cost_usd"] == pytest.approx(2 * per_call, abs=1e-9)
    assert len(events.of(FRAGMENT)) == 2


@req(EO, RUNS, scenario="Модель и метрики запуска через шлюз")
def test_gateway_run_model_and_metrics(stand, clock, events):
    original = stand.model.generate

    def timed(request):
        clock.advance(seconds=2.5)
        return original(request)

    stand.model.generate = timed
    vid, _ = stand.version(TEXTS)  # фрагменты [1,2], [2,3]
    stand.model.replies.extend([one_statement_reply(0), {"statements": []}])
    stand.filling.extract_version(vid)
    row = one_run(stand)
    assert row["model"] == "flash" and row["extractor"] == "gateway"
    assert row["status"] == "done" and row["failure"] is None
    assert row["fragments"] == 2
    assert row["input_tokens"] == 2000 and row["output_tokens"] == 400
    assert row["cost_usd"] == pytest.approx(2 * (1000 * 0.3 + 200 * 1.2) / 1_000_000, abs=1e-9)
    assert row["duration_seconds"] == 5.0  # по часам сервиса: от начала до конца запуска
    assert row["finished_at"] is not None and row["started_at"] is not None
    assert row["source_id"] == stand.filling.version(vid)["source_id"]
    assert row["created"] == 1 and row["dropped"] == 0
    assert {s["provenance"]["model"] for s in stand.statements()} == {"flash"}
    assert {s["provenance"]["run_id"] for s in stand.statements()} == {row["run_id"]}
    [finished] = events.of("knowledge.run.finished")
    assert no_context(finished.fields) == {"run_id", "kind", "created", "dropped"}
    assert (finished["run_id"], finished["kind"]) == (row["run_id"], "extraction")
    assert (finished["created"], finished["dropped"]) == (1, 0)
    assert len(events.of(FRAGMENT)) == 2


@req(EO, RUNS, scenario="Сбой посреди запуска")
def test_failure_in_second_fragment(stand, events):
    vid, ids = stand.version(TEXTS)
    real = stand.onto.statements.paragraph_text

    def broken(paragraph_id):
        if paragraph_id == ids[2]:
            raise RuntimeError("библиотека ответила ошибкой")
        return real(paragraph_id)

    stand.onto.statements.paragraph_text = broken
    stand.model.replies.extend(
        [
            one_statement_reply(0),
            {"statements": [stmt("Локк", "holds", "Идеи", 2, Q[2])]},  # абзац 3 в фрагменте [2,3]
        ]
    )
    with pytest.raises(RuntimeError, match="библиотека ответила ошибкой"):
        stand.filling.extract_version(vid)
    row = one_run(stand)
    assert row["status"] == "failed"
    assert row["failure"].startswith("RuntimeError") and "библиотека" in row["failure"]
    assert row["finished_at"] is not None
    assert len(stand.statements()) == 1  # утверждение первого фрагмента сохранено
    assert row["created"] == 1
    [failed] = events.of("knowledge.run.failed")
    assert no_context(failed.fields) == {"run_id", "kind", "error_kind"}
    assert (failed["run_id"], failed["kind"], failed["error_kind"]) == (
        row["run_id"],
        "extraction",
        "RuntimeError",
    )
    assert events.of("knowledge.run.finished") == []


@req(EO, RUNS, scenario="Ответ шлюза не 200")
def test_gateway_429_budget(stand, events):
    vid, _ = stand.version(TEXTS[:1])
    double = with_double(
        stand,
        GatewayDouble(
            role={"role": "strong", "model": "pro", "call_budget_seconds": 100.0},
            structured=[httpx.Response(429, json={"kind": "budget_exhausted"})],
        ),
    )
    stand.filling.extract_version(vid)
    row = one_run(stand)
    assert row["dropped"] == 1 and row["drop_reasons"] == {"model_budget": 1}
    assert row["status"] == "done" and row["fragments"] == 1
    [event] = events.of("knowledge.extraction.dropped")
    assert event["code"] == "model_budget" and event["run_id"] == row["run_id"]
    assert len(double.structured_calls()) == 1


# --- отказы шлюза: код на каждый вид -----------------------------------------------------

FAILURES = [
    (httpx.Response(429, json={"kind": "budget_exhausted"}), "model_budget"),
    (httpx.Response(429, content=b"not json"), "model_budget"),
    (httpx.Response(400, json={"kind": "bad"}), "model_refused"),
    (httpx.Response(401, json={"kind": "no"}), "model_refused"),
    (httpx.Response(403, content=b"<html>"), "model_refused"),
    (httpx.Response(404, json={"kind": "unknown_role"}), "model_refused"),
    (httpx.Response(422, json={"kind": "bad_schema"}), "model_refused"),
    (httpx.Response(502, json={"kind": "model_schema"}), "model_schema"),
    (httpx.Response(503, json={"kind": "unavailable"}), "model_unavailable"),
    (httpx.Response(500, content=b"boom"), "model_unavailable"),
    (httpx.ReadTimeout("медленно"), "model_timeout"),
    (httpx.ConnectError("нет связи"), "model_unavailable"),
]


@pytest.mark.parametrize(
    ("failure", "code"), FAILURES, ids=[f"{i}-{f[1]}" for i, f in enumerate(FAILURES)]
)
@req(EO, RUNS, invariant="Отказ ответа шлюза и недоступность — одна отбраковка фрагмента с кодом")
def test_gateway_failure_is_one_coded_drop_per_fragment(stand, events, failure, code):
    vid, _ = stand.version(TEXTS)  # два фрагмента: [1,2], [2,3]
    with_double(
        stand,
        GatewayDouble(
            role={"role": "strong", "model": "pro", "call_budget_seconds": 100.0},
            structured=[failure, one_statement_reply(1)],  # второй фрагмент в порядке
        ),
    )
    stand.filling.extract_version(vid)
    row = check_run_accounting(stand, events)
    assert dropped_codes(events) == [code]
    assert row["drop_reasons"] == {code: 1} and row["dropped"] == 1
    assert row["status"] == "done" and row["fragments"] == 2  # отказавший фрагмент обработан
    assert row["created"] == 1 and len(stand.statements()) == 1  # остальные не пострадали
    for e in events.of("knowledge.extraction.dropped"):
        assert set(e.fields) - {"request_id", "service"} == {"run_id", "reason", "code"}


# --- модель запуска: идентификатор, не роль -----------------------------------------------

ROLE_ANSWERS = [
    (
        {"role": "strong", "model": "deepseek-v4-pro", "call_budget_seconds": 10.0},
        "deepseek-v4-pro",
    ),
    ({"role": "strong", "call_budget_seconds": 10.0}, None),  # модель не сообщена
    ({"role": "strong", "model": None, "call_budget_seconds": 10.0}, None),
    (None, None),  # 404
    (httpx.Response(500, json={}), None),
    (httpx.ConnectError("нет связи"), None),
    (httpx.ReadTimeout("медленно"), None),
]


@pytest.mark.parametrize(("role", "model"), ROLE_ANSWERS, ids=range(len(ROLE_ANSWERS)))
@req(EO, RUNS, invariant="filling_runs.model и provenance.model — идентификатор модели, а не роль")
def test_run_model_is_identifier_never_role(stand, events, role, model):
    vid, _ = stand.version(TEXTS[:1])
    with_double(stand, GatewayDouble(role=role, structured=[one_statement_reply(0)]))
    stand.filling.extract_version(vid)
    row = one_run(stand)
    assert row["model"] == model
    assert row["model"] not in ("main", "strong", "fast")
    assert [s["provenance"]["model"] for s in stand.statements()] == [model]
    assert row["status"] == "done"


@req(
    EO,
    RUNS,
    invariant="Модель роли по ответу шлюза: настоящий шлюз с ролью strong на другой модели",
)
def test_model_follows_gateway_role_config(onto, engine_for, clock, events):
    from philograph.knowledge.filling import Filling  # noqa: F401

    from . import extraction_stand as xs

    config = json.loads(json.dumps(xs.CONFIG))
    config["roles"]["strong"] = {"provider": "fake", "model": "pro-model-x"}
    config["prices"]["pro-model-x"] = {
        "input_cache_miss": 1.0,
        "input_cache_hit": 0.1,
        "output": 4.0,
    }
    xs.CONFIG, saved = config, xs.CONFIG
    try:
        stand = Stand(onto, engine_for, clock, fragment_size=2)
    finally:
        xs.CONFIG = saved
    vid, _ = stand.version(TEXTS[:1])
    stand.model.replies.append(one_statement_reply(0))
    stand.filling.extract_version(vid)
    row = one_run(stand)
    assert row["model"] == "pro-model-x"
    assert {s["provenance"]["model"] for s in stand.statements()} == {"pro-model-x"}
    assert row["cost_usd"] == pytest.approx((1000 * 1.0 + 200 * 4.0) / 1_000_000, abs=1e-9)


# --- запуск всегда завершается ------------------------------------------------------------


class Boom(Exception):
    pass


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("сбой"),
        ValueError("x" * 3000),
        KeyError("k"),
        Boom(),
        KeyboardInterrupt(),
        SystemExit(3),
        httpx.ConnectError("нет связи"),
    ],
    ids=lambda e: type(e).__name__,
)
@pytest.mark.parametrize("where", ["statements_add", "model_call_programming_error"])
@req(EO, RUNS, invariant="После выхода из extract_version ни один запуск не running")
def test_no_running_run_after_exit(stand, events, exc, where):
    vid, _ = stand.version(TEXTS)
    if where == "statements_add":

        def boom(*args, **kwargs):
            raise exc

        stand.onto.statements.paragraph_text = boom
        stand.model.replies.append(one_statement_reply(0))
    else:
        double = GatewayDouble(
            role={"role": "strong", "model": "pro", "call_budget_seconds": 1.0},
        )
        double.structured = [one_statement_reply(0)]
        with_double(stand, double)
        original = stand.filling.prompt_data

        def explode(window, schema):
            raise exc

        stand.filling.prompt_data = explode
        del original
    try:
        stand.filling.extract_version(vid)
    except BaseException as caught:
        assert caught is exc  # исключение передаётся дальше без подмены
    rows = runs(stand)
    assert rows and all(r["status"] != "running" for r in rows)
    [row] = rows
    assert row["status"] == "failed" and row["finished_at"] is not None
    assert row["failure"].startswith(type(exc).__name__)
    assert len(row["failure"]) <= 500
    assert events.where("knowledge.run.failed", run_id=row["run_id"], error_kind=type(exc).__name__)


@req(EO, RUNS, invariant="После выхода из extract_version ни один запуск не running")
@pytest.mark.parametrize(
    "spend",
    [
        httpx.Response(200, content=b"not json at all"),
        httpx.Response(200, json={"unexpected": "object"}),
        httpx.Response(200, json=[{"run_id": "x", "cost_usd": "много"}]),
        httpx.Response(500, json={}),
        httpx.Response(200, json=[]),
    ],
    ids=["not-json", "object", "bad-cost", "http-500", "empty"],
)
def test_no_running_run_when_spend_summary_is_broken(stand, events, spend):
    vid, _ = stand.version(TEXTS[:1])
    with_double(
        stand,
        GatewayDouble(
            role={"role": "strong", "model": "pro", "call_budget_seconds": 1.0},
            structured=[one_statement_reply(0)],
            spend=spend,
        ),
    )
    with contextlib.suppress(Exception):
        stand.filling.extract_version(vid)
    rows = runs(stand)
    assert rows and all(r["status"] in ("done", "failed") for r in rows)
    assert all(r["finished_at"] is not None for r in rows)


@req(EO, RUNS, invariant="При пустом результате и без исключения запуск тоже done")
def test_empty_run_is_done(stand, events):
    vid, _ = stand.version(TEXTS)
    stand.filling.extract_version(vid, limit=0)
    row = one_run(stand)
    assert row["status"] == "done" and row["fragments"] == 0 and row["created"] == 0
    assert row["drop_reasons"] in ({}, None) and row["dropped"] == 0


@req(EO, RUNS, invariant="failure — вид исключения и сообщение до 500 знаков")
def test_failure_text_limited(stand, events):
    vid, _ = stand.version(TEXTS[:1])

    def boom(_pid):
        raise ValueError("я" * 2000)

    stand.onto.statements.paragraph_text = boom
    stand.model.replies.append(one_statement_reply(0))
    with pytest.raises(ValueError):
        stand.filling.extract_version(vid)
    failure = one_run(stand)["failure"]
    assert failure.startswith("ValueError: яяя") and len(failure) == 500


@req(
    EO,
    RUNS,
    invariant="Метрики: fragments — число обработанных, в том числе отказавших и при limit",
)
@pytest.mark.parametrize("limit", [None, 1, 2])
def test_fragments_metric_counts_processed(stand, limit):
    vid, _ = stand.version([*TEXTS, "Четвёртый короткий абзац.", "Пятый короткий абзац."])
    stand.filling.extract_version(vid, limit=limit)
    expected = 4 if limit is None else limit  # [1,2],[2,3],[3,4],[4,5]
    assert one_run(stand)["fragments"] == expected


@req(
    EO, RUNS, invariant="Утверждения запуска, отброшенные и записанные, учтены в created и dropped"
)
def test_created_plus_dropped_equals_items(stand, events):
    vid, _ = stand.version(TEXTS)
    stand.model.replies.extend(
        [
            {
                "statements": [
                    stmt("Кант", "holds", "Опыт", 1, Q[0]),
                    stmt("Кант", "holds", "Опыт 2", 1, "нет такой"),
                ]
            },
            {"statements": [stmt("Юм", "holds", "Привычка", 1, Q[1])]},
        ]
    )
    stand.filling.extract_version(vid)
    row = check_run_accounting(stand, events)
    assert (row["created"], row["dropped"]) == (2, 1)
    assert sum(e["created"] + e["dropped"] for e in events.of(FRAGMENT)) == 3


# --- миграция knowledge:10 -----------------------------------------------------------------

NEW_COLUMNS = {
    "extractor",
    "source_id",
    "fragments",
    "duration_seconds",
    "input_tokens",
    "output_tokens",
    "drop_reasons",
    "failure",
}


@req(
    EO,
    RUNS,
    invariant="Миграция knowledge:10: столбцы метрик, прежние строки целы, новые поля пусты",
)
def test_migration_10_keeps_old_rows(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'k.db').as_posix()}", [ks.SCHEMA])
    with engine.begin() as conn:
        ks.migrations._version_table.create(conn, checkfirst=True)
        for version in range(1, 10):
            conn.execute(
                ks.migrations._version_table.insert().values(version=version, name=f"v{version}")
            )
        conn.execute(
            text(
                "CREATE TABLE knowledge.filling_runs (run_id VARCHAR(64) PRIMARY KEY, "
                "kind VARCHAR(30) NOT NULL, target VARCHAR(100), model VARCHAR(100), "
                "template_version VARCHAR(40), started_at DATETIME NOT NULL, "
                "finished_at DATETIME, created INTEGER NOT NULL, dropped INTEGER NOT NULL, "
                "cost_usd JSON, status VARCHAR(20) NOT NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO knowledge.filling_runs VALUES ('r_old', 'extraction', 'v1', 'main', "
                "'t1', '2026-11-01 10:00:00', '2026-11-01 10:05:00', 5, 2, '0.25', 'done')"
            )
        )
        before = {c["name"] for c in inspect(conn).get_columns("filling_runs", schema=ks.SCHEMA)}
    assert not NEW_COLUMNS & before
    assert ks.migrations.upgrade(engine) == [10]
    assert ks.migrations.latest() == 10
    with engine.begin() as conn:
        after = {c["name"] for c in inspect(conn).get_columns("filling_runs", schema=ks.SCHEMA)}
        row = (
            conn.execute(select(ks.filling_runs).where(ks.filling_runs.c.run_id == "r_old"))
            .mappings()
            .one()
        )
    assert after >= NEW_COLUMNS
    assert (row["kind"], row["target"], row["model"], row["created"], row["dropped"]) == (
        "extraction",
        "v1",
        "main",
        5,
        2,
    )
    assert row["status"] == "done" and row["cost_usd"] == 0.25
    for column in NEW_COLUMNS:
        assert row[column] is None, column


# --- таймаут вызова ------------------------------------------------------------------------


def call_timeout(double: GatewayDouble) -> float:
    [call] = double.structured_calls()
    return call.extensions["timeout"]["read"]


@req(EO, TIMEOUT, scenario="Таймаут по бюджету роли")
def test_timeout_by_role_budget(stand, events):
    vid, _ = stand.version(TEXTS[:1])
    double = with_double(
        stand,
        GatewayDouble(
            role={"role": "strong", "model": "pro", "call_budget_seconds": 1084.5},
            structured=[one_statement_reply(0)],
        ),
    )
    stand.filling.extract_version(vid)
    assert call_timeout(double) == 1114.5
    roles = [r for r in double.requests if r.url.path.endswith("/roles/strong")]
    assert len(roles) == 1 and roles[0].method == "GET"


@pytest.mark.parametrize("budget", [0.5, 10, 120.0, 3600, 7200.25])
@req(EO, TIMEOUT, invariant="Таймаут клиента — бюджет шлюза + 30 с и не меньше бюджета")
def test_timeout_is_budget_plus_30(stand, budget):
    vid, _ = stand.version(TEXTS[:1])
    double = with_double(
        stand,
        GatewayDouble(
            role={"role": "strong", "model": "pro", "call_budget_seconds": budget},
            structured=[one_statement_reply(0)],
        ),
    )
    stand.filling.extract_version(vid)
    assert call_timeout(double) == budget + 30 >= budget


@pytest.mark.parametrize(
    "role",
    [None, httpx.ConnectError("нет связи"), httpx.Response(500, json={}), {"role": "strong"}],
    ids=["404", "unavailable", "500", "no-budget"],
)
@req(
    EO,
    TIMEOUT,
    invariant="Без сведений шлюза — PHILOGRAPH_EXTRACTION_TIMEOUT_SECONDS (по умолчанию 1200 с)",
)
def test_timeout_fallback_default(stand, role):
    vid, _ = stand.version(TEXTS[:1])
    double = with_double(stand, GatewayDouble(role=role, structured=[one_statement_reply(0)]))
    stand.filling.extract_version(vid)
    assert call_timeout(double) == 1200.0


@req(
    EO,
    TIMEOUT,
    invariant="Без сведений шлюза — PHILOGRAPH_EXTRACTION_TIMEOUT_SECONDS из настройки сервиса",
)
def test_timeout_fallback_from_service_setting(tmp_path, monkeypatch):
    from philograph.knowledge import main as kmain

    seen = {}
    real = kmain.Filling

    class Recording(real):
        def __init__(self, *args, **kwargs):
            seen.update(kwargs)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(kmain, "Filling", Recording)
    base = {
        "PHILOGRAPH_DATABASE_URL": f"sqlite:///{(tmp_path / 'k.db').as_posix()}",
        "PHILOGRAPH_LIBRARY_URL": "http://library",
        "PHILOGRAPH_LLM_URL": "http://llm",
        "PHILOGRAPH_FILES_ROOT": str(tmp_path / "files"),
    }
    kmain.components(base)
    assert seen["call_timeout"] == 1200.0  # по умолчанию
    kmain.components({**base, "PHILOGRAPH_EXTRACTION_TIMEOUT_SECONDS": "777"})
    assert seen["call_timeout"] == 777.0
