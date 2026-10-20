"""Base class for screens."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .widgets import DIALOGS, Page, clear_layout

if TYPE_CHECKING:
    from ..game import Game
    from .main_window import MainWindow


class Screen(QWidget):
    """A navigable screen. Subclasses implement populate() (rebuilt on every
    refresh) or override refresh() when they keep form state."""

    key = ""
    title = ""

    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win = win
        self.page = Page()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.page)
        self.focus_mode = False

    @property
    def game(self) -> "Game":
        assert self.win.game is not None
        return self.win.game

    @property
    def dialogs(self):
        return DIALOGS

    def open(self, **kwargs) -> None:
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.page.layout_)
        self.populate()
        self.page.layout_.addStretch(1)
        self.page.fit()

    def populate(self) -> None:  # pragma: no cover - overridden
        pass

    def set_focus_mode(self, on: bool) -> None:
        self.focus_mode = on
        self.refresh()

    def checklist(self) -> list[tuple[str, bool]]:
        return []

    def speak_text(self) -> str:
        """Text read aloud by text-to-speech: visible headings and body labels."""
        parts = []
        for w in self.findChildren(QLabel):
            if w.isVisible() and w.text() and w.objectName() in ("H1", "H2", "H3", "Body", "Muted", ""):
                t = w.text()
                if "<" in t:
                    import re
                    t = re.sub(r"<[^>]+>", " ", t)
                parts.append(t)
            if len(parts) > 40:
                break
        return ". ".join(parts)

    def notify(self, text: str, kind: str = "info") -> None:
        self.win.toast(text, kind)

    def fail(self, exc: Exception | str) -> None:
        self.dialogs.error(self, "Please check", str(exc))
