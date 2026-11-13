"""Упоминания и карточка на экране чтения (reader-panels.md, 4.1–4.7; тесты T6–T12, T15, T16).

Сервер знаний подменяется в браузере (``page.route``): ответы ``/mentions`` строятся по
настоящему тексту тестового учебника, карточки — по описанию ниже. Так проверяется клиент:
вид упоминаний, открытие окна только щелчком (Р5), положение окна, стек «Назад», состояния
загрузки и ошибок, полная карточка в панели и деление запроса упоминаний по 500 абзацев (N11).
Сервер знаний проверяется отдельно в ``tests/knowledge/test_mentions_cards.py``.
"""

from __future__ import annotations

import base64
import json
import re
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect

from philograph.library.processing import Pipeline
from philograph.library.registry import License
from philograph.platform.files import FileStore

from ..helpers import aside, reader_context
from ..library.builders import epub

req = pytest.mark.req
EM = "entity-mentions"
EC = "entity-cards"

KANT, HUME, EXPERIENCE = "e_kant", "e_hume", "e_experience"
# Что ищется в тексте учебника: выражение, сущность, тип. Первое вхождение в абзаце.
NAMES = [(r"Кант\w*", KANT, "person"), (r"опыт\w*", EXPERIENCE, "concept")]

# 1×1 GIF: ответ на запрос портрета, чтобы <img> реально загружался и медальон
# не падал в монограмму по onError (T11).
PORTRAIT_IMAGE = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")


def row(statement_id: str, type_: str, relation: str, **extra) -> dict:
    base = {
        "statement_id": statement_id,
        "type": type_,
        "relation": relation,
        "inverse": False,
        "attributions": [],
        "entity_id": None,
        "label": None,
        "value": None,
        "status": "sourced",
        "disputed": False,
        "disputed_by": [],
        "generated": False,
        "in_textbook": None,
        "attributed_to": [],
        "evidence": [],
    }
    base.update(extra)
    return base


def card(entity_id: str, **extra) -> dict:
    base = {
        "id": entity_id,
        "type": "person",
        "title": entity_id,
        "names": [],
        "dates": None,
        "portraits": [],
        "description": None,
        "description_pending": False,
        "sections": [],
        "where_to_read": [],
        "recipes": [],
    }
    base.update(extra)
    return base


def description(text: str, generated: bool = False) -> dict:
    return row(
        "d1",
        "description",
        "Описание",
        value=text,
        generated=generated,
        status="generated" if generated else "sourced",
    )


CARDS = {
    KANT: card(
        KANT,
        title="Кант",
        dates={"original": "1724–1804"},
        # Четыре предложения: в окне остаются первые два (4.4).
        description=description(
            "Немецкий философ. Основатель критической философии. Профессор в Кёнигсберге. "
            "Автор трёх «Критик»."
        ),
        sections=[
            {
                "code": "influence",
                "title": "Влияния",
                "rows": [
                    row(
                        "s1",
                        "influenced_by",
                        "испытал влияние",
                        entity_id=HUME,
                        label="Юм",
                        status="verified",
                    ),
                    row(
                        "s2",
                        "influenced_by",
                        "испытал влияние",
                        entity_id="e_leibniz",
                        label="Лейбниц",
                        evidence=[{"paragraph_id": "x", "link": "/p/x"}],
                    ),
                    row(
                        "s3", "influenced_by", "испытал влияние", entity_id="e_wolff", label="Вольф"
                    ),
                ],
            }
        ],
    ),
    HUME: card(
        HUME,
        title="Юм",
        dates={"original": "1711–1776"},
        description=description("Шотландский философ."),
        sections=[
            {
                "code": "influence",
                "title": "Влияния",
                "rows": [
                    row(
                        "s4",
                        "influenced_by",
                        "повлиял на",
                        inverse=True,
                        entity_id=KANT,
                        label="Кант",
                        status="verified",
                    ),
                ],
            }
        ],
    ),
    EXPERIENCE: card(EXPERIENCE, type="concept", title="Опыт"),
}


