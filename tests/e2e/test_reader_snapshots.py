"""Снимки состояний экрана чтения по 14.3 (reader-panels.md): S0–S12, полоска, сноски, сессии,
страница «Ассистент».

Имена — ``reader-<состояние>-<тема>-<язык>-<ширина>`` (``visual.reader_name``). Ответы ассистента —
из заглушек: готовые NDJSON через ``page.route`` (``tests/assistant/browser.py``) или, для стадий
ответа по одной, поток в браузере, куда тест дописывает строки (``StreamAsk``). Карточка S2/S3/S3a —
подмена ``/entities/*/card``, сноски — подмена ответа главы.

Перед каждым снимком — проверки по DOM: нет горизонтальной прокрутки, колонки чтения (и панель
в режиме «сдвиг», и свёрнутая полоска) не накладываются. Пока эталонов ``reader-*`` нет, ``snap``
ничего не сравнивает: снимки остаются в ``tests/e2e/visual/results/`` для просмотра, эталоны
пишет интегратор (``scripts/visual_check.py --update``) после просмотра.
"""

from __future__ import annotations

import contextlib
import copy
import json
import os
import re
from pathlib import Path

import httpx
import pytest

from ..assistant.browser import DONE, HOLD, AskStub, answer, cite, fragment, ndjson
from ..helpers import aside, start_aside
from . import visual
from .conftest import NOTICE_VERSION, TEST_RATE_BURST
from .test_visual_design import reader_columns

req = pytest.mark.req
pytestmark = pytest.mark.e2e
VD = "visual-design"
AD = "assistant-dialog"
AG = "answer-grounding"
CR = "chapter-reading"
EC = "entity-cards"
KEY = "philograph:v4"
LEGACY = "philograph:v3"
ROOT = Path(__file__).resolve().parents[2]
CHAPTER = "Глава 3. Ответ Канта"
# Светлая RU и тёмная EN — пары тем и языков, если в 14.3 не сказано иное.
PAIRS = [("light", "ru"), ("dark", "en")]
ALL_PAIRS = [("light", "ru"), ("light", "en"), ("dark", "ru"), ("dark", "en")]
WORDS = {
    "ru": {"open_card": "Открыть карточку", "continue": "Продолжить в рамках этого источника"},
    "en": {"open_card": "Open card", "continue": "Continue within this source"},
}


@pytest.fixture(scope="module")
def site(request, tmp_path_factory):
    if os.environ.get("PHILOGRAPH_E2E_URL"):
        yield request.getfixturevalue("stack")
        return
    if not (ROOT / "web" / "dist" / "index.html").exists():
        pytest.skip("клиент не собран: npm run build в web/")
    import dev_stack

    os.environ.setdefault("PHILOGRAPH_RATE_BURST", TEST_RATE_BURST)
    running = dev_stack.start(tmp_path_factory.mktemp("reader-snapshots-stack"))
    yield running
    running.stop()


@pytest.fixture(scope="module")
def ids(site) -> dict:
    source = httpx.get(site.url + "/api/v1/current").json()["source_id"]
    toc = httpx.get(f"{site.url}/api/v1/sources/{source}/toc").json()

    def walk(items):
        for item in items:
            yield item
            yield from walk(item.get("children", []))

    chapter = next(i["chapter_id"] for i in walk(toc) if i["title"] == CHAPTER)
    data = httpx.get(f"{site.url}/api/v1/sources/{source}/chapters/{chapter}").json()
    paragraphs = [b["id"] for b in data["blocks"] if b.get("type") == "block"]
    return {"source": source, "chapter": chapter, "data": data, "paragraphs": paragraphs}


# --- контекст и переходы ------------------------------------------------------------------


def open_context(
    browser, *, theme, lang, width=1440, pinned=False, accepted=True, motion="reduce", settings=None
):
    """Читатель с темой и языком интерфейса; окно фиксированной ширины."""
    context = browser.new_context(
        viewport={"width": width, "height": 860},
        locale="ru-RU" if lang == "ru" else "en-US",
        reduced_motion=motion,
    )
    state = {"version": 3, "theme": theme, "sidebarPinned": pinned, "lang": lang}
    if accepted:
        state["notice"] = NOTICE_VERSION
    if settings:
        state["settings"] = settings
    # Состояние формата 3 под своим ключом: приложение переносит его в формат 4 и записывает.
    # Под ключом v4 данные без ``libraryDialogs`` при каждом чтении получали бы новую пустую
    # сессию, и черновик вопроса на странице «Ассистент» сбрасывался бы.
    context.add_init_script(
        f"if (!localStorage.getItem('{KEY}') && !localStorage.getItem('{LEGACY}'))"
        f" localStorage.setItem('{LEGACY}', {json.dumps(json.dumps(state))});"
    )
    page = context.new_page()
    page.set_default_timeout(15000)
    start_aside(page)
    return context, page


