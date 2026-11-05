"""Сквозные сценарии: читатель проходит по живому сайту, тест проверяет экран и журналы."""

from __future__ import annotations

import httpx
import pytest

from .conftest import reader_context, wait_logs

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
    context = reader_context(browser)
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


@req("entity-mentions", "Показ при чтении")
@req("entity-cards", "Карточка рядом с текстом")
@req("entity-cards", "Природа каждой строки")
@req("entity-cards", "Скорость карточки")
def test_mention_opens_card_and_navigates(page, stack):
    open_textbook(page, stack)
    page.get_by_role("link", name="Глава 3. Ответ Канта").click()
    page.wait_for_selector("h1:text('Глава 3. Ответ Канта')")
    awakening = page.locator("p.block", has_text="догматического сна")
    mention = awakening.locator(".mention", has_text="Юм")
    mention.wait_for()
    assert awakening.locator(".mention").all_inner_texts() == ["Кант", "Юм"]
    page.evaluate("window.scrollTo(0, 120)")
    scroll = page.evaluate("window.scrollY")
    mention.click()
    card = page.get_by_role("dialog", name="Карточка")
    card.locator("h3:text('Юм')").wait_for()
    assert page.evaluate("window.scrollY") == scroll  # глава не сдвигается
    assert "1711" in card.locator(".card-dates").inner_text()
    influence = card.locator("[data-section=influence]")
    assert "так считает" in influence.inner_text()
    # Описание дописывается потоком и помечено как сгенерированное.
    card.locator(".card-description.ungrounded").get_by_role("img", name="Сгенерировано").wait_for()
    assert "демонстрационный" in card.locator(".card-description").inner_text()
    influence.get_by_role("button", name="Кант", exact=True).click()
    card.locator("h3:text('Кант')").wait_for()
    card.get_by_role("button", name="← Назад").click()
    card.locator("h3:text('Юм')").wait_for()
    # Подтверждающий абзац из строки ведёт к абзацу учебника.
    card.get_by_role("button", name="Кант", exact=True).click()
    card.locator("h3:text('Кант')").wait_for()
    card.locator("[data-section=influence] .citation").first.click()
    page.locator("p.block.highlight", has_text="догматического сна").wait_for()

    indexed = wait_logs(stack, "knowledge", lambda e: e["event"] == "knowledge.mentions.indexed")
    assert any(e["mentions"] > 0 for e in indexed)
    served = wait_logs(stack, "knowledge", lambda e: e["event"] == "knowledge.card.served")
    assert "person" in {e["type"] for e in served}
    described = wait_logs(stack, "knowledge", lambda e: e["event"] == "knowledge.card.description")
    assert "generated" in {e["result"] for e in described}


@req("entity-cards", "Разделы карточки по типу")
@req("entity-mentions", "Где читать")
def test_concept_card_with_definition_and_where_to_read(page, stack):
    open_textbook(page, stack)
    page.get_by_role("link", name="Глава 2. Юм и проблема индукции").click()
    page.wait_for_selector("h1:text('Глава 2. Юм и проблема индукции')")
    page.locator("p.block", has_text="привычка ума").locator(
        ".mention", has_text="причинность"
    ).click()
    card = page.get_by_role("dialog", name="Карточка")
    card.locator("h3:text('Причинность')").wait_for()
    definitions = card.locator("[data-section=definitions]")
    assert "априорная категория рассудка" in definitions.inner_text()
    assert "так считает: Кант" in definitions.inner_text()
    where = card.locator("[data-section=where]")
    # По одному упоминанию в каждой главе, поэтому порядок между ними не задан.
    assert sorted(where.get_by_role("button").all_inner_texts()) == [
        "Глава 2. Юм и проблема индукции",
        "Глава 3. Ответ Канта",
    ]
    assert TEXTBOOK in where.inner_text()
    where.get_by_role("button", name="Глава 3. Ответ Канта").click()
    page.wait_for_selector("h1:text('Глава 3. Ответ Канта')")
    card.get_by_role("button", name="Закрыть карточку").click()
    assert page.get_by_role("dialog", name="Карточка").count() == 0


@req("entity-mentions", "Показ при чтении")
def test_chapter_without_knowledge_service(browser, stack):
    context = reader_context(browser)
    page = context.new_page()
    page.route("**/api/knowledge/**", lambda route: route.abort())
    open_textbook(page, stack)
    page.get_by_role("link", name="Глава 3. Ответ Канта").click()
    page.locator("p.block", has_text="догматического сна").wait_for()
    assert page.locator(".mention").count() == 0
    assert page.get_by_role("alert").count() == 0
    context.close()