class Knowledge:
    """Подменённый сервер знаний: упоминания по тексту учебника, карточки из ``CARDS``."""

    def __init__(self, page, texts: dict[str, str]) -> None:
        self.texts = texts
        self.cards = dict(CARDS)
        self.card_status: dict[str, int] = {}
        self.mentions_status = 200
        self.card_requests: list[str] = []
        self.mention_requests: list[list[str]] = []
        self.held: list = []
        self.hold = False
        page.route("**/api/knowledge/v1/mentions*", self._mentions)
        page.route("**/api/knowledge/v1/entities/*/card*", self._card)
        page.route("**/portraits/*", self._portrait)

    def _portrait(self, route) -> None:
        route.fulfill(status=200, content_type="image/gif", body=PORTRAIT_IMAGE)

    def _mentions(self, route) -> None:
        query = parse_qs(urlparse(route.request.url).query)
        targets = [x for x in query.get("targets", [""])[0].split(",") if x]
        self.mention_requests.append(targets)
        if self.mentions_status != 200:
            route.fulfill(status=self.mentions_status, json={"kind": "service_unavailable"})
            return
        found = []
        for target in targets[:500]:  # как сервер: больше 500 за запрос не принимает
            text = self.texts.get(target, "")
            for pattern, entity, type_ in NAMES:
                m = re.search(pattern, text)
                if m:
                    found.append(
                        {
                            "target_id": target,
                            "entity_id": entity,
                            "entity_type": type_,
                            "start": m.start(),
                            "end": m.end(),
                            "kind": "paragraph",
                        }
                    )
        route.fulfill(json=found)

    def _card(self, route) -> None:
        entity = urlparse(route.request.url).path.split("/")[-2]
        self.card_requests.append(entity)
        if self.hold:
            self.held.append((route, entity))
            return
        self.answer(route, entity)

    def answer(self, route, entity: str) -> None:
        status = self.card_status.get(entity, 200)
        if status == 404:
            route.fulfill(status=404, json={"kind": "entity_not_found", "message": "нет"})
        elif status != 200:
            route.fulfill(status=status, json={"kind": "service_unavailable"})
        elif entity in self.cards:
            route.fulfill(body=json.dumps(self.cards[entity]), content_type="application/json")
        else:
            route.fulfill(status=404, json={"kind": "entity_not_found", "message": "нет"})

    def release(self) -> None:
        self.hold = False
        for route, entity in self.held:
            self.answer(route, entity)
        self.held = []


@pytest.fixture
def texts(site) -> dict[str, str]:
    return {block: text for _, block, text in site.paragraphs("textbook")}


def open_reader(browser, site, texts, *, width=1440, height=900, locale="ru-RU"):
    context = reader_context(browser, viewport={"width": width, "height": height}, locale=locale)
    page = context.new_page()
    page.set_default_timeout(5000)
    knowledge = Knowledge(page, texts)
    return context, page, knowledge


def goto_chapter(page, site, source: str = "textbook") -> None:
    page.goto(f"{site.url}/read/{site.ids[source]}")
    page.wait_for_selector("article.chapter p.block")
    aside(page)


def kant(page):
    mention = page.locator("p.block", has_text="говорит Кант").locator(".mention", has_text="Кант")
    mention.wait_for()
    return mention


def opened(dialog, name: str) -> None:
    """Окно показало карточку ``name`` и закончило появляться (иначе Playwright, дожидаясь
    неподвижной цели, прокручивает страницу, а окно закрывается, когда строка уходит из вида)."""
    dialog.locator("h3", has_text=name).wait_for()
    dialog.evaluate("el => Promise.all(el.getAnimations({subtree: true}).map(a => a.finished))")


def rects(page, mention) -> dict:
    """Строка упоминания и окно карточки в координатах окна браузера."""
    return mention.evaluate(
        """el => {
          const line = el.getClientRects()[0];
          const box = document.querySelector('.card-popup').getBoundingClientRect();
          const text = el.closest('.chapter').getBoundingClientRect();
          const panel = document.querySelector('.side-panel');
          return {
            line: {top: line.top, bottom: line.bottom, left: line.left, right: line.right},
            box: {top: box.top, bottom: box.bottom, left: box.left, right: box.right},
            text: {left: text.left, right: text.right},
            panelLeft: panel ? panel.getBoundingClientRect().left : null,
            vw: window.innerWidth, vh: window.innerHeight,
            layout: document.querySelector('.reader').dataset.layout,
          };
        }"""
    )


