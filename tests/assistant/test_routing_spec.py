"""question-routing: что система делает с типом вопроса и с извлечёнными именами.

Модель-маршрутизатор здесь только отдаёт тип; проверяется, какую цепочку шагов запускает
система (поиски, фильтры, шаблон, этапы) и что она пишет в журнал.
"""

from __future__ import annotations

import pytest

from philograph.llm.providers import TransientProviderError

from .conftest import bot  # noqa: F401 — стенд ассистента как фикстура
from .test_map_chain import draft, mb, of, route  # noqa: F401 — стенд с картой
from .test_ontology_retrieval import ob  # noqa: F401 — стенд с онтологией

req = pytest.mark.req
QR = "question-routing"
SELECTION = "Локк сравнивал ум с чистой доской"


class SearchSpy:
    """Записывает запросы цепочки к поиску и отдаёт их настоящему сервису поиска."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.queries: list[dict] = []

    def search(self, **query):
        self.queries.append(query)
        return self.inner.search(**query)


def spy(bot) -> SearchSpy:
    bot.assistant.search = SearchSpy(bot.assistant.search)
    return bot.assistant.search


def route_request(bot):
    return next(r for r in bot.model.requests if r.template == "assistant.route")


def answer_request(bot):
    return next(r for r in bot.model.requests if r.template.startswith("assistant.answer"))


@req(QR, "Типы вопросов", scenario="По месту")
def test_type_local_runs_local_chain(bot, events):
    searches = spy(bot)
    bot.model.routes.append({"type": "local", "confidence": 0.9, "names": []})
    items = bot.ask(
        question="что здесь значит «впечатление»?",
        selection=SELECTION,
        source_id=bot.rig.ids["ru"],
    )
    # маршрутизатору переданы вопрос и выделение
    prompt = route_request(bot).messages[-1].content
    assert "что здесь значит «впечатление»?" in prompt and SELECTION in prompt
    # тип «по месту» запускает цепочку «по месту»: шаблон, поиск в текущем источнике
    routed = events.one("assistant.routed")
    assert routed["type"] == "local" and routed["fallback"] is False
    assert answer_request(bot).template == "assistant.answer.local"
    assert searches.queries[0]["sources"] == [bot.rig.ids["ru"]]
    assert searches.queries[0]["neighbors"] == 1
    assert items[-1]["type"] == "done" and items[-1]["kind"] == "local"
    assert events.of("assistant.searched")[0]["scope"] == "current"


@req(QR, "Типы вопросов", scenario="Другие авторы")
def test_type_other_authors_runs_other_authors_chain(bot, events):
    searches = spy(bot)
    bot.model.routes.append({"type": "other_authors", "confidence": 0.9, "names": []})
    items = bot.ask(question="как это объясняют другие учебники?", source_id=bot.rig.ids["ru"])
    assert events.one("assistant.routed")["type"] == "other_authors"
    assert answer_request(bot).template == "assistant.answer.other_authors"
    assert searches.queries[0]["exclude_sources"] == [bot.rig.ids["ru"]]
    assert "sources" not in searches.queries[0]
    assert items[-1]["kind"] == "other_authors"
    assert events.one("assistant.searched")["scope"] == "others"


@req(QR, "Типы вопросов", scenario="Генезис")
def test_type_genesis_runs_genesis_chain(bot, events):
    searches = spy(bot)
    bot.model.routes.append({"type": "genesis", "confidence": 0.9, "names": []})
    items = bot.ask(question="откуда взялась эта идея?")
    assert events.one("assistant.routed")["type"] == "genesis"
    assert answer_request(bot).template == "assistant.answer.genesis"
    assert {"истоки", "предшественники", "впервые"} <= set(searches.queries[0]["extra_terms"])
    assert items[-1]["kind"] == "genesis"


@req(QR, "Типы вопросов", scenario="Карта")
def test_type_map_runs_map_chain_with_extracted_names(mb, events):
    bot = mb.bot
    searches = spy(bot)
    bot.model.routes.extend(
        [
            route(["эмпиризм"]),
            draft(groups=["Эмпиризм"], **{"from": 1700}),
        ]
    )
    items = bot.ask(question="покажи на карте эмпиристов XVIII века")
    assert events.one("assistant.routed")["type"] == "map"
    assert {"type": "stage", "name": "map_view"} in items
    # извлечённое имя «эмпиризм» дошло до поиска и до подбора кандидатов вида
    assert "эмпиризм" in searches.queries[0]["extra_terms"]
    prompt = next(r for r in bot.model.requests if r.template == "assistant.map.view")
    assert "направление или школа «Эмпиризм»" in prompt.messages[-1].content
    [suggestion] = of(items, "suggestion", "map")
    assert str(mb.ids["empiricism"]) in suggestion["href"]
    events.one("assistant.map_view.drafted")


@req(QR, "Типы вопросов", scenario="Карта")
def test_names_are_what_finds_the_map_entities(mb, events):
    """Без извлечённых имён в вопросе «эмпиристов» кандидатов вида нет: цепочка зависит от имён."""
    bot = mb.bot
    bot.model.routes.append(route([]))
    items = bot.ask(question="покажи на карте эмпиристов XVIII века")
    assert of(items, "notice", "map_no_candidates")
    assert events.one("assistant.map_view.failed")["reason"] == "no_candidates"


@req(QR, "Типы вопросов", invariant="Типы и их цепочки описываются настройкой, а не кодом")
def test_every_type_has_chain_data_and_unknown_type_is_refused_by_schema(bot, events):
    from philograph.assistant.service import CHAINS, TYPES

    for kind in TYPES:
        chain = CHAINS[kind]
        assert chain.get("refuse") or (chain["template"] and chain["searches"]), kind
    # тип вне списка схема вывода не пропускает: маршрутизация идёт запасным путём
    bot.model.routes.extend([{"type": "voodoo", "confidence": 0.99, "names": []}] * 3)
    items = bot.ask(question="что такое опыт?")
    routed = events.one("assistant.routed")
    assert routed["type"] in TYPES and routed["fallback"] is True
    assert items[-1]["type"] == "done"


@req(QR, "Быстрая модель", scenario="Структура ответа маршрутизатора")
def test_router_event_has_type_confidence_duration(bot, events):
    bot.model.routes.append({"type": "genesis", "confidence": 0.77, "names": ["Юм"]})
    bot.ask(question="откуда взялась идея причинности у Юма?")
    routed = events.one("assistant.routed")
    assert routed["type"] == "genesis" and routed["confidence"] == 0.77
    assert isinstance(routed["duration_ms"], float) and routed["duration_ms"] >= 0
    call = next(c for c in bot.gateway.store.calls() if c["operation"] == "route")
    assert call["role"] == "fast" and call["kind"] == "structured" and call["status"] == "ok"


@req(QR, "Быстрая модель", invariant="Структурированный вывод: тип, уверенность и имена")
def test_router_output_violating_schema_is_not_applied(bot, events):
    """Ответ без уверенности и с чужим типом не применяется: выбор запасной."""
    bot.model.routes.extend([{"type": "genesis"}] * 3)
    items = bot.ask(question="что такое опыт?")
    routed = events.one("assistant.routed")
    assert routed["type"] == "knowledge" and routed["fallback"] is True
    assert items[-1]["type"] == "done"


@req(QR, "Запасной тип", scenario="Таймаут маршрутизатора")
def test_router_timeout_falls_back_to_knowledge_without_selection(bot, events):
    searches = spy(bot)
    bot.model.routes.extend([TransientProviderError("таймаут")] * 3)
    items = bot.ask(question="что такое опыт?")
    routed = events.one("assistant.routed")
    assert routed["type"] == "knowledge" and routed["fallback"] is True
    assert routed["confidence"] == 0.0
    assert answer_request(bot).template == "assistant.answer.knowledge"
    assert searches.queries and items[-1]["type"] == "done" and items[-1]["kind"] == "knowledge"
    assert not [i for i in items if i["type"] in ("error", "unavailable", "refused")]


@req(QR, "Запасной тип", invariant="При неуверенности ниже порога выбирается запасной тип")
@pytest.mark.parametrize(
    ("confidence", "fallback"),
    [(0.49, True), (0.5, False), (0.0, True), (1.0, False)],
)
def test_threshold_boundary(bot, events, confidence, fallback):
    bot.model.routes.append({"type": "genesis", "confidence": confidence, "names": []})
    bot.ask(question="откуда взялась идея?")
    routed = events.one("assistant.routed")
    assert routed["fallback"] is fallback
    assert routed["type"] == ("knowledge" if fallback else "genesis")


@req(QR, "Запасной тип", invariant="Запасной тип «по месту», если есть выделение")
def test_fallback_with_selection_is_local(bot, events):
    bot.model.routes.extend([TransientProviderError("сбой")] * 3)
    bot.ask(question="что это?", selection=SELECTION, source_id=bot.rig.ids["ru"])
    routed = events.one("assistant.routed")
    assert routed["type"] == "local" and routed["fallback"] is True


@req(QR, "Вопросы вне темы", scenario="Посторонний вопрос")
def test_off_topic_polite_refusal_no_main_model(bot, events):
    searches = spy(bot)
    bot.model.routes.append({"type": "off_topic", "confidence": 0.95, "names": []})
    items = bot.ask(question="напиши код на Python")
    assert items == [
        {
            "type": "refused",
            "reason": "off_topic",
            "message": "Я помогаю разбираться с материалами по философии.",
        }
    ]
    assert not [c for c in bot.gateway.store.calls() if c["operation"] == "answer"]
    assert [r.template for r in bot.model.requests] == ["assistant.route"]
    assert searches.queries == []
    assert events.one("assistant.refused")["reason"] == "off_topic"
    events.assert_none("assistant.answer.completed")


@req(QR, "Запасной тип", invariant="При неуверенности ниже порога выбирается запасной тип")
@pytest.mark.xfail(
    strict=True,
    reason="дефект: «вне темы» с уверенностью ниже порога остаётся off_topic и даёт отказ, "
    "а спецификация требует запасной тип и продолжение ответа",
)
def test_low_confidence_off_topic_uses_fallback_type(bot, events):
    bot.model.routes.append({"type": "off_topic", "confidence": 0.1, "names": []})
    items = bot.ask(question="напиши код на Python")
    routed = events.one("assistant.routed")
    assert routed["fallback"] is True and routed["type"] == "knowledge"
    assert items[-1]["type"] == "done"


@req(QR, "Заданные цепочки шагов", scenario="По месту")
def test_local_chain_widens_to_library_when_few_found(bot, events):
    """Найдено мало в текущем источнике — второй поиск во всей библиотеке."""
    searches = spy(bot)
    bot.model.routes.append({"type": "local", "confidence": 0.9, "names": []})
    bot.ask(
        question="blank slate",
        selection="Locke described the mind",
        source_id=bot.rig.ids["ru"],
        selection_paragraphs=[],
    )
    scopes = [e["scope"] for e in events.of("assistant.searched")]
    first = events.of("assistant.searched")[0]["results"]
    assert first < 3, "для проверки нужен источник, где найдено меньше трёх"
    assert scopes == ["current", "all"]
    assert searches.queries[0]["sources"] == [bot.rig.ids["ru"]]
    assert "sources" not in searches.queries[1] and searches.queries[1]["limit"] == 6
    assert answer_request(bot).template == "assistant.answer.local"


@req(QR, "Заданные цепочки шагов", scenario="По месту")
def test_local_chain_does_not_widen_when_enough_found(bot, events):
    searches = spy(bot)
    bot.model.routes.append({"type": "local", "confidence": 0.9, "names": []})
    bot.ask(
        question="Юм Локк опыт привычка причинность индукция будущее",
        selection=SELECTION,
        source_id=bot.rig.ids["ru"],
    )
    assert events.of("assistant.searched")[0]["results"] >= 3
    assert [e["scope"] for e in events.of("assistant.searched")] == ["current"]
    assert len(searches.queries) == 1


@req(QR, "Заданные цепочки шагов", scenario="Другие авторы")
def test_other_authors_chain_excludes_current_and_separates_authors(bot, events):
    """Поиск кроме текущего источника; абзацы переданы сгруппированными по источникам."""
    searches = spy(bot)
    bot.model.routes.append({"type": "other_authors", "confidence": 0.9, "names": []})
    bot.ask(question="Юм Локк опыт slate blank привычка причинность")
    assert searches.queries[0]["per_chapter"] == 2
    request = answer_request(bot)
    assert "Раздели ответ по авторам: что пишет каждый" in request.messages[0].content
    block = request.messages[-1].content
    headers = [line for line in block.splitlines() if line.startswith("Источник:")]
    assert len(headers) == len(set(headers)) >= 2, headers  # у каждого источника своя группа
    assert events.one("assistant.searched")["scope"] == "others"


@req(QR, "Заданные цепочки шагов", scenario="Другие авторы")
def test_other_authors_chain_excludes_current_source_results(bot, events):
    bot.model.routes.append({"type": "other_authors", "confidence": 0.9, "names": []})
    bot.ask(question="чистая доска Локк", source_id=bot.rig.ids["ru"])
    block = answer_request(bot).messages[-1].content
    assert "Локк сравнивал ум с чистой доской" not in block  # абзац текущего источника
    assert "blank slate" in block


@req(QR, "Заданные цепочки шагов", scenario="Предел вызовов")
@pytest.mark.parametrize("kind", ["local", "knowledge", "other_authors", "genesis"])
def test_call_limit_per_question(bot, events, kind):
    bot.model.routes.append({"type": kind, "confidence": 0.9, "names": []})
    items = bot.ask(question="что такое опыт?", selection=SELECTION, source_id=bot.rig.ids["ru"])
    done = events.one("assistant.answer.completed")
    assert done["llm_calls"] <= bot.assistant.settings.max_llm_calls
    stored = [c for c in bot.gateway.store.calls() if c["caller"] == "assistant"]
    assert len(stored) <= bot.assistant.settings.max_llm_calls == 3
    assert items[-1]["llm_calls"] == done["llm_calls"]


@req(QR, "Цепочки без онтологии", scenario="Генезис без онтологии")
def test_genesis_without_ontology_searches_predecessors_and_answers_from_them(bot, events):
    searches = spy(bot)
    assert bot.assistant.ontology is None
    bot.model.routes.append({"type": "genesis", "confidence": 0.9, "names": []})
    bot.model.answers.append(
        lambda prompt: [f"Идея Локка о чистой доске [{bot.number(prompt, 'чистой доской')}]. "]
    )
    items = bot.ask(question="откуда взялась идея врождённых идей?")
    assert {"истоки", "предшественники", "впервые"} <= set(searches.queries[0]["extra_terms"])
    assert events.one("assistant.ontology.skipped")["reason"] == "not_configured"
    fragments = of(items, "fragment")
    assert fragments and fragments[0]["grounded"] and fragments[0]["citations"]
    assert not of(items, "suggestion")
    assert events.one("assistant.answer.completed")["passages"] > 0


@req(
    QR,
    "Цепочки без онтологии",
    invariant="Цепочки «другие авторы» и «генезис» работают через поиск",
)
def test_other_authors_without_ontology_works_through_search(bot, events):
    bot.model.routes.append({"type": "other_authors", "confidence": 0.9, "names": []})
    items = bot.ask(question="как объясняют опыт разные авторы?")
    assert events.of("assistant.searched") and items[-1]["type"] == "done"
    assert events.one("assistant.ontology.skipped")["reason"] == "not_configured"


@req(QR, "Цепочки без онтологии", invariant="Точки расширения цепочек для онтологии")
def test_chains_have_ontology_extension_points(bot):
    from philograph.assistant.service import CHAINS

    assert CHAINS["genesis"]["recipe"] == "genesis"
    # онтология добавляет шаги данными, не правкой обработчиков: ask читает recipe из CHAINS
    for kind, chain in CHAINS.items():
        assert isinstance(chain, dict), kind


@req(QR, "Цепочка «карта»", invariant="Подбор вида укладывается в предел вызовов")
@pytest.mark.parametrize("limit", [2, 3, 4])
def test_map_chain_never_exceeds_call_limit(mb, events, limit):
    from philograph.assistant.service import AssistantSettings

    bot = mb.bot
    bot.assistant.settings = AssistantSettings(max_llm_calls=limit, visitor_per_hour=50)
    bot.model.routes.extend([route(["эмпиризм"]), draft(groups=["Эмпиризм"])])
    bot.ask(question="покажи на карте эмпиристов")
    assert events.one("assistant.answer.completed")["llm_calls"] <= limit
