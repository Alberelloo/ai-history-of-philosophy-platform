"""Визуальная проверка клиента одной командой: сборка и сквозные тесты оформления.

    python scripts/visual_check.py            # собрать клиент, проверить по DOM и сравнить снимки
    python scripts/visual_check.py --update   # то же, но переписать эталоны снимков
    python scripts/visual_check.py --no-build # без пересборки web/dist

Тесты сами поднимают стенд (``scripts/dev_stack.py``) во временном каталоге. Эталоны —
``tests/e2e/visual/baselines/<платформа>/``, расхождения — ``tests/e2e/visual/results/``
(фактический снимок, эталон, карта различий). Эталоны обновляйте, только посмотрев снимки.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = [
    "tests/e2e/test_visual_design.py",
    "tests/e2e/test_reader_snapshots.py",
    "tests/web/test_design_system.py",
]


def npm() -> list[str]:
    found = shutil.which("npm") or shutil.which("npm.cmd")
    if not found:
        packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        found_paths = (
            sorted(packages.glob("OpenJS.NodeJS*/node-*/npm.cmd")) if packages.exists() else []
        )
        if not found_paths:
            sys.exit("npm не найден: установите Node.js или соберите клиент сами (--no-build)")
        found = str(found_paths[-1])
    return [found]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--update", action="store_true", help="переписать эталоны снимков")
    parser.add_argument("--no-build", action="store_true", help="не пересобирать клиент")
    parser.add_argument("pytest_args", nargs="*", help="дополнительные аргументы pytest")
    args = parser.parse_args()
    env = {**os.environ, "PYTHONUTF8": "1"}
    if not args.no_build:
        command = npm()
        node_dir = str(Path(command[0]).parent)
        env["PATH"] = node_dir + os.pathsep + env.get("PATH", "")
        subprocess.run([*command, "run", "build"], cwd=ROOT / "web", env=env, check=True)
    if args.update:
        env["PHILOGRAPH_UPDATE_SNAPSHOTS"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS, *args.pytest_args], cwd=ROOT, env=env
    )
    print(f"Снимки при расхождении: {ROOT / 'tests' / 'e2e' / 'visual' / 'results'}")
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
