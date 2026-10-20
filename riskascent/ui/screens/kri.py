"""KRI monitoring dashboard: status, trends, thresholds and escalation."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QLineEdit, QVBoxLayout)

from ...core.kri import KRI, STATUS_CRIT, STATUS_WARN
from ..base import Screen
from ..widgets import Card, Chart, Spark, badge, button, grid, hbox, lbl, vbox
from .. import theme


class KRIScreen(Screen):
    key = "kri"
    title = "KRI monitor"

    def __init__(self, win):
        super().__init__(win)
        self.selected: str | None = None

    def populate(self) -> None:
        g = self.game
        p = theme.current()
        lay = self.page.layout_
        kris = g.list_kris()
        crit = sum(1 for k in kris if k.status() == STATUS_CRIT)
        warn = sum(1 for k in kris if k.status() == STATUS_WARN)
        lay.addWidget(lbl("KEY RISK INDICATORS", "Eyebrow"))
        lay.addWidget(lbl(f"{len(kris)} indicators · {crit} critical · {warn} warning", "H1"))
        lay.addWidget(lbl("A KRI is an early warning. It is only useful if a breach triggers a defined action by a "
                          "named owner. Escalate real breaches; over-escalating normal readings costs credibility.",
                          "Muted"))
        lay.addLayout(hbox(button("New KRI", self.new, "Primary"), button("Add from library", self.from_library),
                           "stretch", button("Advance one month", self.advance, tip="Record next month's readings")))
        if self.selected not in {k.kri_id for k in kris}:
            self.selected = kris[0].kri_id if kris else None
        cards = []
        order = {STATUS_CRIT: 0, STATUS_WARN: 1}
        for k in sorted(kris, key=lambda k: (order.get(k.status(), 2), k.name)):
            st = k.status()
            col = theme.status_color(st)
            hist = [v for _, v in g.kri_history(k.kri_id)]
            c = Card(kind="CardAccent" if k.kri_id == self.selected else "Card")
            c.add(hbox(badge(st, col, filled=st != "Normal"), lbl(k.trend(), "Small", wrap=False), "stretch"))
            c.add(lbl(k.name, "H3"))
            c.add(lbl(f"{k.current:,.2f} {k.unit}".replace(".00 ", " "), "Value"))
            c.add(lbl(f"Warning {k.warning:g} · critical {k.critical:g} · "
                      f"{'higher' if k.higher_is_worse else 'lower'} is worse", "Small"))
            c.add(Spark(hist, k.warning, k.critical, col))
            c.add(hbox(button("Details", lambda kid=k.kri_id: self._select(kid), "Ghost"), stretch_end=True))
            cards.append(c)
        lay.addLayout(grid(cards, 4))
        if self.selected and not self.focus_mode:
            lay.addWidget(self._detail(next(k for k in kris if k.kri_id == self.selected)))

    def _select(self, kid: str) -> None:
        self.selected = kid
        self.refresh()

    def _detail(self, k: KRI) -> Card:
        g = self.game
        p = theme.current()
        c = Card(k.name, f"Owner {k.owner} · source {k.data_source} · {k.frequency.lower()} · "
                         f"linked risk {k.linked_risk or 'none'}")
        hist = g.kri_history(k.kri_id)
        ch = Chart(2.6)
        ax = ch.ax
        if hist:
            xs, ys = zip(*hist)
            ax.plot(xs, ys, marker="o", color=p.accent, label=k.name)
        ax.axhline(k.warning, color=p.warn, linestyle="--", linewidth=1, label="Warning")
        ax.axhline(k.critical, color=p.bad, linestyle="--", linewidth=1, label="Critical")
        ax.set_xlabel("Month")
        ax.set_ylabel(k.unit)
        ax.legend(fontsize=8)
        ch.draw()
        c.add(ch)
        c.add(lbl(f"Escalation when breached: {k.escalation or 'not defined'}", "Body"))
        c.add(lbl(f"Baseline {k.baseline:g}. Expected drift without action {k.drift * 100:+.1f}% per month.",
                  "Small"))
        c.add(hbox(button("Escalate to owner", lambda: self.act(k.kri_id, "escalate"), "Primary"),
                   button("Record as 'monitor'", lambda: self.act(k.kri_id, "monitor")),
                   button("Edit thresholds", lambda: self.edit(k)),
                   button("Delete KRI", lambda: self.delete(k), "Danger"), stretch_end=True))
        return c

    def act(self, kid: str, action: str) -> None:
        msg = self.game.escalate_kri(kid, action)
        self.game.check_achievements()
        self.notify(msg)
        self.win.update_chrome()
        self.refresh()

    def advance(self) -> None:
        events = self.game.advance_period("kri-monitor")
        self.game.check_achievements()
        breaches = [e for e in events if e["type"] == "kri_breach"]
        self.notify(f"Month {self.game.period()}: {len(events)} event(s), {len(breaches)} KRI breach(es).")
        self.win.update_chrome()
        self.refresh()

    def new(self) -> None:
        if KRIDialog(self, None).exec() == QDialog.Accepted:
            self.game.check_achievements()
            self.refresh()

    def edit(self, k: KRI) -> None:
        if KRIDialog(self, k).exec() == QDialog.Accepted:
            self.refresh()

    def delete(self, k: KRI) -> None:
        if self.dialogs.confirm(self, "Delete KRI", f"Delete '{k.name}' and its history?"):
            self.game.delete_kri(k.kri_id)
            self.refresh()

    def from_library(self) -> None:
        g = self.game
        have = {k.kri_id for k in g.list_kris()}
        options = [x for x in g.c.kri_library.values() if x["id"] not in have]
        if not options:
            self.notify("Every library KRI is already being monitored.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("KRI library")
        lay = QVBoxLayout(dlg)
        combo = QComboBox()
        for x in options:
            combo.addItem(f"{x['name']} ({x['unit']})", x["id"])
        lay.addWidget(lbl("Choose an indicator to start monitoring.", "Muted"))
        lay.addWidget(combo)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        lib = dict(g.c.kri_library[combo.currentData()])
        lib["kri_id"] = lib.pop("id")
        lib["owner"] = g.person(lib.pop("owner_role"))["name"]
        lib["history"] = []
        g.save_kri(KRI.from_dict(lib))
        g.check_achievements()
        self.selected = lib["kri_id"]
        self.refresh()


class KRIDialog(QDialog):
    def __init__(self, screen: KRIScreen, k: KRI | None):
        super().__init__(screen)
        self.s, self.k = screen, k
        g = screen.game
        self.setWindowTitle("Edit KRI" if k else "New KRI")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(k.name if k else "")
        self.unit = QLineEdit(k.unit if k else "%")

        def num(v):
            sp = QDoubleSpinBox()
            sp.setRange(-1e12, 1e12)
            sp.setDecimals(2)
            sp.setValue(v)
            return sp

        self.base = num(k.baseline if k else 0)
        self.cur = num(k.current if k else 0)
        self.warn = num(k.warning if k else 10)
        self.crit = num(k.critical if k else 20)
        self.hiw = QCheckBox("Higher values are worse")
        self.hiw.setChecked(k.higher_is_worse if k else True)
        self.owner = QLineEdit(k.owner if k else g.person("coo")["name"])
        self.esc = QLineEdit(k.escalation if k else "")
        self.esc.setPlaceholderText("What happens, and who acts, when it breaches")
        self.src = QLineEdit(k.data_source if k else "")
        self.risk = QComboBox()
        self.risk.addItem("(none)", "")
        for r in g.list_risks():
            self.risk.addItem(f"{r['risk_id']} {r['title']}", r.get("lib_id") or r["risk_id"])
        if k:
            self.risk.setCurrentIndex(max(0, self.risk.findData(k.linked_risk)))
        for label, w in (("Name", self.name), ("Unit", self.unit), ("Baseline", self.base), ("Current", self.cur),
                         ("Warning threshold", self.warn), ("Critical threshold", self.crit), ("", self.hiw),
                         ("Owner", self.owner), ("Escalation action", self.esc), ("Data source", self.src),
                         ("Linked risk", self.risk)):
            form.addRow(label, w)
        lay.addLayout(form)
        self.err = lbl("", "Bad")
        lay.addWidget(self.err)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def save(self):
        g = self.s.game
        d = self.k.to_dict() if self.k else {"kri_id": f"KRI-U{len(g.list_kris()) + 1:02d}", "history": [],
                                               "drift": 0.0, "volatility": 0.05, "frequency": "Monthly"}
        d.update({"name": self.name.text().strip(), "unit": self.unit.text().strip(), "baseline": self.base.value(),
                  "current": self.cur.value(), "warning": self.warn.value(), "critical": self.crit.value(),
                  "higher_is_worse": self.hiw.isChecked(), "owner": self.owner.text().strip(),
                  "escalation": self.esc.text().strip(), "data_source": self.src.text().strip(),
                  "linked_risk": self.risk.currentData()})
        if not d["escalation"]:
            self.err.setText("Define the escalation action: a KRI without one is just a number.")
            return
        try:
            k = KRI.from_dict(d)
            g.save_kri(k)
        except ValueError as exc:
            self.err.setText(str(exc))
            return
        self.s.selected = k.kri_id
        self.accept()