def resize(page, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 860})
    aside(page)


def open_chapter(page, site, ids) -> None:
    page.goto(f"{site.url}/read/{ids['source']}/{ids['chapter']}")
    page.wait_for_selector(f"h1:text('{CHAPTER}')")
    page.locator(".mention").first.wait_for()
    page.evaluate("document.fonts.ready.then(() => true)")
    aside(page)


def open_panel(page):
    """Ассистент в правой панели: кнопка над оглавлением (K1, K2) или в узкой колонке (K3)."""
    if page.locator(".toc__assistant").count():
        page.locator(".toc__assistant").click()
    else:
        page.locator(".rail button").nth(1).click()
    box = page.locator(".side-panel")
    box.locator(".assistant__form").wait_for()
    aside(page)
    return box


def ask(box, text: str) -> None:
    field = box.locator(".assistant__form textarea")
    field.fill(text)
    # Страница раздела после загрузки ещё раз выставляет черновик: вопрос вводится заново.
    for _ in range(20):
        if field.input_value() == text:
            break
        box.page.wait_for_timeout(100)
        field.fill(text)
    box.locator(".assistant__form button[type=submit]").click()


def hume(page):
    return page.locator("p.block", has_text="догматического сна").locator(".mention", has_text="Юм")


def open_popup(page):
    hume(page).click()
    popup = page.locator(".card-popup")
    popup.locator("h3:text('Юм')").wait_for()
    return popup


def wait_description(page) -> None:
    page.wait_for_function(
        "() => { const d = document.querySelector('.card-description');"
        " return d && d.textContent.trim().endsWith('.'); }"
    )


def columns(page) -> list[str]:
    """Колонки чтения и правая панель, которые не должны накладываться."""
    found = reader_columns(page)
    if page.locator(".side-panel[data-mode='shift']").count():
        found.append(".side-panel")
    if page.locator(".side-panel__strip").count():
        found.append(".side-panel__strip")
    return found


def shoot(
    snaps, page, state, theme, lang, width=None, *, regions=None, network=True, pointer=True
) -> None:
    """Проверки по DOM и снимок состояния; ``network=False`` — запрос намеренно висит,
    ``pointer=False`` — указатель остаётся на месте (состояние держится наведением)."""
    visual.settle(page, network=network, pointer=pointer)
    visual.assert_no_horizontal_scroll(page)
    visual.assert_no_overlap(page, regions if regions is not None else columns(page))
    width = width or page.viewport_size["width"]
    snaps(page, visual.reader_name(state, theme, lang, width), network=network, pointer=pointer)


class StreamAsk:
    """Поток ответа в браузере: тест дописывает строки NDJSON по одной (стадии S7)."""

    SCRIPT = """(() => {
      const real = window.fetch.bind(window);
      window.__ask = [];
      window.fetch = (input, init) => {
        const url = typeof input === 'string' ? input : input.url;
        if (!url.includes('/api/assistant/v1/ask')) return real(input, init);
        let controller;
        const body = new ReadableStream({ start(c) { controller = c; } });
        window.__ask.push(controller);
        return Promise.resolve(new Response(body,
          { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));
      };
    })();"""

    def __init__(self, context) -> None:
        context.add_init_script(self.SCRIPT)

    @staticmethod
    def push(page, *events: dict) -> None:
        page.evaluate(
            "line => window.__ask[window.__ask.length - 1].enqueue(new TextEncoder().encode(line))",
            ndjson(*events),
        )

    @staticmethod
    def close(page) -> None:
        page.evaluate("window.__ask[window.__ask.length - 1].close()")


def chapter_with_notes(ids) -> dict:
    """Ответ главы, где в первом абзаце две сноски: короткая и длинная."""
    data = copy.deepcopy(ids["data"])
    block = next(b for b in data["blocks"] if b.get("type") == "block")
    data["footnotes"] = {
        **data.get("footnotes", {}),
        "n-snap-1": {"marker": "1", "text": "Кант И. Пролегомены, предисловие.", "linked": True},
        "n-snap-2": {
            "marker": "2",
            "text": "Примечание переводчика о терминах «догматический» и «критический» "
            "в изданиях XIX века. См. https://example.org/kant",
            "linked": True,
        },
    }
    # Знаки — после слова «Юм» и в конце абзаца: середина строки (``len // 2``) попадала внутрь
    # слова («Юм пр¹обудил»), и снимок показывал дефект сценария, а не продукта.
    text = block["text"]
    block["notes"] = [[text.index("Юм") + len("Юм"), "n-snap-1"], [len(text), "n-snap-2"]]
    return data


