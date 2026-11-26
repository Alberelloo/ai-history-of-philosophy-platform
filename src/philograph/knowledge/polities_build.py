"""Сборка исторических границ из датасета Cliopatria (add-historical-polities).

Команды (манифест — ``sources/cliopatria.yaml``, данные — ``data/cliopatria/``, вне git):

- ``fetch [--record]`` — скачать ``cliopatria.geojson.zip`` закреплённой версии и сверить
  SHA-256 с манифестом (``--record`` печатает сумму для манифеста, без сверки);
- ``build [--offline] [--refresh-labels]`` — артефакт SQLite для ``knowledge/polities.py``;
- ``measure [--years …] [--all-intervals]`` — пределы H2 (размер слоя, gzip -9) и H3 (доля
  русских названий) по артефакту, плюс счётчики ``inactive`` (H1) и ``full_sphere``.

Сборка читает GeoJSON потоково прямо из zip (``ijson``), в памяти — одна запись. Геометрия:
``make_valid`` → ``simplify(preserve_topology=True)`` → сетка ``10^-precision``
(``set_precision`` сохраняет валидность) → отбор многоугольников по площади, самый большой
остаётся всегда → внешнее кольцо по часовой стрелке (сферический обход d3-geo).

Русские названия — только из записи Wikidata того же QID: метка ``ru``, иначе заголовок
статьи ``ruwiki`` без одного завершающего уточнения в скобках, иначе оригинальное ``Name``.
Модель не вызывается. Сеть — только ``wikidata.http_fetch`` (метки) и ``fetch`` (архив).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import tempfile
import time
import unicodedata
import zipfile
from collections.abc import Callable, Iterable, Iterator
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import yaml

from philograph.knowledge import wikidata
from philograph.knowledge.polities import (
    DEFAULT_PATH,
    FORMAT_VERSION,
    SCHEMA,
    PolityLayer,
    response_body,
)
from philograph.platform import events

MANIFEST = Path("sources/cliopatria.yaml")
DATA_DIR = Path("data/cliopatria")
LABELS_FILE = "labels.ru.json"
DOWNLOAD_HOSTS = frozenset({"raw.githubusercontent.com"})
NAME_MAX = 200
INSERT_BATCH = 200
TRAILING_NOTE = re.compile(r"\s*\([^()]*\)\s*$")

events.define(
    "knowledge.polities.built",
    "info",
    "Собран артефакт исторических границ",
    required=(
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
    ),
    optional=("label_failures", "tiny_kept"),
)
events.define(
    "knowledge.polities.measured",
    "info",
    "Замер слоя образований на контрольных годах",
    required=("years", "max_gzip_bytes", "max_gzip_year", "ru_share", "inactive", "full_sphere"),
)


class BuildError(Exception):
    """Сборка невозможна: контрольная сумма, манифест, архив."""


# --- манифест и файлы ------------------------------------------------------------------


def load_manifest(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in ("title", "publisher", "version", "authors", "license", "download", "build"):
        if not data.get(key):
            raise BuildError(f"в манифесте нет поля {key}")
    return data


def source_block(manifest: dict[str, Any]) -> dict[str, Any]:
    """Блок атрибуции ответа ``/map/polities`` — из манифеста, через метаданные артефакта."""
    links = {
        "license_url": manifest.get("license_url"),
        "url": (manifest.get("zenodo") or {}).get("url") or manifest.get("repository"),
    }
    for key, value in links.items():
        if value is not None and not (isinstance(value, str) and value.startswith("https://")):
            raise BuildError(f"ссылка атрибуции {key} не https: {value!r}")
    return {
        "title": manifest["title"],
        "publisher": manifest["publisher"],
        "authors": list(manifest["authors"]),
        "version": manifest["version"],
        "license": manifest.get("license_title", "CC BY 4.0"),
        "license_url": links["license_url"],
        "url": links["url"],
    }


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_download(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in DOWNLOAD_HOSTS:
        raise BuildError(f"адрес загрузки вне разрешённых: {parts.hostname}")


def fetch(
    manifest: dict[str, Any],
    dest: Path,
    *,
    record: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> tuple[Path, str]:
    """Скачать архив во временный файл, сверить SHA-256 и переименовать в ``dest``."""
    url = manifest["download"]["url"]
    _check_download(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".fetch-")
    h = hashlib.sha256()
    try:
        with (
            os.fdopen(fd, "wb") as out,
            httpx.Client(
                transport=transport,
                timeout=60,
                follow_redirects=False,
                headers={"User-Agent": wikidata.USER_AGENT},
            ) as client,
            client.stream("GET", url) as response,
        ):
            if response.status_code != 200:
                raise BuildError(f"загрузка: {response.status_code}")
            for chunk in response.iter_bytes(1 << 20):
                h.update(chunk)
                out.write(chunk)
        digest = h.hexdigest()
        expected = manifest["download"].get("sha256")
        if not record and digest != expected:
            events.emit("knowledge.polities.rejected", code="checksum_mismatch")
            raise BuildError(f"SHA-256 архива {digest} не совпадает с манифестом")
        os.replace(tmp, dest)
        return dest, digest
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# --- названия --------------------------------------------------------------------------


def accept_name(raw: Any, *, sitelink: bool = False) -> str | None:
    """Метка или заголовок, пригодные для показа; иначе ``None``. У заголовка снимается одно
    завершающее уточнение в скобках («Речь Посполитая (1569—1795)» → «Речь Посполитая»)."""
    if not isinstance(raw, str):
        return None
    text = TRAILING_NOTE.sub("", raw, count=1) if sitelink else raw
    text = text.strip()
    if not 1 <= len(text) <= NAME_MAX:
        return None
    if any(unicodedata.category(ch) == "Cc" for ch in text):
        return None
    return text


def name_for(original: str, qid: str | None, names: dict[str, Any]) -> tuple[str, str, str]:
    """``(name, name_status, name_source)`` по правилу «Русские названия образований»."""
    entry = names.get(qid) if qid else None
    if isinstance(entry, dict):
        label = accept_name(entry.get("label"))
        if label:
            return label, "ru", "label"
        title = accept_name(entry.get("sitelink"), sitelink=True)
        if title:
            return title, "ru", "sitelink"
    return original, "original", "original"


def load_labels(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def save_labels(path: Path, labels: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(labels, ensure_ascii=False, indent=0, sort_keys=True), "utf-8")
    os.replace(tmp, path)


def fetch_labels(
    qids: Iterable[str], cache: dict[str, Any], fetch_json: wikidata.Fetch | None
) -> tuple[int, int]:
    """Дозапросить метки QID, которых нет в кэше. ``(запросов, сбоев пачек)``."""
    missing = sorted(q for q in set(qids) if q not in cache)
    if fetch_json is None or not missing:
        return 0, 0
    requests = failures = 0
    for i in range(0, len(missing), wikidata.LABEL_BATCH):
        batch = missing[i : i + wikidata.LABEL_BATCH]
        try:
            got, n = wikidata.labels(batch, "ru", fetch_json)
        except wikidata.WikidataError:
            requests += 1
            failures += 1  # без записи в кэш: следующая сборка спросит снова
            continue
        requests += n
        cache.update(got)
    return requests, failures


# --- геометрия -------------------------------------------------------------------------


def _count(coords: Any) -> int:
    if not coords:
        return 0
    if isinstance(coords[0], (int, float)):
        return 1
    return sum(_count(c) for c in coords)


def _polygons(geom: Any) -> list[Any]:
    from shapely.geometry import MultiPolygon, Polygon

    if isinstance(geom, Polygon):
        return [] if geom.is_empty else [geom]
    if isinstance(geom, MultiPolygon):
        return [g for g in geom.geoms if not g.is_empty]
    if hasattr(geom, "geoms"):
        return [p for g in geom.geoms for p in _polygons(g)]
    return []


def _round(coords: Any, precision: int) -> Any:
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], precision), round(coords[1], precision)]
    return [_round(c, precision) for c in coords]


def _grid_cell(x: float, y: float, precision: int) -> Any:
    """Клетка сетки ``10^-precision``, содержащая точку: наименьший невырожденный
    многоугольник на этой сетке."""
    from shapely.geometry import box

    scale = 10**precision
    ix, iy = math.floor(x * scale), math.floor(y * scale)
    ix = min(max(ix, -180 * scale), 180 * scale - 1)
    iy = min(max(iy, -90 * scale), 90 * scale - 1)
    return box(ix / scale, iy / scale, (ix + 1) / scale, (iy + 1) / scale)


def simplify_geometry(
    geometry: dict[str, Any], tolerance: float, precision: int, min_ring: float
) -> tuple[dict[str, Any], int, bool]:
    """Упрощённая геометрия GeoJSON, число вершин после и признак «оставлен только самый
    большой многоугольник (или клетка сетки у его центроида), потому что остальное меньше
    порога или выродилось на сетке».

    Координаты всегда на сетке ``10^-precision``. Пустая исходная геометрия —
    ``ValueError`` (запись не по формату); вырождение на сетке исключений не даёт."""
    import shapely
    from shapely.geometry import MultiPolygon, Polygon, mapping, shape
    from shapely.geometry.polygon import orient

    source = _polygons(shapely.make_valid(shape(geometry)))
    if not source:
        raise ValueError("пустая геометрия")
    simplified = (
        _polygons(
            shapely.make_valid(MultiPolygon(source).simplify(tolerance, preserve_topology=True))
        )
        or source
    )
    gridded = _polygons(shapely.set_precision(MultiPolygon(simplified), 10.0**-precision))

    def without_small_holes(p: Any) -> Any:
        holes = [r for r in p.interiors if Polygon(r).area >= min_ring]
        return p if len(holes) == len(p.interiors) else Polygon(p.exterior, holes)

    kept = [without_small_holes(p) for p in gridded if p.area >= min_ring]
    tiny = False
    if not kept:
        tiny = True
        cell = 10.0 ** (-2 * precision)
        biggest = max(gridded, key=lambda p: p.area) if gridded else None
        if biggest is not None and biggest.area >= cell * (1 - 1e-9):
            kept = [without_small_holes(biggest)]  # всё меньше порога: самый большой
        else:  # выродился на сетке (пуст или меньше клетки): клетка у центроида
            c = max(simplified, key=lambda p: p.area).centroid
            kept = [_grid_cell(c.x, c.y, precision)]
    kept = [orient(p, sign=-1.0) for p in kept]
    if len(kept) == 1:
        out = {"type": "Polygon", "coordinates": _round(mapping(kept[0])["coordinates"], precision)}
    else:
        out = {
            "type": "MultiPolygon",
            "coordinates": [_round(mapping(p)["coordinates"], precision) for p in kept],
        }
    return out, _count(out["coordinates"]), tiny


def spherical_area(polygon: list[list[list[float]]]) -> float:
    """Площадь многоугольника на единичной сфере по правилу d3-geo ``geoArea``: кольцо
    против часовой стрелки даёт «сферу минус многоугольник» (≥ 2π)."""
    total = 0.0
    for ring in polygon:
        pts = list(ring)
        if not pts:
            continue
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        lam0 = math.radians(pts[0][0])
        phi = math.radians(pts[0][1]) / 2 + math.pi / 4
        cos0, sin0 = math.cos(phi), math.sin(phi)
        for lon, lat in pts[1:]:
            lam = math.radians(lon)
            phi = math.radians(lat) / 2 + math.pi / 4
            d = lam - lam0
            sd = 1.0 if d >= 0 else -1.0
            ad = sd * d
            cos1, sin1 = math.cos(phi), math.sin(phi)
            k = sin0 * sin1
            total += math.atan2(k * sd * math.sin(ad), cos0 * cos1 + k * math.cos(ad))
            lam0, cos0, sin0 = lam, cos1, sin1
    return 2 * (total + 2 * math.pi if total < 0 else total)


def polygons_of(geometry: dict[str, Any]) -> list[Any]:
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    return list(geometry["coordinates"])


# --- сборка ----------------------------------------------------------------------------


def shapely_errors() -> type[Exception]:
    """Ошибка GEOS на испорченной геометрии записи — запись не по формату, не сбой сборки."""
    from shapely.errors import GEOSException

    return GEOSException


def polity_id(name: str) -> str:
    return hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]


def _records(archive: Path, member: str) -> Iterator[dict[str, Any]]:
    import ijson

    with zipfile.ZipFile(archive) as z, z.open(member) as f:
        yield from ijson.items(f, "features.item", use_float=True)


def _valid_record(feature: dict[str, Any]) -> tuple[str, int, int, dict[str, Any]] | None:
    p = feature.get("properties") or {}
    name, start, end = p.get("Name"), p.get("FromYear"), p.get("ToYear")
    geometry = feature.get("geometry") or {}
    if not isinstance(name, str) or not name.strip():
        return None
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (start, end)):
        return None
    if start > end or geometry.get("type") not in ("Polygon", "MultiPolygon"):
        return None
    return name, start, end, geometry


def build(
    manifest: dict[str, Any],
    archive: Path,
    out: Path,
    labels_path: Path,
    *,
    fetch_json: wikidata.Fetch | None = None,
    offline: bool = False,
    refresh_labels: bool = False,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Собрать артефакт; вернуть отчёт (поля события ``knowledge.polities.built``)."""
    started = clock()
    expected = manifest["download"].get("sha256")
    digest = sha256_file(archive)
    if digest != expected:
        events.emit("knowledge.polities.rejected", code="checksum_mismatch")
        raise BuildError(f"SHA-256 архива {digest} не совпадает с манифестом")
    params = manifest["build"]
    tolerance = float(params["tolerance_deg"])
    precision = int(params["precision"])
    min_ring = float(params["min_ring_deg2"])
    member = manifest["download"].get("member", "cliopatria.geojson")

    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=out.parent, prefix=".build-", suffix=".sqlite")
    os.close(fd)
    tmp = Path(tmp_name)
    report = {
        "dataset_version": manifest["version"],
        "rows": 0,
        "polities": 0,
        "skipped_relation": 0,
        "skipped_invalid": 0,
        "qids": 0,
        "ru_labels": 0,
        "ru_sitelinks": 0,
        "label_requests": 0,
        "label_failures": 0,
        "intervals": 0,
        "vertices_in": 0,
        "vertices_out": 0,
        "tiny_kept": 0,
        "seconds": 0.0,
    }
    try:
        conn = sqlite3.connect(tmp)
        conn.executescript(SCHEMA)
        batch: list[tuple] = []
        row_qids: list[tuple[int, str, str | None]] = []
        bounds: set[int] = set()
        for feature in _records(archive, member):
            report["rows"] += 1
            props = feature.get("properties") or {}
            if props.get("Type") != "POLITY":
                report[
                    "skipped_relation" if props.get("Type") == "RELATION" else "skipped_invalid"
                ] += 1
                continue
            valid = _valid_record(feature)
            if valid is None:
                report["skipped_invalid"] += 1
                continue
            name, start, end, geometry = valid
            try:
                simple, vout, tiny = simplify_geometry(geometry, tolerance, precision, min_ring)
            except (ValueError, TypeError, shapely_errors()):
                report["skipped_invalid"] += 1
                continue
            report["vertices_in"] += _count(geometry.get("coordinates") or [])
            report["vertices_out"] += vout
            report["tiny_kept"] += int(tiny)
            qid = props.get("Wikidata")
            qid = qid if isinstance(qid, str) and wikidata.QID.fullmatch(qid) else None
            area = props.get("Area")
            area = (
                float(area)
                if isinstance(area, (int, float)) and not isinstance(area, bool)
                else 0.0
            )
            report["polities"] += 1
            row = report["polities"]
            bounds.update((start, end + 1))
            row_qids.append((row, name, qid))
            batch.append(
                (
                    row,
                    polity_id(name),
                    start,
                    end,
                    name,
                    "original",
                    "original",
                    name,
                    qid,
                    area,
                    json.dumps(simple, separators=(",", ":")),
                )
            )
            if len(batch) >= INSERT_BATCH:
                conn.executemany("INSERT INTO polity_rows VALUES (?,?,?,?,?,?,?,?,?,?,?)", batch)
                batch.clear()
        if batch:
            conn.executemany("INSERT INTO polity_rows VALUES (?,?,?,?,?,?,?,?,?,?,?)", batch)

        qids = {q for _, _, q in row_qids if q}
        report["qids"] = len(qids)
        cache = {} if refresh_labels else load_labels(labels_path)
        requests, failures = fetch_labels(qids, cache, None if offline else fetch_json)
        report["label_requests"], report["label_failures"] = requests, failures
        if requests:
            save_labels(labels_path, cache)
        updates = []
        for row, original, qid in row_qids:
            name, status, source = name_for(original, qid, cache)
            if source == "label":
                report["ru_labels"] += 1
            elif source == "sitelink":
                report["ru_sitelinks"] += 1
            if status != "original":
                updates.append((name, status, source, row))
        conn.executemany(
            "UPDATE polity_rows SET name = ?, name_status = ?, name_source = ? WHERE row = ?",
            updates,
        )
        report["intervals"] = len(bounds)
        report["seconds"] = round(clock() - started, 3)
        meta = {
            "format_version": str(FORMAT_VERSION),
            "dataset_version": manifest["version"],
            "sha256": digest,
            "source": json.dumps(source_block(manifest), ensure_ascii=False, separators=(",", ":")),
            "build": json.dumps(params, sort_keys=True),
            "report": json.dumps(report, sort_keys=True),
        }
        conn.executemany("INSERT INTO meta VALUES (?, ?)", meta.items())
        conn.commit()
        conn.close()
        os.chmod(tmp, 0o644)  # mkstemp даёт 0600: сервис может работать от другого пользователя
        os.replace(tmp, out)
    finally:
        if tmp.exists():
            tmp.unlink()
    events.emit("knowledge.polities.built", **report)
    return report


