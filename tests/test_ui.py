"""User-interface smoke tests (pytest-qt, offscreen)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import SIGNAL
from PySide6.QtWidgets import QPushButton

from riskascent.game import Game
from riskascent.paths import backups_dir, saves_dir, settings_file, user_data_dir
from riskascent.persistence.saves import SaveManager
from riskascent.settings import load_settings
from riskascent.ui import widgets


@pytest.fixture
def win(qtbot, content, data_home, monkeypatch):
    from riskascent.selftest import _Recorder
    from riskascent.ui.main_window import MainWindow
    rec = _Recorder()
    for name in ("info", "error", "confirm", "typed_confirm", "save_file", "open_file", "text"):
        monkeypatch.setattr(widgets.DIALOGS, name, getattr(rec, name))
    saves = SaveManager(saves_dir(), backups_dir())
    w = MainWindow(content, saves, load_settings(settings_file()), user_data_dir(), settings_file())
    w.settings.reduced_motion = True
    w.recorder = rec
    qtbot.addWidget(w)
    w.resize(1280, 800)
    w.show()
    yield w
    if w.game:
        w.close_game()


def _connected(b: QPushButton) -> int:
    return sum(b.receivers(SIGNAL(s)) for s in ("clicked()", "clicked(bool)", "toggled(bool)", "pressed()"))


def test_built_in_self_test_passes(qtbot, content, data_home, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from riskascent.selftest import run_self_test
    from riskascent.ui.main_window import MainWindow
    saves = SaveManager(saves_dir(), backups_dir())
    w = MainWindow(content, saves, load_settings(settings_file()), user_data_dir(), settings_file())
    qtbot.addWidget(w)
    code = run_self_test(QApplication.instance(), w, str(data_home / "report.txt"))
    assert code == 0, (data_home / "report.txt").read_text(encoding="utf-8")


def test_no_dead_buttons_on_any_screen(win, qtbot, content):
    g = Game.new_career(content, win.saves, 1, "Buttons", "meridian", "erm", seed=11)
    win.start_game(g, first=True)
    dead = []
    for key, screen in win.screens.items():
        if key == "startup":
            continue
        kw = {"mission_id": "M01"} if key == "mission" else {}
        win.go(key, **kw)
        qtbot.wait(10)
        for b in screen.findChildren(QPushButton):
            if b.isVisibleTo(screen) and b.isEnabled() and not _connected(b):
                dead.append(f"{key}: '{b.text()}'")
    for b in win.findChildren(QPushButton):
        if b.isVisible() and b.isEnabled() and not _connected(b):
            dead.append(f"chrome: '{b.text()}'")
    assert dead == []


def test_title_screen_buttons_work(win, qtbot):
    win.show_startup()
    qtbot.wait(10)
    s = win.screens["startup"]
    dead = [b.text() for b in s.findChildren(QPushButton) if b.isVisibleTo(s) and b.isEnabled() and not _connected(b)]
    assert dead == []


def test_reset_needs_typed_confirmation(win, content, monkeypatch):
    g = Game.new_career(content, win.saves, 1, "Keep", "meridian", "erm", seed=1)
    win.start_game(g, first=True)
    monkeypatch.setattr(widgets.DIALOGS, "typed_confirm", lambda *a, **k: False)
    win.go("settings")
    win.screens["settings"].reset()
    assert win.saves.slot_path(1).exists() and win.game is not None


def test_keyboard_navigation(win, qtbot, content):
    from PySide6.QtCore import Qt
    g = Game.new_career(content, win.saves, 1, "Keys", "meridian", "erm", seed=1)
    win.start_game(g, first=True)
    win.go("register")
    qtbot.keyClick(win, Qt.Key_1, Qt.ControlModifier)
    assert win.stack.currentWidget() is win.screens["dashboard"]
    qtbot.keyClick(win, Qt.Key_F6)
    assert win.settings.focus_mode
    qtbot.keyClick(win, Qt.Key_Escape)
    assert not win.settings.focus_mode
