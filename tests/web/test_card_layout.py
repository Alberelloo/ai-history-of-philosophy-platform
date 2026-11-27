# ruff: noqa: E501 (встроенный JS и длинные формулировки сценариев)
"""Раскладка экрана чтения и полной карточки (redesign-entity-cards: visual-design «Раскладка
экрана чтения», entity-cards «Раскладка полной карточки», компактное окно без выводов).

Стенд — ``knowledge_stack``; карточка открывается в читателе: упоминание «Кант» в первом
абзаце учебника → окно → «Открыть карточку». Серверный якорь — ``knowledge.card.served`` с
``request_id`` ответа карточки.
"""

from __future__ import annotations

import gzip
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

from . import card_world as cw
from .test_map import open_stack_map, settle

req = pytest.mark.req
EC = "entity-cards"
VD = "visual-design"
SERVED = "knowledge.card.served"
CARD = re.compile(r"/api/knowledge/v1/entities/[^/]+/card")
ROOT = Path(__file__).resolve().parents[2]
CH = 11.03  # ширина 1ch шрифта чтения, на которой посчитана таблица сценария
expect.set_options(timeout=8000)


CLIPPED = """() => {
  const body = document.querySelector('#side-panel .pg-panel__body').getBoundingClientRect();
  const bad = [];
  for (const row of document.querySelectorAll('#side-panel .card-row')) {
    const walker = document.createTreeWalker(row, NodeFilter.SHOW_TEXT);
    let right = -1, left = 1e9;
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (!n.textContent.trim() || n.parentElement.closest('[hidden]')) continue;
      const range = document.createRange();
      range.selectNodeContents(n);
      for (const r of range.getClientRects()) { right = Math.max(right, r.right); left = Math.min(left, r.left); }
    }
    const style = getComputedStyle(row).textOverflow;
    if (right > body.right + 0.5 || left < body.left - 0.5 || style === 'ellipsis')
      bad.push(row.textContent.slice(0, 40));
  }
  return bad;
}"""

PIN_NAV = (
    "(() => { const k = 'philograph:v3';"
    " let s = {}; try { s = JSON.parse(localStorage.getItem(k) || '{}'); } catch (e) {}"
    " s.sidebarPinned = true; s.version = 3; localStorage.setItem(k, JSON.stringify(s)); })();"
)


def kant_world(stack, *, long: bool = False, unbroken: bool = False) -> dict[str, str]:
    """Кант с упоминанием в первом абзаце; девять трудов, пять мест, влияния."""
    w = stack.world
    ids = cw.kant(w, stack)
    k = ids["kant"]
    names = [f"Труд номер {i} о критике способностей познания" for i in range(1, 10)]
    works = []
    for i, name in enumerate(names):
        work = w.thing("work", name, str(1781 + i))
        if long and i == 0:  # длинное название с пробелами (данные до правил названий)
            cw.rename(w, work, "Метафизические первоначала естествознания и антропологии " * 2)
        if unbroken and i == 1:  # одно слово без пробелов
            cw.rename(w, work, "Сверхдлинное" + "названиетруда" * 8)
        cw.add(w, work, "author", obj=k, attributions=cw.src(), status="verified")
        works.append(work)
    for i, name in enumerate(["Кёнигсберг", "Лейпциг", "Берлин", "Йена", "Рига"]):
        cw.lived(w, k, cw.place(w, name, 54.71 - i, 20.51 + i), "activity" if i == 0 else None)
    w.describe(k, "Немецкий философ.")  # описание есть: модель не вызывается
    w.mention(k, stack.textbooks["N"], stack.paragraph("N", "Кант пишет об опыте"))
    return {**ids, "works": works}


def start(make, stack, width, height, *, scheme="light", pinned=False):
    context = make(width, height, color_scheme=scheme)
    if pinned:
        context.add_init_script(PIN_NAV)
    page = context.new_page()
    page.set_default_timeout(8000)
    page.goto(f"{stack.url}/read/{stack.textbooks['N']}")
    page.wait_for_selector("article.chapter p.block")
    return page


