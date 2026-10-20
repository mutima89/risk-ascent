"""Input widgets for each mission step type. Each exposes answer() (raising
ValueError with a friendly message when incomplete) and set_answer() so a
checkpoint can be restored and tests can drive the UI."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QGridLayout, QHBoxLayout,
                               QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

from ...core.util import fmt_money, render, stable_seed
from ..widgets import button, hbox, lbl


class StepWidget(QWidget):
    def __init__(self, step: dict, ctx: dict, matrix=None):
        super().__init__()
        self.step, self.ctx, self.matrix = step, ctx, matrix
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(8)
        self.build()

    def r(self, text: str) -> str:
        return render(text, self.ctx)

    def build(self) -> None:
        raise NotImplementedError

    def answer(self):
        raise NotImplementedError

    def set_answer(self, a) -> None:
        raise NotImplementedError

    def lock(self) -> None:
        self.setEnabled(False)


class ChoiceWidget(StepWidget):
    def build(self):
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for k, o in enumerate(self.step["options"]):
            b = QPushButton(f"{chr(65 + k)}.  {self.r(o['text'])}")
            b.setObjectName("Option")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(44)
            b.setStyleSheet("text-align:left;")
            b.setProperty("oid", o["id"])
            # Wrap long option text.
            b.setText(_wrap_text(b.text(), 110))
            self.group.addButton(b, k)
            self.buttons[o["id"]] = b
            self.lay.addWidget(b)

    def answer(self):
        b = self.group.checkedButton()
        if b is None:
            raise ValueError("Choose one option.")
        return b.property("oid")

    def set_answer(self, a):
        if a in self.buttons:
            self.buttons[a].setChecked(True)


class MultiWidget(StepWidget):
    def build(self):
        self.lay.addWidget(lbl("Select all that apply.", "Small"))
        self.boxes = []
        for o in self.step["options"]:
            cb = QCheckBox(self.r(o["text"]))
            self.boxes.append(cb)
            self.lay.addWidget(cb)

    def answer(self):
        sel = [i for i, b in enumerate(self.boxes) if b.isChecked()]
        if not sel:
            raise ValueError("Select at least one option.")
        return sel

    def set_answer(self, a):
        for i, b in enumerate(self.boxes):
            b.setChecked(i in (a or []))


class NumericWidget(StepWidget):
    def build(self):
        unit = self.step.get("unit", "number")
        cur = self.ctx.get("currency", "USD")
        self.edit = QLineEdit()
        self.edit.setValidator(QDoubleValidator(-1e15, 1e15, 6))
        self.edit.setPlaceholderText("Enter a number (no commas needed)")
        self.edit.setAccessibleName("Numeric answer")
        self.edit.setMaximumWidth(320)
        suffix = {"money": cur, "percent": "%", "ratio": "(ratio, e.g. 1.25)"}.get(unit, "")
        self.lay.addLayout(hbox(self.edit, lbl(suffix, "Muted", wrap=False), stretch_end=True))
        if unit == "percent":
            self.lay.addWidget(lbl("Enter a percentage, e.g. 12.5 for 12.5%.", "Small"))

    def answer(self):
        t = self.edit.text().replace(",", "").strip()
        if not t:
            raise ValueError("Enter a number.")
        try:
            return float(t)
        except ValueError:
            raise ValueError("That is not a number.")

    def set_answer(self, a):
        if a is not None:
            self.edit.setText(f"{float(a):.6g}" if abs(float(a)) < 1e6 else f"{float(a):.2f}")

    def clear(self):
        self.edit.clear()


class ClassifyWidget(StepWidget):
    def build(self):
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(6)
        self.combos = []
        for i, it in enumerate(self.step["items"]):
            g.addWidget(lbl(self.r(it["text"])), i, 0)
            cb = QComboBox()
            cb.addItem("Choose...", None)
            for c in self.step["categories"]:
                cb.addItem(c, c)
            cb.setAccessibleName(f"Category for item {i + 1}")
            cb.setMinimumWidth(180)
            g.addWidget(cb, i, 1)
            self.combos.append(cb)
        g.setColumnStretch(0, 1)
        self.lay.addLayout(g)

    def answer(self):
        out = {}
        for i, cb in enumerate(self.combos):
            if cb.currentData() is None:
                raise ValueError("Classify every item.")
            out[str(i)] = cb.currentData()
        return out

    def set_answer(self, a):
        for i, cb in enumerate(self.combos):
            v = (a or {}).get(str(i))
            if v is not None:
                cb.setCurrentIndex(cb.findData(v))


class RankWidget(StepWidget):
    def build(self):
        self.lay.addWidget(lbl("Drag to reorder, or select an item and use Move up / Move down. Top = highest "
                               "priority.", "Small"))
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setAccessibleName("Ranking")
        import random
        items = list(self.step["items"])
        random.Random(stable_seed("rank", self.step["id"], self.step["prompt"])).shuffle(items)
        if [i["id"] for i in items] == list(self.step["answer"]):
            items = items[::-1]
        for it in items:
            li = QListWidgetItem(self.r(it["text"]))
            li.setData(Qt.UserRole, it["id"])
            self.list.addItem(li)
        self.list.setMinimumHeight(min(320, 38 * len(items) + 12))
        self.lay.addWidget(self.list)
        self.lay.addLayout(hbox(button("Move up", lambda: self.move(-1)), button("Move down", lambda: self.move(1)),
                                stretch_end=True))
        self.list.setCurrentRow(0)

    def move(self, d: int):
        r = self.list.currentRow()
        n = r + d
        if r < 0 or not 0 <= n < self.list.count():
            return
        it = self.list.takeItem(r)
        self.list.insertItem(n, it)
        self.list.setCurrentRow(n)

    def answer(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    def set_answer(self, a):
        if not a:
            return
        texts = {self.list.item(i).data(Qt.UserRole): self.list.item(i).text() for i in range(self.list.count())}
        self.list.clear()
        for k in a:
            li = QListWidgetItem(texts[k])
            li.setData(Qt.UserRole, k)
            self.list.addItem(li)


class AllocateWidget(StepWidget):
    def build(self):
        unit = self.step.get("unit", "money")
        scale = self.ctx.get("money_scale", 1.0)
        cur = self.ctx.get("currency", "USD")

        def show(v):
            return fmt_money(v * scale, cur, compact=False) if unit == "money" else f"{v:g} {unit}"

        self.show_amount = show
        self.boxes = []
        g = QGridLayout()
        g.addWidget(lbl("Option", "Small"), 0, 0)
        g.addWidget(lbl("Cost", "Small"), 0, 1)
        g.addWidget(lbl("Risk reduction (points)", "Small"), 0, 2)
        for r, it in enumerate(self.step["items"], start=1):
            cb = QCheckBox(self.r(it["text"]))
            cb.setProperty("iid", it["id"])
            cb.toggled.connect(self.update_total)
            self.boxes.append((cb, it))
            g.addWidget(cb, r, 0)
            g.addWidget(lbl(show(it["cost"]), wrap=False), r, 1)
            g.addWidget(lbl(f"{it['value']:g}", wrap=False), r, 2)
        g.setColumnStretch(0, 1)
        self.lay.addLayout(g)
        self.total = lbl("", "H3")
        self.lay.addWidget(self.total)
        self.update_total()

    def update_total(self, *_):
        cost = sum(it["cost"] for cb, it in self.boxes if cb.isChecked())
        val = sum(it["value"] for cb, it in self.boxes if cb.isChecked())
        b = self.step["budget"]
        over = cost > b + 1e-9
        self.total.setObjectName("Bad" if over else "H3")
        self.total.setStyleSheet("")
        self.total.setText(f"Selected: {self.show_amount(cost)} of {self.show_amount(b)} budget · {val:g} points"
                           + ("  (over budget)" if over else ""))

    def answer(self):
        sel = [it["id"] for cb, it in self.boxes if cb.isChecked()]
        if not sel:
            raise ValueError("Select at least one option.")
        return sel

    def set_answer(self, a):
        for cb, it in self.boxes:
            cb.setChecked(it["id"] in (a or []))


class MatrixWidget(StepWidget):
    LABELS = {"l": "Inherent likelihood", "i": "Inherent impact", "rl": "Residual likelihood",
              "ri": "Residual impact"}

    def build(self):
        m = self.matrix
        g = QGridLayout()
        self.combos = {}
        for r, key in enumerate(k for k in ("l", "i", "rl", "ri") if k in self.step["expected"]):
            g.addWidget(lbl(self.LABELS[key], wrap=False), r, 0)
            cb = QComboBox()
            cb.addItem("Choose...", None)
            labels = m.likelihood_labels if key in ("l", "rl") else m.impact_labels
            for n in range(1, m.size + 1):
                cb.addItem(f"{n} - {labels[n - 1]}", n)
            cb.setAccessibleName(self.LABELS[key])
            g.addWidget(cb, r, 1)
            self.combos[key] = cb
        g.setColumnStretch(2, 1)
        self.lay.addLayout(g)
        self.lay.addWidget(lbl("Use the organisation's matrix definitions (Assessment workbench) if unsure.", "Small"))

    def answer(self):
        out = {}
        for k, cb in self.combos.items():
            if cb.currentData() is None:
                raise ValueError("Rate every dimension.")
            out[k] = int(cb.currentData())
        return out

    def set_answer(self, a):
        for k, cb in self.combos.items():
            if a and k in a:
                cb.setCurrentIndex(cb.findData(int(a[k])))


class WriteWidget(StepWidget):
    def build(self):
        self.edit = QPlainTextEdit()
        self.edit.setMinimumHeight(150)
        self.edit.setAccessibleName("Written answer")
        lo, hi = self.step.get("min_words", 20), self.step.get("max_words", 200)
        self.edit.setPlaceholderText(f"Write {lo}-{hi} words.")
        self.count = lbl("0 words", "Small")
        self.edit.textChanged.connect(self._count)
        self.lay.addWidget(self.edit)
        self.lay.addWidget(self.count)
        self.lay.addWidget(lbl("Written answers are checked locally for required elements (keyword matching) and "
                               "then shown beside a model answer for self-comparison.", "Small"))

    def _count(self):
        n = len(self.edit.toPlainText().split())
        self.count.setText(f"{n} words (aim for {self.step.get('min_words', 20)}-{self.step.get('max_words', 200)})")

    def answer(self):
        t = self.edit.toPlainText().strip()
        if not t:
            raise ValueError("Write your answer first.")
        return t

    def set_answer(self, a):
        self.edit.setPlainText(a or "")


WIDGETS = {"choice": ChoiceWidget, "multi": MultiWidget, "numeric": NumericWidget, "classify": ClassifyWidget,
           "rank": RankWidget, "allocate": AllocateWidget, "matrix": MatrixWidget, "write": WriteWidget}


def make_step_widget(step: dict, ctx: dict, matrix) -> StepWidget:
    return WIDGETS[step["type"]](step, ctx, matrix)


def _wrap_text(text: str, width: int) -> str:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return "\n".join(lines)
