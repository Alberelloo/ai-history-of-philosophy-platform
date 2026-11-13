"""Доступность и раскладка строки закрытого источника: контраст пометки, прокрутка, размеры."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from browser_checks import Stand, new_page  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

SCRIPT = """
() => {
  const rgb = (value) => {
    const m = value.match(/rgba?\\(([^)]+)\\)/);
    if (!m) return null;
    const parts = m[1].split(/[,/ ]+/).filter(Boolean).map(Number);
    return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
  };
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const contrast = (a, b) => {
    const la = lum(a), lb = lum(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  };
  // Фон бейджа может быть прозрачным: поднимаемся по предкам до непрозрачного.
  const background = (el) => {
    let node = el;
    while (node) {
      const style = getComputedStyle(node);
      const color = rgb(style.backgroundColor);
      if (color && color.a !== 0 && color.a !== undefined) return color;
      node = node.parentElement;
    }
    return { r: 255, g: 255, b: 255, a: 1 };
  };
  const badge = document.querySelector("li.source--restricted .badge");
  const row = document.querySelector("li.source--restricted");
  const openRow = document.querySelector("li.source:not(.source--restricted)");
  if (!badge || !row) return { error: "нет строки закрытого источника" };
  const bs = getComputedStyle(badge);
  const text = rgb(bs.color);
  const bg = background(badge);
  const rowRect = row.getBoundingClientRect();
  const openRect = openRow ? openRow.getBoundingClientRect() : null;
  const buttons = [...row.querySelectorAll("button, a, [tabindex]")].map((el) => el.outerHTML.slice(0, 80));
  return {
    badgeText: badge.textContent.trim(),
    badgeColor: bs.color,
    badgeBackground: bs.backgroundColor,
    contrast: contrast(text, bg),
    fontSize: bs.fontSize,
    fontWeight: bs.fontWeight,
    rowWidth: rowRect.width,
    openRowWidth: openRect ? openRect.width : null,
    sameWidth: openRect ? Math.abs(rowRect.width - openRect.width) < 1 : null,
    focusable: buttons,
    horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  };
}
"""


def main() -> None:
    stand = Stand()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context, page = new_page(browser)
        page.goto(stand.url + "/")
        page.locator("li.source--restricted").wait_for()
        info = page.evaluate(SCRIPT)
        print(json.dumps(info, ensure_ascii=False, indent=1))
        Path(__file__).resolve().parent.joinpath("a11y-report.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
