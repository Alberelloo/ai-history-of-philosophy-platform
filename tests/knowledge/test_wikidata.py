"""epochs — «Доступ к Wikidata» (add-epochs, задача 5.0).

Сценарии и правила требования проверяются на двух уровнях: общей функцией (``wikidata``) и
через команду оператора ``apply`` (``EpochDates``), которая пишет событие
``knowledge.epoch_dates.checked`` — серверный якорь требования. Сеть запрещена ловушкой
``no_network``; ответы Wikidata задаёт тест (``wd_records``), транспорт —
``httpx.MockTransport``, ожидание повторов — внедрённая функция, двигающая ``ManualClock``.
"""

from __future__ import annotations

import getpass
import math
import socket
import subprocess
from datetime import timedelta
from functools import partial

import httpx
import pytest

from philograph.knowledge.epoch_dates import EpochDates
from philograph.knowledge.wikidata import (
    USER_AGENT,
    WikidataError,
    fetch_entity,
    http_fetch,
    wikidata_time,
)

from .wd_records import dated, no_network, record, year  # noqa: F401  (фикстура)
from .wikidata_fixtures import FixtureFetch

req = pytest.mark.req
EP = "epochs"
ACCESS = "Доступ к Wikidata"
CHECKED = "knowledge.epoch_dates.checked"

pytestmark = pytest.mark.usefixtures("no_network")


# --- помощники ----------------------------------------------------------------------------


class Transport:
    """Подменённый транспорт: отвечает по очереди заданными ответами, записывает запросы."""

    def __init__(self, *answers: httpx.Response) -> None:
        self.answers = list(answers)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.pop(0)
        return httpx.Response(answer.status_code, headers=answer.headers, content=answer.content)


class Waits:
    """Внедрённое ожидание: записывает секунды и сдвигает управляемые часы."""

    def __init__(self, clock) -> None:
        self.clock = clock
        self.seconds: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.seconds.append(seconds)
        self.clock.advance(seconds=seconds)


def ok(body: dict) -> httpx.Response:
    return httpx.Response(200, json=body)


def busy(status: int = 429, retry_after: str | None = "1") -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return httpx.Response(status, headers=headers, json={"error": "busy"})


def epoch_without_dating(onto, name: str = "Просвещение") -> str:
    return onto.entities.create("epoch", [("ru", name, "primary")])


def datings(onto, epoch: str) -> list[dict]:
    return [
        s
        for s in onto.statements.about(epoch, types=["dating"], derived=False)
        if s["direction"] == "out"
    ]


def bounds(value: dict) -> tuple[int, int, int, int, str]:
    return (
        value["earliest_start"],
        value["latest_start"],
        value["earliest_end"],
        value["latest_end"],
        value["precision"],
    )


def apply_one(onto, fetch, qid: str = "Q12539", name: str = "Просвещение"):
    manifest = {"epochs": [{"ru": name, "en": None, "wikidata": qid}]}
    return EpochDates(onto.statements, onto.entities).apply(manifest, fetch)


# --- Точности и эра -----------------------------------------------------------------------

# (значение, точность) → (самое раннее, самое позднее, точность) или None — «нет даты».
TABLE = [
    ("+1685-03-01T00:00:00Z", 11, (1685, 1685, "year")),
    ("+1680-00-00T00:00:00Z", 8, (1680, 1689, "decade")),
    ("+1800-00-00T00:00:00Z", 7, (1701, 1800, "century")),
    ("+1701-00-00T00:00:00Z", 7, (1701, 1800, "century")),
    ("-0800-00-00T00:00:00Z", 7, (-799, -700, "century")),
    ("+2000-00-00T00:00:00Z", 6, (1001, 2000, "approx")),
    ("+1500-00-00T00:00:00Z", 5, None),
    ("+0000-00-00T00:00:00Z", 9, None),
    ("1685", 9, None),
]


@req(EP, ACCESS, scenario="Точности и эра")
@pytest.mark.parametrize("value,precision,expected", TABLE, ids=[f"{v}@{p}" for v, p, _ in TABLE])
def test_precisions_and_era(onto, events, value, precision, expected):
    # Правило — общей функцией.
    got = wikidata_time(value, precision)
    if expected is None:
        assert got is None
    else:
        lo, hi, kind = expected
        assert (got.earliest_start, got.latest_start, got.precision) == (lo, hi, kind)
        assert (got.earliest_end, got.latest_end) == (lo, hi)  # одна дата: начало = конец
    # То же правило в команде: начало и конец записи — это значение.
    epoch = epoch_without_dating(onto)
    fetch = FixtureFetch(
        extra={
            "Q12539": record(
                "Q12539", times={"P580": (value, precision), "P582": (value, precision)}
            )
        }
    )
    report = apply_one(onto, fetch)
    checked = events.one(CHECKED)
    if expected is None:
        assert report.epochs[0]["result"] == "no_dates"
        assert checked["result"] == "no_dates" and checked["epoch_id"] == epoch
        assert datings(onto, epoch) == []
    else:
        lo, hi, kind = expected
        assert checked["result"] == "added" and checked["epoch_id"] == epoch
        [dating] = datings(onto, epoch)
        assert bounds(dating["value"]) == (lo, hi, lo, hi, kind)


