"""Financial modelling lab: expected loss and scenarios, Monte Carlo,
cost-benefit / ROI, sensitivity (tornado), liquidity stress test and
contingency reserve. All calculations run locally with seeded randomness."""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QSpinBox, QTabWidget, QWidget)

from ...core.finance import (StressInputs, contingency_reserve, cost_benefit, expected_loss,
                             monte_carlo_annual_loss, scenario_weighted_loss, stress_test, tornado)
from ..base import Screen
from ..widgets import Card, Chart, Tile, button, grid, hbox, lbl, make_table, set_rows, vbox
from .. import theme


def money_spin(cur: str, value: float = 0, maximum: float = 1e12) -> QDoubleSpinBox:
    sp = QDoubleSpinBox()
    sp.setRange(0, maximum)
    sp.setDecimals(0)
    sp.setGroupSeparatorShown(True)
    sp.setPrefix(cur + " ")
    sp.setSingleStep(10000)
    sp.setValue(value)
    sp.setMinimumWidth(170)
    return sp


def pct_spin(value: float, lo: float = 0, hi: float = 100, dec: int = 1) -> QDoubleSpinBox:
    sp = QDoubleSpinBox()
    sp.setRange(lo, hi)
    sp.setDecimals(dec)
    sp.setSuffix(" %")
    sp.setValue(value)
    return sp


def form_grid(rows: list[tuple[str, QWidget]], cols: int = 3) -> QGridLayout:
    g = QGridLayout()
    g.setHorizontalSpacing(14)
    g.setVerticalSpacing(4)
    for k, (label, w) in enumerate(rows):
        r, c = divmod(k, cols)
        g.addWidget(lbl(label, "Small"), r * 2, c)
        g.addWidget(w, r * 2 + 1, c)
    return g


