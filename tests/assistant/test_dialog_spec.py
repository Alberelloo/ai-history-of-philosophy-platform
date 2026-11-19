"""assistant-dialog и answer-grounding на сервере: вопрос, длина, поток, история, лимиты, журнал.

Браузерная часть требований — в ``tests/web``; здесь проверяется то, что делает сервис
ассистента с запросом, и события журнала.
"""

from __future__ import annotations

import pytest

from philograph.assistant.clients import LlmUnavailable
from philograph.assistant.grounding import Passage, verify
from philograph.assistant.service import AskRequest
from philograph.llm.providers import TransientProviderError

from .conftest import bot  # noqa: F401 — стенд ассистента как фикстура
from .test_routing_spec import answer_request, route_request, spy

req = pytest.mark.req
AD = "assistant-dialog"
SELECTION = "По Юму, причинность есть привычка ума"


def types(items):
    return [i["type"] for i in items]


def last_answer_content(bot) -> str:
    requests = [r for r in bot.model.requests if r.template.startswith("assistant.answer")]
    return requests[-1].messages[-1].content


@req(AD, "Вопрос о выделенном фрагменте", scenario="Выделение через абзацы")
def test_selection_across_paragraphs_passes_both(bot, events):
    searches = spy(bot)
    first = bot.para("привычка ума")
    second = bot.para("чистой доской")
    bot.model.routes.append({"type": "local", "confidence": 0.9, "names": []})
    bot.ask(
        question="как это связано?",
        selection="привычка ума ... Локк сравнивал ум с чистой доской",
        selection_paragraphs=[first, second],
        source_id=bot.rig.ids["ru"],
    )
    assert searches.queries[0]["priority"][:2] == [first, second]
    assert events.one("assistant.question.received")["has_selection"] is True
    assert "чистой доской" in answer_request(bot).messages[-1].content


@req(AD, "Вопрос о выделенном фрагменте", scenario="Вопрос без текста")
def test_empty_question_with_selection_explains_fragment(bot, events):
    bot.model.routes.append({"type": "local", "confidence": 0.9, "names": []})
    items = bot.ask(question="", selection=SELECTION, source_id=bot.rig.ids["ru"])
    assert "Объясни этот фрагмент." in route_request(bot).messages[-1].content
    assert "Объясни этот фрагмент." in answer_request(bot).messages[-1].content
    assert items[-1]["type"] == "done" and "fragment" in types(items)
    received = events.one("assistant.question.received")
    assert received["question_length"] == 0 and received["has_selection"] is True
    assert events.one("assistant.routed")["type"] == "local"


@req(
    AD,
    "Вопрос о выделенном фрагменте",
    invariant="Пустой вопрос без выделения не превращается в объяснение фрагмента",
)
def test_empty_question_without_selection_not_replaced(bot, events):
    bot.ask(question="   ")
    assert "Объясни этот фрагмент." not in route_request(bot).messages[-1].content
    assert events.one("assistant.question.received")["has_selection"] is False


@req(AD, "Ограничение длины", scenario="Слишком длинное выделение")
def test_too_long_selection_refused_before_any_call(bot, events):
    searches = spy(bot)
    items = bot.ask(question="что это?", selection="а" * 4001)
    assert items == [
        {
            "type": "refused",
            "reason": "too_long",
            "message": "Слишком длинный фрагмент или вопрос: выделите меньше.",
        }
    ]
    assert bot.model.requests == [] and searches.queries == []  # запрос не отправлен
    assert events.one("assistant.refused")["reason"] == "too_long"
    events.assert_none("assistant.routed")


@req(AD, "Ограничение длины", invariant="Длина фрагмента и вопроса ограничена")
@pytest.mark.parametrize(
    ("field", "size", "refused"),
    [
        ("selection", 4000, False),
        ("selection", 4001, True),
        ("question", 2000, False),
        ("question", 2001, True),
        ("question", 100000, True),
    ],
)
def test_length_limits_boundaries(bot, events, field, size, refused):
    body = {"question": "что это?"}
    body[field] = "а" * size
    items = bot.ask(**body)
    assert (items[0]["type"] == "refused") is refused
    assert bool(events.where("assistant.refused", reason="too_long")) is refused
    assert bool(events.of("assistant.routed")) is (not refused)


