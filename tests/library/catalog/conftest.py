"""Фикстуры каталога: поддельные сайты через httpx.MockTransport, каталог во временной папке."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

from philograph.library import schema
from philograph.library.catalog import model
from philograph.library.catalog.fetcher import CatalogFetch, Fetcher, FetchSettings
from philograph.library.catalog.service import CatalogService
from philograph.library.processing import Pipeline, PipelineSettings
from philograph.library.registry import Registry
from philograph.operator.access import ActionLog
from philograph.operator.access import migrations as operator_migrations
from philograph.platform.files import FileStore

FIXTURES = Path(__file__).parent / "fixtures"
REPO_SOURCES = Path(__file__).resolve().parents[3] / "sources"


def book(*paragraphs: str, header: str = "Release date: 2001", heading: str = "Chapter I") -> bytes:
    """Текст в обёртке Project Gutenberg."""
    body = "\n\n".join(paragraphs)
    return (
        f"The Project Gutenberg eBook\n{header}\n\n"
        "*** START OF THE PROJECT GUTENBERG EBOOK TEST ***\n\n"
        f"{heading}\n\n{body}\n\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK TEST ***\n\nLicense text.\n"
    ).encode()


PARAGRAPHS = [
    f"Paragraph number {i} says that all knowledge begins with experience." for i in range(60)
]


@dataclass
class Web:
    """Поддельный интернет: адрес → (код, тело, заголовки) или список ответов по очереди."""

    routes: dict[str, Any] = field(default_factory=dict)
    seen: list[httpx.Request] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        url = str(request.url)
        route = self.routes.get(url)
        if route is None:
            return httpx.Response(404, request=request)
        if isinstance(route, list):
            route = route.pop(0) if len(route) > 1 else route[0]
        if callable(route):
            return route(request)
        status, body, headers = route if len(route) == 3 else (*route, {})
        return httpx.Response(status, content=body, headers=headers, request=request)

    def hits(self, url: str) -> int:
        return sum(1 for r in self.seen if str(r.url) == url)


@dataclass
class Env:
    web: Web
    catalog: model.Catalog
    service: CatalogService
    registry: Registry
    sleeps: list[float]

    def entry(
        self, entry_id: str = "test-book", url: str = "https://books.example/b.txt", **extra
    ) -> dict:
        data = {
            "id": entry_id,
            "landing_url": f"https://books.example/{entry_id}",
            "adapter": "direct",
            "kind": "primary",
            "section": "epistemology",
            "harvested": {
                "at": "2026-11-06T00:00:00",
                "adapter_version": 1,
                "metadata": {
                    "title": "An Essay on Knowledge",
                    "authors": [{"name": "John Locke", "death_year": 1704, "wikidata": None}],
                    "language": "en",
                    "year": 1690,
                    "translator": None,
                },
                "files": [{"name": "b.txt", "url": url, "clean": "gutenberg"}],
                "license_hint": "Public domain in the USA.",
            },
            "override": {},
            "license": {"kind": "public-domain", "basis": "public_domain", "evidence": "ум. 1704"},
            "review": {"status": "approved", "by": "test", "at": None, "note": None},
            "publish": "auto",
        }
        data.update(extra)
        self.catalog.entries.append(data)
        return data

    def sync(self, *ids: str):
        outcomes = self.service.sync(list(ids) or None)
        return {o.catalog_id: o for o in outcomes}


@pytest.fixture
def web() -> Web:
    return Web()


@pytest.fixture
def env(engine_for, clock, tmp_path, web) -> Env:
    engine = engine_for(schema.migrations, operator_migrations)
    registry = Registry(engine, clock, actions=ActionLog(engine, clock))
    folder = tmp_path / "sources"
    folder.mkdir()
    for name in ("catalog.schema.json", "licenses.yaml"):
        shutil.copy(REPO_SOURCES / name, folder / name)
    catalog = model.Catalog(folder / "catalog.yaml", [])
    sleeps: list[float] = []
    fetcher = Fetcher(
        FetchSettings(retries=2, backoff=0.5),
        transport=httpx.MockTransport(web.handle),
        sleep=sleeps.append,
        monotonic=lambda: 0.0,
    )
    files = FileStore(tmp_path / "files")
    pipeline = Pipeline(
        registry,
        files,
        CatalogFetch(engine, fetcher, files, clock=clock),
        clock=clock,
        settings=PipelineSettings(fetch_retries=0),
    )
    service = CatalogService(catalog, registry, pipeline, fetcher, clock)
    return Env(web, catalog, service, registry, sleeps)