def open_card(page, label="Кант"):
    """Упоминание → окно → «Открыть карточку» → полная карточка; ответ карточки."""
    page.locator(".mention", has_text=label).first.click()
    dialog = page.get_by_role("dialog", name="Карточка")
    dialog.locator("h3").first.wait_for()
    with page.expect_response(CARD) as response:
        dialog.get_by_role("button", name="Открыть карточку").click()
    page.locator("#side-panel h3.pg-entity-head__name").first.wait_for()
    page.evaluate("document.fonts.ready.then(() => true)")
    return response.value


def served_for(events, response, **expected):
    rid = response.headers.get("x-request-id")
    assert rid, response.url
    found = events.where(SERVED, request_id=rid)
    assert len(found) == 1, (rid, events.names())
    for key, value in expected.items():
        assert found[0][key] == value, (key, found[0].fields)
    return found[0]


def metrics(page) -> dict:
    return page.evaluate(
        """() => {
          const panel = document.querySelector('#side-panel');
          const p = panel.getBoundingClientRect();
          const text = document.querySelector('article.chapter').getBoundingClientRect();
          const span = document.createElement('span');
          span.style.cssText = 'position:absolute;visibility:hidden;width:1ch;font:var(--type-read-body)';
          document.body.appendChild(span);
          const ch = span.getBoundingClientRect().width;
          span.remove();
          const nav = document.querySelector('.sidebar').getBoundingClientRect();
          const body = panel.querySelector('.pg-panel__body');
          return {
            panel: p.width, panelLeft: p.left, panelRight: p.right, panelTop: p.top,
            panelBottom: p.bottom,
            cssPanel: parseFloat(getComputedStyle(document.documentElement)
              .getPropertyValue('--panel')),
            layout: document.querySelector('.reader').dataset.layout,
            mode: panel.dataset.mode, ch, textWidth: text.width, textRight: text.right,
            navRight: nav.right, scrollW: document.documentElement.scrollWidth,
            innerW: window.innerWidth, innerH: window.innerHeight,
            bodyScrollW: body ? body.scrollWidth : null, bodyClientW: body ? body.clientWidth : null,
            bodyScrollH: body ? body.scrollHeight : null, bodyClientH: body ? body.clientHeight : null,
          };
        }"""
    )


# --- Раскладка экрана чтения: ширина панели по окну -----------------------------------------

TABLE = [
    # окно, навигация закреплена, ширина .side-panel, раскладка
    (1024, False, 576, "K3"),
    (1280, False, 472, "K4"),
    (1366, False, 560, "K4"),
    (1440, False, 536, "K3"),
    (1680, False, 576, "K2"),
    (1680, True, 552, "K3"),
    (1920, False, 528, "K1"),
]


@req(VD, "Раскладка экрана чтения", scenario="Ширина панели по окну")
@pytest.mark.parametrize("width,pinned,panel,layout", TABLE)
def test_panel_width_by_window(
    knowledge_context, knowledge_stack, events, width, pinned, panel, layout
):
    kant_world(knowledge_stack)
    page = start(knowledge_context, knowledge_stack, width, 800, pinned=pinned)
    # Открытая панель с ассистентом (Alt+Q), затем карточка поверх: стек панели.
    page.keyboard.press("Alt+KeyQ")
    page.locator("#side-panel").wait_for()
    page.evaluate("document.fonts.ready.then(() => true)")
    with_assistant = metrics(page)
    response = open_card(page)
    with_card = metrics(page)
    assert abs(with_card["ch"] - CH) < 0.1, with_card["ch"]
    assert abs(with_card["panel"] - panel) <= 1, with_card
    assert abs(with_card["cssPanel"] - with_card["panel"]) <= 1, with_card
    assert with_card["layout"] == layout, with_card
    assert 62 * with_card["ch"] - 1 <= with_card["textWidth"] <= 68 * with_card["ch"] + 1, with_card
    if width >= 1280:
        assert with_card["textRight"] <= with_card["panelLeft"] - 24 + 1, with_card
    else:
        assert with_card["panelLeft"] >= with_card["navRight"], with_card  # навигацию не закрывает
    assert with_card["scrollW"] <= with_card["innerW"], with_card
    # Карточка вместо ассистента: ширина и раскладка не меняются.
    assert abs(with_assistant["panel"] - with_card["panel"]) <= 1, (with_assistant, with_card)
    assert with_assistant["layout"] == with_card["layout"]
    page.locator("#side-panel").get_by_role("button", name="Назад").first.click()
    page.locator('#side-panel[aria-label="Ассистент"]').wait_for()
    back = metrics(page)
    assert abs(back["panel"] - panel) <= 1 and back["layout"] == layout, back
    served_for(events, response, type="person", layout="person")
    assert page.context.errors == []


