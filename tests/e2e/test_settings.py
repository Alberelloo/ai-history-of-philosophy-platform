"""Сквозные сценарии уведомления при первом входе и настроек читателя: всё в браузере."""

from __future__ import annotations

import json

import httpx
import pytest

from ..helpers import topnav
from .conftest import NOTICE_VERSION, reader_context, wait_logs

req = pytest.mark.req
FR = "first-run-notice"
RS = "reader-settings"
pytestmark = pytest.mark.e2e
KEY = "philograph:v2"
NOTICE = "О пометках и обработке вопросов"


def stored(page) -> dict:
    return json.loads(page.evaluate(f"localStorage.getItem('{KEY}')") or "null") or {}


def seed_once(context, script: str) -> None:
    """Данные кладутся до загрузки приложения, но только при первом открытии вкладки."""
    context.add_init_script(
        "if (!sessionStorage.getItem('seeded')) {"
        f" sessionStorage.setItem('seeded', '1'); {script} }}"
    )


def textbook_and_chapter(stack, title: str) -> tuple[str, str]:
    source = httpx.get(stack.url + "/api/v1/current").json()["source_id"]
    toc = httpx.get(f"{stack.url}/api/v1/sources/{source}/toc").json()
    chapter = next(item["chapter_id"] for item in toc if item["title"] == title)
    return source, chapter


def open_assistant(page, stack):
    page.goto(stack.url + "/read")
    page.wait_for_selector("h1:text('Глава 1. Опыт и врождённые идеи')")
    page.get_by_role("button", name="Ассистент", exact=True).click()
    return page.get_by_role("complementary", name="Ассистент")


@req(FR, "Уведомление при первом входе")
@req(FR, "Выбор прямо в уведомлении")
@req(FR, "Показывается один раз")
def test_first_run_notice_choice_and_once(browser, stack):
    context = reader_context(browser, accepted=False)
    page = context.new_page()
    page.goto(stack.url + "/")
    notice = page.get_by_role("region", name=NOTICE)
    notice.wait_for()
    assert "внешний провайдер" in notice.inner_text()
    assert notice.locator(".ungrounded").get_by_role("img", name="Сгенерировано").count() == 1
    generation = notice.get_by_label("Генерация без опоры на источники")
    assert generation.is_checked() and not notice.get_by_label("Только по источникам").is_checked()
    generation.uncheck()
    notice.get_by_role("button", name="Понятно").click()
    assert page.get_by_role("region", name=NOTICE).count() == 0
    topnav(page).get_by_role("link", name="Настройки").click()
    page.wait_for_selector("h1:text('Настройки')")
    assert not page.get_by_label("Генерация без опоры на источники").is_checked()
    # Второй визит — без уведомления; новая версия текста — снова с ним.
    page.goto(stack.url + "/")
    page.wait_for_selector(".source")
    assert page.get_by_role("region", name=NOTICE).count() == 0
    assert stored(page)["notice"] == NOTICE_VERSION
    page.evaluate(
        f"localStorage.setItem('{KEY}', JSON.stringify("
        f"{{...JSON.parse(localStorage.getItem('{KEY}')), notice: '2020-01'}}))"
    )
    page.reload()
    page.get_by_role("region", name=NOTICE).wait_for()
    context.close()


@req(FR, "Доступ к тексту позже")
def test_notice_text_in_settings(page, stack):
    page.goto(stack.url + "/settings")
    page.get_by_text(NOTICE).click()
    assert "внешний провайдер" in page.locator("details").inner_text()


