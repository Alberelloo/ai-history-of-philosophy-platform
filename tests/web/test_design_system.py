"""Требования visual-design, которые проверяются без браузера: токены, стили, каталог строк,
сравнение снимков."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

req = pytest.mark.req
VD = "visual-design"
ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
sys.path.insert(0, str(ROOT / "scripts"))

import design_tokens  # noqa: E402

LITERAL_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(")


def _node() -> str | None:
    found = shutil.which("node")
    if found:
        return found
    # Windows без node в PATH: установка WinGet.
    packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    candidates = (
        sorted(packages.glob("OpenJS.NodeJS*/node-*/node.exe")) if packages.exists() else []
    )
    return str(candidates[-1]) if candidates else None


@req(VD, "Токены оформления")
def test_tokens_css_matches_tokens_json():
    expected = design_tokens.generate(design_tokens.load())
    current = design_tokens.TARGET.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert current == expected, "tokens.css устарел: python scripts/design_tokens.py"


@req(VD, "Токены оформления")
def test_changed_tokens_are_detected(tmp_path, monkeypatch):
    """Изменили tokens.json и не перегенерировали — проверка падает."""
    tokens = design_tokens.load()
    tokens["color"]["tokens"][0]["value"]["light"] = "#ffffff"
    changed = design_tokens.generate(tokens)
    target = tmp_path / "tokens.css"
    target.write_text(design_tokens.generate(design_tokens.load()), encoding="utf-8")
    assert target.read_text(encoding="utf-8") != changed
    monkeypatch.setattr(design_tokens, "TARGET", target)
    monkeypatch.setattr(design_tokens, "load", lambda: tokens)
    monkeypatch.setattr(sys, "argv", ["design_tokens.py", "--check"])
    assert design_tokens.main() == 1


@req(VD, "Токены оформления")
def test_tokens_layout_by_theme():
    css = design_tokens.TARGET.read_text(encoding="utf-8")
    light = css.split('[data-theme="dark"]')[0]
    assert ':root,\n[data-theme="light"]' in css and "--paper: #eff1ec;" in light
    assert "@media (prefers-color-scheme: dark)" in css
    assert ':root:not([data-theme="light"])' in css and "--paper: #13171e;" in css
    assert '--font-read: "Literata Variable", Literata' in css
    for name in ("--space-4: 16px;", "--radius-sm: 8px;", "--dur-quick: 120ms;", "--topbar: 56px;"):
        assert name in css


@req(VD, "Токены оформления")
def test_client_styles_use_only_tokens():
    """Цвета в стилях клиента — только через var(--…), без литералов вроде #fff."""
    for path in (WEB / "src" / "styles.css", WEB / "src" / "styles" / "components.css"):
        lines = [
            f"{path.name}:{n}: {line.strip()}"
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if LITERAL_COLOR.search(line)
        ]
        assert not lines, lines
    # В разметке компонентов тоже нет литеральных цветов (кроме currentColor в значках).
    for path in (WEB / "src").glob("*.tsx"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"[\"']#[0-9a-fA-F]{3,8}[\"']", text), path.name


@req(VD, "Шрифты")
def test_fonts_bundled_without_external_services():
    main = (WEB / "src" / "main.tsx").read_text(encoding="utf-8")
    assert "@fontsource/onest" in main and "@fontsource-variable/literata" in main
    design_css = (ROOT / "docs" / "design" / "system").glob("*.css")
    for path in [*(WEB / "src").rglob("*.*"), WEB / "index.html", *design_css]:
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "fonts.googleapis.com" not in text and "fonts.gstatic.com" not in text, path


