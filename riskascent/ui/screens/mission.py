"""Mission flow: briefing -> investigation workspace -> decisions -> debrief.

Every submitted step is checkpointed to the save immediately, so closing the
app mid-mission resumes at the same point."""

from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QListWidget, QListWidgetItem, QPlainTextEdit, QSlider,
                               QSplitter, QTextBrowser, QVBoxLayout, QWidget)

from ...core.competency import COMPETENCIES
from ...core.risk_engine import RiskMatrix
from ...core.difficulty import hint_auto_open, hint_available
from ...core.util import render
from ..base import Screen
from ..widgets import Card, Checklist, badge, bar, button, clear_layout, grid, hbox, lbl, vbox
from .. import theme
from .step_widgets import make_step_widget

TYPE_LABELS = {"career": "Career assignment", "capstone": "Capstone assessment", "crisis": "Crisis scenario",
               "side": "Side mission", "executive": "Executive path", "weekly": "Weekly challenge"}

GENERIC_HINTS = {
    "choice": "Which option deals with the cause, not just the symptom, and is proportionate to the evidence?",
    "multi": "Select only what is relevant: every unnecessary selection costs credit, like wasted effort.",
    "numeric": "Write out the formula with units first. Check whether values are annual, monthly or one-off.",
    "classify": "Take each item on its own and ask which definition it fits best.",
    "rank": "Rank by consequence first (life safety, legal, financial), then by urgency.",
    "allocate": "Compare value per unit of cost, then check whether a different combination fits the budget better.",
    "matrix": "Rate inherent risk as if no controls existed; residual reflects only controls that actually work.",
    "write": "Lead with the point, state the evidence, give the recommendation and who must act.",
}
APPROACH = {
    "numeric": ["Identify the quantities in the prompt and documents.", "Choose the formula.",
                "Convert units (monthly vs annual, % vs decimal).", "Calculate and sanity-check the size."],
    "write": ["One sentence: what happened or what the risk is.", "One sentence: the evidence.",
              "One sentence: the recommendation and the owner.", "Remove anything the reader does not need."],
    "allocate": ["Note the budget.", "Find the highest value-for-cost items.", "Try two or three combinations.",
                 "Check nothing important is left out for a small saving."],
    "matrix": ["Rate likelihood without controls.", "Rate impact without controls.",
               "Ask which controls are proven to work.", "Reduce likelihood (preventive) or impact (detective/corrective)."],
    "rank": ["Find the item that could cause the worst harm.", "Order the rest by consequence.",
             "Use urgency to break ties."],
}