NOTE_NEIGHBOURS = """() => [...document.querySelectorAll('article.chapter .note-ref')].map(ref => {
  const host = ref.closest('.note') ?? ref;
  const text = n => (n ? n.textContent : '');
  return [text(host.previousSibling).slice(-1), text(host.nextSibling).slice(0, 1)];
})"""


def assert_notes_after_words(page) -> None:
    """Знак сноски стоит после слова: перед ним буква или знак препинания, после — не буква."""
    for before, after in page.evaluate(NOTE_NEIGHBOURS):
        assert before and not before.isspace(), (before, after)
        assert not after.isalpha(), f"знак сноски внутри слова: …{before}|{after}…"


def route_card(page, handler) -> None:
    page.route("**/api/knowledge/v1/entities/*/card*", handler)


def fulfill(status: int, body: dict):
    """Обработчик подмены: ответ с кодом и JSON."""
    return lambda route: route.fulfill(status=status, json=body)


# --- S0, S5: раскладка ------------------------------------------------------------------


@req(VD, "Визуальная проверка")
@req(VD, "Раскладка экрана чтения")
@req(VD, "Раскладка без наложений")
@pytest.mark.parametrize(("theme", "lang"), ALL_PAIRS)
def test_s0_s5_layout(browser, site, ids, theme, lang):
    """S0 и S5 на 1024–2560, обе темы и оба языка."""
    snaps = visual.Snaps()
    context, page = open_context(browser, theme=theme, lang=lang, width=1024)
    try:
        for width in visual.WIDTHS:
            resize(page, width)
            open_chapter(page, site, ids)
            shoot(snaps, page, "s0", theme, lang)
            open_panel(page)
            shoot(snaps, page, "s5", theme, lang)
    finally:
        context.close()
    snaps.check()


@req(VD, "Визуальная проверка")
@req(VD, "Боковая панель навигации")
@pytest.mark.parametrize(("theme", "lang"), PAIRS)
def test_s0_s5_pinned(browser, site, ids, theme, lang):
    """S0 и S5 с закреплённой навигацией на 1280, 1440, 1920."""
    snaps = visual.Snaps()
    context, page = open_context(browser, theme=theme, lang=lang, width=1280, pinned=True)
    try:
        for width in (1280, 1440, 1920):
            resize(page, width)
            open_chapter(page, site, ids)
            assert visual.sidebar_state(page) == "pinned"
            shoot(snaps, page, "s0-pinned", theme, lang)
            open_panel(page)
            shoot(snaps, page, "s5-pinned", theme, lang)
    finally:
        context.close()
    snaps.check()


# --- S1, S4: карточка --------------------------------------------------------------------


@req(VD, "Визуальная проверка")
@req(EC, "Карточка рядом с текстом")
@pytest.mark.parametrize(("theme", "lang"), PAIRS)
def test_s1_s4_card(browser, site, ids, theme, lang):
    """S1 (окно у «Юм») и S4 (полная карточка в панели) на 1024–1920."""
    snaps = visual.Snaps()
    context, page = open_context(browser, theme=theme, lang=lang, width=1024)
    try:
        for width in (1024, 1280, 1440, 1920):
            resize(page, width)
            open_chapter(page, site, ids)
            popup = open_popup(page)
            wait_description(page)
            shoot(snaps, page, "s1", theme, lang)
            popup.get_by_role("button", name=WORDS[lang]["open_card"]).click()
            page.locator(".side-panel .card-section h4").first.wait_for()
            aside(page)
            assert_full_card_head(page)
            shoot(snaps, page, "s4", theme, lang)
    finally:
        context.close()
    snaps.check()


def assert_full_card_head(page) -> None:
    """S4 (4.5, Lifeline.md): годы один раз в голове рядом с меткой семьи и линия жизни — шкала
    с полосой и веком, а не вторая строка с теми же годами. Тело панели прокручивается само:
    последняя кнопка графа, срезанная краем окна, достижима прокруткой."""
    panel = page.locator(".side-panel")
    life = panel.locator(".pg-lifeline")
    assert life.get_attribute("aria-hidden") == "true"
    assert life.locator(".pg-lifeline__life").bounding_box()["width"] > 20
    assert life.locator(".pg-lifeline__century").count() >= 1
    assert panel.locator(".card-dates").count() == 1
    last = panel.locator(".card-section, .card-graph, button").last
    scroller = last.evaluate(
        """e => { for (let p = e.parentElement; p; p = p.parentElement) {
            const s = getComputedStyle(p);
            if (/(auto|scroll)/.test(s.overflowY) && p.scrollHeight > p.clientHeight) return true; }
          return false; }"""
    )
    bottom = last.bounding_box()
    fits = bottom["y"] + bottom["height"] <= page.viewport_size["height"]
    assert fits or scroller, "низ полной карточки срезан, а тело панели не прокручивается"


