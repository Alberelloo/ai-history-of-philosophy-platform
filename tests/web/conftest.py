"""Сервер библиотеки с тестовыми источниками и браузер Playwright.

Сервер запускается в потоке этого же процесса, поэтому тест видит и страницу в браузере, и
события журнала сервера. Нужны собранный клиент (``npm run build`` в ``web/``) и Chromium
(``python -m playwright install chromium``); без них тесты интерфейса пропускаются.
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest

from philograph.library import schema
from philograph.library.app import build_app
from philograph.library.processing import Pipeline
from philograph.library.reading import Reading
from philograph.library.registry import License, Registry
from philograph.operator.access import migrations as operator_migrations
from philograph.platform.db import make_engine
from philograph.platform.files import FileStore

from ..helpers import reader_context
from ..library.builders import epub

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "web" / "dist"

TEXTBOOK = epub(
    [
        (
            "Глава 1. Опыт",
            "<p>Всякое знание начинается с опыта, говорит Кант.</p>"
            '<span epub:type="pagebreak" title="41"/>'
            '<p>Кант пишет о вещи в себе<a href="#n1" epub:type="noteref">1</a>'
            " весьма подробно.</p>"
            '<aside epub:type="footnote" id="n1"><p>Критика чистого разума, B XXVI. '
            "См. https://example.org/kant</p></aside>"
            '<span epub:type="pagebreak" title="42"/>'
            + "".join(f"<p>Абзац {i} о чувственности и опыте познания.</p>" for i in range(40)),
        ),
        (
            "Глава 2. Рассудок",
            "<p>Рассудок даёт правила явлениям.</p><h2>Схематизм</h2>"
            + "".join(f"<p>Схема {i} связывает категории и созерцания.</p>" for i in range(30)),
        ),
        ("Глава 3. Разум", "<p>Разум стремится к безусловному.</p>"),
    ]
)
PRIMARY = b"Chapter 1\n\nAll our knowledge begins with experience.\n"
REFERENCE = "Статья «Познание»\n\nПознание — процесс постижения мира.\n".encode()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Site:
    def __init__(
        self,
        url: str,
        registry: Registry,
        pipeline: Pipeline,
        reading: Reading,
        ids: dict[str, str],
    ) -> None:
        self.url = url
        self.registry = registry
        self.pipeline = pipeline
        self.reading = reading
        self.ids = ids

    def paragraphs(self, source: str) -> list[tuple[str, str, str]]:
        """(глава, абзац, текст) опубликованной версии источника."""
        version = self.registry.get(self.ids[source]).published_version
        doc = self.registry.load_document(version)
        result = []
        for chapter in self.reading.chapters(doc):
            for section in chapter.walk():
                result.extend((chapter.id, b.id, b.text) for b in section.blocks)
        return result


@pytest.fixture(scope="module")
def site(tmp_path_factory) -> Site:
    if not (DIST / "index.html").exists():
        pytest.skip("клиент не собран: npm run build в web/")
    import uvicorn

    tmp = tmp_path_factory.mktemp("site")
    engine = make_engine(
        f"sqlite:///{(tmp / 'site.db').as_posix()}", [schema.SCHEMA, operator_migrations.schema]
    )
    schema.migrations.upgrade(engine)
    operator_migrations.upgrade(engine)
    registry = Registry(engine)
    registry.add_license_kind(
        "public-domain",
        "Общественное достояние",
        "https://example.org/public-domain",
        {"display": True, "external_processing": True, "quoting": True},
    )
    files = {"textbook.epub": TEXTBOOK, "primary.txt": PRIMARY, "reference.txt": REFERENCE}
    pipeline = Pipeline(registry, FileStore(tmp / "files"), lambda spec: files[spec["path"]])
    lic = License("public-domain", "public_domain", author_death_years=[1900])
    ids = {
        "textbook": registry.register(
            "operator",
            title="История теории познания",
            authors=["В. Ф. Асмус"],
            year=1950,
            language="ru",
            kind="textbook",
            license=lic,
            scope="public",
            files=[{"name": "t", "path": "textbook.epub"}],
        ),
        "primary": registry.register(
            "operator",
            title="Critique of Pure Reason",
            authors=["I. Kant"],
            year=1781,
            language="en",
            kind="primary",
            license=lic,
            scope="public",
            files=[{"name": "p", "path": "primary.txt"}],
        ),
        "reference": registry.register(
            "operator",
            title="Философский словарь",
            authors=["Коллектив авторов"],
            language="ru",
            kind="reference",
            license=lic,
            scope="public",
            files=[{"name": "r", "path": "reference.txt"}],
        ),
    }
    for source_id in ids.values():
        version = pipeline.start("operator", source_id)
        registry.publish("operator", version)
    reading = Reading(registry, engine)
    reading.set_default("operator", ids["textbook"])
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            build_app(reading, web_root=DIST), host="127.0.0.1", port=port, log_level="warning"
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    yield Site(f"http://127.0.0.1:{port}", registry, pipeline, reading, ids)
    server.should_exit = True
    thread.join(5)


@pytest.fixture
def page(browser, site):
    context = reader_context(browser, permissions=["clipboard-read", "clipboard-write"])
    page = context.new_page()
    page.set_default_timeout(5000)
    yield page
    context.close()
