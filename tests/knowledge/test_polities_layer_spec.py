"""Сценарные и нормативные тесты тестировщика: «Слой политических образований на год» и
«Русские названия образований» (серверная часть). Дельта:
``openspec/changes/add-historical-polities/specs/geo-timeline/spec.md``.

Ожидания считаются в тесте по входной фикстуре (наивный фильтр строк GeoJSON, правило
названий по словарю Wikidata), а не берутся у кода. Запросы идут через HTTP-маршрут сервиса
знаний; событие ответа находится по ``request_id``.
"""

# ruff: noqa: E501 — имена инвариантов спецификации

from __future__ import annotations

import hashlib
import json
import sqlite3
import unicodedata
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from philograph.knowledge.app import build_app
from philograph.knowledge.cards import Cards
from philograph.knowledge.geo import PlaceLayer
from philograph.knowledge.map import SectionMap
from philograph.knowledge.polities import PolityLayer
from philograph.knowledge.snapshot import Snapshots
from philograph.platform.client import ServiceClient

from .cliopatria_fixture import FIXTURES, FakeWikidata, entities
from .test_polities_build_spec import feature, poly, run_build, square, write_geojson

req = pytest.mark.req
GEO = "geo-timeline"
LAYER = "Слой политических образований на год"
NAMES = "Русские названия образований"
SERVED_FIELDS = {"year", "polities", "untranslated", "bytes", "valid_from", "valid_to", "cached"}
CONTEXT = {"request_id", "run_id", "service"}
LIMIT = 9999

# Фикстура сценария «Год 1650» — ровно пять образований из GIVEN.
FIVE = [
    ("Holy Roman Empire", 962, 1806, "Q12548", 800000),
    ("Polish-Lithuanian Commonwealth", 1569, 1795, "Q172107", 900000),
    ("Ottoman Empire", 1299, 1922, "Q12560", 1500000),
    ("Kingdom of Prussia", 1701, 1918, "Q27306", 300000),
    ("Russian Empire", 1721, 1917, "Q34266", 5000000),
]


def sid(name: str) -> str:
    return hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]


def five_features() -> list[dict]:
    return [
        feature(n, a, b, poly(square(5 * i, 45, 4)), qid=q, area=s)
        for i, (n, a, b, q, s) in enumerate(FIVE)
    ]


class Service:
    """Сервис знаний со слоем мест и слоем образований; модель и библиотека — записывающие
    поддельные транспорты."""

    def __init__(self, onto, db: Path | None, **layer: Any) -> None:
        self.llm_calls: list[str] = []
        self.library_calls: list[str] = []

        def llm(request: httpx.Request) -> httpx.Response:
            self.llm_calls.append(str(request.url))
            return httpx.Response(503, json={"error": "нет модели"})

        def library(request: httpx.Request) -> httpx.Response:
            self.library_calls.append(request.url.path)
            if request.url.path.endswith("/internal/access"):
                return httpx.Response(200, json={"closed": [], "hidden": []})
            return httpx.Response(404, json={"detail": "Not Found"})

        snapshots = Snapshots(onto.statements.engine)
        section_map = SectionMap(onto.statements, snapshots=snapshots)
        self.layer = PolityLayer(db, **layer)
        app = build_app(
            onto.statements,
            section_map=section_map,
            place_layer=PlaceLayer(section_map, snapshots),
            cards=Cards(
                onto.statements,
                None,
                ServiceClient("llm", "http://llm", transport=httpx.MockTransport(llm)),
            ),
            library=ServiceClient(
                "library", "http://library/api", transport=httpx.MockTransport(library)
            ),
            polity_layer=self.layer,
        )
        self.client = TestClient(app, raise_server_exceptions=False)

    def get(self, path: str, params: dict | None = None) -> tuple[httpx.Response, str]:
        rid = f"rid-{uuid.uuid4().hex[:10]}"
        r = self.client.get(path, params=params, headers={"X-Request-Id": rid})
        return r, rid

    def year(self, year: Any) -> tuple[httpx.Response, str]:
        return self.get("/v1/map/polities", {"year": str(year)})


def served(events, rid: str):
    found = events.where("knowledge.polities.served", request_id=rid)
    assert len(found) == 1, (rid, events.names())
    return found[0]


@pytest.fixture
def five(tmp_path):
    src = write_geojson(tmp_path / "five.geojson", five_features())
    code, out, _, _ = run_build(tmp_path / "b", src)
    assert code == 0
    return out


@pytest.fixture
def europe(tmp_path):
    code, out, _labels, _wd = run_build(tmp_path / "eu", "europe.geojson")
    assert code == 0
    return out