def assert_beside_line(r: dict) -> None:
    """Окно не пересекает строку упоминания и не выходит за окно браузера (4.3)."""
    line, box = r["line"], r["box"]
    if r["layout"] == "K1":
        assert box["left"] >= r["text"]["right"], r  # правее правого края текста
    else:
        assert box["bottom"] <= line["top"] or box["top"] >= line["bottom"], r
    assert box["left"] >= 0 and box["right"] <= r["vw"], r
    assert box["top"] >= 0 and box["bottom"] <= r["vh"], r
    if r["panelLeft"] is not None:
        assert box["right"] <= r["panelLeft"], r


# --- T6: упоминания и сервис знаний недоступен -------------------------------------------


@req(EM, "Показ при чтении")
def test_t6_mentions_are_buttons_and_absent_without_service(browser, site, texts):
    context, page, knowledge = open_reader(browser, site, texts)
    try:
        goto_chapter(page, site)
        mention = kant(page)
        assert mention.get_attribute("role") == "button"
        assert mention.get_attribute("tabindex") == "0"
        assert mention.get_attribute("aria-haspopup") == "dialog"
        assert mention.evaluate("el => el.tagName") == "SPAN"
        assert page.locator("article.chapter .mention").count() > 2
    finally:
        context.close()

    context, page, knowledge = open_reader(browser, site, texts)
    knowledge.mentions_status = 503
    try:
        goto_chapter(page, site)
        page.wait_for_timeout(300)
        assert knowledge.mention_requests, "запрос упоминаний не ушёл"
        assert page.locator("article.chapter .mention").count() == 0
        assert page.locator("[role=alert]").count() == 0  # ошибок на экране нет
        expect(page.locator("p.block", has_text="говорит Кант")).to_be_visible()
    finally:
        context.close()


# --- T7: цвет семьи -----------------------------------------------------------------------


@req(EM, "Показ при чтении")
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_t7_family_colour(browser, site, texts, theme):
    context = reader_context(browser, viewport={"width": 1440, "height": 900}, color_scheme=theme)
    page = context.new_page()
    Knowledge(page, texts)
    try:
        goto_chapter(page, site)
        kant(page)
        expected = page.evaluate(
            """() => {
              const probe = document.createElement('span');
              document.body.appendChild(probe);
              const out = {};
              for (const fam of ['people', 'ideas']) {
                probe.style.textDecorationColor =
                  `color-mix(in oklab, var(--${fam}) 65%, transparent)`;
                out[fam] = getComputedStyle(probe).textDecorationColor;
              }
              probe.remove();
              return out;
            }"""
        )
        person = page.locator(".mention[data-family=people]").first
        concept = page.locator(".mention[data-family=ideas]").first
        got_person = person.evaluate("el => getComputedStyle(el).textDecorationColor")
        got_concept = concept.evaluate("el => getComputedStyle(el).textDecorationColor")
        assert got_person == expected["people"]
        assert got_concept == expected["ideas"]
        assert got_person != got_concept
    finally:
        context.close()


# --- T8: только щелчок, положение, клавиатура ---------------------------------------------


@req(EC, "Карточка рядом с текстом")
def test_t8_hover_never_opens_card(browser, site, texts):
    context, page, knowledge = open_reader(browser, site, texts)
    try:
        goto_chapter(page, site)
        mention = kant(page)
        mention.hover()
        page.wait_for_timeout(2000)
        assert page.get_by_role("dialog").count() == 0
        mentions = page.locator("article.chapter .mention")
        for i in range(5):
            mentions.nth(i).hover()
            page.wait_for_timeout(100)
        assert page.get_by_role("dialog").count() == 0
        assert knowledge.card_requests == []  # запрос карточки не уходил
        mention.click()
        expect(page.get_by_role("dialog", name="Карточка")).to_be_visible()
        assert knowledge.card_requests == [KANT]
    finally:
        context.close()


@req(EC, "Карточка рядом с текстом")
@pytest.mark.parametrize("width", [1920, 1440, 1280, 1024])
def test_t8_popover_beside_mention_line(browser, site, texts, width):
    context, page, _ = open_reader(browser, site, texts, width=width)
    try:
        goto_chapter(page, site)
        mention = kant(page)
        mention.click()
        dialog = page.get_by_role("dialog", name="Карточка")
        opened(dialog, "Кант")
        assert mention.get_attribute("aria-expanded") == "true"
        assert mention.get_attribute("aria-controls") == "card-popup"
        assert_beside_line(rects(page, mention))
        scroll = page.evaluate("document.documentElement.scrollWidth")
        assert scroll <= width + 1  # окно не создаёт горизонтальной прокрутки
    finally:
        context.close()


