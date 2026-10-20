"""Training and spaced-review centre: retrieval practice on due concepts,
confidence calibration, targeted (deliberate) practice and the concept
library. All review data stays local."""

from __future__ import annotations

import random
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QRadioButton, QSlider

from ...core.competency import COMPETENCIES
from ...core.util import stable_seed
from ..base import Screen
from ..widgets import Card, Chart, button, fit_height, grid, hbox, lbl, make_table, set_rows
from .. import theme


class TrainingScreen(Screen):
    key = "training"
    title = "Training centre"

    def __init__(self, win):
        super().__init__(win)
        self.answer_shown: dict | None = None

    def populate(self) -> None:
        g = self.game
        p = theme.current()
        lay = self.page.layout_
        intervals = self.win.settings.review_intervals
        due = g.due_reviews(intervals)
        unlocked = g.unlocked_concepts()
        lay.addWidget(lbl("TRAINING AND SPACED REVIEW", "Eyebrow"))
        lay.addWidget(lbl(f"{len(due)} review(s) due · {len(unlocked)} concepts learned", "H1"))
        lay.addWidget(lbl("Short retrieval practice at growing intervals is one of the best-evidenced ways to make "
                          "learning stick. Answer from memory first; the explanation comes after. Intervals (days): "
                          + ", ".join(str(i) for i in intervals) + " (change in Settings).", "Muted"))

        rc = Card(kind="CardAccent", eyebrow="Retrieval practice")
        if self.answer_shown:
            a = self.answer_shown
            rc.add(lbl(a["question"], "H2"))
            rc.add(lbl(("✓ Correct. " if a["correct"] else "✕ Not quite. ") + a["explanation"], "Body"))
            if not a["correct"]:
                rc.add(lbl("Correct answer: " + a["right"], "Small"))
            rc.add(lbl(f"Next review: {a['next_due']}", "Small"))
            rc.add(hbox(button("Next card" if due else "Done", self._next, "Primary", shortcut="Ctrl+Return"),
                        stretch_end=True))
        elif due:
            card = due[0]
            c = g.c.concepts[card.concept_id]
            rc.add(lbl(f"{c['title']} · box {card.box + 1} of {len(intervals)}", "Small"))
            rc.add(lbl(c["question"], "H2"))
            self.group = QButtonGroup(self)
            order = list(range(len(c["options"])))
            random.Random(stable_seed(card.concept_id, card.reviews)).shuffle(order)
            for pos, i in enumerate(order):
                rb = QRadioButton(c["options"][i])
                rb.setProperty("i", i)
                self.group.addButton(rb, pos)
                rc.add(rb)
            self.conf = QSlider(Qt.Horizontal)
            self.conf.setRange(50, 100)
            self.conf.setValue(70)
            cl = lbl("Confidence: 70%", "Small")
            self.conf.valueChanged.connect(lambda v: cl.setText(f"Confidence: {v}%"))
            rc.add(self.conf, cl)
            self.current = card.concept_id
            rc.add(hbox(button("Check answer", self.check, "Primary", shortcut="Ctrl+Return"), stretch_end=True))
        else:
            nxt = sorted(c.due for c in g.review_cards() if c.concept_id in unlocked and c.due)
            rc.add(lbl("Nothing due right now.", "H2"))
            rc.add(lbl((f"Next review on {nxt[0]}. " if nxt else "Complete missions to unlock concepts for review. ")
                       + "There is no streak to keep: come back whenever suits you.", "Muted"))
        lay.addWidget(rc)
        if self.focus_mode:
            return

        # Deliberate practice
        comps = g.competency_scores()
        exp = g.c.rubrics["stage_expectations"][str(g.level_def().stage)]
        gaps = sorted(COMPETENCIES, key=lambda k: comps[k] - exp.get(k, 50))[:3]
        dp = Card("Deliberate practice", "Your three largest gaps against stage expectations, with missions that "
                  "assess them. Replays use fresh outcome seeds.")
        status = {s["mission"]["id"]: s for s in g.mission_status()}
        for k in gaps:
            ms = [m for m in g.c.mission_list() if status[m["id"]]["available"] and m["type"] != "executive"
                  and any(k in (s.get("competencies") or []) for s in m["steps"])][:3]
            dp.add(lbl(f"{COMPETENCIES[k]}: {comps[k]:.0f} (expected {exp.get(k, 50):.0f})", "H3"))
            if ms:
                row = [button(m["title"], lambda mid=m["id"]: self.win.go("mission", mission_id=mid)) for m in ms]
                dp.add(hbox(*row, stretch_end=True))
            else:
                dp.add(lbl("Missions for this competency unlock at later levels.", "Small"))
            dp.add(hbox(button(f"Review {COMPETENCIES[k].lower()} concepts now", lambda k=k: self.practise(k), "Ghost"),
                        stretch_end=True))

        # Calibration
        cal = g.calibration()
        cc = Card("Confidence calibration", cal.message())
        bins = cal.bins()
        if bins:
            ch = Chart(2.6, 4)
            ax = ch.ax
            ax.plot([0.5, 1], [0.5, 1], color=p.muted, linestyle="--", linewidth=1, label="Perfect calibration")
            ax.plot([b["mean_conf"] for b in bins], [b["accuracy"] for b in bins], marker="o", color=p.accent,
                    label="You")
            for b in bins:
                ax.annotate(str(b["n"]), (b["mean_conf"], b["accuracy"]), fontsize=7, color=p.muted,
                            xytext=(4, 4), textcoords="offset points")
            ax.set_xlim(0.45, 1.02)
            ax.set_ylim(0, 1.05)
            ax.set_xlabel("Stated confidence")
            ax.set_ylabel("Actual accuracy")
            ax.legend(fontsize=7)
            ch.draw()
            cc.add(ch)
            s = cal.summary()
            cc.add(lbl(f"Brier score {s['brier']:.3f} (0 is perfect; 0.25 is what always saying 50% scores).",
                       "Small"))
        else:
            cc.add(lbl("Rate your confidence on reviews and key mission decisions to build this chart.", "Small"))
        lay.addLayout(grid([dp, cc], 2))

        # Library
        lib = Card("Concept library", "Concepts you have met in missions. Explanations appear after your first "
                   "review, so the first encounter is genuine retrieval.")
        cards = {c.concept_id: c for c in g.review_cards()}
        rows = []
        for cid in sorted(unlocked):
            c = g.c.concepts.get(cid)
            if not c:
                continue
            rc_ = cards.get(cid)
            rows.append((c["title"], COMPETENCIES.get(c.get("competency", ""), ""),
                         (rc_.box + 1) if rc_ else 1, rc_.due if rc_ and rc_.due else "now",
                         c["explanation"] if rc_ and rc_.reviews else "Review it first"))
        t = make_table(["Concept", "Competency", "Box", "Next review", "Explanation"], 4)
        set_rows(t, rows)
        fit_height(t, 12)
        lib.add(t if rows else lbl("Complete your first mission to unlock concepts.", "Muted"))
        lay.addWidget(lib)

    def check(self) -> None:
        b = self.group.checkedButton()
        if b is None:
            self.fail("Choose an answer first.")
            return
        g = self.game
        cid = self.current
        c = g.c.concepts[cid]
        res = g.record_review(cid, int(b.property("i")), self.conf.value() / 100, self.win.settings.review_intervals)
        g.check_achievements()
        self.answer_shown = {"question": c["question"], "correct": res["correct"], "explanation": res["explanation"],
                             "right": c["options"][c["answer"]], "next_due": res["next_due"]}
        self.win.update_chrome()
        self.refresh()

    def _next(self) -> None:
        self.answer_shown = None
        self.refresh()

    def practise(self, comp: str) -> None:
        g = self.game
        today = date.today().isoformat()
        unlocked = g.unlocked_concepts()
        ids = [k for k, c in g.c.concepts.items() if c.get("competency") == comp and k in unlocked]
        if not ids:
            self.notify("No concepts for that competency have been taught yet. Try one of the missions listed.")
            return
        with g.db.tx():
            for k in ids:
                g.db.ex("UPDATE review_cards SET due=? WHERE concept_id=?", (today, k))
        self.answer_shown = None
        self.win.update_chrome()
        self.refresh()