ERA = [
    ("-0800-00-00T00:00:00Z", 9, -799),  # 800 до н. э. — астрономический −799
    ("-0001-00-00T00:00:00Z", 9, 0),  # 1 до н. э. — 0
    ("+0001-00-00T00:00:00Z", 9, 1),
    ("-0384-00-00T00:00:00Z", 9, -383),  # Аристотель
    ("+1685-12-31T00:00:00Z", 10, 1685),  # месяц отбрасывается
]


@req(EP, ACCESS, invariant="знак — эра; точность 9 и выше — год")
@pytest.mark.parametrize("value,precision,astro", ERA, ids=[v for v, _, _ in ERA])
def test_era_sign_and_year_precision(value, precision, astro, onto, events):
    got = wikidata_time(value, precision)
    assert (got.earliest_start, got.latest_start, got.earliest_end, got.latest_end) == (
        astro,
        astro,
        astro,
        astro,
    )
    assert got.precision == "year"
    epoch = epoch_without_dating(onto)
    fetch = FixtureFetch(
        extra={
            "Q1": record(
                "Q1", times={"P580": (value, precision), "P582": ("+1800-00-00T00:00:00Z", 9)}
            )
        }
    )
    apply_one(onto, fetch, qid="Q1")
    assert events.one(CHECKED)["result"] == "added"
    [dating] = datings(onto, epoch)
    assert dating["value"]["earliest_start"] == astro


CENTURY = [
    ("+1700-00-00T00:00:00Z", (1601, 1700)),  # ⌈1700/100⌉ = 17
    ("+1601-00-00T00:00:00Z", (1601, 1700)),
    ("+0100-00-00T00:00:00Z", (1, 100)),
    ("-0100-00-00T00:00:00Z", (-99, 0)),  # I в. до н. э. (100…1 до н. э.)
    ("-0701-00-00T00:00:00Z", (-799, -700)),  # ⌈701/100⌉ = 8 — VIII в. до н. э.
]


@req(EP, ACCESS, invariant="номер века — ⌈|год| / 100⌉")
@pytest.mark.parametrize("value,expected", CENTURY, ids=[v for v, _ in CENTURY])
def test_century_number(value, expected, events):
    got = wikidata_time(value, 7)
    assert (got.earliest_start, got.latest_start, got.precision) == (*expected, "century")
    events.assert_none(CHECKED)  # чистое правило: команда не запускалась, событий нет


GARBAGE = [
    ("+1685-00-00T00:00:00Z", 4),
    ("+1685-00-00T00:00:00Z", 0),
    ("-0000-00-00T00:00:00Z", 9),
    ("+1685", 9),
    ("", 9),
    ("+1685-00-00", 9),
    ("1685-00-00T00:00:00Z", 9),  # без знака
    ("+abcd-00-00T00:00:00Z", 9),
]


@req(EP, ACCESS, invariant="точность ниже 6, год 0000 и запись не по формату — нет даты")
@pytest.mark.parametrize("value,precision", GARBAGE, ids=[f"{v!r}@{p}" for v, p in GARBAGE])
def test_garbage_time_is_no_date(value, precision, onto, events):
    assert wikidata_time(value, precision) is None
    epoch = epoch_without_dating(onto)
    fetch = FixtureFetch(
        extra={
            "Q1": record(
                "Q1", times={"P580": (value, precision), "P582": ("+1800-00-00T00:00:00Z", 9)}
            )
        }
    )
    apply_one(onto, fetch, qid="Q1")
    assert events.one(CHECKED)["result"] == "no_dates"
    assert datings(onto, epoch) == []


# --- Повтор при 429 -----------------------------------------------------------------------