class FinanceScreen(Screen):
    key = "finance"
    title = "Financial modelling lab"

    def __init__(self, win):
        super().__init__(win)
        self.built_for = None
        self.tab_index = 0

    def refresh(self) -> None:
        # Keep the player's inputs while the same career is open.
        key = (id(self.win.game), self.win.settings.theme, self.win.settings.high_contrast,
               self.win.settings.text_scale)
        if self.built_for == key:
            return
        self.built_for = key
        super().refresh()

    def populate(self) -> None:
        g = self.game
        self.cur = g.org["currency"]
        self.scale = g.org["money_scale"]
        lay = self.page.layout_
        lay.addWidget(lbl("FINANCIAL MODELLING LAB", "Eyebrow"))
        lay.addWidget(lbl("Put numbers on risk", "H1"))
        lay.addWidget(lbl("Every result explains its assumptions. Simulations are seeded, so the same inputs "
                          "and seed always give the same answer.", "Muted"))
        self.tabs = QTabWidget()
        self.tabs.addTab(self._el_tab(), "Expected loss and scenarios")
        self.tabs.addTab(self._mc_tab(), "Monte Carlo")
        self.tabs.addTab(self._cba_tab(), "Cost-benefit and ROI")
        self.tabs.addTab(self._tornado_tab(), "Sensitivity")
        self.tabs.addTab(self._stress_tab(), "Stress test")
        self.tabs.setCurrentIndex(self.tab_index)
        self.tabs.currentChanged.connect(lambda i: setattr(self, "tab_index", i))
        lay.addWidget(self.tabs)

    def m(self, v: float) -> str:
        return self.game.money(v, False)

    # ------------------------------------------------------------ EL
    def _el_tab(self) -> QWidget:
        w = QWidget()
        lay = vbox(spacing=12, margins=(14, 14, 14, 14))
        w.setLayout(lay)
        self.el_p = pct_spin(10)
        self.el_i = money_spin(self.cur, 2_000_000 * self.scale)
        lay.addLayout(form_grid([("Annual probability", self.el_p), ("Impact if it occurs", self.el_i)]))
        self.el_out = lbl("", "H3")
        lay.addLayout(hbox(button("Calculate expected loss", self.calc_el, "Primary"), self.el_out, "stretch"))
        lay.addWidget(lbl("Expected loss = probability × impact. It is the long-run average, not what will "
                          "happen: in most years the loss is zero and in a bad year it is the full impact.", "Small"))
        lay.addWidget(lbl("Scenario analysis", "H3"))
        lay.addWidget(lbl("Mutually exclusive outcomes for one event. Probabilities must sum to 100% or less; the "
                          "remainder is 'no loss'.", "Small"))
        self.scen = []
        sg = QGridLayout()
        defaults = [("Minor disruption", 20, 150_000), ("Major outage", 6, 1_800_000), ("Catastrophic", 1, 12_000_000),
                    ("", 0, 0), ("", 0, 0)]
        sg.addWidget(lbl("Scenario", "Small"), 0, 0)
        sg.addWidget(lbl("Probability", "Small"), 0, 1)
        sg.addWidget(lbl("Loss", "Small"), 0, 2)
        from PySide6.QtWidgets import QLineEdit
        for r, (name, p, loss) in enumerate(defaults, start=1):
            ne = QLineEdit(name)
            ps = pct_spin(p)
            ls = money_spin(self.cur, loss * self.scale)
            sg.addWidget(ne, r, 0)
            sg.addWidget(ps, r, 1)
            sg.addWidget(ls, r, 2)
            self.scen.append((ne, ps, ls))
        lay.addLayout(sg)
        self.scen_out = lbl("", "Body")
        lay.addLayout(hbox(button("Weight scenarios", self.calc_scen, "Primary"), stretch_end=True))
        lay.addWidget(self.scen_out)
        return w

    def calc_el(self):
        el = expected_loss(self.el_p.value() / 100, self.el_i.value())
        self.el_out.setText(f"Expected annual loss: {self.m(el)}")
        self.game.count("el_calcs")
        self.game.check_achievements()

    def calc_scen(self):
        rows = [(p.value() / 100, l.value()) for n, p, l in self.scen if p.value() > 0]
        try:
            res = scenario_weighted_loss(rows)
        except ValueError as exc:
            self.fail(exc)
            return
        self.scen_out.setText(f"Probability-weighted loss: {self.m(res['expected_loss'])}\nWorst credible case: "
                              f"{self.m(res['worst_case'])}\nProbability of no loss: {res['p_no_loss'] * 100:.1f}%\n"
                              "The worst case can be many times the weighted loss; appetite decisions should look "
                              "at both.")
        self.game.count("scenario_runs")

    # ------------------------------------------------------------ Monte Carlo
    def _mc_tab(self) -> QWidget:
        w = QWidget()
        lay = vbox(spacing=12, margins=(14, 14, 14, 14))
        w.setLayout(lay)
        self.mc_f = QDoubleSpinBox()
        self.mc_f.setRange(0, 200)
        self.mc_f.setDecimals(2)
        self.mc_f.setValue(1.5)
        self.mc_med = money_spin(self.cur, 120_000 * self.scale)
        self.mc_p90 = money_spin(self.cur, 900_000 * self.scale)
        self.mc_cap = money_spin(self.cur, 0)
        self.mc_cap.setSpecialValueText("No cap")
        self.mc_n = QSpinBox()
        self.mc_n.setRange(1000, 200_000)
        self.mc_n.setSingleStep(5000)
        self.mc_n.setValue(20000)
        self.mc_seed = QSpinBox()
        self.mc_seed.setRange(1, 2_000_000_000)
        self.mc_seed.setValue(42)
        self.mc_conf = pct_spin(90, 50, 99.9)
        self.mc_thr = money_spin(self.cur, 2_000_000 * self.scale)
        lay.addLayout(form_grid([("Events per year (Poisson frequency)", self.mc_f),
                                 ("Severity per event: median", self.mc_med),
                                 ("Severity per event: 90th percentile", self.mc_p90),
                                 ("Severity cap (e.g. insurance limit)", self.mc_cap),
                                 ("Simulated years", self.mc_n), ("Random seed", self.mc_seed),
                                 ("Reserve confidence", self.mc_conf), ("Loss threshold to test", self.mc_thr)], 4))
        lay.addLayout(hbox(button("Run simulation", self.run_mc, "Primary"), stretch_end=True))
        self.mc_tiles = [Tile("Mean annual loss"), Tile("Median"), Tile("90th percentile"), Tile("99th percentile"),
                         Tile("Expected shortfall 95%"), Tile("Reserve at confidence")]
        lay.addLayout(grid(self.mc_tiles, 6))
        self.mc_chart = Chart(3.2)
        lay.addWidget(self.mc_chart)
        self.mc_out = lbl("Severity is lognormal fitted to your median and 90th percentile; frequency is Poisson. "
                          "Use the 90th percentile for 'a bad year', not the maximum.", "Small")
        lay.addWidget(self.mc_out)
        return w

    def run_mc(self):
        try:
            res = monte_carlo_annual_loss(self.mc_f.value(), self.mc_med.value(), self.mc_p90.value(),
                                          self.mc_n.value(), self.mc_seed.value(),
                                          self.mc_cap.value() or None)
        except ValueError as exc:
            self.fail(f"{exc}. The 90th percentile must be larger than the median.")
            return
        self.last_mc = res
        rv = contingency_reserve(res, self.mc_conf.value() / 100)
        p = theme.current()
        for t, (v, sub) in zip(self.mc_tiles, [(res.mean, "budget for this"), (res.median, "typical year"),
                                               (res.p90, "1-in-10 bad year"), (res.p99, "1-in-100 year"),
                                               (res.expected_shortfall_95, "average of worst 5%"),
                                               (rv["reserve"], f"unexpected part {self.game.money(rv['unexpected_loss'])}")]):
            t.set(self.game.money(v), sub)
        ax = self.mc_chart.reset()
        losses = res.losses
        pos = losses[losses > 0]
        if pos.size:
            hi = np.percentile(pos, 99.5)
            ax.hist(np.minimum(pos, hi), bins=60, color=p.accent, alpha=0.85)
            for v, c, name in ((res.mean, p.gold, "mean"), (res.p90, p.warn, "P90"), (res.p99, p.bad, "P99")):
                ax.axvline(v, color=c, linestyle="--", linewidth=1.4, label=f"{name} {self.game.money(v)}")
            ax.legend(fontsize=8)
        ax.set_title(f"Simulated annual losses ({res.n:,} years; {100 * (1 - res.prob_any_loss):.0f}% had no loss)",
                     fontsize=9)
        ax.set_xlabel(f"Annual loss ({self.cur})")
        ax.xaxis.set_major_formatter(_money_fmt(self.cur))
        self.mc_chart.draw()
        pe = res.prob_exceeding(self.mc_thr.value())
        self.mc_out.setText(f"Probability that annual losses exceed {self.m(self.mc_thr.value())}: {pe * 100:.1f}%. "
                            f"Seed {res.seed}. Holding a reserve at the {self.mc_conf.value():.0f}% level covers losses "
                            f"in about {self.mc_conf.value():.0f} of 100 years; the expected loss is usually budgeted, "
                            "and only the unexpected part reserved.")
        self.game.count("mc_runs")
        self.game.check_achievements()

    # ------------------------------------------------------------ CBA
    def _cba_tab(self) -> QWidget:
        g = self.game
        w = QWidget()
        lay = vbox(spacing=12, margins=(14, 14, 14, 14))
        w.setLayout(lay)
        self.cba_risk = QComboBox()
        for r in g.list_risks():
            self.cba_risk.addItem(f"{r['risk_id']} {r['title']}", r["risk_id"])
        self.cba_title = None
        from PySide6.QtWidgets import QLineEdit
        self.cba_title = QLineEdit("Risk treatment")
        self.cba_before = money_spin(self.cur, 600_000 * self.scale)
        self.cba_after = money_spin(self.cur, 150_000 * self.scale)
        self.cba_up = money_spin(self.cur, 400_000 * self.scale)
        self.cba_ann = money_spin(self.cur, 60_000 * self.scale)
        self.cba_years = QSpinBox()
        self.cba_years.setRange(1, 15)
        self.cba_years.setValue(3)
        self.cba_rate = pct_spin(8, 0, 30)
        lay.addLayout(form_grid([("Linked risk", self.cba_risk), ("Proposal title", self.cba_title),
                                 ("Expected annual loss before", self.cba_before),
                                 ("Expected annual loss after", self.cba_after), ("Upfront cost", self.cba_up),
                                 ("Annual running cost", self.cba_ann), ("Horizon (years)", self.cba_years),
                                 ("Discount rate", self.cba_rate)], 4))
        lay.addLayout(hbox(button("Evaluate", self.run_cba, "Primary"),
                           button("Send to budget as proposal", self.to_budget),
                           button("Create investment proposal report", self.to_report), stretch_end=True))
        self.cba_tiles = [Tile("Annual risk reduction"), Tile("NPV"), Tile("ROI (undiscounted)"), Tile("Payback"),
                          Tile("Benefit / cost")]
        lay.addLayout(grid(self.cba_tiles, 5))
        self.cba_chart = Chart(2.6)
        lay.addWidget(self.cba_chart)
        self.cba_out = lbl("Benefit = avoided expected loss. A positive NPV means the treatment pays for itself on "
                           "average; safety, legal and reputational benefits may justify it even when it does not.",
                           "Small")
        lay.addWidget(self.cba_out)
        return w

    def cba_inputs(self) -> dict:
        return {"el_before": self.cba_before.value(), "el_after": self.cba_after.value(),
                "upfront": self.cba_up.value(), "annual": self.cba_ann.value(), "years": self.cba_years.value(),
                "rate": self.cba_rate.value() / 100}

    def run_cba(self) -> dict | None:
        i = self.cba_inputs()
        if i["el_after"] > i["el_before"]:
            self.fail("Expected loss after treatment cannot exceed the loss before it.")
            return None
        try:
            cb = cost_benefit(i["el_before"], i["el_after"], i["upfront"], i["annual"], i["years"], i["rate"])
        except ValueError as exc:
            self.fail(exc)
            return None
        p = theme.current()
        self.cba_tiles[0].set(self.game.money(cb.annual_risk_reduction), "per year")
        self.cba_tiles[1].set(self.game.money(cb.npv), f"at {i['rate'] * 100:.1f}%", p.good if cb.npv > 0 else p.bad)
        self.cba_tiles[2].set("n/a" if cb.total_cost == 0 else f"{cb.roi * 100:.0f}%", f"over {i['years']} years")
        self.cba_tiles[3].set("never" if cb.payback_years is None else f"{cb.payback_years:.1f} yrs", "simple payback")
        self.cba_tiles[4].set("n/a" if cb.total_cost == 0 else f"{cb.benefit_cost_ratio:.2f}", "benefit ÷ cost")
        ax = self.cba_chart.reset()
        flows = [-i["upfront"]] + [cb.annual_risk_reduction - i["annual"]] * i["years"]
        cum = np.cumsum(flows)
        ax.bar(range(len(flows)), flows, color=[p.bad if f < 0 else p.good for f in flows], alpha=0.8, label="Net cash flow")
        ax.plot(range(len(flows)), cum, color=p.gold, marker="o", label="Cumulative")
        ax.axhline(0, color=p.muted, linewidth=0.8)
        ax.set_xticks(range(len(flows)))
        ax.set_xticklabels(["Now"] + [f"Y{k}" for k in range(1, len(flows))])
        ax.yaxis.set_major_formatter(_money_fmt(self.cur))
        ax.legend(fontsize=8)
        self.cba_chart.draw()
        self.last_cba = {**i, "npv": cb.npv, "roi": cb.roi, "payback": cb.payback_years,
                         "risk_id": self.cba_risk.currentData(), "title": self.cba_title.text().strip() or "Risk treatment"}
        self.game.count("cba_runs")
        self.game.check_achievements()
        return self.last_cba

    def to_budget(self):
        d = self.run_cba()
        if d:
            self.win.handoff["investment"] = d
            self.win.go("budget")

    def to_report(self):
        d = self.run_cba()
        if d:
            self.win.handoff["investment"] = d
            self.win.go("reports", kind="investment_proposal")

    # ------------------------------------------------------------ tornado
    def _tornado_tab(self) -> QWidget:
        w = QWidget()
        lay = vbox(spacing=12, margins=(14, 14, 14, 14))
        w.setLayout(lay)
        lay.addWidget(lbl("Which assumption matters most to the cost-benefit case? Each input is moved to its low "
                          "and high value while the others stay at the values on the Cost-benefit tab.", "Muted"))
        self.tor_pct = pct_spin(30, 5, 90, 0)
        lay.addLayout(hbox(lbl("Vary each input by ±", wrap=False), self.tor_pct,
                           button("Run sensitivity", self.run_tornado, "Primary"), stretch_end=True))
        self.tor_chart = Chart(3.0)
        lay.addWidget(self.tor_chart)
        self.tor_out = lbl("", "Body")
        lay.addWidget(self.tor_out)
        return w

    def run_tornado(self):
        base = self.cba_inputs()
        k = self.tor_pct.value() / 100

        def model(x):
            after = min(x["el_after"], x["el_before"])
            return cost_benefit(x["el_before"], after, x["upfront"], x["annual"], int(x["years"]), x["rate"]).npv

        names = {"el_before": "Loss before", "el_after": "Loss after", "upfront": "Upfront cost",
                 "annual": "Running cost", "rate": "Discount rate"}
        ranges = {n: (base[n] * (1 - k), base[n] * (1 + k)) for n in names}
        rows = tornado(model, base, ranges)
        p = theme.current()
        ax = self.tor_chart.reset()
        b = rows[0]["base"]
        for y, r in enumerate(reversed(rows)):
            lo, hi = sorted((r["low"], r["high"]))
            ax.barh(y, hi - lo, left=lo, color=p.accent, alpha=0.85)
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels([names[r["parameter"]] for r in reversed(rows)])
        ax.axvline(b, color=p.gold, linestyle="--", linewidth=1.2)
        ax.xaxis.set_major_formatter(_money_fmt(self.cur))
        ax.set_title(f"NPV range (base {self.game.money(b)})", fontsize=9)
        self.tor_chart.draw()
        top = rows[0]
        flips = [names[r["parameter"]] for r in rows if (r["low"] > 0) != (r["high"] > 0)]
        self.tor_out.setText(f"Most sensitive: {names[top['parameter']]} (NPV swing {self.m(top['swing'])}). "
                             + (f"The decision flips sign within the range for: {', '.join(flips)}. Get better evidence "
                                "on these before committing." if flips else
                                "The decision does not flip within these ranges: it is robust to these assumptions."))
        self.game.count("tornado_runs")
        self.game.check_achievements()

    # ------------------------------------------------------------ stress
    def _stress_tab(self) -> QWidget:
        g = self.game
        w = QWidget()
        lay = vbox(spacing=12, margins=(14, 14, 14, 14))
        w.setLayout(lay)
        m = g.metrics()
        self.st_rev = money_spin(self.cur, m.get("revenue", 0) / 12)
        self.st_cost = money_spin(self.cur, m.get("operating_costs", 0) / 12)
        self.st_cash = money_spin(self.cur, max(0, m.get("cash", 0)))
        self.st_fac = money_spin(self.cur, m.get("cash", 0) * 0.5)
        self.st_debt = money_spin(self.cur, m.get("revenue", 0) * 0.004)
        self.st_cov = money_spin(self.cur, m.get("cash", 0) * 0.25)
        self.st_rs = pct_spin(25, 0, 100, 0)
        self.st_cs = pct_spin(5, 0, 200, 0)
        self.st_fw = QCheckBox("Committed facility withdrawn")
        lay.addLayout(form_grid([("Monthly revenue", self.st_rev), ("Monthly operating costs", self.st_cost),
                                 ("Cash today", self.st_cash), ("Committed facility", self.st_fac),
                                 ("Monthly debt service", self.st_debt), ("Minimum cash covenant", self.st_cov),
                                 ("Revenue shock", self.st_rs), ("Cost shock", self.st_cs)], 4))
        lay.addWidget(self.st_fw)
        lay.addLayout(hbox(button("Run 12-month stress test", self.run_stress, "Primary"), stretch_end=True))
        self.st_chart = Chart(2.8)
        lay.addWidget(self.st_chart)
        self.st_out = lbl("Defaults come from the organisation's current figures.", "Small")
        lay.addWidget(self.st_out)
        return w

    def run_stress(self):
        inp = StressInputs(self.st_rev.value(), self.st_cost.value(), self.st_cash.value(), self.st_fac.value(),
                           self.st_debt.value(), self.st_cov.value())
        try:
            res = stress_test(inp, self.st_rs.value() / 100, self.st_cs.value() / 100, self.st_fw.isChecked())
        except ValueError as exc:
            self.fail(exc)
            return
        p = theme.current()
        ax = self.st_chart.reset()
        months = list(range(1, 13))
        ax.plot(months, res["cash_path"], color=p.accent, marker="o", label="Cash")
        ax.axhline(inp.min_cash_covenant, color=p.warn, linestyle="--", label="Covenant minimum")
        ax.axhline(0, color=p.bad, linewidth=1)
        ax.yaxis.set_major_formatter(_money_fmt(self.cur))
        ax.set_xlabel("Month")
        ax.legend(fontsize=8)
        self.st_chart.draw()
        txt = [f"Monthly net cash flow under stress: {self.m(res['monthly_net'])}."]
        txt.append("Survives the 12-month horizon." if res["survives_horizon"] else
                   f"Runs out of cash and facility in month {res['runway_months']}.")
        if res["covenant_breach_month"]:
            txt.append(f"Covenant breached in month {res['covenant_breach_month']}: lenders may withdraw the facility, "
                       "so re-run with it withdrawn.")
        self.st_out.setText(" ".join(txt))
        self.game.count("stress_tests")
        self.game.check_achievements()


def _money_fmt(cur: str):
    from matplotlib.ticker import FuncFormatter
    from ...core.util import fmt_money
    return FuncFormatter(lambda v, _: fmt_money(v, cur))