@req(VD, "Раскладка экрана чтения", invariant="ширина открытой панели > 448px на 1024, 1366 и 1920")
@pytest.mark.parametrize("width", [1024, 1366, 1920])
def test_panel_wider_than_448(knowledge_context, knowledge_stack, events, width):
    kant_world(knowledge_stack)
    page = start(knowledge_context, knowledge_stack, width, 800)
    response = open_card(page)
    found = metrics(page)
    assert found["panel"] > 448, found
    assert found["cssPanel"] > 448, found
    served_for(events, response, type="person")


@req(VD, "Раскладка экрана чтения", invariant="колонка текста при открытой панели не уже 62ch")
@pytest.mark.parametrize("width", [1024, 1280, 1366, 1440, 1600, 1680, 1920, 2560])
def test_text_column_with_open_panel(knowledge_context, knowledge_stack, events, width):
    kant_world(knowledge_stack)
    page = start(knowledge_context, knowledge_stack, width, 800)
    response = open_card(page)
    found = metrics(page)
    assert 62 * found["ch"] - 1 <= found["textWidth"] <= 68 * found["ch"] + 1, found
    assert found["scrollW"] <= found["innerW"], found
    served_for(events, response, type="person")


@req(
    VD,
    "Раскладка экрана чтения",
    invariant="при закреплённой навигации и открытой панели колонка текста не уже 62ch (порог K4)",
)
@pytest.mark.parametrize(
    "width", [1280, 1366, 1440, 1471, 1472, 1473, 1474, 1475, 1476, 1480, 1600, 1680, 1920]
)
def test_text_column_with_open_panel_and_pinned_navigation(
    knowledge_context, knowledge_stack, events, width
):
    kant_world(knowledge_stack)
    page = start(knowledge_context, knowledge_stack, width, 800, pinned=True)
    response = open_card(page)
    found = metrics(page)
    assert 62 * found["ch"] - 1 <= found["textWidth"] <= 68 * found["ch"] + 1, found
    assert found["scrollW"] <= found["innerW"], found
    sidebar = page.locator(".sidebar")
    state = sidebar.get_attribute("data-state")
    assert state in ("pinned", "collapsed"), state
    if state == "collapsed":  # причина сворачивания названа: закрепление недоступно
        expect(sidebar.locator('button[aria-disabled="true"]')).to_have_count(1)
    else:
        expect(sidebar.locator('button[aria-disabled="true"]')).to_have_count(0)
    served_for(events, response, type="person")


@req(VD, "Раскладка экрана чтения", scenario="Полоска справа")
def test_strip_expands_over_text(knowledge_context, knowledge_stack, events):
    kant_world(knowledge_stack)
    page = start(knowledge_context, knowledge_stack, 1024, 800)
    before = metrics_closed(page)
    response = open_card(page)
    panel = page.locator("#side-panel")
    expect(panel).to_have_attribute("data-mode", "strip")
    found = metrics(page)
    assert abs(found["panel"] - 576) <= 1 and found["layout"] == before["layout"] == "K3", found
    assert found["panelLeft"] >= found["navRight"]
    panel.locator(".side-panel__collapse").click()
    strip = page.locator(".side-panel__strip")
    strip.wait_for()
    box = strip.bounding_box()
    assert box["width"] == 48 or abs(box["width"] - 48) <= 1, box
    assert abs(box["x"] + box["width"] - 1024) <= 1 and box["height"] >= 700, box
    strip.click()
    page.locator("#side-panel").wait_for()
    assert abs(metrics(page)["panel"] - 576) <= 1
    assert metrics(page)["layout"] == "K3"
    served_for(events, response, type="person")