# --- независимая модель фикстуры ---------------------------------------------------------


def valid_rows(features: list[dict]) -> list[dict]:
    out = []
    for f in features:
        p = f["properties"]
        if (
            p.get("Type") == "POLITY"
            and p.get("Name")
            and isinstance(p.get("FromYear"), int)
            and isinstance(p.get("ToYear"), int)
            and p["FromYear"] <= p["ToYear"]
            and (f.get("geometry") or {}).get("type") in ("Polygon", "MultiPolygon")
        ):
            out.append(p)
    return out


def europe_rows() -> list[dict]:
    return valid_rows(json.loads((FIXTURES / "europe.geojson").read_text("utf-8"))["features"])


def naive(rows: list[dict], year: int) -> frozenset[str]:
    return frozenset(sid(p["Name"]) for p in rows if p["FromYear"] <= year <= p["ToYear"])


def naive_rows(rows: list[dict], year: int) -> frozenset[int]:
    return frozenset(i for i, p in enumerate(rows) if p["FromYear"] <= year <= p["ToYear"])


def accepted(text: Any, *, title: bool = False) -> str | None:
    """Правило приёма метки/заголовка дельты: 1–200 символов после обрезки, без управляющих;
    у заголовка снимается одно завершающее уточнение в круглых скобках."""
    if not isinstance(text, str):
        return None
    if title:
        s = text.rstrip()
        if s.endswith(")"):
            depth, i = 0, len(s) - 1
            while i >= 0:
                if s[i] == ")":
                    depth += 1
                elif s[i] == "(":
                    depth -= 1
                    if depth == 0:
                        break
                i -= 1
            if i >= 0:
                text = s[:i]
    t = text.strip()
    if not 1 <= len(t) <= 200 or any(unicodedata.category(c) == "Cc" for c in t):
        return None
    return t


def expected_name(original: str, qid: Any, records: dict) -> tuple[str, str, str]:
    import re

    if not isinstance(qid, str) or not re.fullmatch(r"Q\d+", qid) or qid not in records:
        return original, "original", "original"
    rec = records[qid]
    label = accepted(((rec.get("labels") or {}).get("ru") or {}).get("value"))
    if label:
        return label, "ru", "label"
    title = accepted(((rec.get("sitelinks") or {}).get("ruwiki") or {}).get("title"), title=True)
    if title:
        return title, "ru", "sitelink"
    return original, "original", "original"


# --- Слой: сценарии -------------------------------------------------------------------


@req(GEO, LAYER, scenario="Год 1650")
def test_year_1650(onto, five, events):
    svc = Service(onto, five)
    r, rid = svc.year(1650)
    assert r.status_code == 200
    data = r.json()
    assert data["year"] == 1650
    got = {p["original"]: p for p in data["polities"]}
    assert set(got) == {"Holy Roman Empire", "Polish-Lithuanian Commonwealth", "Ottoman Empire"}
    for p in got.values():
        assert p["from"] <= 1650 <= p["to"]
    assert data["valid_from"] <= 1650 <= data["valid_to"]
    assert data["cached"] is False
    assert set(data["source"]) >= {
        "title",
        "publisher",
        "authors",
        "version",
        "license",
        "license_url",
        "url",
    }
    for p in data["polities"]:
        assert set(p) >= {
            "id",
            "name",
            "name_status",
            "name_source",
            "original",
            "wikidata",
            "from",
            "to",
            "geometry",
        }
        assert p["geometry"]["type"] in ("Polygon", "MultiPolygon")
    ev = served(events, rid)
    assert (ev["year"], ev["polities"], ev["cached"]) == (1650, 3, False)


@req(GEO, LAYER, scenario="Год без образований")
@pytest.mark.parametrize("year", [-3500, 2100])
def test_year_without_polities(onto, five, events, year):
    svc = Service(onto, five)
    r, rid = svc.year(year)
    assert r.status_code == 200
    data = r.json()
    assert data["polities"] == []
    assert data["valid_from"] <= year <= data["valid_to"]
    assert served(events, rid)["polities"] == 0


