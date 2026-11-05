"""Сквозные сценарии: читатель проходит по живому сайту, тест проверяет экран и журналы."""

from __future__ import annotations

import httpx
import pytest

from .conftest import wait_logs

req = pytest.mark.req
TEXTBOOK = "Теория познания: демонстрационный учебник"
pytestmark = pytest.mark.e2e


def open_textbook(page, stack):
    page.goto(stack.url + "/")
    page.locator(".source", has_text=TEXTBOOK).get_by_role("button", name="Читать").click()
    page.wait_for_selector("h1:text('Глава 1. Опыт и врождённые идеи')")


@req("source-library", "Поиск по названию и автору")
@req("source-library", "Фильтр по виду источника")
def test_library_search_filter_and_choose(page, stack):
    page.goto(stack.url + "/")
    page.wait_for_selector(".source")
    assert page.locator(".source").count() == 2
    page.get_by_label("Поиск по названию и автору").fill("демонстрац")
    page.wait_for_function("document.querySelectorAll('.source').length === 1")
    assert page.locator(".source h2").inner_text() == TEXTBOOK
    page.get_by_label("Поиск по названию и автору").fill("")
    page.get_by_label("Первоисточник").check()
    page.wait_for_selector(".source h2:text('Empiricism: a demonstration reader')")
    page.wait_for_function("document.querySelectorAll('.source').length === 1")
    page.get_by_role("button", name="Сбросить поиск и фильтры").first.click()
    page.wait_for_function("document.querySelectorAll('.source').length === 2")
    textbook = page.locator(".source", has_text=TEXTBOOK)
    assert "По умолчанию" in textbook.inner_text() and "Проект PhiloGraph" in textbook.inner_text()


@req("chapter-reading", "Сноски")
@req("chapter-reading", "Страницы печатного издания")
@req("chapter-reading", "Оглавление")
@req("chapter-reading", "Переход между главами")
def test_reading_journey(page, stack):
    open_textbook(page, stack)
    assert page.locator(".page-mark").all_inner_texts()[:2] == ["с. 11", "с. 12"]
    page.locator(".note-ref").first.hover()
    popup = page.get_by_role("tooltip")
    assert "белой бумаге" in popup.inner_text()
    assert popup.get_by_role("link").get_attribute("href") == "https://example.org/tabula-rasa"
    page.get_by_role("navigation", name="Главы").get_by_role(
        "button", name="Следующая глава →"
    ).click()
    page.wait_for_selector("h1:text('Глава 2. Юм и проблема индукции')")
    toc = page.get_by_role("navigation", name="Оглавление")
    assert toc.locator("[aria-current=true]").inner_text() == "Глава 2. Юм и проблема индукции"
    toc.get_by_role("link", name="Глава 3. Ответ Канта").click()
    page.wait_for_selector("h1:text('Глава 3. Ответ Канта')")
    toc.get_by_role("link", name="Привычка и ожидание").click()
    page.wait_for_selector("h2:text('Привычка и ожидание')")


@req("chapter-reading", "Ссылка на абзац")
def test_copy_and_follow_paragraph_link(page, stack):
    open_textbook(page, stack)
    paragraph = page.locator("p.block", has_text="мрамор с прожилками")
    paragraph.hover()
    paragraph.locator(".copy-link").click()
    link = page.evaluate("navigator.clipboard.readText()")
    assert link.startswith(stack.url + "/p/")
    page.goto(stack.url + "/")
    page.goto(link)
    highlighted = page.locator("p.block.highlight")
    highlighted.wait_for()
    assert "мрамор с прожилками" in highlighted.inner_text()


