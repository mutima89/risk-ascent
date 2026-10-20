"""Main career dashboard: one clear next action, then the state of the career
and organisation at a glance."""

from __future__ import annotations

from ...core.career import eligible
from ...core.kri import STATUS_CRIT, STATUS_WARN
from ...core.risk_engine import heatmap_counts
from ..base import Screen
from ..widgets import Card, HeatMap, Tile, badge, bar, button, grid, hbox, lbl, vbox
from .. import theme


def next_action(win) -> dict:
    """The single most useful next step, used by the dashboard and focus mode."""
    g = win.game
    active = g.db.one("SELECT mission_id FROM mission_runs WHERE status='active' ORDER BY run_id DESC LIMIT 1")
    if active:
        m = g.c.missions[active["mission_id"]]
        return {"title": f"Resume: {m['title']}", "text": "Your progress was saved at the last step you completed.",
                "label": "Resume mission", "go": ("mission", {"mission_id": m["id"]})}
    if g.next_level_def() and eligible(g.promotion_checks()):
        return {"title": "You are ready for promotion",
                "text": f"Every requirement for {g.next_level_def().title} is met. Sit the promotion interview "
                        "when you are ready.", "label": "Go to career map", "go": ("career", {})}
    lvl = g.level_def()
    best = g.best_scores()
    status = {s["mission"]["id"]: s for s in g.mission_status()}
    for mid in lvl.required_missions + ([lvl.capstone] if lvl.capstone else []):
        s = status.get(mid)
        if s and s["available"] and (mid not in best or (mid == lvl.capstone and best[mid] < 0.7)
                                     or best.get(mid, 1) < 0.6):
            m = s["mission"]
            return {"title": m["title"], "text": m["objective"], "label": "Open briefing",
                    "go": ("mission", {"mission_id": mid}), "meta": f"{m['duration']} · {m['xp']} XP"}
    if g.level >= len(g.c.careers["levels"]) and not g.cro_passed():
        return {"title": "The CRO board simulation", "text": "Your final assessment is available.",
                "label": "Open CRO assessment", "go": ("final", {})}
    due = g.due_reviews(win.settings.review_intervals)
    if due:
        return {"title": f"{len(due)} concept review(s) due", "text": "A few minutes of retrieval practice "
                "keeps what you've learned available when you need it.", "label": "Start review",
                "go": ("training", {})}
    unread = [m for m in g.list_messages() if m["status"] == "unread"]
    if unread:
        return {"title": f"{len(unread)} unread message(s)", "text": unread[0]["subject"],
                "label": "Open inbox", "go": ("stakeholders", {})}
    checks = [c for c in g.promotion_checks() if not c.passed]
    return {"title": "Build your track record", "text": (checks[0].detail if checks else
            "Take on optional missions, crisis scenarios or weekly challenges, or advance the organisation a month."),
            "label": "Browse missions", "go": ("missions", {})}