@req(GEO, LAYER, scenario="Кэш по интервалу")
def test_cache_by_interval(onto, five, events):
    svc = Service(onto, five)
    r1, rid1 = svc.year(1650)
    r2, rid2 = svc.year(1650)
    r3, rid3 = svc.year(1651)
    d1, d2, d3 = r1.json(), r2.json(), r3.json()
    assert (d1["valid_from"], d1["valid_to"]) == (d3["valid_from"], d3["valid_to"])  # GIVEN
    assert d2["cached"] is True and d3["cached"] is True
    p1 = json.dumps(d1["polities"], ensure_ascii=False).encode()
    assert json.dumps(d2["polities"], ensure_ascii=False).encode() == p1
    assert json.dumps(d3["polities"], ensure_ascii=False).encode() == p1
    assert d3["year"] == 1651
    assert [served(events, x)["cached"] for x in (rid1, rid2, rid3)] == [False, True, True]
    assert len(events.of("knowledge.polities.served")) == 3


def many_intervals(tmp: Path, n: int = 120) -> Path:
    """n образований подряд по 10 лет: n интервалов постоянного набора (и промежутки)."""
    feats = [feature(f"Era {i:03d}", 10 * i, 10 * i + 9, poly(square(0, 0, 3))) for i in range(n)]
    src = write_geojson(tmp / "many.geojson", feats)
    code, out, _, _ = run_build(tmp / "m", src)
    assert code == 0
    return out


@req(GEO, LAYER, scenario="Ограниченный кэш")
def test_bounded_cache(onto, tmp_path, events):
    db = many_intervals(tmp_path)
    svc = Service(onto, db, cache_size=8)
    years = [10 * i + 5 for i in range(100)]
    for y in years:
        r, _ = svc.year(y)
        assert r.status_code == 200 and r.json()["cached"] is False
        assert svc.layer.cached_intervals() <= 8
    r, rid = svc.year(years[0])
    assert r.json()["cached"] is False
    assert served(events, rid)["cached"] is False


@req(GEO, LAYER, scenario="Предел кэша по байтам")
def test_cache_byte_limit(onto, europe, events):
    probe = Service(onto, europe)
    a = len(probe.year(1650)[0].content)
    b = len(probe.year(1800)[0].content)
    limit = max(a, b) + min(a, b) // 2
    assert max(a, b) < limit < a + b  # GIVEN
    events.clear()
    svc = Service(onto, europe, cache_size=64, cache_bytes=limit)
    rids = []
    for y in (1650, 1800, 1650):
        r, rid = svc.year(y)
        assert r.status_code == 200
        rids.append(rid)
        assert svc.layer.cached_bytes() <= limit
    assert r.json()["cached"] is False
    assert [served(events, x)["cached"] for x in rids] == [False, False, False]


