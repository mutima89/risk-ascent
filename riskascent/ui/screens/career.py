"""Career map and promotion pathway: the ladder, requirements for the next
role, promotion interview and salary negotiation, lateral moves."""

from __future__ import annotations

import random

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QHBoxLayout, QRadioButton, QSlider,
                               QStackedWidget, QVBoxLayout, QWidget)

from ...core.career import eligible
from ...core.util import stable_seed
from ..base import Screen
from ..widgets import Card, badge, bar, button, grid, hbox, lbl, vbox
from .. import theme


class CareerScreen(Screen):
    key = "career"
    title = "Career map"

    def populate(self) -> None:
        g = self.game
        p = theme.current()
        lay = self.page.layout_
        lay.addWidget(lbl("CAREER MAP", "Eyebrow"))
        lay.addWidget(lbl(f"{g.title()} · level {g.level} of {len(g.c.careers['levels'])}", "H1"))
        path = g.profile["career_path"]
        lay.addWidget(lbl("Path: " + ("Expert (technical depth)" if path == "expert" else "Management (leadership)")
                          + f" · Track: {g.track()['label']}", "Muted"))

        nxt = g.next_level_def()
        if nxt:
            checks = g.promotion_checks()
            req = Card(kind="CardAccent" if eligible(checks) else "Card", eyebrow="Next role")
            req.add(lbl(nxt.title_for(path), "H2"))
            if nxt.expert_title != nxt.title:
                req.add(lbl(f"Management title: {nxt.title}  ·  Expert title: {nxt.expert_title}", "Small"))
            for c in checks:
                req.add(hbox(lbl("✓" if c.passed else "○", "Good" if c.passed else "Muted", wrap=False),
                             lbl(c.label), "stretch", lbl(c.detail, "Small", wrap=False)))
            rng = g.salary_range(nxt)
            req.add(lbl(f"Illustrative base salary for the role: {g.money(rng['min'], False)} to "
                        f"{g.money(rng['max'], False)}. {rng['label']}.", "Small"))
            b = button("Sit promotion interview", self.interview, "Primary")
            b.setEnabled(eligible(checks))
            if not eligible(checks):
                b.setToolTip("Meet every requirement above first.")
            req.add(hbox(b, button("Missions for this level", lambda: self.win.go("missions")), stretch_end=True))
            lay.addWidget(req)
        else:
            done = Card(kind="CardAccent", eyebrow="Top of the ladder")
            done.add(lbl("You hold the most senior role in the career ladder.", "H2"))
            done.add(lbl("Pass the CRO board simulation to unlock the seven executive paths.", "Muted"))
            done.add(hbox(button("CRO assessment", lambda: self.win.go("final"), "Primary"), stretch_end=True))
            lay.addWidget(done)
        if self.focus_mode:
            return

        # Ladder
        lay.addWidget(lbl("The ladder", "H2"))
        cards = []
        for ld in g.c.careers["levels"]:
            n = ld["level"]
            state = "done" if n < g.level else "current" if n == g.level else "future"
            c = Card(kind="CardAccent" if state == "current" else "Card" if state == "done" else "CardMuted")
            c.add(hbox(lbl(f"LEVEL {n} · {ld['stage_name'].upper()}", "Eyebrow"), "stretch",
                       badge("You are here", p.accent) if state == "current" else
                       badge("✓", p.good) if state == "done" else None))
            title = ld.get("expert_title") if path == "expert" else ld["title"]
            c.add(lbl(title, "H3"))
            c.add(lbl("\n".join("• " + r for r in ld["responsibilities"][:3]), "Small"))
            if ld.get("unlocks"):
                c.add(lbl("Unlocks: " + ", ".join(ld["unlocks"][:3]), "Small"))
            cards.append(c)
        lay.addLayout(grid(cards, 5))

        # Executive paths
        lay.addWidget(lbl("Executive paths", "H2"))
        lay.addWidget(lbl("After the CRO board simulation, seven executive roles open. Each needs specific "
                          "competency strengths and has its own assessment mission.", "Muted"))
        ecards = []
        for ep in g.exec_paths():
            c = Card(kind="CardAccent" if ep["completed"] else "Card")
            st = "Completed" if ep["completed"] else "Ready" if ep["ready"] else \
                ("Locked: pass CRO assessment" if not ep["unlocked"] else "Build competencies")
            c.add(hbox(lbl(ep["title"], "H3"), "stretch",
                       badge(st, p.good if ep["completed"] or ep["ready"] else p.muted)))
            c.add(lbl(ep["description"], "Small"))
            c.add(lbl("Needs: " + ", ".join(f"{k} {v}" for k, v in ep["minima"].items()), "Small"))
            if ep["competency_gaps"]:
                c.add(lbl("Gaps: " + ", ".join(ep["competency_gaps"]), "Small"))
            if ep["unlocked"]:
                c.add(hbox(button("Open assessment", lambda m=ep["assessment"]: self.win.go("mission", mission_id=m)),
                           stretch_end=True))
            ecards.append(c)
        lay.addLayout(grid(ecards, 3))

        # Lateral moves
        moves = Card(eyebrow="Lateral moves")
        moves.add(lbl("Change specialist track or move to a different organisation and industry. Your level, "
                      "competencies, achievements and mission record come with you; the new organisation's "
                      "state starts fresh. A backup is taken first.", "Muted"))
        self.track_combo = QComboBox()
        for t in g.c.careers["tracks"]:
            self.track_combo.addItem(t["label"], t["id"])
        self.track_combo.setCurrentIndex(self.track_combo.findData(g.profile["track"]))
        self.org_combo = QComboBox()
        for o in g.c.orgs.values():
            if o["id"] != g.profile["org_id"]:
                self.org_combo.addItem(f"{o['name']} ({o['industry_label']}, {o['currency']})", o["id"])
        moves.add(hbox(lbl("Track", wrap=False), self.track_combo, button("Change track", self.change_track),
                       "stretch"))
        moves.add(hbox(lbl("Organisation", wrap=False), self.org_combo,
                       button("Move organisation", self.change_org), "stretch"))
        lay.addWidget(moves)

    def change_track(self) -> None:
        t = self.track_combo.currentData()
        if t == self.game.profile["track"]:
            self.notify("That is already your track.")
            return
        self.game.change_track(t)
        self.game.check_achievements()
        self.notify(f"You moved to the {self.track_combo.currentText()} track.")
        self.win.update_chrome()
        self.refresh()

    def change_org(self) -> None:
        oid = self.org_combo.currentData()
        name = self.game.c.orgs[oid]["name"]
        if not self.dialogs.confirm(self, "Move organisation",
                                    f"Join {name}? The current organisation's simulation (register, KRIs, budget) "
                                    "stays in a backup; your career record moves with you."):
            return
        try:
            g = self.game.change_organisation(oid)
        except ValueError as exc:
            self.fail(exc)
            return
        self.win.game = g
        g.check_achievements()
        self.win.go("dashboard")
        self.notify(f"Welcome to {name}.")

    def interview(self) -> None:
        dlg = PromotionDialog(self)
        dlg.exec()
        self.win.update_chrome()
        self.refresh()


