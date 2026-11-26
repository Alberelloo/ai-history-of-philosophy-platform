"""Сценарные и нормативные тесты тестировщика: «Сборка исторических границ», «Пределы
исторического слоя» (замер на фикстуре) и «Атрибуция исторических границ» (документация
и манифест). Дельта: ``openspec/changes/add-historical-polities/specs/geo-timeline/spec.md``.

Тесты идут от сценариев дельты. Сферическая площадь считается в тесте своей функцией
(формула d3-geo ``geoArea``), валидность геометрии — shapely, идентификатор — SHA-1 в тесте:
ничего из этого не берётся у кода сборки. Wikidata — словарь ответов, сети нет.
"""

# ruff: noqa: E501 — имена инвариантов спецификации

from __future__ import annotations

import gzip
import hashlib
import itertools
import json
import math
import re
import sqlite3
import subprocess
import tracemalloc
import zipfile
from pathlib import Path
from typing import Any

import pytest
import yaml
from shapely.geometry import shape

from philograph.knowledge.polities import PolityLayer
from philograph.knowledge.polities_build import build, fetch, main, measure

from .cliopatria_fixture import FIXTURES, FakeWikidata, entities, make_archive, manifest

req = pytest.mark.req
GEO = "geo-timeline"
BUILD = "Сборка исторических границ"
LIMITS = "Пределы исторического слоя"
ATTR = "Атрибуция исторических границ"
ROOT = Path(__file__).resolve().parents[2]
SPEC_EVENT_FIELDS = {
    "dataset_version",
    "rows",
    "polities",
    "skipped_relation",
    "skipped_invalid",
    "qids",
    "ru_labels",
    "ru_sitelinks",
    "label_requests",
    "intervals",
    "vertices_in",
    "vertices_out",
    "seconds",
}


# --- независимые расчёты теста ----------------------------------------------------------


def sphere_area(polygon: list[list[list[float]]]) -> float:
    """Сферическая площадь многоугольника GeoJSON (стерадианы) — порт d3-geo ``geoArea``."""
    total = 0.0
    for ring in polygon:
        pts = list(ring)
        if pts and pts[0] != pts[-1]:
            pts.append(pts[0])
        lam0 = math.radians(pts[0][0])
        phi0 = math.radians(pts[0][1]) / 2 + math.pi / 4
        cos0, sin0 = math.cos(phi0), math.sin(phi0)
        for lon, lat in pts[1:]:
            lam = math.radians(lon)
            phi = math.radians(lat) / 2 + math.pi / 4
            d = lam - lam0
            sd = 1 if d >= 0 else -1
            ad = sd * d
            cos1, sin1 = math.cos(phi), math.sin(phi)
            k = sin0 * sin1
            u = cos0 * cos1 + k * math.cos(ad)
            v = k * sd * math.sin(ad)
            total += math.atan2(v, u)
            lam0, cos0, sin0 = lam, cos1, sin1
    ring_sum = total
    return 2 * (2 * math.pi + ring_sum if ring_sum < 0 else ring_sum)


def polygons(geometry: dict[str, Any]) -> list[Any]:
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    assert geometry["type"] == "MultiPolygon", geometry["type"]
    return geometry["coordinates"]


def sha_id(name: str) -> str:
    return hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]


def digits_ok(value: float, precision: int) -> bool:
    text = repr(float(value))
    if "e" in text:
        return abs(value) < 10**-precision and value == 0
    frac = text.split(".")[1] if "." in text else ""
    return len(frac.rstrip("0")) <= precision


def square(lon: float, lat: float, size: float, *, ccw: bool = True) -> list[list[float]]:
    ring = [[lon, lat], [lon + size, lat], [lon + size, lat + size], [lon, lat + size], [lon, lat]]
    return ring if ccw else ring[::-1]


def feature(
    name: Any,
    start: Any,
    end: Any,
    geometry: dict[str, Any] | None,
    *,
    qid: Any = "",
    kind: str = "POLITY",
    area: float = 1000.0,
) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {
            "Name": name,
            "Type": kind,
            "FromYear": start,
            "ToYear": end,
            "Wikidata": qid,
            "Area": area,
        },
        "geometry": geometry,
    }


def poly(*rings) -> dict[str, Any]:
    return {"type": "Polygon", "coordinates": list(rings)}


