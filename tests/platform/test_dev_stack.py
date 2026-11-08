"""Стенд разработки: демо-источники не попадают в обычный запуск."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import dev_stack  # noqa: E402


def test_demo_sources_off_by_default():
    args = dev_stack.build_parser().parse_args([])
    assert args.demo is False


def test_demo_sources_flag():
    args = dev_stack.build_parser().parse_args(["--demo"])
    assert args.demo is True


def test_tests_keep_demo_sources():
    # Сквозные тесты зовут start(tmp_path) без ключей и рассчитывают на демо-источники.
    import inspect

    assert inspect.signature(dev_stack.start).parameters["demo"].default is True