@req(FR, "Ассистент до согласия")
def test_question_waits_for_notice(browser, stack):
    context = reader_context(browser, accepted=False)
    page = context.new_page()
    panel = open_assistant(page, stack)
    panel.get_by_label("Вопрос ассистенту").fill("что такое опыт?")
    before = len(
        wait_logs(stack, "assistant", lambda e: e["event"] == "assistant.question.received", 0)
    )
    panel.get_by_role("button", name="Спросить").click()
    assert "Прочитайте уведомление" in panel.get_by_role("alert").inner_text()
    page.locator(".first-run.attention").wait_for()
    after = len(
        wait_logs(stack, "assistant", lambda e: e["event"] == "assistant.question.received", 1)
    )
    assert after == before  # вопрос провайдеру не ушёл
    page.get_by_role("region", name=NOTICE).get_by_role("button", name="Понятно").click()
    panel.get_by_role("button", name="Спросить").click()
    panel.locator(".fragment").first.wait_for()
    context.close()


@req(RS, "Набор настроек")
@req(RS, "Связь настроек")
@req(RS, "Передача на сервер")
def test_settings_defaults_and_effect(page, stack):
    page.goto(stack.url + "/settings")
    assert page.get_by_label("Генерация без опоры на источники").is_checked()
    assert not page.get_by_label("Только по источникам").is_checked()
    assert page.get_by_label("Все источники").is_checked()
    page.get_by_label("Генерация без опоры на источники").uncheck()
    # Без перезагрузки: переход внутри приложения.
    topnav(page).get_by_role("link", name="Библиотека").click()
    page.locator(".source", has_text="Теория познания").get_by_role("button", name="Читать").click()
    page.wait_for_selector("h1:text('Глава 1. Опыт и врождённые идеи')")
    page.get_by_role("button", name="Ассистент", exact=True).click()
    panel = page.get_by_role("complementary", name="Ассистент")
    panel.get_by_label("Вопрос ассистенту").fill("что такое опыт по Локку?")
    panel.get_by_role("button", name="Спросить").click()
    panel.locator(".fragment").first.wait_for()
    done = wait_logs(stack, "assistant", lambda e: e["event"] == "assistant.answer.completed")
    assert done[-1]["hidden"] >= 1 and done[-1]["ungrounded"] == 0  # как «только по источникам»
    assert panel.locator(".fragment.ungrounded").count() == 0
    # Граф не достраивается, карточка без описания моделью.
    locke = httpx.get(stack.url + "/api/knowledge/v1/entities", params={"name": "Локк"}).json()[0]
    page.goto(f"{stack.url}/graph/{locke['id']}?recipe=polemic")
    page.wait_for_selector("text=Связей пока нет.")
    built = wait_logs(stack, "knowledge", lambda e: e["event"] == "knowledge.graph.built")
    assert built[-1]["extension"] == "disabled"
    page.goto(stack.url + "/read")
    page.locator("p.block", has_text="Локк сравнивал").locator(".mention", has_text="Локк").click()
    page.get_by_role("dialog", name="Карточка").locator("h3:text('Локк')").wait_for()
    assert page.locator(".card-description").count() == 0


@req(RS, "Единое хранилище в браузере")
def test_old_format_migrated(browser, stack):
    source, chapter = textbook_and_chapter(stack, "Глава 3. Ответ Канта")
    context = reader_context(browser, accepted=False)
    seed_once(
        context,
        f"""
        localStorage.setItem('philograph:v1', JSON.stringify({{version: 1,
            currentSource: '{source}', positions: {{'{source}': {{chapterId: '{chapter}'}}}}}}));
        localStorage.setItem('philograph:scope:v1',
            JSON.stringify({{onlyTextbook: false, generation: false}}));
        localStorage.setItem('philograph:dialog:v1', JSON.stringify([
            {{question: 'старый вопрос', fragments: [], status: 'done'}}]));
        """,
    )
    page = context.new_page()
    page.goto(stack.url + "/read")
    page.wait_for_selector("h1:text('Глава 3. Ответ Канта')")  # место чтения перенесено
    data = stored(page)
    assert data["version"] == 2 and data["settings"]["generation"] is False
    assert page.evaluate("localStorage.getItem('philograph:v1')") is None
    page.get_by_role("region", name=NOTICE).get_by_role("button", name="Понятно").click()
    page.get_by_role("button", name="Ассистент", exact=True).click()
    assert "старый вопрос" in page.get_by_role("complementary", name="Ассистент").inner_text()
    context.close()


