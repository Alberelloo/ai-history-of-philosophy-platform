"""Страница проверки портретов оператора (задача 4.3).

Сервер знаний подменяется в браузере (``page.route``): вход оператора, очередь проверки
онтологии (страница считает вход выполненным, когда она отвечает 200) и очередь портретов с
действиями. Проверяется клиент: список черновиков с подписью, лицензией и ссылкой на источник;
«Подтвердить» и «Скрыть»; пустые состояния; ошибки 404/400; клавиатурный фокус на кнопках.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect

from ..helpers import reader_context

req = pytest.mark.req


def portrait(id_: int, **extra) -> dict:
    row = {
        "id": id_,
        "entity_id": f"e_{id_}",
        "label": f"Философ {id_}",
        "file_id": f"file-{id_}",
        "width": 480,
        "height": 600,
        "author": "Художник",
        "year": "1800",
        "license": "pd",
        "license_url": None,
        "source_url": f"https://example.org/source-{id_}",
        "position": id_,
        "status": "draft",
        "hidden": False,
        "created_at": "2026-11-13T00:00:00",
    }
    row.update(extra)
    return row


class Knowledge:
    """Подменённый сервер знаний: вход, очередь онтологии и очереди портретов."""

    def __init__(self, page) -> None:
        self.logged_in = False
        self.drafts: list[dict] = []
        self.approved: list[dict] = []
        self.hidden: list[dict] = []
        self.actions: list[str] = []
        self.errors: dict[tuple[int, str], tuple[int, dict]] = {}
        page.route("**/api/knowledge/v1/operator/login", self._login)
        page.route("**/api/knowledge/v1/review/queue*", self._queue)
        page.route("**/api/knowledge/v1/review/portraits**", self._portraits)
        page.route("**/api/knowledge/v1/portraits/*", self._image)

    def _login(self, route) -> None:
        self.logged_in = True
        route.fulfill(json={"status": "ok"})

    def _queue(self, route) -> None:
        if self.logged_in:
            route.fulfill(json=[])
        else:
            route.fulfill(status=404, json={"kind": "not_found"})

    def _image(self, route) -> None:
        # Превью черновика сервер не отдаёт: адрес отвечает 404 до подтверждения.
        route.fulfill(status=404, json={"kind": "portrait_not_found"})

    def _portraits(self, route) -> None:
        url = urlparse(route.request.url)
        if route.request.method == "POST":
            portrait_id = int(url.path.rstrip("/").split("/")[-1])
            action = parse_qs(url.query).get("action", [""])[0]
            self.actions.append(f"{portrait_id}:{action}")
            error = self.errors.get((portrait_id, action))
            if error:
                route.fulfill(status=error[0], json=error[1])
                return
            row = next(
                (d for d in self.drafts + self.approved + self.hidden if d["id"] == portrait_id),
                None,
            )
            if action == "approve":
                self.drafts = [d for d in self.drafts if d["id"] != portrait_id]
                if row:
                    row["status"] = "approved"
                    self.approved.append(row)
            elif action == "hide":
                self.drafts = [d for d in self.drafts if d["id"] != portrait_id]
                self.approved = [d for d in self.approved if d["id"] != portrait_id]
                if row:
                    row["hidden"] = True
                    self.hidden.append(row)
            elif action == "show":
                self.hidden = [d for d in self.hidden if d["id"] != portrait_id]
                if row:
                    row["hidden"] = False
                    (self.approved if row["status"] == "approved" else self.drafts).append(row)
            route.fulfill(json={"status": "ok"})
            return
        status = parse_qs(url.query).get("status", ["draft"])[0]
        rows = {"draft": self.drafts, "approved": self.approved, "hidden": self.hidden}[status]
        route.fulfill(json=rows)


def open_review(browser, site, *, drafts=None, approved=None, hidden=None, errors=None):
    context = reader_context(browser, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page.set_default_timeout(5000)
    knowledge = Knowledge(page)
    knowledge.drafts = [dict(d) for d in (drafts or [])]
    knowledge.approved = [dict(d) for d in (approved or [])]
    knowledge.hidden = [dict(d) for d in (hidden or [])]
    if errors:
        knowledge.errors = dict(errors)
    return context, page, knowledge


def login(page) -> None:
    page.get_by_label("Пароль оператора").fill("пароль")
    page.get_by_role("button", name="Войти").click()
    page.get_by_role("button", name="Утверждения").wait_for()


def open_portraits(page) -> None:
    page.get_by_role("button", name="Портреты").click()
    page.get_by_label("Статус портрета").wait_for()


# --- очередь черновиков, «Подтвердить» и «Скрыть» -------------------------------------------


@req("entity-portraits", "Проверка оператором")
def test_portraits_queue_approve_and_hide(browser, site):
    context, page, k = open_review(
        browser,
        site,
        drafts=[
            portrait(1, license="cc-by", license_url="https://example.org/lic-1"),
            portrait(2, author=None, year=None),
        ],
    )
    try:
        page.goto(f"{site.url}/internal/review")
        login(page)
        open_portraits(page)
        items = page.locator(".review-item")
        expect(items).to_have_count(2)

        first = items.nth(0)
        expect(first).to_contain_text("Философ 1")
        expect(first).to_contain_text("Художник, 1800")
        license_link = first.locator("a", has_text="Лицензия")
        expect(license_link).to_have_attribute("href", "https://example.org/lic-1")
        expect(license_link).to_contain_text("cc-by")
        expect(first.locator("a", has_text="Источник")).to_have_attribute(
            "href", "https://example.org/source-1"
        )
        expect(first).to_contain_text("480 × 600")
        # Черновик не отдаётся файлом, поэтому вместо картинки — монограмма с подписью.
        expect(first).to_contain_text("Превью появится после подтверждения")

        # Без автора и года подпись показывает только то, что есть (EC-2).
        second = items.nth(1)
        expect(second).to_contain_text("Философ 2")
        expect(second.locator("a", has_text="Лицензия")).to_have_count(0)
        expect(second).to_contain_text("Лицензия: pd")

        # Подтвердить — POST action=approve, элемент уходит из черновиков.
        first.get_by_role("button", name="Подтвердить").click()
        expect(items).to_have_count(1)
        assert "1:approve" in k.actions
        expect(items.nth(0)).to_contain_text("Философ 2")

        # Скрыть черновик — он исчезает, очередь пуста.
        items.nth(0).get_by_role("button", name="Скрыть").click()
        expect(items).to_have_count(0)
        expect(page.get_by_text("Нет портретов на проверке")).to_be_visible()
        assert "2:hide" in k.actions
    finally:
        context.close()


# --- пустые состояния -----------------------------------------------------------------------


@req("entity-portraits", "Проверка оператором")
def test_portraits_empty_and_hidden_empty(browser, site):
    context, page, _ = open_review(browser, site)
    try:
        page.goto(f"{site.url}/internal/review")
        login(page)
        open_portraits(page)
        expect(page.get_by_text("Нет портретов на проверке")).to_be_visible()
        # Скрытые пусты — отдельное сообщение.
        page.get_by_label("Статус портрета").select_option("hidden")
        expect(page.get_by_text("Скрытых нет")).to_be_visible()
    finally:
        context.close()


# --- списки подтверждённых и скрытых, «Сделать главным» и «Вернуть» ------------------------


@req("entity-portraits", "Проверка оператором")
def test_portraits_approved_and_hidden_actions(browser, site):
    context, page, k = open_review(
        browser,
        site,
        approved=[portrait(1, status="approved", license_url="https://example.org/lic-1")],
        hidden=[portrait(2, status="approved", hidden=True)],
    )
    try:
        page.goto(f"{site.url}/internal/review")
        login(page)
        open_portraits(page)
        expect(page.get_by_text("Нет портретов на проверке")).to_be_visible()

        page.get_by_label("Статус портрета").select_option("approved")
        approved_item = page.locator(".review-item")
        expect(approved_item).to_have_count(1)
        expect(approved_item).to_contain_text("Философ 1")
        expect(approved_item.get_by_role("button", name="Подтвердить")).to_have_count(0)
        approved_item.get_by_role("button", name="Сделать главным").click()
        page.wait_for_timeout(200)
        assert "1:main" in k.actions

        page.get_by_label("Статус портрета").select_option("hidden")
        hidden_item = page.locator(".review-item")
        expect(hidden_item).to_have_count(1)
        expect(hidden_item).to_contain_text("Философ 2")
        hidden_item.get_by_role("button", name="Вернуть").click()
        expect(page.locator(".review-item")).to_have_count(0)
        expect(page.get_by_text("Скрытых нет")).to_be_visible()
        assert "2:show" in k.actions
    finally:
        context.close()


# --- ошибки 404/400 показываются текстом ----------------------------------------------------


@req("entity-portraits", "Проверка оператором")
def test_portraits_action_error_text(browser, site):
    context, page, _ = open_review(
        browser,
        site,
        drafts=[portrait(1)],
        errors={
            (1, "approve"): (404, {"kind": "not_found", "error": "Портрет не найден"}),
            (1, "hide"): (
                400,
                {"kind": "unknown_action", "error": "Неизвестное действие с портретом"},
            ),
        },
    )
    try:
        page.goto(f"{site.url}/internal/review")
        login(page)
        open_portraits(page)
        items = page.locator(".review-item")
        expect(items).to_have_count(1)
        items.nth(0).get_by_role("button", name="Подтвердить").click()
        expect(page.get_by_role("alert")).to_contain_text("Портрет не найден")
        items.nth(0).get_by_role("button", name="Скрыть").click()
        expect(page.get_by_role("alert")).to_contain_text("Неизвестное действие с портретом")
    finally:
        context.close()


# --- клавиатурный фокус на кнопках ----------------------------------------------------------


@req("entity-portraits", "Проверка оператором")
def test_portraits_buttons_are_keyboard_focusable(browser, site):
    context, page, _ = open_review(browser, site, drafts=[portrait(1)])
    try:
        page.goto(f"{site.url}/internal/review")
        login(page)
        open_portraits(page)
        first = page.locator(".review-item").nth(0)
        approve = first.get_by_role("button", name="Подтвердить")
        hide = first.get_by_role("button", name="Скрыть")
        # Кнопки — настоящие <button>, их можно получить с клавиатуры.
        assert approve.evaluate("e => e.tagName") == "BUTTON"
        assert hide.evaluate("e => e.tagName") == "BUTTON"
        approve.focus()
        expect(approve).to_be_focused()
    finally:
        context.close()
