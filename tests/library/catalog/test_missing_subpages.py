"""chapter-reading «Необработанные части в тексте»: неоцифрованная подстраница Wikisource —
глава-заглушка, а не пропуск."""

from __future__ import annotations

from urllib.parse import quote

import pytest

from philograph.library.catalog.adapters import Wikisource
from philograph.library.catalog.fetcher import missing_page

req = pytest.mark.req
CR = "chapter-reading"
HOST = "ru.wikisource.org"
PAGE = "Опыт о разуме"


def rest(page: str) -> str:
    return f"https://{HOST}/api/rest_v1/page/html/{quote(page.replace(' ', '_'), safe='')}"


def html(title: str, body: str) -> bytes:
    head = f'<meta charset="utf-8"/><title>{title}</title>'
    return f"<html><head>{head}</head><body>{body}</body></html>".encode()


def site(env) -> None:
    first = f"{PAGE}/Глава 1"
    env.web.routes[rest(PAGE)] = (
        200,
        html(
            PAGE,
            "<p>Оглавление.</p>"
            f'<a href="./{quote(first.replace(" ", "_"))}">Глава 1</a>'
            f'<a href="./{quote((PAGE + "/Глава 2").replace(" ", "_"))}'
            '?action=edit&amp;redlink=1">Глава 2</a>',
        ),
    )
    paragraphs = "".join(
        f"<p>Абзац {i}: всякое знание начинается с опыта, но не всё происходит из опыта.</p>"
        for i in range(60)
    )
    env.web.routes[rest(first)] = (200, html(first, paragraphs))


@req(CR, "Необработанные части в тексте")
def test_red_link_recorded_as_missing_subpage(env):
    site(env)
    files = Wikisource().files(HOST, PAGE, env.service.fetcher)
    assert [(f["name"], bool(f.get("missing"))) for f in files] == [
        (PAGE, False),
        (f"{PAGE}/Глава 1", False),
        (f"{PAGE}/Глава 2", True),
    ]
    stub = missing_page(f"{PAGE}/Глава 2")
    assert b'data-philograph="missing"' in stub and "Глава 2".encode() in stub


@req(CR, "Необработанные части в тексте")
def test_missing_subpage_becomes_placeholder_chapter(env):
    site(env)
    files = Wikisource().files(HOST, PAGE, env.service.fetcher)
    entry = env.entry("ws-essay", adapter="wikisource")
    entry["harvested"]["files"] = files
    entry["harvested"]["metadata"]["language"] = "ru"
    entry["harvested"]["metadata"]["title"] = PAGE
    outcome = env.sync("ws-essay")["ws-essay"]
    assert outcome.outcome == "published", outcome
    source = env.registry.get(outcome.source_id)
    doc = env.registry.load_document(source.published_version)
    sections = {s.title: s for s in doc.walk()}
    assert "Глава 1" in sections and "Глава 2" in sections
    missing = sections["Глава 2"].blocks
    assert [(b.kind, b.detail) for b in missing] == [("unrendered", "глава не оцифрована на сайте")]
    assert any("Абзац 5" in b.text for b in sections["Глава 1"].blocks)