# --- полоска справа на 1024 ---------------------------------------------------------------


@req(VD, "Визуальная проверка")
@req(VD, "Раскладка экрана чтения")
@pytest.mark.parametrize(("theme", "lang"), PAIRS)
def test_strip(browser, site, ids, theme, lang):
    """Полоска свёрнута, развёрнута и свёрнута во время ответа (1024)."""
    snaps = visual.Snaps()
    context, page = open_context(browser, theme=theme, lang=lang, width=1024)
    stub = AskStub(page).reply(HOLD)
    try:
        open_chapter(page, site, ids)
        box = open_panel(page)
        assert box.get_attribute("data-mode") == "strip"
        # Развёрнутая полоска лежит поверх текста: её с колонками не сравниваем.
        shoot(snaps, page, "strip-expanded", theme, lang, regions=reader_columns(page))
        page.locator(".side-panel__collapse").click()
        page.locator(".side-panel__strip").wait_for()
        shoot(snaps, page, "strip-collapsed", theme, lang)
        page.locator(".side-panel__strip").click()
        ask(page.locator(".side-panel"), "Что Кант взял у Юма?")
        page.locator(".side-panel .assistant__stage").wait_for()
        page.locator(".side-panel__collapse").click()
        strip = page.locator(".side-panel__strip")
        strip.wait_for()
        # Свёрнута во время ответа (2.3): точка стадии 8px accent и подпись «Ассистент отвечает».
        dot = strip.locator(".side-panel__dot")
        dot.wait_for()
        box = dot.bounding_box()
        assert round(box["width"]) == 8 and round(box["height"]) == 8
        visual.assert_color(
            page, ".side-panel__strip .side-panel__dot", "background-color", "accent"
        )
        answering = {"ru": "Ассистент отвечает", "en": "The assistant is answering"}[lang]
        assert answering in strip.text_content()
        assert len(stub.requests) == 1  # сворачивание поток не останавливает
        shoot(snaps, page, "strip-streaming", theme, lang)
        stub.release(answer(fragment("Ответ.", grounded=False)))
    finally:
        context.close()
    snaps.check()


# --- S7: стадии ответа ----------------------------------------------------------------------


@req(VD, "Визуальная проверка")
@req(AD, "Ход ответа")
@pytest.mark.parametrize(("theme", "lang"), PAIRS)
def test_s7_stages(browser, site, ids, theme, lang):
    """S7 на каждой из четырёх стадий, итог ответа и S7 при prefers-reduced-motion (1440).

    Стадии снимаются без «уменьшения движения»: цикл индикатора останавливает сам снимок
    (``animations="disabled"``); отдельный снимок — с ``prefers-reduced-motion: reduce``."""
    snaps = visual.Snaps()
    paragraph = ids["paragraphs"][0]
    for motion in ("no-preference", "reduce"):
        context, page = open_context(browser, theme=theme, lang=lang, motion=motion)
        StreamAsk(context)
        try:
            open_chapter(page, site, ids)
            box = open_panel(page)
            ask(box, "Что Кант взял у Юма?")
            box.locator(".assistant__stage").wait_for()
            if motion == "reduce":
                StreamAsk.push(page, {"type": "stage", "name": "searching"})
                page.wait_for_function("() => document.querySelector('.assistant__stage')")
                shoot(snaps, page, "s7-reduced", theme, lang)
                continue
            shoot(snaps, page, "s7-stage1", theme, lang)
            StreamAsk.push(page, {"type": "stage", "name": "searching"})
            page.wait_for_timeout(100)
            shoot(snaps, page, "s7-stage2", theme, lang)
            StreamAsk.push(page, {"type": "stage", "name": "composing", "found": 6})
            box.locator(".assistant__stage-found").wait_for()
            shoot(snaps, page, "s7-stage3", theme, lang)
            StreamAsk.push(
                page,
                fragment(
                    "Кант признаёт, что Юм пробудил его от догматического сна.",
                    cite(ids["source"], ids["chapter"], paragraph),
                ),
            )
            box.locator(".fragment").wait_for()
            shoot(snaps, page, "s7-stage4", theme, lang)
            StreamAsk.push(page, fragment("Это общая оценка.", grounded=False), DONE)
            StreamAsk.close(page)
            box.locator(".copy-answer").wait_for()
            shoot(snaps, page, "s7-done", theme, lang)
        finally:
            context.close()
    snaps.check()


