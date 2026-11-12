"""Группа 5 «Ассистент»: регион читателя доходит до поиска и онтологии, закрытые источники
не попадают в контекст модели и в ответ. Требования ``regional-access`` и ``answer-grounding``.
"""

from __future__ import annotations

import json
import re

import pytest

from philograph.assistant.grounding import Passage, verify
from philograph.assistant.ontology import Ontology
from philograph.library.registry import License

from .conftest import bot  # noqa: F401 — стенд ассистента как фикстура

req = pytest.mark.req
RA = "regional-access"
AG = "answer-grounding"

RESTRICTED_TEXT = "Глава 1\n\nРассудок есть способность правил, разум — способность принципов.\n"
NO_EXTERNAL_TEXT = "Глава 1\n\nРассудок даёт правила, а разум — принципы познания.\n"
OPEN_PERMISSIONS = {"display": True, "external_processing": True, "quoting": True}


class FakeSearch:
    """Поиск, который только запоминает запросы (для проверки передачи региона)."""

    def __init__(self) -> None:
        self.queries: list[dict] = []

    def search(self, **query):
        self.queries.append(query)
        return {"results": [], "semantic_used": True}


class FakeKnowledge:
    """Сервис знаний, который запоминает тело запроса контекста."""

    def __init__(self) -> None:
        self.bodies: list[dict] = []

    def context(self, **body):
        self.bodies.append(body)
        return {
            "entities": [],
            "terms": [],
            "priority": [],
            "statements": [],
            "paragraphs": [],
            "facts": [],
            "graph": None,
        }


def add_restricted(bot) -> str:
    """Регистрирует источник только для РФ, возвращает его идентификатор."""
    rig = bot.rig
    rig.registry.add_license_kind(
        "ru-only", "Только РФ", None, dict(OPEN_PERMISSIONS), regions=["RU"]
    )
    lic = License("ru-only", "public_domain", author_death_years=[1900])
    source_id = rig.registry.register(
        "operator",
        title="Ограниченная книга",
        authors=["К"],
        language="ru",
        kind="textbook",
        license=lic,
        scope="public",
        files=[{"name": "r", "path": "restricted.txt"}],
    )
    rig.files["restricted.txt"] = RESTRICTED_TEXT.encode()
    rig.ids["restricted"] = source_id
    return source_id


def add_no_external(bot) -> str:
    """Регистрирует источник только для РФ без внешней обработки, возвращает идентификатор."""
    rig = bot.rig
    rig.registry.add_license_kind(
        "ru-no-external",
        "Только РФ без внешней обработки",
        None,
        {"display": True, "external_processing": False, "quoting": True},
        regions=["RU"],
    )
    lic = License("ru-no-external", "public_domain", author_death_years=[1900])
    source_id = rig.registry.register(
        "operator",
        title="Без внешней обработки",
        authors=["Н"],
        language="ru",
        kind="textbook",
        license=lic,
        scope="public",
        files=[{"name": "n", "path": "noexternal.txt"}],
    )
    rig.files["noexternal.txt"] = NO_EXTERNAL_TEXT.encode()
    rig.ids["no_external"] = source_id
    return source_id


def ask_region(bot, region: str | None, **body) -> list[dict]:
    """Запрос к ассистенту с заголовком региона (нет региона — заголовка нет)."""
    headers = {"X-Philograph-Region": region} if region else {}
    response = bot.client.post("/v1/ask", json=body, headers=headers)
    assert response.status_code == 200
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def prompt(bot) -> str:
    return bot.model.requests[-1].messages[-1].content


def block(prompt: str, name: str) -> str:
    match = re.search(rf'<data name="{name}">\n(.*?)\n</data>', prompt, re.S)
    return match.group(1) if match else ""


def cited_sources(items: list[dict]) -> set[str]:
    return {
        c["source_id"]
        for i in items
        if i["type"] == "fragment"
        for c in i["citations"]
        if c["kind"] == "paragraph"
    }


@req(RA, "Ассистент не использует закрытые источники")
def test_region_from_header_reaches_search(bot):
    """Заголовок региона читается и передаётся в поиск; без заголовка — неизвестный регион."""
    fake = FakeSearch()
    bot.assistant.search = fake
    bot.model.routes.append({"type": "knowledge", "confidence": 0.9, "names": []})
    ask_region(bot, "DE", question="что такое рассудок?")
    assert fake.queries and fake.queries[-1]["region"] == "DE"

    ask_region(bot, None, question="что такое рассудок?")
    assert fake.queries[-1]["region"] is None

    # Служебное значение CDN «страна не определена» — тоже неизвестный регион.
    ask_region(bot, "XX", question="что такое рассудок?")
    assert fake.queries[-1]["region"] is None


@req(RA, "Ассистент не использует закрытые источники")
def test_ontology_context_carries_region(bot):
    """Регион передаётся сервису знаний в запросе контекста онтологии."""
    knowledge = FakeKnowledge()
    bot.assistant.ontology = Ontology(knowledge)
    bot.model.routes.append({"type": "knowledge", "confidence": 0.9, "names": []})
    ask_region(bot, "DE", question="что такое рассудок?")
    assert knowledge.bodies and knowledge.bodies[-1]["region"] == "DE"

    ask_region(bot, None, question="что такое рассудок?")
    assert knowledge.bodies[-1]["region"] is None


