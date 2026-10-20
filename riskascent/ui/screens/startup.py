"""Startup / title screen: loading summary, career slots, new career wizard."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QLineEdit, QListWidget, QListWidgetItem, QRadioButton, QSpinBox, QVBoxLayout, QWidget)

from ... import __version__
from ...core.content import count_decision_points
from ...core.difficulty import DIFFICULTIES
from ...game import Game
from ...persistence.saves import MAX_SLOTS
from ..base import Screen
from ..widgets import Card, badge, button, grid, hbox, lbl, make_table, set_rows, vbox
from .. import theme


class StartupScreen(Screen):
    key = "startup"
    title = "Welcome"

    def populate(self) -> None:
        c = self.win.content
        lay = self.page.layout_
        hero = QWidget()
        hv = QVBoxLayout(hero)
        hv.setContentsMargins(0, 18, 0, 6)
        hv.setSpacing(4)
        hv.addWidget(lbl("A CAREER SIMULATOR FOR RISK PROFESSIONALS", "Eyebrow"))
        t = lbl("RISK ASCENT", "H1")
        t.setStyleSheet("font-size: 30pt; letter-spacing: 3px;")
        hv.addWidget(t)
        hv.addWidget(lbl("From Junior Analyst to Chief Risk Officer. Make decisions, live with the consequences, "
                         "and learn why good judgement and good outcomes are not the same thing.", "Muted"))
        lay.addWidget(hero)

        slots = self.win.saves.list_slots()
        n_missions = len(c.missions)
        loaded = Card(eyebrow="Ready")
        loaded.add(lbl(f"✓ Loaded and validated {n_missions} missions, {count_decision_points(c)} decision "
                       f"points, {len(c.orgs)} organisations, {len(c.achievements)} achievements.", "Small"))
        loaded.add(lbl(f"✓ {sum(1 for s in slots if s)} saved career(s) found. Data folder: {self.win.data_dir}",
                       "Small", select=True))
        loaded.add(lbl("✓ Fully offline. No account, no telemetry. Version " + __version__, "Small"))
        lay.addWidget(loaded)

        lay.addWidget(lbl("Careers", "H2"))
        cards = []
        for i, s in enumerate(slots, start=1):
            card = Card(kind="CardAccent" if s and s.get("ok") and i == self.win.settings.last_slot else "Card")
            if s is None:
                card.add(lbl(f"SLOT {i}", "Eyebrow"), lbl("Empty", "H3"),
                         lbl("Start a new career in any of the organisations.", "Muted"), "stretch",
                         button("New career", lambda i=i: self.new_career(i), "Primary"))
            elif not s.get("ok"):
                card.add(lbl(f"SLOT {i}", "Eyebrow"), lbl("Save needs recovery", "H3"),
                         lbl("This save could not be read. Opening it restores the newest valid backup and "
                             "keeps the damaged file.", "Muted"), "stretch",
                         hbox(button("Recover and open", lambda i=i: self.open_slot(i), "Primary"),
                              button("Backups", lambda i=i: self.backups(i))))
            else:
                org = self.win.content.orgs.get(s["org_id"], {})
                lvl = self.win.content.level(int(s["level"]))
                card.add(lbl(f"SLOT {i}", "Eyebrow"), lbl(s["name"], "H3"),
                         lbl(f"{lvl['title']} (level {s['level']})", None),
                         lbl(f"{org.get('name', s['org_id'])}\n{s['xp']} XP · last played {s['updated_at'][:16].replace('T', ' ')}",
                             "Small"), "stretch",
                         hbox(button("Continue", lambda i=i: self.open_slot(i), "Primary"),
                              button("Backups", lambda i=i: self.backups(i)),
                              button("Delete", lambda i=i: self.delete(i), "Danger")))
            card.setMinimumHeight(170)
            cards.append(card)
        lay.addLayout(grid(cards, 3))
        lay.addWidget(lbl("Saves are stored on this computer and backed up automatically after missions and "
                          "promotions. Credentials earned in the game are internal achievements, not accredited "
                          "qualifications. Salaries shown are illustrative simulation data.", "Small"))

    def open_slot(self, slot: int) -> None:
        try:
            self.win.open_slot(slot)
        except Exception as exc:
            self.fail(f"This save could not be opened and no valid backup was found.\n\n{exc}")

    def new_career(self, slot: int) -> None:
        dlg = NewCareerDialog(self, self.win.content)
        if dlg.exec() != QDialog.Accepted:
            return
        v = dlg.values()
        try:
            g = Game.new_career(self.win.content, self.win.saves, slot, v["name"], v["org"], v["track"],
                                v["difficulty"], v["avatar"], seed=v["seed"])
        except ValueError as exc:
            self.fail(exc)
            return
        self.win.start_game(g, first=True)

    def delete(self, slot: int) -> None:
        if self.dialogs.typed_confirm(self, "Delete career",
                                      f"Delete the career in slot {slot}? Backups in the backups folder are kept, "
                                      "so it can be restored later from 'Backups'.", "DELETE"):
            self.win.saves.delete_slot(slot, "DELETE")
            self.refresh()

    def backups(self, slot: int) -> None:
        BackupDialog(self, slot).exec()
        self.refresh()


class BackupDialog(QDialog):
    def __init__(self, screen: StartupScreen, slot: int):
        super().__init__(screen)
        self.screen_, self.slot = screen, slot
        self.setWindowTitle(f"Backups for slot {slot}")
        self.resize(720, 420)
        lay = QVBoxLayout(self)
        lay.addWidget(lbl("Restoring replaces the current save with the selected backup. A safety copy of the "
                          "current save is taken first, so a restore can itself be undone.", "Muted"))
        self.table = make_table(["Backup", "Saved", "Size", "Valid"], 0)
        lay.addWidget(self.table, 1)
        self.items = screen.win.saves.list_backups(slot)
        set_rows(self.table, [(b["name"], b["modified"].replace("T", " "), f"{b['size'] / 1024:.0f} KB",
                               "Yes" if b["valid"] else "No") for b in self.items], data=self.items)
        lay.addLayout(hbox("stretch", button("Restore selected", self.restore, "Primary"),
                           button("Close", self.reject)))

    def restore(self) -> None:
        r = self.table.currentRow()
        if r < 0:
            DIALOGS_error(self, "Choose a backup first.")
            return
        b = self.items[r]
        if not b["valid"]:
            DIALOGS_error(self, "That backup failed its integrity check and cannot be restored.")
            return
        if not self.screen_.dialogs.confirm(self, "Restore backup", f"Restore {b['name']} into slot {self.slot}?"):
            return
        try:
            self.screen_.win.saves.restore(self.slot, b["path"])
        except Exception as exc:
            DIALOGS_error(self, str(exc))
            return
        self.screen_.dialogs.info(self, "Restored", "Backup restored. Choose Continue to open it.")
        self.accept()


def DIALOGS_error(parent, text: str) -> None:
    from ..widgets import DIALOGS
    DIALOGS.error(parent, "Backups", text)


class NewCareerDialog(QDialog):
    AVATARS = ["◆", "▲", "●", "★", "■", "✦"]

    def __init__(self, parent, content):
        super().__init__(parent)
        self.c = content
        self.setWindowTitle("New career")
        self.resize(860, 640)
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.addWidget(lbl("Start your career", "H1"))
        lay.addWidget(lbl("Only a display name is stored, locally. Everything else can be changed later "
                          "through lateral moves or New Game Plus.", "Muted"))
        form = QFormLayout()
        form.setSpacing(10)
        self.name = QLineEdit()
        self.name.setMaxLength(40)
        self.name.setPlaceholderText("Display name (1-40 characters)")
        self.name.setAccessibleName("Display name")
        form.addRow("Name", self.name)
        self.avatar = QComboBox()
        for a in self.AVATARS:
            self.avatar.addItem(a)
        form.addRow("Badge", self.avatar)
        self.track = QComboBox()
        for t in content.careers["tracks"]:
            self.track.addItem(t["label"], t["id"])
        form.addRow("Career track", self.track)
        lay.addLayout(form)

        lay.addWidget(lbl("Organisation", "H3"))
        body = QHBoxLayout()
        self.orgs = QListWidget()
        self.orgs.setAccessibleName("Organisation")
        for o in content.orgs.values():
            it = QListWidgetItem(f"{o['name']}\n{o['industry_label']} · {o['city']} · {o['currency']}")
            it.setData(Qt.UserRole, o["id"])
            self.orgs.addItem(it)
        self.orgs.setCurrentRow(0)
        self.org_desc = lbl("", "Body")
        self.org_desc.setMinimumWidth(300)
        self.orgs.currentItemChanged.connect(self._org_changed)
        body.addWidget(self.orgs, 3)
        body.addWidget(self.org_desc, 2)
        lay.addLayout(body, 1)
        self._org_changed()

        lay.addWidget(lbl("Difficulty", "H3"))
        self.diff_group = QButtonGroup(self)
        dl = QHBoxLayout()
        for i, (k, d) in enumerate(DIFFICULTIES.items()):
            rb = QRadioButton(d.label)
            rb.setToolTip(d.description)
            rb.setProperty("key", k)
            if k == "standard":
                rb.setChecked(True)
            self.diff_group.addButton(rb, i)
            dl.addWidget(_wrap(vbox(rb, lbl(d.description, "Small"), spacing=4)), 1)
        lay.addLayout(dl)
        adv = QHBoxLayout()
        adv.addWidget(lbl("Scenario seed (optional, for reproducible runs):", "Small"))
        self.seed = QSpinBox()
        self.seed.setRange(0, 2_000_000_000)
        self.seed.setSpecialValueText("Random")
        adv.addWidget(self.seed)
        adv.addStretch(1)
        lay.addLayout(adv)
        self.err = lbl("", "Bad")
        lay.addWidget(self.err)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Begin career")
        bb.button(QDialogButtonBox.Ok).setObjectName("Primary")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.name.setFocus()

    def _org_changed(self, *_):
        it = self.orgs.currentItem()
        if not it:
            return
        o = self.c.orgs[it.data(Qt.UserRole)]
        self.org_desc.setText(f"{o['name']}\n\n{o['description']}\n\nEmployees: {o['employees']:,}\nRegulator: "
                              f"{o['regulator']}\nCurrency: {o['currency']}")

    def _accept(self):
        if not self.name.text().strip():
            self.err.setText("Please enter a display name.")
            return
        self.accept()

    def values(self) -> dict:
        b = self.diff_group.checkedButton()
        return {"name": self.name.text().strip(), "avatar": self.avatar.currentText(),
                "track": self.track.currentData(), "org": self.orgs.currentItem().data(Qt.UserRole),
                "difficulty": b.property("key") if b else "standard", "seed": self.seed.value() or None}

    def set_values(self, name: str, org: str, track: str = "erm", difficulty: str = "standard") -> None:
        """Used by automated UI tests."""
        self.name.setText(name)
        for i in range(self.orgs.count()):
            if self.orgs.item(i).data(Qt.UserRole) == org:
                self.orgs.setCurrentRow(i)
        self.track.setCurrentIndex(self.track.findData(track))
        for b in self.diff_group.buttons():
            if b.property("key") == difficulty:
                b.setChecked(True)


def _wrap(layout) -> QWidget:
    w = QWidget()
    w.setLayout(layout)
    return w