# --- состояния на 1440 ------------------------------------------------------------------


def assert_notice_readable(notice) -> None:
    """Текст Notice в окне карточки не сжат в колонку: не уже 60% ширины Notice, действие —
    под текстом (раунд 4: текст S3 стоял колонкой ~65px в 11 строк)."""
    text = notice.locator(":scope > div").bounding_box()
    whole = notice.bounding_box()
    action = notice.locator(":scope > .pg-btn").bounding_box()
    assert text["width"] >= 0.6 * whole["width"], (text, whole)
    assert action["y"] >= text["y"] + text["height"] - 1, (action, text)


def card_states(browser, site, ids, snaps, theme, lang) -> None:
    """S2 (загружается дольше 300 мс), S3 (карточки нет), S3a (не загрузилась)."""
    held: list = []
    context, page = open_context(browser, theme=theme, lang=lang)
    try:
        route_card(page, lambda r: held.append(r))
        open_chapter(page, site, ids)
        hume(page).click()
        page.locator(".card-popup").wait_for()
        page.wait_for_timeout(450)  # строка «Загружаем карточку…» — после 300 мс
        shoot(snaps, page, "s2", theme, lang, network=False)
        page.unroute("**/api/knowledge/v1/entities/*/card*")
        for state, status, body in (
            ("s3", 404, {"kind": "entity_not_found", "error": "нет"}),
            ("s3a", 503, {"kind": "unavailable", "error": "нет"}),
        ):
            page.keyboard.press("Escape")
            page.unroute("**/api/knowledge/v1/entities/*/card*")
            route_card(page, fulfill(status, body))
            open_chapter(page, site, ids)
            hume(page).click()
            notice = page.locator(".card-popup .pg-notice")
            notice.wait_for()
            assert_notice_readable(notice)
            shoot(snaps, page, state, theme, lang)
    finally:
        for route in held:
            with contextlib.suppress(Exception):  # запрос уже отменён клиентом
                route.abort()
        context.close()


def select_paragraph(page, paragraph: str) -> None:
    page.evaluate(
        """id => { const p = document.getElementById('p-' + id);
        const range = document.createRange(); range.selectNodeContents(p);
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range);
        p.dispatchEvent(new MouseEvent('mouseup', {bubbles: true})); }""",
        paragraph,
    )
    page.locator(".selection-toolbar .pg-btn--primary").click()


def assert_s6(page, box, paragraph: str, lang: str) -> None:
    """S6 (3.1, 5.2): подпись главы над цитатой, выделение в тексте снято, панели действий над
    выделением нет, абзац фрагмента отмечен линией accent-soft на левом поле."""
    caption = box.locator(".assistant__fragment-from")
    expected = {"ru": f"Фрагмент из главы «{CHAPTER}»", "en": f"Passage from “{CHAPTER}”"}[lang]
    assert caption.inner_text() == expected
    page.wait_for_timeout(200)  # панель действий появляется через 120 мс после mouseup
    assert page.evaluate("getSelection().toString()") == ""
    assert page.locator(".selection-toolbar").count() == 0
    marked = page.locator("article.chapter .block.is-fragment")
    assert marked.count() == 1 and marked.get_attribute("data-paragraph") == paragraph
    line = marked.evaluate(
        "e => { const s = getComputedStyle(e, '::before');"
        " return [s.content, s.borderLeftWidth, s.borderLeftColor]; }"
    )
    assert line[0] != "none" and line[1] == "2px"
    soft = visual.rgba(page, visual.token(page, "accent-soft"))
    assert visual.rgba(page, line[2])[:3] == soft[:3]


