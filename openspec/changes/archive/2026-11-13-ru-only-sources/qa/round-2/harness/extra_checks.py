"""Раунд 2: регрессии после фиксов F-1/F-3 — список, фильтры, ссылка на абзац, EC-4 в браузере.

Стенд — из browser_checks.py (шлюз + собранный клиент + SQLite), скриншоты — round-2.
Код проекта и тесты не меняются: только наблюдение через браузер и HTTP.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import browser_checks as bc  # noqa: E402
from browser_checks import Stand, new_page, report, shot  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from philograph.library.reading import Internal  # noqa: E402
from philograph.library.registry import License  # noqa: E402


def open_paragraph(stand: Stand) -> str:
    version = stand.registry.get(stand.ids["primary"]).published_version or ""
    payload = Internal(stand.registry, stand.reading).version_paragraphs(version)
    return payload["paragraphs"][0]["id"]


def main() -> None:
    stand = Stand()
    print("URL:", stand.url)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        # --- UC-2 (регрессия): ссылка на абзац открытого источника работает ---
        context, page = new_page(browser)
        paragraph = open_paragraph(stand)
        page.goto(f"{stand.url}/p/{paragraph}")
        # Найденный абзац переносится на главу с якорем #p-<id>.
        page.wait_for_url("**/read/**", timeout=15000)
        page.locator(".chapter").wait_for()
        page.locator(f"#p-{paragraph}").wait_for()
        body = page.locator("#content").inner_text()
        report(
            "UC-2",
            "ссылка на абзац открытого источника открывается",
            "All our knowledge begins with experience" in body
            and f"#p-{paragraph}" in page.url,
            "переход на главу с якорем #p-<id> и текстом абзаца",
            f"адрес: {page.url}; текст: {body[:120]!r}",
            [shot(page, "UC-2-1-open-paragraph")],
        )
        context.close()

        # --- TC-8 (регрессия): фильтр вида в интерфейсе действует на закрытую строку ---
        context, page = new_page(browser)
        page.goto(stand.url + "/")
        page.locator("li.source--restricted").wait_for()
        total_before = page.locator(".sources .source").count()
        page.locator(".pg-filter__button", has_text="Вид").click()
        page.locator(".pg-filter-menu__option", has_text="Учебник").click()
        page.wait_for_timeout(700)
        restricted_kind = page.locator("li.source--restricted").count()
        titles_kind = page.locator(".sources .source h2").all_inner_texts()
        report(
            "TC-8",
            "фильтр вида оставляет закрытую строку и убирает чужие виды",
            restricted_kind == 1
            and any("Русский учебник" in t for t in titles_kind)
            and not any("Critique of Pure Reason" in t for t in titles_kind),
            "при фильтре «Учебник» остаётся закрытая строка, первоисточник скрыт",
            f"всего строк было {total_before}, стало {len(titles_kind)}: {titles_kind}",
            [shot(page, "TC-8-1-kind-filter-restricted")],
        )
        # сброс фильтра
        page.locator(".filters__reset").click()
        page.wait_for_timeout(600)
        report(
            "TC-8",
            "сброс фильтра возвращает полный список с закрытой строкой",
            page.locator(".sources .source").count() == total_before
            and page.locator("li.source--restricted").count() == 1,
            f"снова {total_before} строк, из них одна закрытая",
            f"строк: {page.locator('.sources .source').count()}; закрытых: "
            f"{page.locator('li.source--restricted').count()}",
            [shot(page, "TC-8-2-filter-reset-full-list")],
        )
        # поиск по автору: только закрытая строка
        page.locator('input[type="search"]').fill("Юркевич")
        page.wait_for_timeout(700)
        report(
            "TC-8",
            "поиск по автору находит закрытую строку",
            page.locator(".sources .source").count() == 1
            and page.locator("li.source--restricted").count() == 1,
            "по «Юркевич» — одна строка, и она закрытая",
            f"строк: {page.locator('.sources .source').count()}",
            [shot(page, "TC-8-3-search-author-restricted")],
        )
        context.close()

        # --- EC-4 / F-3: пустое пересечение регионов — источника нет нигде ---
        stand.registry.add_license_kind(
            "kind-narrow",
            "RU и BY, затем только RU",
            None,
            {"display": True, "external_processing": True, "quoting": True},
            regions=["RU", "BY"],
        )
        narrow_id = stand.registry.register(
            "operator",
            title="Источник только для BY",
            authors=["Тестовый автор BY"],
            year=2015,
            language="ru",
            kind="textbook",
            license=License(
                "kind-narrow", "public_domain", author_death_years=[1900], regions=["BY"]
            ),
            scope="public",
            files=[{"name": "nb", "path": "reference.txt"}],
        )
        version = stand.pipeline.start("operator", narrow_id)
        stand.registry.publish("operator", version)
        before_narrow = stand.registry.regions(narrow_id)
        stand.registry.add_license_kind(
            "kind-narrow",
            "RU и BY, затем только RU",
            None,
            {"display": True, "external_processing": True, "quoting": True},
            regions=["RU"],
        )
        after_narrow = stand.registry.regions(narrow_id)
        permissions = stand.registry.permissions(narrow_id)

        context, page = new_page(browser)
        page.goto(stand.url + "/")
        page.locator(".sources .source").first.wait_for()
        page.wait_for_timeout(500)
        titles = page.locator(".sources .source h2").all_inner_texts()
        report(
            "EC-4",
            "после сужения вида до [RU] источник [BY] не показывается в списке",
            before_narrow == frozenset({"BY"})
            and after_narrow == frozenset()
            and permissions.get("display") is False
            and not any("только для BY" in t for t in titles),
            "regions до сужения {BY}, после — пусто, display=false, строки в списке нет",
            f"до: {sorted(before_narrow or [])}; после: {sorted(after_narrow or [])}; "
            f"display={permissions.get('display')}; заголовки списка: {titles}",
            [shot(page, "EC-4-1-empty-intersection-hidden")],
        )
        context.close()

        # --- EC-4: тот же источник с регионом RU тоже не виден ---
        stand_two = None
        del stand_two
        context, page = new_page(browser)
        seen_ru: dict = {}

        def grab(resp):
            if "/api/v1/sources" in resp.url:
                try:
                    seen_ru.update(resp.json())
                except Exception:  # noqa: BLE001
                    pass

        page.on("response", grab)
        page.goto(stand.url + "/")
        page.locator(".sources .source").first.wait_for()
        page.wait_for_timeout(400)
        ids_visible = {s.get("id") for s in seen_ru.get("sources", [])}
        report(
            "EC-4",
            "источник с пустым пересечением отсутствует и в ответе API",
            narrow_id not in ids_visible,
            "идентификатора источника нет среди sources",
            f"видимых источников: {len(ids_visible)}; есть ли закрытый-пустой: "
            f"{narrow_id in ids_visible}",
            [shot(page, "EC-4-2-empty-intersection-api")],
        )
        context.close()

        browser.close()

    failed = [c for c in bc.CHECKS if not c["ok"]]
    out = Path(__file__).resolve().parent / "extra-report.json"
    out.write_text(
        json.dumps(
            {"url": stand.url, "checks": bc.CHECKS, "failed": failed, "console": bc.CONSOLE},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print("\nИтог: проверок", len(bc.CHECKS), ", провалено", len(failed))
    for item in failed:
        print("FAILED:", item["case"], item["step"], "|", item["actual"][:400])
    for item in bc.CONSOLE[:15]:
        print("  console:", item["type"], item["text"][:220])


if __name__ == "__main__":
    main()
