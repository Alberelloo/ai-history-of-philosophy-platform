"""Юнит-тесты модулей глобуса клиента (`web/unit/**/*.test.ts`), разработчик.

Файл теста собирается esbuild из `web/node_modules` и выполняется в node. Это тесты
модулей разработчика, а не сценарные и нормативные тесты спецификации: маркеров ``req`` нет.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / "web"
ESBUILD = WEB / "node_modules" / ".bin" / "esbuild"
FILES = sorted((WEB / "unit").rglob("*.test.ts"))


@pytest.mark.parametrize("path", FILES, ids=[p.stem for p in FILES])
def test_unit(path: Path, tmp_path: Path) -> None:
    assert ESBUILD.exists(), "нужен web/node_modules: cd web && npm ci"
    out = tmp_path / "bundle.mjs"
    subprocess.run(
        [
            str(ESBUILD),
            str(path),
            "--bundle",
            "--platform=node",
            "--format=esm",
            f"--outfile={out}",
            "--log-level=error",
        ],
        cwd=WEB,
        check=True,
    )
    run = subprocess.run(["node", str(out)], cwd=WEB, capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "failed 0" in run.stdout, run.stdout