@req(AD, "Общий вопрос", scenario="Общий вопрос в раздел")
def test_broader_question_in_book_panel_sends_nothing_to_library(bot, events):
    searches = spy(bot)
    bot.model.routes.append({"type": "other_authors", "confidence": 0.9, "names": []})
    items = bot.ask(
        question="а что думали другие авторы?", context="book", source_id=bot.rig.ids["ru"]
    )
    assert types(items) == ["handoff", "done"]
    assert items[0]["reason"] == "broader"
    assert searches.queries == []  # по всем источникам ничего не искали
    assert [r.template for r in bot.model.requests] == ["assistant.route"]  # ответа нет
    assert events.one("assistant.handoff")["reason"] == "broader"
    events.assert_none("assistant.searched")
    events.assert_none("assistant.answer.completed")


@req(AD, "Общий вопрос", invariant="Ответ по всей библиотеке только после перехода в раздел")
def test_library_answer_only_in_assistant_section(bot, events):
    bot.model.routes.append({"type": "other_authors", "confidence": 0.9, "names": []})
    bot.ask(question="другие авторы?", context="book", source_id=bot.rig.ids["ru"])
    assert not events.of("assistant.searched")
    events.clear()
    # после перехода (context=library) тот же вопрос отвечается по всем источникам
    bot.model.routes.append({"type": "other_authors", "confidence": 0.9, "names": []})
    items = bot.ask(question="другие авторы?", context="library", source_id=bot.rig.ids["ru"])
    assert events.of("assistant.searched") and "fragment" in types(items)
    events.assert_none("assistant.handoff")


@req(AD, "Общий вопрос", scenario="Вопрос без выделения")
def test_question_without_selection_answers_from_library(bot, events):
    bot.model.routes.append({"type": "knowledge", "confidence": 0.9, "names": []})
    bot.model.answers.append(
        lambda prompt: [f"Юм считал причинность привычкой [{bot.number(prompt, 'привычка ума')}]. "]
    )
    items = bot.ask(question="что считал Юм о причинности?")
    fragment = next(i for i in items if i["type"] == "fragment")
    assert fragment["grounded"] and fragment["citations"][0]["paragraph_id"] == bot.para(
        "привычка ума"
    )
    assert events.one("assistant.routed")["type"] == "knowledge"
    assert events.one("assistant.question.received")["has_selection"] is False
    assert events.one("assistant.answer.completed")["grounded"] == 1


@req(AD, "Ответ потоком", scenario="Остановка")
def test_stop_keeps_received_part_and_logs_stopped(bot, events):
    """Клиент закрыл поток после первого фрагмента: генерация прекращена, событие stopped."""
    bot.model.answers.append(["Юм пишет о привычке [1]. ", "Кант ответил Юму [2]. ", "Третий. "])
    stream = bot.assistant.ask(AskRequest(question="что пишет Юм?", visitor="v"))
    received = []
    for item in stream:
        received.append(item)
        if item["type"] == "fragment":
            break
    stream.close()  # читатель нажал «Остановить»: клиент оборвал соединение
    assert types(received).count("fragment") == 1
    assert events.one("assistant.stopped")["fragments"] == 1
    events.assert_none("assistant.answer.completed")
    events.assert_none("assistant.answer.interrupted")


@req(AD, "Ответ потоком", invariant="Ссылки и пометки приходят вместе с фрагментом")
def test_every_fragment_carries_citations_and_mark(bot):
    bot.model.answers.append(["Юм пишет о привычке [1]. ", "Это без опоры. ", "И ссылка [2]. "])
    items = bot.ask(question="что пишет Юм?")
    fragments = [i for i in items if i["type"] == "fragment"]
    assert len(fragments) == 3
    for fragment in fragments:
        assert isinstance(fragment["grounded"], bool)
        assert fragment["grounded"] is bool(fragment["citations"])
    assert types(items)[-1] == "done"


@req(AD, "Ошибка посреди ответа", scenario="Обрыв")
def test_stream_break_keeps_marks_and_offers_retry(bot, events):
    bot.model.answers.append(
        ["Юм пишет о привычке [1]. ", "Без опоры. ", TransientProviderError("обрыв")]
    )
    items = bot.ask(question="что пишет Юм?")
    fragments = [i for i in items if i["type"] == "fragment"]
    assert [f["grounded"] for f in fragments] == [True, False]  # пометки не потеряны
    assert items[-1] == {
        "type": "error",
        "message": "Ответ оборвался. Можно повторить.",
        "retry": True,
    }
    interrupted = events.one("assistant.answer.interrupted")
    assert interrupted["fragments"] == 2 and interrupted["error_kind"] == "stream_broken"
    events.assert_none("assistant.answer.completed")