@req("assistant-dialog", "Вопрос о выделенном фрагменте")
@req("answer-grounding", "Ссылки на абзацы")
@req("answer-grounding", "Пофрагментная пометка")
@req("observability", "Сквозной идентификатор запроса")
def test_assistant_on_selection_through_all_services(page, stack):
    open_textbook(page, stack)
    page.get_by_role("link", name="Глава 2. Юм и проблема индукции").click()
    page.wait_for_selector("h1:text('Глава 2. Юм и проблема индукции')")
    page.evaluate("""() => {
        const p = [...document.querySelectorAll('p.block')]
            .find(e => e.innerText.includes('проблема индукции'));
        const range = document.createRange(); range.selectNodeContents(p.firstChild);
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range);
        p.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
    }""")
    page.get_by_role("button", name="Спросить ассистента").click()
    panel = page.get_by_role("complementary", name="Ассистент")
    panel.get_by_label("Вопрос ассистенту").fill("что здесь значит проблема индукции?")
    panel.get_by_role("button", name="Спросить").click()
    grounded = panel.locator(".fragment:not(.ungrounded)").first
    grounded.wait_for()
    # Фрагменты приходят потоком: ждём и второй, без опоры на источники.
    panel.locator(".fragment.ungrounded .ungrounded-mark").wait_for()
    assert panel.locator(".fragment.ungrounded").count() == 1
    grounded.locator(".citation").first.click()
    page.locator("p.block.highlight").wait_for()

    # Один и тот же идентификатор запроса у шлюза, ассистента, поиска и сервиса LLM.
    done = wait_logs(stack, "assistant", lambda e: e["event"] == "assistant.answer.completed")
    assert done and done[-1]["grounded"] >= 1
    request_id = done[-1]["request_id"]
    for service, event in (
        ("gateway", "http.request.completed"),
        ("search", "search.query.completed"),
        ("llm", "llm.call.completed"),
    ):
        assert wait_logs(
            stack,
            service,
            lambda e, ev=event: e["event"] == ev and e.get("request_id") == request_id,
        ), (service, event)


@req("service-runtime", "Взаимодействие только через интерфейсы сервисов")
def test_internal_interfaces_hidden_behind_gateway(stack):
    response = httpx.get(stack.url + "/api/v1/internal/published")
    assert response.status_code == 404
    assert wait_logs(stack, "gateway", lambda e: e["event"] == "gateway.internal.blocked")


@req("source-library", "Учебник по умолчанию")
@req("source-library", "Запоминание выбранного источника")
def test_first_visit_and_remembered_source(browser, stack):
    context = browser.new_context()
    page = context.new_page()
    page.goto(stack.url + "/read")
    page.wait_for_selector("h1:text('Глава 1. Опыт и врождённые идеи')")
    page.goto(stack.url + "/")
    page.locator(".source", has_text="Empiricism").get_by_role("button", name="Читать").click()
    page.wait_for_selector("p.block:has-text('blank slate')")
    page.goto(stack.url + "/read")
    page.wait_for_selector("p.block:has-text('blank slate')")
    context.close()


@req("ontology-statements", "Реакция на изменения библиотеки")
def test_knowledge_service_receives_library_events(stack):
    received = wait_logs(
        stack,
        "knowledge",
        lambda e: e["event"] == "knowledge.library.event" and e["kind"] == "source.published",
        60,
    )
    assert len({e["event_id"] for e in received}) >= 2  # оба демо-источника


@req("ontology-review", "Доступ")
@req("ontology-review", "Очередь проверки")
@req("ontology-review", "Решения")
def test_operator_reviews_ontology_in_browser(page, stack):
    assert httpx.get(stack.url + "/api/knowledge/v1/review/queue").status_code == 404
    page.goto(stack.url + "/internal/review")
    page.get_by_label("Пароль оператора").fill("не тот пароль")
    page.get_by_role("button", name="Войти").click()
    assert "Неверный пароль" in page.get_by_role("alert").inner_text()
    page.get_by_label("Пароль оператора").fill("demo-operator")
    page.get_by_role("button", name="Войти").click()
    warned = page.locator(".review-item", has_text="influence_against_time")
    warned.get_by_role("button").click()
    context = page.get_by_role("region", name="Утверждение")
    assert "Локк — испытал влияние — Новые опыты" in context.inner_text()
    context.get_by_role("button", name="Отклонить").click()
    page.wait_for_function("!document.body.innerText.includes('influence_against_time')")
    decided = wait_logs(stack, "knowledge", lambda e: e["event"] == "knowledge.review.decided")
    assert decided and decided[-1]["decision"] == "reject"