# --- замер -----------------------------------------------------------------------------


def change_points(db: Path) -> list[int]:
    """Первые годы всех интервалов постоянного набора внутри лет датасета."""
    conn = sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT from_year FROM polity_rows UNION SELECT to_year + 1 FROM polity_rows"
        ).fetchall()
    finally:
        conn.close()
    return sorted(r[0] for r in rows)


def measure_year(layer: PolityLayer, year: int) -> dict[str, Any]:
    part, source = layer.compute(year)
    body = response_body(year, part, source, cached=False)
    polities = json.loads(part.body)
    inactive = sum(1 for p in polities if not p["from"] <= year <= p["to"])
    full = sum(
        1
        for p in polities
        for poly in polygons_of(p["geometry"])
        if spherical_area(poly) >= 2 * math.pi
    )
    return {
        "year": year,
        "polities": part.polities,
        "ru": part.ru,
        "bytes": len(body),
        "gzip_bytes": len(gzip.compress(body, 9)),
        "inactive": inactive,
        "full_sphere": full,
    }


def measure(db: Path, years: list[int], *, all_intervals: bool = False) -> dict[str, Any]:
    layer = PolityLayer(db)
    per_year = [measure_year(layer, y) for y in years]
    total = sum(r["polities"] for r in per_year)
    result: dict[str, Any] = {
        "years": per_year,
        "ru_share": round(sum(r["ru"] for r in per_year) / total, 4) if total else 0.0,
        "inactive": sum(r["inactive"] for r in per_year),
        "full_sphere": sum(r["full_sphere"] for r in per_year),
    }
    sized = per_year
    if all_intervals:
        sized = [measure_year(layer, y) for y in change_points(db)]
        result["intervals"] = len(sized)
        result["intervals_inactive"] = sum(r["inactive"] for r in sized)
        result["intervals_full_sphere"] = sum(r["full_sphere"] for r in sized)
    top = max(sized, key=lambda r: (r["gzip_bytes"], -r["year"])) if sized else None
    result["max_gzip_bytes"] = top["gzip_bytes"] if top else 0
    result["max_gzip_year"] = top["year"] if top else None
    events.emit(
        "knowledge.polities.measured",
        years=len(per_year),
        max_gzip_bytes=result["max_gzip_bytes"],
        max_gzip_year=result["max_gzip_year"],
        ru_share=result["ru_share"],
        inactive=result["inactive"],
        full_sphere=result["full_sphere"],
    )
    return result