def entity_id(stack, name: str) -> str:
    found = httpx.get(stack.url + "/api/knowledge/v1/entities", params={"name": name}).json()
    return found[0]["id"]


def open_graph(page, stack, name: str, recipe: str) -> None:
    open_textbook(page, stack)  # выбранный учебник — для переключателя источников
    page.goto(f"{stack.url}/graph/{entity_id(stack, name)}?recipe={recipe}")


@req("knowledge-graph", "Запрос графа")
@req("knowledge-graph", "Достройка")
@req("knowledge-graph", "Пометка достроенного")
@req("knowledge-graph", "Отложенное сохранение")
@req("knowledge-graph", "Показ графа")
@req("knowledge-graph", "Подробности связи")
@req("source-scope", "Сравнение с другими")
def test_genesis_graph_from_card(page, stack, tmp_path):
    open_textbook(page, stack)
    page.get_by_role("link", name="Глава 3. Ответ Канта").click()
    page.locator("p.block", has_text="догматического сна").locator(
        ".mention", has_text="Кант"
    ).click()
    card = page.get_by_role("dialog", name="Карточка")
    card.locator("[data-section=graph]").get_by_role("button", name="Генезис").click()
    page.wait_for_selector("h1:text('Генезис: Кант')")
    # Сохранённая связь видна сразу, достроенные приходят следом и помечены.
    page.locator(".graph-edge[data-generated=false]").first.wait_for()
    page.wait_for_function(
        "document.querySelectorAll('.graph-edge[data-generated=true]').length === 2"
    )
    x = {
        name: float(page.get_by_role("button", name=name, exact=True).get_attribute("data-x"))
        for name in ("Локк", "Юм", "Кант")
    }
    assert x["Локк"] < x["Юм"] < x["Кант"]  # по времени
    page.get_by_role("button", name="Кант — испытал влияние — Юм").click()
    details = page.get_by_role("region", name="Связь")
    assert f"так считает: {TEXTBOOK}" in details.inner_text()
    assert "Юм пробудил его от догматического сна" in details.inner_text()
    page.get_by_role("button", name="Кант — развивает — Лейбниц").click()
    assert "достроена моделью и не подтверждена" in details.inner_text()
    with page.expect_download() as download:
        page.get_by_role("button", name="Сохранить изображение").click()
    image = tmp_path / "graph.svg"
    download.value.save_as(image)
    exported = image.read_text(encoding="utf-8")
    assert exported.count('stroke-dasharray="6 4"') == 2 and "◇" in exported

    extended = wait_logs(stack, "knowledge", lambda e: e["event"] == "knowledge.graph.extended")
    assert extended[-1]["proposed"] == 2 and extended[-1]["dropped"] == 1  # «жил в» вне рецепта
    assert wait_logs(stack, "knowledge", lambda e: e["event"] == "knowledge.graph.saved")

    # Повторный запрос: достроенное уже сохранено, модель не вызывается.
    page.reload()
    proposed = ("Кант — развивает — Лейбниц", "Юм — испытал влияние — Локк")
    for name in proposed:
        page.locator(f".graph-edge[data-generated=true][aria-label='{name}']").wait_for()
    built = wait_logs(stack, "knowledge", lambda e: e["event"] == "knowledge.graph.built")
    assert built[-1]["extension"] == "done_before"
    assert (
        len(wait_logs(stack, "knowledge", lambda e: e["event"] == "knowledge.graph.extended")) == 1
    )
    page.get_by_role("button", name="Мельче").click()
    page.wait_for_selector("text=Глубина 2 из 3")
    for name in proposed:  # пометка не теряется при смене глубины
        assert page.get_by_role("button", name=name).get_attribute("data-generated") == "true"
    # Сравнение: чего нет в моём учебнике.
    page.get_by_label("Нет в моём учебнике").check()
    page.wait_for_function("!document.querySelector('.graph-edge[data-generated=false]')")
    labels = page.locator(".graph-edge").evaluate_all("els => els.map(e => e.ariaLabel)")
    assert set(proposed) <= set(labels) and "Кант — испытал влияние — Юм" not in labels


