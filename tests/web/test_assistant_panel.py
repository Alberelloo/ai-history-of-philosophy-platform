"""Требования спецификации assistant-dialog: панель в браузере, сервер и журнал."""

from __future__ import annotations

import threading
import time

import pytest

from philograph.library.app import build_app as library_app
from philograph.llm.providers import TransientProviderError

from ..assistant.conftest import bot  # noqa: F401 — стенд ассистента как фикстура
from ..helpers import aside
from ..search.conftest import rig as search_rig  # noqa: F401
from .conftest import DIST, _free_port

req = pytest.mark.req
AD = "assistant-dialog"


@pytest.fixture
def server(bot):
    if not (DIST / "index.html").exists():
        pytest.skip("клиент не собран: npm run build в web/")
    import uvicorn

    from philograph.assistant.app import build_app as assistant_app
    from philograph.library.reading import Reading
    from philograph.llm.app import build_app as llm_app
    from philograph.platform.client import ServiceClient

    def serve(app):
        port = _free_port()
        srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(target=srv.run, daemon=True)
        thread.start()
        while not srv.started:
            time.sleep(0.05)
        return f"http://127.0.0.1:{port}", srv, thread

    # Сервис LLM — на настоящем порту: ответ модели идёт потоком по HTTP, как в работе.
    llm_url, llm_srv, llm_thread = serve(llm_app(bot.gateway))
    bot.assistant.llm.client = ServiceClient("llm", llm_url, timeout=30)
    rig = bot.rig
    reading = Reading(rig.registry, rig.registry.engine)
    url, srv, thread = serve(
        library_app(reading, web_root=DIST, mounts={"/api/assistant": assistant_app(bot.assistant)})
    )
    yield url, bot
    for s, th in ((srv, thread), (llm_srv, llm_thread)):
        s.should_exit = True
        th.join(5)


def open_reader(page, url, bot):
    page.goto(f"{url}/read/{bot.rig.ids['ru']}")
    page.wait_for_selector(".chapter p")
    aside(page)  # перед кликом по кнопке над текстом: панель раскрывается наведением


def select_text(page, needle):
    page.evaluate(
        """needle => {
        const p = [...document.querySelectorAll('p.block')].find(e => e.innerText.includes(needle));
        const range = document.createRange(); range.selectNodeContents(p.firstChild);
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range);
        p.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
    }""",
        needle,
    )


@req(AD, "Вопрос о выделенном фрагменте")
def test_ask_about_selection(page, server, events):
    url, bot = server
    open_reader(page, url, bot)
    select_text(page, "привычка ума")
    page.get_by_role("button", name="Спросить ассистента").click()
    panel = page.get_by_role("complementary", name="Ассистент")
    assert "привычка ума" in panel.locator(".selection-context").inner_text()
    bot.model.routes.append({"type": "local", "confidence": 0.9, "names": []})
    bot.model.answers.append(["Это значит, что связь причин выводится из привычки [1]. "])
    panel.get_by_role("button", name="Спросить").click()
    panel.locator(".fragment").first.wait_for()
    assert events.one("assistant.question.received")["has_selection"] is True
    assert "Объясни этот фрагмент" in bot.model.requests[-1].messages[-1].content
    searched = events.of("assistant.searched")[0]
    assert searched["scope"] == "current"


@req(AD, "Панель действий над выделением")
def test_selection_toolbar(page, server):
    url, bot = server
    open_reader(page, url, bot)
    select_text(page, "привычка ума")
    toolbar = page.get_by_role("toolbar", name="Действия с выделенным")
    toolbar.wait_for()
    assert toolbar.get_by_role("button", name="Спросить ассистента").is_visible()
    assert toolbar.get_by_role("button", name="Скопировать ссылку на абзац").is_visible()


@req(AD, "Ограничение длины")
def test_length_limit(bot, events):
    items = bot.ask(question="что это?", selection="а" * 5000)
    assert items == [
        {
            "type": "refused",
            "reason": "too_long",
            "message": "Слишком длинный фрагмент или вопрос: выделите меньше.",
        }
    ]
    assert not [c for c in bot.gateway.store.calls() if c["operation"] == "route"]