def metrics_closed(page) -> dict:
    return page.evaluate(
        "() => ({layout: document.querySelector('.reader').dataset.layout,"
        " scrollW: document.documentElement.scrollWidth})"
    )


@req(VD, "Раскладка экрана чтения", scenario="Оглавление важнее поля")
@req(VD, "Раскладка экрана чтения", scenario="Панель сдвигает колонки")
def test_toc_kept_field_dropped_when_panel_opens(knowledge_context, knowledge_stack, events):
    kant_world(knowledge_stack)
    page = start(knowledge_context, knowledge_stack, 1680, 800)
    closed = metrics_closed(page)
    assert closed["layout"] == "K1"
    text_before = page.locator("article.chapter").bounding_box()
    response = open_card(page)
    found = metrics(page)
    assert found["layout"] == "K2"  # поле сносок ушло, оглавление осталось
    expect(page.locator(".toc")).to_be_visible()
    text_after = page.locator("article.chapter").bounding_box()
    assert text_after["x"] + text_after["width"] <= found["panelLeft"] - 24 + 1
    assert text_after["x"] != text_before["x"] or text_after["width"] != text_before["width"]
    served_for(events, response, type="person")


@req(VD, "Раскладка экрана чтения", scenario="Состав раскладок")
@req(VD, "Раскладка экрана чтения", scenario="Колонка текста в пределах меры")
@pytest.mark.parametrize(
    "width,mode", [(2560, "K1"), (1920, "K1"), (1440, "K1"), (1280, "K2"), (1024, "K3")]
)
def test_closed_panel_layout_modes(knowledge_context, knowledge_stack, events, width, mode):
    kant_world(knowledge_stack)
    page = start(knowledge_context, knowledge_stack, width, 800)
    found = page.evaluate(
        """() => {
          const t = document.querySelector('article.chapter').getBoundingClientRect().width;
          const span = document.createElement('span');
          span.style.cssText = 'position:absolute;visibility:hidden;width:1ch;font:var(--type-read-body)';
          document.body.appendChild(span);
          const ch = span.getBoundingClientRect().width; span.remove();
          const q = s => document.querySelector(s);
          return {layout: q('.reader').dataset.layout, ch: t / ch,
                  toc: !!q('nav.toc'), rail: !!q('.rail'), field: !!q('.notes-field, .reader__field'),
                  scrollW: document.documentElement.scrollWidth, innerW: innerWidth};
        }"""
    )
    assert found["layout"] == mode, found
    assert 62 - 0.2 <= found["ch"] <= 68 + 0.2, found
    assert found["scrollW"] <= found["innerW"]
    assert found["toc"] == (mode in ("K1", "K2")) and found["rail"] == (mode == "K3")
    assert not events.of(SERVED)  # панель закрыта — карточки не запрашивались


# --- Раскладка полной карточки -------------------------------------------------------------

SIZES = [(1024, 576), (1366, 768), (1920, 1080)]