@req("source-scope", "Переключатель источников")
@req("source-scope", "Фильтр по атрибуции")
@req("source-scope", "Достройка в режиме учебника")
def test_textbook_scope_shared_by_graph_card_and_assistant(page, stack):
    open_graph(page, stack, "Кант", "genesis")
    page.wait_for_selector("h1:text('Генезис: Кант')")
    page.get_by_label("Только выбранный учебник").check()
    notice = page.get_by_role("status").filter(has_text="только выбранный учебник")
    notice.wait_for()
    page.wait_for_function("document.querySelectorAll('.graph-edge').length === 1")
    assert page.locator(".graph-edge").get_attribute("aria-label") == "Кант — испытал влияние — Юм"
    built = wait_logs(stack, "knowledge", lambda e: e["event"] == "knowledge.graph.built")
    assert built[-1]["extension"] == "scope"
    # То же значение в карточке и в ассистенте.
    page.get_by_role("button", name="Юм", exact=True).click()
    page.get_by_role("region", name="Узел").get_by_role("button", name="Открыть карточку").click()
    card = page.get_by_role("dialog", name="Карточка")
    assert card.get_by_label("Только выбранный учебник").is_checked()
    card.get_by_role("button", name="Закрыть карточку").click()
    page.get_by_role("button", name="← К чтению").click()
    page.wait_for_selector("h1:text('Глава 1. Опыт и врождённые идеи')")
    page.evaluate("""() => {
        const p = document.querySelector('p.block');
        const range = document.createRange(); range.selectNodeContents(p.firstChild);
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range);
        p.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
    }""")
    page.get_by_role("button", name="Спросить ассистента").click()
    panel = page.get_by_role("complementary", name="Ассистент")
    assert panel.get_by_label("Только выбранный учебник").is_checked()
    panel.get_by_label("Вопрос ассистенту").fill("о чём этот абзац?")
    panel.get_by_role("button", name="Спросить").click()
    searched = wait_logs(
        stack, "assistant", lambda e: e["event"] == "assistant.searched" and e["scope"] == "current"
    )
    assert searched
    # Снятие флажка в ассистенте возвращает «все источники» и графу.
    panel.get_by_label("Только выбранный учебник").uncheck()
    page.goto(f"{stack.url}/graph/{entity_id(stack, 'Кант')}?recipe=genesis")
    page.wait_for_selector("h1:text('Генезис: Кант')")
    assert not page.get_by_label("Только выбранный учебник").is_checked()


@req("knowledge-graph", "Пустой граф")
@req("knowledge-graph", "Без достройки при выключенной генерации")
@req("knowledge-graph", "Запрос графа")
def test_empty_graph_and_unsuitable_recipe(page, stack):
    open_graph(page, stack, "Кант", "answers")
    alert = page.get_by_role("alert")
    assert "не подходит" in alert.inner_text()
    alert.get_by_role("button", name="Генезис").click()
    page.wait_for_selector("h1:text('Генезис: Кант')")

    page.goto(f"{stack.url}/graph/{entity_id(stack, 'Причинность')}?recipe=genesis")
    page.get_by_label("Достраивать моделью").uncheck()
    page.wait_for_selector("text=Связей пока нет.")
    assert "выключена" in page.get_by_role("status").inner_text()
    built = wait_logs(stack, "knowledge", lambda e: e["event"] == "knowledge.graph.built")
    assert built[-1]["extension"] == "disabled" and built[-1]["edges"] == 0
    page.get_by_role("button", name="Включить достройку моделью").wait_for()
    page.get_by_role("button", name="Попробовать: Полемика").click()
    page.wait_for_selector("h1:text('Полемика: Причинность')")


@req("ontology-retrieval", "Сущности вопроса")
@req("ontology-retrieval", "Утверждения в контексте")
def test_assistant_answer_uses_ontology(page, stack):
    open_textbook(page, stack)
    page.get_by_role("button", name="Ассистент").click()
    panel = page.get_by_role("complementary", name="Ассистент")
    panel.get_by_label("Вопрос ассистенту").fill("что Кант взял у Юма?")
    panel.get_by_role("button", name="Спросить").click()
    panel.locator(".fragment").first.wait_for()
    used = wait_logs(stack, "assistant", lambda e: e["event"] == "assistant.ontology.used")
    assert {"Кант", "Юм"} <= set(used[-1]["entities"]) and used[-1]["statements"] >= 1
    request_id = used[-1]["request_id"]
    assert wait_logs(
        stack,
        "knowledge",
        lambda e: e["event"] == "knowledge.assistant.context" and e.get("request_id") == request_id,
    )


@req("abuse-protection", "Защита от автоматических запросов")
def test_direct_paid_call_without_page_rejected(stack):
    response = httpx.post(stack.url + "/api/assistant/v1/ask", json={"question": "что такое опыт?"})
    assert response.status_code == 403 and response.json()["kind"] == "page_token_required"
    assert wait_logs(
        stack,
        "gateway",
        lambda e: e["event"] == "gateway.limit.triggered" and e["kind"] == "page_token",
    )


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
