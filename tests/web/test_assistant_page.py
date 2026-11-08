"""Раздел «Ассистент» и переход в него из панели книги (reader-panels.md, 5.10).

Тесты T36, T41, T42, T43, T46 из 14.2. Ответ ассистента подменяется готовыми строками NDJSON
(``tests/assistant/browser.py``), книги — настоящие из стенда библиотеки.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote

import pytest

from ..assistant.browser import (
    DONE,
    STORAGE,
    AskStub,
    answer,
    ask,
    cite,
    fragment,
    ndjson,
    open_assistant,
    panel,
    stored,
)
from ..helpers import reader_context
from .test_assistant_dialogs import chapters, open_book

req = pytest.mark.req
AD = "assistant-dialog"
VD = "visual-design"
QUESTION = "А что думали другие авторы?"
BROADER = ndjson(
    {"type": "stage", "name": "searching"}, {"type": "handoff", "reason": "broader"}, DONE
)


@pytest.fixture
def wide(page):
    page.set_viewport_size({"width": 1440, "height": 900})
    return page


def library_turns(page) -> list[dict]:
    return [m for s in stored(page)["libraryDialogs"]["sessions"] for m in s["messages"]]


def library_requests(stub) -> list[dict]:
    return [r for r in stub.requests if r["context"] == "library"]


def handoff_block(page):
    block = panel(page).locator(".handoff-block")
    block.wait_for()
    return block


# --- T41, T42: переход отправляет один раз ------------------------------------


@req(AD, "Переход с вопросом из панели")
def test_t41_transfer_sends_once(wide, site):
    """T41: щелчок (и двойной) по ссылке — ровно один запрос; «Назад», «Вперёд», повтор — нет."""
    page = wide
    stub = AskStub(page).reply(
        BROADER, answer(fragment("Ответ по всей библиотеке.", grounded=False))
    )
    sid = open_book(page, site)
    open_assistant(page)
    ask(panel(page), QUESTION)
    block = handoff_block(page)
    assert len(stub.requests) == 1  # до выбора — ничего не отправлено
    link = block.get_by_role("link", name="Перейти в «Ассистент» и продолжить по всем источникам")
    href = link.get_attribute("href") or ""
    assert href.startswith(f"/assistant?q={quote(QUESTION, safe='')}") and f"from={sid}" in href
    link.dblclick()
    page.wait_for_url("**/assistant?q=*")
    page.locator(".assistant-page .copy-answer").wait_for()
    page.wait_for_timeout(300)
    sent = library_requests(stub)
    assert len(sent) == 1
    assert sent[0]["question"] == QUESTION and sent[0]["source_id"] == sid
    turns = library_turns(page)
    assert len(turns) == 1 and turns[0]["handoffId"]
    assert "Из книги «История теории познания»" in page.locator(".handoff-from").inner_text()
    # «Назад» и «Вперёд» — запросов нет.
    page.go_back()
    page.wait_for_url(re.compile(rf"/read/{sid}"))
    page.go_forward()
    page.wait_for_url("**/assistant?q=*")
    page.locator(".assistant-page .turn").wait_for()
    page.wait_for_timeout(300)
    assert len(library_requests(stub)) == 1
    # В панели книги — «Открыть ответ в разделе «Ассистент»», без новой отправки.
    page.go_back()
    page.wait_for_url(re.compile(rf"/read/{sid}"))
    page.wait_for_selector(".chapter [data-paragraph]")
    open_assistant(page)
    opened = panel(page).get_by_role("link", name="Открыть ответ в разделе «Ассистент»")
    assert panel(page).locator(".handoff-block").count() == 0
    book_turn = stored(page)["dialogs"][sid]["sessions"][0]["messages"][0]
    assert book_turn["handoff"]["choice"] == "library" and book_turn["handoff"]["sent"] is True
    opened.click()
    page.wait_for_url(re.compile(r"/assistant$"))
    page.locator(".assistant-page .turn").wait_for()
    page.wait_for_timeout(300)
    assert len(library_requests(stub)) == 1 and len(library_turns(page)) == 1


@req(AD, "Переход с вопросом из панели")
def test_t42_reload_and_direct_address_do_not_send(browser, site):
    """T42: перезагрузка, прямой адрес, новая вкладка (Ctrl+щелчок) и незакрытое уведомление."""
    context = reader_context(browser, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    stub = AskStub(page).reply(BROADER, answer(fragment("Ответ.", grounded=False)))
    sid = open_book(page, site)
    open_assistant(page)
    ask(panel(page), QUESTION)
    handoff_block(page).get_by_role("link", name=re.compile("^Перейти")).click()
    page.locator(".assistant-page .copy-answer").wait_for()
    assert len(library_requests(stub)) == 1
    # Перезагрузка после отправки: «уже задан», вопрос в поле, запроса нет.
    page.reload()
    page.locator(".assistant__asked").wait_for()
    assert "Этот вопрос уже задан" in page.locator(".assistant__asked").inner_text()
    assert page.get_by_label("Вопрос ассистенту").input_value() == QUESTION
    page.locator(".assistant__asked").get_by_role("button", name="Показать ответ").click()
    page.wait_for_timeout(300)
    assert len(library_requests(stub)) == 1
    # Прямой адрес в новой вкладке: «перенесён и не отправлен»; «Спросить» — ровно один запрос.
    other = context.new_page()
    other_stub = AskStub(other).reply(answer(fragment("Ответ два.", grounded=False)))
    other.goto(f"{site.url}/assistant?q={quote('Новый вопрос')}&from={sid}")
    pending = other.locator(".assistant__pending", has_text="История теории познания")
    pending.wait_for()
    assert "Вопрос перенесён из книги «История теории познания» и ещё не отправлен" in (
        pending.inner_text()
    )
    assert other.get_by_label("Вопрос ассистенту").input_value() == "Новый вопрос"
    other.wait_for_timeout(300)
    assert other_stub.requests == []
    other.get_by_role("button", name="Спросить", exact=True).click()
    other.locator(".turn").nth(1).locator(".copy-answer").wait_for()
    assert len(other_stub.requests) == 1 and other_stub.requests[0]["source_id"] == sid
    other.close()
    # Ctrl+щелчок по ссылке в панели: новая вкладка без отправки.
    stub.reply(BROADER)
    page.goto(f"{site.url}/read/{sid}")
    page.wait_for_selector(".chapter [data-paragraph]")
    open_assistant(page)
    ask(panel(page), "Как это у других?")
    link = panel(page).locator(".handoff-block").get_by_role("link", name=re.compile("^Перейти"))
    before = len(stub.requests)
    with context.expect_page() as opened:
        link.click(modifiers=["Control"])
    tab = opened.value
    tab_stub = AskStub(tab)
    tab.wait_for_load_state()
    tab.locator(".assistant__pending").wait_for()
    tab.wait_for_timeout(300)
    assert tab_stub.requests == [] and len(stub.requests) == before
    tab.close()
    context.close()


@req(AD, "Переход с вопросом из панели")
def test_t42_notice_not_closed_does_not_send(browser, site):
    """T42: щелчок по ссылке при незакрытом уведомлении первого входа — не отправлено, S12."""
    sid = site.ids["textbook"]
    turn = {
        "id": "t-1",
        "question": QUESTION,
        "fragments": [],
        "status": "done",
        "handoff": {"reason": "broader"},
    }
    state = {
        "version": 4,
        "dialogs": {
            sid: {
                "updatedAt": 1,
                "activeId": "s-1",
                "sessions": [
                    {"id": "s-1", "title": "", "createdAt": 1, "updatedAt": 1, "messages": [turn]}
                ],
            }
        },
    }
    context = reader_context(browser, accepted=False, viewport={"width": 1440, "height": 900})
    context.add_init_script(
        f"""if (!sessionStorage.getItem('seeded')) {{
        sessionStorage.setItem('seeded', '1');
        localStorage.setItem('{STORAGE}', {json.dumps(json.dumps(state))});
    }}"""
    )
    page = context.new_page()
    stub = AskStub(page)
    open_book(page, site)
    open_assistant(page)
    handoff_block(page).get_by_role("link", name=re.compile("^Перейти")).click()
    page.wait_for_url("**/assistant?q=*")
    page.locator(".assistant__pending").wait_for()
    assert page.get_by_label("Вопрос ассистенту").input_value() == QUESTION
    assert "Прочитайте уведомление" in page.locator(".assistant-page").inner_text()
    page.wait_for_timeout(300)
    assert stub.requests == [] and library_turns(page) == []
    context.close()


# --- T43: страница раздела ------------------------------------------------------


@req(AD, "Раздел «Ассистент»")
@req(VD, "Разделы в разработке")
def test_t43_nav_item_current_without_soon(wide, site):
    """T43: пункт «Ассистент» ведёт на /assistant, отмечен текущим, без метки «скоро»."""
    page = wide
    page.goto(f"{site.url}/assistant")
    page.wait_for_selector(".assistant-page")
    item = page.locator(".sidebar").get_by_role("link", name=re.compile("Ассистент"))
    assert item.get_attribute("aria-current") == "page"
    assert item.get_attribute("href") == "/assistant"
    assert "скоро" not in item.inner_text().lower()
    history = page.evaluate("history.length")
    page.goto(f"{site.url}/soon/assistant")
    page.wait_for_url(re.compile(r"/assistant$"))
    assert page.evaluate("history.length") == history + 1  # заменён без новой записи
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


# --- T46: граница и выбор ----------------------------------------------------------


def select_paragraph(page, paragraph: str) -> None:
    page.evaluate(
        """id => { const p = document.getElementById('p-' + id);
        const range = document.createRange(); range.selectNodeContents(p.firstChild);
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range);
        p.dispatchEvent(new MouseEvent('mouseup', {bubbles: true})); }""",
        paragraph,
    )
    page.get_by_role("toolbar").get_by_role("button", name="Спросить ассистента").click()


@pytest.mark.parametrize("kind", ["broader", "outside_book"])
@req(AD, "Граница книги")
def test_t46_boundary_and_stay_in_book(wide, site, kind):
    """T46: граница обоих видов; до выбора — ничего; «Продолжить в рамках» — запрос по книге."""
    page = wide
    sid, other = site.ids["textbook"], site.ids["primary"]
    (ch, paras), *_ = chapters(site)
    (other_ch, other_paras), *_ = chapters(site, "primary")
    if kind == "broader":
        first = BROADER
    else:
        first = ndjson(
            {"type": "stage", "name": "searching"},
            {"type": "stage", "name": "composing", "found": 1},
            fragment("У Канта иначе.", cite(other, other_ch, other_paras[0][0])),
            fragment("Связь неочевидна.", grounded=False),
            {"type": "handoff", "reason": "outside_book"},
            DONE,
        )
    stub = AskStub(page).reply(
        first, answer(fragment("Ответ по книге.", cite(sid, ch, paras[0][0])))
    )
    open_book(page, site)
    select_paragraph(page, paras[0][0])
    box = panel(page)
    box.get_by_label("Вопрос ассистенту").fill(QUESTION)
    box.get_by_role("button", name="Спросить", exact=True).click()
    block = handoff_block(page)
    text = block.inner_text()
    if kind == "broader":
        assert "Ваш ответ выходит за границы этого источника" in text
        assert (
            box.locator(".fragment").count() == 0
            and box.locator(".pg-generated__mark").count() == 0
        )
    else:
        assert "В этой книге ответа нет" in text
        assert box.locator(".fragment").count() == 2
        assert box.locator(".fragment.ungrounded").count() == 1
    assert block.get_by_role("button", name="Продолжить в рамках этого источника").is_visible()
    assert block.get_by_role("link", name=re.compile("^Перейти")).is_visible()
    page.wait_for_timeout(300)
    assert len(stub.requests) == 1  # до выбора запросов нет
    block.get_by_role("button", name="Продолжить в рамках этого источника").click()
    box.locator(".handoff-declined").wait_for()
    assert "Ответ дан только по этой книге" in box.locator(".handoff-declined").inner_text()
    assert box.locator(".handoff-block").count() == 0  # вторая кнопка и ссылка удалены
    box.locator(".turn").nth(1).locator(".copy-answer").wait_for()
    first_request, second = stub.requests
    assert second["context"] == "book" and second["handoff_declined"] is True
    assert second["handoff_reason"] == kind and second["source_id"] == sid
    assert second["question"] == first_request["question"] == QUESTION
    assert second["selection"] == first_request["selection"] and second["selection"]
    assert second["selection_paragraphs"] == [paras[0][0]]
    book = stored(page)["dialogs"][sid]["sessions"][0]["messages"]
    assert book[0]["handoff"] == {"reason": kind, "choice": "book"}
    if kind == "outside_book":
        assert "У Канта иначе." in box.locator(".turn").first.inner_text()  # прежний ответ виден
    assert library_turns(page) == []
    page.wait_for_timeout(300)
    assert len(stub.requests) == 2


# --- T36: язык интерфейса -----------------------------------------------------------

CYRILLIC = """root => {
  const bad = [];
  const walk = (node) => {
    if (node.nodeType === Node.ELEMENT_NODE) {
      const el = node;
      if (el.closest('[lang]:not(html)') && el.closest('[lang]:not(html)').lang !== 'en') return;
      if (el.matches('.question, .selection-context, textarea')) return;  // текст читателя
      el.childNodes.forEach(walk);
      for (const attr of ['aria-label', 'title', 'placeholder']) {
        const v = el.getAttribute(attr);
        if (v && /[А-Яа-яЁё]/.test(v)) bad.push(attr + ': ' + v);
      }
    } else if (node.nodeType === Node.TEXT_NODE && /[А-Яа-яЁё]/.test(node.textContent)) {
      bad.push(node.textContent.trim());
    }
  };
  walk(root);
  return bad;
}"""


@req(VD, "Язык интерфейса")
def test_t36_assistant_page_and_boundary_in_english(browser, site):
    """T36: страница «Ассистент» и граница S7a в EN — без кириллицы в интерфейсе."""
    context = reader_context(browser, locale="en-US", viewport={"width": 1440, "height": 900})
    page = context.new_page()
    stub = AskStub(page).reply(
        BROADER, answer(fragment("Answer across the library.", grounded=False))
    )
    page.goto(f"{site.url}/assistant")
    page.wait_for_selector(".assistant-page")
    assert page.locator(".assistant-page").evaluate(CYRILLIC) == []
    open_book(page, site)
    page.locator(".toc__assistant").click()
    box = page.get_by_role("complementary", name="Assistant")
    box.get_by_label("Question to the assistant").fill("What did other authors think?")
    box.get_by_role("button", name="Ask", exact=True).click()
    box.locator(".handoff-block").wait_for()
    assert box.evaluate(CYRILLIC) == [], box.evaluate(CYRILLIC)
    box.locator(".handoff-block").get_by_role("link").click()
    page.locator(".assistant-page .copy-answer").wait_for()
    assert page.locator(".assistant-page").evaluate(CYRILLIC) == []
    assert len(stub.requests) == 2
    context.close()


@req(AD, "Переход с вопросом из панели")
def test_transfer_shows_book_and_chapter(wide, site):
    """У перенесённого вопроса подпись «Из книги «…», глава «…»» — ссылка на главу."""
    page = wide
    (ch, _), *_ = chapters(site)
    sid = site.ids["textbook"]
    AskStub(page).reply(BROADER, answer(fragment("Ответ по всей библиотеке.", grounded=False)))
    open_book(page, site, chapter=ch)
    open_assistant(page)
    ask(panel(page), QUESTION)
    handoff_block(page).get_by_role("link", name=re.compile("^Перейти")).click()
    page.locator(".assistant-page .copy-answer").wait_for()
    label = page.locator(".handoff-from a")
    assert label.inner_text() == "Из книги «История теории познания», глава «Глава 1. Опыт»"
    assert label.get_attribute("href") == f"/read/{sid}/{ch}"
    assert stored(page)["libraryDialogs"]["sessions"][0]["messages"][0]["from"]["chapterTitle"] == (
        "Глава 1. Опыт"
    )