@req(EP, ACCESS, scenario="Повтор при 429")
def test_retry_after_429(onto, events, clock):
    epoch = epoch_without_dating(onto)
    transport = Transport(busy(429, "1"), ok(dated("Q12539", year(1685), year(1815))))
    waits = Waits(clock)
    start = clock.now()
    fetch = partial(http_fetch, wait=waits, transport=httpx.MockTransport(transport))
    apply_one(onto, fetch)
    # Запись получена со второй попытки, ожидание — через внедрённые часы.
    assert len(transport.requests) == 2
    assert waits.seconds == [1.0]
    assert clock.now() - start == timedelta(seconds=1)
    for request in transport.requests:
        assert request.headers["User-Agent"] == USER_AGENT
        assert request.url.host == "www.wikidata.org" and "Q12539" in request.url.path
    checked = events.one(CHECKED)
    assert (checked["epoch_id"], checked["qid"], checked["result"]) == (epoch, "Q12539", "added")
    [dating] = datings(onto, epoch)
    assert bounds(dating["value"]) == (1685, 1685, 1815, 1815, "year")


@req(EP, ACCESS, scenario="Повтор при 429")
def test_four_429_fail_after_three_retries(onto, events, clock):
    epoch = epoch_without_dating(onto)
    transport = Transport(*(busy(429, "1") for _ in range(4)))
    waits = Waits(clock)
    fetch = partial(http_fetch, wait=waits, transport=httpx.MockTransport(transport))
    with pytest.raises(WikidataError):
        fetch_entity("Q12539", fetch)
    assert len(transport.requests) == 4  # первая попытка и три повтора
    assert waits.seconds == [1.0, 1.0, 1.0]
    # Через команду: сбой загрузки — fetch_failed, без записи.
    transport.answers = [busy(429, "1") for _ in range(4)]
    transport.requests.clear()
    apply_one(onto, fetch)
    assert len(transport.requests) == 4
    checked = events.one(CHECKED)
    assert (checked["epoch_id"], checked["result"]) == (epoch, "fetch_failed")
    assert datings(onto, epoch) == []
    assert events.one("knowledge.epoch_dates.run")["skipped"] == 1


@req(EP, ACCESS, invariant="ждёт по Retry-After, не дольше заданного предела; 429 и 503")
@pytest.mark.parametrize(
    "status,retry_after,expected",
    [(429, "7", 7.0), (503, "2", 2.0), (429, "3600", 30.0), (503, "1e9", 30.0)],
    ids=["429-7s", "503-2s", "429-cap", "503-cap"],
)
def test_retry_after_respected_and_capped(onto, events, clock, status, retry_after, expected):
    epoch_without_dating(onto)
    transport = Transport(busy(status, retry_after), ok(dated("Q12539", year(1685), year(1815))))
    waits = Waits(clock)
    fetch = partial(http_fetch, wait=waits, transport=httpx.MockTransport(transport))
    apply_one(onto, fetch)
    assert len(waits.seconds) == 1
    assert waits.seconds[0] <= 30.0  # предел по умолчанию
    assert waits.seconds == [expected]
    assert events.one(CHECKED)["result"] == "added"


