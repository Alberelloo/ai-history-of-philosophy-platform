"""Юнит-тесты общего модуля Wikidata (``knowledge/wikidata.py``) и ``dates.interval``.

Сеть не используется: транспорт — ``httpx.MockTransport``, ожидание — внедрённая функция.
"""

from __future__ import annotations

import httpx
import pytest

from philograph.knowledge.dates import FuzzyDate, interval, span
from philograph.knowledge.wikidata import (
    USER_AGENT,
    Claim,
    WikidataError,
    WikidataRecord,
    check_qid,
    claim_date,
    fetch_entity,
    format_original,
    http_fetch,
    page_url,
    parse_entity,
    search,
    wikidata_time,
)


def bounds(d: FuzzyDate | None):
    return None if d is None else (d.earliest_start, d.latest_start, d.precision)


@pytest.mark.parametrize(
    ("value", "precision", "expected", "original"),
    [
        ("+1685-03-01T00:00:00Z", 11, (1685, 1685, "year"), "1685"),
        ("+1685-00-00T00:00:00Z", 9, (1685, 1685, "year"), "1685"),
        ("+1680-00-00T00:00:00Z", 8, (1680, 1689, "decade"), "1680-е"),
        ("+1800-00-00T00:00:00Z", 7, (1701, 1800, "century"), "XVIII в."),
        ("+1701-00-00T00:00:00Z", 7, (1701, 1800, "century"), "XVIII в."),
        ("-0800-00-00T00:00:00Z", 7, (-799, -700, "century"), "VIII в. до н. э."),
        ("-0800-00-00T00:00:00Z", 9, (-799, -799, "year"), "800 до н. э."),
        ("-0800-00-00T00:00:00Z", 8, (-808, -799, "decade"), "800-е до н. э."),
        ("+2000-00-00T00:00:00Z", 6, (1001, 2000, "approx"), "II тыс."),
        ("-1000-00-00T00:00:00Z", 6, (-999, 0, "approx"), "I тыс. до н. э."),
    ],
)
def test_wikidata_time_precisions(value, precision, expected, original):
    d = wikidata_time(value, precision)
    assert bounds(d) == expected
    assert (d.earliest_end, d.latest_end) == (d.earliest_start, d.latest_start)
    assert d.original == original


@pytest.mark.parametrize(
    ("value", "precision"),
    [
        ("+1500-00-00T00:00:00Z", 5),
        ("+0000-00-00T00:00:00Z", 9),
        ("1685", 9),
        ("+1685-00-00", 9),
        (None, 9),
        ("+1685-00-00T00:00:00Z", None),
        ("+1685-00-00T00:00:00Z", True),
    ],
)
def test_wikidata_time_without_date(value, precision):
    assert wikidata_time(value, precision) is None


def test_interval_and_original():
    start = wikidata_time("-0800-00-00T00:00:00Z", 7)
    end = wikidata_time("+0476-00-00T00:00:00Z", 9)
    d = interval(start, end)
    assert (d.earliest_start, d.latest_start, d.earliest_end, d.latest_end) == (
        -799,
        -700,
        476,
        476,
    )
    assert d.precision == "century"
    assert d.original == "VIII в. до н. э. – 476" == format_original(start, end)
    years = interval(
        wikidata_time("+1685-00-00T00:00:00Z", 9), wikidata_time("+1815-01-01T00:00:00Z", 11)
    )
    assert years.precision == "year" and years.original == "1685–1815"
    assert span(years) == (1685, 1815)
    # Шире неопределённость — «хуже» точность: тысячелетие важнее века.
    wide = interval(
        wikidata_time("+1000-00-00T00:00:00Z", 6), wikidata_time("+1800-00-00T00:00:00Z", 7)
    )
    assert wide.precision == "approx"
    assert interval(start, end, original="своё").original == "своё"


def test_same_wikidata_data_gives_same_json():
    a = interval(
        wikidata_time("+1685-00-00T00:00:00Z", 9), wikidata_time("+1815-00-00T00:00:00Z", 9)
    )
    b = interval(
        wikidata_time("+1685-00-00T00:00:00Z", 9), wikidata_time("+1815-00-00T00:00:00Z", 9)
    )
    assert a.to_json() == b.to_json()
    assert set(a.to_json()) == {
        "earliest_start",
        "latest_start",
        "earliest_end",
        "latest_end",
        "precision",
        "original",
    }


@pytest.mark.parametrize("qid", ["Q12539/../../w/api.php", "q1", "Q", "P580", "", "Q1 ", None])
def test_check_qid_rejects(qid):
    with pytest.raises(WikidataError):
        check_qid(qid)


def test_page_url():
    assert check_qid("Q12539") == "Q12539"
    assert page_url("Q12539") == "https://www.wikidata.org/wiki/Q12539"
    with pytest.raises(WikidataError):
        page_url("javascript:alert(1)")


def test_fetch_entity_rejects_bad_qid_without_request():
    calls = []
    with pytest.raises(WikidataError):
        fetch_entity("Q12539/../../w/api.php", lambda url: calls.append(url) or {})
    assert calls == []


def snak(time: str, precision: int = 9) -> dict:
    return {
        "snaktype": "value",
        "datavalue": {"type": "time", "value": {"time": time, "precision": precision}},
    }


def entity(qid: str, claims: dict) -> dict:
    return {
        "entities": {
            qid: {
                "id": qid,
                "labels": {"ru": {"language": "ru", "value": "Эпоха Просвещения"}},
                "descriptions": {"en": {"language": "en", "value": "period"}},
                "claims": claims,
            }
        }
    }