@req(AD, "Общий вопрос")
def test_general_question_answers_with_citations(bot, events):
    bot.model.answers.append(
        lambda prompt: [
            f"Юм считал причинность привычкой ума [{bot.number(prompt, 'привычка ума')}]. "
        ]
    )
    items = bot.ask(question="что считал Юм о причинности?")
    fragment = next(i for i in items if i["type"] == "fragment")
    assert fragment["grounded"] and fragment["citations"]
    assert events.one("assistant.routed")["type"] == "knowledge"


@req(AD, "Ответ потоком")
def test_stream_and_stop(page, server, events):
    url, bot = server
    open_reader(page, url, bot)
    page.get_by_role("button", name="Ассистент").click()
    panel = page.get_by_role("complementary", name="Ассистент")
    bot.model.answers.append(
        ["Юм пишет о привычке [1]. ", 0.3, "Затем о будущем [1]. ", 3.0, "Конец [1]. "]
    )
    panel.get_by_label("Вопрос ассистенту").fill("что пишет Юм о привычке?")
    panel.get_by_role("button", name="Спросить").click()
    panel.locator(".fragment").first.wait_for()  # первый фрагмент до конца ответа
    assert panel.locator(".answer").get_attribute("data-status") == "streaming"
    panel.get_by_role("button", name="Остановить").click()

    panel.locator(".status-mark", has_text="остановлено").wait_for()
    assert panel.locator(".fragment").count() >= 1


@req(AD, "Место в тексте не теряется")
def test_reading_position_kept(page, server):
    url, bot = server
    open_reader(page, url, bot)
    page.evaluate("window.scrollTo(0, 200)")
    before = page.evaluate("window.scrollY")
    page.get_by_role("button", name="Ассистент").click()
    page.get_by_role("complementary", name="Ассистент").wait_for()
    page.get_by_role("button", name="Закрыть ассистента").click()
    assert page.evaluate("window.scrollY") == before


@req(AD, "Память диалога")
def test_dialog_memory(page, server, bot, events):
    url, _ = server
    open_reader(page, url, bot)
    page.get_by_role("button", name="Ассистент").click()
    panel = page.get_by_role("complementary", name="Ассистент")
    bot.model.answers.append(["Юм считал причинность привычкой [1]. "])
    panel.get_by_label("Вопрос ассистенту").fill("что Юм думал о причинности?")
    panel.get_by_role("button", name="Спросить").click()
    panel.locator(".turn").first.locator(".fragment").wait_for()
    page.wait_for_timeout(200)
    panel.get_by_label("Вопрос ассистенту").fill("а у Канта?")
    panel.get_by_role("button", name="Спросить").click()
    panel.locator(".turn").nth(1).locator(".fragment").wait_for()
    prompt = bot.model.requests[-1].messages[-1].content
    assert "что Юм думал о причинности?" in prompt  # история передана
    page.reload()
    page.get_by_role("button", name="Ассистент").click()
    assert panel.locator(".turn").count() == 2  # диалог в браузере
    panel.get_by_role("button", name="Новая сессия", exact=True).click()
    assert panel.locator(".turn").count() == 0
    long_history = [{"question": f"вопрос {i}", "answer": "ответ"} for i in range(6)]
    bot.ask(question="и ещё?", history=long_history)
    assert "Раньше читатель спрашивал: вопрос 0; вопрос 1; вопрос 2" in (
        bot.model.requests[-1].messages[-1].content
    )


@req(AD, "Язык ответа")
def test_answer_language_follows_question(bot):
    bot.ask(question="What did Hume think about causation?")
    assert "английский" in bot.model.requests[-1].messages[-1].content
    bot.ask(question="Что Юм думал о привычке?")
    assert "русский" in bot.model.requests[-1].messages[-1].content


