"""Юнит-тесты сравнения снимков (tests/e2e/visual.py) без браузера: страница подменена."""

from __future__ import annotations

import pytest

from . import visual

req = pytest.mark.req
VD = "visual-design"


class FakePage:
    """Ровно то, что зовёт ``visual.snap``: подготовка страницы и снимок в файл."""

    def __init__(self, color=(10, 20, 30)) -> None:
        self.viewport_size = {"width": 40, "height": 20}
        self.color = color
        self.mouse = self

    def move(self, *_):
        pass

    def wait_for_load_state(self, *_):
        pass

    def evaluate(self, *_):
        return True

    def locator(self, selector):
        return selector

    def screenshot(self, *, path, **_):
        from PIL import Image

        Image.new("RGB", (40, 20), self.color).save(path)


@pytest.fixture
def folders(tmp_path, monkeypatch):
    monkeypatch.setattr(visual, "BASELINES", tmp_path / "baselines" / "linux")
    monkeypatch.setattr(visual, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(visual, "UPDATE", False)
    return tmp_path


@req(VD, "Визуальная проверка", nolog="сравнение снимков: событий журнала нет по природе")
def test_missing_baseline_fails_when_required(folders, monkeypatch):
    monkeypatch.setenv("PHILOGRAPH_REQUIRE_SNAPSHOTS", "1")
    with pytest.raises(visual.SnapshotMissing, match="screen-light-1280: нет эталона"):
        visual.snap(FakePage(), "screen-light-1280")
    assert (folders / "results" / "screen-light-1280.png").exists()

    # Несколько снимков в одном тесте: недостающий эталон — в общем списке падений.
    snaps = visual.Snaps()
    snaps(FakePage(), "screen-dark-1280")
    with pytest.raises(visual.SnapshotMismatch, match="screen-dark-1280: нет эталона"):
        snaps.check()


@req(VD, "Визуальная проверка", nolog="сравнение снимков: событий журнала нет по природе")
def test_missing_baseline_skips_comparison_locally(folders, monkeypatch):
    monkeypatch.delenv("PHILOGRAPH_REQUIRE_SNAPSHOTS", raising=False)
    assert visual.snap(FakePage(), "screen-light-1280") is None
    assert (folders / "results" / "screen-light-1280.png").exists()


@req(VD, "Визуальная проверка", nolog="сравнение снимков: событий журнала нет по природе")
def test_existing_baseline_compared(folders, monkeypatch):
    monkeypatch.setenv("PHILOGRAPH_REQUIRE_SNAPSHOTS", "1")
    monkeypatch.setattr(visual, "UPDATE", True)
    assert visual.snap(FakePage(), "screen") == 0.0
    monkeypatch.setattr(visual, "UPDATE", False)
    assert visual.snap(FakePage(), "screen") == 0.0
    with pytest.raises(visual.SnapshotMismatch, match=r"отличается 100\.00% пикселей"):
        visual.snap(FakePage(color=(250, 250, 250)), "screen")
    assert (folders / "results" / "screen-diff.png").exists()