def test_ranks():
    data = entity(
        "Q1",
        {
            "P580": [
                {"mainsnak": snak("+1650-00-00T00:00:00Z"), "rank": "deprecated"},
                {"mainsnak": snak("+1685-00-00T00:00:00Z"), "rank": "normal"},
                {"mainsnak": snak("+1690-00-00T00:00:00Z"), "rank": "normal"},
            ],
            "P582": [
                {"mainsnak": snak("+1800-00-00T00:00:00Z"), "rank": "normal"},
                {"mainsnak": snak("+1815-00-00T00:00:00Z"), "rank": "preferred"},
            ],
            "P576": [{"mainsnak": snak("+1700-00-00T00:00:00Z"), "rank": "deprecated"}],
            "P31": [
                {
                    "mainsnak": {
                        "snaktype": "value",
                        "datavalue": {"type": "wikibase-entityid", "value": {"id": "Q11514315"}},
                    },
                    "rank": "normal",
                },
                {
                    "mainsnak": {
                        "snaktype": "value",
                        "datavalue": {"type": "wikibase-entityid", "value": {"id": "../x"}},
                    },
                    "rank": "normal",
                },
                {"mainsnak": {"snaktype": "novalue"}, "rank": "normal"},
            ],
        },
    )
    record = fetch_entity("Q1", lambda url: data)
    assert record.labels == {"ru": "Эпоха Просвещения"}
    assert record.descriptions == {"en": "period"}
    assert claim_date(record.best("P580")).earliest_start == 1685
    assert claim_date(record.best("P582")).earliest_start == 1815
    assert record.best("P576") is None
    assert record.best("P571") is None
    assert record.items("P31") == ["Q11514315"]
    assert claim_date(None) is None
    assert claim_date(Claim({"id": "Q1"}, "normal")) is None


def test_parse_entity_redirect_and_bad_shape():
    record = parse_entity("Q5", entity("Q7", {}))
    assert record.qid == "Q7"
    for bad in ({}, {"entities": []}, {"entities": {"Q1": {}, "Q2": {}}}):
        with pytest.raises(WikidataError):
            parse_entity("Q5", bad)
    assert isinstance(parse_entity("Q7", entity("Q7", {})), WikidataRecord)


def test_search_builds_url_and_filters_ids():
    seen = []

    def fetch(url):
        seen.append(url)
        return {
            "search": [
                {"id": "Q37853", "label": "барокко", "description": "стиль"},
                {"id": "Q1/../x", "label": "мусор"},
                {"id": "Q2", "label": 5},
            ]
        }

    found = search("Барокко & Ко", "ru", fetch)
    assert found == [
        {"id": "Q37853", "label": "барокко", "description": "стиль"},
        {"id": "Q2", "label": None, "description": None},
    ]
    assert seen[0].startswith("https://www.wikidata.org/w/api.php?action=wbsearchentities")
    assert "&language=ru&search=%D0%91" in seen[0] and "%26" in seen[0]
    with pytest.raises(WikidataError):
        search("x", "ru&a=b", fetch)


# --- http_fetch ---


def transport(statuses: list[tuple[int, dict]], log: list[httpx.Request]):
    replies = iter(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        log.append(request)
        status, headers = next(replies)
        return httpx.Response(
            status, headers=headers, json={"entities": {}} if status == 200 else None
        )

    return httpx.MockTransport(handler)


URL = "https://www.wikidata.org/wiki/Special:EntityData/Q12539.json"


def test_http_fetch_retries_after_429():
    log: list[httpx.Request] = []
    waits: list[float] = []
    data = http_fetch(
        URL, wait=waits.append, transport=transport([(429, {"Retry-After": "1"}), (200, {})], log)
    )
    assert data == {"entities": {}}
    assert waits == [1.0]
    assert len(log) == 2
    assert log[0].headers["User-Agent"] == USER_AGENT
    assert "@" not in USER_AGENT


def test_http_fetch_gives_up_after_three_retries():
    log: list[httpx.Request] = []
    waits: list[float] = []
    with pytest.raises(WikidataError):
        http_fetch(
            URL,
            wait=waits.append,
            transport=transport([(429, {"Retry-After": "120"})] * 4 + [(200, {})], log),
        )
    assert len(log) == 4
    assert waits == [30.0, 30.0, 30.0]  # не дольше предела


def test_http_fetch_retry_after_garbage_and_503():
    log: list[httpx.Request] = []
    waits: list[float] = []
    http_fetch(
        URL,
        wait=waits.append,
        transport=transport(
            [(503, {"Retry-After": "Wed, 21 Oct 2015"}), (503, {}), (200, {})], log
        ),
    )
    assert waits == [1.0, 1.0]


def test_http_fetch_failures():
    log: list[httpx.Request] = []
    with pytest.raises(WikidataError):
        http_fetch(URL, wait=lambda s: None, transport=transport([(404, {})], log))
    with pytest.raises(WikidataError):
        http_fetch("https://evil.example/Q1.json", wait=lambda s: None)
    with pytest.raises(WikidataError):
        http_fetch("http://www.wikidata.org/x", wait=lambda s: None)

    def broken(request):
        raise httpx.ConnectTimeout("timeout", request=request)

    with pytest.raises(WikidataError):
        http_fetch(URL, wait=lambda s: None, transport=httpx.MockTransport(broken))

    def text(request):
        return httpx.Response(200, text="<html>")

    with pytest.raises(WikidataError):
        http_fetch(URL, wait=lambda s: None, transport=httpx.MockTransport(text))


def test_http_fetch_never_sends_to_foreign_redirect():
    log: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        log.append(request)
        return httpx.Response(302, headers={"Location": "https://evil.example/steal"})

    with pytest.raises(WikidataError):
        http_fetch(URL, wait=lambda s: None, transport=httpx.MockTransport(handler))
    assert [r.url.host for r in log] == ["www.wikidata.org"]