def answer_states(browser, site, ids, snaps, theme, lang) -> None:
    """S6, S7a (оба вида и после «Продолжить»), S8, S9 (лимит и обрыв)."""
    src, chapter, paragraph = ids["source"], ids["chapter"], ids["paragraphs"][0]
    outside = ndjson(
        {"type": "stage", "name": "searching"},
        {"type": "stage", "name": "composing", "found": 1},
        fragment("В другой книге сказано иначе.", cite("other-source", "other-chapter", "p-x")),
        fragment("Связь неочевидна.", grounded=False),
        {"type": "handoff", "reason": "outside_book"},
        DONE,
    )
    broader = ndjson(
        {"type": "stage", "name": "searching"}, {"type": "handoff", "reason": "broader"}, DONE
    )
    context, page = open_context(browser, theme=theme, lang=lang)
    stub = AskStub(page)
    try:
        open_chapter(page, site, ids)
        select_paragraph(page, ids["paragraphs"][1])
        box = page.locator(".side-panel")
        box.locator(".assistant__form .selection-context").wait_for()
        aside(page)
        assert_s6(page, box, ids["paragraphs"][1], lang)
        shoot(snaps, page, "s6", theme, lang)
        for state, body in (("s7a-broader", broader), ("s7a-outside", outside)):
            stub.reply(body)
            box.locator(".assistant__new").click()
            ask(box, "А что думали другие авторы?")
            box.locator(".handoff-block").wait_for()
            shoot(snaps, page, state, theme, lang)
        stub.reply(answer(fragment("Ответ по книге.", cite(src, chapter, paragraph))))
        box.locator(".handoff-block").get_by_role("button", name=WORDS[lang]["continue"]).click()
        box.locator(".turn").nth(1).locator(".copy-answer").wait_for()
        shoot(snaps, page, "s7a-book", theme, lang)
        for state, body, ready in (
            (
                "s8",
                answer(
                    {
                        "type": "notice",
                        "kind": "no_library_support",
                        "message": "Ответ составлен без опоры на библиотеку.",
                    },
                    fragment("Стоики учили о добродетели.", grounded=False),
                ),
                ".copy-answer",
            ),
            (
                "s9-budget",
                ndjson({"type": "unavailable", "reason": "budget_exhausted", "message": "…"}),
                ".assistant-notice",
            ),
            (
                "s9-broken",
                ndjson(
                    {"type": "stage", "name": "searching"},
                    fragment("Начало ответа.", grounded=False),
                    {"type": "error", "message": "обрыв"},
                ),
                ".assistant__summary",
            ),
        ):
            stub.reply(body)
            box.locator(".assistant__new").click()
            ask(box, "Вопрос для снимка")
            box.locator(f".turn {ready}").wait_for()
            shoot(snaps, page, state, theme, lang)
    finally:
        context.close()


@req(VD, "Визуальная проверка")
@req(EC, "Карточка рядом с текстом")
@pytest.mark.parametrize(("theme", "lang"), PAIRS)
def test_card_states(browser, site, ids, theme, lang):
    """S2, S3, S3a — 1440."""
    snaps = visual.Snaps()
    card_states(browser, site, ids, snaps, theme, lang)
    snaps.check()


@req(VD, "Визуальная проверка")
@req(AD, "Вопрос о выделенном фрагменте")
@req(AD, "Граница книги")
@req(AD, "Недоступность и лимиты")
@req(AG, "Пофрагментная пометка")
@pytest.mark.parametrize(("theme", "lang"), PAIRS)
def test_answer_states(browser, site, ids, theme, lang):
    """S6, S7a (шире книги, вне книги, после «Продолжить»), S8, S9 — 1440."""
    snaps = visual.Snaps()
    answer_states(browser, site, ids, snaps, theme, lang)
    snaps.check()


@req(VD, "Визуальная проверка")
@req(AG, "Режим «только по источникам»")
@req(AD, "Недоступность и лимиты")
@pytest.mark.parametrize(("theme", "lang"), PAIRS)
def test_s10_s12(browser, site, ids, theme, lang):
    """S10 (только по источникам) и S12 (вопрос до согласия) — 1440."""
    snaps = visual.Snaps()
    settings = {"generation": False, "sourcesOnly": True, "onlyTextbook": False}
    context, page = open_context(browser, theme=theme, lang=lang, settings=settings)
    try:
        open_chapter(page, site, ids)
        open_panel(page).locator(".assistant__sources-only").wait_for()
        shoot(snaps, page, "s10", theme, lang)
    finally:
        context.close()
    context, page = open_context(browser, theme=theme, lang=lang, accepted=False)
    stub = AskStub(page)
    try:
        open_chapter(page, site, ids)
        box = open_panel(page)
        ask(box, "Что Кант взял у Юма?")
        box.locator(".assistant-notice").first.wait_for()
        assert stub.requests == []  # до согласия вопрос не уходит
        # Пример пометки в уведомлении — одной строкой, точка вплотную после него (без пробела).
        example = page.locator(".first-run .notice-example")
        assert example.evaluate("e => e.getClientRects().length") == 1
        wrap = page.locator(".first-run .notice-example-wrap").evaluate("e => e.textContent")
        assert wrap.endswith(example.evaluate("e => e.textContent") + ".")
        shoot(snaps, page, "s12", theme, lang, regions=[*columns(page), ".first-run"])
    finally:
        context.close()
    snaps.check()