@req(EC, "Карточка рядом с текстом")
def test_t8_close_by_esc_outside_and_repeated_click(browser, site, texts):
    context, page, _ = open_reader(browser, site, texts)
    try:
        goto_chapter(page, site)
        mention = kant(page)
        dialog = page.get_by_role("dialog", name="Карточка")
        # Esc: окно закрывается, фокус на упоминании.
        mention.click()
        opened(dialog, "Кант")
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)
        assert mention.evaluate("el => el === document.activeElement")
        assert mention.get_attribute("aria-expanded") == "false"
        # Enter: окно открывается, фокус на заголовке окна.
        page.keyboard.press("Enter")
        opened(dialog, "Кант")
        expect(dialog.locator("h3")).to_be_focused()
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)
        # Space тоже открывает и не прокручивает страницу.
        y = page.evaluate("window.scrollY")
        page.keyboard.press(" ")
        opened(dialog, "Кант")
        assert page.evaluate("window.scrollY") == y
        page.keyboard.press("Escape")
        # Щелчок мимо окна закрывает его.
        mention.click()
        dialog.wait_for()
        page.locator("article.chapter h1").click()
        expect(dialog).to_have_count(0)
        # Повторный щелчок по тому же упоминанию закрывает окно.
        mention.click()
        dialog.wait_for()
        mention.click()
        expect(dialog).to_have_count(0)
    finally:
        context.close()


@req(EC, "Карточка рядом с текстом")
def test_t8_drag_selection_from_mention_does_not_open(browser, site, texts):
    context, page, knowledge = open_reader(browser, site, texts)
    try:
        goto_chapter(page, site)
        mention = kant(page)
        box = mention.bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x - 120, y, steps=8)
        page.mouse.up()
        page.wait_for_timeout(300)
        assert page.get_by_role("dialog").count() == 0
        assert knowledge.card_requests == []
        assert page.evaluate("window.getSelection().toString().length") > 0
    finally:
        context.close()


# --- T9: переворот окна вверх -------------------------------------------------------------


@req(EC, "Карточка рядом с текстом")
def test_t9_popover_flips_above_line_at_bottom(browser, site, texts):
    context, page, _ = open_reader(browser, site, texts, width=1280, height=800)
    try:
        goto_chapter(page, site)
        assert page.locator(".reader").get_attribute("data-layout") == "K2"
        mention = page.locator("p.block", has_text="Абзац 12 ").locator(".mention")
        mention.wait_for()
        # Строка упоминания — последняя видимая строка окна.
        mention.evaluate(
            "el => window.scrollBy(0, el.getBoundingClientRect().bottom - window.innerHeight + 4)"
        )
        mention.click()
        page.get_by_role("dialog", name="Карточка").locator("h3", has_text="Опыт").wait_for()
        r = rects(page, mention)
        assert r["box"]["bottom"] <= r["line"]["top"], r  # низ окна выше верха строки
        assert_beside_line(r)
    finally:
        context.close()


# --- T10: переход по связи и «Назад» -------------------------------------------------------


@req(EC, "Карточка рядом с текстом")
def test_t10_link_and_back_in_popover_and_panel(browser, site, texts):
    context, page, _ = open_reader(browser, site, texts)
    try:
        goto_chapter(page, site)
        kant(page).click()
        dialog = page.get_by_role("dialog", name="Карточка")
        opened(dialog, "Кант")
        dialog.get_by_role("button", name="Юм").click()
        expect(dialog.locator("h3")).to_have_text("Юм")
        dialog.get_by_role("button", name="Назад").click()
        expect(dialog.locator("h3")).to_have_text("Кант")
        # То же в панели: «Назад» подписан, куда вернёт.
        dialog.get_by_role("button", name="Открыть карточку").click()
        panel = page.get_by_role("complementary", name="Карточка")
        panel.locator("h3", has_text="Кант").wait_for()
        panel.locator("[data-section=influence]").get_by_role("button", name="Юм").click()
        expect(panel.locator("h3.pg-entity-head__name")).to_have_text("Юм")
        back = panel.get_by_role("button", name="Назад: Кант")
        expect(back).to_be_visible()
        back.click()
        expect(panel.locator("h3.pg-entity-head__name")).to_have_text("Кант")
        expect(panel.get_by_role("button", name=re.compile("^Назад"))).to_have_count(0)
    finally:
        context.close()


# --- T11: состав окна -----------------------------------------------------------------------


