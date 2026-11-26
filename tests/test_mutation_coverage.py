"""У каждого требования изменения с отмеченным пунктом мутационной проверки есть мутация.

Пункт отмечен строкой ``- [x] … mutation_check.py --change <изменение>`` в ``tasks.md``
неархивного изменения (design.md improve-extraction-naming, «Дамп, мутации, наблюдаемость»).
Пока пункт не отмечен, проверки нет; отметка без записей в ``mutations.yaml`` роняет CI.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MARK = re.compile(r"^\s*- \[x\].*mutation_check\.py --change ([\w-]+)", re.MULTILINE)


def checked_changes() -> list[str]:
    found = []
    for tasks in sorted((ROOT / "openspec" / "changes").glob("*/tasks.md")):
        if "archive" in tasks.parts:
            continue
        for change in MARK.findall(tasks.read_text(encoding="utf-8")):
            if change == tasks.parent.name:
                found.append(change)
    return found


@pytest.mark.parametrize("change", checked_changes() or [None])
def test_every_requirement_has_mutation(change):
    if change is None:
        return  # ни одно изменение ещё не отметило мутационную проверку
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "mutation_check.py"), "--coverage", change],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
