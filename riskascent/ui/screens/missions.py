"""Mission selection: filterable mission cards and weekly challenges."""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox

from ..base import Screen
from ..widgets import Card, badge, button, grid, hbox, lbl
from .. import theme
from .mission import TYPE_LABELS

FILTERS = [("level", "Available at my level"), ("all", "All missions"), ("career", "Career assignments"),
           ("capstone", "Capstones"), ("crisis", "Crisis scenarios"), ("side", "Side missions and packs"),
           ("executive", "Executive paths"), ("todo", "Not yet completed"), ("done", "Completed")]


class MissionsScreen(Screen):
    key = "missions"
    title = "Missions"

    def __init__(self, win):
        super().__init__(win)
        self.filter = "level"

    def populate(self) -> None:
        g = self.game
        p = theme.current()
        lay = self.page.layout_
        lay.addWidget(lbl("MISSIONS", "Eyebrow"))
        lay.addWidget(lbl("Choose your next assignment", "H1"))
        lvl = g.level_def()
        req = set(lvl.required_missions + ([lvl.capstone] if lvl.capstone else []))
        combo = QComboBox()
        for k, label in FILTERS:
            combo.addItem(label, k)
        combo.setCurrentIndex(combo.findData(self.filter))
        combo.currentIndexChanged.connect(lambda _: self._set_filter(combo.currentData()))
        combo.setAccessibleName("Mission filter")
        lay.addLayout(hbox(lbl("Show", wrap=False), combo, "stretch",
                           lbl("◆ = required for your next promotion", "Small", wrap=False)))

        if not self.focus_mode:
            wk = g.weekly_challenges()
            wc = Card(eyebrow="Weekly challenges (optional)")
            if not wk:
                wc.add(lbl("Complete a mission to unlock replayable challenges with different constraints. "
                           "Skipping a week costs nothing.", "Muted"))
            else:
                wc.add(lbl("Replays with a twist. They refresh each week and are always optional.", "Small"))
                for w in wk:
                    wc.add(hbox(lbl(f"{w['title']}", "H3"), badge(w["label"], p.gold), "stretch",
                                button("Play", lambda w=w: self.win.go("mission", mission_id=w["mission_id"],
                                                                        modifier=w["modifier"]))))
            lay.addWidget(wc)

        cards = []
        for s in g.mission_status():
            m = s["mission"]
            f = self.filter
            if f == "level" and not (s["available"] and (m["level"] >= g.level - 1 or m["id"] in req
                                                         or s["best"] is None)):
                continue
            if f in TYPE_LABELS and m["type"] != f:
                continue
            if f == "todo" and s["best"] is not None:
                continue
            if f == "done" and s["best"] is None:
                continue
            cards.append(self.card(s, m["id"] in req))
        if not cards:
            lay.addWidget(lbl("No missions match this filter.", "Muted"))
        lay.addLayout(grid(cards, 3))

    def _set_filter(self, f: str) -> None:
        self.filter = f
        self.refresh()

    def card(self, s: dict, required: bool) -> Card:
        p = theme.current()
        m = s["mission"]
        kind = "CardAccent" if s["active_run"] else "Card" if s["available"] else "CardMuted"
        c = Card(kind=kind)
        typ = {"crisis": p.bad, "capstone": p.gold, "executive": p.gold, "side": p.info}.get(m["type"], p.accent)
        c.add(hbox(badge(TYPE_LABELS.get(m["type"], m["type"]), typ), lbl(f"L{m['level']}", "Small", wrap=False),
                   "stretch", lbl("◆" if required else "", "Gold", wrap=False)))
        c.add(lbl(m["title"], "H3"))
        c.add(lbl(m["objective"], "Small"))
        meta = f"{m['duration']} · {len(m['steps'])} decisions · {m['xp']} XP"
        if s["recommended"]:
            meta += " · suits your track"
        c.add(lbl(meta, "Small"))
        if s["best"] is not None:
            col = p.good if s["best"] >= 0.7 else p.warn
            c.add(hbox(badge(f"Best {s['best'] * 100:.0f}%", col), stretch_end=True))
        c.add("stretch")
        if s["active_run"]:
            c.add(hbox(button("Resume", lambda: self.win.go("mission", mission_id=m["id"]), "Primary"),
                       stretch_end=True))
        elif s["available"]:
            c.add(hbox(button("Replay" if s["best"] is not None else "Open briefing",
                              lambda: self.win.go("mission", mission_id=m["id"]),
                              None if s["best"] is not None else "Primary"), stretch_end=True))
        else:
            c.add(lbl("\U0001F512 " + s["reason"], "Small"))
        c.setMinimumHeight(200)
        return c