# --- командная строка ------------------------------------------------------------------


def _json_error() -> type[Exception]:
    try:
        import ijson
    except ImportError:  # без extra geo-build: build всё равно не запустится
        return ValueError
    return ijson.JSONError


def main(argv: list[str] | None = None, *, fetch_json: wikidata.Fetch | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="python -m philograph.knowledge.polities_build",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch", help="скачать архив и сверить SHA-256")
    f.add_argument("--dest", type=Path, default=None)
    f.add_argument("--record", action="store_true", help="напечатать сумму без сверки")
    b = sub.add_parser("build", help="собрать артефакт")
    b.add_argument("--archive", type=Path, default=None)
    b.add_argument(
        "--out", type=Path, default=Path(os.environ.get("PHILOGRAPH_POLITIES_DB", DEFAULT_PATH))
    )
    b.add_argument("--labels", type=Path, default=DATA_DIR / LABELS_FILE)
    b.add_argument("--offline", action="store_true", help="без сети: только кэш меток")
    b.add_argument("--refresh-labels", action="store_true", help="запросить все метки заново")
    m = sub.add_parser("measure", help="пределы H2/H3 по артефакту")
    m.add_argument(
        "--db", type=Path, default=Path(os.environ.get("PHILOGRAPH_POLITIES_DB", DEFAULT_PATH))
    )
    m.add_argument("--years", type=int, nargs="*", default=None)
    m.add_argument("--all-intervals", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        archive_default = DATA_DIR / manifest["download"].get("file", "cliopatria.geojson.zip")
        if args.command == "fetch":
            path, digest = fetch(manifest, args.dest or archive_default, record=args.record)
            print(json.dumps({"file": str(path), "sha256": digest}, ensure_ascii=False))
        elif args.command == "build":
            fetcher = fetch_json or partial(wikidata.http_fetch, wait=time.sleep)
            report = build(
                manifest,
                args.archive or archive_default,
                args.out,
                args.labels,
                fetch_json=fetcher,
                offline=args.offline,
                refresh_labels=args.refresh_labels,
            )
            print(json.dumps(report, ensure_ascii=False))
        else:
            years = args.years if args.years else list(manifest.get("control_years") or [])
            print(
                json.dumps(
                    measure(args.db, years, all_intervals=args.all_intervals), ensure_ascii=False
                )
            )
    except BuildError as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 1
    except (
        OSError,
        zipfile.BadZipFile,
        KeyError,
        httpx.HTTPError,
        ValueError,
        _json_error(),
    ) as exc:
        # Обрезанный или испорченный архив (ijson), нет файла, сбой сети: артефакт не
        # тронут (временный файл удалён), сообщение без трассировки.
        print(f"ошибка: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    events.configure(sinks=[events.json_sink(sys.stderr)])
    sys.exit(main())
