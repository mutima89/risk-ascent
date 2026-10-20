"""Settings and accessibility, plus save and recovery management."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QSlider, QSpinBox
from PySide6.QtCore import Qt

from ...core.difficulty import DIFFICULTIES
from ...core.learning import DEFAULT_INTERVALS
from ...persistence.saves import SaveManager
from ..base import Screen
from ..widgets import Card, button, fit_height, grid, hbox, lbl, make_table, selected_data, set_rows


class SettingsScreen(Screen):
    key = "settings"
    title = "Settings & accessibility"

    def populate(self) -> None:
        s = self.win.settings
        lay = self.page.layout_
        lay.addWidget(lbl("SETTINGS AND ACCESSIBILITY", "Eyebrow"))
        lay.addWidget(lbl("Make it work for you", "H1"))
        lay.addWidget(lbl("Changes apply immediately and are saved on this computer.", "Muted"))

        look = Card("Display")
        self.theme = QComboBox()
        self.theme.addItem("Dark", "dark")
        self.theme.addItem("Light", "light")
        self.theme.setCurrentIndex(self.theme.findData(s.theme))
        self.theme.currentIndexChanged.connect(lambda _: self.set("theme", self.theme.currentData()))
        look.add(hbox(lbl("Theme", wrap=False), self.theme, "stretch"))
        hc = QCheckBox("High contrast")
        hc.setChecked(s.high_contrast)
        hc.toggled.connect(lambda v: self.set("high_contrast", v))
        look.add(hc)
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(85, 160)
        self.size_slider.setSingleStep(5)
        self.size_slider.setPageStep(10)
        self.size_slider.setValue(int(s.text_scale * 100))
        self.size_slider.setAccessibleName("Text size")
        size_lbl = lbl(f"Text size {int(s.text_scale * 100)}%", wrap=False)
        self.size_slider.valueChanged.connect(lambda v: size_lbl.setText(f"Text size {v}%"))
        self.size_slider.sliderReleased.connect(lambda: self.set("text_scale", self.size_slider.value() / 100))
        look.add(hbox(size_lbl, self.size_slider, button("Apply size", lambda: self.set("text_scale", self.size_slider.value() / 100)),
                      button("Reset", lambda: self.set("text_scale", 1.0), "Ghost")))
        look.add(lbl("Shortcut: Ctrl+= and Ctrl+- change text size anywhere; Ctrl+0 resets.", "Small"))
        rm = QCheckBox("Reduce motion (no screen transitions)")
        rm.setChecked(s.reduced_motion)
        rm.toggled.connect(lambda v: self.set("reduced_motion", v))
        look.add(rm)

        focus = Card("Focus and pacing")
        fm = QCheckBox("Focus mode: show only the current objective and checklist (F6)")
        fm.setChecked(s.focus_mode)
        fm.toggled.connect(lambda v: self.set("focus_mode", v))
        focus.add(fm)
        tm = QCheckBox("Show session timer")
        tm.setChecked(s.show_timer)
        tm.toggled.connect(lambda v: self.set("show_timer", v))
        focus.add(tm)
        self.session = QSpinBox()
        self.session.setRange(0, 120)
        self.session.setSpecialValueText("Off")
        self.session.setSuffix(" min")
        self.session.setValue(s.session_minutes)
        self.session.valueChanged.connect(lambda v: self.set("session_minutes", v, refresh=False))
        focus.add(hbox(lbl("Gentle break suggestion after", wrap=False), self.session, "stretch"))
        focus.add(lbl("The suggestion is a single dismissible banner. There are no streaks, timers that punish "
                      "you, or pressure to keep playing.", "Small"))

        speech = Card("Narration")
        tts = QCheckBox("Enable read-aloud (uses the voices installed in Windows)")
        tts.setChecked(s.tts_enabled)
        tts.toggled.connect(lambda v: self.set("tts_enabled", v))
        speech.add(tts)
        speech.add(lbl("When enabled, a 'Read aloud' button appears in the top bar (Ctrl+Shift+S). Press it again "
                       "to stop.", "Small"))
        if s.tts_enabled:
            speech.add(hbox(button("Test voice", self.win.read_aloud), stretch_end=True))

        learn = Card("Learning")
        rr = QCheckBox("Show 'reviews due' counts in the menu and dashboard (never a pop-up)")
        rr.setChecked(s.review_reminders)
        rr.toggled.connect(lambda v: self.set("review_reminders", v))
        learn.add(rr)
        self.intervals = QLineEdit(", ".join(str(i) for i in s.review_intervals))
        learn.add(lbl("Review intervals (days)"), hbox(self.intervals,
                       button("Save intervals", self.save_intervals),
                       button("Default", lambda: (self.intervals.setText(", ".join(map(str, DEFAULT_INTERVALS))),
                                                  self.save_intervals()), "Ghost")))
        learn.add(lbl("A correct answer moves a concept to the next interval; a miss brings it back tomorrow.",
                      "Small"))
        if self.win.game:
            g = self.game
            self.diff = QComboBox()
            for k, d in DIFFICULTIES.items():
                self.diff.addItem(f"{d.label}: {d.description}", k)
            self.diff.setCurrentIndex(self.diff.findData(g.profile["difficulty"]))
            self.diff.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            self.diff.setMinimumContentsLength(24)
            learn.add(lbl("Difficulty for this career", "H3"), self.diff,
                      hbox(button("Change difficulty", self.change_difficulty), stretch_end=True))
            learn.add(lbl("Applies to missions you start from now on. Difficulty also adapts within missions: "
                          "if you struggle, hints open and tasks are broken down; as you master material, support "
                          "is reduced.", "Small"))
        lay.addLayout(grid([look, focus, speech, learn], 2))

        priv = Card("Privacy and data")
        priv.add(lbl("Risk Ascent runs fully offline. It has no accounts, no analytics and no telemetry, and it "
                     "never downloads or runs code. Your display name and progress are stored only in the data "
                     "folder below.", "Body"))
        folder = QLineEdit(str(self.win.data_dir))
        folder.setReadOnly(True)
        folder.setCursorPosition(0)
        priv.add(folder)
        bk = QCheckBox("Take an automatic backup when a session ends (in addition to after missions)")
        bk.setChecked(s.autosave_backups)
        bk.toggled.connect(lambda v: self.set("autosave_backups", v))
        priv.add(bk)
        row = [button("Open data folder", self.open_folder)]
        if self.win.game:
            row.append(button("Reset this career", self.reset, "Danger"))
        priv.add(hbox(*row, stretch_end=True))
        lay.addWidget(priv)

    def set(self, key: str, value, refresh: bool = True) -> None:
        setattr(self.win.settings, key, value)
        self.win.save_settings()
        if refresh:
            self.win.apply_settings()

    def save_intervals(self) -> None:
        try:
            vals = [int(x) for x in self.intervals.text().replace(" ", "").split(",") if x]
            if not vals or any(v <= 0 for v in vals) or vals != sorted(vals):
                raise ValueError
        except ValueError:
            self.fail("Enter increasing whole numbers of days, separated by commas, e.g. 1, 3, 7, 14, 30.")
            return
        self.win.settings.review_intervals = vals[:8]
        self.win.save_settings()
        self.notify("Review intervals saved.")
        self.win.update_chrome()

    def change_difficulty(self) -> None:
        g = self.game
        k = self.diff.currentData()
        with g.db.tx():
            g._touch(difficulty=k)
        self.notify(f"Difficulty set to {DIFFICULTIES[k].label}.")

    def open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.win.data_dir)))

    def reset(self) -> None:
        g = self.game
        if not self.dialogs.typed_confirm(self, "Reset career", f"This deletes the career '{g.profile['name']}' in "
                                          f"slot {g.slot}. A final backup is taken first and can be restored from the "
                                          "title screen.", "RESET"):
            return
        g.reset_career("RESET")
        self.win.game = None
        self.win.show_startup()


class SavesScreen(Screen):
    key = "saves"
    title = "Saves & recovery"

    def populate(self) -> None:
        g = self.game
        lay = self.page.layout_
        sm: SaveManager = self.win.saves
        lay.addWidget(lbl("SAVE AND RECOVERY", "Eyebrow"))
        lay.addWidget(lbl(f"Slot {g.slot}: {g.profile['name']}", "H1"))
        lay.addWidget(lbl("Every action is written to the save immediately inside a database transaction, so an "
                          "interrupted save cannot leave half-written data. Backups are taken automatically after "
                          "each mission, promotion and session; the newest 15 automatic backups are kept, manual "
                          "ones are never deleted.", "Muted"))
        path = sm.slot_path(g.slot)
        info = Card("Current save")
        info.add(lbl(f"File: {path}", "Small", select=True))
        info.add(lbl(f"Size {path.stat().st_size / 1024:.0f} KB · schema version {g.db.version} · "
                     f"created with version {g.db.meta_get('created_version', '?')}", "Small"))
        self.verify_label = lbl("", "Small")
        info.add(self.verify_label)
        info.add(hbox(button("Back up now", self.backup, "Primary", shortcut="Ctrl+Shift+B"),
                      button("Verify integrity", self.verify), button("Export a copy", self.export_copy),
                      button("Open backups folder", self.open_backups, "Ghost"), stretch_end=True))
        lay.addWidget(info)
        bc = Card("Backups for this slot", "Restoring takes a safety copy of the current save first.")
        self.items = sm.list_backups(g.slot)
        self.table = make_table(["Backup", "Saved", "Size", "Valid"], 0)
        set_rows(self.table, [(b["name"], b["modified"].replace("T", " "), f"{b['size'] / 1024:.0f} KB",
                               "Yes" if b["valid"] else "No") for b in self.items], data=[b["path"] for b in self.items])
        fit_height(self.table, 10)
        bc.add(self.table, hbox(button("Restore selected backup", self.restore), stretch_end=True))
        lay.addWidget(bc)
        oc = Card("All career slots")
        rows = []
        for i, s in enumerate(sm.list_slots(), start=1):
            rows.append((i, s["name"] if s and s.get("ok") else ("Damaged" if s else "Empty"),
                         f"Level {s['level']}" if s and s.get("ok") else "", (s.get("updated_at") or "").replace("T", " ")[:16] if s else ""))
        t = make_table(["Slot", "Career", "Level", "Last played"], 1)
        set_rows(t, rows)
        fit_height(t, 6)
        oc.add(t, lbl("Switch careers from the title screen (Exit to title).", "Small"))
        lay.addWidget(oc)

    def backup(self) -> None:
        p = self.game.backup("manual")
        self.notify(f"Backup saved: {p.name}")
        self.refresh()

    def verify(self) -> None:
        ok = self.game.db.integrity_ok()
        self.verify_label.setText("✓ Integrity check passed." if ok else
                                  "✕ Integrity check failed. Restore the newest valid backup below.")
        self.verify_label.setObjectName("Good" if ok else "Bad")
        self.verify_label.setStyleSheet("")

    def export_copy(self) -> None:
        g = self.game
        path = self.dialogs.save_file(self, "Export save copy", str(Path.home() / f"RiskAscent_slot{g.slot}_"
                                                                     f"{datetime.now():%Y%m%d}.db"), "Save (*.db)")
        if not path:
            return
        b = g.backup("export")
        shutil.copy2(b, path)
        self.notify(f"Copy saved to {path}")

    def open_backups(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.win.saves.backup_dir(self.game.slot))))

    def restore(self) -> None:
        bpath = selected_data(self.table)
        if not bpath:
            self.notify("Select a backup first.")
            return
        b = next(x for x in self.items if x["path"] == bpath)
        if not b["valid"]:
            self.fail("That backup failed its integrity check and cannot be restored.")
            return
        if not self.dialogs.confirm(self, "Restore backup", f"Replace the current save with {b['name']}? A safety "
                                    "backup of the current state is taken first."):
            return
        g = self.game
        slot = g.slot
        try:
            self.win.saves.restore(slot, bpath, current=g.db)
        except Exception as exc:
            self.fail(exc)
            return
        self.win.game = None
        self.win.open_slot(slot)
        self.win.toast(f"Restored {b['name']}.")
