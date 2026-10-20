"""Budget and resource allocation: the risk function budget, delegated
authority, treatment investment proposals, department budgets and the
player's professional development budget."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QLineEdit, QSpinBox

from ...core.competency import COMPETENCIES
from ..base import Screen
from ..widgets import Card, Tile, button, fit_height, grid, hbox, lbl, make_table, set_rows
from .. import theme
from .finance import form_grid, money_spin

DEPT_WEIGHTS = {"operations": 0.44, "finance": 0.06, "it": 0.12, "hr": 0.05, "legal": 0.03, "sales": 0.15,
                "procurement": 0.08, "security": 0.04, "exec": 0.03}

COURSES = [
    ("quant", "Quantitative risk modelling workshop", 2500, ["financial", "analysis"]),
    ("influence", "Influencing executives masterclass", 1800, ["communication", "stakeholder"]),
    ("controls", "Internal controls and audit fundamentals", 1500, ["technical", "evidence"]),
    ("resilience", "Business continuity practitioner course", 2000, ["technical", "prioritization"]),
    ("leadership", "Leading risk teams programme", 3500, ["leadership", "strategy", "ethics"]),
]


class BudgetScreen(Screen):
    key = "budget"
    title = "Budget & investments"

    def populate(self) -> None:
        g = self.game
        p = theme.current()
        lay = self.page.layout_
        lay.addWidget(lbl("BUDGET AND RESOURCE ALLOCATION", "Eyebrow"))
        lay.addWidget(lbl("Spend where risk reduction is greatest", "H1"))
        inv = g.list_investments()
        approved = [i for i in inv if i["status"] == "Approved"]
        tiles = [Tile("Risk function budget", g.money(g.budget()), "remaining, refreshed quarterly"),
                 Tile("Your delegated authority", g.money(g.authority_limit()), "above this the CFO decides"),
                 Tile("Approved investments", f"{len(approved)}",
                      g.money(sum(i["cost"] for i in approved)) + " committed"),
                 Tile("Annual expected loss avoided", g.money(sum(i["el_before"] - i["el_after"] for i in approved)),
                      "from approved treatments")]
        lay.addLayout(grid(tiles, 4))

        h = self.win.handoff.pop("investment", None)
        prop = Card("Propose a treatment investment",
                    "Within your authority you decide (and must still meet a minimum benefit/cost of 0.5). Above it, "
                    "the CFO weighs the 3-year benefit/cost ratio and their trust in you. Build the case in the "
                    "Financial lab first.")
        cur = g.org["currency"]
        self.risk = QComboBox()
        for r in g.list_risks():
            if r["status"] != "Closed":
                self.risk.addItem(f"{r['risk_id']} {r['title']} (residual {r['res_l']}×{r['res_i']})", r["risk_id"])
        self.ptitle = QLineEdit((h or {}).get("title", ""))
        self.ptitle.setPlaceholderText("e.g. Deploy MFA to all remote accounts")
        self.cost = money_spin(cur, (h or {}).get("upfront", 0) + (h or {}).get("annual", 0) * (h or {}).get("years", 0)
                               or 150_000 * g.org["money_scale"])
        self.before = money_spin(cur, (h or {}).get("el_before", 300_000 * g.org["money_scale"]))
        self.after = money_spin(cur, (h or {}).get("el_after", 120_000 * g.org["money_scale"]))
        self.dl = QSpinBox()
        self.dl.setRange(-3, 0)
        self.dl.setValue(-1)
        self.di = QSpinBox()
        self.di.setRange(-3, 0)
        if h and h.get("risk_id"):
            self.risk.setCurrentIndex(max(0, self.risk.findData(h["risk_id"])))
        prop.add(form_grid([("Risk", self.risk), ("Proposal", self.ptitle), ("Total cost", self.cost),
                            ("Expected annual loss before", self.before), ("Expected annual loss after", self.after),
                            ("Residual likelihood change", self.dl), ("Residual impact change", self.di)], 4))
        if h:
            prop.add(lbl(f"Prefilled from the Financial lab: NPV {g.money(h['npv'])}, total cost over "
                         f"{h['years']} years.", "Small"))
        self.result_lbl = lbl("", "Body")
        prop.add(hbox(button("Submit proposal", self.submit, "Primary"), stretch_end=True), self.result_lbl)
        lay.addWidget(prop)

        hist = Card("Investment decisions")
        t = make_table(["Month", "Proposal", "Risk", "Cost", "EL reduction", "Decision", "Decided by", "Reason"], 7)
        colors = {(k, 5): theme.status_color(i["status"]) for k, i in enumerate(inv)}
        set_rows(t, [(f"M{i['period']}", i["title"], i["risk_id"], g.money(i["cost"]),
                      g.money(i["el_before"] - i["el_after"]), i["status"], i["decided_by"], i["data"].get("reason", ""))
                     for i in inv], colors)
        fit_height(t, 8)
        hist.add(t if inv else lbl("No proposals yet.", "Muted"))
        lay.addWidget(hist)
        if self.focus_mode:
            return

        m = g.metrics()
        dc = Card("Department budgets", "Illustrative split of annual operating costs. Each department's objective "
                  "and incentive shapes how it reacts to risk requests.")
        dt = make_table(["Department", "Head", "Annual budget", "Objective", "Constraint", "Incentive"], (3, 4, 5))
        rows = []
        for d in g.c.departments:
            head = g.person(d["head"]) if d.get("head") in g.c.roles else {"name": "-"}
            rows.append((d["name"], head["name"], g.money(m.get("operating_costs", 0) * DEPT_WEIGHTS.get(d["id"], 0.05)),
                         d.get("objective", ""), d.get("constraint", ""), d.get("incentive", "")))
        set_rows(dt, rows)
        fit_height(dt, 10)
        dc.add(dt)
        lay.addWidget(dc)

        pd_budget = self.pd_budget()
        spent = g.db.meta_get("pd_spent", {})
        year = str(g.period() // 12)
        used = spent.get(year, 0)
        pdc = Card("Professional development", f"Annual training budget at your level: {g.money(pd_budget, False)} "
                   f"(illustrative). Used this year: {g.money(used, False)}. A course schedules targeted practice "
                   "on the competencies it covers; the competency itself still only moves with demonstrated work.")
        comps = g.competency_scores()
        for cid, name, cost, covers in COURSES:
            c = cost * g.org["money_scale"]
            b = button("Book", lambda cid=cid: self.book(cid))
            b.setEnabled(used + c <= pd_budget)
            pdc.add(hbox(lbl(name, wrap=False), lbl(", ".join(f"{COMPETENCIES[k]} {comps[k]:.0f}" for k in covers),
                                                    "Small"), "stretch", lbl(g.money(c, False), "Small", wrap=False), b))
        lay.addWidget(pdc)

    def pd_budget(self) -> float:
        g = self.game
        return (1500 + 900 * g.level) * g.org["money_scale"]

    def book(self, cid: str) -> None:
        g = self.game
        course = next(c for c in COURSES if c[0] == cid)
        cost = course[2] * g.org["money_scale"]
        spent = g.db.meta_get("pd_spent", {})
        year = str(g.period() // 12)
        if spent.get(year, 0) + cost > self.pd_budget():
            self.fail("Not enough professional development budget left this year.")
            return
        spent[year] = spent.get(year, 0) + cost
        from datetime import date
        with g.db.tx():
            g.db.meta_set("pd_spent", spent)
            concepts = [k for k, c in g.c.concepts.items() if c.get("competency") in course[3]]
            for k in concepts:
                g.db.ex("UPDATE review_cards SET due=? WHERE concept_id=? AND (due='' OR due>?)",
                        (date.today().isoformat(), k, date.today().isoformat()))
            g.db.ex("INSERT INTO career_history(period, event, detail, level, title, salary, created_at)"
                    " VALUES(?,?,?,?,?,?,datetime('now'))",
                    (g.period(), "Training", f"{course[1]} ({g.money(cost, False)})", g.level, g.title(),
                     g.profile["salary"]))
            g.db.counter_add("courses_booked")
        self.notify(f"Booked: {course[1]}. Related practice is now in the Training centre (it appears once the "
                    "concept has been taught in a mission).")
        self.win.update_chrome()
        self.refresh()

    def submit(self) -> None:
        g = self.game
        rid = self.risk.currentData()
        if not rid:
            self.fail("Choose a risk.")
            return
        title = self.ptitle.text().strip()
        if not title:
            self.fail("Give the proposal a title.")
            return
        try:
            res = g.propose_investment(rid, title, self.cost.value(), self.before.value(), self.after.value(),
                                       self.dl.value(), self.di.value())
        except ValueError as exc:
            self.fail(exc)
            return
        g.check_achievements()
        self.notify(("Approved: " if res["approved"] else "Declined: ") + res["reason"])
        self.refresh()
