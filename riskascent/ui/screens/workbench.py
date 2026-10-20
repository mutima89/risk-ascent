"""Risk assessment workbench: rate a risk from estimates, apply controls,
check appetite and rating fragility; view heat maps; configure the matrix and
appetite statement."""

from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QGridLayout, QSpinBox, QTableWidgetItem, QTabWidget,
                               QWidget)

from ...core.finance import expected_loss
from ...core.risk_engine import (CONTROL_EFFECTIVENESS, CONTROL_TYPES, LIMITATIONS, RISK_CATEGORIES, Appetite,
                                 ControlRating, RiskMatrix, heatmap_counts, sensitivity_of_rating,
                                 suggested_residual)
from ..base import Screen
from ..widgets import Card, HeatMap, button, grid, hbox, lbl, make_table, set_rows, vbox
from .. import theme


class WorkbenchScreen(Screen):
    key = "workbench"
    title = "Assessment workbench"

    def __init__(self, win):
        super().__init__(win)
        self.tab_index = 0

    def populate(self) -> None:
        lay = self.page.layout_
        lay.addWidget(lbl("RISK ASSESSMENT WORKBENCH", "Eyebrow"))
        lay.addWidget(lbl("Rate, challenge and calibrate", "H1"))
        self.tabs = QTabWidget()
        self.tabs.addTab(self._rate_tab(), "Rate a risk")
        self.tabs.addTab(self._heat_tab(), "Heat maps")
        self.tabs.addTab(self._config_tab(), "Matrix and appetite")
        self.tabs.setCurrentIndex(self.tab_index)
        self.tabs.currentChanged.connect(lambda i: setattr(self, "tab_index", i))
        lay.addWidget(self.tabs)
        lay.addWidget(lbl(LIMITATIONS, "Small"))

    # ---------------------------------------------------------- rate tab
    def _rate_tab(self) -> QWidget:
        g = self.game
        w = QWidget()
        lay = vbox(spacing=12, margins=(14, 14, 14, 14))
        w.setLayout(lay)
        cur = g.org["currency"]
        self.risk_combo = QComboBox()
        self.risk_combo.addItem("Free-form estimate (not linked)", None)
        for r in g.list_risks():
            self.risk_combo.addItem(f"{r['risk_id']}  {r['title']}", r["risk_id"])
        self.risk_combo.currentIndexChanged.connect(self._risk_selected)
        self.cat = QComboBox()
        self.cat.addItems(RISK_CATEGORIES)
        self.prob = QDoubleSpinBox()
        self.prob.setRange(0, 100)
        self.prob.setDecimals(1)
        self.prob.setSuffix(" % per year")
        self.prob.setValue(30)
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1e12)
        self.amount.setDecimals(0)
        self.amount.setSingleStep(10000)
        self.amount.setPrefix(cur + " ")
        self.amount.setGroupSeparatorShown(True)
        self.amount.setValue(500000 * g.org["money_scale"])
        form = QGridLayout()
        form.addWidget(lbl("Register risk", "Small"), 0, 0)
        form.addWidget(self.risk_combo, 1, 0, 1, 2)
        form.addWidget(lbl("Category", "Small"), 0, 2)
        form.addWidget(self.cat, 1, 2)
        form.addWidget(lbl("Annual probability of the event", "Small"), 2, 0)
        form.addWidget(self.prob, 3, 0)
        form.addWidget(lbl("Impact if it happens (realistic severe case)", "Small"), 2, 1)
        form.addWidget(self.amount, 3, 1)
        lay.addLayout(form)
        self.controls = []
        cl = QGridLayout()
        cl.addWidget(lbl("Controls (the strongest in each family counts; weak controls do not stack)", "Small"),
                     0, 0, 1, 3)
        for i in range(3):
            t = QComboBox()
            t.addItem("(none)", None)
            for ct in CONTROL_TYPES:
                t.addItem(ct, ct)
            e = QComboBox()
            for n, l in enumerate(CONTROL_EFFECTIVENESS):
                e.addItem(f"{n} - {l}", n)
            e.setCurrentIndex(2)
            cl.addWidget(lbl(f"Control {i + 1}", wrap=False), i + 1, 0)
            cl.addWidget(t, i + 1, 1)
            cl.addWidget(e, i + 1, 2)
            self.controls.append((t, e))
        lay.addLayout(cl)
        lay.addLayout(hbox(button("Assess", self.assess, "Primary"), button("Apply ratings to register risk",
                                                                            self.apply), stretch_end=True))
        self.result_lbl = lbl("", "Body")
        self.heat = HeatMap()
        self.heat.setMinimumHeight(280)
        res_card = Card("Result")
        res_card.add(self.result_lbl, "stretch")
        lay.addLayout(grid([res_card, Card("Inherent (solid) → residual (dashed)").add(self.heat)], 2))
        self.assess(False)
        return w

    def _risk_selected(self, *_):
        rid = self.risk_combo.currentData()
        if not rid:
            return
        g = self.game
        r = g.get_risk(rid)
        m = g.matrix()
        self.cat.setCurrentText(r["category"])
        self.prob.setValue(m.midpoint_probability(r["inh_l"]) * 100)
        self.amount.setValue(m.midpoint_impact(r["inh_i"], g.org["money_scale"]))
        self.assess(False)

    def _inputs(self):
        g = self.game
        m = g.matrix()
        p = self.prob.value() / 100
        a = self.amount.value()
        l = m.likelihood_from_probability(p)
        i = m.impact_from_amount(a, g.org["money_scale"])
        ctrls = [ControlRating(t.currentData(), e.currentData()) for t, e in self.controls if t.currentData()]
        rl, ri = suggested_residual(l, i, ctrls)
        return m, p, a, l, i, rl, ri, ctrls

    def assess(self, count: bool = True) -> None:
        g = self.game
        m, p, a, l, i, rl, ri, ctrls = self._inputs()
        s, b = m.rate(l, i)
        rs, rb = m.rate(rl, ri)
        sens = sensitivity_of_rating(m, p, a, 0.25, g.org["money_scale"])
        el = expected_loss(p, a)
        st = g.appetite().status(self.cat.currentText(), rs)
        ap, tol = g.appetite().thresholds(self.cat.currentText())
        lines = [f"Inherent: likelihood {l} ({m.likelihood_labels[l - 1]}) × impact {i} "
                 f"({m.impact_labels[i - 1]}) = {s}, {b}.",
                 f"Residual after controls: {rl} × {ri} = {rs}, {rb}.",
                 f"Appetite for {self.cat.currentText()}: up to {ap}; tolerance {tol}. Status: {st}.",
                 f"Expected annual loss (p × impact, inherent): {g.money(el, False)}."]
        if sens["fragile"]:
            lines.append("⚠ Fragile rating: a ±25% change in your estimates moves this risk into a different "
                         "band. Gather better evidence before relying on it.")
        else:
            lines.append("Robust rating: ±25% estimate changes stay in the same band.")
        if not ctrls:
            lines.append("No controls entered, so residual equals inherent.")
        self.result_lbl.setText("\n".join(lines))
        self.heat.set_data(m, None, (l, i), (rl, ri))
        if count:
            g.count("el_calcs")

    def apply(self) -> None:
        rid = self.risk_combo.currentData()
        if not rid:
            self.notify("Choose a register risk to apply ratings to.")
            return
        g = self.game
        m, p, a, l, i, rl, ri, ctrls = self._inputs()
        r = g.get_risk(rid)
        r.update({"inh_l": l, "inh_i": i, "res_l": rl, "res_i": ri,
                  "control_eff": max([c.effectiveness for c in ctrls], default=0)})
        r["notes"] = (r.get("notes") or "") + (f"\n[M{g.period()}] Re-assessed in workbench: p={p:.0%}, "
                                               f"impact {g.money(a)}.")
        try:
            g.save_risk(r)
        except ValueError as exc:
            self.fail(exc)
            return
        g.check_achievements()
        self.notify(f"{rid} updated: inherent {l}×{i}, residual {rl}×{ri}.")

    # ---------------------------------------------------------- heat tab
    def _heat_tab(self) -> QWidget:
        g = self.game
        w = QWidget()
        lay = vbox(spacing=12, margins=(14, 14, 14, 14))
        w.setLayout(lay)
        m = g.matrix()
        risks = g.list_risks()
        cards = []
        for residual, title in ((False, "Inherent risk"), (True, "Residual risk")):
            hm = HeatMap()
            hm.set_data(m, heatmap_counts(risks, m.size, residual))
            hm.setMinimumHeight(300)
            hm.cell_clicked.connect(lambda l, i, r=residual: self._cell(l, i, r))
            cards.append(Card(title).add(hm))
        lay.addLayout(grid(cards, 2))
        moved = sum(1 for r in risks if (r["res_l"], r["res_i"]) != (r["inh_l"], r["inh_i"]))
        lay.addWidget(lbl(f"{moved} of {len(risks)} risks have a lower residual than inherent rating. Click a "
                          "residual cell to open those risks in the register.", "Small"))
        return w

    def _cell(self, l, i, residual):
        if l and residual:
            self.win.go("register", cell=(l, i))

    # ---------------------------------------------------------- config tab
    def _config_tab(self) -> QWidget:
        g = self.game
        w = QWidget()
        lay = vbox(spacing=12, margins=(14, 14, 14, 14))
        w.setLayout(lay)
        m = g.matrix()
        mc = Card("Risk matrix", "Changing the matrix size re-expresses all register ratings on the new scale.")
        self.size_combo = QComboBox()
        for s in (3, 4, 5):
            self.size_combo.addItem(f"{s} × {s}", s)
        self.size_combo.setCurrentIndex(self.size_combo.findData(m.size))
        mc.add(hbox(lbl("Size", wrap=False), self.size_combo, button("Apply matrix", self.save_matrix), "stretch"))
        t = make_table(["Rating", "Likelihood", "Annual probability", "Impact", "Financial range"], 4)
        scale = g.org["money_scale"]
        rows = []
        for n in range(m.size):
            lo, hi = m.likelihood_ranges[n]
            ilo, ihi = m.impact_ranges[n]
            rows.append((n + 1, m.likelihood_labels[n], f"{lo:.0%} to {hi:.0%}", m.impact_labels[n],
                         f"{g.money(ilo * scale)} to {g.money(ihi * scale)}"))
        set_rows(t, rows)
        t.setMinimumHeight(200)
        mc.add(t)
        mc.add(lbl("Bands on L×I score: " + ", ".join(f"{n} ≤ {u}" for n, u in m.bands), "Small"))
        ac = Card("Risk appetite statement", "Appetite: the level of risk the organisation is willing to take. "
                  "Tolerance: the most it will accept before mandatory action.")
        a = g.appetite()
        self.app_spin = QSpinBox()
        self.tol_spin = QSpinBox()
        for sp, v in ((self.app_spin, a.default_appetite), (self.tol_spin, a.default_tolerance)):
            sp.setRange(1, m.size * m.size)
            sp.setValue(v)
        ac.add(hbox(lbl("Default appetite ≤", wrap=False), self.app_spin, lbl("tolerance ≤", wrap=False),
                    self.tol_spin, "stretch"))
        self.cat_table = make_table(["Category", "Appetite", "Tolerance"], 0, select_rows=False)
        self.cat_table.setRowCount(len(RISK_CATEGORIES))
        self.cat_spins = {}
        for r, c in enumerate(RISK_CATEGORIES):
            self.cat_table.setItem(r, 0, QTableWidgetItem(c))
            ap, tol = a.by_category.get(c, (0, 0))
            s1, s2 = QSpinBox(), QSpinBox()
            for sp, v in ((s1, ap), (s2, tol)):
                sp.setRange(0, m.size * m.size)
                sp.setSpecialValueText("default")
                sp.setValue(v)
            self.cat_table.setCellWidget(r, 1, s1)
            self.cat_table.setCellWidget(r, 2, s2)
            self.cat_spins[c] = (s1, s2)
        self.cat_table.setMinimumHeight(300)
        ac.add(lbl("Category overrides (0 = use default). Safety and compliance usually have a lower appetite.",
                   "Small"), self.cat_table, hbox(button("Save appetite", self.save_appetite, "Primary"),
                                                   stretch_end=True))
        lay.addLayout(grid([mc, ac], 2))
        return w

    def save_matrix(self) -> None:
        size = self.size_combo.currentData()
        if size == self.game.matrix().size:
            self.notify("The matrix is already that size.")
            return
        if not self.dialogs.confirm(self, "Change matrix", f"Switch to a {size}×{size} matrix? Existing "
                                    "ratings will be re-expressed on the new scale. A backup is taken first."):
            return
        self.game.backup("pre-matrix")
        self.game.set_matrix(RiskMatrix.sized(size))
        a = self.game.appetite()
        mx = size * size
        a.default_appetite = min(a.default_appetite, mx - 2)
        a.default_tolerance = min(max(a.default_tolerance, a.default_appetite + 1), mx)
        a.by_category = {k: (min(v[0], mx - 1), min(v[1], mx)) for k, v in a.by_category.items() if v[0] < v[1]}
        try:
            self.game.set_appetite(a)
        except ValueError:
            pass
        self.game.check_achievements()
        self.notify(f"Matrix changed to {size}×{size}.")
        self.refresh()

    def save_appetite(self) -> None:
        by_cat = {}
        for c, (s1, s2) in self.cat_spins.items():
            if s1.value() or s2.value():
                if not (s1.value() and s2.value()) or s1.value() >= s2.value():
                    self.fail(f"{c}: set both appetite and tolerance, with appetite below tolerance.")
                    return
                by_cat[c] = (s1.value(), s2.value())
        try:
            self.game.set_appetite(Appetite(self.app_spin.value(), self.tol_spin.value(), by_cat))
        except ValueError as exc:
            self.fail(exc)
            return
        self.game.check_achievements()
        self.notify("Appetite statement saved. The register's appetite status now uses it.")
        self.refresh()