@req(VD, "Язык интерфейса")
def test_catalog_keys_checked_by_typescript(tmp_path):
    """Ключ, которого нет в английском каталоге, ломает проверку типов клиента."""
    node = _node()
    tsc = WEB / "node_modules" / "typescript" / "bin" / "tsc"
    if not node or not tsc.exists():
        pytest.skip("нет node или зависимостей клиента (npm ci в web/)")
    src = tmp_path / "i18n"
    shutil.copytree(WEB / "src" / "i18n", src, ignore=shutil.ignore_patterns("index.ts"))
    config = tmp_path / "tsconfig.json"
    config.write_text(
        '{"compilerOptions": {"strict": true, "noEmit": true, "target": "ES2022",'
        ' "module": "ESNext", "moduleResolution": "Bundler", "skipLibCheck": true,'
        ' "resolveJsonModule": true,'
        ' "types": []}, "include": ["i18n"]}',
        encoding="utf-8",
    )

    def check() -> subprocess.CompletedProcess:
        return subprocess.run(
            [node, str(tsc), "-p", str(config)], capture_output=True, text=True, check=False
        )

    assert check().returncode == 0, check().stdout
    en = src / "en.ts"
    text = en.read_text(encoding="utf-8")
    assert '    library: "Library",\n' in text
    en.write_text(text.replace('    library: "Library",\n', "", 1), encoding="utf-8")
    broken = check()
    assert broken.returncode != 0 and "library" in broken.stdout, broken.stdout


@req(VD, "Язык интерфейса")
def test_ontology_names_in_both_catalogs():
    """Названия разделов карточки, связей и рецептов есть на обоих языках и совпадают с реестром."""
    import json

    from philograph.knowledge import registry_data
    from philograph.knowledge.cards import MISCONCEPTIONS_TITLE, SECTIONS

    ru = json.loads((WEB / "src" / "i18n" / "ontology.ru.json").read_text(encoding="utf-8"))
    en = json.loads((WEB / "src" / "i18n" / "ontology.en.json").read_text(encoding="utf-8"))
    sections = {code: title for items in SECTIONS.values() for code, title, *_ in items}
    sections["misconceptions"] = MISCONCEPTIONS_TITLE
    relations = {r["code"]: r for r in registry_data.RELATIONS}
    recipes = {r[0]: r[1] for r in registry_data.RECIPES}

    assert ru["sections"] == sections
    assert ru["recipes"] == recipes
    assert set(ru["relations"]) == set(relations)
    for code, spec in relations.items():
        expected = {"title": spec["title"]}
        if spec["inverse_title"]:
            expected["inverse"] = spec["inverse_title"]
        assert ru["relations"][code] == expected, code

    cyrillic = re.compile("[а-яё]", re.IGNORECASE)
    for group in ("sections", "recipes", "relations"):
        assert set(en[group]) == set(ru[group]), group
    texts = [*en["sections"].values(), *en["recipes"].values()]
    for code, names in en["relations"].items():
        assert set(names) == set(ru["relations"][code]), code  # inverse там же, где в реестре
        texts += names.values()
    assert all(text.strip() and not cyrillic.search(text) for text in texts), texts


@req(VD, "Визуальная проверка")
def test_snapshot_mismatch_keeps_files(tmp_path, monkeypatch):
    """Сдвиг сильнее порога проваливает сравнение и оставляет снимок, эталон и разницу."""
    from PIL import Image, ImageDraw

    from ..e2e import visual

    monkeypatch.setattr(visual, "RESULTS", tmp_path / "results")
    expected = tmp_path / "expected.png"
    actual = tmp_path / "actual.png"
    base = Image.new("RGB", (200, 100), (239, 241, 236))
    ImageDraw.Draw(base).rectangle((20, 20, 80, 60), fill=(56, 91, 143))
    base.save(expected)
    shifted = Image.new("RGB", (200, 100), (239, 241, 236))
    ImageDraw.Draw(shifted).rectangle((40, 20, 100, 60), fill=(56, 91, 143))
    shifted.save(actual)

    assert visual.compare(expected, expected, "same") == 0
    with pytest.raises(visual.SnapshotMismatch):
        visual.compare(actual, expected, "shifted")
    kept = sorted(p.name for p in (tmp_path / "results").iterdir())
    assert kept == ["shifted-actual.png", "shifted-diff.png", "shifted-expected.png"]

    # Сглаживание (небольшая разница каналов) порог не превышает.
    soft = Image.open(expected).point(lambda v: min(255, v + 10))
    soft.save(actual)
    assert visual.compare(actual, expected, "soft") == 0