@req(EC, "Раскладка полной карточки", scenario="Три размера окна")
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_card_fits_panel_in_three_sizes(knowledge_context, knowledge_stack, events, scheme):
    kant_world(knowledge_stack, long=True)
    for width, height in SIZES:
        page = start(knowledge_context, knowledge_stack, width, height, scheme=scheme)
        response = open_card(page)
        found = metrics(page)
        assert found["scrollW"] <= found["innerW"], (width, found)
        assert found["bodyScrollW"] <= found["bodyClientW"], (width, found)
        assert found["bodyScrollH"] > found["bodyClientH"], (width, found)  # прокрутка в теле
        assert (
            found["panel"] > 448
            and abs(found["panel"] - {1024: 576, 1366: 560, 1920: 528}[width]) <= 1
        )
        if width != 1024:
            assert found["textRight"] <= found["panelLeft"] - 24 + 1, (width, found)
        assert found["panelLeft"] >= found["navRight"] - 1, (width, found)
        assert found["panelTop"] >= 0 and found["panelBottom"] <= found["innerH"] + 1, found
        rows = page.locator("#side-panel .card-row")
        assert rows.count() > 8
        clipped = page.evaluate(CLIPPED)
        assert clipped == [], (width, clipped)
        # Длинная карточка прокручивается в теле панели, страница остаётся на месте.
        page.locator("#side-panel .pg-panel__body").evaluate(
            "el => { el.scrollTop = el.scrollHeight; }"
        )
        assert page.evaluate("() => window.scrollY") == 0
        assert page.evaluate(
            "() => getComputedStyle(document.querySelector('.pg-panel__body')).overflowY"
        ) in ("auto", "scroll")
        served_for(events, response, type="person", layout="person")
        page.context.close()


@req(
    EC,
    "Раскладка полной карточки",
    invariant="текст строк не обрезается: длинное слово без пробелов переносится",
)
@pytest.mark.parametrize("width,height", SIZES)
def test_unbroken_long_word_is_wrapped(knowledge_context, knowledge_stack, events, width, height):
    kant_world(knowledge_stack, unbroken=True)
    page = start(knowledge_context, knowledge_stack, width, height)
    response = open_card(page)
    found = metrics(page)
    assert found["bodyScrollW"] <= found["bodyClientW"], found
    assert found["scrollW"] <= found["innerW"], found
    clipped = page.evaluate(CLIPPED)
    assert clipped == [], clipped
    served_for(events, response, type="person")


@req(EC, "Раскладка полной карточки", scenario="Инфобокс по ширине")
def test_infobox_columns_by_window_width(knowledge_context, knowledge_stack, events):
    ids = kant_world(knowledge_stack)
    seen = {}
    for width, height in ((1920, 1080), (1280, 800)):
        page = start(knowledge_context, knowledge_stack, width, height)
        open_card(page)
        with page.expect_response(CARD) as response:
            page.locator("#side-panel [data-section=works] .card-row__entity").first.click()
        page.locator("#side-panel dl.card-facts").first.wait_for()
        served_for(events, response.value, type="work")
        seen[width] = page.evaluate(
            """() => {
              const item = document.querySelector('#side-panel dl.card-facts .card-facts__item');
              const dt = item.querySelector('dt').getBoundingClientRect();
              const dd = item.querySelector('dd').getBoundingClientRect();
              return {dtTop: dt.top, ddTop: dd.top, dtBottom: dt.bottom,
                      panel: document.querySelector('#side-panel').getBoundingClientRect().width};
            }"""
        )
        page.context.close()
    assert seen[1920]["panel"] == 528 and seen[1280]["panel"] == 472, seen
    assert abs(seen[1920]["dtTop"] - seen[1920]["ddTop"]) <= 4, seen  # две колонки
    assert seen[1280]["ddTop"] >= seen[1280]["dtBottom"] - 1, seen  # значение под подписью
    _ = ids


@req(
    EC,
    "Раскладка полной карточки",
    invariant="инфобокс: две колонки от 32rem ширины панели, иначе одна",
)
@pytest.mark.parametrize("width,columns", [(1280, 1), (1680, 2), (1920, 2)])
def test_infobox_columns_follow_panel_width(
    knowledge_context, knowledge_stack, events, width, columns
):
    kant_world(knowledge_stack)
    page = start(knowledge_context, knowledge_stack, width, 900)
    open_card(page)
    with page.expect_response(CARD) as response:
        page.locator("#side-panel [data-section=works] .card-row__entity").first.click()
    page.locator("#side-panel dl.card-facts").first.wait_for()
    found = page.evaluate(
        """() => {
          const item = document.querySelector('#side-panel dl.card-facts .card-facts__item');
          const dt = item.querySelector('dt').getBoundingClientRect();
          const dd = item.querySelector('dd').getBoundingClientRect();
          return {side: Math.abs(dt.top - dd.top) <= 4,
                  panel: document.querySelector('#side-panel').getBoundingClientRect().width,
                  root: parseFloat(getComputedStyle(document.documentElement).fontSize)};
        }"""
    )
    assert (found["panel"] >= 32 * found["root"]) == (columns == 2), found
    assert found["side"] == (columns == 2), found
    served_for(events, response.value, type="work")