class MissionScreen(Screen):
    key = "mission"
    title = "Mission"

    def __init__(self, win):
        super().__init__(win)
        self.mission: dict | None = None
        self.run = None
        self.run_id: int | None = None
        self.step_widget = None
        self.last_result = None
        self.completion: dict | None = None
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._ctrl_enter)

    # ------------------------------------------------------------ lifecycle
    def open(self, mission_id: str | None = None, modifier: str | None = None, **_):
        g = self.game
        self.completion = None
        self.last_result = None
        self.modifier = modifier
        if mission_id is None:
            row = g.db.one("SELECT mission_id FROM mission_runs WHERE status='active' ORDER BY run_id DESC LIMIT 1")
            if row is None:
                if self.mission is None:
                    self.win.go("missions")
                    return
                mission_id = self.mission["id"]
            else:
                mission_id = row["mission_id"]
        self.mission = g.c.missions[mission_id]
        active = g.db.one("SELECT run_id FROM mission_runs WHERE mission_id=? AND status='active'", (mission_id,))
        if active:
            self.run_id, self.run = g.start_or_resume(mission_id)
        else:
            self.run_id, self.run = None, None
        self.title = self.mission["title"]
        self.win.crumb.setText(self.title)
        self.refresh()

    def save_now(self) -> None:
        if self.run is not None and self.run_id is not None and self.completion is None and self.win.game:
            try:
                self.win.game.save_checkpoint(self.run_id, self.run)
            except Exception:
                pass

    def _ctx(self):
        return self.game.ctx()

    def r(self, text: str) -> str:
        return render(text or "", self._ctx())

    def populate(self) -> None:
        if self.mission is None:
            return
        if self.completion is not None:
            self.show_debrief()
        elif self.run is None or self.run.phase == "briefing":
            self.show_briefing()
        elif self.run.phase == "investigation":
            self.show_investigation()
        else:
            self.show_steps()

    def phase_bar(self, current: int) -> QHBoxLayout:
        names = ["Briefing", "Investigation", "Decisions", "Debrief"]
        p = theme.current()
        items = []
        for i, n in enumerate(names):
            col = p.accent if i == current else p.good if i < current else p.muted
            items.append(badge(("✓ " if i < current else f"{i + 1}  ") + n, col, filled=i == current))
        return hbox(*items, stretch_end=True)

    # ------------------------------------------------------------ briefing
    def show_briefing(self) -> None:
        m, g = self.mission, self.game
        lay = self.page.layout_
        lay.addLayout(self.phase_bar(0))
        p = theme.current()
        lay.addWidget(lbl(f"{TYPE_LABELS.get(m['type'], m['type']).upper()} · LEVEL {m['level']}", "Eyebrow"))
        lay.addWidget(lbl(m["title"], "H1"))
        sender = g.person(m.get("from", "mentor"))
        brief = Card(kind="CardAccent")
        brief.add(lbl(f"From: {sender['name']}, {sender['title']}", "Small"),
                  lbl(self.r(m.get("subject", "")), "H3"), lbl(self.r(m["briefing"]), "Body"))
        lay.addWidget(brief)
        comps = sorted({c for s in m["steps"] for c in (s.get("competencies") or [])})
        info = Card()
        info.add(lbl("Objective", "H3"), lbl(m["objective"], "Body"))
        info.add(lbl(f"About {m['duration']} · {len(m['steps'])} decisions · up to {m['xp']} XP · "
                     f"{len(m.get('documents', []))} documents", "Small"))
        info.add(lbl("Assesses: " + ", ".join(COMPETENCIES.get(c, c) for c in comps), "Small"))
        sc = g.scaffolding()
        note = {"support": "Extra support is on: hints open automatically and tasks are broken into smaller steps.",
                "stretch": "Stretch mode: hints are reduced and extra, more ambiguous evidence is included.",
                "normal": ""}[sc]
        if note:
            info.add(lbl(note, "Small"))
        if self.modifier:
            info.add(lbl(f"Weekly challenge modifier: {self.modifier.replace('_', ' ')}", "Gold"))
        best = g.best_scores().get(m["id"])
        if best is not None:
            info.add(lbl(f"Your best score: {best * 100:.0f}%. Replaying gives a fresh seed for outcomes; only "
                         "improvements add (reduced) XP.", "Small"))
        lay.addWidget(info)
        st = next((s for s in g.mission_status() if s["mission"]["id"] == m["id"]), None)
        accept = self.accept_btn = button("Accept assignment", self.accept, "Primary", "Ctrl+Enter")
        if st and not st["available"]:
            accept.setEnabled(False)
            lay.addWidget(lbl(f"Not yet available: {st['reason']}", "Warn"))
        lay.addLayout(hbox(accept, button("Back to missions", lambda: self.win.go("missions")), stretch_end=True))

    def accept(self) -> None:
        g = self.game
        self.run_id, self.run = g.start_or_resume(self.mission["id"], self.modifier)
        self.run.set_phase("investigation")
        g.save_checkpoint(self.run_id, self.run)
        self.win.update_chrome()
        self.refresh()

    # ------------------------------------------------------------ investigation
    def show_investigation(self) -> None:
        m, run = self.mission, self.run
        lay = self.page.layout_
        lay.addLayout(self.phase_bar(1))
        lay.addWidget(lbl("Investigation workspace", "H1"))
        lay.addWidget(lbl("Read the evidence before you decide. Key documents are marked ★. Your notes are "
                          "saved with the mission.", "Muted"))
        docs = run.documents()
        split = QSplitter(Qt.Horizontal)
        self.doc_list = QListWidget()
        self.doc_list.setAccessibleName("Documents")
        for d in docs:
            it = QListWidgetItem(("★ " if d.get("key") else "   ") + d["title"] +
                                 ("  ✓" if d["id"] in run.state["docs_viewed"] else ""))
            it.setData(Qt.UserRole, d["id"])
            self.doc_list.addItem(it)
        self.doc_view = QTextBrowser()
        self.doc_view.setOpenExternalLinks(False)
        self.doc_view.setMinimumHeight(340)
        split.addWidget(self.doc_list)
        split.addWidget(self.doc_view)
        split.setSizes([280, 700])
        self.doc_list.currentItemChanged.connect(self._doc_selected)
        lay.addWidget(split)
        if docs:
            self.doc_list.setCurrentRow(0)
        self.notes = QPlainTextEdit(run.state.get("notes", ""))
        self.notes.setPlaceholderText("Working notes: facts, assumptions, unknowns...")
        self.notes.setMaximumHeight(110)
        self.notes.textChanged.connect(lambda: run.state.__setitem__("notes", self.notes.toPlainText()))
        lay.addWidget(Card("Notes").add(self.notes))
        iq = m.get("info_questions")
        if iq:
            card = Card("Gap analysis", self.r(iq["prompt"]))
            self.iq_boxes = []
            for o in iq["options"]:
                cb = QCheckBox(self.r(o["text"]))
                self.iq_boxes.append(cb)
                card.add(cb)
            res = run.state.get("info_result")
            if res:
                for i in run.state.get("info_answer") or []:
                    self.iq_boxes[i].setChecked(True)
                for cb in self.iq_boxes:
                    cb.setEnabled(False)
                card.add(lbl(f"{res['feedback']} ({res['score'] * 100:.0f}%) " + " ".join(res["details"]), "Small"))
            else:
                card.add(hbox(button("Submit gap analysis", self.submit_info), stretch_end=True))
            lay.addWidget(card)
        key_docs = [d for d in docs if d.get("key")]
        seen = set(run.state["docs_viewed"])
        missing = [d["title"] for d in key_docs if d["id"] not in seen]
        if missing:
            lay.addWidget(lbl(f"Not yet opened: {', '.join(missing)}. You can still proceed, but evidence you "
                              "haven't read may matter.", "Small"))
        go = button("Proceed to decisions", self.to_steps, "Primary", "Ctrl+Enter")
        if iq and not run.state.get("info_result"):
            go.setEnabled(False)
            go.setToolTip("Submit the gap analysis first.")
        lay.addLayout(hbox(go, button("Back to briefing", self.back_to_briefing), "stretch",
                           button("Save and exit", self.save_exit, "Ghost")))

    def _doc_selected(self, cur, _prev):
        if cur is None:
            return
        did = cur.data(Qt.UserRole)
        d = next(x for x in self.run.documents() if x["id"] == did)
        self.doc_view.setHtml(self.doc_html(d))
        if did not in self.run.state["docs_viewed"]:
            self.run.mark_doc(did)
            cur.setText(cur.text() + "  ✓")
            self.game.save_checkpoint(self.run_id, self.run)

    def doc_html(self, d: dict) -> str:
        p = theme.current()
        out = [f"<h2 style='color:{p.text}'>{html.escape(d['title'])}</h2>"]
        if d.get("from"):
            out.append(f"<p style='color:{p.muted}'>From: {html.escape(self.r(d['from']))}</p>")
        if d.get("body"):
            body = html.escape(self.r(d["body"])).replace("\n", "<br>")
            out.append(f"<p style='color:{p.text};line-height:140%'>{body}</p>")
        if d.get("table"):
            t = d["table"]
            out.append(f"<table cellspacing='0' cellpadding='6' style='border-collapse:collapse;color:{p.text}'>")
            out.append("<tr>" + "".join(f"<th align='left' style='background:{p.surface2};border-bottom:1px solid "
                                        f"{p.border}'>{html.escape(self.r(str(c)))}</th>" for c in t["columns"]) + "</tr>")
            for row in t["rows"]:
                out.append("<tr>" + "".join(f"<td style='border-bottom:1px solid {p.border}'>"
                                            f"{html.escape(self.r(str(c)))}</td>" for c in row) + "</tr>")
            out.append("</table>")
        return "".join(out)

    def submit_info(self) -> None:
        sel = [i for i, b in enumerate(self.iq_boxes) if b.isChecked()]
        if not sel:
            self.fail("Select at least one question.")
            return
        self.run.submit_investigation(sel)
        self.game.save_checkpoint(self.run_id, self.run)
        self.refresh()

    def to_steps(self) -> None:
        self.run.set_phase("steps")
        self.game.save_checkpoint(self.run_id, self.run)
        self.refresh()

    def back_to_briefing(self) -> None:
        self.run.set_phase("briefing")
        self.game.save_checkpoint(self.run_id, self.run)
        self.refresh()

    def save_exit(self) -> None:
        self.save_now()
        self.notify("Mission saved. Resume it any time from the dashboard or 'Current mission'.")
        self.win.go("dashboard")

    # ------------------------------------------------------------ steps
    def show_steps(self) -> None:
        run, m, g = self.run, self.mission, self.game
        lay = self.page.layout_
        lay.addLayout(self.phase_bar(2))
        step = run.current_step()
        if step is None:
            self.completion = g.complete_mission(self.run_id, run)
            self.win.update_chrome()
            clear_layout(lay)
            self.show_debrief()
            return
        idx = run.index
        body = QHBoxLayout()
        body.setSpacing(16)
        main = QVBoxLayout()
        main.setSpacing(12)
        main.addWidget(lbl(f"DECISION {idx + 1} OF {len(run.steps)}", "Eyebrow"))
        main.addWidget(bar(idx, len(run.steps)))
        prompt = lbl(self.r(step["prompt"]), "H2")
        main.addWidget(prompt)
        if step.get("to"):
            main.addWidget(lbl(f"Audience: {self.r('{shr:' + step['to'] + '}')}", "Small"))
        diff = g.difficulty()
        sc = run.scaffolding
        had_error = bool(run.state["attempts"].get(step["id"]))
        hint_text = step.get("hint") or GENERIC_HINTS.get(step["type"], "")
        if sc == "support" and step["type"] in APPROACH:
            main.addWidget(Card(eyebrow="Break it down").add(
                lbl("\n".join(f"{i + 1}. {s}" for i, s in enumerate(APPROACH[step["type"]])), "Small")))
        self.hint_box = lbl(f"Hint: {self.r(hint_text)}", "Muted")
        self.hint_box.setVisible(hint_auto_open(diff, sc) or step["id"] in run.state["hints_used"])
        main.addWidget(self.hint_box)
        self.example_box = lbl("", "Muted")
        if step.get("worked_example"):
            self.example_box.setText("Worked example: " + self.r(step["worked_example"]))
        self.example_box.setVisible(step["id"] in run.state["examples_used"])
        main.addWidget(self.example_box)

        # Mission content is authored on the standard 5x5 scale.
        self.step_widget = make_step_widget(step, self._ctx(), RiskMatrix())
        prev = run.state["answers"].get(step["id"])
        res = run.state["results"].get(step["id"])
        if prev is not None:
            self.step_widget.set_answer(prev)
        main.addWidget(self.step_widget)

        self.conf = None
        if step.get("confidence") or m["type"] in ("capstone",):
            self.conf = QSlider(Qt.Horizontal)
            self.conf.setRange(50, 100)
            self.conf.setValue(70)
            self.conf.setSingleStep(5)
            self.conf.setAccessibleName("Confidence")
            self.conf_label = lbl("", "Small")
            self.conf.valueChanged.connect(lambda v: self.conf_label.setText(
                f"How confident are you? {v}% (50% = a guess). Used only for calibration feedback, never for score."))
            self.conf.valueChanged.emit(70)
            main.addWidget(Card(eyebrow="Confidence").add(self.conf, self.conf_label))

        self.feedback = QVBoxLayout()
        main.addLayout(self.feedback)
        actions = QHBoxLayout()
        self.submit_btn = button("Submit decision", self.submit, "Primary", tip="Ctrl+Enter")
        self.next_btn = button("Next", self.next_step, "Primary", tip="Ctrl+Enter")
        self.next_btn.hide()
        actions.addWidget(self.submit_btn)
        actions.addWidget(self.next_btn)
        hb = button("Show hint", self.show_hint)
        hb.setEnabled(bool(hint_text) and hint_available(diff, sc, had_error))
        if not hb.isEnabled():
            hb.setToolTip("Executive difficulty: hints appear after a first incorrect attempt.")
        actions.addWidget(hb)
        if step.get("worked_example") and diff.worked_examples:
            actions.addWidget(button("Worked example", self.show_example,
                                     tip="Shows a solved similar task. Competency credit for this step is weighted lower."))
        actions.addStretch(1)
        actions.addWidget(button("Documents", self.view_docs, "Ghost"))
        actions.addWidget(button("Save and exit", self.save_exit, "Ghost"))
        main.addLayout(actions)
        if res and res["final"]:
            self.show_result(res)
        body.addLayout(main, 3)

        if not self.focus_mode:
            side = QVBoxLayout()
            ck = Checklist("Mission checklist")
            items = [("Briefing read", True), ("Evidence reviewed", bool(run.state["docs_viewed"]))]
            for i, s in enumerate(run.steps):
                done = s["id"] in run.state["results"] and run.state["results"][s["id"]]["final"]
                items.append((f"Decision {i + 1}: {_short(self.r(s['prompt']))}", done))
            items.append(("Debrief", False))
            ck.set_items(items, current=idx + 2)
            side.addWidget(ck)
            side.addStretch(1)
            sw = QWidget()
            sw.setLayout(side)
            sw.setMaximumWidth(320)
            body.addWidget(sw, 1)
        lay.addLayout(body)

    def show_hint(self) -> None:
        self.run.use_hint(self.run.current_step()["id"])
        self.hint_box.show()
        self.game.save_checkpoint(self.run_id, self.run)

    def show_example(self) -> None:
        self.run.use_hint(self.run.current_step()["id"], example=True)
        self.example_box.show()
        self.game.save_checkpoint(self.run_id, self.run)

    def view_docs(self) -> None:
        self.run.set_phase("investigation")
        self.game.save_checkpoint(self.run_id, self.run)
        self.refresh()

    def _ctrl_enter(self) -> None:
        # One screen-level shortcut dispatches by phase; per-button shortcuts would be ambiguous.
        if self.completion is not None:
            return
        if self.run is None or self.run.phase == "briefing":
            btn = getattr(self, "accept_btn", None)
            if self.mission is not None and btn is not None and btn.isEnabled():
                self.accept()
            return
        if self.run.phase == "investigation":
            self.to_steps()
            return
        if self.run.phase != "steps":
            return
        if self.next_btn.isVisible():
            self.next_step()
        elif self.submit_btn.isVisible() and self.submit_btn.isEnabled():
            self.submit()

    def submit(self) -> None:
        step = self.run.current_step()
        try:
            ans = self.step_widget.answer()
            conf = self.conf.value() / 100 if self.conf is not None else None
            res = self.run.submit(step["id"], ans, conf)
        except ValueError as exc:
            self.fail(exc)
            return
        self.game.save_checkpoint(self.run_id, self.run)
        self.show_result(res.to_dict())

    def show_result(self, res: dict) -> None:
        p = theme.current()
        clear_layout(self.feedback)
        score = res["score"]
        kind = "CardAccent"
        card = Card(kind=kind)
        if not res["final"]:
            card.add(lbl(res["feedback"], "Warn"))
            card.add(hbox(button("Try again", self.retry, "Primary"), stretch_end=True))
            self.feedback.addWidget(card)
            self.submit_btn.hide()
            return
        verdict = "Strong" if score >= 0.85 else "Good" if score >= 0.67 else "Partly right" if score >= 0.34 else "Weak"
        col = p.good if score >= 0.67 else p.warn if score >= 0.34 else p.bad
        card.add(hbox(badge(f"{verdict} · {score * 100:.0f}%", col, filled=True), "stretch"))
        card.add(lbl(res["feedback"], "Body"))
        for d in res.get("details", []):
            if d:
                card.add(lbl("• " + d, "Small"))
        if res.get("correct_answer"):
            card.add(lbl("Stronger answer: " + res["correct_answer"], "Small"))
        if res.get("outcome"):
            card.add(lbl("What happened: " + res["outcome"], "Body"))
        if res.get("luck"):
            card.add(lbl("Judgement vs luck: " + res["luck"], "Gold"))
        if res.get("confidence") is not None:
            ok = res.get("correct")
            card.add(lbl(f"You were {res['confidence'] * 100:.0f}% confident and "
                         f"{'right' if ok else 'not right'}.", "Small"))
        self.feedback.addWidget(card)
        self.step_widget.lock()
        self.submit_btn.hide()
        self.next_btn.setText("Finish and debrief" if self.run.index + 1 >= len(self.run.steps) else "Next decision")
        self.next_btn.show()
        self.next_btn.setFocus()

    def retry(self) -> None:
        if hasattr(self.step_widget, "clear"):
            self.step_widget.clear()
        clear_layout(self.feedback)
        self.submit_btn.show()
        self.hint_box.setVisible(True if hint_available(self.game.difficulty(), self.run.scaffolding, True)
                                 else self.hint_box.isVisible())

    def next_step(self) -> None:
        self.run.advance()
        self.game.save_checkpoint(self.run_id, self.run)
        if self.run.current_step() is None:
            self.finish()
        else:
            self.refresh()

    def finish(self) -> None:
        g = self.game
        self.completion = g.complete_mission(self.run_id, self.run)
        self.win.update_chrome()
        self.refresh()

    # ------------------------------------------------------------ debrief
    def show_debrief(self) -> None:
        p = theme.current()
        c = self.completion
        res = c["result"]
        m = self.mission
        lay = self.page.layout_
        lay.addLayout(self.phase_bar(3))
        lay.addWidget(lbl("SCENARIO DEBRIEF", "Eyebrow"))
        lay.addWidget(lbl(m["title"], "H1"))
        score = res.score
        col = p.good if score >= 0.75 else p.warn if score >= 0.5 else p.bad
        top = Card(kind="CardAccent")
        sv = lbl(f"{score * 100:.0f}%", "Value", wrap=False)
        sv.setStyleSheet(f"font-size:30pt;color:{col};")
        top.add(hbox(sv, vbox(lbl(res.debrief.get("ending_title") or "Assignment closed", "H2"),
                              lbl(res.debrief.get("ending", ""), "Body"), spacing=2), "stretch"))
        top.add(lbl(f"+{c['xp']} XP" + ("" if c["first_completion"] else " (replay: only improvements earn XP)"),
                    "Gold"))
        lay.addWidget(top)

        ev = Card("What you did")
        for s, r in zip(self.run.steps, res.step_results):
            good = r.score >= 0.67
            ev.add(hbox(lbl("✓" if good else "✕", "Good" if good else "Bad", wrap=False),
                        lbl(_short(self.r(s["prompt"]), 90)), "stretch", lbl(f"{r.score * 100:.0f}%", "Small", wrap=False)))
            if not good and r.correct_answer:
                ev.add(lbl("   Stronger: " + r.correct_answer, "Small"))
        well = [self.r(s["prompt"]) for s, r in zip(self.run.steps, res.step_results) if r.score >= 0.85]
        lay.addWidget(ev)
        learn = Card("Why it matters")
        learn.add(lbl(res.debrief.get("summary", ""), "Body"))
        for kp in res.debrief.get("key_points", []):
            learn.add(lbl("• " + kp, "Body"))
        if res.debrief.get("stronger_approach"):
            learn.add(lbl("A stronger approach", "H3"), lbl(res.debrief["stronger_approach"], "Body"))
        if res.debrief.get("transfer"):
            learn.add(lbl("Transfer: where else this applies", "H3"), lbl(res.debrief["transfer"], "Body"))
        lay.addWidget(learn)
        if res.luck_notes:
            lk = Card("Judgement vs luck", "Decisions are scored on quality given what you knew. Outcomes are "
                      "seeded and logged, so you can see when luck, not judgement, drove the result.")
            for n in res.luck_notes:
                lk.add(lbl("• " + n, "Body"))
            lay.addWidget(lk)
        cons = Card("Consequences in the organisation")
        if c["effects"]:
            cons.add(lbl(", ".join(c["effects"]), "Small"))
        else:
            cons.add(lbl("No direct changes from this mission.", "Small"))
        for e in c["events"]:
            cons.add(lbl(f"• Month {e.get('period', '')}: {e['title']}. {e.get('text', '')[:200]}", "Small"))
        comp = Card("Competency evidence")
        for k, v in sorted(res.competency_perf.items(), key=lambda kv: -kv[1]):
            comp.add(hbox(lbl(COMPETENCIES.get(k, k), wrap=False), "stretch", lbl(f"{v * 100:.0f}%", "Small")))
            comp.add(bar(v * 100, 100, "Good" if v >= 0.67 else "Warn" if v >= 0.4 else "Bad"))
        lay.addLayout(grid([cons, comp], 2))
        if c["achievements"]:
            ac = Card("Achievements earned", kind="CardAccent")
            for a in c["achievements"]:
                ac.add(lbl(f"★ {a['name']}: {a['description']}", "Gold"))
            lay.addWidget(ac)
        btns = [button("Back to missions", lambda: self.win.go("missions"), "Primary"),
                button("Dashboard", lambda: self.win.go("dashboard")),
                button("Replay mission", self.replay)]
        if c["promotion_ready"]:
            btns.insert(0, button("You're ready for promotion", lambda: self.win.go("career"), "Primary"))
        lay.addLayout(hbox(*btns, stretch_end=True))

    def replay(self) -> None:
        mid = self.mission["id"]
        self.completion = None
        self.open(mission_id=mid)


def _short(text: str, n: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"