@req(RS, "Единое хранилище в браузере")
def test_corrupted_storage_resets(browser, stack):
    context = reader_context(browser, accepted=False)
    seed_once(context, f"localStorage.setItem('{KEY}', '{{испорчено');")
    page = context.new_page()
    page.goto(stack.url + "/")
    page.wait_for_selector(".source")
    page.get_by_role("region", name=NOTICE).get_by_role("button", name="Понятно").click()
    page.goto(stack.url + "/settings")
    assert page.get_by_label("Генерация без опоры на источники").is_checked()
    assert stored(page)["version"] == 2
    context.close()


@req(RS, "Недоступное хранилище")
def test_private_mode_without_storage(browser, stack):
    context = reader_context(browser, accepted=False)
    context.add_init_script(
        "Object.defineProperty(window, 'localStorage', "
        "{get() { throw new DOMException('denied', 'SecurityError'); }});"
    )
    page = context.new_page()
    page.goto(stack.url + "/")
    page.wait_for_selector(".source")
    assert "не сохранятся" in page.locator(".storage-warning").inner_text()
    page.get_by_role("region", name=NOTICE).get_by_role("button", name="Понятно").click()
    topnav(page).get_by_role("link", name="Настройки").click()
    page.get_by_label("Только по источникам").check()  # в пределах вкладки работает
    assert page.get_by_label("Только по источникам").is_checked()
    context.close()


@req(RS, "Сброс данных")
def test_reset_all_data(browser, stack):
    context = reader_context(browser, accepted=False)
    page = context.new_page()
    page.goto(stack.url + "/settings")
    page.get_by_role("region", name=NOTICE).get_by_role("button", name="Понятно").click()
    page.get_by_label("Только по источникам").check()
    page.get_by_role("button", name="Сбросить все данные").click()
    page.get_by_role("alertdialog").get_by_role("button", name="Отмена").click()
    assert stored(page)["settings"]["sourcesOnly"] is True  # без подтверждения ничего не удалено
    page.get_by_role("button", name="Сбросить все данные").click()
    page.get_by_role("alertdialog").get_by_role("button", name="Удалить").click()
    page.get_by_role("status").filter(has_text="Данные удалены").wait_for()
    assert page.evaluate(f"localStorage.getItem('{KEY}')") is None
    page.reload()
    page.get_by_role("region", name=NOTICE).wait_for()
    assert not page.get_by_label("Только по источникам").first.is_checked()
    context.close()


@req(RS, "Предел объёма диалогов")
def test_old_dialogs_dropped_over_limit(browser, stack):
    context = reader_context(browser, accepted=False)
    big = json.dumps(
        {
            "version": 2,
            "notice": NOTICE_VERSION,
            "dialogs": [
                [{"question": f"диалог {i} " + "x" * 60_000, "fragments": [], "status": "done"}]
                for i in range(5)
            ],
        },
        ensure_ascii=False,
    )
    seed_once(context, f"localStorage.setItem('{KEY}', {json.dumps(big)});")
    page = context.new_page()
    panel = open_assistant(page, stack)
    panel.get_by_label("Вопрос ассистенту").fill("новый вопрос")
    panel.get_by_role("button", name="Спросить").click()
    panel.locator(".fragment").first.wait_for()
    page.wait_for_function(
        f"JSON.parse(localStorage.getItem('{KEY}')).dialogs.flat()"
        ".some(t => t.question === 'новый вопрос')"
    )
    dialogs = stored(page)["dialogs"]
    assert len(json.dumps(dialogs, ensure_ascii=False)) <= 200_000
    questions = [t["question"][:8] for d in dialogs for t in d]
    assert "диалог 0" not in questions and questions[-1] == "новый во"
    context.close()