# --- S13: глава не оцифрована ------------------------------------------------------------


def missing_chapter(site, ids) -> tuple[str, str, dict]:
    """Глава 2 (у неё есть и предыдущая, и следующая) без текста: одна плашка «не оцифрована»."""
    toc = httpx.get(f"{site.url}/api/v1/sources/{ids['source']}/toc").json()
    item = next(i for i in toc if i["title"].startswith("Глава 2"))
    chapter = item["chapter_id"]
    data = httpx.get(f"{site.url}/api/v1/sources/{ids['source']}/chapters/{chapter}").json()
    first = next(b for b in data["blocks"] if b.get("type") == "block")
    data["blocks"] = [
        {
            **first,
            "id": first["id"] + "-missing",
            "kind": "unrendered",
            "text": "",
            "pages": [],
            "notes": [],
            "detail": "глава не оцифрована на сайте",
            "detail_code": "missing",
            "page": None,
        }
    ]
    data["footnotes"], data["unlinked_notes"] = {}, []
    return chapter, item["title"], data


@req(VD, "Визуальная проверка")
@req(CR, "Необработанные части в тексте")
@pytest.mark.parametrize(("theme", "lang"), PAIRS)
def test_s13_missing_chapter(browser, site, ids, theme, lang):
    """S13 — глава не оцифрована (1440): заголовок, одна плашка, переход к соседним главам."""
    snaps = visual.Snaps()
    chapter, title, data = missing_chapter(site, ids)
    context, page = open_context(browser, theme=theme, lang=lang)
    page.route(f"**/sources/{ids['source']}/chapters/{chapter}", lambda r: r.fulfill(json=data))
    try:
        page.goto(f"{site.url}/read/{ids['source']}/{chapter}")
        page.locator("h1", has_text=title).wait_for()
        figure = page.locator("article.chapter figure.unrendered")
        figure.wait_for()
        assert figure.count() == 1
        assert page.locator("article.chapter p.block").count() == 0
        assert figure.get_attribute("data-nontext") is not None
        label = {"ru": "Не передано в тексте", "en": "Not rendered as text"}[lang]
        detail = {"ru": "глава не оцифрована на сайте", "en": "chapter not digitized on the site"}
        assert label in figure.text_content() and detail[lang] in figure.text_content()
        assert figure.locator(".ask-paragraph").count() == 0
        nav = page.locator(".chapter-nav")
        assert nav.locator("[rel=prev]").count() == 1 and nav.locator("[rel=next]").count() == 1
        aside(page)
        shoot(snaps, page, "s13", theme, lang)
    finally:
        context.close()
    snaps.check()


# --- сноски --------------------------------------------------------------------------------


@req(VD, "Визуальная проверка")
@req(CR, "Сноски")
@pytest.mark.parametrize(("theme", "lang"), PAIRS)
def test_notes(browser, site, ids, theme, lang):
    """Поле сносок (1920, 1440) и окно сноски (1280, 1024)."""
    snaps = visual.Snaps()
    data = chapter_with_notes(ids)
    context, page = open_context(browser, theme=theme, lang=lang, width=1920)
    page.route(
        f"**/sources/{ids['source']}/chapters/{ids['chapter']}", lambda r: r.fulfill(json=data)
    )
    try:
        for width in (1920, 1440):
            resize(page, width)
            open_chapter(page, site, ids)
            page.locator(".field-note[data-note-id='n-snap-2']").wait_for()
            page.wait_for_timeout(100)  # положения на поле — после отрисовки
            assert_notes_after_words(page)
            shoot(snaps, page, "notes-field", theme, lang)
        for width in (1280, 1024):
            resize(page, width)
            open_chapter(page, site, ids)
            assert_notes_after_words(page)
            # Окно открыто наведением и живёт, пока указатель на знаке: снимок не уводит указатель
            # в угол (иначе через 200 мс окно закрывалось, и на снимке его не было).
            page.locator("button.note-ref").last.hover()
            popup = page.locator(".note-popup")
            popup.wait_for()
            popup.evaluate("e => Promise.all(e.getAnimations().map(a => a.finished))")
            shoot(snaps, page, "notes-popup", theme, lang, regions=columns(page), pointer=False)
            assert popup.is_visible(), "окно сноски закрылось до снимка"
            aside(page)
    finally:
        context.close()
    snaps.check()


# --- сессии в панели --------------------------------------------------------------------


def two_sessions(box, stub) -> None:
    for question in ("Что Кант взял у Юма?", "Как связаны опыт и рассудок?"):
        stub.reply(answer(fragment(f"Ответ на «{question}».", grounded=False)))
        if box.locator(".turn").count():
            box.locator(".assistant__new").click()
        ask(box, question)
        box.locator(".copy-answer").wait_for()


