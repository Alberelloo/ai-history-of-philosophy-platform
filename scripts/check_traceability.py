"""Проверка прослеживаемости: у каждого требования реализованных возможностей есть тест.

Требования берутся из спецификаций OpenSpec (заголовки ``### Requirement:``) для
возможностей, перечисленных в ``openspec/traceability.yaml``. Тесты связываются с
требованием маркером ``@pytest.mark.req("<возможность>", "<требование>")``. Скрипт падает,
если требование без теста или маркер ссылается на несуществующее требование.

Запуск: ``python scripts/check_traceability.py``.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REQ_RE = re.compile(r"^### Requirement:\s*(.+?)\s*$", re.MULTILINE)


def spec_requirements(capability: str) -> dict[str, list[str]]:
    """Требования возможности по всем местам, где она описана: основная спецификация и изменения."""
    found: dict[str, list[str]] = {}
    candidates = [
        ROOT / "openspec" / "specs" / capability / "spec.md",
        *ROOT.glob(f"openspec/changes/*/specs/{capability}/spec.md"),
    ]
    for path in candidates:
        if path.exists() and "archive" not in path.parts:
            for name in REQ_RE.findall(path.read_text(encoding="utf-8")):
                found.setdefault(name, []).append(str(path.relative_to(ROOT)))
    return found


def test_markers() -> dict[tuple[str, str], list[str]]:
    markers: dict[tuple[str, str], list[str]] = {}
    for path in (ROOT / "tests").rglob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                continue
            for deco in node.decorator_list:
                # ``@pytest.mark.req(...)`` или сокращение ``req = pytest.mark.req``.
                func = deco.func if isinstance(deco, ast.Call) else None
                is_req = (isinstance(func, ast.Attribute) and func.attr == "req") or (
                    isinstance(func, ast.Name) and func.id == "req"
                )
                if (
                    is_req
                    and isinstance(deco, ast.Call)
                    and len(deco.args) == 2
                    and all(isinstance(a, ast.Constant) for a in deco.args)
                ):
                    key = (deco.args[0].value, deco.args[1].value)
                    markers.setdefault(key, []).append(f"{path.relative_to(ROOT)}::{node.name}")
    return markers


def main() -> int:
    config = yaml.safe_load((ROOT / "openspec" / "traceability.yaml").read_text(encoding="utf-8"))
    enforced: list[str] = config.get("enforce", [])
    markers = test_markers()
    problems: list[str] = []
    total = covered = 0
    for capability in enforced:
        requirements = spec_requirements(capability)
        if not requirements:
            problems.append(f"{capability}: спецификация не найдена")
        for name in requirements:
            total += 1
            if (capability, name) in markers:
                covered += 1
            else:
                problems.append(f"{capability}: нет теста для «{name}»")
    for (capability, name), where in markers.items():
        if capability in enforced and name not in spec_requirements(capability):
            problems.append(
                f"{capability}: маркер на несуществующее требование «{name}» ({', '.join(where)})"
            )
    print(f"Требований с тестами: {covered} из {total}")
    for problem in problems:
        print(f"  ✗ {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