@req(GEO, LAYER, scenario="Слой больше предела кэша")
def test_layer_bigger_than_cache(onto, europe, events):
    probe = Service(onto, europe)
    size = len(probe.year(1650)[0].content)
    events.clear()
    svc = Service(onto, europe, cache_bytes=size // 2)
    r1, rid1 = svc.year(1650)
    r2, rid2 = svc.year(1650)
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["polities"] == r2.json()["polities"]
    assert r1.json()["cached"] is False and r2.json()["cached"] is False
    assert [served(events, x)["cached"] for x in (rid1, rid2)] == [False, False]


@req(GEO, LAYER, scenario="Нет артефакта")
def test_no_artifact(onto, europe, tmp_path, events):
    svc = Service(onto, tmp_path / "nowhere" / "polities.sqlite")
    r, _ = svc.year(1650)
    assert r.status_code == 503
    assert r.json().get("kind") == "polities_unavailable" or "polities_unavailable" in r.text
    bad = tmp_path / "v999.sqlite"
    bad.write_bytes(europe.read_bytes())
    conn = sqlite3.connect(bad)
    conn.execute("UPDATE meta SET value = '999' WHERE key = 'format_version'")
    conn.commit()
    conn.close()
    svc2 = Service(onto, bad)
    r2, _ = svc2.year(1650)
    assert r2.status_code == 503
    assert "polities_unavailable" in r2.text
    reasons = [e["reason"] for e in events.of("knowledge.polities.unavailable")]
    assert reasons == ["missing", "format"]
    places, _ = svc2.get("/v1/map/places")
    assert places.status_code == 200
    places1, _ = svc.get("/v1/map/places")
    assert places1.status_code == 200
    events.assert_none("knowledge.polities.served")


@req(GEO, LAYER, scenario="Испорченный год")
def test_bad_year(onto, five, events):
    svc = Service(onto, five)
    for raw in ("abc", "1.5", "10000", "-10000", ""):
        r, _ = svc.year(raw)
        assert r.status_code == 400, raw
        assert "bad_year" in r.text, raw
    r, _ = svc.get("/v1/map/polities")
    assert r.status_code == 400 and "bad_year" in r.text
    codes = [e["code"] for e in events.of("knowledge.polities.rejected")]
    assert codes == ["bad_year"] * 6
    events.assert_none("knowledge.polities.served")


@req(GEO, LAYER, scenario="Без сети и модели")
def test_no_network_no_model(onto, five, events, _forbid_network):
    svc = Service(onto, five)
    for y in (1650, 1800):
        r, rid = svc.year(y)
        assert r.status_code == 200
        served(events, rid)
    assert _forbid_network == []
    assert svc.llm_calls == []


# --- Слой: инварианты ------------------------------------------------------------------


@req(GEO, LAYER, invariant="H1: в ответе ровно образования со строкой from_year ≤ T ≤ to_year")
def test_activity_every_year(onto, europe, events):
    rows = europe_rows()
    svc = Service(onto, europe)
    for y in range(-3500, 2101):
        r, _rid = svc.year(y)
        assert r.status_code == 200, y
        data = r.json()
        ids = [p["id"] for p in data["polities"]]
        assert len(ids) == len(set(ids)), y
        assert set(ids) == naive(rows, y), y
        for p in data["polities"]:
            assert p["from"] <= y <= p["to"], (y, p["id"])
    assert len(events.of("knowledge.polities.served")) == 5601


@req(
    GEO,
    LAYER,
    invariant="valid_from…valid_to — наибольший интервал вокруг T с тем же набором строк",
)
def test_interval_maximal(onto, europe, events):
    rows = europe_rows()
    sets = {y: naive_rows(rows, y) for y in range(-LIMIT, LIMIT + 1)}
    svc = Service(onto, europe)
    years = [*list(range(-3500, 2101, 7)), -LIMIT, LIMIT, 0, 1648, 1649, 1806, 1807]
    for y in years:
        r, rid = svc.year(y)
        d = r.json()
        vf, vt = d["valid_from"], d["valid_to"]
        assert vf <= y <= vt
        assert all(sets[t] == sets[y] for t in range(vf, vt + 1)), (y, vf, vt)
        assert vf == -LIMIT or sets[vf - 1] != sets[y], (y, vf)
        assert vt == LIMIT or sets[vt + 1] != sets[y], (y, vt)
        ev = served(events, rid)
        assert (ev["valid_from"], ev["valid_to"]) == (vf, vt)


@req(
    GEO,
    LAYER,
    invariant="строки одного id на T сливаются: MultiPolygon, from — max, to — min, поля — строки с наибольшим from_year",
)
def test_merge_rows_same_id(onto, tmp_path, events):
    feats = [
        feature("Dup", 1600, 1700, poly(square(0, 40, 2)), qid="Q12548", area=10),
        feature("Dup", 1650, 1750, poly(square(5, 40, 2)), qid="Q12560", area=20),
        feature("Dup", 1650, 1690, poly(square(10, 40, 2)), qid="Q27306", area=5),
        feature("Other", 1600, 1800, poly(square(20, 40, 2)), qid="Q4948", area=30),
    ]
    src = write_geojson(tmp_path / "dup.geojson", feats)
    code, out, _, _ = run_build(tmp_path / "d", src)
    assert code == 0
    svc = Service(onto, out)
    r, rid = svc.year(1660)
    dup = [p for p in r.json()["polities"] if p["id"] == sid("Dup")]
    assert len(dup) == 1
    p = dup[0]
    assert p["geometry"]["type"] == "MultiPolygon"
    assert len(p["geometry"]["coordinates"]) == 3
    assert (p["from"], p["to"]) == (1650, 1690)
    # наибольший from_year 1650 у строк 2 и 3, при равенстве — меньший номер строки (2)
    assert p["wikidata"] == "Q12560"
    assert p["name"] == "Османская империя"
    # порядок: «Dup» (10+20+5=35) площадью больше «Other» (30)
    assert [x["id"] for x in r.json()["polities"]] == [sid("Dup"), sid("Other")]
    assert served(events, rid)["polities"] == 2
    r2, _ = svc.year(1720)
    [d2] = [x for x in r2.json()["polities"] if x["id"] == sid("Dup")]
    assert (d2["from"], d2["to"], d2["wikidata"]) == (1650, 1750, "Q12560")
    assert d2["geometry"]["type"] == "Polygon"


@req(GEO, LAYER, invariant="порядок — по убыванию площади, при равенстве — по id; детерминирован")
def test_order_area_then_id(onto, tmp_path, events):
    names = ["Zeta", "Alpha", "Mu", "Beta", "Omega", "Kappa"]
    areas = [500, 500, 900, 100, 500, 900]
    feats = [
        feature(n, 1600, 1700, poly(square(4 * i, 30, 3)), qid="", area=a)
        for i, (n, a) in enumerate(zip(names, areas, strict=True))
    ]
    src = write_geojson(tmp_path / "order.geojson", feats)
    code, out, _, _ = run_build(tmp_path / "o", src)
    assert code == 0
    expected = [
        sid(n) for n, _ in sorted(zip(names, areas, strict=True), key=lambda x: (-x[1], sid(x[0])))
    ]
    s1, s2 = Service(onto, out), Service(onto, out)
    r1, rid = s1.year(1650)
    r2, _ = s2.year(1650)
    assert [p["id"] for p in r1.json()["polities"]] == expected
    assert r1.content == r2.content
    assert served(events, rid)["polities"] == 6


@req(
    GEO, LAYER, invariant="событие served — поля дельты, без названий, геометрии и идентификаторов"
)
def test_served_event_has_no_payload(onto, europe, events):
    svc = Service(onto, europe)
    for y in (1650, 1650, 1800, -3500):
        r, rid = svc.year(y)
        data = r.json()
        ev = served(events, rid)
        assert set(ev.fields) - CONTEXT == SERVED_FIELDS
        assert ev["bytes"] == len(r.content)
        assert ev["untranslated"] == sum(
            1 for p in data["polities"] if p["name_status"] == "original"
        )
        assert ev["polities"] == len(data["polities"])
        values = json.dumps(
            {k: v for k, v in ev.fields.items() if k not in CONTEXT}, ensure_ascii=False
        )
        for p in data["polities"]:
            assert p["id"] not in values and p["name"] not in values and p["original"] not in values
        assert "coordinates" not in values


@req(GEO, LAYER, invariant="повтор года из кэша отдаётся без чтения артефакта")
def test_cached_without_reading_artifact(onto, five, events, monkeypatch):
    svc = Service(onto, five)
    r1, _ = svc.year(1650)
    opened: list[Any] = []
    real = sqlite3.connect

    def spy(*a, **k):
        opened.append(a[0] if a else k)
        return real(*a, **k)

    monkeypatch.setattr(sqlite3, "connect", spy)
    for y in (1650, 1651, 1700):
        r, _rid = svc.year(y)
        assert r.json()["cached"] is True
        assert r.json()["polities"] == r1.json()["polities"]
    assert [
        x for x in opened if "polities" in str(x) or "five" in str(x) or str(five) in str(x)
    ] == []
    assert len(events.where("knowledge.polities.served", cached=True)) == 3


@req(GEO, LAYER, invariant="кэш вытесняет давно не запрошенный интервал (LRU)")
def test_cache_lru(onto, tmp_path, events):
    db = many_intervals(tmp_path, 20)
    svc = Service(onto, db, cache_size=3)
    for y in (5, 15, 25):
        svc.year(y)
    svc.year(5)  # 5 — свежий, вытесняться должен 15
    svc.year(35)
    out = {}
    for y in (5, 25, 15):
        r, rid = svc.year(y)
        out[y] = (r.json()["cached"], served(events, rid)["cached"])
    assert out[5] == (True, True)
    assert out[25] == (True, True)
    assert out[15] == (False, False)


@req(GEO, LAYER, invariant="год — целое −9999…9999; враждебные значения — 400 bad_year")
@pytest.mark.parametrize(
    "raw",
    ["9999x", " ", "+1", "1e3", "0x10", "1650;DROP", "--1", "99999", "1650&year=1", "nan", "-"],
)
def test_bad_year_hostile(onto, five, events, raw):
    svc = Service(onto, five)
    r, _ = svc.year(raw)
    assert r.status_code == 400, raw
    assert "bad_year" in r.text
    assert events.one("knowledge.polities.rejected")["code"] == "bad_year"
    events.assert_none("knowledge.polities.served")


@req(
    GEO,
    LAYER,
    invariant="год — целое −9999…9999; цифры не ASCII (арабские, полноширинные) — 400 bad_year",
)
@pytest.mark.parametrize("raw", ["١٢٣", "１６５０", "١"])
def test_bad_year_non_ascii_digits(onto, five, events, raw):
    svc = Service(onto, five)
    r, _ = svc.year(raw)
    assert r.status_code == 400, (raw, r.status_code, r.text[:80])
    assert events.one("knowledge.polities.rejected")["code"] == "bad_year"
    events.assert_none("knowledge.polities.served")


@req(GEO, LAYER, invariant="границы диапазона года −9999 и 9999 принимаются")
@pytest.mark.parametrize("year", [-9999, 9999, 0, -1])
def test_year_bounds_accepted(onto, five, events, year):
    svc = Service(onto, five)
    r, rid = svc.year(year)
    assert r.status_code == 200
    assert r.json()["year"] == year
    assert served(events, rid)["year"] == year


# --- Русские названия: сценарии -------------------------------------------------------


@req(GEO, NAMES, scenario="Священная Римская империя")
def test_hre_russian_label(onto, tmp_path, events):
    code, out, _, _ = run_build(tmp_path / "eu", "europe.geojson")
    assert code == 0
    built = events.one("knowledge.polities.built")
    records = entities()
    expected_labels = sum(
        1
        for p in europe_rows()
        if expected_name(p["Name"], p.get("Wikidata"), records)[2] == "label"
    )
    assert built["ru_labels"] == expected_labels
    svc = Service(onto, out)
    r, rid = svc.year(1650)
    [hre] = [p for p in r.json()["polities"] if p["original"] == "Holy Roman Empire"]
    assert hre["name"] == "Священная Римская империя"
    assert (hre["name_status"], hre["name_source"]) == ("ru", "label")
    assert hre["wikidata"] == "Q12548"
    served(events, rid)


@req(GEO, NAMES, scenario="Без русской метки")
def test_without_russian_label(onto, tmp_path, events):
    records = {
        "Q900001": {
            "id": "Q900001",
            "labels": {"en": {"language": "en", "value": "Only English"}},
            "sitelinks": {"enwiki": {"site": "enwiki", "title": "Only English"}},
        }
    }
    feats = [
        feature("English Only", 1600, 1700, poly(square(0, 40, 3)), qid="Q900001"),
        feature("No QID", 1600, 1700, poly(square(5, 40, 3)), qid=""),
        feature("Digits QID", 1600, 1700, poly(square(10, 40, 3)), qid="12548"),
    ]
    src = write_geojson(tmp_path / "noru.geojson", feats)
    wd = FakeWikidata(records)
    code, out, _, _ = run_build(tmp_path / "b", src, wd=wd)
    assert code == 0
    svc = Service(onto, out)
    r, rid = svc.year(1650)
    got = {p["original"]: p for p in r.json()["polities"]}
    assert set(got) == {"English Only", "No QID", "Digits QID"}
    for p in got.values():
        assert p["name"] == p["original"]
        assert p["name_status"] == "original"
        assert p["name_source"] == "original"
    assert got["No QID"]["wikidata"] is None
    assert got["Digits QID"]["wikidata"] is None
    sent = [q for url in wd.calls for q in parse_qs(urlsplit(url).query)["ids"][0].split("|")]
    assert "12548" not in sent and "" not in sent
    assert served(events, rid)["untranslated"] == 3


@req(GEO, NAMES, scenario="Заголовок русской Википедии")
def test_ruwiki_title(onto, tmp_path, events):
    records = {
        "Q900010": {
            "id": "Q900010",
            "labels": {},
            "sitelinks": {"ruwiki": {"site": "ruwiki", "title": "Речь Посполитая (1569—1795)"}},
        },
        "Q900011": {
            "id": "Q900011",
            "labels": {},
            "sitelinks": {"ruwiki": {"site": "ruwiki", "title": "Тест (а) (б)"}},
        },
    }
    feats = [
        feature("PLC", 1600, 1700, poly(square(0, 40, 3)), qid="Q900010"),
        feature("Test", 1600, 1700, poly(square(5, 40, 3)), qid="Q900011"),
    ]
    src = write_geojson(tmp_path / "sl.geojson", feats)
    code, out, _, _ = run_build(tmp_path / "b", src, wd=FakeWikidata(records))
    assert code == 0
    assert events.one("knowledge.polities.built")["ru_sitelinks"] == 2
    svc = Service(onto, out)
    r, rid = svc.year(1650)
    got = {p["original"]: p for p in r.json()["polities"]}
    assert (got["PLC"]["name"], got["PLC"]["name_status"], got["PLC"]["name_source"]) == (
        "Речь Посполитая",
        "ru",
        "sitelink",
    )
    assert got["Test"]["name"] == "Тест (а)"
    assert got["Test"]["name_source"] == "sitelink"
    served(events, rid)


HOSTILE = ["   ", "Я" * 300, "Импе\u0007рия", "<b>Империя</b>"]


def hostile_build(tmp: Path, labels: list[str], wd_events=None):
    records = {
        f"Q90002{i}": {
            "id": f"Q90002{i}",
            "labels": {"ru": {"language": "ru", "value": v}},
            "sitelinks": {},
        }
        for i, v in enumerate(labels)
    }
    feats = [
        feature(f"Hostile {i}", 1600, 1700, poly(square(5 * i, 40, 3)), qid=f"Q90002{i}")
        for i in range(len(labels))
    ]
    tmp.mkdir(parents=True, exist_ok=True)
    src = write_geojson(tmp / "h.geojson", feats)
    return run_build(tmp / "b", src, wd=FakeWikidata(records))


@req(GEO, NAMES, scenario="Испорченные метки")
def test_hostile_labels(onto, tmp_path, events):
    code, out, _, _ = hostile_build(tmp_path / "bad", HOSTILE)
    assert code == 0
    bad_labels = events.one("knowledge.polities.built")["ru_labels"]
    events.clear()
    code, _, _, _ = hostile_build(tmp_path / "good", ["Альфа", "Бета", "Гамма", "<b>Империя</b>"])
    assert code == 0
    good_labels = events.one("knowledge.polities.built")["ru_labels"]
    assert bad_labels == good_labels - 3
    svc = Service(onto, out)
    r, rid = svc.year(1650)
    got = {p["original"]: p for p in r.json()["polities"]}
    for i in range(3):
        assert got[f"Hostile {i}"]["name_status"] == "original"
        assert got[f"Hostile {i}"]["name"] == f"Hostile {i}"
    assert got["Hostile 3"]["name"] == "<b>Империя</b>"
    assert got["Hostile 3"]["name_status"] == "ru"
    assert served(events, rid)["untranslated"] == 3


@req(GEO, NAMES, scenario="Пачки запросов")
def test_label_batches(tmp_path, events):
    feats = [
        feature(f"P{i:03d}", 1600, 1700, poly(square(0, 0, 2)), qid=f"Q{1000 + i}")
        for i in range(120)
    ]
    src = write_geojson(tmp_path / "q120.geojson", feats)
    wd = FakeWikidata({})
    code, _, _, _ = run_build(tmp_path / "b", src, wd=wd)
    assert code == 0
    assert len(wd.calls) == 3
    sent: list[str] = []
    for url in wd.calls:
        u = httpx.URL(url)
        assert (u.scheme, u.host, u.path) == ("https", "www.wikidata.org", "/w/api.php")
        q = parse_qs(urlsplit(url).query)
        assert q["action"] == ["wbgetentities"]
        assert q["props"] == ["labels|sitelinks"]
        assert q["languages"] == ["ru"]
        assert q["sitefilter"] == ["ruwiki"]
        assert "languagefallback" not in q
        ids = q["ids"][0].split("|")
        assert len(ids) <= 50
        sent += ids
    assert sorted(sent) == sorted(f"Q{1000 + i}" for i in range(120))
    ev = events.one("knowledge.polities.built")
    assert (ev["label_requests"], ev["qids"]) == (3, 120)


@req(GEO, NAMES, scenario="Без сети")
def test_offline_build(onto, tmp_path, events, _forbid_network):
    records = entities()
    rows = europe_rows()
    qids = sorted(
        {
            p["Wikidata"]
            for p in rows
            if isinstance(p["Wikidata"], str) and p["Wikidata"].startswith("Q")
        }
    )
    half = qids[: len(qids) // 2]
    cache = {}
    for q in half:
        rec = records[q]
        cache[q] = {
            "label": ((rec.get("labels") or {}).get("ru") or {}).get("value"),
            "sitelink": ((rec.get("sitelinks") or {}).get("ruwiki") or {}).get("title"),
        }
    labels = tmp_path / "labels.ru.json"
    labels.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    wd = FakeWikidata()
    code, out, _, _ = run_build(
        tmp_path / "b", "europe.geojson", wd=wd, labels=labels, extra=["--offline"]
    )
    assert code == 0
    assert wd.calls == []
    assert _forbid_network == []
    assert events.one("knowledge.polities.built")["label_requests"] == 0
    conn = sqlite3.connect(out)
    try:
        got = conn.execute(
            "SELECT original, wikidata, name, name_status FROM polity_rows"
        ).fetchall()
    finally:
        conn.close()
    for original, qid, name, status in got:
        if qid in half:
            assert (name, status) == expected_name(original, qid, records)[:2], original
        else:
            assert (name, status) == (original, "original"), original


# --- Русские названия: инварианты ---------------------------------------------------


@req(
    GEO,
    NAMES,
    invariant="name — принятая метка ru/ruwiki своего QID либо original; original всегда Name",
)
def test_name_rule_every_year(onto, europe, events):
    records = entities()
    rows = europe_rows()
    by_id: dict[str, list[dict]] = {}
    for p in rows:
        by_id.setdefault(sid(p["Name"]), []).append(p)
    svc = Service(onto, europe)
    for y in range(1500, 1901):
        r, rid = svc.year(y)
        for p in r.json()["polities"]:
            src = by_id[p["id"]]
            assert p["original"] in {s["Name"] for s in src}
            lead = [s for s in src if s["FromYear"] <= y <= s["ToYear"]]
            lead = max(lead, key=lambda s: s["FromYear"])
            name, status, source = expected_name(lead["Name"], lead.get("Wikidata"), records)
            assert (p["name"], p["name_status"], p["name_source"]) == (name, status, source), (
                y,
                p["original"],
            )
            if status == "original":
                assert p["name"] == p["original"]
        assert served(events, rid)["untranslated"] == sum(
            1 for p in r.json()["polities"] if p["name_status"] == "original"
        )


@req(
    GEO,
    NAMES,
    invariant="QID проверяется по ^Q\\d+$ до запроса: враждебные значения не уходят в Wikidata",
)
def test_hostile_qids_not_requested(tmp_path, events):
    bad = ["Q1|Q2", "Q1&action=delete", "q42", "Q", "Q12 ", "Q-1", "Q１２", "../Q1", "Q1\nQ2"]
    feats = [feature(f"B{i}", 1600, 1700, poly(square(i, 0, 1)), qid=q) for i, q in enumerate(bad)]
    feats.append(feature("Good", 1600, 1700, poly(square(30, 0, 1)), qid="Q12548"))
    src = write_geojson(tmp_path / "bq.geojson", feats)
    wd = FakeWikidata()
    code, out, _, _ = run_build(tmp_path / "b", src, wd=wd)
    assert code == 0
    sent = [q for url in wd.calls for q in parse_qs(urlsplit(url).query)["ids"][0].split("|")]
    assert sent == ["Q12548"]
    for url in wd.calls:
        assert "delete" not in url
    conn = sqlite3.connect(out)
    rows = dict(conn.execute("SELECT original, wikidata FROM polity_rows").fetchall())
    conn.close()
    assert all(rows[f"B{i}"] is None for i in range(len(bad)))
    assert rows["Good"] == "Q12548"
    assert events.one("knowledge.polities.built")["qids"] == 1


@req(GEO, NAMES, invariant="--refresh-labels запрашивает все QID заново")
def test_refresh_labels(tmp_path, events):
    labels = tmp_path / "labels.ru.json"
    code, _, _, wd1 = run_build(tmp_path / "a", "europe.geojson", labels=labels)
    assert code == 0
    code, _, _, wd2 = run_build(
        tmp_path / "b", "europe.geojson", labels=labels, extra=["--refresh-labels"]
    )
    assert code == 0

    def ids(wd):
        return sorted(q for u in wd.calls for q in parse_qs(urlsplit(u).query)["ids"][0].split("|"))

    assert ids(wd2) == ids(wd1) and ids(wd1)
    reqs = [e["label_requests"] for e in events.of("knowledge.polities.built")]
    assert reqs[1] == reqs[0] >= 1


@req(GEO, NAMES, invariant="кэш меток — QID → {label, sitelink}, строка или null")
def test_labels_cache_shape(tmp_path, events):
    labels = tmp_path / "labels.ru.json"
    code, _, _, _ = run_build(tmp_path / "a", "europe.geojson", labels=labels)
    assert code == 0
    cache = json.loads(labels.read_text("utf-8"))
    rows = europe_rows()
    qids = {
        p["Wikidata"]
        for p in rows
        if isinstance(p["Wikidata"], str)
        and p["Wikidata"][:1] == "Q"
        and p["Wikidata"][1:].isdigit()
    }
    assert set(cache) == qids
    for q, v in cache.items():
        assert set(v) == {"label", "sitelink"}, q
        assert all(x is None or isinstance(x, str) for x in v.values()), q
    assert events.one("knowledge.polities.built")["qids"] == len(qids)


@req(GEO, NAMES, invariant="эндпоинт не обращается к сети за названиями: метки в артефакте")
def test_endpoint_no_wikidata(onto, europe, events, _forbid_network, monkeypatch):
    calls = []
    real = httpx.Client.send

    def spy(self, request, *a, **k):
        calls.append(str(request.url))
        return real(self, request, *a, **k)

    monkeypatch.setattr(httpx.Client, "send", spy)
    svc = Service(onto, europe)
    r, rid = svc.year(1650)
    assert r.status_code == 200
    assert [c for c in calls if "wikidata" in c] == []
    assert _forbid_network == [] and svc.llm_calls == []
    served(events, rid)
