"""Генерация CSS-переменных клиента из токенов дизайн-системы.

Источник — ``docs/design/tokens.json``, результат — ``web/src/styles/tokens.css``. Файл
результата коммитится; тест сверяет его с генератором, чтобы токены и клиент не разошлись.

Раскладка:

- цвета и тени, у которых значения по темам: светлые — в ``:root, [data-theme="light"]``,
  тёмные — в ``[data-theme="dark"]`` и в ``@media (prefers-color-scheme: dark)`` для режима
  «как в системе» (атрибута нет);
- прочие семейства (отступы, радиусы, размеры, ширины, длительности, кривые, слои) —
  ``--<имя>`` в ``:root``;
- семейства шрифтов — ``--font-ui`` и ``--font-read``, стили текста — ``--type-<имя>``
  (сокращённая запись ``font``) и ``--type-<имя>-tracking`` (межбуквенный интервал).

Шрифты подключаются из пакетов @fontsource; у вариативных пакетов своё имя семейства
(«Literata Variable»), оно ставится в стек перед именем из токенов.

Запуск: ``python scripts/design_tokens.py`` (пишет файл) или ``--check`` (сверяет).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "design" / "tokens.json"
TARGET = ROOT / "web" / "src" / "styles" / "tokens.css"

# Имя семейства в токенах → имя семейства, под которым его объявляет пакет @fontsource.
PACKAGE_FAMILIES = {"Literata": "Literata Variable"}
# Семейства с простыми значениями: попадают в :root как есть.
PLAIN = ("spacing", "radius", "size", "breakpoint", "duration", "easing", "layer")


def _family_stack(stack: str) -> str:
    names = [name.strip() for name in stack.split(",")]
    result: list[str] = []
    for name in names:
        package = PACKAGE_FAMILIES.get(name.strip('"'))
        if package:
            result.append(f'"{package}"')
        result.append(name)
    return ", ".join(result)


def _font(style: dict, family: str) -> str:
    italic = "italic " if style.get("fontStyle") == "italic" else ""
    return (
        f"{italic}{style['fontWeight']} {style['fontSize']}/{style['lineHeight']} "
        f"var(--font-{family})"
    )


def _block(selector: str, lines: list[str], indent: str = "") -> list[str]:
    return [f"{indent}{selector} {{", *(f"{indent}  {line}" for line in lines), f"{indent}}}"]


def generate(tokens: dict) -> str:
    themed: dict[str, list[str]] = {"light": [], "dark": []}
    for group in (tokens["color"]["tokens"], tokens["shadow"]["tokens"]):
        for token in group:
            for theme in themed:
                themed[theme].append(f"--{token['name']}: {token['value'][theme]};")
    themed["light"].append("color-scheme: light;")
    themed["dark"].append("color-scheme: dark;")

    plain: list[str] = []
    families = tokens["type"]["families"]
    for name in ("ui", "read"):
        plain.append(f"--font-{name}: {_family_stack(families[name])};")
    for group in tokens["type"]["groups"]:
        for style in group["styles"]:
            plain.append(f"--type-{style['name']}: {_font(style, group['family'])};")
            plain.append(
                f"--type-{style['name']}-tracking: {style.get('letterSpacing', 'normal')};"
            )
    for family in PLAIN:
        for token in tokens[family]["tokens"]:
            plain.append(f"--{token['name']}: {token['value']};")

    out = [
        "/* Сгенерировано scripts/design_tokens.py из docs/design/tokens.json. Не править руками:",
        "   поменяйте tokens.json и запустите python scripts/design_tokens.py. */",
        "",
        *_block(':root,\n[data-theme="light"]', themed["light"]),
        "",
        *_block('[data-theme="dark"]', themed["dark"]),
        "",
        "/* Режим «как в системе»: атрибута data-theme нет, тема берётся из системы. */",
        "@media (prefers-color-scheme: dark) {",
        *_block(':root:not([data-theme="light"])', themed["dark"], indent="  "),
        "}",
        "",
        *_block(":root", plain),
        "",
    ]
    return "\n".join(out)


def load() -> dict:
    return json.loads(SOURCE.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="только сверить файл")
    args = parser.parse_args()
    expected = generate(load())
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current.replace("\r\n", "\n") != expected:
            print(f"{TARGET.relative_to(ROOT)} устарел: python scripts/design_tokens.py")
            return 1
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(expected, encoding="utf-8", newline="\n")
    print(f"записан {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
