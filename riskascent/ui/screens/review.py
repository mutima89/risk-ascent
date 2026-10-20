"""Performance review: competencies against stage expectations, evidenced
strengths, development areas and the assessment rubrics."""

from __future__ import annotations

from ..base import Screen
from ..widgets import Card, bar, button, fit_height, grid, hbox, lbl, make_table, set_rows
from .. import theme


class ReviewScreen(Screen):
    key = "review"
    title = "Performance review"

    def populate(self) -> None:
        g = self.game
        p = theme.current()
        lay = self.page.layout_
        rv = g.performance_review()
        lvl = g.level_def()
        lay.addWidget(lbl(f"PERFORMANCE REVIEW · STAGE {lvl.stage}: {lvl.stage_name.upper()}", "Eyebrow"))
        lay.addWidget(lbl(f"{rv['overall']}", "H1"))
        lay.addWidget(lbl(f"{g.profile['name']}, {g.title()}. {rv['met']} of {rv['total']} competencies meet the "
                          "expectation for your stage. Ratings come only from recorded evidence.", "Muted"))
        sc = Card("Strengths")
        if not rv["strengths"]:
            sc.add(lbl("Not enough evidence yet. Complete missions to build a record.", "Muted"))
        for s in rv["strengths"]:
            sc.add(lbl(f"{s['label']}: {s['score']:.0f} (expected {s['expected']:.0f}), {s['rating']}", "H3"))
            if s.get("evidence_refs"):
                sc.add(lbl("Evidence: " + "; ".join(s["evidence_refs"]), "Small"))
        wc = Card("Development areas")
        if not rv["weaknesses"]:
            wc.add(lbl("No significant gaps against your stage expectations.", "Muted"))
        for w in rv["weaknesses"]:
            wc.add(lbl(f"{w['label']}: {w['score']:.0f} (expected {w['expected']:.0f}), {w['rating']}", "H3"))
            if w.get("evidence_refs"):
                wc.add(lbl("Evidence: " + "; ".join(w["evidence_refs"]), "Small"))
            for d in w.get("development", []):
                wc.add(lbl("→ " + d, "Small"))
        wc.add(hbox(button("Targeted practice", lambda: self.win.go("training")),
                    button("Find missions", lambda: self.win.go("missions")), stretch_end=True))
        lay.addLayout(grid([sc, wc], 2))
        if self.focus_mode:
            return

        tc = Card("Competency ratings")
        t = make_table(["Competency", "Score", "Expected at stage", "Gap", "Rating", "Evidence"], 0)
        colors = {}
        for i, r in enumerate(rv["rows"]):
            colors[(i, 4)] = p.good if r["gap"] >= 0 else p.warn if r["gap"] > -10 else p.bad
        set_rows(t, [(r["label"], f"{r['score']:.0f}", f"{r['expected']:.0f}", f"{r['gap']:+.0f}", r["rating"],
                      r["evidence"]) for r in rv["rows"]], colors)
        fit_height(t, 12)
        tc.add(t)
        lay.addWidget(tc)
        cal = rv.get("calibration")
        if cal:
            lay.addWidget(Card("Confidence calibration", cal["message"]))

        lay.addWidget(lbl("Assessment rubrics", "H2"))
        lay.addWidget(lbl("Transparent criteria with level-specific expectations. Your current level descriptor is "
                          "highlighted.", "Muted"))
        cards = []
        stage = str(min(lvl.stage, 6))
        for r in g.c.rubrics["rubrics"]:
            c = Card(r["title"])
            c.add(lbl("\n".join("• " + x for x in r["criteria"]), "Small"))
            levels = r.get("levels", {})
            key = stage if stage in levels else str(min(int(k) for k in levels)) if levels else None
            if key:
                c.add(lbl(f"At your stage: {levels[key]}", "Body"))
            cards.append(c)
        lay.addLayout(grid(cards, 3))
        notes = g.c.rubrics.get("scoring_notes", "")
        if notes:
            lay.addWidget(lbl(notes if isinstance(notes, str) else " ".join(notes), "Small"))
        lay.addWidget(lbl("Simulator credentials and reviews are internal game achievements. They are not accredited "
                          "qualifications and do not guarantee employability.", "Small"))
