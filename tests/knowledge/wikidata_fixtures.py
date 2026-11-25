"""Загрузка Wikidata из файлов ``tests/knowledge/fixtures/wikidata`` — без сети.

``FixtureFetch`` — функция ``wikidata.Fetch`` (адрес → JSON): записи ``entity_<QID>.json``,
поиск — по ``index.json`` («название|язык» → файл; нет — пустой ответ). Записи, которых нет,
и QID из ``failing`` — сбой загрузки (``WikidataError``). Вызовы записываются в ``calls``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from philograph.knowledge.wikidata import WikidataError

FIXTURES = Path(__file__).parent / "fixtures" / "wikidata"


def read(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FixtureFetch:
    def __init__(
        self, extra: dict[str, dict[str, Any]] | None = None, failing: set[str] | None = None
    ) -> None:
        self.extra = extra or {}  # QID → ответ EntityData, поверх файлов
        self.failing = failing or set()
        self.calls: list[str] = []
        self.index = read("index.json")["search"]

    def __call__(self, url: str) -> dict[str, Any]:
        self.calls.append(url)
        parts = urlsplit(url)
        if parts.path.startswith("/wiki/Special:EntityData/"):
            qid = parts.path.rsplit("/", 1)[1].removesuffix(".json")
            if qid in self.failing:
                raise WikidataError("сбой загрузки (фикстура)")
            if qid in self.extra:
                return self.extra[qid]
            path = FIXTURES / f"entity_{qid}.json"
            if not path.exists():
                raise WikidataError("сбой загрузки: 404 (фикстура)")
            return read(path.name)
        if parts.path == "/w/api.php":
            query = parse_qs(parts.query)
            key = f"{query['search'][0]}|{query['language'][0]}"
            return read(self.index[key]) if key in self.index else {"search": []}
        raise AssertionError(f"неожиданный адрес {url}")