@req(RA, "Ассистент не использует закрытые источники")
def test_question_outside_rf_has_no_closed_source(bot):
    """Вопрос читателя вне РФ: лучший ответ в закрытом источнике не попадает в контекст."""
    restricted = add_restricted(bot)
    bot.rig.publish("restricted")
    bot.model.routes.append({"type": "knowledge", "confidence": 0.9, "names": []})
    bot.model.answers.append(["Рассудок и разум по источникам [1]. "])
    items = ask_region(bot, "DE", question="рассудок и разум")
    passages = block(prompt(bot), "passages")
    assert passages  # ответ строится по открытым источникам
    assert "Рассудок есть способность правил" not in passages  # текста закрытого источника нет
    assert restricted not in cited_sources(items)  # и ссылок на него нет

    # Тот же вопрос из РФ: закрытый источник доступен и попадает в контекст.
    bot.model.routes.append({"type": "knowledge", "confidence": 0.9, "names": []})
    bot.model.answers.append(["Ответ [1]. "])
    ask_region(bot, "RU", question="рассудок и разум")
    assert "Рассудок есть способность правил" in block(prompt(bot), "passages")


@req(RA, "Ассистент не использует закрытые источники")
def test_selection_in_closed_source_ignored(bot):
    """Выделение и текущий источник из закрытого источника не используются и не получают
    приоритета: текст не попадает в контекст модели."""
    restricted = add_restricted(bot)
    bot.rig.publish("restricted")
    restricted_para = bot.rig.paragraph("restricted", "Рассудок есть способность правил")
    bot.model.routes.append({"type": "local", "confidence": 0.9, "names": []})
    bot.model.answers.append(["Ответ [1]. "])
    items = ask_region(
        bot,
        "DE",
        question="объясни этот фрагмент",
        selection="Рассудок есть способность правил, разум — способность принципов.",
        selection_paragraphs=[restricted_para],
        source_id=restricted,
    )
    passages = block(prompt(bot), "passages")
    assert "Рассудок есть способность правил" not in passages
    assert restricted not in cited_sources(items)


@req(RA, "Ассистент не использует закрытые источники")
def test_current_source_in_closed_region_behaves_as_absent(bot):
    """Текущий (запомненный) источник из закрытого региона: ассистент работает, как будто
    источника нет — ответ без опоры на библиотеку, ссылок на закрытый источник нет."""
    restricted = add_restricted(bot)
    bot.rig.publish("restricted")
    bot.model.routes.append({"type": "knowledge", "confidence": 0.9, "names": []})
    bot.model.answers.append(["Ответ [1]. "])
    items = ask_region(
        bot, "DE", question="рассудок и разум", scope="current", source_id=restricted
    )
    assert "Рассудок есть способность правил" not in prompt(bot)
    assert restricted not in cited_sources(items)
    assert any(i.get("kind") == "no_library_support" for i in items)


@req(RA, "Внешняя обработка закрытых источников")
def test_non_external_paragraphs_not_sent_to_model(bot):
    """7.2: абзацы без ``external_processing`` не уходят модели, в потоке есть пометка со ссылкой.

    Читатель из РФ видит источник по региону, но текст не передаётся модели: фиктивная модель
    фиксирует в ``passages`` только пересказываемые абзацы, а найденное показано ссылкой."""
    source = add_no_external(bot)
    bot.rig.publish("no_external")
    bot.model.routes.append({"type": "knowledge", "confidence": 0.9, "names": []})
    bot.model.answers.append(["Ответ без опоры на закрытый абзац. "])
    items = ask_region(bot, "RU", question="рассудок и разум")

    passages = block(prompt(bot), "passages")
    assert "Рассудок даёт правила" not in passages  # текста источника без внешней обработки нет
    assert "категория рассудка" in passages  # открытые абзацы пересказываются, как раньше

    notice = next(i for i in items if i["type"] == "notice" and i["kind"] == "found_not_retold")
    assert notice["message"] == "Найдено в источниках, не пересказывается."
    assert [s["paragraph_id"] for s in notice["suggestions"]] == [
        bot.rig.paragraph("no_external", "Рассудок даёт правила")
    ]
    assert source not in cited_sources(items)


@req(RA, "Внешняя обработка закрытых источников")
def test_only_hidden_results_marked_as_unsupported(bot):
    """Найдены только непересказываемые абзацы: контекст модели пуст, ответ честно помечен
    «без опоры на библиотеку», а найденное показано ссылками."""
    source = add_no_external(bot)
    bot.rig.publish("no_external")
    paragraph = bot.rig.paragraph("no_external", "Рассудок даёт правила")
    hidden = {
        "paragraph_id": paragraph,
        "source_id": source,
        "source_title": "Без внешней обработки",
        "text": "Рассудок даёт правила, а разум — принципы познания.",
        "external": False,
    }

    class HiddenOnly:
        def search(self, **query):
            return {"results": [hidden], "semantic_used": False}

    bot.assistant.search = HiddenOnly()
    bot.model.routes.append({"type": "knowledge", "confidence": 0.9, "names": []})
    bot.model.answers.append(["Ответ [1]. "])
    items = ask_region(bot, "RU", question="рассудок и разум")

    assert "Рассудок даёт правила" not in prompt(bot)  # модели нечего пересказывать
    kinds = [i["kind"] for i in items if i["type"] == "notice"]
    assert kinds == ["found_not_retold", "no_library_support"]
    assert cited_sources(items) == set()


@req(AG, "Проверка ссылок кодом")
def test_citation_to_unpassed_paragraph_removed():
    """Второй слой защиты: ссылка на абзац, которого нет среди переданных (например, из
    закрытого источника, отсечённого регионом), удаляется проверкой кода."""
    open_passage = Passage(1, "p-open", "s-open", "c1", "Глава", "Открытый текст источника.")
    fragment = verify("Закрытый источник пишет иначе [2].", {1: open_passage})
    assert fragment.citations == []
    assert fragment.removed_citations == 1
    assert fragment.grounded is False
