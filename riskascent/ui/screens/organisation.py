"""Organisation overview: health metrics and history, departments, the event
timeline and the passage of time."""

from __future__ import annotations

import json

from PySide6.QtWidgets import QComboBox

from ...core.org_sim import INDEX_METRICS, METRIC_LABELS, MONEY_METRICS
from ..base import Screen
from ..widgets import Card, Chart, Tile, badge, button, fit_height, grid, hbox, lbl, make_table, set_rows
from .. import theme


class OrganisationScreen(Screen):
    key = "org"
    title = "Organisation overview"

    def __init__(self, win):
        super().__init__(win)
        self.metric_key = "reputation"

    def populate(self) -> None:
        g = self.game
        p = theme.current()
        org = g.org
        lay = self.page.layout_
        lay.addWidget(lbl(f"{org['industry_label'].upper()} · {org['city'].upper()} · MONTH {g.period()}",
                          "Eyebrow"))
        lay.addWidget(lbl(org["name"], "H1"))
        lay.addWidget(lbl(org["description"], "Muted"))
        sched = json.loads(g.db.one("SELECT scheduled_json FROM org_state")[0])
        lay.addLayout(hbox(button("Advance one month", self.advance, "Primary",
                                  tip="Time passes: KRIs move, consequences of earlier decisions arrive"),
                           lbl(f"{org['employees']:,} employees · regulator: {org['regulator']} · "
                               f"{len(sched)} consequence(s) of earlier decisions still pending", "Small"),
                           stretch_end=True))
        m = g.metrics()
        hist = g.metrics_history()
        prev = hist[-2][1] if len(hist) >= 2 else m
        tiles = []
        for k in MONEY_METRICS + INDEX_METRICS + ["risk_exposure"]:
            v = m.get(k, 0)
            dv = v - prev.get(k, v)
            money = k in MONEY_METRICS
            good_up = k not in ("operating_costs", "risk_exposure")
            col = (p.good if (dv > 0) == good_up else p.bad) if dv else None
            t = Tile(METRIC_LABELS.get(k, k))
            t.set(g.money(v) if money else f"{v:.0f}",
                  "no change" if not dv else f"{'+' if dv > 0 else ''}{g.money(dv) if money else f'{dv:.1f}'}", col)
            tiles.append(t)
        lay.addLayout(grid(tiles, 4))
        if self.focus_mode:
            return

        hc = Card("History")
        combo = QComboBox()
        for k in MONEY_METRICS + INDEX_METRICS + ["risk_exposure"]:
            combo.addItem(METRIC_LABELS.get(k, k), k)
        combo.setCurrentIndex(max(0, combo.findData(self.metric_key)))
        combo.currentIndexChanged.connect(lambda _: self._metric(combo.currentData()))
        hc.add(hbox(lbl("Metric", wrap=False), combo, stretch_end=True))
        ch = Chart(2.6)
        xs = [h[0] for h in hist]
        ys = [h[1].get(self.metric_key, 0) for h in hist]
        ch.ax.plot(xs, ys, marker="o", color=p.accent)
        if self.metric_key in MONEY_METRICS:
            from .finance import _money_fmt
            ch.ax.yaxis.set_major_formatter(_money_fmt(org["currency"]))
        else:
            ch.ax.set_ylim(0, 100)
        ch.ax.set_xlabel("Month")
        ch.draw()
        hc.add(ch)
        lay.addWidget(hc)

        lay.addWidget(lbl("Departments", "H2"))
        lay.addWidget(lbl("Each department has its own objective, constraint and incentive. Risk proposals that "
                          "ignore them meet resistance.", "Muted"))
        cards = []
        for d in g.c.departments:
            head = g.person(d["head"]) if d.get("head") in g.c.roles else None
            c = Card(d["name"])
            if head:
                c.add(lbl(f"Led by {head['name']}, {head['title']} · trust {g.trust().get(d['head'], 50):.0f}",
                          "Small"))
            c.add(lbl(f"Objective: {d.get('objective', '')}", "Small"), lbl(f"Constraint: {d.get('constraint', '')}", "Small"),
                  lbl(f"Incentive: {d.get('incentive', '')}", "Small"),
                  lbl("Exposures: " + ", ".join(d.get("exposures", [])), "Small"))
            cards.append(c)
        lay.addLayout(grid(cards, 3))

        ec = Card("Event timeline", "Incidents, consequences and decisions, newest first.")
        evs = g.events(80)
        t = make_table(["Month", "Type", "Event", "Detail"], 3)
        colors = {(i, 2): (p.bad if e["severity"] >= 3 else p.warn if e["severity"] == 2 else p.text)
                  for i, e in enumerate(evs)}
        set_rows(t, [(e["period"], e["type"].replace("_", " "), e["title"],
                      e["text"] + (" " + e["data"].get("judgement", "") if e["data"].get("judgement") else ""))
                     for e in evs], colors)
        fit_height(t, 12)
        ec.add(t if evs else lbl("No events yet.", "Muted"))
        unack = [e for e in evs if not e.get("acknowledged")]
        if unack:
            ec.add(hbox(button(f"Mark {len(unack)} as reviewed", self.ack_all), stretch_end=True))
        lay.addWidget(ec)

    def _metric(self, k: str) -> None:
        self.metric_key = k
        self.refresh()

    def advance(self) -> None:
        events = self.game.advance_period("manual")
        self.game.check_achievements()
        titles = ", ".join(e["title"] for e in events[:3])
        self.notify(f"Month {self.game.period()}. " + (f"{len(events)} event(s): {titles}" if events else
                                                       "A quiet month."))
        self.win.update_chrome()
        self.refresh()

    def ack_all(self) -> None:
        g = self.game
        with g.db.tx():
            g.db.ex("UPDATE events SET acknowledged=1")
        self.refresh()