def write_geojson(path: Path, features: list[dict]) -> Path:
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def fixture_rows(name: str = "europe.geojson") -> list[dict[str, Any]]:
    """Строки POLITY фикстуры, прошедшие проверки дельты (правило 2 сборки), по порядку."""
    fc = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    out = []
    for f in fc["features"]:
        p = f["properties"]
        ok = (
            p.get("Type") == "POLITY"
            and p.get("Name")
            and isinstance(p.get("FromYear"), int)
            and isinstance(p.get("ToYear"), int)
            and p["FromYear"] <= p["ToYear"]
            and (f.get("geometry") or {}).get("type") in ("Polygon", "MultiPolygon")
        )
        if ok:
            out.append(p)
    return out


def artifact_rows(db: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM polity_rows ORDER BY row")]
    finally:
        conn.close()


def artifact_meta(db: Path) -> dict[str, str]:
    conn = sqlite3.connect(db)
    try:
        return dict(conn.execute("SELECT key, value FROM meta").fetchall())
    finally:
        conn.close()


def write_manifest(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def run_build(tmp: Path, geojson, *, wd=None, extra=(), out=None, labels=None, **params):
    """``build`` через командную строку: (код выхода, артефакт, кэш меток, Wikidata)."""
    archive, sha = make_archive(tmp / "src", geojson)
    m = write_manifest(tmp / "manifest.yaml", manifest(sha, **params))
    out = out or tmp / "polities.sqlite"
    labels = labels or tmp / "labels.ru.json"
    wd = wd if wd is not None else FakeWikidata()
    code = main(
        [
            "--manifest",
            str(m),
            "build",
            "--archive",
            str(archive),
            "--out",
            str(out),
            "--labels",
            str(labels),
            *extra,
        ],
        fetch_json=wd,
    )
    return code, out, labels, wd


def check_geometry(row_geometry: str, precision: int) -> list[tuple]:
    """Нарушения правил 3–4 сборки у геометрии строки: валидность, точность, площадь < 2π."""
    bad = []
    g = json.loads(row_geometry)
    if g["type"] not in ("Polygon", "MultiPolygon"):
        bad.append(("тип", g["type"]))
        return bad
    if not shape(g).is_valid:
        bad.append(("невалидна", g["type"]))
    for p in polygons(g):
        if not shape({"type": "Polygon", "coordinates": p}).is_valid:
            bad.append(("многоугольник невалиден",))
        a = sphere_area(p)
        if not a < 2 * math.pi:
            bad.append(("сферическая площадь ≥ 2π", round(a, 4)))
        for ring in p:
            for lon, lat in ring:
                if not (digits_ok(lon, precision) and digits_ok(lat, precision)):
                    bad.append(("точность", lon, lat))
    return bad


# --- Сборка исторических границ: сценарии ------------------------------------------------


@req(GEO, BUILD, scenario="Сборка фикстуры")
def test_build_fixture(tmp_path, events):
    code, out, _, _ = run_build(tmp_path, "build10.geojson")
    assert code == 0
    rows = artifact_rows(out)
    assert len(rows) == 8
    for r in rows:
        assert check_geometry(r["geometry"], 2) == [], r["original"]
    ev = events.one("knowledge.polities.built")
    assert ev["rows"] == 10
    assert ev["polities"] == 8
    assert ev["skipped_relation"] == 1
    assert ev["skipped_invalid"] == 1
    assert ev["vertices_out"] < ev["vertices_in"]
    assert set(ev.fields) - {"request_id", "run_id", "service"} >= SPEC_EVENT_FIELDS
    assert ev["dataset_version"] == "v9.9.9-test"


@req(GEO, BUILD, scenario="Маленькое образование остаётся")
def test_tiny_polity_kept(tmp_path, events):
    # Все кольца меньше min_ring_deg2 (0,01 град²): 0,06² = 0,0036 и 0,09² = 0,0081.
    small = square(10.0, 50.0, 0.06)
    big = square(20.0, 40.0, 0.09)
    features = [
        feature(
            "Tiny Twin",
            1600,
            1700,
            {"type": "MultiPolygon", "coordinates": [[small], [big]]},
            qid="Q999999902",
        ),
        feature("Ordinary", 1600, 1700, poly(square(0.0, 45.0, 3.0)), qid="Q4948"),
    ]
    src = write_geojson(tmp_path / "tiny.geojson", features)
    code, out, _, _ = run_build(tmp_path, src)
    assert code == 0
    rows = {r["original"]: r for r in artifact_rows(out)}
    assert set(rows) == {"Tiny Twin", "Ordinary"}
    g = json.loads(rows["Tiny Twin"]["geometry"])
    ps = polygons(g)
    assert len(ps) == 1, g
    kept = shape({"type": "Polygon", "coordinates": ps[0]})
    # Это самое большое исходное кольцо (после упрощения): внутри квадрата 20…20,09 × 40…40,09.
    assert kept.centroid.distance(shape(poly(big)).centroid) < 0.02, kept.centroid
    assert kept.area == pytest.approx(0.0081, abs=0.002)
    ev = events.one("knowledge.polities.built")
    assert ev["polities"] == 2


@req(GEO, BUILD, scenario="Вырожденное кольцо")
def test_degenerate_ring_becomes_grid_cell(tmp_path, events):
    # Квадраты со стороной 0,004° (Ватикан) и 0,00004° при precision = 2 (клетка 0,01°).
    def centered(lon, lat, side):
        h = side / 2
        return poly(
            [
                [lon - h, lat - h],
                [lon + h, lat - h],
                [lon + h, lat + h],
                [lon - h, lat + h],
                [lon - h, lat - h],
            ]
        )

    cases = {
        "Vatican": ((12.453, 41.903), 0.004, (12.45, 12.46, 41.90, 41.91)),
        "Speck": ((30.1234, 50.4567), 0.00004, (30.12, 30.13, 50.45, 50.46)),
    }
    features = [
        feature(n, 1600, 1700, centered(*c, side), qid="Q4948") for n, (c, side, _) in cases.items()
    ]
    features.append(feature("Ordinary", 1600, 1700, poly(square(0.0, 45.0, 3.0)), qid="Q12548"))
    features.append(feature("Broken", 1700, 1600, poly(square(5.0, 45.0, 1.0))))  # пропуск
    src = write_geojson(tmp_path / "degenerate.geojson", features)
    code, out, _, _ = run_build(tmp_path, src, precision=2)
    assert code == 0
    rows = {r["original"]: r for r in artifact_rows(out)}
    assert set(rows) == {"Vatican", "Speck", "Ordinary"}
    for name, (_, _, (x0, x1, y0, y1)) in cases.items():
        g = json.loads(rows[name]["geometry"])
        ps = polygons(g)
        assert len(ps) == 1, (name, g)
        assert check_geometry(rows[name]["geometry"], 2) == [], name
        cell = shape({"type": "Polygon", "coordinates": ps[0]})
        assert [round(v, 6) for v in cell.bounds] == [x0, y0, x1, y1], (name, cell.bounds)
        assert cell.area == pytest.approx(0.0001, rel=1e-6), name
        assert len(ps[0]) == 1, (name, "у клетки нет дыр")
    ev = events.one("knowledge.polities.built")
    assert ev["polities"] == 3
    assert ev["skipped_invalid"] == 1  # только «Broken»


@req(GEO, BUILD, scenario="Одно образование — один id")
def test_one_polity_one_id(tmp_path, events):
    code, out, _, _ = run_build(tmp_path, "europe.geojson")
    assert code == 0
    hre = [r for r in artifact_rows(out) if r["original"] == "Holy Roman Empire"]
    assert len(hre) == 3
    expected = hashlib.sha1(b"Holy Roman Empire").hexdigest()[:12]
    assert {r["id"] for r in hre} == {expected}
    assert sorted((r["from_year"], r["to_year"]) for r in hre) == [
        (962, 1500),
        (1501, 1648),
        (1649, 1806),
    ]
    ev = events.one("knowledge.polities.built")
    assert ev["polities"] == len(fixture_rows()) == 16


@req(GEO, BUILD, scenario="Повторная сборка")
def test_rebuild_same_rows(tmp_path, events):
    labels = tmp_path / "labels.ru.json"
    code1, out1, _, _wd1 = run_build(tmp_path / "a", "europe.geojson", labels=labels)
    code2, out2, _, wd2 = run_build(tmp_path / "b", "europe.geojson", labels=labels)
    assert code1 == code2 == 0
    fields = ("id", "from_year", "to_year", "name", "original", "geometry")
    first = [tuple(r[f] for f in fields) for r in artifact_rows(out1)]
    second = [tuple(r[f] for f in fields) for r in artifact_rows(out2)]
    assert first == second
    assert artifact_rows(out1) == artifact_rows(out2)  # поле в поле, все столбцы
    built = events.of("knowledge.polities.built")
    assert len(built) == 2
    assert built[0]["label_requests"] >= 1
    assert built[1]["label_requests"] == 0
    assert wd2.calls == []


@req(GEO, BUILD, scenario="Неверная контрольная сумма")
def test_checksum_mismatch(tmp_path, events):
    code, out, labels, _ = run_build(tmp_path, "europe.geojson")
    assert code == 0
    before = hashlib.sha256(out.read_bytes()).hexdigest()
    archive = tmp_path / "src" / "cliopatria.geojson.zip"
    data = bytearray(archive.read_bytes())
    data[len(data) // 2] ^= 0x01
    archive.write_bytes(bytes(data))
    events.clear()
    code = main(
        [
            "--manifest",
            str(tmp_path / "manifest.yaml"),
            "build",
            "--archive",
            str(archive),
            "--out",
            str(out),
            "--labels",
            str(labels),
        ],
        fetch_json=FakeWikidata(),
    )
    assert code != 0
    assert hashlib.sha256(out.read_bytes()).hexdigest() == before
    assert events.one("knowledge.polities.rejected")["code"] == "checksum_mismatch"
    events.assert_none("knowledge.polities.built")


@req(GEO, BUILD, scenario="Данные вне git")
def test_data_outside_git():
    files = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert [f for f in files if f.startswith("data/")] == []
    banned = {"cliopatria.geojson", "cliopatria.geojson.zip", "polities.sqlite", "labels.ru.json"}
    assert [f for f in files if Path(f).name in banned] == []
    heavy = [f for f in files if Path(f).suffix in (".geojson", ".zip", ".sqlite")]
    allowed = re.compile(r"^tests/(.+/)?fixtures/cliopatria/[^/]+$")
    assert [f for f in heavy if not allowed.match(f)] == []
    assert sum((ROOT / f).stat().st_size for f in heavy) <= 200 * 1024
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "data/" in [line.strip() for line in ignore]
    m = yaml.safe_load((ROOT / "sources" / "cliopatria.yaml").read_text(encoding="utf-8"))
    for path in (
        "zenodo.record",
        "zenodo.doi",
        "version",
        "authors",
        "license",
        "download.url",
        "download.sha256",
        "build.tolerance_deg",
        "build.precision",
        "build.min_ring_deg2",
        "control_years",
    ):
        value: Any = m
        for key in path.split("."):
            value = value.get(key) if isinstance(value, dict) else None
        assert value not in (None, "", []), path
    assert m["license"] == "cc-by-4.0"
    licenses = yaml.safe_load((ROOT / "sources" / "licenses.yaml").read_text(encoding="utf-8"))
    assert "cc-by-4.0" in json.dumps(licenses)
    assert re.fullmatch(r"[0-9a-f]{64}", m["download"]["sha256"])


# --- Сборка: инварианты ----------------------------------------------------------------


@req(
    GEO,
    BUILD,
    invariant="геометрия валидна, координаты не длиннее precision, площадь каждого многоугольника < 2π",
)
@pytest.mark.parametrize("precision", [1, 2, 3])
def test_geometry_rules_hostile_input(tmp_path, events, precision):
    # Враждебные входы: «бабочка» (самопересечение), обход против часовой и по часовой,
    # дыра, координаты с 9 знаками, образование через антимеридиан (170…179,9).
    bowtie = [[0, 0], [4, 4], [4, 0], [0, 4], [0, 0]]
    fine = [
        [round(10 + 3 * math.cos(t / 20), 9), round(50 + 2 * math.sin(t / 20), 9)]
        for t in range(126)
    ]
    fine.append(fine[0])
    features = [
        feature("Bowtie", 1600, 1700, poly(bowtie), qid="Q4948"),
        feature("CCW", 1600, 1700, poly(square(20, 40, 5, ccw=True)), qid="Q12548"),
        feature("CW", 1600, 1700, poly(square(30, 40, 5, ccw=False)), qid="Q12560"),
        feature(
            "Holed",
            1600,
            1700,
            poly(square(40, 40, 6), square(42, 42, 2, ccw=False)),
            qid="Q27306",
        ),
        feature("Fine", 1600, 1700, poly(fine), qid="Q34266"),
        feature("Pacific", 1600, 1700, poly(square(170, -20, 9.9)), qid="Q70972"),
        feature(
            "Multi",
            1600,
            1700,
            {
                "type": "MultiPolygon",
                "coordinates": [[square(60, 10, 3)], [square(66, 10, 4, ccw=False)]],
            },
            qid="Q80702",
        ),
    ]
    src = write_geojson(tmp_path / "hostile.geojson", features)
    code, out, _, _ = run_build(tmp_path, src, precision=precision)
    assert code == 0
    rows = artifact_rows(out)
    assert {r["original"] for r in rows} == {f["properties"]["Name"] for f in features}
    for r in rows:
        assert check_geometry(r["geometry"], precision) == [], r["original"]
    assert events.one("knowledge.polities.built")["polities"] == len(features)


@req(
    GEO,
    BUILD,
    invariant="внешнее кольцо по часовой, дыры — против (сферическая площадь меньше полусферы)",
)
def test_ring_orientation(tmp_path, events):
    features = [
        feature("Holed", 1600, 1700, poly(square(40, 40, 6), square(42, 42, 2)), qid="Q27306"),
        feature("Plain", 1600, 1700, poly(square(10, 10, 5)), qid="Q12548"),
    ]
    src = write_geojson(tmp_path / "orient.geojson", features)
    code, out, _, _ = run_build(tmp_path, src)
    assert code == 0
    for r in artifact_rows(out):
        for p in polygons(json.loads(r["geometry"])):
            outer, *holes = p
            # По часовой на плоскости lon/lat — отрицательная площадь по формуле шнурка.
            assert shoelace(outer) < 0, (r["original"], "внешнее кольцо не по часовой")
            for h in holes:
                assert shoelace(h) > 0, (r["original"], "дыра не против часовой")
            assert sphere_area(p) < 2 * math.pi
    assert events.one("knowledge.polities.built")["polities"] == 2


def shoelace(ring) -> float:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in itertools.pairwise(ring)) / 2


@req(
    GEO,
    BUILD,
    invariant="записано столько строк, сколько строк POLITY прошло проверки; ни одна не пропала",
)
def test_no_row_lost_and_skips_counted(tmp_path, events):
    good = poly(square(0, 0, 2))
    features = [
        feature("A", 1600, 1700, good, qid="Q4948"),
        feature("Rel", 1600, 1700, good, kind="RELATION"),
        feature("", 1600, 1700, good),  # без Name
        feature(None, 1600, 1700, good),  # без Name
        feature("Float", 1600.5, 1700, good),  # нецелый FromYear
        feature("Str", 1600, "1700", good),  # нецелый ToYear
        feature("Reverse", 1700, 1600, good),  # FromYear > ToYear
        feature("Point", 1600, 1700, {"type": "Point", "coordinates": [1, 1]}),
        feature("Line", 1600, 1700, {"type": "LineString", "coordinates": [[1, 1], [2, 2]]}),
        feature("NoGeom", 1600, 1700, None),
        feature("B", -3400, 2024, good, qid="Q12548"),
        feature("C", 5, 5, {"type": "MultiPolygon", "coordinates": [good["coordinates"]]}),
        feature("Rel2", 1, 2, good, kind="RELATION"),
    ]
    src = write_geojson(tmp_path / "mixed.geojson", features)
    code, out, _, _ = run_build(tmp_path, src)
    assert code == 0
    rows = artifact_rows(out)
    assert [r["original"] for r in rows] == ["A", "B", "C"]
    assert [(r["from_year"], r["to_year"]) for r in rows] == [(1600, 1700), (-3400, 2024), (5, 5)]
    ev = events.one("knowledge.polities.built")
    assert (ev["rows"], ev["polities"], ev["skipped_relation"], ev["skipped_invalid"]) == (
        13,
        3,
        2,
        8,
    )


@req(GEO, BUILD, invariant="у всех строк одного Name один id — первые 12 знаков SHA-1 от Name")
def test_id_is_sha1_of_name(tmp_path, events):
    names = ["Holy Roman Empire", "Речь Посполитая", "(Spanish Empire)", "A" * 300, "x;DROP"]
    features = []
    for i, n in enumerate(names):
        for k in range(2):
            features.append(feature(n, 1000 + 100 * k, 1099 + 100 * k, poly(square(i * 5, 10, 2))))
    src = write_geojson(tmp_path / "ids.geojson", features)
    code, out, _, _ = run_build(tmp_path, src)
    assert code == 0
    by_name: dict[str, set[str]] = {}
    for r in artifact_rows(out):
        by_name.setdefault(r["original"], set()).add(r["id"])
    assert by_name == {n: {sha_id(n)} for n in names}
    assert events.one("knowledge.polities.built")["polities"] == 10


@req(GEO, BUILD, invariant="сборка детерминирована: тот же архив, манифест и кэш дают те же строки")
def test_build_deterministic_three_times(tmp_path, events):
    labels = tmp_path / "labels.ru.json"
    outs = []
    for i in range(3):
        code, out, _, _ = run_build(tmp_path / str(i), "europe.geojson", labels=labels)
        assert code == 0
        outs.append(artifact_rows(out))
    assert outs[0] == outs[1] == outs[2]
    assert [e["label_requests"] for e in events.of("knowledge.polities.built")][1:] == [0, 0]


@req(
    GEO,
    BUILD,
    invariant="архив читается потоково: без распаковки на диск и без загрузки GeoJSON целиком",
)
def test_streaming_build(tmp_path, events, monkeypatch):
    # GeoJSON ~12 МБ (сжимается в архиве сильно): пик памяти Python сборки — меньше половины.
    ring = [
        [round(10 + 3 * math.cos(t / 80), 4), round(50 + 2 * math.sin(t / 80), 4)]
        for t in range(500)
    ]
    ring.append(ring[0])
    features = [feature(f"P{i:04d}", 1000 + i, 1001 + i, poly(ring)) for i in range(1200)]
    src = write_geojson(tmp_path / "large.geojson", features)
    size = src.stat().st_size
    assert size > 10_000_000
    archive, sha = make_archive(tmp_path / "src", src)
    src.unlink()

    def no_extract(*a, **k):
        raise AssertionError("архив распаковывается на диск")

    monkeypatch.setattr(zipfile.ZipFile, "extract", no_extract)
    monkeypatch.setattr(zipfile.ZipFile, "extractall", no_extract)
    before = set(tmp_path.rglob("*"))
    tracemalloc.start()
    try:
        build(
            manifest(sha),
            archive,
            tmp_path / "out" / "polities.sqlite",
            tmp_path / "out" / "labels.ru.json",
            fetch_json=FakeWikidata({}),
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < size / 2, (peak, size)
    created = {p for p in set(tmp_path.rglob("*")) - before if p.is_file()}
    assert {p.name for p in created} <= {"polities.sqlite", "labels.ru.json"}, created
    assert events.one("knowledge.polities.built")["polities"] == 1200


@req(GEO, BUILD, invariant="при сбое сборки прежний артефакт остаётся прежним (атомарная замена)")
def test_failed_build_keeps_artifact(tmp_path, events):
    code, out, labels, _ = run_build(tmp_path, "europe.geojson")
    assert code == 0
    before = hashlib.sha256(out.read_bytes()).hexdigest()
    # Архив с верной суммой в манифесте, но GeoJSON обрывается на середине.
    text = (FIXTURES / "europe.geojson").read_text(encoding="utf-8")
    broken = write_geojson(tmp_path / "unused.geojson", [])
    broken.write_text(text[: len(text) // 2], encoding="utf-8")
    archive, sha = make_archive(tmp_path / "src2", broken)
    events.clear()
    with pytest.raises(Exception):  # noqa: B017 — любой сбой, важен итог на диске
        build(manifest(sha), archive, out, labels, fetch_json=FakeWikidata())
    assert hashlib.sha256(out.read_bytes()).hexdigest() == before
    assert sorted(p.name for p in out.parent.iterdir() if p.name.startswith(".")) == []
    events.assert_none("knowledge.polities.built")


@req(GEO, BUILD, invariant="при неверной сумме артефакт не создаётся, код выхода ненулевой")
def test_checksum_mismatch_no_artifact_created(tmp_path, events):
    archive, _sha = make_archive(tmp_path / "src")
    m = write_manifest(tmp_path / "m.yaml", manifest("0" * 64))
    out = tmp_path / "polities.sqlite"
    code = main(
        [
            "--manifest",
            str(m),
            "build",
            "--archive",
            str(archive),
            "--out",
            str(out),
            "--labels",
            str(tmp_path / "l.json"),
        ],
        fetch_json=FakeWikidata(),
    )
    assert code != 0
    assert not out.exists()
    assert events.one("knowledge.polities.rejected")["code"] == "checksum_mismatch"
    events.assert_none("knowledge.polities.built")


@req(GEO, BUILD, invariant="fetch сверяет SHA-256: при расхождении загруженный файл удаляется")
def test_fetch_mismatch_deletes_download(tmp_path, events):
    import httpx

    body = b"PK-fake-archive" * 100
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=body)

    m = manifest("f" * 64)
    dest = tmp_path / "data" / "cliopatria.geojson.zip"
    with pytest.raises(Exception):  # noqa: B017
        fetch(m, dest, transport=httpx.MockTransport(handler))
    assert not dest.exists()
    assert list(dest.parent.iterdir()) == []
    assert calls == [m["download"]["url"]]
    assert events.one("knowledge.polities.rejected")["code"] == "checksum_mismatch"
    good = manifest(hashlib.sha256(body).hexdigest())
    events.clear()
    path, digest = fetch(good, dest, transport=httpx.MockTransport(handler))
    assert path.read_bytes() == body and digest == hashlib.sha256(body).hexdigest()
    events.assert_none("knowledge.polities.rejected")


@req(
    GEO,
    BUILD,
    invariant="метаданные артефакта: версия формата, датасета, SHA-256 архива, атрибуция, параметры",
)
def test_artifact_metadata(tmp_path, events):
    code, out, _, _ = run_build(tmp_path, "europe.geojson")
    assert code == 0
    meta = artifact_meta(out)
    archive = tmp_path / "src" / "cliopatria.geojson.zip"
    assert meta["dataset_version"] == "v9.9.9-test"
    assert meta["sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert meta.get("format_version")
    source = json.loads(meta["source"])
    assert source["title"] == "Cliopatria"
    assert source["authors"] == ["Ed Chalstrey", "James Bennett"]
    assert json.loads(meta["build"]) == {
        "tolerance_deg": 0.05,
        "precision": 2,
        "min_ring_deg2": 0.01,
    }
    conn = sqlite3.connect(out)
    try:
        idx = [r[0] for r in conn.execute("SELECT sql FROM sqlite_master WHERE type='index'")]
    finally:
        conn.close()
    assert any("from_year" in (s or "") for s in idx), idx
    assert events.one("knowledge.polities.built")["dataset_version"] == "v9.9.9-test"


# --- Пределы исторического слоя: замер на фикстуре -------------------------------------


@req(GEO, LIMITS, scenario="Замер на фикстуре")
def test_measure_on_fixture(tmp_path, events, onto):
    from fastapi.testclient import TestClient

    from philograph.knowledge.app import build_app

    code, out, _, _ = run_build(tmp_path, "europe.geojson")
    assert code == 0
    events.clear()
    m = write_manifest(
        tmp_path / "manifest.yaml", {**manifest("0" * 64), "control_years": [1650, 1800, -3500]}
    )
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(["--manifest", str(m), "measure", "--db", str(out)])
    assert code == 0
    result = json.loads(buf.getvalue())
    client = TestClient(build_app(onto.statements, polity_layer=PolityLayer(out, cache_size=0)))
    assert [r["year"] for r in result["years"]] == [1650, 1800, -3500]
    for row in result["years"]:
        r = client.get("/v1/map/polities", params={"year": str(row["year"])})
        assert r.status_code == 200
        data = r.json()
        assert row["polities"] == len(data["polities"])
        assert row["ru"] == sum(1 for p in data["polities"] if p["name_status"] == "ru")
        assert row["bytes"] == len(r.content)
        assert row["gzip_bytes"] == len(gzip.compress(r.content, 9))
        assert row["inactive"] == 0 and row["full_sphere"] == 0
    total = sum(r["polities"] for r in result["years"])
    assert result["ru_share"] == pytest.approx(
        sum(r["ru"] for r in result["years"]) / total, abs=1e-4
    )
    ev = events.one("knowledge.polities.measured")
    assert ev["years"] == 3
    assert ev["ru_share"] == result["ru_share"]
    assert ev["max_gzip_bytes"] == max(r["gzip_bytes"] for r in result["years"])


@req(
    GEO,
    LIMITS,
    invariant="measure --all-intervals: максимум размера по всем интервалам постоянного набора",
)
def test_measure_all_intervals_max(tmp_path, events):
    code, out, _, _ = run_build(tmp_path, "europe.geojson")
    assert code == 0
    events.clear()
    result = measure(out, [1650], all_intervals=True)
    # Независимо: первый год каждого интервала — границы строк фикстуры.
    starts = sorted(
        {p["FromYear"] for p in fixture_rows()} | {p["ToYear"] + 1 for p in fixture_rows()}
    )
    layer = PolityLayer(out, cache_size=0)
    sizes = {}
    for y in starts:
        body = layer.serve(y)
        data = json.loads(body)
        # тело замера — с cached=false; длина gzip та же функция, что у эндпоинта
        sizes[y] = len(gzip.compress(body, 9))
        assert all(p["from"] <= y <= p["to"] for p in data["polities"])
    assert result["max_gzip_bytes"] == max(sizes.values())
    assert result["max_gzip_year"] in [y for y, s in sizes.items() if s == max(sizes.values())]
    ev = events.one("knowledge.polities.measured")
    assert ev["max_gzip_bytes"] == result["max_gzip_bytes"]
    assert ev["inactive"] == 0 and ev["full_sphere"] == 0


@req(GEO, LIMITS, invariant="full_sphere считает многоугольники со сферической площадью ≥ 2π")
def test_measure_detects_full_sphere(tmp_path, events):
    # Артефакт с неверно ориентированным кольцом подложен вручную: measure обязан его увидеть.
    code, out, _, _ = run_build(tmp_path, "europe.geojson")
    assert code == 0
    conn = sqlite3.connect(out)
    (row, geom) = conn.execute(
        "SELECT row, geometry FROM polity_rows WHERE original = 'Ottoman Empire'"
    ).fetchone()
    g = json.loads(geom)
    g["coordinates"] = [ring[::-1] for ring in g["coordinates"]]
    conn.execute("UPDATE polity_rows SET geometry = ? WHERE row = ?", (json.dumps(g), row))
    conn.commit()
    conn.close()
    assert sphere_area(g["coordinates"]) >= 2 * math.pi
    events.clear()
    result = measure(out, [1650])
    assert result["full_sphere"] == 1
    assert events.one("knowledge.polities.measured")["full_sphere"] == 1


# --- Атрибуция: документация и манифест ------------------------------------------------


@req(GEO, ATTR, scenario="Документация и манифест")
def test_docs_manifest_artifact_agree(tmp_path, events):
    doc = (ROOT / "docs" / "product" / "system-design.md").read_text(encoding="utf-8")
    real = yaml.safe_load((ROOT / "sources" / "cliopatria.yaml").read_text(encoding="utf-8"))
    assert "Cliopatria" in doc
    assert "CC BY 4.0" in doc
    assert real["zenodo"]["doi"] in doc
    assert real["version"] in doc
    for author in real["authors"]:
        assert author in doc, author
    # Метаданные артефакта фикстуры совпадают с её манифестом.
    code, out, _, _ = run_build(tmp_path, "europe.geojson")
    assert code == 0
    fixture_manifest = yaml.safe_load((FIXTURES / "manifest.yaml").read_text(encoding="utf-8"))
    source = json.loads(artifact_meta(out)["source"])
    assert source["authors"] == fixture_manifest["authors"]
    assert source["version"] == fixture_manifest["version"]
    assert source["license"] == "CC BY 4.0"
    assert source["license_url"] == "https://creativecommons.org/licenses/by/4.0/"
    # Манифест фикстуры повторяет поля атрибуции настоящего (кроме версии).
    for key in ("title", "publisher", "authors", "license", "license_url"):
        assert fixture_manifest[key] == real[key], key
    assert entities()  # словарь фикстур на месте
    # Метаданные реального артефакта (вне git) — если он собран, те же значения.
    real_db = ROOT / "data" / "cliopatria" / "polities.sqlite"
    if real_db.exists():
        rs = json.loads(artifact_meta(real_db)["source"])
        assert rs["version"] == real["version"] and rs["authors"] == real["authors"]
