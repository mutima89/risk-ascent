"""Shared fixtures. Every test gets its own throwaway data folder, so nothing
touches a real installation's saves."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from riskascent.core.content import load_content  # noqa: E402
from riskascent.game import Game  # noqa: E402
from riskascent.paths import content_dir  # noqa: E402
from riskascent.persistence.saves import SaveManager  # noqa: E402


@pytest.fixture(scope="session")
def content():
    return load_content(content_dir())


@pytest.fixture(autouse=True)
def data_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("RISKASCENT_HOME", str(home))
    return home


@pytest.fixture
def saves(tmp_path):
    return SaveManager(tmp_path / "saves", tmp_path / "backups")


@pytest.fixture
def game(content, saves):
    g = Game.new_career(content, saves, 1, "Tester", "meridian", "erm", "standard", seed=1234)
    yield g
    try:
        g.close()
    except Exception:
        pass


def play_mission(g: Game, mid: str, confidence: float | None = 0.7) -> dict:
    from riskascent.autoplay import play
    rid, run = g.start_or_resume(mid)
    play(run, confidence)
    return g.complete_mission(rid, run)
