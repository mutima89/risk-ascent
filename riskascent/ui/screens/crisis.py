"""Crisis command centre: the twelve authored crisis scenarios and a seeded,
escalating multi-threat exercise played in turns with limited capacity."""

from __future__ import annotations

from dataclasses import asdict

from PySide6.QtWidgets import QCheckBox

from ...core.crisis import ACTIONS, CrisisExercise, Threat
from ..base import Screen
from ..widgets import Card, badge, bar, button, grid, hbox, lbl, vbox
from .. import theme


def save_exercise(game, ex: CrisisExercise | None) -> None:
    with game.db.tx():
        game.db.meta_set("crisis_active", asdict(ex) if ex else None)


def load_exercise(game) -> CrisisExercise | None:
    d = game.db.meta_get("crisis_active")
    if not d:
        return None
    d = dict(d)
    d["threats"] = [Threat(**t) for t in d["threats"]]
    return CrisisExercise(**d)


class CrisisScreen(Screen):
    key = "crisis"
    title = "Crisis command"

    def populate(self) -> None:
        g = self.game
        p = theme.current()
        lay = self.page.layout_
        lay.addWidget(lbl("CRISIS COMMAND CENTRE", "Eyebrow"))
        lay.addWidget(lbl("Decide under pressure", "H1"))
        ex = load_exercise(g)
        self.ex = ex
        if ex is not None:
            self.exercise_view(ex)
            return
        intro = Card(kind="CardAccent", eyebrow="Escalating crisis exercise")
        intro.add(lbl("Several threats arrive at once and grow every turn. You have limited response capacity. "
                      "Investigate to learn the true severity, contain what matters most, communicate to protect "
                      "reputation, and escalate when you need executive resources. Each exercise is generated from "
                      "a logged seed, so it can be replayed exactly.", "Body"))
        intro.add(lbl(" · ".join(f"{a['label']} ({a['cost']} capacity): {a['desc']}" for a in ACTIONS.values()),
                      "Small"))
        intro.add(hbox(button("Start a new exercise", self.start, "Primary"), stretch_end=True))
        lay.addWidget(intro)
        c = g.counters()
        lay.addWidget(lbl(f"Exercises completed: {c.get('crisis_exercises', 0)} · won: {c.get('crisis_wins', 0)} "
                          f"· flawless: {c.get('crisis_flawless', 0)}", "Small"))
        if self.focus_mode:
            return
        lay.addWidget(lbl("Crisis scenarios", "H2"))
        cards = []
        for s in g.mission_status():
            m = s["mission"]
            if m["type"] != "crisis":
                continue
            cd = Card(kind="Card" if s["available"] else "CardMuted")
            cd.add(hbox(badge(f"L{m['level']}", p.bad), "stretch",
                        badge(f"Best {s['best'] * 100:.0f}%", p.good) if s["best"] is not None else None))
            cd.add(lbl(m["title"], "H3"), lbl(m["objective"], "Small"), "stretch")
            if s["available"]:
                cd.add(hbox(button("Resume" if s["active_run"] else "Play",
                                   lambda mid=m["id"]: self.win.go("mission", mission_id=mid),
                                   "Primary" if s["best"] is None else None), stretch_end=True))
            else:
                cd.add(lbl("\U0001F512 " + s["reason"], "Small"))
            cd.setMinimumHeight(170)
            cards.append(cd)
        lay.addLayout(grid(cards, 3))

    def start(self) -> None:
        ex = self.game.start_crisis_exercise()
        save_exercise(self.game, ex)
        self.refresh()

    def exercise_view(self, ex: CrisisExercise) -> None:
        p = theme.current()
        lay = self.page.layout_
        if ex.finished:
            self.finish_view(ex)
            return
        top = Card(kind="CardAccent")
        top.add(hbox(lbl(f"Turn {ex.turn} of {ex.turns}", "H2"), "stretch",
                     lbl(f"Capacity this turn: {ex.capacity()}", "Gold", wrap=False)))
        top.add(hbox(vbox(lbl("Reputation", "Small"), bar(ex.reputation, 100, "Good" if ex.reputation >= 50 else "Bad")),
                     vbox(lbl("Credibility with executives", "Small"),
                          bar(ex.credibility, 100, "Good" if ex.credibility >= 50 else "Warn"))))
        top.add(lbl(f"Seed {ex.seed}. Estimates for uninvestigated threats can be wrong by up to ±45%.", "Small"))
        lay.addWidget(top)
        self.boxes: list[tuple[QCheckBox, str, str]] = []
        cards = []
        for t in ex.active():
            sev = t.visible()
            col = p.bad if sev >= 70 else p.warn if sev >= 40 else p.medium
            c = Card()
            c.add(hbox(badge(t.domain, p.info), "stretch",
                       badge(("Severity " if t.investigated else "Estimated ") + f"{sev:.0f}", col, filled=True)))
            c.add(lbl(t.name, "H3"))
            c.add(bar(sev, 100, "Bad" if sev >= 70 else "Warn"))
            c.add(lbl("Facts established" if t.investigated else "Facts not yet established", "Small"))
            for a, info in ACTIONS.items():
                cb = QCheckBox(f"{info['label']} ({info['cost']})")
                cb.setToolTip(info["desc"])
                cb.toggled.connect(self._update_cost)
                self.boxes.append((cb, a, t.tid))
                c.add(cb)
            cards.append(c)
        lay.addLayout(grid(cards, 3))
        resolved = [t.name for t in ex.threats if t.resolved]
        failed = [t.name for t in ex.threats if t.failed]
        if resolved or failed:
            lay.addWidget(lbl(("Under control: " + ", ".join(resolved) + ". " if resolved else "")
                              + ("Lost control: " + ", ".join(failed) + "." if failed else ""), "Small"))
        self.cost_label = lbl("", "H3")
        lay.addLayout(hbox(self.cost_label, "stretch", button("Abandon exercise", self.abandon, "Danger"),
                           button("Execute turn", self.play, "Primary", shortcut="Ctrl+Return")))
        self._update_cost()
        if ex.log:
            lay.addWidget(Card("Operations log").add(lbl("\n".join(ex.log[-14:]), "Small")))

    def _update_cost(self, *_):
        cost = sum(ACTIONS[a]["cost"] for cb, a, _ in self.boxes if cb.isChecked())
        cap = self.ex.capacity()
        self.cost_label.setText(f"Plan uses {cost} of {cap} capacity" + ("  (over capacity)" if cost > cap else ""))
        self.cost_label.setObjectName("Bad" if cost > cap else "H3")
        self.cost_label.setStyleSheet("")

    def plan(self) -> list[tuple[str, str]]:
        return [(a, tid) for cb, a, tid in self.boxes if cb.isChecked()]

    def play(self) -> None:
        ex = self.ex
        try:
            lines = ex.play_turn(self.plan())
        except ValueError as exc:
            self.fail(exc)
            return
        save_exercise(self.game, ex)
        self.notify(" ".join(lines[:3]))
        self.refresh()

    def abandon(self) -> None:
        if self.dialogs.confirm(self, "Abandon exercise", "Abandon this exercise? It will not be scored."):
            save_exercise(self.game, None)
            self.refresh()

    def finish_view(self, ex: CrisisExercise) -> None:
        p = theme.current()
        sc = self.game.finish_crisis_exercise(ex)
        save_exercise(self.game, None)
        lay = self.page.layout_
        c = Card(kind="CardAccent", eyebrow="Exercise debrief")
        col = p.good if sc["score"] >= 0.7 else p.warn if sc["score"] >= 0.5 else p.bad
        v = lbl(f"{sc['score'] * 100:.0f}%", "Value")
        v.setStyleSheet(f"color:{col};font-size:28pt;")
        c.add(v)
        c.add(lbl(f"Containment {sc['containment'] * 100:.0f}% · prioritisation {sc['prioritisation'] * 100:.0f}% "
                  f"(turns where you acted on the most severe threat) · reputation {sc['reputation']:.0f} · "
                  f"credibility {sc['credibility']:.0f} · threats lost {sc['failed']}", "Body"))
        tips = []
        if sc["prioritisation"] < 0.7:
            tips.append("Act on the most severe threat every turn. Investigating first makes containment twice as "
                        "effective.")
        if sc["failed"]:
            tips.append("A threat reaching 100 is a major impact. When capacity is short, escalate a serious threat "
                        "early to gain resources.")
        if sc["credibility"] < 60:
            tips.append("Escalating minor threats costs credibility. Escalate when severity is genuinely high.")
        if sc["reputation"] < 60:
            tips.append("Communicate on threats with public visibility; it halves reputational spread.")
        c.add(lbl("\n".join("• " + t for t in tips) or "A well-run exercise: clear priorities and proportionate "
                  "escalation.", "Body"))
        c.add(lbl(f"Seed {ex.seed}. Same seed and same decisions produce the same result.", "Small"))
        c.add(hbox(button("Back to command centre", self.refresh, "Primary"), stretch_end=True))
        lay.addWidget(c)
        lay.addWidget(Card("Operations log").add(lbl("\n".join(ex.log), "Small")))
