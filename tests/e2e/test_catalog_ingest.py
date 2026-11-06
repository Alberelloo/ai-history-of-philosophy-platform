"""Сквозной путь каталога: сайт с книгой → catalog sync → источник в библиотеке и читалке."""

from __future__ import annotations

import functools
import http.server
import os
import subprocess
import sys
import threading

import pytest
import yaml

from ..helpers import reader_context
from .conftest import ROOT

pytestmark = pytest.mark.e2e
req = pytest.mark.req
SC = "source-catalog"
TITLE = "An Essay on Experience and Habit"
BOOK = (
    "*** START OF THE PROJECT GUTENBERG EBOOK TEST ***\n\n"
    "Chapter I. Of Experience\n\n"
    "All our reasonings concerning matter of fact seem to be founded on the relation of "
    "cause and effect, which custom alone makes us expect.\n\n"
    "Chapter II. Of Habit\n\n"
    "Habit is the great guide of human life, says the philosopher of the quiet library.\n\n"
    "*** END OF THE PROJECT GUTENBERG EBOOK TEST ***\n"
)


@pytest.fixture(scope="module")
def own_stack(tmp_path_factory):
    if os.environ.get("PHILOGRAPH_E2E_URL"):
        pytest.skip("стенд docker compose: команда каталога запускается только у своего стенда")
    if not (ROOT / "web" / "dist" / "index.html").exists():
        pytest.skip("клиент не собран: npm run build в web/")
    import dev_stack

    running = dev_stack.start(tmp_path_factory.mktemp("catalog-stack"))
    yield running
    running.stop()


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("site")
    (root / "book.txt").write_text(BOOK, encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def catalog_cli(stack, catalog, *args) -> str:
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "PHILOGRAPH_DATABASE_URL": f"sqlite:///{(stack.data / 'stack.db').as_posix()}",
        "PHILOGRAPH_FILES_ROOT": str(stack.data / "files"),
    }
    done = subprocess.run(
        [sys.executable, "-m", "philograph.library.catalog", "--catalog", str(catalog), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


@req(SC, "Синхронизация каталога с библиотекой")
@req(SC, "Правило публикации обновлений")
def test_catalog_sync_publishes_and_reader_shows(browser, own_stack, site, tmp_path):
    folder = tmp_path / "sources"
    folder.mkdir()
    for name in ("catalog.schema.json", "licenses.yaml"):
        (folder / name).write_bytes((ROOT / "sources" / name).read_bytes())
    entry = {
        "id": "e2e-essay-on-experience",
        "landing_url": f"{site}/book",
        "adapter": "direct",
        "kind": "primary",
        "section": "epistemology",
        "harvested": None,
        "override": {
            "metadata": {
                "title": TITLE,
                "authors": [{"name": "David Hume", "death_year": 1776, "wikidata": None}],
                "language": "en",
                "year": 1748,
            },
            "files": [{"name": "book.txt", "url": f"{site}/book.txt", "clean": "gutenberg"}],
        },
        "license": {"kind": "public-domain", "basis": "public_domain", "evidence": "ум. 1776"},
        "review": {"status": "approved", "by": "e2e", "at": None, "note": None},
        "publish": "auto",
    }
    catalog = folder / "catalog.yaml"
    catalog.write_text(
        yaml.safe_dump({"version": 1, "entries": [entry]}, allow_unicode=True), encoding="utf-8"
    )
    assert "ошибок: 0" in catalog_cli(own_stack, catalog, "validate")
    first = catalog_cli(own_stack, catalog, "sync")
    assert "e2e-essay-on-experience" in first and "опубликовано" in first, first
    again = catalog_cli(own_stack, catalog, "sync")
    assert "изменений нет" in again, again

    context = reader_context(browser, viewport={"width": 1400, "height": 900})
    page = context.new_page()
    page.set_default_timeout(15000)
    page.goto(own_stack.url + "/")
    card = page.locator(".source", has_text=TITLE)
    card.get_by_role("button", name="Читать").click()
    page.get_by_text("which custom alone makes us expect").wait_for()
    # служебные строки Project Gutenberg вырезаны до разбора
    assert page.get_by_text("PROJECT GUTENBERG").count() == 0
    context.close()
