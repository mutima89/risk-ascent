"""Controls assurance (design and operating tests, findings) and business
continuity (BIA review, recovery order)."""

from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QLineEdit, QPlainTextEdit, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from ...core.bcm import Process, criticality
from ...core.controls import DESIGN_CRITERIA, SAMPLE_SIZES, design_rating, finding_severity, operating_result
from ...core.risk_engine import CONTROL_EFFECTIVENESS
from ..base import Screen
from ..widgets import Card, button, grid, hbox, lbl, make_table, selected_data, set_rows, vbox
from .. import theme


def eff_label(v) -> str:
    return "Not tested" if v is None else f"{v} {CONTROL_EFFECTIVENESS[int(v)]}"


class AssuranceScreen(Screen):
    key = "assurance"
    title = "Controls & resilience"

    def __init__(self, win):
        super().__init__(win)
        self.tab_index = 0

    def populate(self) -> None:
        lay = self.page.layout_
        lay.addWidget(lbl("CONTROLS, ASSURANCE AND RESILIENCE", "Eyebrow"))
        lay.addWidget(lbl("Do the controls actually work?", "H1"))
        tabs = QTabWidget()
        tabs.addTab(self._controls_tab(), "Control testing")
        tabs.addTab(self._findings_tab(), "Findings")
        tabs.addTab(self._bia_tab(), "Business impact analysis")
        tabs.setCurrentIndex(self.tab_index)
        tabs.currentChanged.connect(lambda i: setattr(self, "tab_index", i))
        lay.addWidget(tabs)

    # ------------------------------------------------------------ controls
    def _controls_tab(self) -> QWidget:
        g = self.game
        w = QWidget()
        lay = vbox(spacing=12, margins=(14, 14, 14, 14))
        w.setLayout(lay)
        ctrls = g.list_controls()
        self.ctrl_table = make_table(["ID", "Control", "Type", "Frequency", "Owner", "Design", "Operating",
                                      "Overall", "Last test"], 1)
        rows, colors = [], {}
        for i, c in enumerate(ctrls):
            lt = c.get("last_test")
            rows.append((c["control_id"], c["name"], c["type"], c["frequency"], c.get("owner", ""),
                         eff_label(c.get("design_rating")), eff_label(c.get("operating_rating")),
                         eff_label(c.get("effectiveness", 0)),
                         f"Month {lt['period']}: {lt['conclusion']}" if lt else "Never"))
            e = c.get("effectiveness", 0)
            colors[(i, 7)] = theme.current().good if e >= 3 else theme.current().warn if e == 2 else theme.current().bad
        set_rows(self.ctrl_table, rows, colors, [c["control_id"] for c in ctrls])
        self.ctrl_table.setMinimumHeight(260)
        self.ctrl_table.currentCellChanged.connect(lambda *_: self._ctrl_selected())
        lay.addWidget(self.ctrl_table)

        test = Card("Test the selected control",
                    "Design: would it work if performed as described? Operating: did it actually operate? "
                    "A control is only as good as the weaker of the two.")
        self.ctrl_desc = lbl("Select a control above.", "Small")
        test.add(self.ctrl_desc)
        self.design_boxes = {}
        for key, label in DESIGN_CRITERIA:
            cb = QCheckBox(label)
            self.design_boxes[key] = cb
            test.add(cb)
        self.tested = QSpinBox()
        self.tested.setRange(0, 500)
        self.exceptions = QSpinBox()
        self.exceptions.setRange(0, 500)
        self.sample_note = lbl("", "Small")
        test.add(hbox(lbl("Items tested", wrap=False), self.tested, lbl("Exceptions found", wrap=False),
                      self.exceptions, "stretch"))
        test.add(self.sample_note)
        self.test_result = lbl("", "Body")
        test.add(self.test_result)
        test.add(hbox(button("Evaluate", self.evaluate), button("Record test result", self.record, "Primary"),
                      button("Raise finding from this test", self.raise_from_test), stretch_end=True))
        lay.addWidget(test)
        if ctrls:
            self.ctrl_table.selectRow(0)
            self._ctrl_selected()
        return w

    def _ctrl(self):
        cid = selected_data(self.ctrl_table)
        return next((c for c in self.game.list_controls() if c["control_id"] == cid), None)

    def _ctrl_selected(self):
        c = self._ctrl()
        if not c:
            return
        self.ctrl_desc.setText(f"{c['name']}: {c.get('description', '')}\nEvidence: {c.get('evidence', '')} · "
                               f"mitigates {', '.join(c.get('mitigates', []))}")
        n = SAMPLE_SIZES.get(c["frequency"], 1)
        self.sample_note.setText(f"Guidance: a {c['frequency'].lower()} control needs a sample of at least {n}.")
        self.test_result.setText("")

    def evaluate(self):
        c = self._ctrl()
        if not c:
            self.notify("Select a control first.")
            return None
        d, gaps = design_rating({k: b.isChecked() for k, b in self.design_boxes.items()})
        try:
            op = operating_result(c["frequency"], self.tested.value(), self.exceptions.value())
        except ValueError as exc:
            self.fail(exc)
            return None
        overall = min(d, op["rating"]) if op["rating"] is not None else min(d, 2)
        self.test_result.setText(f"Design: {eff_label(d)}" + (f" (gaps: {'; '.join(gaps)})" if gaps else "") +
                                 f"\nOperating: {op['conclusion']}. {op['note']}\nOverall effectiveness: "
                                 f"{eff_label(overall)}")
        return d, op, gaps

    def record(self):
        ev = self.evaluate()
        if not ev:
            return
        d, op, gaps = ev
        c = self._ctrl()
        self.game.record_control_test(c["control_id"], d, op["rating"], gaps, op["conclusion"])
        self.game.check_achievements()
        self.notify(f"Test recorded for {c['control_id']}. Linked register risks were re-assessed.")
        self.refresh()

    def raise_from_test(self):
        ev = self.evaluate()
        if not ev:
            return
        d, op, gaps = ev
        c = self._ctrl()
        g = self.game
        linked = [r for r in g.list_risks() if r.get("lib_id") in c.get("mitigates", [])]
        score = max((r["res_l"] * r["res_i"] for r in linked), default=9)
        sev = finding_severity(score, min(d, op["rating"]) if op["rating"] is not None else None)
        FindingDialog(self, {"control_id": c["control_id"], "severity": sev,
                             "title": f"{c['name']}: " + (gaps[0] if gaps else op["conclusion"]),
                             "root_cause": "; ".join(gaps) or op["note"], "owner": c.get("owner", "")}).exec()
        self.refresh()

    # ------------------------------------------------------------ findings
    def _findings_tab(self) -> QWidget:
        g = self.game
        w = QWidget()
        lay = vbox(spacing=12, margins=(14, 14, 14, 14))
        w.setLayout(lay)
        fs = g.list_findings()
        self.find_table = make_table(["ID", "Finding", "Severity", "Control", "Owner", "Due", "Status"], 1)
        colors = {(i, 2): theme.band_color(f["severity"]) for i, f in enumerate(fs)}
        set_rows(self.find_table, [(f["finding_id"], f["title"], f["severity"], f.get("control_id", ""),
                                    f.get("owner", ""), f"Month {f.get('due_period', '')}", f.get("status", "Open"))
                                   for f in fs], colors, [f["finding_id"] for f in fs])
        self.find_table.setMinimumHeight(260)
        lay.addWidget(self.find_table)
        if not fs:
            lay.addWidget(lbl("No findings yet. Test a control, or raise a finding directly.", "Muted"))
        lay.addLayout(hbox(button("New finding", lambda: (FindingDialog(self, {}).exec(), self.refresh()), "Primary"),
                           button("Edit selected", self.edit_finding), button("Close selected", self.close_finding),
                           stretch_end=True))
        lay.addWidget(lbl("A good finding states the condition, the criteria it breaches, the root cause, the "
                          "consequence and an owned, dated action.", "Small"))
        return w

    def _finding(self):
        fid = selected_data(self.find_table)
        return next((f for f in self.game.list_findings() if f["finding_id"] == fid), None)

    def edit_finding(self):
        f = self._finding()
        if not f:
            self.notify("Select a finding first.")
            return
        FindingDialog(self, f).exec()
        self.refresh()

    def close_finding(self):
        f = self._finding()
        if not f:
            self.notify("Select a finding first.")
            return
        f["status"] = "Closed"
        self.game.save_finding(f)
        self.notify(f"{f['finding_id']} closed.")
        self.refresh()

    # ------------------------------------------------------------ BIA
    def _bia_tab(self) -> QWidget:
        g = self.game
        w = QWidget()
        lay = vbox(spacing=12, margins=(14, 14, 14, 14))
        w.setLayout(lay)
        procs = g.list_processes()
        names = {p.pid: p.name for p in procs}
        self.bia_table = make_table(["Process", "Owner", "Tier", "Impact 4h/24h/72h/1wk", "MTPD", "RTO", "RPO",
                                     "Tested recovery", "Depends on", "Strategy"], 9)
        set_rows(self.bia_table, [(p.name, p.owner, criticality(p), "/".join(str(x) for x in p.impact_curve),
                                   f"{p.mtpd_hours:g}h", f"{p.rto_hours:g}h", f"{p.rpo_hours:g}h",
                                   "-" if p.capability_hours is None else f"{p.capability_hours:g}h",
                                   ", ".join(names.get(d, d) for d in p.dependencies), p.strategy) for p in procs],
                 data=[p.pid for p in procs])
        self.bia_table.setMinimumHeight(280)
        lay.addWidget(self.bia_table)
        lay.addLayout(hbox(button("Edit selected process", self.edit_process),
                           button("Run BIA review", self.review, "Primary"), stretch_end=True))
        self.bia_out = lbl("MTPD: the longest the business can survive without the process. RTO must be shorter "
                           "than MTPD, and every dependency must recover at least as fast as the process that "
                           "needs it.", "Small")
        lay.addWidget(self.bia_out)
        return w

    def edit_process(self):
        pid = selected_data(self.bia_table)
        if not pid:
            self.notify("Select a process first.")
            return
        p = next(x for x in self.game.list_processes() if x.pid == pid)
        if ProcessDialog(self, p).exec() == QDialog.Accepted:
            self.refresh()

    def review(self):
        res = self.game.bia_review()
        self.game.check_achievements()
        names = {p.pid: p.name for p in self.game.list_processes()}
        text = ("No inconsistencies found." if not res["issues"] else
                f"{len(res['issues'])} issue(s):\n" + "\n".join("• " + i for i in res["issues"]))
        if res["order"]:
            text += "\n\nRecovery order: " + " → ".join(names.get(x, x) for x in res["order"])
        self.bia_out.setText(text)
        self.bia_out.setObjectName("Body")