@req(AD, "Недоступность и лимиты")
def test_unavailable_and_limits(bot, events):
    for i in range(5):
        bot.ask(question=f"вопрос номер {i}")
    limited = bot.ask(question="шестой вопрос")
    assert limited[0]["type"] == "unavailable" and limited[0]["reason"] == "visitor_limit"
    assert limited[0]["retry_after_seconds"] > 0

    bot.assistant.limits.per_hour = 100
    reservation = bot.gateway.store.reserve("site", "2026-11-04", None, 0, bot.gateway.clock.now())
    bot.gateway.store.settle(reservation, 10.0)  # дневной лимит исчерпан
    items = bot.ask(question="что такое опыт?")
    assert items[0]["reason"] == "budget_exhausted" and "завтра" in items[0]["message"]
    assert events.where("assistant.refused", reason="budget_exhausted")


@req(AD, "Ошибка посреди ответа")
def test_error_mid_answer_keeps_marks(page, server):
    url, bot = server
    open_reader(page, url, bot)
    page.get_by_role("button", name="Ассистент").click()
    panel = page.get_by_role("complementary", name="Ассистент")
    bot.model.answers.append(
        ["Юм пишет о привычке [1]. ", "Без опоры. ", TransientProviderError("обрыв")]
    )
    panel.get_by_label("Вопрос ассистенту").fill("что пишет Юм?")
    panel.get_by_role("button", name="Спросить").click()
    panel.get_by_role("button", name="Повторить").wait_for()
    assert panel.locator(".fragment").count() == 2
    assert panel.locator(".fragment.ungrounded").count() == 1  # пометка не потерялась
    assert "оборвался" in panel.locator(".assistant-notice").inner_text()


@req(AD, "Память диалога")
def test_sessions_are_separate(page, server, bot):
    url, _ = server
    open_reader(page, url, bot)
    page.get_by_role("button", name="Ассистент").click()
    panel = page.get_by_role("complementary", name="Ассистент")
    bot.model.answers.append(["Юм считал причинность привычкой [1]. "])
    panel.get_by_label("Вопрос ассистенту").fill("что Юм думал о причинности?")
    panel.get_by_role("button", name="Спросить").click()
    panel.locator(".turn").first.locator(".fragment").wait_for()
    # «+» — вторая сессия, пустая; «+» при пустой активной не плодит третью.
    panel.get_by_role("button", name="Новая сессия", exact=True).click()
    assert panel.locator(".turn").count() == 0
    panel.get_by_role("button", name="Новая сессия", exact=True).click()
    # Список сессий всегда на виду: две строки.
    assert panel.locator(".assistant__sessions .assistant__session").count() == 2
    # Возврат к первой сессии по списку (сначала новые, 5.8): там только первый вопрос.
    panel.locator(".assistant__session-title", has_text="причинности").click()
    assert panel.locator(".turn").count() == 1
    assert "причинности" in panel.locator(".turn").first.inner_text()


@req(AD, "Ход ответа")
def test_answer_stages_visible(page, server, bot):
    url, _ = server
    open_reader(page, url, bot)
    page.get_by_role("button", name="Ассистент").click()
    panel = page.get_by_role("complementary", name="Ассистент")
    bot.model.answers.append(["Юм пишет о привычке [1]. ", 1.0, "Кант ответил [1]. "])
    panel.get_by_label("Вопрос ассистенту").fill("что пишет Юм?")
    panel.get_by_role("button", name="Спросить").click()
    # Стадия видна во время потока; номер «N из 4», без процента и счётчика слов.
    panel.locator(".assistant__stage").first.wait_for()
    stage_text = panel.locator(".assistant__stage").first.inner_text()
    assert "из 4" in stage_text
    assert "%" not in stage_text and "слов" not in stage_text
    panel.locator(".fragment").first.wait_for()


@req(AD, "Раздел «Ассистент»")
def test_assistant_page_and_stub(page, server):
    url, _ = server
    page.goto(f"{url}/assistant")
    page.wait_for_selector(".assistant-page")
    assert "по всей библиотеке" in page.locator(".assistant-page__subtitle").inner_text()
    # Старая закладка /soon/assistant заменяется на /assistant.
    page.goto(f"{url}/soon/assistant")
    page.wait_for_url("**/assistant")


