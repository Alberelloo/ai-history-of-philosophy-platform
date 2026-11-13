"""Проверка гипотезы: тест tests/web/test_region_restricted.py читает count() без ожидания.

Повторяем тот же сценарий: goto('/') и сразу count() для li.source--restricted; затем ждём
и снова считаем. Если сразу 0, а после ожидания 1 — это гонка в тесте, а не в продукте.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from browser_checks import Stand, new_page  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


def main() -> None:
    stand = Stand()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for attempt in range(1, 6):
            context, page = new_page(browser)
            page.goto(stand.url + "/")
            immediate = page.locator("li.source--restricted").count()
            page.locator("li.source--restricted").first.wait_for(timeout=10000)
            after = page.locator("li.source--restricted").count()
            print(f"попытка {attempt}: сразу после goto={immediate}, после ожидания={after}")
            context.close()
        browser.close()


if __name__ == "__main__":
    main()
