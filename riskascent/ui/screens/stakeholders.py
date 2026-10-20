"""Stakeholder communication: inbox, replies and the trust map."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QPushButton

from ..base import Screen
from ..widgets import Card, badge, bar, button, clear_layout, grid, hbox, lbl, vbox
from .. import theme


class StakeholdersScreen(Screen):
    key = "stakeholders"
    title = "Stakeholders"

    def __init__(self, win):
        super().__init__(win)
        self.msg_id: int | None = None
        self.last_feedback: str = ""

    def populate(self) -> None:
        g = self.game
        p = theme.current()
        lay = self.page.layout_
        msgs = g.list_messages()
        unread = sum(1 for m in msgs if m["status"] == "unread")
        lay.addWidget(lbl("STAKEHOLDER COMMUNICATION", "Eyebrow"))
        lay.addWidget(lbl(f"Inbox · {unread} unread", "H1"))
        lay.addWidget(lbl("Each executive has priorities, a preferred style and things that frustrate them. The same "
                          "message lands differently with a CFO than with a COO.", "Muted"))
        if self.msg_id not in {m["id"] for m in msgs}:
            pending = [m for m in msgs if m["status"] != "replied" and m["options"]]
            self.msg_id = (pending or msgs or [{"id": None}])[0]["id"]

        inbox = Card("Messages")
        self.list = QListWidget()
        self.list.setAccessibleName("Messages")
        for m in msgs:
            sender = g.person(m["sender"])
            mark = "● " if m["status"] == "unread" else "↩ " if m["status"] == "replied" else "   "
            it = QListWidgetItem(f"{mark}{m['subject']}\n    {sender['name']} · month {m['period']}")
            it.setData(Qt.UserRole, m["id"])
            self.list.addItem(it)
            if m["id"] == self.msg_id:
                self.list.setCurrentItem(it)
        self.list.setMinimumHeight(420)
        self.list.currentItemChanged.connect(self._selected)
        inbox.add(self.list)
        self.reader = Card()
        self._render_message()
        lay.addLayout(grid([inbox, self.reader], 2))

        if self.focus_mode:
            return
        lay.addWidget(lbl("Trust map", "H2"))
        trust = g.trust()
        cards = []
        for role in g.c.roles:
            if role in ("analyst",):
                continue
            pp = g.person(role)
            t = trust.get(role, 50)
            c = Card()
            c.add(hbox(lbl(pp["name"], "H3"), "stretch", lbl(f"{t:.0f}", "Gold" if t >= 70 else "Small", wrap=False)))
            c.add(lbl(pp["title"], "Small"))
            c.add(bar(t, 100, "Good" if t >= 60 else "Warn" if t >= 40 else "Bad", f"Trust {t:.0f}"))
            c.add(lbl(pp.get("style", ""), "Small"))
            if pp.get("prefers"):
                c.add(lbl("Responds to: " + ", ".join(pp["prefers"]) + (" · dislikes: " + ", ".join(pp["dislikes"])
                                                                        if pp.get("dislikes") else ""), "Small"))
            cards.append(c)
        lay.addLayout(grid(cards, 4))

    def _selected(self, cur, _prev):
        if cur is None:
            return
        self.msg_id = cur.data(Qt.UserRole)
        self.last_feedback = ""
        self.game.mark_read(self.msg_id)
        self.win.update_chrome()
        self._render_message()

    def _render_message(self) -> None:
        g = self.game
        clear_layout(self.reader.body)
        m = next((x for x in g.list_messages() if x["id"] == self.msg_id), None)
        if m is None:
            self.reader.add(lbl("No messages yet.", "Muted"))
            return
        if m["status"] == "unread":
            g.mark_read(m["id"])
        sender = g.person(m["sender"])
        self.reader.add(lbl(f"From {sender['name']}, {sender['title']} · month {m['period']}", "Small"),
                        lbl(m["subject"], "H2"), lbl(m["body"], "Body"))
        if m["status"] == "replied":
            self.reader.add(lbl("Your reply", "H3"), lbl(m.get("reply") or "", "Body"))
            if self.last_feedback:
                self.reader.add(lbl(self.last_feedback, "Gold"))
        elif m["options"]:
            self.reader.add(lbl("How do you respond?", "H3"))
            for i, o in enumerate(m["options"]):
                b = QPushButton(o["text"])
                b.setObjectName("Option")
                b.setStyleSheet("text-align:left;")
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, i=i: self.reply(i))
                self.reader.add(b)
        else:
            self.reader.add(lbl("No reply needed.", "Small"))
        self.reader.add("stretch")

    def reply(self, i: int) -> None:
        try:
            res = self.game.reply_message(self.msg_id, i)
        except ValueError as exc:
            self.fail(exc)
            return
        self.game.check_achievements()
        d = res["trust_delta"]
        self.last_feedback = f"Trust {'+' if d >= 0 else ''}{d:.0f}. {res['feedback']}"
        self.notify(self.last_feedback)
        self.win.update_chrome()
        self.refresh()