@req(AD, "Переход с вопросом из панели")
def test_handoff_block_and_transfer_link(page, server, bot):
    url, _ = server
    open_reader(page, url, bot)
    page.get_by_role("button", name="Ассистент").click()
    panel = page.get_by_role("complementary", name="Ассистент")
    bot.model.routes.append({"type": "other_authors", "confidence": 0.9, "names": []})
    panel.get_by_label("Вопрос ассистенту").fill("а что думали другие авторы?")
    panel.get_by_role("button", name="Спросить").click()
    panel.locator(".handoff-block").wait_for()
    assert "выходит за границы" in panel.locator(".handoff-block").inner_text()
    link = panel.locator(".handoff-block a")
    assert "/assistant?q=" in (link.get_attribute("href") or "")
    # Кнопка «Продолжить в рамках этого источника» отправляет новый обмен с handoff_declined.
    panel.locator(".handoff-block button", has_text="Продолжить").click()
    panel.locator(".handoff-block").wait_for(state="detached")


# --- «Спросить об абзаце» и тройной щелчок (5.1, 7) -------------------------------------


@req(AD, "Вопрос о выделенном фрагменте")
def test_ask_about_paragraph_button(page, site):
    """Кнопка «Спросить об абзаце» под «Скопировать ссылку»: фрагмент — текст абзаца, один id;
    у плашки неразобранной части кнопки нет."""
    from ..assistant.browser import AskStub, answer, ask, fragment, panel
    from .test_assistant_dialogs import chapters

    (chapter_id, paras), *_ = chapters(site)
    source = site.ids["textbook"]
    real = page.request.get(f"{site.url}/api/v1/sources/{source}/chapters/{chapter_id}").json()
    real["blocks"].insert(
        0,
        {
            "type": "block",
            "id": "p-plate",
            "kind": "unrendered",
            "text": "",
            "lang": "ru",
            "pages": [],
            "notes": [],
            "detail": None,
            "detail_code": "missing",
            "page": None,
        },
    )
    page.route(f"**/sources/{source}/chapters/{chapter_id}", lambda r: r.fulfill(json=real))
    page.set_viewport_size({"width": 1440, "height": 900})
    stub = AskStub(page).reply(answer(fragment("Ответ об абзаце.", grounded=False)))
    page.goto(f"{site.url}/read/{source}/{chapter_id}")
    target, text = paras[2]
    block = page.locator(f"#p-{target}")
    block.wait_for()
    assert page.locator("figure.unrendered .ask-paragraph").count() == 0
    block.hover()
    button = block.get_by_role("button", name="Спросить об абзаце")
    assert button.is_visible()
    # Под «Скопировать ссылку», в левом промежутке, не поверх текста.
    copy = block.locator(".copy-link").bounding_box()
    own = button.bounding_box()
    para = block.evaluate("e => e.getBoundingClientRect().left")
    assert own["y"] >= copy["y"] + copy["height"] and own["x"] + own["width"] <= para
    button.click()
    box = panel(page)
    quote = box.locator(".assistant__form .selection-context")
    quote.wait_for()
    assert quote.inner_text().strip() == text.strip()
    ask(box, "О чём этот абзац?")
    box.locator(".copy-answer").wait_for()
    assert stub.requests[0]["selection_paragraphs"] == [target]
    assert stub.requests[0]["selection"].strip() == text.strip()


@req(AD, "Панель действий над выделением")
def test_triple_click_selects_one_paragraph(page, site):
    """Тройной щелчок по абзацу → «Спросить ассистента» → фрагмент одного абзаца, без соседнего."""
    from ..assistant.browser import AskStub, answer, ask, fragment, panel
    from .test_assistant_dialogs import chapters, open_book

    (_, paras), *_ = chapters(site)
    page.set_viewport_size({"width": 1440, "height": 900})
    stub = AskStub(page).reply(answer(fragment("Ответ.", grounded=False)))
    open_book(page, site)
    target, text = paras[3]
    page.locator(f"#p-{target}").click(click_count=3)
    toolbar = page.get_by_role("toolbar")
    toolbar.get_by_role("button", name="Спросить ассистента").click()
    box = panel(page)
    box.locator(".assistant__form .selection-context").wait_for()
    ask(box, "Поясните")
    box.locator(".copy-answer").wait_for()
    request = stub.requests[0]
    assert request["selection_paragraphs"] == [target], request["selection_paragraphs"]
    assert text.strip() in request["selection"]
