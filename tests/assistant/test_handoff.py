"""assistant-page «Граница книги»: событие handoff при context=book (N12)."""

from __future__ import annotations

import pytest

from .conftest import bot  # noqa: F401 — стенд ассистента как фикстура

req = pytest.mark.req
AP = "assistant-page"


def types(items: list[dict]) -> list[str]:
    return [i["type"] for i in items]


@req(AP, "Граница книги")
def test_handoff_broader_for_other_authors(bot):
    bot.model.routes.append({"type": "other_authors", "confidence": 0.9, "names": []})
    items = bot.ask(question="а что думали другие авторы?", context="book", source_id="src")
    assert "handoff" in types(items) and "fragment" not in types(items)
    assert next(i for i in items if i["type"] == "handoff")["reason"] == "broader"


@req(AP, "Граница книги")
def test_handoff_declined_suppresses_broader(bot):
    bot.model.routes.append({"type": "other_authors", "confidence": 0.9, "names": []})
    bot.model.answers.append(["Ответ по книге [1]. "])
    items = bot.ask(
        question="а что думали другие авторы?",
        context="book",
        source_id="src",
        handoff_declined=True,
        handoff_reason="broader",
    )
    assert "handoff" not in types(items)


@req(AP, "Граница книги")
def test_handoff_outside_book(bot):
    bot.model.routes.append({"type": "knowledge", "confidence": 0.9, "names": []})
    bot.model.answers.append(["Ответ по другому источнику [1]. "])
    items = bot.ask(question="что пишут в других книгах?", context="book", source_id="другая-книга")
    handoff = next((i for i in items if i["type"] == "handoff"), None)
    assert handoff is not None and handoff["reason"] == "outside_book"


@req(AP, "Граница книги")
def test_library_context_never_handsoff(bot):
    bot.model.routes.append({"type": "knowledge", "confidence": 0.9, "names": []})
    bot.model.answers.append(["Ответ по другому источнику [1]. "])
    items = bot.ask(question="что пишут в других книгах?", context="library", source_id="другая-книга")
    assert "handoff" not in types(items)