@req(EC, "Карточка рядом с текстом")
@req(EC, "Портреты в карточке")
def test_t11_popover_contents(browser, site, texts):
    context, page, knowledge = open_reader(browser, site, texts)
    knowledge.cards[KANT] = dict(
        CARDS[KANT],
        portraits=[
            {
                "url": f"/portraits/kant-{i}.jpg",
                "width": 400,
                "height": 500,
                "author": "Беккер",
                "year": str(1791 + i),
                "license": "public domain",
                "license_url": "https://example.org/license-kant",
                "source_url": f"https://example.org/kant-{i}",
            }
            for i in range(3)
        ],
    )
    try:
        goto_chapter(page, site)
        kant(page).click()
        dialog = page.get_by_role("dialog", name="Карточка")
        opened(dialog, "Кант")
        # Медальон 56px, одно изображение без счётчика и галереи.
        medallion = dialog.locator(".pg-portrait")
        assert medallion.count() == 1
        assert medallion.evaluate("el => getComputedStyle(el).getPropertyValue('--size')") == "56px"
        # С главным изображением: <img> с src, alt персоны и размерами из данных.
        image = medallion.locator("img")
        assert image.count() == 1
        assert image.get_attribute("src").endswith("/portraits/kant-0.jpg")
        assert image.get_attribute("alt") == "Кант"
        assert image.get_attribute("width") == "400"
        assert image.get_attribute("height") == "500"
        assert dialog.locator(".pg-portrait-gallery, .pg-portrait-gallery__count").count() == 0
        assert dialog.locator(".card-popup__facts .card-row").count() == 2  # из трёх строк
        assert "Юм" in dialog.locator(".card-popup__facts").inner_text()  # проверенная первой
        assert dialog.get_by_role("switch").count() == 0  # нет переключателей источников
        assert dialog.get_by_label("Только выбранный учебник").count() == 0
        text = dialog.locator(".card-description").inner_text()
        assert text == "Немецкий философ. Основатель критической философии."
        assert "…" not in text
        clipped = dialog.evaluate(
            """box => [...box.querySelectorAll('h3, p, li, button')]
                .filter(el => el.scrollWidth > el.clientWidth + 1)
                .map(el => el.textContent)"""
        )
        assert clipped == []

        # Без изображений: монограмма, без <img>.
        page.keyboard.press("Escape")
        knowledge.cards[KANT] = dict(CARDS[KANT], portraits=[])
        page.reload()
        kant(page).click()
        opened(dialog, "Кант")
        medallion = dialog.locator(".pg-portrait")
        assert medallion.count() == 1
        assert medallion.evaluate("el => el.classList.contains('pg-portrait--empty')") is True
        assert medallion.locator("img").count() == 0
    finally:
        context.close()


# --- T15: загрузка, не найдена, сбой --------------------------------------------------------


CATALOG = {
    "ru-RU": {
        "label": "Карточка",
        "loading": "Загружаем карточку…",
        "not_found": "Карточки нет",
        "failed": "Карточку не удалось загрузить",
        "retry": "Повторить",
    },
    "en-US": {
        "label": "Card",
        "loading": "Loading the card…",
        "not_found": "There is no card",
        "failed": "The card could not be loaded",
        "retry": "Retry",
    },
}


@req(EC, "Карточка рядом с текстом")
@pytest.mark.parametrize("locale", ["ru-RU", "en-US"])
def test_t15_loading_not_found_and_failure(browser, site, texts, locale):
    words = CATALOG[locale]
    context, page, knowledge = open_reader(browser, site, texts, locale=locale)
    try:
        goto_chapter(page, site)
        mention = kant(page)
        dialog = page.get_by_role("dialog", name=words["label"])
        # S2: пока ответа нет — имя из текста упоминания и «Загружаем карточку…».
        knowledge.hold = True
        mention.click()
        expect(dialog.locator("h3")).to_have_text("Кант")
        expect(dialog.get_by_text(words["loading"])).to_be_visible()
        assert dialog.locator("h3", has_text="…").count() == 0
        knowledge.release()
        expect(dialog.get_by_text(words["loading"])).to_have_count(0)
        expect(dialog.locator(".card-dates")).to_have_text("1724–1804")
        page.keyboard.press("Escape")

        # S3: 404 entity_not_found.
        knowledge.card_status[EXPERIENCE] = 404
        concept = page.locator(".mention[data-family=ideas]").first
        concept.click()
        expect(dialog.get_by_role("alert")).to_contain_text(words["not_found"])
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)

        # S3a: 503, «Повторить» отправляет запрос снова.
        knowledge.card_status[EXPERIENCE] = 503
        concept.click()
        expect(dialog.get_by_role("alert")).to_contain_text(words["failed"])
        before = knowledge.card_requests.count(EXPERIENCE)
        knowledge.card_status[EXPERIENCE] = 200
        # Щелчок — после появления окна (анимация 9.5): иначе Playwright, не дождавшись
        # «стабильной» кнопки, прокручивает её к краю окна, строка упоминания уходит из вида,
        # и окно закрывается по правилу 4.3 — артефакт сценария, не продукта.
        dialog.evaluate("e => Promise.all(e.getAnimations().map(a => a.finished))")
        dialog.get_by_role("button", name=words["retry"]).click()
        expect(dialog.locator("h3")).to_have_text("Опыт")
        assert knowledge.card_requests.count(EXPERIENCE) == before + 1
    finally:
        context.close()


