"""Юнит-тесты разработчика: сборка исторических границ, слой на год, метки Wikidata
(add-historical-polities). Сценарные и нормативные тесты по дельте пишет тестировщик."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from philograph.knowledge import wikidata
from philograph.knowledge.polities import (
    BadYear,
    PolitiesUnavailable,
    PolityLayer,
    parse_year,
    response_body,
)
from philograph.knowledge.polities_build import (
    BuildError,
    accept_name,
    build,
    fetch,
    measure,
    polygons_of,
    spherical_area,
)

from .cliopatria_fixture import FIXTURES, FakeWikidata, make_archive, manifest


@pytest.fixture
def built(tmp_path):
    archive, sha = make_archive(tmp_path / "src")
    wd = FakeWikidata()
    out = tmp_path / "polities.sqlite"
    report = build(manifest(sha), archive, out, tmp_path / "labels.json", fetch_json=wd)
    return out, report, wd, archive, sha


def rows(db: Path) -> list[tuple]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT * FROM polity_rows ORDER BY row").fetchall()
    finally:
        conn.close()


def naive(year: int) -> set[str]:
    fc = json.loads((FIXTURES / "europe.geojson").read_text(encoding="utf-8"))
    out = set()
    for f in fc["features"]:
        p = f["properties"]
        if (
            p["Type"] == "POLITY"
            and p["FromYear"] <= p["ToYear"]
            and p["FromYear"] <= year <= p["ToYear"]
        ):
            out.add(hashlib.sha1(p["Name"].encode()).hexdigest()[:12])
    return out


# --- wikidata.labels ---------------------------------------------------------------------


def test_labels_batches_and_params():
    wd = FakeWikidata({})
    qids = [f"Q{i}" for i in range(1, 121)] + ["12548", "", "Q1"]
    got, n = wikidata.labels(qids, "ru", wd)
    assert n == 3 and len(wd.calls) == 3
    for url in wd.calls:
        q = httpx.URL(url)
        assert q.host == "www.wikidata.org" and q.path == "/w/api.php"
        assert q.params["action"] == "wbgetentities"
        assert q.params["props"] == "labels|sitelinks"
        assert q.params["languages"] == "ru" and q.params["sitefilter"] == "ruwiki"
        assert "languagefallback" not in q.params
        assert len(q.params["ids"].split("|")) <= 50
        assert "12548" not in q.params["ids"].split("|")
    assert got["12548"] == {"label": None, "sitelink": None}


def test_labels_redirect_and_missing():
    def fetch_json(url):
        return {
            "entities": {
                "Q20": {
                    "id": "Q20",
                    "redirects": {"from": "Q10", "to": "Q20"},
                    "labels": {"ru": {"value": "Новая"}},
                    "sitelinks": {},
                },
                "Q11": {"id": "Q11", "missing": ""},
            }
        }

    got, _ = wikidata.labels(["Q10", "Q11"], "ru", fetch_json)
    assert got["Q10"] == {"label": "Новая", "sitelink": None}
    assert got["Q11"] == {"label": None, "sitelink": None}


def test_labels_url_rejects_bad_input():
    with pytest.raises(wikidata.WikidataError):
        wikidata.labels_url(["Q1"] * 51, "ru")
    with pytest.raises(wikidata.WikidataError):
        wikidata.labels_url(["Q1x"], "ru")
    with pytest.raises(wikidata.WikidataError):
        wikidata.labels_url(["Q1"], "ru&x=1")


@pytest.mark.parametrize(
    ("raw", "sitelink", "expected"),
    [
        ("Речь Посполитая", False, "Речь Посполитая"),
        ("Речь Посполитая (1569—1795)", True, "Речь Посполитая"),
        ("Тест (а) (б)", True, "Тест (а)"),
        ("Тест (а)", False, "Тест (а)"),
        ("   ", False, None),
        ("x" * 201, False, None),
        ("a\u0007b", False, None),
        ("<b>Империя</b>", False, "<b>Империя</b>"),
        (None, False, None),
        ("(только скобки)", True, None),
    ],
)
def test_accept_name(raw, sitelink, expected):
    assert accept_name(raw, sitelink=sitelink) == expected


# --- сборка ------------------------------------------------------------------------------


def test_build_counts_and_names(built, events):
    out, *_ = built
    ev = events.one("knowledge.polities.built")
    assert ev.get("rows") == 18 and ev.get("polities") == 16
    assert ev.get("skipped_relation") == 1 and ev.get("skipped_invalid") == 1
    assert ev.get("vertices_out") < ev.get("vertices_in")
    assert ev.get("qids") == 12 and ev.get("label_requests") == 1
    names = {r[7]: (r[4], r[5], r[6], r[8]) for r in rows(out)}
    assert names["Holy Roman Empire"] == ("Священная Римская империя", "ru", "label", "Q12548")
    assert names["Sitelink Realm"] == ("Пример", "ru", "sitelink", "Q999999903")
    assert names["Untranslated Realm"] == (
        "Untranslated Realm",
        "original",
        "original",
        "Q999999901",
    )
    assert names["Bad QID Polity"][1:] == ("original", "original", None)
    assert names["Nameless Polity"][3] is None
    assert ev.get("ru_sitelinks") == 1


def test_build_geometry_rules(built):
    out, *_ = built
    from shapely.geometry import shape

    ids = {}
    for r in rows(out):
        g = json.loads(r[10])
        assert shape(g).is_valid
        for poly in polygons_of(g):
            assert spherical_area(poly) < 2 * math.pi
        ids.setdefault(r[7], set()).add(r[1])
        if r[7] == "Tiny City":
            assert g["type"] == "Polygon"
    assert all(len(v) == 1 for v in ids.values())
    assert ids["Holy Roman Empire"] == {hashlib.sha1(b"Holy Roman Empire").hexdigest()[:12]}


def test_rebuild_is_deterministic_and_uses_cache(built, tmp_path, events):
    out, _, wd, archive, sha = built
    events.clear()
    out2 = tmp_path / "again.sqlite"
    build(manifest(sha), archive, out2, tmp_path / "labels.json", fetch_json=wd)
    assert rows(out) == rows(out2)
    assert events.one("knowledge.polities.built").get("label_requests") == 0
    assert len(wd.calls) == 1


def test_offline_uses_only_cache(tmp_path, events):
    archive, sha = make_archive(tmp_path / "src")
    wd = FakeWikidata()
    report = build(
        manifest(sha),
        archive,
        tmp_path / "o.sqlite",
        tmp_path / "l.json",
        fetch_json=wd,
        offline=True,
    )
    assert wd.calls == [] and report["label_requests"] == 0 and report["ru_labels"] == 0


def test_checksum_mismatch_keeps_artifact(built, tmp_path, events):
    out, _, wd, archive, sha = built
    before = hashlib.sha256(out.read_bytes()).hexdigest()
    data = bytearray(archive.read_bytes())
    data[-5] ^= 1
    archive.write_bytes(bytes(data))
    events.clear()
    with pytest.raises(BuildError):
        build(manifest(sha), archive, out, tmp_path / "labels.json", fetch_json=wd)
    assert hashlib.sha256(out.read_bytes()).hexdigest() == before
    assert events.one("knowledge.polities.rejected").get("code") == "checksum_mismatch"
    events.assert_none("knowledge.polities.built")


def test_fetch_checks_host_and_sum(tmp_path, events):
    body = b"zip-bytes"
    sha = hashlib.sha256(body).hexdigest()
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=body))
    m = manifest(sha)
    path, digest = fetch(m, tmp_path / "a.zip", transport=transport)
    assert path.read_bytes() == body and digest == sha
    with pytest.raises(BuildError):
        fetch(manifest("0" * 64), tmp_path / "b.zip", transport=transport)
    assert not (tmp_path / "b.zip").exists()
    assert events.one("knowledge.polities.rejected").get("code") == "checksum_mismatch"
    bad = manifest(sha)
    bad["download"]["url"] = "https://example.org/x.zip"
    with pytest.raises(BuildError):
        fetch(bad, tmp_path / "c.zip", transport=transport)


# --- слой на год -------------------------------------------------------------------------


def test_activity_and_interval_over_all_years(built):
    out, *_ = built
    layer = PolityLayer(out)
    seen = {}
    for year in range(600, 1950):
        part, _ = layer.compute(year)
        items = json.loads(part.body)
        got = {p["id"] for p in items}
        assert got == naive(year), year
        assert all(p["from"] <= year <= p["to"] for p in items)
        assert part.valid_from <= year <= part.valid_to
        rowset = {(p["id"], p["from"], p["to"]) for p in items}  # набор строк, не только id
        seen[year] = (rowset, part.valid_from, part.valid_to)
    for got, lo, hi in seen.values():
        for y in (lo, hi):
            if y in seen:
                assert seen[y][0] == got
        for y in (lo - 1, hi + 1):
            if y in seen:
                assert seen[y][0] != got


def test_merged_rows_and_order(built):
    out, *_ = built
    part, _ = PolityLayer(out).compute(1650)
    items = json.loads(part.body)
    hre = next(p for p in items if p["original"] == "Holy Roman Empire")
    assert (hre["from"], hre["to"]) == (1649, 1806)
    assert items[0]["original"] == "Ottoman Empire" or items[0]["original"] == "Russian Empire"
    areas = [p["id"] for p in items]
    assert len(areas) == len(set(areas))


def test_serve_cache_and_events(built, events):
    out, *_ = built
    layer = PolityLayer(out)
    a = layer.serve(1650)
    b = layer.serve(1650)
    c = layer.serve(1651)
    ja, jb, jc = (json.loads(x) for x in (a, b, c))
    assert ja["polities"] == jb["polities"] == jc["polities"]
    assert (ja["cached"], jb["cached"], jc["cached"]) == (False, True, True)
    assert jc["year"] == 1651
    served = events.of("knowledge.polities.served")
    assert [e.get("cached") for e in served] == [False, True, True]
    assert ja["source"]["version"] == "v9.9.9-test"
    assert all("name" not in e.fields for e in served)


def test_cache_limits(built):
    out, *_ = built
    small = PolityLayer(out, cache_size=2)
    for y in (700, 1400, 1650, 1800):
        small.serve(y)
    assert small.cached_intervals() == 2
    assert json.loads(small.serve(700))["cached"] is False
    one = len(PolityLayer(out).compute(1650)[0].body)
    tiny = PolityLayer(out, cache_bytes=one - 1)
    tiny.serve(1650)
    assert json.loads(tiny.serve(1650))["cached"] is False
    assert tiny.cached_bytes() == 0


def test_unavailable(tmp_path, events):
    with pytest.raises(PolitiesUnavailable) as exc:
        PolityLayer(tmp_path / "nope.sqlite").serve(1650)
    assert exc.value.reason == "missing"
    db = tmp_path / "old.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO meta VALUES ('format_version', '999')")
    conn.commit()
    conn.close()
    with pytest.raises(PolitiesUnavailable) as exc:
        PolityLayer(db).serve(1650)
    assert exc.value.reason == "format"
    assert [e.get("reason") for e in events.of("knowledge.polities.unavailable")] == [
        "missing",
        "format",
    ]


@pytest.mark.parametrize("raw", ["abc", "1.5", "10000", "-10000", "", None, " 12 x"])
def test_parse_year_rejects(raw):
    with pytest.raises(BadYear):
        parse_year(raw)


def test_route(built, onto, events):
    from philograph.knowledge.app import build_app

    out, *_ = built
    client = TestClient(build_app(onto.statements, polity_layer=PolityLayer(out)))
    r = client.get("/v1/map/polities", params={"year": "1650"})
    assert r.status_code == 200 and r.json()["year"] == 1650
    assert client.get("/v1/map/polities", params={"year": "x"}).status_code == 400
    assert events.one("knowledge.polities.rejected").get("code") == "bad_year"
    none = TestClient(build_app(onto.statements))
    r = none.get("/v1/map/polities", params={"year": "1650"})
    assert r.status_code == 503


def test_measure_matches_endpoint(built, events):
    import gzip

    out, *_ = built
    result = measure(out, [1650, 1800, -3500])
    layer = PolityLayer(out)
    for row in result["years"]:
        part, source = layer.compute(row["year"])
        body = response_body(row["year"], part, source, cached=False)
        assert row["bytes"] == len(body) and row["gzip_bytes"] == len(gzip.compress(body, 9))
        assert row["polities"] == part.polities and row["inactive"] == 0
    assert events.one("knowledge.polities.measured").get("years") == 3


# --- ревью 7: вырождение на сетке, дыры, ссылки, путь артефакта ---------------------------


def _square(x: float, y: float, d: float) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[[x, y], [x + d, y], [x + d, y + d], [x, y + d], [x, y]]],
    }


@pytest.mark.parametrize("side", [0.004, 0.00004])
def test_degenerate_polygon_becomes_grid_cell(side):
    from shapely.geometry import shape

    from philograph.knowledge.polities_build import simplify_geometry

    x, y = 12.453 - side / 2, 41.903 - side / 2  # Ватикан
    out, _, tiny = simplify_geometry(_square(x, y, side), 0.05, 2, 0.01)
    assert tiny and out["type"] == "Polygon"
    ring = out["coordinates"][0]
    assert {tuple(p) for p in ring} == {
        (12.45, 41.9),
        (12.46, 41.9),
        (12.46, 41.91),
        (12.45, 41.91),
    }
    assert all(round(v, 2) == v for p in ring for v in p)
    assert shape(out).is_valid and spherical_area(out["coordinates"]) < 2 * math.pi


def test_degenerate_records_do_not_break_build(tmp_path, events):
    feats = [
        {
            "type": "Feature",
            "properties": {
                "Name": f"Vatican {i}",
                "FromYear": 1929,
                "ToYear": 2024,
                "Area": 0.44,
                "Type": "POLITY",
                "Wikidata": "",
                "Wikipedia": "",
                "SeshatID": "",
            },
            "geometry": _square(12.451, 41.901, side),
        }
        for i, side in enumerate([0.004, 0.00004])
    ]
    src = tmp_path / "v.geojson"
    src.write_text(json.dumps({"type": "FeatureCollection", "features": feats}), "utf-8")
    archive, sha = make_archive(tmp_path / "src", src)
    report = build(manifest(sha), archive, tmp_path / "v.sqlite", tmp_path / "l.json", offline=True)
    assert report["polities"] == 2 and report["skipped_invalid"] == 0 and report["tiny_kept"] == 2


def test_small_holes_dropped():
    from philograph.knowledge.polities_build import simplify_geometry

    g = {
        "type": "Polygon",
        "coordinates": [
            [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]],
            [[0.2, 0.2], [0.2, 0.25], [0.25, 0.25], [0.25, 0.2], [0.2, 0.2]],
            [[0.5, 0.5], [0.5, 0.8], [0.8, 0.8], [0.8, 0.5], [0.5, 0.5]],
        ],
    }
    out, _, _ = simplify_geometry(g, 0.05, 2, 0.01)
    assert len(out["coordinates"]) == 2  # внешнее кольцо и большая дыра


def test_source_links_must_be_https():
    from philograph.knowledge.polities_build import source_block

    m = manifest("0" * 64)
    m["license_url"] = "javascript:alert(1)"
    with pytest.raises(BuildError):
        source_block(m)


def test_artifact_path_with_special_chars(built, tmp_path):
    out, *_ = built
    odd = tmp_path / "a#b?c%d"
    odd.mkdir()
    target = odd / "polities.sqlite"
    target.write_bytes(out.read_bytes())
    assert json.loads(PolityLayer(target).serve(1650))["polities"]
    with pytest.raises(PolitiesUnavailable) as exc:
        PolityLayer(odd / "nope.sqlite").serve(1650)
    assert exc.value.reason == "missing"


def test_main_truncated_archive_exit_code(tmp_path, capsys):
    from philograph.knowledge.polities_build import main

    archive, _ = make_archive(tmp_path / "src")
    data = archive.read_bytes()[:-200]
    archive.write_bytes(data)
    m = yaml_manifest(tmp_path, hashlib.sha256(data).hexdigest())
    code = main(
        [
            "--manifest",
            str(m),
            "build",
            "--archive",
            str(archive),
            "--out",
            str(tmp_path / "x.sqlite"),
            "--labels",
            str(tmp_path / "l.json"),
            "--offline",
        ]
    )
    assert code == 1 and not (tmp_path / "x.sqlite").exists()
    assert "ошибка" in capsys.readouterr().err


def yaml_manifest(tmp_path: Path, sha: str) -> Path:
    import yaml

    p = tmp_path / "manifest.yaml"
    p.write_text(yaml.safe_dump(manifest(sha), allow_unicode=True), "utf-8")
    return p
