"""Список открытых книг в боковой панели: закрытие единственной книги (source-library)."""

from __future__ import annotations

import pytest

from ..helpers import aside, sidenav

req = pytest.mark.req
SL = "source-library"


def stored(page) -> dict:
    return page.evaluate("() => JSON.parse(localStorage.getItem('philograph:v4'))")


def read_textbook(page, site) -> str:
    source = site.ids["textbook"]
    page.goto(f"{site.url}/read/{source}")
    page.wait_for_selector("article.chapter p.block")
    return source


@req(SL, "Открытые книги")
def test_close_only_open_book_while_reading(page, site):
    """Единственную открытую книгу можно закрыть: переход в библиотеку, список пуст."""
    page.set_viewport_size({"width": 1440, "height": 900})
    source = read_textbook(page, site)
    assert [o["id"] for o in stored(page)["openSources"]] == [source]
    nav = sidenav(page)
    nav.get_by_role("button", name="Закрыть книгу «История теории познания»").click()
    page.wait_for_url(f"{site.url}/")
    page.wait_for_selector(".library, [data-page=library], h1")
    page.wait_for_timeout(300)  # отложенные эффекты чтения не должны вернуть книгу
    data = stored(page)
    assert data["openSources"] == []
    assert data.get("currentSource") is None
    assert data["positions"][source]["chapterId"]  # место чтения сохранилось
    books = sidenav(page).get_by_role("list", name="Открытые книги").get_by_role("listitem")
    assert books.count() == 1 and "sidebar__empty" in (books.first.get_attribute("class") or "")
    aside(page)
    assert page.locator(".sidebar__count").count() == 0


@req(SL, "Открытые книги")
def test_close_only_open_book_from_library(page, site):
    """Закрытие единственной книги вне экрана чтения — книга уходит, страница остаётся."""
    page.set_viewport_size({"width": 1440, "height": 900})
    read_textbook(page, site)
    page.goto(f"{site.url}/settings")
    page.wait_for_selector("h1")
    sidenav(page).get_by_role("button", name="Закрыть книгу «История теории познания»").click()
    page.wait_for_timeout(300)
    assert stored(page)["openSources"] == []
    assert page.url.endswith("/settings")


@req(SL, "Открытые книги")
def test_closed_last_book_does_not_come_back(page, site):
    """После закрытия последней книги заголовок «Открытые книги» ведёт в библиотеку, а не
    к учебнику по умолчанию; запоздалый ответ экрана чтения не возвращает книгу."""
    page.set_viewport_size({"width": 1440, "height": 900})
    source = site.ids["textbook"]
    toc = {"n": 0}

    def slow_toc(route):
        toc["n"] += 1
        page.wait_for_timeout(800)
        route.continue_()

    page.route("**/sources/*/toc", slow_toc)
    page.goto(f"{site.url}/read/{source}")
    sidenav(page).get_by_role("button", name="Закрыть книгу «История теории познания»").click()
    page.wait_for_url(f"{site.url}/")
    page.wait_for_timeout(1500)  # ответ оглавления пришёл после закрытия
    page.unroute_all(behavior="ignoreErrors")
    assert toc["n"] >= 1
    assert page.url == f"{site.url}/"
    assert stored(page)["openSources"] == []
    header = sidenav(page).get_by_role("link", name="Открытые книги")
    assert header.get_attribute("href") == "/"
    header.click()
    page.wait_for_timeout(300)
    assert page.url == f"{site.url}/"
    assert stored(page)["openSources"] == []