@req(AD, "Недоступность и лимиты", scenario="Лимит исчерпан")
def test_daily_budget_exhausted_message(bot, events):
    reservation = bot.gateway.store.reserve("site", "2026-11-04", None, 0, bot.gateway.clock.now())
    bot.gateway.store.settle(reservation, 10.0)
    items = bot.ask(question="что такое опыт?")
    assert len(items) == 1 and items[0]["reason"] == "budget_exhausted"
    assert "недоступен" in items[0]["message"] and "завтра" in items[0]["message"]
    assert "Чтение и карточки работают" in items[0]["message"]
    assert events.one("assistant.refused")["reason"] == "budget_exhausted"
    events.assert_none("assistant.answer.completed")


@req(AD, "Недоступность и лимиты", invariant="Модель недоступна: понятное сообщение")
def test_model_unavailable_message(bot, events):
    def broken(*_a, **_k):
        raise LlmUnavailable("provider_unavailable")
        yield  # pragma: no cover

    bot.assistant.llm.stream = broken
    items = bot.ask(question="что такое опыт?")
    assert items[-1]["type"] == "unavailable" and items[-1]["reason"] == "llm_unavailable"
    assert "Чтение и карточки работают" in items[-1]["message"]
    assert events.one("assistant.refused")["reason"] == "llm_unavailable"


@req(AD, "Недоступность и лимиты", invariant="Лимит запросов посетителя: когда спросить снова")
def test_visitor_limit_tells_when_to_retry_and_recovers(bot, clock, events):
    for i in range(5):
        assert bot.ask(question=f"вопрос номер {i}")[-1]["type"] == "done"
    limited = bot.ask(question="шестой")
    assert limited[0]["reason"] == "visitor_limit"
    wait = limited[0]["retry_after_seconds"]
    assert 0 < wait <= 3601 and "через" in limited[0]["message"]
    assert events.where("assistant.refused", reason="visitor_limit")
    clock.advance(seconds=wait - 1)
    assert bot.ask(question="рано")[0]["type"] == "unavailable"
    clock.advance(seconds=2)
    assert bot.ask(question="теперь можно")[-1]["type"] == "done"


@req(AD, "Память диалога", scenario="Уточнение")
def test_followup_carries_history_to_router_and_answer(bot, events):
    history = [{"question": "что Юм думал о причинности?", "answer": "Привычка ума [1]."}]
    bot.ask(question="а у Канта?", history=history)
    for request in (route_request(bot), answer_request(bot)):
        content = request.messages[-1].content
        assert "что Юм думал о причинности?" in content and "Привычка ума" in content
    assert "а у Канта?" in answer_request(bot).messages[-1].content
    assert events.one("assistant.answer.completed")["type"] == "knowledge"


@req(AD, "Память диалога", scenario="Новый диалог")
def test_new_dialog_sends_no_history(bot, events):
    bot.ask(question="что Юм думал о причинности?", history=[])
    content = answer_request(bot).messages[-1].content
    assert "Вопрос:" not in content and "Раньше читатель" not in content
    assert "Вопрос:" not in route_request(bot).messages[-1].content
    events.one("assistant.answer.completed")


@req(AD, "Память диалога", invariant="Длинная история: последние обмены и краткое изложение")
@pytest.mark.parametrize("turns", [1, 3, 4, 10])
def test_history_over_limit_keeps_last_turns_and_summary(bot, events, turns):
    history = [{"question": f"вопрос-{i}", "answer": f"ответ-{i}"} for i in range(turns)]
    bot.ask(question="и ещё?", history=history)
    content = answer_request(bot).messages[-1].content
    for turn in history[-3:]:
        assert f"Вопрос: {turn['question']}" in content
    earlier = history[:-3]
    if earlier:
        assert "Раньше читатель спрашивал: " + "; ".join(t["question"] for t in earlier) in content
        for turn in earlier:
            assert f"Вопрос: {turn['question']}" not in content  # только краткое изложение
    else:
        assert "Раньше читатель" not in content
    events.one("assistant.answer.completed")


