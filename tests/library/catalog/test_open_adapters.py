"""Адаптеры открытых репозиториев: arXiv, PhilArchive, DOAJ (мок-HTTP)."""

from __future__ import annotations

import json

import pytest

from philograph.library.catalog.adapters import Arxiv, Doaj, PhilArchive, suggest_license

req = pytest.mark.req
SC = "source-catalog"

ARXIV_ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Knowledge and Its Limits</title>
    <summary>The paper argues that knowledge is unanalysable.</summary>
    <author><name>Timothy Williamson</name></author>
    <author><name>Jane Doe</name></author>
    <published>2000-10-01T00:00:00Z</published>
  </entry>
</feed>
"""

OAI_DC = (
    b"<OAI-PMH><GetRecord><record><metadata>"
    b'<oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/" '
    b'xmlns:dc="http://purl.org/dc/elements/1.1/">'
    b"<dc:title>On Denoting</dc:title>"
    b"<dc:creator>Bertrand Russell</dc:creator>"
    b"<dc:date>1905</dc:date>"
    b"<dc:description>An analysis of definite descriptions.</dc:description>"
    b"<dc:rights>CC BY 4.0</dc:rights>"
    b"<dc:identifier>https://philarchive.org/archive/RUSOD.pdf</dc:identifier>"
    b"</oai_dc:dc></metadata></record></GetRecord></OAI-PMH>"
)

DOAJ_JSON = {
    "results": [
        {
            "bibjson": {
                "title": "Epistemic Contextualism",
                "author": [{"name": "Stewart Cohen"}],
                "year": 1999,
                "abstract": "A defense of contextualism about knowledge.",
                "license": [{"type": "CC BY"}],
                "link": [{"type": "fulltext", "url": "https://journal.example/article.pdf"}],
            }
        }
    ]
}


@req(SC, "Адаптеры открытых репозиториев")
def test_arxiv_harvest(env):
    api = "https://export.arxiv.org/api/query?id_list=hep-th%2F9901001"
    env.web.routes[api] = (200, ARXIV_ATOM)
    harvest = Arxiv().harvest("https://arxiv.org/abs/hep-th/9901001", env.service.fetcher)
    meta = harvest.metadata
    assert meta["title"] == "Knowledge and Its Limits"
    assert meta["authors"] == [
        {"name": "Timothy Williamson", "death_year": None, "wikidata": None},
        {"name": "Jane Doe", "death_year": None, "wikidata": None},
    ]
    assert meta["year"] == 2000
    assert meta["abstract"].startswith("The paper argues")
    assert harvest.files == [
        {"name": "hep-th/9901001.pdf", "url": "https://arxiv.org/pdf/hep-th/9901001"}
    ]
    assert "arXiv" in harvest.license_hint


@req(SC, "Адаптеры открытых репозиториев")
def test_philarchive_harvest(env):
    identifier = "oai%3Aphilarchive.org%3Arec%2FRUSOD"
    api = (
        f"https://philarchive.org/oai?verb=GetRecord&metadataPrefix=oai_dc&identifier={identifier}"
    )
    env.web.routes[api] = (200, OAI_DC)
    harvest = PhilArchive().harvest("https://philarchive.org/rec/RUSOD", env.service.fetcher)
    meta = harvest.metadata
    assert meta["title"] == "On Denoting"
    assert meta["authors"][0]["name"] == "Bertrand Russell"
    assert meta["year"] == 1905
    assert harvest.files == [
        {"name": "paper.pdf", "url": "https://philarchive.org/archive/RUSOD.pdf"}
    ]
    assert "CC BY 4.0" in harvest.license_hint


@req(SC, "Адаптеры открытых репозиториев")
def test_doaj_harvest(env):
    env.web.routes["https://doaj.org/api/search/articles/abc123"] = (
        200,
        json.dumps(DOAJ_JSON).encode(),
    )
    harvest = Doaj().harvest("https://doaj.org/article/abc123", env.service.fetcher)
    meta = harvest.metadata
    assert meta["title"] == "Epistemic Contextualism"
    assert meta["authors"] == [{"name": "Stewart Cohen", "death_year": None, "wikidata": None}]
    assert meta["year"] == 1999
    assert harvest.files == [{"name": "article.pdf", "url": "https://journal.example/article.pdf"}]
    assert "CC BY" in harvest.license_hint


@req(SC, "Адаптеры открытых репозиториев")
def test_arxiv_license_classified_open(env):
    api = "https://export.arxiv.org/api/query?id_list=hep-th%2F9901001"
    env.web.routes[api] = (200, ARXIV_ATOM)
    harvest = Arxiv().harvest("https://arxiv.org/abs/hep-th/9901001", env.service.fetcher)
    license_ = suggest_license(harvest, 2026)
    assert license_["rights_tier"] == "open_license"
    assert license_["kind"] == "arxiv-non-exclusive"


@req(SC, "Адаптеры открытых репозиториев")
def test_cc_license_classified_open(env):
    from dataclasses import dataclass

    @dataclass
    class Harvest:
        metadata: dict = None
        license_hint: str | None = None

    h = Harvest({"authors": [{"name": "X", "death_year": 1990}]}, "CC BY 4.0")
    license_ = suggest_license(h, 2026)
    assert license_["rights_tier"] == "open_license"
    assert license_["kind"] == "cc-by-4.0"
