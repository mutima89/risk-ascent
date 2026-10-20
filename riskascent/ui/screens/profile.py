"""Player profile and skill tree."""

from __future__ import annotations

from ...core.competency import BRANCHES, COMPETENCIES, TIERS
from ..base import Screen
from ..widgets import Card, RadarChart, Tile, badge, bar, button, fit_height, grid, hbox, lbl, make_table, set_rows
from .. import theme


class ProfileScreen(Screen):
    key = "profile"
    title = "Player profile"

    def populate(self) -> None:
        g = self.game
        p = theme.current()
        lay = self.page.layout_
        prof = g.profile
        head = Card(kind="CardAccent")
        av = lbl(prof["avatar"] or "◆", "H1", wrap=False)
        av.setStyleSheet(f"font-size:34pt;color:{p.accent};")
        head.add(hbox(av, _col(lbl(prof["name"], "H1"), lbl(f"{g.title()} · {g.org['name']}", "Muted"),
                               lbl(f"{g.org['industry_label']} · {g.org['city']} · track "
                                   f"{g.track()['label']} · {g.difficulty().label} difficulty"
                                   + (f" · New Game+ {prof['ngplus']}" if prof["ngplus"] else ""), "Small")),
                      "stretch"))
        lay.addWidget(head)

        sal = g.salary_range()
        tiles = [Tile("Level", f"{g.level}", g.level_def().stage_name),
                 Tile("Experience", f"{prof['xp']:,}", "XP from demonstrated work"),
                 Tile("Base salary", g.money(prof["salary"]), "illustrative"),
                 Tile("Bonus eligibility", f"{sal['bonus_pct'][0]:.0f}-{sal['bonus_pct'][1]:.0f}%", "of base, illustrative"),
                 Tile("Delegated authority", g.money(g.authority_limit()), "per investment"),
                 Tile("Team", f"{g.level_def().team_size}", "direct and indirect reports")]
        lay.addLayout(grid(tiles, 6))
        lay.addWidget(lbl(sal["label"] + ". " + g.c.careers["compensation_note"], "Small"))

        comps = g.load_competencies()
        exp = g.c.rubrics["stage_expectations"][str(g.level_def().stage)]
        radar = RadarChart()
        radar.set_data([COMPETENCIES[k].split()[0] for k in COMPETENCIES], [comps[k].score for k in COMPETENCIES],
                       [exp.get(k, 50) for k in COMPETENCIES])
        rc = Card("Competency profile", "Solid: your scores. Dashed gold: expectations at your career stage.")
        rc.add(radar)
        lc = Card("Competencies", "Scores move only with evidence from missions, reviews and decisions.")
        for k, label in COMPETENCIES.items():
            st = comps[k]
            e = exp.get(k, 50)
            kind = "Good" if st.score >= e else "Warn" if st.score >= e - 10 else "Bad"
            lc.add(hbox(lbl(label, wrap=False), "stretch",
                        lbl(f"{st.score:.0f} (expected {e:.0f}) · {st.evidence} evidence", "Small", wrap=False)))
            lc.add(bar(st.score, 100, kind, f"{label} {st.score:.0f} of 100"))
        lay.addLayout(grid([rc, lc], 2))

        cal = g.calibration().summary()
        cc = Card("Confidence calibration", cal["message"])
        if cal["n"]:
            cc.add(lbl(f"{cal['n']} rated answers · Brier score {cal['brier']:.3f} (lower is better) · bias "
                       f"{cal['bias'] * 100:+.0f} points", "Small"))
        cc.add(hbox(button("Open training centre", lambda: self.win.go("training")), stretch_end=True))
        lay.addWidget(cc)

        hc = Card("Career history")
        t = make_table(["Month", "Event", "Detail", "Title", "Salary"], 2)
        rows = [(h["period"], h["event"], h["detail"], h["title"], g.money(h["salary"]))
                for h in reversed(g.career_history())]
        set_rows(t, rows[:60])
        fit_height(t, 10)
        hc.add(t)
        lay.addWidget(hc)


class SkillTreeScreen(Screen):
    key = "skills"
    title = "Skill tree"

    def populate(self) -> None:
        g = self.game
        p = theme.current()
        lay = self.page.layout_
        lay.addWidget(lbl("SKILL TREE", "Eyebrow"))
        lay.addWidget(lbl("Five branches, four tiers each", "H1"))
        lay.addWidget(lbl("Tiers unlock automatically when the branch's competency average and the amount of "
                          "evidence both reach the threshold. There are no points to spend: skill is shown, not "
                          "bought.", "Muted"))
        tiers = g.branch_tiers()
        scores = g.branch_scores()
        comps = g.load_competencies()
        for b, (name, members) in BRANCHES.items():
            score, ev = scores[b]
            card = Card()
            card.add(hbox(lbl(name, "H2"), "stretch",
                          badge(f"Tier {tiers[b]} of 4", p.gold if tiers[b] else p.muted)))
            card.add(lbl("Built from: " + ", ".join(f"{COMPETENCIES[m]} ({comps[m].score:.0f})" for m in members)
                         + f" · average {score:.0f} · {ev} pieces of evidence", "Small"))
            nodes = []
            for t, node in enumerate(g.c.skills[b], start=1):
                tier_name, s_min, e_min = TIERS[t - 1]
                unlocked = tiers[b] >= t
                c = Card(kind="CardAccent" if unlocked else "CardMuted")
                c.add(hbox(lbl(f"TIER {t} · {tier_name.upper()}", "Eyebrow"), "stretch",
                           lbl("✓" if unlocked else "\U0001F512" if t > tiers[b] + 1 else "○",
                               "Good" if unlocked else "Muted", wrap=False)))
                c.add(lbl(node["name"], "H3"))
                c.add(lbl(node["description"], "Small"))
                if not unlocked:
                    c.add(lbl(f"Needs average {s_min} (now {score:.0f}) and {e_min} evidence (now {ev}).", "Small"))
                    c.add(bar(min(score / s_min, ev / e_min if e_min else 1), 1))
                nodes.append(c)
            card.add(grid(nodes, 4))
            lay.addWidget(card)


def _col(*ws):
    from ..widgets import vbox
    from PySide6.QtWidgets import QWidget
    w = QWidget()
    w.setLayout(vbox(*ws, spacing=2))
    return w