class PromotionDialog(QDialog):
    """Interview (three questions) followed by salary negotiation."""

    def __init__(self, screen: CareerScreen):
        super().__init__(screen)
        self.s = screen
        self.g = screen.game
        self.setWindowTitle("Promotion interview")
        self.resize(760, 560)
        self.questions = self.g.interview_questions()
        rng = random.Random(stable_seed(self.g.profile["seed"], "iv-order", self.g.level,
                                        self.g.counters().get("interviews", 0)))
        self.orders = []
        for q in self.questions:
            idx = list(range(len(q["options"])))
            rng.shuffle(idx)
            self.orders.append(idx)
        self.groups: list[QButtonGroup] = []
        self.outcome: dict | None = None
        lay = QVBoxLayout(self)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)

        nxt = self.g.next_level_def()
        page = QWidget()
        pv = QVBoxLayout(page)
        pv.addWidget(lbl(f"Interview for {nxt.title_for(self.g.profile['career_path'])}", "H1"))
        pv.addWidget(lbl("Choose the answer that best reflects how you would respond. The panel is looking for "
                         "specific, evidenced, honest answers.", "Muted"))
        for qi, q in enumerate(self.questions):
            pv.addWidget(lbl(f"{qi + 1}. {q['prompt']}", "H3"))
            grp = QButtonGroup(self)
            for pos, oi in enumerate(self.orders[qi]):
                rb = QRadioButton(q["options"][oi]["text"])
                rb.setProperty("oi", oi)
                grp.addButton(rb, pos)
                pv.addWidget(rb)
            self.groups.append(grp)
        path_box = QHBoxLayout()
        path_box.addWidget(lbl("Career path for the new role:", wrap=False))
        self.path = QComboBox()
        self.path.addItem("Management (lead people and functions)", "management")
        self.path.addItem("Expert (deep technical specialism)", "expert")
        self.path.setCurrentIndex(self.path.findData(self.g.profile["career_path"]))
        path_box.addWidget(self.path)
        path_box.addStretch(1)
        pv.addLayout(path_box)
        pv.addWidget(lbl("Salary negotiation: where in the illustrative range will you ask?", "H3"))
        rng_range = self.g.salary_range(nxt)
        self.range = rng_range
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(50)
        self.slider.setAccessibleName("Salary ask position")
        self.ask_label = lbl("", "Small")
        self.slider.valueChanged.connect(self._ask_changed)
        pv.addWidget(self.slider)
        pv.addWidget(self.ask_label)
        self._ask_changed(50)
        pv.addWidget(lbl(f"Your evidence strength (core mission average): {self.g.evidence_strength() * 100:.0f}%. "
                         "Asks well beyond what your record supports tend to be countered.", "Small"))
        self.err = lbl("", "Bad")
        pv.addWidget(self.err)
        pv.addStretch(1)
        pv.addLayout(hbox("stretch", button("Cancel", self.reject), button("Submit answers", self.submit, "Primary")))
        self.stack.addWidget(page)
        self.result_page = QWidget()
        self.result_lay = QVBoxLayout(self.result_page)
        self.stack.addWidget(self.result_page)

    def _ask_changed(self, v: int) -> None:
        r = self.range
        amt = r["min"] + v / 100 * (r["max"] - r["min"])
        self.ask_label.setText(f"Ask: {self.g.money(amt, False)} ({v}% of range "
                               f"{self.g.money(r['min'], False)} to {self.g.money(r['max'], False)}). Illustrative.")

    def answers(self) -> list[tuple[dict, int]] | None:
        out = []
        for q, grp in zip(self.questions, self.groups):
            b = grp.checkedButton()
            if b is None:
                return None
            out.append((q, int(b.property("oi"))))
        return out

    def choose_best(self) -> None:
        """Used by automated UI tests."""
        for q, grp in zip(self.questions, self.groups):
            best = max(range(len(q["options"])), key=lambda i: q["options"][i]["quality"])
            for b in grp.buttons():
                if int(b.property("oi")) == best:
                    b.setChecked(True)

    def submit(self) -> None:
        ans = self.answers()
        if ans is None:
            self.err.setText("Please answer every question.")
            return
        try:
            res = self.g.promote(ans, self.slider.value() / 100, self.path.currentData())
        except ValueError as exc:
            self.err.setText(str(exc))
            return
        self.outcome = res
        lay = self.result_lay
        if res["promoted"]:
            lay.addWidget(lbl("PROMOTED", "Eyebrow"))
            lay.addWidget(lbl(f"Congratulations: {res['title']}", "H1"))
            n = res["negotiation"]
            lay.addWidget(lbl(f"Agreed base salary: {self.g.money(n['salary'], False)} (illustrative). {n['note']}",
                              "Body"))
        else:
            lay.addWidget(lbl("NOT THIS TIME", "Eyebrow"))
            lay.addWidget(lbl("The panel was not yet convinced.", "H1"))
            lay.addWidget(lbl(res["note"], "Body"))
        lay.addWidget(lbl(f"Interview score: {res['interview_score'] * 100:.0f}%", "H3"))
        for (q, oi), fb in zip(ans, res["feedback"]):
            lay.addWidget(lbl(q["prompt"], "H3"))
            lay.addWidget(lbl(f"Your answer: {q['options'][oi]['text']}\nPanel feedback: {fb}", "Small"))
        lay.addStretch(1)
        lay.addLayout(hbox("stretch", button("Close", self.accept, "Primary")))
        self.stack.setCurrentWidget(self.result_page)