class DashboardScreen(Screen):
    key = "dashboard"
    title = "Dashboard"

    def populate(self) -> None:
        g = self.game
        p = theme.current()
        lay = self.page.layout_
        prof = g.profile
        nxt = g.next_level_def()
        na = next_action(self.win)

        lay.addWidget(lbl(f"MONTH {g.period()} · {g.org['name'].upper()}", "Eyebrow"))
        lay.addWidget(lbl(f"Good to see you, {prof['name']}.", "H1"))

        act = Card(kind="CardAccent", eyebrow="Next action")
        act.add(lbl(na["title"], "H2"), lbl(na["text"], "Body"))
        if na.get("meta"):
            act.add(lbl(na["meta"], "Small"))
        go_key, go_kw = na["go"]
        b = button(na["label"], lambda: self.win.go(go_key, **go_kw), "Primary", shortcut="Ctrl+Return")
        act.add(hbox(b, stretch_end=True))
        lay.addWidget(act)
        if self.focus_mode:
            lay.addWidget(lbl("Focus mode shows only your next action. Press F6 or Esc to see everything.", "Small"))
            return

        # Career progress
        car = Card(eyebrow="Career")
        car.add(lbl(f"{g.title()}", "H2"))
        xp = prof["xp"]
        if nxt:
            need = nxt.xp_required
            car.add(lbl(f"{xp} / {need} XP towards {nxt.title}", "Muted"), bar(xp, need, "Gold"))
            checks = g.promotion_checks()
            done = sum(1 for c in checks if c.passed)
            car.add(lbl(f"Promotion requirements: {done} of {len(checks)} met", "Small"),
                    bar(done, len(checks), "Good" if done == len(checks) else None))
        else:
            car.add(lbl(f"{xp} XP · top of the ladder", "Muted"))
        sal = g.salary_range()
        car.add(lbl(f"Base salary {g.money(prof['salary'], False)} (illustrative)", "Small"))
        car.add(hbox(button("Career map", lambda: self.win.go("career")),
                     button("Performance review", lambda: self.win.go("review")), stretch_end=True))

        # Alerts
        alerts = Card(eyebrow="Needs attention")
        kris = g.list_kris()
        crit = [k for k in kris if k.status() == STATUS_CRIT]
        warn = [k for k in kris if k.status() == STATUS_WARN]
        unread = [m for m in g.list_messages() if m["status"] == "unread"]
        events = g.events(20, unacknowledged=True)
        due = g.due_reviews(self.win.settings.review_intervals)
        rows = []
        if crit:
            rows.append((f"{len(crit)} KRI(s) at critical: " + ", ".join(k.name for k in crit[:3]), p.bad, "kri"))
        if warn:
            rows.append((f"{len(warn)} KRI(s) at warning", p.warn, "kri"))
        if unread:
            rows.append((f"{len(unread)} unread stakeholder message(s)", p.info, "stakeholders"))
        sev = [e for e in events if e["severity"] >= 2]
        if sev:
            rows.append((f"{len(sev)} new incident(s): {sev[0]['title']}", p.warn, "org"))
        if due and self.win.settings.review_reminders:
            rows.append((f"{len(due)} concept review(s) due", p.accent, "training"))
        if not rows:
            alerts.add(lbl("Nothing urgent. A good time for deliberate practice or an optional mission.", "Muted"))
        for text, color, key in rows:
            dot = lbl("●", wrap=False)
            dot.setStyleSheet(f"color:{color};")
            alerts.add(hbox(dot, lbl(text), "stretch", button("Open", lambda k=key: self.win.go(k), "Ghost")))
        alerts.add("stretch")
        lay.addLayout(grid([car, alerts], 2))

        # Organisation tiles
        m = g.metrics()
        hist = g.metrics_history()
        prev = hist[-2][1] if len(hist) >= 2 else m
        tiles = []
        for k, label, money in [("cash", "Cash & liquidity", True), ("reputation", "Reputation", False),
                                ("risk_exposure", "Risk exposure", False), ("resilience", "Resilience", False),
                                ("control_effectiveness", "Control effectiveness", False),
                                ("compliance", "Compliance", False)]:
            v = m.get(k, 0)
            dv = v - prev.get(k, v)
            t = Tile(label)
            good_up = k != "risk_exposure"
            col = p.good if (dv > 0) == good_up and dv else (p.bad if dv else None)
            t.set(g.money(v) if money else f"{v:.0f}",
                  ("no change" if not dv else (f"{'+' if dv > 0 else ''}{g.money(dv) if money else f'{dv:.1f}'} "
                                               "vs last month")), col)
            tiles.append(t)
        lay.addWidget(lbl("Organisation", "H2"))
        lay.addLayout(grid(tiles, 6))

        # Risk profile + recent events
        hm_card = Card(eyebrow="Residual risk profile")
        hm = HeatMap()
        mat = g.matrix()
        hm.set_data(mat, heatmap_counts(g.list_risks(), mat.size, True))
        hm.setMinimumHeight(260)
        hm.cell_clicked.connect(lambda l, i: self.win.go("register", cell=(l, i)) if l else None)
        hm_card.add(hm, lbl("Click a cell to open those risks in the register.", "Small"))
        ev_card = Card(eyebrow="Recent events")
        evs = g.events(7)
        if not evs:
            ev_card.add(lbl("No events yet. Completing missions advances the organisation month by month.", "Muted"))
        for e in evs:
            col = p.bad if e["severity"] >= 3 else p.warn if e["severity"] == 2 else p.muted
            ev_card.add(vbox(hbox(badge(f"M{e['period']}", col), lbl(e["title"], "H3"), "stretch"),
                             lbl(e["text"][:220], "Small"), spacing=2))
        ev_card.add("stretch", hbox(button("Organisation overview", lambda: self.win.go("org")), stretch_end=True))
        lay.addLayout(grid([hm_card, ev_card], 2))

    def checklist(self):
        return []