class FindingDialog(QDialog):
    def __init__(self, screen: AssuranceScreen, f: dict):
        super().__init__(screen)
        self.s = screen
        g = screen.game
        self.f = dict(f)
        self.setWindowTitle("Assurance finding")
        self.resize(640, 520)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.title_e = QLineEdit(f.get("title", ""))
        self.sev = QComboBox()
        self.sev.addItems(["Low", "Medium", "High", "Critical"])
        self.sev.setCurrentText(f.get("severity", "Medium"))
        self.ctrl = QComboBox()
        self.ctrl.addItem("(none)", "")
        for c in g.list_controls():
            self.ctrl.addItem(f"{c['control_id']} {c['name']}", c["control_id"])
        self.ctrl.setCurrentIndex(max(0, self.ctrl.findData(f.get("control_id", ""))))
        self.root = QPlainTextEdit(f.get("root_cause", ""))
        self.action = QPlainTextEdit(f.get("action", ""))
        for e in (self.root, self.action):
            e.setMaximumHeight(70)
        self.owner = QLineEdit(f.get("owner", ""))
        self.due = QSpinBox()
        self.due.setRange(g.period(), g.period() + 36)
        self.due.setValue(int(f.get("due_period", g.period() + 3)))
        self.due.setPrefix("Month ")
        self.status = QComboBox()
        self.status.addItems(["Open", "In progress", "Closed"])
        self.status.setCurrentText(f.get("status", "Open"))
        for k, wdg in (("Title", self.title_e), ("Severity", self.sev), ("Control", self.ctrl),
                       ("Root cause", self.root), ("Agreed action", self.action), ("Action owner", self.owner),
                       ("Due", self.due), ("Status", self.status)):
            form.addRow(k, wdg)
        lay.addLayout(form)
        self.err = lbl("", "Bad")
        lay.addWidget(self.err)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def save(self):
        g = self.s.game
        f = {"finding_id": self.f.get("finding_id") or g.next_finding_id(), "title": self.title_e.text().strip(),
             "severity": self.sev.currentText(), "control_id": self.ctrl.currentData(),
             "root_cause": self.root.toPlainText().strip(), "action": self.action.toPlainText().strip(),
             "owner": self.owner.text().strip(), "due_period": self.due.value(), "status": self.status.currentText()}
        if not f["action"] or not f["owner"]:
            self.err.setText("A finding needs an agreed action and an owner.")
            return
        try:
            g.save_finding(f)
        except ValueError as exc:
            self.err.setText(str(exc))
            return
        g.check_achievements()
        self.accept()


