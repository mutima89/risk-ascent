"""Achievements and career portfolio."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from ...core.competency import COMPETENCIES
from ...paths import reports_dir
from ..base import Screen
from ..widgets import Card, badge, bar, button, fit_height, grid, hbox, lbl, make_table, set_rows
from .. import theme

CATEGORY_NAMES = {"career": "Career", "capstone": "Capstones", "tools": "Professional tools", "crisis": "Crisis",
                  "learning": "Learning", "skills": "Skills", "organisation": "Organisation", "executive": "Executive"}


class PortfolioScreen(Screen):
    key = "portfolio"
    title = "Achievements & portfolio"

    def populate(self) -> None:
        g = self.game
        p = theme.current()
        lay = self.page.layout_
        earned = g.earned_achievements()
        defs = g.c.achievements
        lay.addWidget(lbl("ACHIEVEMENTS AND CAREER PORTFOLIO", "Eyebrow"))
        lay.addWidget(lbl(f"{len(earned)} of {len(defs)} achievements", "H1"))
        lay.addWidget(bar(len(earned), len(defs), "Gold"))
        lay.addWidget(lbl("Every achievement is tied to something you verifiably did in the game. None are awarded "
                          "for time spent or log-in streaks. They are internal game achievements, not accredited "
                          "qualifications.", "Small"))

        results = g.mission_results(200)
        best: dict[str, dict] = {}
        for r in results:
            if r["mission_id"] not in best or r["score"] > best[r["mission_id"]]["score"]:
                best[r["mission_id"]] = r
        pc = Card("Portfolio of evidence", "Your best attempt at each mission, with the competencies it evidenced.")
        t = make_table(["Mission", "Type", "Best score", "Month", "Strongest evidence"], 4)
        rows = []
        for mid, r in sorted(best.items(), key=lambda kv: kv[1]["run_id"]):
            comp = r["result"].get("competency_perf", {})
            top = sorted(comp.items(), key=lambda kv: -kv[1])[:3]
            rows.append((r["title"], r["type"], f"{r['score'] * 100:.0f}%", r["period"],
                         ", ".join(f"{COMPETENCIES.get(k, k)} {v * 100:.0f}%" for k, v in top)))
        set_rows(t, rows)
        fit_height(t, 10)
        pc.add(t if rows else lbl("Complete missions to build your portfolio.", "Muted"))
        pc.add(hbox(button("Export portfolio (HTML)", self.export, "Primary"), stretch_end=True))
        lay.addWidget(pc)
        if self.focus_mode:
            return

        cats: dict[str, list] = {}
        for a in defs:
            cats.setdefault(a.get("category", "career"), []).append(a)
        for cat, items in cats.items():
            have = sum(1 for a in items if a["id"] in earned)
            lay.addWidget(lbl(f"{CATEGORY_NAMES.get(cat, cat)} · {have}/{len(items)}", "H2"))
            cards = []
            for a in items:
                got = a["id"] in earned
                c = Card(kind="CardAccent" if got else "CardMuted")
                name = a["name"] if got or not a.get("hidden") else "Hidden achievement"
                desc = a["description"] if got or not a.get("hidden") else \
                    "Earned through a consequential decision in a mission."
                c.add(hbox(lbl("★" if got else "☆", "Gold" if got else "Muted", wrap=False),
                           lbl(name, "H3"), "stretch"))
                c.add(lbl(desc, "Small"))
                if got:
                    c.add(lbl(f"Earned {earned[a['id']]['earned_at'][:10]} (month {earned[a['id']]['period']})", "Small"))
                cards.append(c)
            lay.addLayout(grid(cards, 4))

    def export(self) -> None:
        g = self.game
        path = self.dialogs.save_file(self, "Export portfolio",
                                      str(reports_dir() / f"portfolio_{datetime.now():%Y%m%d}.html"), "HTML (*.html)")
        if not path:
            return
        e = html.escape
        earned = g.earned_achievements()
        rows = "".join(f"<tr><td>{e(r['title'])}</td><td>{e(r['type'])}</td><td>{r['score'] * 100:.0f}%</td>"
                       f"<td>{r['period']}</td></tr>" for r in g.mission_results(200) if r["status"] == "completed")
        comps = "".join(f"<tr><td>{e(COMPETENCIES[k])}</td><td>{v.score:.0f}</td><td>{v.evidence}</td></tr>"
                        for k, v in g.load_competencies().items())
        ach = "".join(f"<li>{e(a['name'])}: {e(a['description'])}</li>" for a in g.c.achievements if a["id"] in earned)
        hist = "".join(f"<tr><td>{h['period']}</td><td>{e(h['event'])}</td><td>{e(h['detail'])}</td></tr>"
                       for h in g.career_history())
        doc = (f"<!doctype html><html><head><meta charset='utf-8'><title>Portfolio - {e(g.profile['name'])}</title>"
               "<style>body{font-family:Segoe UI,Arial,sans-serif;margin:28px;color:#1d2433}table{border-collapse:"
               "collapse;width:100%}td,th{border:1px solid #d5dae3;padding:5px;text-align:left}h2{border-bottom:2px "
               "solid #1f6f8b}</style></head><body>"
               f"<h1>{e(g.profile['name'])}: Risk Ascent career portfolio</h1><p>{e(g.title())}, {e(g.org['name'])}. "
               f"Generated {datetime.now():%d %b %Y}.</p><p><i>Simulator achievements are internal game records, not "
               "accredited qualifications.</i></p>"
               f"<h2>Competencies</h2><table><tr><th>Competency</th><th>Score</th><th>Evidence</th></tr>{comps}</table>"
               f"<h2>Missions</h2><table><tr><th>Mission</th><th>Type</th><th>Score</th><th>Month</th></tr>{rows}</table>"
               f"<h2>Achievements</h2><ul>{ach}</ul>"
               f"<h2>Career history</h2><table><tr><th>Month</th><th>Event</th><th>Detail</th></tr>{hist}</table>"
               "</body></html>")
        Path(path).write_text(doc, encoding="utf-8")
        g.count("exports")
        g.check_achievements()
        self.notify(f"Portfolio saved to {path}")
