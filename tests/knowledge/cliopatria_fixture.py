"""Фикстура датасета Cliopatria для тестов (add-historical-polities): архив собирается во
временный каталог из GeoJSON фикстуры, Wikidata — словарь ответов, без сети."""

from __future__ import annotations

import copy
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import yaml

FIXTURES = Path(__file__).parent / "fixtures" / "cliopatria"


def make_archive(dest: Path, geojson: Path | str = "europe.geojson") -> tuple[Path, str]:
    """``cliopatria.geojson.zip`` из файла фикстуры; архив детерминирован (дата записи)."""
    source = Path(geojson) if Path(geojson).is_absolute() else FIXTURES / geojson
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "cliopatria.geojson.zip"
    info = zipfile.ZipInfo("cliopatria.geojson", date_time=(2024, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(info, source.read_bytes())
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def manifest(sha256: str, **build: Any) -> dict[str, Any]:
    data = yaml.safe_load((FIXTURES / "manifest.yaml").read_text(encoding="utf-8"))
    data["download"]["sha256"] = sha256
    data["build"].update(build)
    return data


def entities() -> dict[str, Any]:
    return json.loads((FIXTURES / "labels.json").read_text(encoding="utf-8"))


class FakeWikidata:
    """``Fetch``: адрес ``wbgetentities`` → ответ из словаря записей; запросы запоминаются."""

    def __init__(self, records: dict[str, Any] | None = None) -> None:
        self.records = entities() if records is None else records
        self.calls: list[str] = []

    def __call__(self, url: str) -> dict[str, Any]:
        self.calls.append(url)
        ids = parse_qs(urlsplit(url).query)["ids"][0].split("|")
        out = {}
        for q in ids:
            rec = self.records.get(q)
            out[q] = copy.deepcopy(rec) if rec is not None else {"id": q, "missing": ""}
        return {"entities": out}