# --- Карточка на карте ---------------------------------------------------------------------


@req(EC, "Раскладка полной карточки", scenario="Карточка на карте")
def test_card_on_map_in_three_sizes(knowledge_context, knowledge_stack, events):
    ids = kant_world(knowledge_stack)
    for width, height in SIZES:
        page, _ = open_stack_map(
            knowledge_context, knowledge_stack, f"/graph/{ids['kant']}", width=width, height=height
        )
        with page.expect_response(CARD) as response:
            page.locator(".map-selected").get_by_role("button", name="Открыть карточку").click()
        page.locator("#side-panel h3.pg-entity-head__name").first.wait_for()
        settle(page)
        found = page.evaluate(
            """() => {
              const r = s => { const e = document.querySelector(s);
                return e ? e.getBoundingClientRect() : null; };
              const p = r('#side-panel'), sheet = r('.map-chart'), mp = r('.map-panel');
              return {scrollW: document.documentElement.scrollWidth, innerW: innerWidth,
                      innerH: innerHeight, panel: p, sheet, mp};
            }"""
        )
        assert found["scrollW"] <= found["innerW"], (width, found)
        panel = found["panel"]
        assert panel["left"] >= 0 and panel["right"] <= found["innerW"] + 1, found
        assert panel["top"] >= 0 and panel["bottom"] <= found["innerH"] + 1, found
        assert panel["width"] > 448, (width, found)
        for key in ("sheet", "mp"):
            box = found[key]
            assert box and box["left"] >= -1 and box["right"] <= found["innerW"] + 1, (key, found)
        served_for(events, response.value, type="person")
        assert page.context.errors == []
        page.context.close()


# --- Компактное окно без выведенных строк ---------------------------------------------------


@req(EC, "Выведенные строки", scenario="Компактное окно без выводов")
def test_popup_shows_statements_only(knowledge_context, knowledge_stack, events):
    w = knowledge_stack.world
    berkeley = w.person("Джордж Беркли", "1685", "1753")
    treatise = w.thing("work", "Трактат о началах")
    doctrine = w.thing("doctrine", "Имматериализм")
    cw.add(w, treatise, "author", obj=berkeley, attributions=cw.src(), status="verified")
    cw.add(w, treatise, "discusses", obj=doctrine, attributions=cw.src())
    w.describe(doctrine, "Философское учение.")
    w.mention(
        doctrine,
        knowledge_stack.textbooks["N"],
        knowledge_stack.paragraph("N", "Кант пишет об опыте"),
    )
    page = start(knowledge_context, knowledge_stack, 1440, 900)
    with page.expect_response(CARD) as response:
        page.locator(".mention", has_text="Кант").first.click()
    dialog = page.get_by_role("dialog", name="Карточка")
    dialog.locator("h3", has_text="Имматериализм").wait_for()
    expect(dialog).to_contain_text("Трактат о началах")
    expect(dialog).not_to_contain_text("Беркли")
    page.keyboard.press("Escape")
    assert page.context.errors == []
    assert page.evaluate("window.__consoleErrors") == []
    served_for(events, response.value, type="doctrine", inferred=1)


# --- Сборка --------------------------------------------------------------------------------

BASE_ENTRY_GZIP = 158_566  # фрагмент точки входа до изменения, gzip -9 (progress.md, 3.x)