# --- N11: глава больше 500 абзацев ---------------------------------------------------------


LONG_CHAPTER = 1100


@pytest.fixture(scope="module")
def long_source(site, tmp_path_factory) -> str:
    paragraphs = "".join(
        f"<p>Абзац {i}: {'Кант пишет об этом.' if i % 100 == 99 else 'текст без имён.'}</p>"
        for i in range(LONG_CHAPTER)
    )
    book = epub([("Глава длинная", paragraphs)])
    tmp = tmp_path_factory.mktemp("long")
    pipeline = Pipeline(site.registry, FileStore(tmp / "files"), lambda spec: book)
    source_id = site.registry.register(
        "operator",
        title="Длинная книга",
        authors=["Автор"],
        year=1900,
        language="ru",
        kind="textbook",
        license=License("public-domain", "public_domain", author_death_years=[1900]),
        scope="public",
        files=[{"name": "l", "path": "long.epub"}],
    )
    site.registry.publish("operator", pipeline.start("operator", source_id))
    site.ids["long"] = source_id
    return source_id


@req(EM, "Показ при чтении")
def test_n11_mentions_requested_in_parts_of_500(browser, site, long_source):
    texts = {block: text for _, block, text in site.paragraphs("long")}
    assert len(texts) >= LONG_CHAPTER
    context, page, knowledge = open_reader(browser, site, texts)
    try:
        goto_chapter(page, site, "long")
        expected = sum(1 for text in texts.values() if "Кант" in text)
        expect(page.locator("article.chapter .mention")).to_have_count(expected)
        assert len(knowledge.mention_requests) == 3  # 1100 абзацев → 500 + 500 + 100
        assert all(len(part) <= 500 for part in knowledge.mention_requests)
        asked = [x for part in knowledge.mention_requests for x in part]
        assert len(asked) == len(set(asked))  # без повторов
        assert set(texts) <= set(asked)
        # Упоминание из третьей части на месте: абзац 1099.
        last = page.locator("p.block", has_text="Абзац 1099:").locator(".mention")
        expect(last).to_have_text("Кант")
    finally:
        context.close()


# --- Полная карточка в панели: T12, T16, N10 -----------------------------------------------


def open_full(page, site):
    """Окно у «Кант» → «Открыть карточку»: полная карточка в правой панели."""
    goto_chapter(page, site)
    kant(page).click()
    dialog = page.get_by_role("dialog", name="Карточка")
    opened(dialog, "Кант")
    dialog.get_by_role("button", name="Открыть карточку").click()
    panel = page.get_by_role("complementary", name="Карточка")
    panel.locator("h3.pg-entity-head__name", has_text="Кант").wait_for()
    return panel


