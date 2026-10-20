"""Main window: sidebar navigation, top bar, screen stack and app-wide services
(theme, focus mode, session timer, text-to-speech, keyboard shortcuts)."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QAction, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from ..core.content import Content
from ..game import Game
from ..paths import settings_file
from ..persistence.saves import SaveManager
from ..settings import Settings, save_settings
from . import theme
from .widgets import DIALOGS, button, lbl

NAV = [
    ("Career", [("dashboard", "Dashboard", "Ctrl+1"), ("missions", "Missions", "Ctrl+2"),
                ("career", "Career map", ""), ("profile", "Profile", ""), ("skills", "Skill tree", ""),
                ("review", "Performance review", ""), ("portfolio", "Achievements & portfolio", "")]),
    ("Workspace", [("register", "Risk register", "Ctrl+3"), ("workbench", "Assessment workbench", "Ctrl+4"),
                   ("assurance", "Controls & resilience", ""), ("finance", "Financial lab", "Ctrl+5"),
                   ("kri", "KRI monitor", "Ctrl+6"), ("crisis", "Crisis command", ""),
                   ("stakeholders", "Stakeholders", "Ctrl+7"), ("budget", "Budget & investments", ""),
                   ("reports", "Executive reports", "Ctrl+8")]),
    ("Organisation", [("org", "Organisation overview", "")]),
    ("Learning", [("training", "Training centre", "Ctrl+9")]),
    ("System", [("final", "CRO assessment", ""), ("settings", "Settings & accessibility", "Ctrl+,"),
                ("saves", "Saves & recovery", "")]),
]


class MainWindow(QMainWindow):
    def __init__(self, content: Content, saves: SaveManager, settings: Settings, data_dir: Path,
                 settings_path: Path | None = None):
        super().__init__()
        self.content = content
        self.saves = saves
        self.settings = settings
        self.settings_path = settings_path or settings_file()
        self.data_dir = data_dir
        self.game: Game | None = None
        self.recovered_from: str | None = None
        self.session_start = time.monotonic()
        self.break_shown = False
        self.tts = None
        self.handoff: dict = {}
        self._anim = None
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1360, 860)
        self.setMinimumSize(1000, 680)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # Sidebar
        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(238)
        sv = QVBoxLayout(self.sidebar)
        sv.setContentsMargins(10, 16, 10, 12)
        sv.setSpacing(6)
        brand = lbl("RISK ASCENT", "Brand", wrap=False)
        brand.setContentsMargins(10, 0, 0, 0)
        sub = lbl("Junior Analyst to Chief Risk Officer", "BrandSub")
        sub.setContentsMargins(10, 0, 0, 8)
        sv.addWidget(brand)
        sv.addWidget(sub)
        self.player_label = lbl("", "Small")
        self.player_label.setContentsMargins(10, 0, 0, 6)
        sv.addWidget(self.player_label)
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setAccessibleName("Main navigation")
        self.nav_items: dict[str, QListWidgetItem] = {}
        self.mission_item = QListWidgetItem("▶  Current mission")
        self.mission_item.setData(Qt.UserRole, "mission")
        self.nav.addItem(self.mission_item)
        self.mission_item.setHidden(True)
        for group, items in NAV:
            head = QListWidgetItem(group.upper())
            head.setFlags(Qt.NoItemFlags)
            self.nav.addItem(head)
            for key, label, sc in items:
                it = QListWidgetItem(label)
                it.setData(Qt.UserRole, key)
                if sc:
                    it.setToolTip(f"{label} ({sc})")
                self.nav.addItem(it)
                self.nav_items[key] = it
        self.nav.currentItemChanged.connect(self._nav_changed)
        sv.addWidget(self.nav, 1)
        self.save_state = lbl("All progress saved locally", "Small")
        self.save_state.setContentsMargins(10, 0, 0, 0)
        sv.addWidget(self.save_state)
        sv.addWidget(button("Exit to title", self.close_game, "Ghost", "Save and return to the title screen"))
        h.addWidget(self.sidebar)

        # Main column
        col = QWidget()
        cv = QVBoxLayout(col)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        self.topbar = QFrame()
        self.topbar.setObjectName("TopBar")
        tb = QHBoxLayout(self.topbar)
        tb.setContentsMargins(22, 10, 16, 10)
        self.crumb = lbl("", "Crumb", wrap=False)
        tb.addWidget(self.crumb)
        tb.addStretch(1)
        self.timer_label = lbl("", "Timer", wrap=False)
        self.timer_label.setToolTip("Session timer (can be turned off in Settings)")
        tb.addWidget(self.timer_label)
        self.read_btn = button("Read aloud", self.read_aloud, "Ghost", "Read this screen aloud", "Ctrl+Shift+S")
        tb.addWidget(self.read_btn)
        self.focus_btn = button("Focus mode", self.toggle_focus, None,
                                "Hide everything except the current objective (F6)")
        self.focus_btn.setCheckable(True)
        tb.addWidget(self.focus_btn)
        cv.addWidget(self.topbar)
        self.banner = QFrame()
        self.banner.setObjectName("Banner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 8, 8, 8)
        self.banner_text = lbl("", None)
        bl.addWidget(self.banner_text, 1)
        bl.addWidget(button("Dismiss", lambda: self.banner.hide(), "Ghost"))
        self.banner.hide()
        bwrap = QHBoxLayout()
        bwrap.setContentsMargins(22, 8, 22, 0)
        bwrap.addWidget(self.banner)
        cv.addLayout(bwrap)
        self.stack = QStackedWidget()
        cv.addWidget(self.stack, 1)
        h.addWidget(col, 1)

        self.screens: dict[str, QWidget] = {}
        self._build_screens()
        self._shortcuts()
        self.statusBar().showMessage("Offline. No accounts, no telemetry. Saves are stored on this computer.")
        self.tick = QTimer(self)
        self.tick.timeout.connect(self._tick)
        self.tick.start(1000)
        self.apply_settings()
        self.show_startup()

    # ------------------------------------------------------------ screens
    def _build_screens(self) -> None:
        from .screens import ALL_SCREENS
        for cls in ALL_SCREENS:
            s = cls(self)
            self.screens[cls.key] = s
            self.stack.addWidget(s)

    def get_screen(self, key: str):
        return self.screens[key]

    def show_startup(self) -> None:
        self.sidebar.hide()
        self.topbar.hide()
        self.banner.hide()
        self.stack.setCurrentWidget(self.screens["startup"])
        self.screens["startup"].refresh()

    def go(self, key: str, **kwargs) -> None:
        if self.game is None and key not in ("startup",):
            return
        s = self.screens[key]
        self.sidebar.setVisible(not self.settings.focus_mode)
        self.topbar.show()
        self.crumb.setText(s.title)
        if key in self.nav_items or key == "mission":
            item = self.mission_item if key == "mission" else self.nav_items[key]
            self.nav.blockSignals(True)
            self.nav.setCurrentItem(item)
            self.nav.blockSignals(False)
        s.focus_mode = self.settings.focus_mode
        s.open(**kwargs)
        self._switch(s)
        self.update_chrome()

    def _switch(self, w: QWidget) -> None:
        self.stack.setCurrentWidget(w)
        if self.settings.reduced_motion:
            return
        eff = QGraphicsOpacityEffect(w)
        w.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(140)
        anim.setStartValue(0.55)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: w.setGraphicsEffect(None))
        anim.start()
        self._anim = anim

    def current_screen(self):
        return self.stack.currentWidget()

    def _nav_changed(self, cur: QListWidgetItem | None, _prev) -> None:
        if cur is None:
            return
        key = cur.data(Qt.UserRole)
        if key:
            self.go(key)

    def update_chrome(self) -> None:
        if not self.game:
            return
        g = self.game
        self.player_label.setText(f"{g.profile['name']} · {g.title()}\n{g.org['name']}")
        active = g.db.one("SELECT run_id FROM mission_runs WHERE status='active' LIMIT 1")
        self.mission_item.setHidden(active is None)
        unread = sum(1 for m in g.list_messages() if m["status"] == "unread")
        self.nav_items["stakeholders"].setText("Stakeholders" + (f"  ({unread})" if unread else ""))
        due = len(g.due_reviews(self.settings.review_intervals)) if self.settings.review_reminders else 0
        self.nav_items["training"].setText("Training centre" + (f"  ({due} due)" if due else ""))
        self.save_state.setText(f"Saved locally · slot {g.slot}")

    # ------------------------------------------------------------ games
    def start_game(self, game: Game, first: bool = False) -> None:
        if self.game is not None and self.game is not game:
            try:
                self.game.close()
            except Exception:
                pass
        self.game = game
        self.settings.last_slot = game.slot
        self.save_settings()
        self.session_start = time.monotonic()
        self.break_shown = False
        game.check_achievements()
        self.go("dashboard")
        if self.recovered_from:
            self.toast(f"Your save could not be read, so it was restored from backup {self.recovered_from}. "
                       "The damaged file was kept beside it.", "warn")
            self.recovered_from = None
        elif first:
            self.toast("Welcome. Your mentor has left a message, and your first mission is ready.")

    def open_slot(self, slot: int) -> None:
        db, recovered = self.saves.open_with_recovery(slot)
        self.recovered_from = recovered
        self.start_game(Game(self.content, db, self.saves, slot))

    def close_game(self) -> None:
        if self.game is None:
            return
        self.screens["mission"].save_now()
        if self.settings.autosave_backups:
            try:
                self.game.backup("session-end")
            except Exception:
                pass
        self.game.close()
        self.game = None
        self.show_startup()

    def closeEvent(self, e) -> None:
        try:
            if self.game is not None:
                self.screens["mission"].save_now()
                if self.settings.autosave_backups:
                    self.game.backup("session-end")
                self.game.close()
        finally:
            self.save_settings()
        super().closeEvent(e)

    # ------------------------------------------------------------ settings
    def save_settings(self) -> None:
        try:
            save_settings(self.settings, self.settings_path)
        except OSError:
            pass

    def apply_settings(self) -> None:
        s = self.settings
        s.validate()
        p = theme.palette_for(s.theme, s.high_contrast)
        theme.set_current(p)
        app = QApplication.instance()
        f = QFont(app.font())
        f.setPointSizeF(10 * s.text_scale)
        app.setFont(f)
        app.setStyleSheet(theme.stylesheet(p, s.text_scale))
        self.timer_label.setVisible(s.show_timer)
        self.read_btn.setVisible(s.tts_enabled)
        self.focus_btn.setChecked(s.focus_mode)
        if self.game is not None:
            self.sidebar.setVisible(not s.focus_mode)
            cur = self.current_screen()
            if hasattr(cur, "refresh") and cur is not self.screens["startup"]:
                cur.focus_mode = s.focus_mode
                cur.refresh()

    def toggle_focus(self) -> None:
        if self.game is None:
            return
        self.settings.focus_mode = not self.settings.focus_mode
        self.save_settings()
        self.apply_settings()
        self.toast("Focus mode on: one objective at a time. Press F6 or Esc to leave." if self.settings.focus_mode
                   else "Focus mode off.")

    def change_text_size(self, delta: float | None) -> None:
        self.settings.text_scale = 1.0 if delta is None else self.settings.text_scale + delta
        self.settings.validate()
        self.save_settings()
        self.apply_settings()

    # ------------------------------------------------------------ services
    def toast(self, text: str, kind: str = "info") -> None:
        self.banner.setObjectName("BannerWarn" if kind == "warn" else "Banner")
        self.banner.setStyleSheet("")
        self.banner_text.setText(text)
        self.banner.show()
        self.statusBar().showMessage(text, 8000)
        # One timer owned by the window: restarting it keeps the newest toast up for its full time,
        # and it cannot fire after the window (and its banner label) has been destroyed.
        if not hasattr(self, "_banner_timer"):
            self._banner_timer = QTimer(self)
            self._banner_timer.setSingleShot(True)
            self._banner_timer.timeout.connect(self.banner.hide)
        self._banner_timer.start(9000 if kind == "warn" else 6000)

    def _tick(self) -> None:
        if self.game is None:
            return
        secs = int(time.monotonic() - self.session_start)
        self.timer_label.setText(f"Session {secs // 3600:d}:{secs // 60 % 60:02d}:{secs % 60:02d}")
        mins = self.settings.session_minutes
        if mins and secs >= mins * 60 and not self.break_shown:
            self.break_shown = True
            self.toast(f"You've been working for {mins} minutes. A short break helps consolidate learning; "
                       "your progress is saved. (You can change or turn off this reminder in Settings.)")

    def read_aloud(self) -> None:
        if not self.settings.tts_enabled:
            return
        if self.tts is None:
            try:
                from PySide6.QtTextToSpeech import QTextToSpeech
                self.tts = QTextToSpeech(self)
            except Exception:
                self.tts = False
        if not self.tts:
            self.toast("Text-to-speech is not available on this system. Windows normally provides voices "
                       "under Settings > Time & language > Speech.", "warn")
            return
        if self.tts.state() == self.tts.State.Speaking:
            self.tts.stop()
            return
        cur = self.current_screen()
        text = cur.speak_text() if hasattr(cur, "speak_text") else ""
        self.tts.say(text[:4000])

    def _shortcuts(self) -> None:
        for _, items in NAV:
            for key, _label, sc in items:
                if sc:
                    QShortcut(QKeySequence(sc), self, activated=lambda k=key: self.go(k))
        QShortcut(QKeySequence("F6"), self, activated=self.toggle_focus)
        QShortcut(QKeySequence("Escape"), self, activated=self._escape)
        QShortcut(QKeySequence("Ctrl+="), self, activated=lambda: self.change_text_size(0.1))
        QShortcut(QKeySequence("Ctrl++"), self, activated=lambda: self.change_text_size(0.1))
        QShortcut(QKeySequence("Ctrl+-"), self, activated=lambda: self.change_text_size(-0.1))
        QShortcut(QKeySequence("Ctrl+0"), self, activated=lambda: self.change_text_size(None))
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self.backup_now)
        QShortcut(QKeySequence("F1"), self, activated=self.show_shortcuts)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=lambda: self.nav.setFocus())

    def _escape(self) -> None:
        if self.settings.focus_mode:
            self.toggle_focus()

    def backup_now(self) -> None:
        if self.game is None:
            return
        p = self.game.backup("manual")
        self.toast(f"Backup saved: {p.name}")

    def show_shortcuts(self) -> None:
        lines = ["Navigation: Ctrl+L focuses the menu; use arrow keys and Enter.",
                 "Ctrl+1 Dashboard, Ctrl+2 Missions, Ctrl+3 Register, Ctrl+4 Workbench, Ctrl+5 Financial lab,",
                 "Ctrl+6 KRIs, Ctrl+7 Stakeholders, Ctrl+8 Reports, Ctrl+9 Training, Ctrl+, Settings.",
                 "F6 focus mode (Esc leaves it). Ctrl+= / Ctrl+- text size, Ctrl+0 reset.",
                 "Ctrl+B backup now. Ctrl+Shift+S read aloud (when enabled in Settings).",
                 "In missions: Ctrl+Enter submits the current step; Tab moves between options; Space selects."]
        DIALOGS.info(self, "Keyboard shortcuts", "\n".join(lines))
