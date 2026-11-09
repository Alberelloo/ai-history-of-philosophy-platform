"""Подробности ссылок ответа для подсказки (reader-panels.md, 5.4; N4 и N5 из 12.2).

N4: у ссылки на абзац — название книги, название главы и начало абзаца. Название главы
ассистент берёт из оглавления библиотеки: поиск хранит у абзаца только заголовок раздела.
N5: у ссылки на утверждение онтологии — ``entity_id`` сущности утверждения.
"""

from __future__ import annotations

import httpx
import pytest

from philograph.assistant.clients import LibraryHttp
from philograph.library.app import build_app as library_app
from philograph.library.reading import Reading
from philograph.platform.client import ServiceClient

from ..helpers import asgi_transport
from .conftest import bot  # noqa: F401 — стенд ассистента как фикстура

req = pytest.mark.req
AG = "answer-grounding"


def citations(items: list[dict]) -> list[dict]:
    return [c for i in items if i["type"] == "fragment" for c in i["citations"]]


def library_for(bot) -> LibraryHttp:
    reading = Reading(bot.rig.registry, bot.rig.registry.engine)
    client = ServiceClient(
        "library", "http://library/api", transport=asgi_transport(library_app(reading))
    )
    return LibraryHttp(client)


def toc_titles(bot, source_id: str) -> dict[str, str]:
    reading = Reading(bot.rig.registry, bot.rig.registry.engine)
    titles: dict[str, str] = {}

    def walk(nodes):
        for n in nodes:
            if n["id"] == n["chapter_id"]:
                titles[n["id"]] = n["title"]
            walk(n["children"])

    walk(reading.toc(source_id))
    return titles


@req(AG, "Ссылки на абзацы")
def test_citation_has_book_chapter_and_start(bot):
    """N4: название книги, название главы и первые 120 знаков абзаца."""
    bot.assistant.library = library_for(bot)
    bot.model.answers.append(["Юм говорил о привычке [1]. "])
    items = bot.ask(question="Что Юм говорил о причинности?")
    cited = citations(items)
    assert cited, items
    c = cited[0]
    titles = toc_titles(bot, c["source_id"])
    assert c["chapter_id"] in titles
    assert c["chapter_title"] == titles[c["chapter_id"]] and c["chapter_title"]
    assert c["source_title"]
    assert c["paragraph_start"] and len(c["paragraph_start"]) <= 120


@req(AG, "Ссылки на абзацы")
def test_chapter_titles_cached_per_source(bot):
    """Оглавление источника запрашивается один раз на много ответов."""
    library = library_for(bot)
    calls: list[str] = []
    original = library.client.get

    def counting(path, **kw):
        calls.append(path)
        return original(path, **kw)

    library.client.get = counting
    bot.assistant.library = library
    for _ in range(2):
        bot.model.answers.append(["Юм говорил о привычке [1]. "])
        bot.ask(question="Что Юм говорил о причинности?")
    assert len(calls) == len(set(calls)) >= 1


@req(AG, "Ссылки на абзацы")
def test_answer_without_library_has_no_chapter_title(bot, events):
    """Без библиотеки или при её сбое ответ идёт как обычно, без названия главы."""
    bot.model.answers.append(["Юм говорил о привычке [1]. "])
    assert citations(bot.ask(question="Что Юм говорил о причинности?"))[0]["chapter_title"] is None

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет связи", request=request)

    bot.assistant.library = LibraryHttp(
        ServiceClient("library", "http://library/api", transport=httpx.MockTransport(down))
    )
    bot.model.answers.append(["Юм говорил о привычке [1]. "])
    items = bot.ask(question="Что Юм говорил о причинности?")
    assert items[-1]["type"] == "done"
    assert citations(items)[0]["chapter_title"] is None
    assert events.where("service.call.failed", target="library")