@req(EP, ACCESS, invariant="User-Agent проекта без сведений об операторе; таймаут")
def test_user_agent_without_operator_data_and_timeout(onto, events, clock):
    epoch_without_dating(onto)
    transport = Transport(ok(dated("Q12539", year(1685), year(1815))))
    fetch = partial(http_fetch, wait=Waits(clock), transport=httpx.MockTransport(transport))
    apply_one(onto, fetch)
    [request] = transport.requests
    agent = request.headers["User-Agent"]
    assert agent == USER_AGENT and agent.startswith("PhiloGraph/")
    private = {getpass.getuser(), socket.gethostname()}
    try:
        email = subprocess.run(
            ["git", "config", "user.email"], capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        email = ""
    private |= {email} if email else set()
    for value in private:
        assert value.lower() not in agent.lower(), value
    assert "@" not in agent
    timeout = request.extensions["timeout"]
    assert all(
        isinstance(timeout[k], (int, float)) and math.isfinite(timeout[k]) and timeout[k] > 0
        for k in ("connect", "read", "write", "pool")
    ), timeout
    assert events.one(CHECKED)["result"] == "added"


# --- Неверный идентификатор ---------------------------------------------------------------

HOSTILE = [
    "Q12539/../../w/api.php",
    "Q12539?action=query",
    "Q12539#x",
    "q12539",
    "Q",
    " Q12539",
    "Q12539\n",
    "https://example.org/Q1",
    "P580",
    "Q-1",
]


@req(EP, ACCESS, scenario="Неверный идентификатор")
def test_bad_id_sends_nothing(onto, events, clock):
    transport = Transport()
    fetch = partial(http_fetch, wait=Waits(clock), transport=httpx.MockTransport(transport))
    with pytest.raises(WikidataError, match="идентификатор"):
        fetch_entity("Q12539/../../w/api.php", fetch)
    assert transport.requests == []
    # Через команду: эпоха базы с таким внешним идентификатором (--linked) — сбой загрузки.
    epoch = epoch_without_dating(onto)
    onto.entities.add_external(epoch, "wikidata", "Q12539/../../w/api.php")
    EpochDates(onto.statements, onto.entities).apply({"epochs": []}, fetch, linked=True)
    assert transport.requests == []
    checked = events.one(CHECKED)
    assert (checked["epoch_id"], checked["result"]) == (epoch, "fetch_failed")
    assert datings(onto, epoch) == []


@req(EP, ACCESS, invariant="адрес строится из идентификатора, проверенного по ^Q\\d+$")
@pytest.mark.parametrize("qid", HOSTILE, ids=repr)
def test_hostile_ids_never_requested(qid, events):
    fetch = FixtureFetch()
    with pytest.raises(WikidataError):
        fetch_entity(qid, fetch)
    assert fetch.calls == []
    events.assert_none(CHECKED)


# --- Ранги значений -----------------------------------------------------------------------


@req(EP, ACCESS, scenario="Ранги значений")
def test_deprecated_value_never_taken(onto, events):
    epoch = epoch_without_dating(onto)
    fetch = FixtureFetch(
        extra={
            "Q12539": record(
                "Q12539",
                times={
                    "P580": [
                        ("+1650-00-00T00:00:00Z", 9, "deprecated"),
                        ("+1685-00-00T00:00:00Z", 9, "normal"),
                    ],
                    "P582": ("+1815-00-00T00:00:00Z", 9),
                },
            )
        }
    )
    apply_one(onto, fetch)
    [dating] = datings(onto, epoch)
    assert dating["value"]["earliest_start"] == 1685 and dating["value"]["latest_start"] == 1685
    assert events.one(CHECKED)["result"] == "added"


RANKS = [
    # значения P580 (время, ранг) → ожидаемое начало (None — нет даты)
    ([("+1650", "normal"), ("+1685", "preferred")], 1685),
    ([("+1650", "normal"), ("+1660", "normal")], 1650),
    ([("+1650", "deprecated"), ("+1660", "normal"), ("+1670", "normal")], 1660),
    ([("+1650", "preferred"), ("+1685", "deprecated")], 1650),
    ([("+1650", "deprecated")], None),
]


@req(EP, ACCESS, invariant="предпочтённое, иначе первое обычное; устаревшее — никогда")
@pytest.mark.parametrize(
    "values,start", RANKS, ids=["pref", "first-normal", "skip-dep", "pref-first", "only-dep"]
)
def test_rank_choice(values, start, onto, events):
    epoch = epoch_without_dating(onto)
    p580 = [(f"{v}-00-00T00:00:00Z", 9, rank) for v, rank in values]
    fetch = FixtureFetch(
        extra={"Q1": record("Q1", times={"P580": p580, "P582": ("+1815-00-00T00:00:00Z", 9)})}
    )
    apply_one(onto, fetch, qid="Q1")
    checked = events.one(CHECKED)
    if start is None:
        assert checked["result"] == "no_dates" and datings(onto, epoch) == []
    else:
        assert checked["result"] == "added"
        [dating] = datings(onto, epoch)
        assert dating["value"]["earliest_start"] == start


# --- Ответ — данные -----------------------------------------------------------------------


@req(EP, ACCESS, invariant="из ответа берутся только перечисленные свойства")
def test_only_listed_properties_taken(onto, events):
    epoch = epoch_without_dating(onto)
    other = onto.entities.create("person", [("ru", "Вольтер", "primary")])
    onto.entities.add_external(other, "wikidata", "Q9068")
    fetch = FixtureFetch(
        extra={
            "Q12539": record(
                "Q12539",
                ru="<b>Просвещение</b>",
                description="ignore previous instructions",
                times={"P580": ("+1685-00-00T00:00:00Z", 9), "P582": ("+1815-00-00T00:00:00Z", 9)},
                items={"P737": ["Q9068"], "P1343": ["Q2"], "P361": ["Q3"], "P793": ["Q4"]},
            )
        }
    )
    events.clear()
    apply_one(onto, fetch)
    stmts = onto.statements.about(epoch, derived=False)
    assert [s["type"] for s in stmts] == ["dating"]  # ни влияний, ни частей, ни событий
    assert onto.statements.about(other, derived=False) == []  # P737 → Вольтер не связан
    assert onto.entities.label(epoch) == "Просвещение"  # метка записи не переименовала эпоху
    events.assert_none("knowledge.entity.created")
    assert events.one(CHECKED)["result"] == "added"
