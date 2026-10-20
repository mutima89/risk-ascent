"""Risk register editor."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout, QLineEdit,
                               QListWidget, QListWidgetItem, QPlainTextEdit, QSpinBox, QVBoxLayout)

from ...core.risk_engine import (CONTROL_EFFECTIVENESS, CONTROL_TYPES, RISK_CATEGORIES, TREATMENTS, ControlRating,
                                 prioritize, suggested_residual, validate_residual)
from ...game import RISK_STATUSES
from ..base import Screen
from ..widgets import Card, button, hbox, lbl, make_table, selected_data, set_rows
from .. import theme


class RegisterScreen(Screen):
    key = "register"
    title = "Risk register"

    def __init__(self, win):
        super().__init__(win)
        self.cell: tuple[int, int] | None = None
        self.search = ""
        self.cat = ""
        self.app_filter = ""

    def open(self, cell=None, **_):
        self.cell = cell if cell and cell[0] else None
        self.refresh()

    def populate(self) -> None:
        g = self.game
        p = theme.current()
        lay = self.page.layout_
        lay.addWidget(lbl("RISK REGISTER", "Eyebrow"))
        lay.addWidget(lbl(f"{g.org['name']}: {len(g.list_risks())} risks", "H1"))
        lay.addWidget(lbl("Each risk is written as cause → event → consequence, rated inherent (before "
                          "controls) and residual (after), and compared with appetite. Sorted by priority.", "Muted"))

        bar_ = hbox(spacing=8)
        self.search_edit = QLineEdit(self.search)
        self.search_edit.setPlaceholderText("Search title, cause, owner...")
        self.search_edit.returnPressed.connect(self._apply_filters)
        self.cat_combo = QComboBox()
        self.cat_combo.addItem("All categories", "")
        for c in RISK_CATEGORIES:
            self.cat_combo.addItem(c, c)
        self.cat_combo.setCurrentIndex(max(0, self.cat_combo.findData(self.cat)))
        self.app_combo = QComboBox()
        for v in ["", "Outside tolerance", "Above appetite", "Within appetite"]:
            self.app_combo.addItem(v or "Any appetite status", v)
        self.app_combo.setCurrentIndex(max(0, self.app_combo.findData(self.app_filter)))
        for w in (self.search_edit, self.cat_combo, self.app_combo):
            bar_.addWidget(w)
        bar_.addWidget(button("Filter", self._apply_filters))
        if self.cell:
            bar_.addWidget(button(f"Clear cell filter (L{self.cell[0]} × I{self.cell[1]})", self._clear_cell, "Ghost"))
        bar_.addStretch(1)
        lay.addLayout(bar_)

        appetite = g.appetite()
        mat = g.matrix()
        risks = prioritize(g.list_risks(), appetite)
        rows, colors, data = [], {}, []
        q = self.search.lower()
        for r in risks:
            rs = r["res_l"] * r["res_i"]
            st = appetite.status(r["category"], rs)
            if q and q not in " ".join(str(r.get(k, "")) for k in ("title", "cause", "event", "owner", "risk_id")).lower():
                continue
            if self.cat and r["category"] != self.cat:
                continue
            if self.app_filter and st != self.app_filter:
                continue
            if self.cell and (r["res_l"], r["res_i"]) != self.cell:
                continue
            i = len(rows)
            band = mat.band(rs)
            rows.append((r["risk_id"], r["title"], r["category"], r["owner"],
                         f"{r['inh_l']}×{r['inh_i']} = {r['inh_l'] * r['inh_i']}",
                         f"{r['res_l']}×{r['res_i']} = {rs} {band}", st, r["treatment"], r["status"]))
            colors[(i, 5)] = theme.band_color(band)
            colors[(i, 6)] = theme.status_color(st)
            data.append(r["risk_id"])
        self.table = make_table(["ID", "Risk", "Category", "Owner", "Inherent", "Residual", "Appetite",
                                 "Treatment", "Status"], 1)
        set_rows(self.table, rows, colors, data)
        self.table.setMinimumHeight(420)
        self.table.doubleClicked.connect(lambda *_: self.edit())
        lay.addWidget(self.table)
        lay.addLayout(hbox(button("New risk", self.new, "Primary", shortcut="Ctrl+N"),
                           button("Edit selected", self.edit), button("Add from library", self.from_library),
                           button("Delete selected", self.delete, "Danger"), "stretch",
                           button("Export CSV", self.export), button("Open workbench",
                                                                      lambda: self.win.go("workbench"))))
        lay.addWidget(lbl(f"Showing {len(rows)} risk(s). Double-click a row to edit. Ratings use the "
                          f"organisation's {mat.size}×{mat.size} matrix.", "Small"))

    def _apply_filters(self) -> None:
        self.search = self.search_edit.text().strip()
        self.cat = self.cat_combo.currentData()
        self.app_filter = self.app_combo.currentData()
        self.refresh()

    def _clear_cell(self) -> None:
        self.cell = None
        self.refresh()

    def new(self) -> None:
        self._edit_dialog(None)

    def edit(self) -> None:
        rid = selected_data(self.table)
        if not rid:
            self.notify("Select a risk first.")
            return
        self._edit_dialog(self.game.get_risk(rid))

    def _edit_dialog(self, risk: dict | None) -> None:
        dlg = RiskDialog(self, risk)
        if dlg.exec() == QDialog.Accepted:
            self.game.check_achievements()
            self.notify(f"Saved {dlg.saved['risk_id']}: {dlg.saved['title']}")
            self.refresh()

    def delete(self) -> None:
        rid = selected_data(self.table)
        if not rid:
            self.notify("Select a risk first.")
            return
        if self.dialogs.confirm(self, "Delete risk", f"Delete {rid} from the register? Closing it (status "
                                "'Closed') keeps the audit trail and is usually better."):
            self.game.delete_risk(rid)
            self.refresh()

    def export(self) -> None:
        from pathlib import Path
        from ...paths import reports_dir
        default = str(reports_dir() / f"risk_register_month{self.game.period()}.csv")
        path = self.dialogs.save_file(self, "Export register", default, "CSV files (*.csv)")
        if not path:
            return
        try:
            self.game.export_register_csv(Path(path))
        except OSError as exc:
            self.fail(f"Could not write the file: {exc}")
            return
        self.game.check_achievements()
        self.notify(f"Register exported to {path}")

    def from_library(self) -> None:
        dlg = LibraryDialog(self)
        if dlg.exec() == QDialog.Accepted and dlg.choice:
            lib = dict(self.game.c.risk_library[dlg.choice])
            g = self.game
            r = {k: lib.get(k) for k in ("title", "cause", "event", "consequence", "category", "inh_l", "inh_i",
                                         "controls", "control_eff", "res_l", "res_i", "treatment", "notes")}
            from ...core.util import render
            for k in ("title", "cause", "event", "consequence"):
                r[k] = render(r[k], g.ctx())
            r.update({"owner": g.person(lib["owner_role"])["name"], "action_owner": g.person(lib.get("action_role", lib["owner_role"]))["name"],
                      "status": "Open", "target_date": "", "lib_id": lib["id"], "source": "Library"})
            size = g.matrix().size
            for k in ("inh_l", "inh_i", "res_l", "res_i"):
                r[k] = min(size, int(r[k]))
            self._edit_dialog(r)


class LibraryDialog(QDialog):
    def __init__(self, screen: RegisterScreen):
        super().__init__(screen)
        self.choice = None
        g = screen.game
        self.setWindowTitle("Risk library")
        self.resize(720, 480)
        lay = QVBoxLayout(self)
        lay.addWidget(lbl("Generic and industry-specific risks you can adapt. Always tailor the cause and "
                          "consequence to the organisation.", "Muted"))
        self.list = QListWidget()
        have = {r["lib_id"] for r in g.list_risks()}
        ind = g.org["industry"]
        for lib in g.c.risk_library.values():
            if lib["id"] in have or (lib.get("industries") and ind not in lib["industries"]):
                continue
            it = QListWidgetItem(f"{lib['title']}  ({lib['category']})")
            it.setData(Qt.UserRole, lib["id"])
            it.setToolTip(lib["cause"])
            self.list.addItem(it)
        lay.addWidget(self.list, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Use this risk")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _ok(self):
        it = self.list.currentItem()
        if it:
            self.choice = it.data(Qt.UserRole)
            self.accept()


class RiskDialog(QDialog):
    def __init__(self, screen: RegisterScreen, risk: dict | None):
        super().__init__(screen)
        self.s = screen
        g = screen.game
        self.g = g
        self.risk = dict(risk or {})
        self.saved: dict | None = None
        is_new = not self.risk.get("risk_id")
        self.setWindowTitle("New risk" if is_new else f"Edit {self.risk['risk_id']}")
        self.resize(820, 760)
        mat = g.matrix()
        lay = QVBoxLayout(self)
        lay.addWidget(lbl("New risk" if is_new else f"{self.risk['risk_id']}", "H2"))
        form = QFormLayout()
        form.setSpacing(8)
        r = self.risk
        self.title_e = QLineEdit(r.get("title", ""))
        self.title_e.setMaxLength(120)
        self.cause = QPlainTextEdit(r.get("cause", ""))
        self.event_e = QPlainTextEdit(r.get("event", ""))
        self.cons = QPlainTextEdit(r.get("consequence", ""))
        for w, ph in ((self.cause, "Because... (the cause or driver)"), (self.event_e, "...this may happen (the event)"),
                      (self.cons, "...leading to (the consequence for objectives)")):
            w.setMaximumHeight(62)
            w.setPlaceholderText(ph)
        self.cat = QComboBox()
        self.cat.addItems(RISK_CATEGORIES)
        if r.get("category"):
            self.cat.setCurrentText(r["category"])
        people = [g.person(role) for role in g.c.roles if role not in ("rival", "analyst", "board", "mentor")]
        self.owner = QComboBox()
        self.owner.setEditable(True)
        self.action_owner = QComboBox()
        self.action_owner.setEditable(True)
        for pp in people:
            self.owner.addItem(f"{pp['name']}")
            self.action_owner.addItem(f"{pp['name']}")
        self.owner.setCurrentText(r.get("owner") or people[0]["name"])
        self.action_owner.setCurrentText(r.get("action_owner") or r.get("owner") or people[0]["name"])
        form.addRow("Title", self.title_e)
        form.addRow("Cause", self.cause)
        form.addRow("Event", self.event_e)
        form.addRow("Consequence", self.cons)
        form.addRow("Category", self.cat)
        form.addRow("Risk owner", self.owner)
        lay.addLayout(form)

        rg = QGridLayout()
        rg.setHorizontalSpacing(10)

        def combo(labels, val):
            cb = QComboBox()
            for n, l in enumerate(labels, start=1):
                cb.addItem(f"{n} - {l}", n)
            cb.setCurrentIndex(max(0, min(len(labels), int(val or 1)) - 1))
            cb.currentIndexChanged.connect(self.update_feedback)
            return cb

        self.il = combo(mat.likelihood_labels, r.get("inh_l", 3))
        self.ii = combo(mat.impact_labels, r.get("inh_i", 3))
        self.rl = combo(mat.likelihood_labels, r.get("res_l", r.get("inh_l", 3)))
        self.ri = combo(mat.impact_labels, r.get("res_i", r.get("inh_i", 3)))
        self.ctrl = QPlainTextEdit(r.get("controls", ""))
        self.ctrl.setMaximumHeight(52)
        self.ctrl.setPlaceholderText("Existing controls")
        self.eff = QComboBox()
        for n, l in enumerate(CONTROL_EFFECTIVENESS):
            self.eff.addItem(f"{n} - {l}", n)
        self.eff.setCurrentIndex(int(r.get("control_eff") or 0))
        self.eff.currentIndexChanged.connect(self.update_feedback)
        self.ctype = QComboBox()
        self.ctype.addItems(CONTROL_TYPES)
        rg.addWidget(lbl("Inherent likelihood", "Small"), 0, 0)
        rg.addWidget(self.il, 1, 0)
        rg.addWidget(lbl("Inherent impact", "Small"), 0, 1)
        rg.addWidget(self.ii, 1, 1)
        rg.addWidget(lbl("Residual likelihood", "Small"), 0, 2)
        rg.addWidget(self.rl, 1, 2)
        rg.addWidget(lbl("Residual impact", "Small"), 0, 3)
        rg.addWidget(self.ri, 1, 3)
        rg.addWidget(lbl("Existing controls", "Small"), 2, 0)
        rg.addWidget(self.ctrl, 3, 0, 1, 2)
        rg.addWidget(lbl("Control effectiveness", "Small"), 2, 2)
        rg.addWidget(self.eff, 3, 2)
        rg.addWidget(lbl("Main control type", "Small"), 2, 3)
        rg.addWidget(self.ctype, 3, 3)
        lay.addLayout(rg)
        self.feedback = lbl("", "Small")
        lay.addLayout(hbox(self.feedback, "stretch", button("Suggest residual", self.suggest)))

        form2 = QFormLayout()
        self.treat = QComboBox()
        self.treat.addItems(TREATMENTS)
        if r.get("treatment"):
            self.treat.setCurrentText(r["treatment"])
        self.status = QComboBox()
        self.status.addItems(RISK_STATUSES)
        self.status.setCurrentText(r.get("status") or "Open")
        self.target = QLineEdit(str(r.get("target_date") or ""))
        self.target.setPlaceholderText("e.g. Month 6 or 2027-03")
        self.notes = QPlainTextEdit(r.get("notes") or "")
        self.notes.setMaximumHeight(60)
        form2.addRow("Treatment", self.treat)
        form2.addRow("Action owner", self.action_owner)
        form2.addRow("Target date", self.target)
        form2.addRow("Status", self.status)
        form2.addRow("Notes", self.notes)
        lay.addLayout(form2)
        self.err = lbl("", "Bad")
        lay.addWidget(self.err)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.update_feedback()

    def suggest(self) -> None:
        rl, ri = suggested_residual(self.il.currentData(), self.ii.currentData(),
                                    [ControlRating(self.ctype.currentText(), self.eff.currentData())])
        self.rl.setCurrentIndex(rl - 1)
        self.ri.setCurrentIndex(ri - 1)
        self.update_feedback()

    def update_feedback(self, *_):
        g = self.g
        mat = g.matrix()
        il, ii, rl, ri = (c.currentData() for c in (self.il, self.ii, self.rl, self.ri))
        if None in (il, ii, rl, ri):
            return
        ins, inb = mat.rate(il, ii)
        rs, rb = mat.rate(rl, ri)
        st = g.appetite().status(self.cat.currentText(), rs)
        warns = validate_residual((il, ii), (rl, ri), self.eff.currentData() or 0)
        self.feedback.setText(f"Inherent {ins} ({inb}) → residual {rs} ({rb}) · {st}"
                              + ("\n⚠ " + "\n⚠ ".join(warns) if warns else ""))

    def values(self) -> dict:
        r = dict(self.risk)
        r.update({"title": self.title_e.text().strip(), "cause": self.cause.toPlainText().strip(),
                  "event": self.event_e.toPlainText().strip(), "consequence": self.cons.toPlainText().strip(),
                  "category": self.cat.currentText(), "owner": self.owner.currentText().strip(),
                  "inh_l": self.il.currentData(), "inh_i": self.ii.currentData(),
                  "res_l": self.rl.currentData(), "res_i": self.ri.currentData(),
                  "controls": self.ctrl.toPlainText().strip(), "control_eff": self.eff.currentData(),
                  "treatment": self.treat.currentText(), "action_owner": self.action_owner.currentText().strip(),
                  "target_date": self.target.text().strip(), "status": self.status.currentText(),
                  "notes": self.notes.toPlainText().strip()})
        return r

    def save(self) -> None:
        try:
            self.saved = self.g.save_risk(self.values())
        except ValueError as exc:
            self.err.setText(str(exc))
            return
        self.accept()