@req(EC, "Природа каждой строки")
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_t12_nature_of_each_row(browser, site, texts, theme):
    context = reader_context(browser, viewport={"width": 1440, "height": 900}, color_scheme=theme)
    page = context.new_page()
    knowledge = Knowledge(page, texts)
    knowledge.cards[KANT] = dict(
        CARDS[KANT],
        sections=[
            {
                "code": "influence",
                "title": "Влияния",
                "rows": [
                    row(
                        "v1",
                        "influenced_by",
                        "испытал влияние",
                        entity_id=HUME,
                        label="Юм",
                        status="verified",
                    ),
                    row(
                        "g1",
                        "influenced_by",
                        "испытал влияние",
                        entity_id="e_leibniz",
                        label="Лейбниц",
                        status="generated",
                        generated=True,
                    ),
                    row(
                        "d1",
                        "influenced_by",
                        "испытал влияние",
                        entity_id="e_wolff",
                        label="Вольф",
                        disputed=True,
                        evidence=[{"paragraph_id": "x", "link": "/p/x"}],
                        attributions=[
                            {"who": "Асмус", "kind": "source", "stance": "asserts"},
                            {"who": "Рассел", "kind": "source", "stance": "disputes"},
                        ],
                    ),
                ],
            }
        ],
    )
    try:
        panel = open_full(page, site)
        rows = panel.locator("[data-section=influence] li.card-row")
        expect(rows).to_have_count(3)
        verified, generated, disputed = rows.nth(0), rows.nth(1), rows.nth(2)
        # Проверенная — StatusMark значком и словом.
        expect(verified.locator(".pg-status--verified")).to_have_text("Проверено")
        assert verified.locator(".pg-generated").count() == 0
        # Сгенерированная — pg-generated с ромбом и словом.
        expect(generated.locator(".pg-generated")).to_have_count(1)
        mark = generated.locator(".pg-generated").get_by_role("img", name="Сгенерировано")
        expect(mark).to_be_visible()
        expect(generated.locator(".pg-status--generated")).to_have_text("Сгенерировано")
        # Спорная — «Спорно» и «не согласны: …»; кто так считает.
        expect(disputed.locator(".card-disputed")).to_contain_text("Спорно")
        expect(disputed).to_contain_text("не согласны: Рассел")
        expect(disputed).to_contain_text("так считает: Асмус, Рассел")
        # Сводка природы знания, без отдельной метки карточки (Р4).
        expect(panel.locator(".card-summary")).to_have_text(
            "Проверено: 1 · По источникам: 1 · Сгенерировано: 1"
        )
    finally:
        context.close()


def portraits(n: int) -> list[dict]:
    return [
        {
            "url": f"/portraits/kant-{i}.jpg",
            "width": 400,
            "height": 500,
            "author": f"Художник {i}",
            "year": str(1760 + i),
            "license": "public domain",
            "license_url": f"https://example.org/license-{i}",
            "source_url": f"https://example.org/kant-{i}",
        }
        for i in range(n)
    ]


