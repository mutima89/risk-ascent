"""Final CRO board simulation and the career summary, with New Game Plus."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox

from ...core.competency import COMPETENCIES
from ...core.difficulty import DIFFICULTIES
from ..base import Screen
from ..widgets import Card, Chart, RadarChart, Tile, badge, button, grid, hbox, lbl, vbox
from .. import theme


class FinalScreen(Screen):
    key = "final"
    title = "CRO assessment"

    def populate(self) -> None:
        g = self.game
        p = theme.current()
        lay = self.page.layout_
        fid = g.c.careers["final_assessment"]
        fm = g.c.missions[fid]
        top_level = len(g.c.careers["levels"])
        best = g.best_scores().get(fid)
        lay.addWidget(lbl("FINAL ASSESSMENT", "Eyebrow"))
        lay.addWidget(lbl(fm["title"], "H1"))
        c = Card(kind="CardAccent")
        c.add(lbl(fm["objective"], "Body"))
        c.add(lbl("The board simulation assesses enterprise-wide judgement: risk appetite, financial trade-offs, "
                  "strategic alignment, governance and communication under uncertainty. Pass mark 70%.", "Small"))
        if g.level < top_level:
            c.add(lbl(f"Available once you hold the level {top_level} role (you are level {g.level}). "
                      "The career map shows what each promotion needs.", "Warn"))
            c.add(hbox(button("Career map", lambda: self.win.go("career"), "Primary"), stretch_end=True))
        else:
            if best is not None:
                c.add(badge(f"Best score {best * 100:.0f}% · {'passed' if best >= 0.7 else 'not yet passed'}",
                            p.good if best >= 0.7 else p.warn, filled=True))
            c.add(hbox(button("Enter the boardroom" if best is None else "Retake the board simulation",
                              lambda: self.win.go("mission", mission_id=fid), "Primary"), stretch_end=True))
        lay.addWidget(c)
        lay.addWidget(self.summary())
        if g.cro_passed():
            ng = Card("New Game Plus", "Start again at level 1 in a different organisation with harder settings. "
                      "Achievements carry over, and 80% of each competency score as a head start. Your current "
                      "career is backed up first.")
            self.org_combo = QComboBox()
            for o in g.c.orgs.values():
                self.org_combo.addItem(f"{o['name']} ({o['industry_label']})", o["id"])
            self.diff_combo = QComboBox()
            for k, d in DIFFICULTIES.items():
                self.diff_combo.addItem(d.label, k)
            self.diff_combo.setCurrentIndex(self.diff_combo.findData("expert"))
            ng.add(hbox(lbl("Organisation", wrap=False), self.org_combo, lbl("Difficulty", wrap=False),
                        self.diff_combo, button("Begin New Game Plus", self.ngplus, "Primary"), "stretch"))
            lay.addWidget(ng)

    def summary(self) -> Card:
        g = self.game
        p = theme.current()
        card = Card("Career summary")
        hist = g.career_history()
        promos = [h for h in hist if h["event"] in ("Joined", "Promotion")]
        best = g.best_scores()
        caps = [(m["title"], best.get(m["id"])) for m in g.c.mission_list() if m["type"] == "capstone"]
        c = g.counters()
        tiles = [Tile("Current role", g.title() if len(g.title()) < 26 else f"Level {g.level}", g.org["name"]),
                 Tile("Missions completed", f"{len(best)}", f"of {len(g.c.missions)}"),
                 Tile("Achievements", f"{len(g.earned_achievements())}", f"of {len(g.c.achievements)}"),
                 Tile("Months in role", f"{g.period()}", "simulated"),
                 Tile("Sound calls, bad luck", f"{c.get('good_decision_bad_luck', 0)}",
                      "good decisions that met bad outcomes"),
                 Tile("Promotions", f"{c.get('promotions', 0)}", f"{c.get('interviews', 0)} interviews")]
        card.add(grid(tiles, 6))
        if len(promos) >= 1:
            ch = Chart(2.4)
            xs = list(range(len(promos)))
            ch.ax.step(xs, [h["salary"] for h in promos], where="post", color=p.gold, marker="o")
            ch.ax.set_xticks(xs)
            ch.ax.set_xticklabels([f"L{h['level']}" for h in promos])
            from .finance import _money_fmt
            ch.ax.yaxis.set_major_formatter(_money_fmt(g.org["currency"]))
            ch.ax.set_title("Base salary by role (illustrative)", fontsize=9)
            ch.draw()
            radar = RadarChart()
            comps = g.competency_scores()
            radar.set_data([v.split()[0] for v in COMPETENCIES.values()], [comps[k] for k in COMPETENCIES])
            card.add(grid([ch, radar], 2))
        card.add(lbl("Capstones: " + " · ".join(f"{t} {'%.0f%%' % (s * 100) if s is not None else '(not attempted)'}"
                                                      for t, s in caps), "Small"))
        paths = [ep for ep in g.exec_paths() if ep["completed"]]
        card.add(lbl("Executive paths completed: " + (", ".join(ep["title"] for ep in paths) or "none yet"), "Small"))
        card.add(lbl("Credentials earned in Risk Ascent are internal game achievements, not accredited "
                     "qualifications. Salaries are illustrative simulation data.", "Small"))
        return card

    def ngplus(self) -> None:
        if not self.dialogs.confirm(self, "New Game Plus", "Start New Game Plus in this slot? The current career is "
                                    "backed up first and can be restored from Saves & recovery."):
            return
        g = self.game.new_game_plus(self.org_combo.currentData(), self.diff_combo.currentData())
        self.win.game = None
        self.win.start_game(g, first=True)