class ProcessDialog(QDialog):
    def __init__(self, screen: AssuranceScreen, p: Process):
        super().__init__(screen)
        self.s, self.p = screen, p
        self.setWindowTitle(f"Edit {p.name}")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.curve = []
        for t, v in zip(("4 hours", "24 hours", "72 hours", "1 week"), p.impact_curve):
            sp = QSpinBox()
            sp.setRange(0, 5)
            sp.setValue(v)
            form.addRow(f"Impact if down {t} (0-5)", sp)
            self.curve.append(sp)

        def hours(v):
            sp = QDoubleSpinBox()
            sp.setRange(0, 2000)
            sp.setSuffix(" h")
            sp.setValue(v)
            return sp

        self.mtpd, self.rto, self.rpo = hours(p.mtpd_hours), hours(p.rto_hours), hours(p.rpo_hours)
        form.addRow("MTPD", self.mtpd)
        form.addRow("RTO", self.rto)
        form.addRow("RPO", self.rpo)
        self.cap = hours(p.capability_hours or 0)
        self.cap.setSpecialValueText("Not tested")
        form.addRow("Tested recovery time", self.cap)
        self.strategy = QLineEdit(p.strategy)
        form.addRow("Continuity strategy", self.strategy)
        lay.addLayout(form)
        self.err = lbl("", "Bad")
        lay.addWidget(self.err)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def save(self):
        d = self.p.to_dict()
        d.update({"impact_curve": [s.value() for s in self.curve], "mtpd_hours": self.mtpd.value(),
                  "rto_hours": self.rto.value(), "rpo_hours": self.rpo.value(),
                  "capability_hours": self.cap.value() or None, "strategy": self.strategy.text().strip()})
        try:
            p = Process.from_dict(d)
        except ValueError as exc:
            self.err.setText(str(exc))
            return
        self.s.game.save_process(p)
        self.accept()