@req(AD, "Память диалога", invariant="История одной книги не попадает в запрос другой")
def test_history_is_only_what_the_request_carries(bot, events):
    bot.ask(question="первый вопрос книги А", source_id=bot.rig.ids["ru"])
    bot.ask(question="вопрос книги Б", source_id=bot.rig.ids["en"])
    assert "первый вопрос книги А" not in last_answer_content(bot)
    assert len(events.of("assistant.answer.completed")) == 2


@req(AD, "Язык ответа", scenario="Вопрос на английском")
def test_english_question_answer_language(bot, events):
    items = bot.ask(question="What did Hume think about causation?")
    assert "английский" in answer_request(bot).messages[-1].content
    assert items[-1]["answer_language"] == "английский"
    assert events.one("assistant.answer.completed")["type"] == "knowledge"


@req(AD, "Язык ответа", invariant="Язык ответа — язык вопроса")
@pytest.mark.parametrize(
    ("question", "language"),
    [
        ("Что Юм думал о привычке?", "русский"),
        ("What is empiricism?", "английский"),
        ("Hume и причинность", "русский"),
        ("12345 ???", "русский"),
        ("Kant, Hume и Locke", "английский"),
    ],
)
def test_answer_language_by_question(bot, events, question, language):
    items = bot.ask(question=question)
    assert items[-1]["answer_language"] == language
    assert language in answer_request(bot).messages[-1].content
    events.one("assistant.answer.completed")


@req(AD, "Язык ответа", invariant="Цитаты приводятся на языке источника")
def test_quote_stays_in_source_language(events):
    passage = Passage(
        1, "p1", "s1", "c1", "Chapter 1", "Locke described the mind at birth as a blank slate."
    )
    good = verify("Локк писал: «the mind at birth as a blank slate» [1].", {1: passage})
    assert good.grounded and "«the mind at birth as a blank slate»" in good.text
    translated = verify("Локк писал: «ум при рождении как чистая доска» [1].", {1: passage})
    assert not translated.grounded and "«" not in translated.text  # перевод не выдан за цитату


@req(AD, "Граница книги", scenario="Шире книги")
def test_broader_boundary_event(bot, events):
    bot.model.routes.append({"type": "other_authors", "confidence": 0.9, "names": []})
    items = bot.ask(question="а что другие?", context="book", source_id="src")
    assert types(items) == ["handoff", "done"] and items[-1]["stats"]["fragments"] == 0
    assert events.one("assistant.handoff")["reason"] == "broader"


@req(AD, "Граница книги", scenario="Вне книги")
def test_outside_book_answer_kept_with_handoff_after(bot, events):
    bot.model.routes.append({"type": "knowledge", "confidence": 0.9, "names": []})
    bot.model.answers.append(["Ответ по источнику [1]. ", "Без опоры. "])
    items = bot.ask(question="что пишут в других книгах?", context="book", source_id="другая")
    kinds = types(items)
    assert kinds.index("fragment") < kinds.index("handoff") < kinds.index("done")
    assert [f["grounded"] for f in items if f["type"] == "fragment"] == [True, False]
    assert next(i for i in items if i["type"] == "handoff")["reason"] == "outside_book"
    assert events.one("assistant.handoff")["reason"] == "outside_book"
    assert events.one("assistant.answer.completed")["fragments"] == 2


@req(AD, "Граница книги", invariant="Отказ от перехода не повторяет границу")
def test_declined_boundary_does_not_repeat(bot, events):
    bot.model.routes.append({"type": "other_authors", "confidence": 0.9, "names": []})
    items = bot.ask(
        question="а что другие?",
        context="book",
        source_id="src",
        handoff_declined=True,
        handoff_reason="broader",
    )
    assert "handoff" not in types(items) and "fragment" in types(items)
    events.assert_none("assistant.handoff")
    events.clear()
    bot.model.routes.append({"type": "knowledge", "confidence": 0.9, "names": []})
    items = bot.ask(
        question="а что другие?",
        context="book",
        source_id="другая",
        handoff_declined=True,
        handoff_reason="outside_book",
    )
    assert "handoff" not in types(items)
    events.assert_none("assistant.handoff")