@req(EC, "Портреты в карточке")
def test_t16_portrait_gallery(browser, site, texts):
    context, page, knowledge = open_reader(browser, site, texts)
    try:
        # Пять изображений: счётчик, точки, листание кнопками, точками, стрелками.
        knowledge.cards[KANT] = dict(CARDS[KANT], portraits=portraits(5))
        panel = open_full(page, site)
        gallery = panel.locator(".pg-portrait-gallery")
        image = gallery.locator("img")
        count = gallery.locator(".pg-portrait-gallery__count")
        expect(count).to_have_text("1 из 5")
        expect(gallery.locator(".pg-portrait-gallery__dot")).to_have_count(5)
        credit = gallery.locator(".pg-portrait-gallery__credit")
        expect(credit).to_contain_text("Художник 0")
        expect(credit).to_contain_text("1760")
        license_link = credit.locator("a", has_text="Лицензия")
        expect(license_link).to_have_attribute("href", "https://example.org/license-0")
        source_link = credit.locator("a", has_text="Источник")
        expect(source_link).to_have_attribute("href", "https://example.org/kant-0")
        assert image.get_attribute("width") == "400"
        assert image.get_attribute("height") == "500"
        seen = {image.get_attribute("src")}
        gallery.get_by_role("button", name="Следующий портрет").click()
        expect(count).to_have_text("2 из 5")
        seen.add(image.get_attribute("src"))
        gallery.focus()
        page.keyboard.press("ArrowRight")
        expect(count).to_have_text("3 из 5")
        seen.add(image.get_attribute("src"))
        gallery.locator(".pg-portrait-gallery__dot").nth(4).click()
        expect(count).to_have_text("5 из 5")
        seen.add(image.get_attribute("src"))
        gallery.focus()
        page.keyboard.press("ArrowLeft")
        expect(count).to_have_text("4 из 5")
        seen.add(image.get_attribute("src"))
        gallery.get_by_role("button", name="Предыдущий портрет").click()
        expect(count).to_have_text("3 из 5")
        assert len(seen) == 5  # изображения различны
        panel.get_by_role("button", name="Закрыть карточку").click()

        # Одно изображение: без счётчика и точек.
        knowledge.cards[KANT] = dict(CARDS[KANT], portraits=portraits(1))
        page.reload()
        panel = open_full(page, site)
        gallery = panel.locator(".pg-portrait-gallery")
        expect(gallery.locator("img")).to_have_count(1)
        assert gallery.locator(".pg-portrait-gallery__count").count() == 0
        assert gallery.locator(".pg-portrait-gallery__dot").count() == 0
        panel.get_by_role("button", name="Закрыть карточку").click()

        # Общественное достояние без адреса лицензии: лицензия в подписи есть, ссылки нет.
        one = portraits(1)
        one[0]["license"] = "pd"
        one[0]["license_url"] = None
        knowledge.cards[KANT] = dict(CARDS[KANT], portraits=one)
        page.reload()
        panel = open_full(page, site)
        credit = panel.locator(".pg-portrait-gallery__credit")
        expect(credit).to_contain_text("Лицензия: pd")
        assert credit.locator("a", has_text="Лицензия").count() == 0
        assert credit.locator("a", has_text="Источник").count() == 1
        panel.get_by_role("button", name="Закрыть карточку").click()

        # Ошибка загрузки: вместо битой картинки — пустое состояние с монограммой.
        knowledge.cards[KANT] = dict(CARDS[KANT], portraits=portraits(1))
        page.route("**/portraits/kant-0.jpg", lambda route: route.fulfill(status=500, body=""))
        page.reload()
        panel = open_full(page, site)
        gallery = panel.locator(".pg-portrait-gallery")
        assert "pg-portrait-gallery--empty" in (gallery.get_attribute("class") or "")
        assert gallery.locator("img").count() == 0
        expect(gallery.locator(".pg-portrait-gallery__empty")).to_contain_text("Изображений нет")
        panel.get_by_role("button", name="Закрыть карточку").click()

        # Без изображений: монограмма и «Изображений нет».
        knowledge.cards[KANT] = dict(CARDS[KANT], portraits=[])
        page.reload()
        panel = open_full(page, site)
        gallery = panel.locator(".pg-portrait-gallery")
        expect(gallery.locator(".pg-portrait--empty")).to_have_count(1)
        expect(gallery).to_contain_text("Изображений нет")
        assert gallery.locator("img").count() == 0
    finally:
        context.close()


@req(EM, "Где читать")
@req(EC, "Карточка рядом с текстом")
def test_n10_where_to_read_opens_first_paragraph(browser, site, texts):
    context, page, knowledge = open_reader(browser, site, texts)
    blocks = site.paragraphs("textbook")
    first_chapter = blocks[0][0]
    later = [(chapter, block) for chapter, block, _ in blocks if chapter != first_chapter]
    target_chapter, target = later[3]  # абзац в середине главы 2, не первый
    last_chapter = blocks[-1][0]
    source = site.ids["textbook"]
    knowledge.cards[KANT] = dict(
        CARDS[KANT],
        where_to_read=[
            {
                "source_id": source,
                "source_title": "История теории познания",
                "chapter_id": target_chapter,
                "chapter_title": "Глава 2. Рассудок",
                "count": 2,
                "targets": [target],
                "first_paragraph_id": target,
            },
            {
                "source_id": source,
                "source_title": "История теории познания",
                "chapter_id": last_chapter,
                "chapter_title": "Глава 3. Разум",
                "count": 1,
                "targets": [],
                "first_paragraph_id": None,
            },
        ],
    )
    try:
        panel = open_full(page, site)
        where = panel.locator("[data-section=where]")
        where.get_by_role("button", name="Глава 2. Рассудок").click()
        page.wait_for_url(re.compile(f"/read/{source}/{target_chapter}#p-{target}$"))
        expect(page.locator(f"#p-{target}")).to_be_in_viewport()
        # Без first_paragraph_id — к началу главы.
        where.get_by_role("button", name="Глава 3. Разум").click()
        page.wait_for_url(re.compile(f"/read/{source}/{last_chapter}$"))
        # Панель и окно после перезагрузки не восстанавливаются (Р6).
        page.reload()
        page.wait_for_selector("article.chapter p.block")
        assert page.get_by_role("complementary", name="Карточка").count() == 0
        assert page.get_by_role("dialog").count() == 0
    finally:
        context.close()