def open_sessions(box) -> None:
    toggle = box.locator(".assistant__sessions-toggle")
    if toggle.count() and toggle.get_attribute("aria-expanded") != "true":
        toggle.click()
    box.locator(".assistant__sessions").wait_for()


@req(VD, "Визуальная проверка")
@req(AD, "Память диалога")
@pytest.mark.parametrize(("theme", "lang"), PAIRS)
def test_sessions_panel(browser, site, ids, theme, lang):
    """Список сессий в панели, строка переименования, подтверждение удаления — 1440."""
    snaps = visual.Snaps()
    context, page = open_context(browser, theme=theme, lang=lang)
    stub = AskStub(page)
    try:
        open_chapter(page, site, ids)
        box = open_panel(page)
        two_sessions(box, stub)
        open_sessions(box)
        shoot(snaps, page, "sessions", theme, lang)
        box.locator("[data-rename-session]").first.click()
        box.locator(".assistant__session-input").wait_for()
        shoot(snaps, page, "session-rename", theme, lang)
        page.keyboard.press("Escape")
        box.locator("[data-delete-session]").first.click()
        box.locator(".assistant__session-confirm").wait_for()
        shoot(snaps, page, "session-delete", theme, lang)
    finally:
        context.close()
    snaps.check()


# --- страница «Ассистент» ---------------------------------------------------------------


def page_regions() -> list[str]:
    return [".sidebar", ".assistant-page"]


@req(VD, "Визуальная проверка")
@req(AD, "Раздел «Ассистент»")
@req(AD, "Переход с вопросом из панели")
@pytest.mark.parametrize(("theme", "lang"), PAIRS)
def test_assistant_page(browser, site, ids, theme, lang):
    """Страница «Ассистент»: пустая, с диалогом, «перенесён и не отправлен», «уже задан»
    (1024, 1440, 1920); список сессий и подтверждение удаления (1440)."""
    snaps = visual.Snaps()
    widths = (1024, 1440, 1920)
    src = ids["source"]
    broader = ndjson(
        {"type": "stage", "name": "searching"}, {"type": "handoff", "reason": "broader"}, DONE
    )
    context, page = open_context(browser, theme=theme, lang=lang)
    stub = AskStub(page)
    try:
        page.goto(site.url + "/assistant")
        page.locator(".assistant-page .assistant__form").wait_for()
        for width in widths:
            resize(page, width)
            shoot(snaps, page, "page-empty", theme, lang, regions=page_regions())
        box = page.locator(".assistant-page")
        stub.reply(answer(fragment("Ответ по всей библиотеке.", grounded=False)))
        ask(box, "Что такое трансцендентальное?")
        box.locator(".copy-answer").wait_for()
        for width in widths:
            resize(page, width)
            shoot(snaps, page, "page-dialog", theme, lang, regions=page_regions())
        resize(page, 1440)
        stub.reply(answer(fragment("Второй ответ.", grounded=False)))
        box.locator(".assistant__new").click()
        ask(box, "Как связаны опыт и рассудок?")
        box.locator(".copy-answer").wait_for()
        shoot(snaps, page, "page-sessions", theme, lang, regions=page_regions())
        box.locator("[data-delete-session]").first.click()
        box.locator(".assistant__session-confirm").wait_for()
        shoot(snaps, page, "page-delete", theme, lang, regions=page_regions())
        page.keyboard.press("Escape")
        # «Перенесён и не отправлен»: прямой адрес с вопросом.
        page.goto(f"{site.url}/assistant?q={re.sub(' ', '%20', 'Новый вопрос')}&from={src}")
        page.locator(".assistant__pending").wait_for()
        for width in widths:
            resize(page, width)
            shoot(snaps, page, "page-pending", theme, lang, regions=page_regions())
        # «Уже задан»: переход из панели книги отправил вопрос, затем перезагрузка.
        resize(page, 1440)
        stub.reply(broader, answer(fragment("Ответ по всем источникам.", grounded=False)))
        open_chapter(page, site, ids)
        panel_box = open_panel(page)
        ask(panel_box, "А что думали другие авторы?")
        panel_box.locator(".handoff-block a").first.click()
        page.locator(".assistant-page .copy-answer").first.wait_for()
        page.reload()
        page.locator(".assistant__asked").wait_for()
        for width in widths:
            resize(page, width)
            shoot(snaps, page, "page-asked", theme, lang, regions=page_regions())
    finally:
        context.close()
    snaps.check()