@req(EC, "Государство основного места", scenario="Основной фрагмент не растёт")
def test_country_data_is_a_separate_chunk():
    dist = ROOT / "web" / "dist"
    if not (dist / "index.html").exists():
        pytest.skip("клиент не собран: npm run build в web/")
    html = (dist / "index.html").read_text(encoding="utf-8")
    entry = re.search(r'<script[^>]+src="/?(assets/index-[^"]+\.js)"', html)
    assert entry, html
    entry_text = (dist / entry.group(1)).read_text(encoding="utf-8")
    chunks = [p for p in (dist / "assets").glob("*.js") if p.name != Path(entry.group(1)).name]
    countries = [p for p in chunks if p.name.startswith("countries-")]
    assert countries, [p.name for p in chunks]
    data = countries[0].read_text(encoding="utf-8")
    assert "Polygon" in data or "arcs" in data  # границы стран лежат в отдельном фрагменте
    assert "Polygon" not in entry_text and '"arcs"' not in entry_text
    assert "countries-" in entry_text  # точка входа ссылается на него динамически
    size = len(gzip.compress(entry_text.encode("utf-8"), 9))
    assert size <= BASE_ENTRY_GZIP + 15 * 1024, size


# --- Временное сворачивание навигации и плавный масштаб -------------------------------------


@req(VD, "Раскладка экрана чтения", scenario="Временное сворачивание навигации")
@pytest.mark.parametrize("width,collapses", [(1366, True), (1440, True), (1680, False)])
def test_pinned_navigation_collapses_while_panel_open(
    knowledge_context, knowledge_stack, events, width, collapses
):
    kant_world(knowledge_stack)
    page = start(knowledge_context, knowledge_stack, width, 800, pinned=True)
    sidebar = page.locator(".sidebar")
    expect(sidebar).to_have_attribute("data-state", "pinned")
    response = open_card(page)
    if collapses:
        expect(sidebar).to_have_attribute("data-state", "collapsed")
        assert abs(sidebar.bounding_box()["width"] - 56) <= 1
        pin = sidebar.locator('button[aria-disabled="true"]')
        expect(pin).to_have_count(1)
        assert pin.get_attribute("title")  # объясняет, почему закрепление недоступно
        page.locator("#side-panel").get_by_role("button", name="Закрыть карточку").click()
        page.locator("#side-panel").wait_for(state="detached")
        expect(sidebar).to_have_attribute("data-state", "pinned")
        expect(sidebar.locator('button[aria-disabled="true"]')).to_have_count(0)
    else:
        expect(sidebar).to_have_attribute("data-state", "pinned")
        expect(sidebar.locator('button[aria-disabled="true"]')).to_have_count(0)
        assert sidebar.bounding_box()["width"] > 200
    served_for(events, response, type="person")


@req(VD, "Раскладка экрана чтения", scenario="Плавный масштаб")
def test_root_font_scales_above_1920(browser, site):
    from ..helpers import reader_context

    def clamp(width: int) -> float:
        return min(max(16.0, 0.531 * 16 + 0.0039 * width), 16 * 1.16)

    context = reader_context(browser, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        page.goto(f"{site.url}/read/{site.ids['textbook']}")
        page.wait_for_selector("article.chapter p.block")
        seen = {}
        for width in (1440, 1920, 2560, 3840):
            page.set_viewport_size({"width": width, "height": 900})
            page.evaluate("document.fonts.ready.then(() => true)")
            seen[width] = page.evaluate(
                "() => ({root: parseFloat(getComputedStyle(document.documentElement).fontSize),"
                " text: parseFloat(getComputedStyle(document.querySelector('article.chapter p.block')).fontSize)})"
            )
        assert seen[1440]["root"] == 16.0 and seen[1920]["root"] == 16.0, seen
        for width in (2560, 3840):
            assert abs(seen[width]["root"] - clamp(width)) < 0.05, (width, seen)
        assert seen[2560]["root"] > 18 and seen[3840]["root"] == pytest.approx(18.56, abs=0.01), (
            seen
        )
        # Размеры в rem растут вместе с кеглем: кегль текста чтения — доля корневого.
        ratio = seen[1920]["text"] / seen[1920]["root"]
        for width in (1440, 2560, 3840):
            assert abs(seen[width]["text"] / seen[width]["root"] - ratio) < 0.01, (width, seen)
        assert seen[2560]["text"] > seen[1920]["text"] and seen[3840]["text"] > seen[2560]["text"]
    finally:
        context.close()
