"""Диагностика: что видит браузер на главной странице стенда."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from browser_checks import Stand, new_page  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


def main() -> None:
    stand = Stand()
    print("URL:", stand.url)
    events = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context, page = new_page(browser)
        page.on("console", lambda m: events.append(("console", m.type, m.text)))
        page.on("pageerror", lambda e: events.append(("pageerror", str(e))))
        page.on("requestfailed", lambda r: events.append(("requestfailed", r.url, r.failure)))
        page.on("response", lambda r: events.append(("response", r.status, r.url)) if "/api/" in r.url else None)
        page.goto(stand.url + "/")
        page.wait_for_timeout(4000)
        print("URL after:", page.url)
        print("TITLE:", page.title())
        print("BODY TEXT:", page.locator("body").inner_text()[:2000])
        print("HTML len:", len(page.content()))
        print("sources ul:", page.locator("ul.sources").count(), "li:", page.locator("li.source").count())
        print("alerts:", page.locator('[role="alert"]').all_inner_texts())
        print("notices:", page.locator(".pg-notice").all_inner_texts()[:5])
        print("---- events ----")
        for e in events:
            print(e)
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
