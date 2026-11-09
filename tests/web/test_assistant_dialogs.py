"""Панель ассистента в браузере: пометки, ошибки, переходы по ссылкам, диалоги книг и сессии.

Тесты T21–T25, T38–T40, T48 из reader-panels.md (14.2). Ответ ассистента подменяется готовыми
строками NDJSON (``tests/assistant/browser.py``), книга — настоящая из стенда библиотеки.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ..assistant.browser import (
    HOLD,
    STORAGE,
    AskStub,
    answer,
    ask,
    cite,
    fragment,
    go,
    ndjson,
    new_session,
    open_assistant,
    panel,
    stored,
)
from ..helpers import reader_context

req = pytest.mark.req
AD = "assistant-dialog"
AG = "answer-grounding"
RS = "reader-settings"
UNGROUNDED = "[без опоры на источники]"


@pytest.fixture
def wide(page):
    page.set_viewport_size({"width": 1440, "height": 900})
    return page


def open_book(page, site, key: str = "textbook", chapter: str | None = None) -> str:
    sid = site.ids[key]
    page.goto(f"{site.url}/read/{sid}" + (f"/{chapter}" if chapter else ""))
    page.wait_for_selector(".chapter [data-paragraph]")
    return sid


def chapters(site, key: str = "textbook") -> list[tuple[str, list[tuple[str, str]]]]:
    """Главы книги по порядку: (глава, [(абзац, текст)])."""
    result: list[tuple[str, list[tuple[str, str]]]] = []
    for chapter, paragraph, text in site.paragraphs(key):
        if not result or result[-1][0] != chapter:
            result.append((chapter, []))
        result[-1][1].append((paragraph, text))
    return result


def top_of(page, paragraph: str) -> float:
    return page.evaluate(
        "id => document.getElementById('p-' + id).getBoundingClientRect().top", paragraph
    )


# --- T21–T23: пометки и режимы ------------------------------------------------


@req(AG, "Пофрагментная пометка")
@req(AG, "Ссылки на абзацы")
def test_t21_marks_only_ungrounded_fragment_and_copy(wide, site):
    """T21: два фрагмента со ссылками и один без опоры; подсказка ссылки — книга, глава, начало."""
    page = wide
    (ch1, paras), *_ = chapters(site)
    sid = site.ids["textbook"]
    start = paras[0][1][:120]
    stub = AskStub(page).reply(
        answer(
            fragment(
                "Кант пишет об опыте.",
                cite(
                    sid,
                    ch1,
                    paras[0][0],
                    source_title="История теории познания",
                    chapter_title="Глава 1. Опыт",
                    paragraph_start=start,
                ),
            ),
            fragment("Затем о вещи в себе.", cite(sid, ch1, paras[1][0])),
            fragment("Это повлияло на всю философию.", grounded=False),
        )
    )
    open_book(page, site)
    open_assistant(page)
    ask(panel(page), "Что пишет Кант?")
    box = panel(page)
    box.locator(".copy-answer").wait_for()
    frags = box.locator(".fragment")
    assert frags.count() == 3
    marked = ["ungrounded" in (frags.nth(i).get_attribute("class") or "") for i in range(3)]
    assert marked == [False, False, True]
    assert box.locator(".fragment .pg-generated__mark").count() == 1
    assert frags.nth(2).locator(".pg-generated__mark").count() == 1
    title = box.locator(".citation").first.get_attribute("title") or ""
    assert "Глава 1. Опыт" in title and start[:30] in title
    assert stub.requests[0]["context"] == "book" and stub.requests[0]["source_id"] == sid
    box.locator(".copy-answer").click()
    copied = page.evaluate("navigator.clipboard.readText()")
    assert copied.count(UNGROUNDED) == 1
    assert copied.index(UNGROUNDED) > copied.index("Затем о вещи в себе.")


@req(AG, "Генерация без опоры по умолчанию")
def test_t22_notice_without_library_support(wide, site):
    """T22: notice no_library_support — предупреждение над ответом, фрагменты помечены."""
    page = wide
    AskStub(page).reply(
        answer(
            {
                "type": "notice",
                "kind": "no_library_support",
                "message": "Ответ составлен без опоры на библиотеку.",
            },
            fragment("Стоики учили о добродетели.", grounded=False),
        )
    )
    open_book(page, site)
    open_assistant(page)
    ask(panel(page), "Что говорили стоики?")
    box = panel(page)
    box.locator(".copy-answer").wait_for()
    notice = box.locator(".turn .pg-notice--warning")
    assert "без опоры на библиотеку" in notice.inner_text()
    # Предупреждение — над ответом.
    assert notice.bounding_box()["y"] < box.locator(".turn .answer").bounding_box()["y"]
    assert box.locator(".fragment.ungrounded").count() == 1


def seed_settings(page, site, **settings) -> None:
    """Настройки читателя до открытия книги (уведомление уже закрыто)."""
    page.goto(f"{site.url}/settings")
    page.evaluate(
        """([key, settings]) => {
        const s = JSON.parse(localStorage.getItem(key) || '{}');
        s.settings = {...(s.settings || {}), ...settings};
        localStorage.setItem(key, JSON.stringify(s));
    }""",
        [STORAGE, settings],
    )


@req(AG, "Режим «только по источникам»")
def test_t23_sources_only_line_and_nearby(wide, site):
    """T23: строка «только по источникам», ссылка в настройки, «Близкое в библиотеке»."""
    page = wide
    (ch1, paras), *_ = chapters(site)
    target = paras[5][0]
    stub = AskStub(page).reply(
        ndjson(
            {"type": "stage", "name": "searching"},
            {
                "type": "no_answer",
                "message": "В источниках ответа не нашлось.",
                "suggestions": [{"paragraph_id": target, "title": "Об опыте"}],
            },
        )
    )
    seed_settings(page, site, sourcesOnly=True)
    sid = open_book(page, site)
    open_assistant(page)
    box = panel(page)
    line = box.locator(".assistant__sources-only")
    assert "Ассистент отвечает только по источникам." in line.inner_text()
    assert line.get_by_role("link", name="Изменить в настройках").get_attribute("href") == (
        "/settings#assistant"
    )
    ask(panel(page), "Что такое добродетель?")
    box.get_by_text("В источниках ответа не нашлось.").wait_for()
    assert stub.requests[0]["sources_only"] is True
    assert "Близкое в библиотеке:" in box.locator(".assistant__suggestions").inner_text()
    box.locator(".assistant__suggestions").get_by_role("link", name="Об опыте").click()
    page.wait_for_url(re.compile(rf"/read/{sid}/{ch1}#p-{target}$"))
    line.get_by_role("link", name="Изменить в настройках").click()
    page.wait_for_url("**/settings#assistant")


# --- T24: ошибки и недоступность ----------------------------------------------

CODES = [
    # (событие, текст, есть ли «Повторить»)
    (
        {"type": "unavailable", "reason": "budget_exhausted", "message": "…"},
        "Сегодня ассистент недоступен, он заработает завтра. Чтение и карточки работают.",
        False,
    ),
    (
        {"type": "unavailable", "reason": "llm_unavailable", "message": "…"},
        "Ассистент временно недоступен. Чтение и карточки работают.",
        True,
    ),
    (
        {"type": "unavailable", "reason": "visitor_limit", "retry_after_seconds": 120},
        "Слишком много вопросов подряд. Спросите снова через 2 мин. Чтение и карточки работают.",
        False,
    ),
    (
        {"type": "unavailable", "reason": "search_unavailable", "message": "…"},
        "Ответ временно недоступен: поиск не отвечает.",
        True,
    ),
    (
        {"type": "refused", "reason": "off_topic", "message": "…"},
        "Я помогаю разбираться с материалами по философии.",
        False,
    ),
    (
        {"type": "refused", "reason": "too_long", "message": "…"},
        "Слишком длинный фрагмент или вопрос: выделите меньше.",
        False,
    ),
    (
        {"type": "error", "message": "обрыв"},
        "Ответ оборвался. Можно повторить.",
        True,
    ),
]


@req(AD, "Недоступность и лимиты")
@req(AD, "Ошибка посреди ответа")
def test_t24_messages_by_code(wide, site):
    """T24: текст по таблице 5.7 и «Повторить» там, где она указана."""
    page = wide
    stub = AskStub(page)
    open_book(page, site)
    open_assistant(page)
    box = panel(page)
    for i, (event, text, retry) in enumerate(CODES):
        stub.reply(ndjson(event))
        new_session(box)
        ask(panel(page), f"вопрос {i}")
        box.locator(".turn .assistant-notice").wait_for()
        assert box.locator(".turn .assistant-notice").inner_text().strip() == text
        assert box.get_by_role("button", name="Повторить").count() == (1 if retry else 0), text
        if event.get("reason") == "visitor_limit":
            # До конца срока «Спросить» неактивна, запрос не уходит.
            sent = len(stub.requests)
            assert box.get_by_role("button", name="Спросить").get_attribute("aria-disabled")
            box.get_by_label("Вопрос ассистенту").fill("ещё вопрос")
            box.get_by_label("Вопрос ассистенту").press("Enter")
            page.wait_for_timeout(200)
            assert len(stub.requests) == sent
            # Срок в 2 мин тест не ждёт: после перезагрузки вкладки лимита в памяти нет.
            page.reload()
            page.wait_for_selector(".chapter [data-paragraph]")
            open_assistant(page)
    # Обрыв после первого фрагмента: полученная часть с пометкой, сообщение и «Повторить».
    stub.reply(
        ndjson(fragment("Начало ответа.", grounded=False), {"type": "error", "message": "x"})
    )
    new_session(box)
    ask(panel(page), "оборвётся")
    box.get_by_role("button", name="Повторить").wait_for()
    assert box.locator(".fragment.ungrounded").count() == 1
    assert "Оборвалось на стадии" in box.locator(".assistant__summary").inner_text()


@req(AD, "Недоступность и лимиты")
def test_t24_client_timeout(browser, site):
    """T24: 46 с без событий (часы Playwright) — запрос отменён, сообщение и «Повторить»."""
    context = reader_context(browser, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page.clock.install()
    failed: list[str] = []
    page.on("requestfailed", lambda r: failed.append(r.url))
    stub = AskStub(page).reply(HOLD)
    open_book(page, site)
    open_assistant(page)
    ask(panel(page), "ответа не будет")
    box = panel(page)
    box.locator(".assistant__stage").wait_for()
    page.clock.run_for(46_000)
    box.get_by_text("Ассистент не ответил за 45 секунд. Повторите вопрос.").wait_for()
    assert box.get_by_role("button", name="Повторить").is_visible()
    assert any("/api/assistant/v1/ask" in u for u in failed)
    stub.release(answer(fragment("поздно")))  # отменённый запрос не дописывается
    assert box.locator(".fragment").count() == 0
    context.close()


# --- T25: ссылки на абзацы ----------------------------------------------------


@req(AG, "Ссылки на абзацы")
def test_t25_citations_same_and_other_chapter_and_back(wide, site):
    """T25: абзац этой главы — прокрутка и подсветка; другой главы — переход, «Назад» на место."""
    page = wide
    (ch1, paras1), (ch2, paras2), *_ = chapters(site)
    sid = site.ids["textbook"]
    near, far = paras1[30][0], paras2[10][0]
    AskStub(page).reply(
        answer(
            fragment("Об опыте.", cite(sid, ch1, near)),
            fragment("О схемах.", cite(sid, ch2, far)),
        )
    )
    open_book(page, site, chapter=ch1)
    open_assistant(page)
    ask(panel(page), "Где об опыте и схемах?")
    box = panel(page)
    box.locator(".copy-answer").wait_for()
    url = page.url
    box.locator(".citation").nth(0).click()
    page.wait_for_function(
        "id => { const r = document.getElementById('p-' + id).getBoundingClientRect();"
        " return r.top >= 0 && r.top < 200; }",
        arg=near,
    )
    assert "highlight" in (page.locator(f"#p-{near}").get_attribute("class") or "")
    assert page.url == url and box.is_visible()
    page.wait_for_function(
        "id => !document.getElementById('p-' + id).classList.contains('highlight')",
        arg=near,
        timeout=4000,
    )
    # Опорный абзац у верха окна, затем переход в другую главу.
    anchor = paras1[12][0]
    page.evaluate(
        "id => document.getElementById('p-' + id).scrollIntoView({block: 'start'})", anchor
    )
    page.wait_for_timeout(100)
    before = top_of(page, anchor)
    box.locator(".citation").nth(1).click()
    page.wait_for_url(re.compile(rf"/read/{sid}/{ch2}#p-{far}$"))
    page.locator(f"#p-{far}").wait_for()
    assert panel(page).is_visible()
    page.go_back()
    page.wait_for_url(re.compile(rf"/read/{sid}/{ch1}$"))
    page.locator(f"#p-{anchor}").wait_for()
    page.wait_for_function(
        "([id, top]) => Math.abs(document.getElementById('p-' + id).getBoundingClientRect().top"
        " - top) <= 4",
        arg=[anchor, before],
    )
    assert panel(page).is_visible()


# --- T38, T39: диалоги книг ---------------------------------------------------


@req(AD, "Память диалога")
def test_t38_book_dialogs_do_not_mix(wide, site, browser):
    """T38: у книг свои наборы сессий; переход в другую книгу меняет набор; сброс — пусто."""
    page = wide
    a, b = site.ids["textbook"], site.ids["primary"]
    stub = AskStub(page)
    open_book(page, site)
    open_assistant(page)
    box = panel(page)
    for q in ("Вопрос один в A", "Вопрос два в A"):
        stub.reply(answer(fragment(f"Ответ на «{q}».", grounded=False)))
        ask(panel(page), q)
        box.locator(".turn .copy-answer").nth(0).wait_for()
    page.wait_for_function("() => document.querySelectorAll('.turn .copy-answer').length === 2")
    # В книгу B внутри приложения: панель открыта, история B пустая.
    go(page, f"/read/{b}")
    page.wait_for_url(re.compile(rf"/read/{b}/"))
    page.wait_for_function(
        "title => document.querySelector('.assistant__book')?.textContent.includes(title)",
        arg="Critique of Pure Reason",
    )
    assert box.locator(".turn").count() == 0
    stub.reply(answer(fragment("Ответ в B.", grounded=False)))
    ask(panel(page), "Вопрос в B")
    box.locator(".copy-answer").wait_for()
    request = stub.requests[-1]
    assert request["source_id"] == b and request["history"] == []
    # Назад в A: только обмены A.
    page.go_back()
    page.wait_for_url(re.compile(rf"/read/{a}/"))
    page.wait_for_function("() => document.querySelectorAll('.turn').length === 2")
    assert "Вопрос в B" not in box.locator(".turns").inner_text()
    state = stored(page)
    dialogs = state["dialogs"]
    a_questions = [m["question"] for s in dialogs[a]["sessions"] for m in s["messages"]]
    b_questions = [m["question"] for s in dialogs[b]["sessions"] for m in s["messages"]]
    assert a_questions == ["Вопрос один в A", "Вопрос два в A"] and b_questions == ["Вопрос в B"]
    assert all(not s["messages"] for s in state["libraryDialogs"]["sessions"])
    # Закрыть A в навигации и открыть снова — диалог A на месте (Р12).
    page.evaluate(
        """id => { const s = JSON.parse(localStorage.getItem('philograph:v4'));
        s.openSources = s.openSources.filter(o => o.id !== id);
        localStorage.setItem('philograph:v4', JSON.stringify(s)); }""",
        a,
    )
    page.goto(f"{site.url}/read/{b}")
    page.wait_for_selector(".chapter [data-paragraph]")
    assert a not in [o["id"] for o in stored(page)["openSources"]]
    open_book(page, site)
    open_assistant(page)
    assert panel(page).locator(".turn").count() == 2
    # Две вкладки: A и B, вопросы в обеих — чужая книга не перезаписана.
    other = page.context.new_page()
    other.set_viewport_size({"width": 1440, "height": 900})
    stub_b = AskStub(other).reply(answer(fragment("Второй ответ в B.", grounded=False)))
    other.goto(f"{site.url}/read/{b}")
    other.wait_for_selector(".chapter [data-paragraph]")
    open_assistant(other)
    stub.reply(answer(fragment("Третий ответ в A.", grounded=False)))
    ask(panel(page), "Вопрос три в A")
    ask(panel(other), "Вопрос два в B")
    panel(page).locator(".turn").nth(2).locator(".copy-answer").wait_for()
    panel(other).locator(".turn").nth(1).locator(".copy-answer").wait_for()
    assert stub_b.requests[-1]["source_id"] == b
    dialogs = stored(page)["dialogs"]
    assert [m["question"] for m in dialogs[a]["sessions"][0]["messages"]][-1] == "Вопрос три в A"
    assert [m["question"] for m in dialogs[b]["sessions"][0]["messages"]] == [
        "Вопрос в B",
        "Вопрос два в B",
    ]
    other.close()
    # «Сбросить данные» — диалоги книг и раздела пусты.
    page.goto(f"{site.url}/settings")
    page.get_by_role("button", name="Сбросить все данные").click()
    page.get_by_role("alertdialog").get_by_role("button", name="Удалить").click()
    page.get_by_role("status").filter(has_text="Данные удалены").wait_for()
    assert page.evaluate(f"localStorage.getItem('{STORAGE}')") is None


@req(AD, "Память диалога")
@req(AG, "Ссылки на абзацы")
def test_t39_link_to_other_book_switches_dialog_and_back(wide, site):
    """T39 (Р13): ссылка на абзац книги B во время ответа в A — диалог B, «Вернуться» — в A."""
    page = wide
    a, b = site.ids["textbook"], site.ids["primary"]
    (b_ch, b_paras), *_ = chapters(site, "primary")
    (a_ch, a_paras), *_ = chapters(site)
    stub = AskStub(page).reply(
        answer(fragment("У Канта в «Критике».", cite(b, b_ch, b_paras[0][0]))), HOLD
    )
    open_book(page, site, chapter=a_ch)
    open_assistant(page)
    box = panel(page)
    ask(panel(page), "Где у Канта?")
    box.locator(".copy-answer").wait_for()
    ask(panel(page), "Второй вопрос, долгий ответ")
    box.locator(".assistant__stage").wait_for()
    anchor = a_paras[20][0]
    page.evaluate(
        "id => document.getElementById('p-' + id).scrollIntoView({block: 'start'})", anchor
    )
    page.wait_for_timeout(100)
    before = top_of(page, anchor)
    box.locator(".citation").first.click()
    page.wait_for_url(re.compile(rf"/read/{b}/{b_ch}#p-"))
    notice = box.locator(".assistant__came-from")
    notice.wait_for()
    assert "Вы пришли из диалога по книге «История теории познания»." in notice.inner_text()
    assert box.locator(".turn").count() == 0  # диалог книги B
    # Поток в A идёт дальше: ответ дописывается в сессию A.
    stub.release(answer(fragment("Долгий ответ дописан.", grounded=False)))
    page.wait_for_function(
        """id => JSON.parse(localStorage.getItem('philograph:v4')).dialogs[id].sessions[0]
        .messages[1].status === 'done'""",
        arg=a,
    )
    notice.get_by_role("button", name="Вернуться").click()
    page.wait_for_url(re.compile(rf"/read/{a}/{a_ch}$"))
    page.locator(f"#p-{anchor}").wait_for()
    page.wait_for_function(
        "([id, top]) => Math.abs(document.getElementById('p-' + id).getBoundingClientRect().top"
        " - top) <= 4",
        arg=[anchor, before],
    )
    assert box.locator(".assistant__came-from").count() == 0
    assert "Долгий ответ дописан." in box.locator(".turn").nth(1).inner_text()
    assert len(stub.requests) == 2  # запрос не отменялся и не повторялся


# --- T40: перенос хранилища ----------------------------------------------------

V3_DIALOGS = [
    [{"question": "старый вопрос 1", "fragments": [], "status": "done"}],
    [
        {"question": "старый вопрос 2", "fragments": [], "status": "done"},
        {"question": "старый вопрос 3", "fragments": [], "status": "streaming"},
    ],
]


def migrated_page(browser, site, key: str, value) -> object:
    context = reader_context(browser, accepted=False, viewport={"width": 1440, "height": 900})
    context.add_init_script(
        f"""if (!sessionStorage.getItem('seeded')) {{
        sessionStorage.setItem('seeded', '1');
        localStorage.clear();
        localStorage.setItem({json.dumps(key)}, {json.dumps(json.dumps(value))});
    }}"""
    )
    return context


@req(RS, "Единое хранилище в браузере")
@req(AD, "Память диалога")
def test_t40_v3_to_v4_migration(browser, site):
    """T40: v3 → v4: поля как есть, старые диалоги — сессии раздела «Ассистент»; v2 и v1 так же."""
    sid = site.ids["textbook"]
    v3 = {
        "version": 3,
        "settings": {"generation": False, "sourcesOnly": True, "onlyTextbook": True},
        "theme": "dark",
        "openSources": [{"id": sid, "openedAt": 5}],
        "currentSource": sid,
        "positions": {sid: {"chapterId": "c1", "paragraphId": "p1"}},
        "dialogs": V3_DIALOGS,
        "notice": "2026-11",
    }
    context = migrated_page(browser, site, "philograph:v3", v3)
    page = context.new_page()
    page.goto(f"{site.url}/settings")
    page.wait_for_function("() => localStorage.getItem('philograph:v4') !== null")
    assert page.evaluate("localStorage.getItem('philograph:v3')") is None
    state = stored(page)
    assert state["settings"] == v3["settings"] and state["positions"] == v3["positions"]
    assert state["openSources"] == v3["openSources"] and state["theme"] == "dark"
    assert state["dialogs"] == {}
    library = state["libraryDialogs"]
    assert len(library["sessions"]) == 2
    assert library["activeId"] == library["sessions"][-1]["id"]
    turns = [m for s in library["sessions"] for m in s["messages"]]
    assert [m["question"] for m in turns] == [
        "старый вопрос 1",
        "старый вопрос 2",
        "старый вопрос 3",
    ]
    assert all(m["id"] for m in turns)
    # Повторная загрузка ничего не меняет; незаконченный обмен — «остановлено».
    page.reload()
    page.wait_for_load_state("networkidle")
    again = stored(page)
    assert again["libraryDialogs"]["sessions"][1]["messages"][1]["id"] == turns[2]["id"]
    assert again["libraryDialogs"]["activeId"] == library["activeId"]
    # Панель книги пуста: старый общий диалог — в разделе «Ассистент».
    page.goto(f"{site.url}/read/{sid}")
    page.wait_for_selector(".chapter [data-paragraph]")
    open_assistant(page)
    assert panel(page).locator(".turn").count() == 0
    page.goto(f"{site.url}/assistant")
    page.locator(".turn").first.wait_for()
    assert "старый вопрос 3" in page.locator(".turns").inner_text()
    assert "остановлено" in page.locator(".turn").nth(1).inner_text()
    context.close()

    for key, value in (
        ("philograph:v2", {"version": 2, "currentSource": sid, "dialogs": V3_DIALOGS}),
        ("philograph:dialog:v1", V3_DIALOGS[1]),
    ):
        context = migrated_page(browser, site, key, value)
        page = context.new_page()
        page.goto(f"{site.url}/settings")
        page.wait_for_function("() => localStorage.getItem('philograph:v4') !== null")
        assert page.evaluate(f"localStorage.getItem({json.dumps(key)})") is None
        state = stored(page)
        questions = [
            m["question"] for s in state["libraryDialogs"]["sessions"] for m in s["messages"]
        ]
        assert "старый вопрос 3" in questions and state["dialogs"] == {}, key
        context.close()


# --- T48: сессии ----------------------------------------------------------------


def sessions_list(box):
    """Список сессий: на странице всегда открыт, в панели — развёрнут, если был свёрнут."""
    toggle = box.get_by_role("button", name="Сессии", exact=True)
    if toggle.count() and toggle.get_attribute("aria-expanded") != "true":
        toggle.click()
    return box.get_by_role("list", name="Сессии", exact=True)


def session_crud(page, box, stub, key_of) -> None:
    """Сценарий T48 в панели книги или на странице раздела; ``key_of`` — набор в хранилище."""
    stub.reply(answer(fragment("Первый ответ.", grounded=False)))
    ask(box, "Первый вопрос сессии. И продолжение")
    box.locator(".copy-answer").wait_for()
    # «+» — вторая сессия.
    new_session(box)
    stub.reply(answer(fragment("Второй ответ.", grounded=False)))
    ask(box, "Второй вопрос? Ещё текст")
    box.locator(".copy-answer").wait_for()
    items = sessions_list(box).locator(".assistant__session")
    assert items.count() == 2
    second = key_of()["activeId"]
    updated = next(s for s in key_of()["sessions"] if s["id"] == second)["updatedAt"]
    # Сначала новые: вторая сессия — первая строка; название — первая фраза вопроса.
    row = items.nth(0)
    assert "Второй вопрос" in row.inner_text() and "Ещё текст" not in row.inner_text()
    rename = row.get_by_role("button", name=re.compile("^Переименовать"))
    delete = row.get_by_role("button", name=re.compile("^Удалить:"))
    field = box.get_by_label("Название сессии")
    # Переименовать в «Черновик» (Enter); текст в поле выделен.
    rename.click()
    assert field.evaluate("e => e === document.activeElement && e.selectionEnd === e.value.length")
    field.fill("Черновик")
    field.press("Enter")
    assert "Черновик" in row.inner_text()
    # Esc в поле: название прежнее, список открыт.
    rename.click()
    field.fill("Не сохранится")
    field.press("Escape")
    assert sessions_list(box).is_visible() and "Черновик" in row.inner_text()
    # Пустое название — снова первая фраза; дата последнего обмена не меняется.
    rename.click()
    field.fill("   ")
    field.press("Enter")
    assert "Второй вопрос" in row.inner_text()
    current = next(s for s in key_of()["sessions"] if s["id"] == second)
    assert current["updatedAt"] == updated and current["title"] == ""
    # Удалить → Отмена; Удалить → Esc; Удалить → Удалить (активную).
    delete.click()
    assert "Удалить сессию? Обмены будут стёрты." in row.inner_text()
    row.get_by_role("button", name="Отмена").click()
    assert items.count() == 2
    assert delete.evaluate("e => e === document.activeElement")  # фокус на «Удалить» (10.4)
    delete.click()
    page.keyboard.press("Escape")
    assert items.count() == 2 and sessions_list(box).is_visible()
    delete.click()
    row.get_by_role("button", name="Удалить", exact=True).click()
    page.wait_for_function("() => document.querySelectorAll('.assistant__session').length === 1")
    state = key_of()
    assert second not in [s["id"] for s in state["sessions"]]
    assert state["activeId"] == state["sessions"][0]["id"]  # активной стала оставшаяся
    assert "Первый вопрос" in box.locator(".turns").inner_text()
    # Фокус — на названии активной сессии в списке (10.4, «Подтверждённое удаление»).
    assert box.evaluate(
        "(b) => b.contains(document.activeElement) && document.activeElement.matches("
        "'.assistant__session.is-active .assistant__session-title')"
    )
    # Удалить единственную — пустая «Новая сессия».
    sessions_list(box)
    items.nth(0).get_by_role("button", name=re.compile("^Удалить:")).click()
    items.nth(0).get_by_role("button", name="Удалить", exact=True).click()
    page.wait_for_function(
        "() => document.querySelector('.assistant__session')?.textContent.includes('Новая сессия')"
    )
    assert items.count() == 1 and box.locator(".turn").count() == 0
    # Сессия с идущим ответом: подтверждение «Ответ ещё идёт», поток отменён.
    stub.reply(HOLD)
    ask(box, "Долгий вопрос")
    box.locator(".assistant__stage").wait_for()
    row = sessions_list(box).locator(".assistant__session").nth(0)
    assert "Ответ идёт" in row.inner_text()
    row.get_by_role("button", name=re.compile("^Удалить:")).click()
    assert "Ответ ещё идёт: он будет остановлен и удалён." in row.inner_text()
    sent = len(stub.requests)
    row.get_by_role("button", name="Удалить", exact=True).click()
    stub.release(answer(fragment("Не должен появиться.")))
    page.wait_for_timeout(300)
    assert "Не должен появиться" not in json.dumps(key_of(), ensure_ascii=False)
    assert "Долгий вопрос" not in json.dumps(key_of(), ensure_ascii=False)
    assert len(stub.requests) == sent
    # Пустая сессия, с которой переключились, удаляется сама.
    stub.reply(answer(fragment("Ответ.", grounded=False)))
    ask(box, "Вопрос для переключения")
    box.locator(".copy-answer").wait_for()
    new_session(box)
    items = sessions_list(box).locator(".assistant__session")
    assert items.count() == 2
    items.filter(has_text="Вопрос для переключения").locator(".assistant__session-title").click()
    assert len(key_of()["sessions"]) == 1
    # «+» при пустой активной не создаёт новую.
    new_session(box)
    new_session(box)
    assert len(key_of()["sessions"]) == 2


@req(AD, "Память диалога")
def test_t48_sessions_in_book_panel(wide, site):
    """T48: создание, переименование, удаление с подтверждением в панели книги."""
    page = wide
    stub = AskStub(page)
    sid = open_book(page, site)
    open_assistant(page)
    session_crud(page, panel(page), stub, lambda: stored(page)["dialogs"][sid])
    page.reload()
    page.wait_for_selector(".chapter [data-paragraph]")
    open_assistant(page)
    page.wait_for_function("() => document.querySelectorAll('.turn').length === 0")
    sessions_list(panel(page)).locator(".assistant__session-title", has_text="переключения").click()
    assert "Вопрос для переключения" in panel(page).locator(".turns").inner_text()
    assert all(not s["messages"] for s in stored(page)["libraryDialogs"]["sessions"])


@req(AD, "Раздел «Ассистент»")
def test_t48_sessions_on_assistant_page(wide, site):
    """T48 на странице «Ассистент»: тот же сценарий, набор libraryDialogs."""
    page = wide
    stub = AskStub(page)
    page.goto(f"{site.url}/assistant")
    page.wait_for_selector(".assistant-page")
    box = page.locator(".assistant-page")
    session_crud(page, box, stub, lambda: stored(page)["libraryDialogs"])
    assert stored(page)["dialogs"] == {}


# --- T17: Alt+Q ---------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
SHORTCUT_WIRED = "useAssistantShortcut" in (ROOT / "web/src/ReaderPage.tsx").read_text(
    encoding="utf-8"
)


@pytest.mark.skipif(
    not SHORTCUT_WIRED,
    reason="хук useAssistantShortcut подключает интегратор в ReaderPage (файл потока B)",
)
@req(AD, "Вопрос о выделенном фрагменте")
def test_t17_alt_q_with_and_without_selection(wide, site):
    """T17: Alt+Q при выделении через два абзаца — фрагмент без служебных вставок; без выделения —
    панель без фрагмента, при открытой панели — фокус в поле вопроса."""
    page = wide
    (_, paras), *_ = chapters(site)
    first, second = paras[0][0], paras[1][0]
    stub = AskStub(page)
    open_book(page, site)
    page.evaluate(
        """([a, b]) => {
        const range = document.createRange();
        range.setStart(document.getElementById('p-' + a).firstChild, 0);
        const end = document.getElementById('p-' + b);
        range.setEnd(end, end.childNodes.length);
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range);
    }""",
        [first, second],
    )
    page.keyboard.press("Alt+KeyQ")
    box = panel(page)
    quote = box.locator(".assistant__form .selection-context")
    quote.wait_for()
    assert "весьма подробно" in quote.inner_text() and "с. 41" not in quote.inner_text()
    assert box.get_by_label("Вопрос ассистенту").evaluate("e => e === document.activeElement")
    stub.reply(answer(fragment("Ответ.", grounded=False)))
    box.get_by_role("button", name="Спросить", exact=True).click()
    box.locator(".copy-answer").wait_for()
    assert stub.requests[0]["selection_paragraphs"] == [first, second]
    # Панель открыта, фокус в тексте: Alt+Q без выделения — фокус в поле вопроса.
    page.evaluate("getSelection().removeAllRanges(); document.activeElement.blur()")
    page.keyboard.press("Alt+KeyQ")
    assert box.get_by_label("Вопрос ассистенту").evaluate("e => e === document.activeElement")
    # Панель закрыта: Alt+Q без выделения открывает её без фрагмента.
    box.get_by_role("button", name="Закрыть ассистента").click()
    page.keyboard.press("Alt+KeyQ")
    panel(page).wait_for()
    assert panel(page).locator(".assistant__form .selection-context").count() == 0


# --- ссылка на утверждение (5.4) ------------------------------------------------------


def statement(sid: str, chapter: str, entity: str | None, title: str) -> dict:
    return {
        **cite(sid, chapter, None, title=title),
        "kind": "statement",
        "statement_id": f"st-{title}",
        "entity_id": entity,
    }


@req(AG, "Ссылки на абзацы")
def test_statement_citation_opens_card_in_panel(wide, site):
    """Ссылка на утверждение с entity_id — кнопка: карточка ложится на стек панели, «Назад к
    ассистенту» возвращает к ответу; без entity_id — прежняя метка, не кнопка. На странице
    «Ассистент» карточка открывается в правой панели."""
    from .test_reader_cards import CARDS, HUME

    page = wide
    (ch1, _), *_ = chapters(site)
    sid = site.ids["textbook"]
    page.route("**/api/knowledge/v1/entities/*/card*", lambda r: r.fulfill(json=CARDS[HUME]))
    linked = statement(sid, ch1, HUME, "Юм — повлиял на — Кант")
    plain = statement(sid, ch1, None, "Без сущности")
    stub = AskStub(page).reply(answer(fragment("Юм повлиял на Канта.", linked, plain)))
    open_book(page, site)
    open_assistant(page)
    ask(panel(page), "Кто повлиял на Канта?")
    box = panel(page)
    box.locator(".copy-answer").wait_for()
    cites = box.locator(".pg-cite--statement")
    assert cites.count() == 2
    assert cites.nth(0).evaluate("e => e.tagName") == "BUTTON"
    assert cites.nth(1).evaluate("e => e.tagName") == "SPAN"
    cites.nth(0).click()
    card = page.get_by_role("complementary", name="Карточка")
    card.get_by_text("Шотландский философ.").wait_for()
    back = card.get_by_role("button", name="Назад к ассистенту")
    back.click()
    panel(page).locator(".copy-answer").wait_for()
    assert "Юм повлиял на Канта." in panel(page).locator(".turns").inner_text()
    # Страница «Ассистент»: панели нет — она открывается с карточкой.
    stub.reply(answer(fragment("Юм повлиял на Канта.", linked)))
    page.goto(f"{site.url}/assistant")
    area = page.locator(".assistant-page")
    ask(area, "Кто повлиял на Канта?")
    area.locator(".copy-answer").wait_for()
    area.locator(".pg-cite--statement").first.click()
    page.get_by_role("complementary", name="Карточка").get_by_text(
        "Шотландский философ."
    ).wait_for()
