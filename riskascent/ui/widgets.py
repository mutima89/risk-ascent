"""Reusable widgets and layout helpers shared by all screens."""

from __future__ import annotations

from typing import Callable, Iterable, Sequence

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLayout, QLineEdit, QMessageBox, QProgressBar,
                               QPushButton, QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from . import theme


# ----------------------------------------------------------------- basics
def lbl(text: str = "", role: str | None = None, wrap: bool = True, rich: bool = False,
        select: bool = False) -> QLabel:
    w = QLabel(text)
    if role:
        w.setObjectName(role)
    w.setWordWrap(wrap)
    w.setTextFormat(Qt.RichText if rich else Qt.PlainText)
    if select:
        w.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
    return w


def button(text: str, slot: Callable | None = None, kind: str | None = None, tip: str = "",
           shortcut: str | None = None) -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if slot:
        b.clicked.connect(lambda *_: slot())
    if tip:
        b.setToolTip(tip)
    if shortcut:
        b.setShortcut(QKeySequence(shortcut))
        b.setToolTip((tip + " " if tip else "") + f"({shortcut})")
    b.setCursor(Qt.PointingHandCursor)
    return b


def hbox(*items, spacing: int = 10, margins: tuple = (0, 0, 0, 0), stretch_end: bool = False) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for it in items:
        _add(lay, it)
    if stretch_end:
        lay.addStretch(1)
    return lay


def vbox(*items, spacing: int = 10, margins: tuple = (0, 0, 0, 0), stretch_end: bool = False) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for it in items:
        _add(lay, it)
    if stretch_end:
        lay.addStretch(1)
    return lay


def _add(lay, it) -> None:
    if it is None:
        return
    if it == "stretch":
        lay.addStretch(1)
    elif isinstance(it, QLayout):
        lay.addLayout(it)
    else:
        lay.addWidget(it)


def clear_layout(lay: QLayout) -> None:
    while lay.count():
        item = lay.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def divider() -> QFrame:
    f = QFrame()
    f.setObjectName("Divider")
    f.setFrameShape(QFrame.NoFrame)
    return f


class Card(QFrame):
    def __init__(self, title: str | None = None, subtitle: str | None = None, kind: str = "Card",
                 eyebrow: str | None = None):
        super().__init__()
        self.setObjectName(kind)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 14)
        self.body.setSpacing(8)
        if eyebrow:
            self.body.addWidget(lbl(eyebrow.upper(), "Eyebrow"))
        if title:
            self.title_label = lbl(title, "H2")
            self.body.addWidget(self.title_label)
        if subtitle:
            self.body.addWidget(lbl(subtitle, "Muted"))
        # Trailing stretch keeps content top-aligned when a card is taller than it needs to be
        # (e.g. beside a taller card in a grid row); add() inserts above it.
        self.body.addStretch(1)

    def add(self, *items) -> "Card":
        for it in items:
            if it is None:
                continue
            i = self.body.count() - 1
            if it == "stretch":
                self.body.insertStretch(i, 1)
            elif isinstance(it, QLayout):
                self.body.insertLayout(i, it)
            else:
                self.body.insertWidget(i, it)
        return self


class Tile(QFrame):
    """A labelled number with an optional sub-line and accent colour."""

    def __init__(self, label: str, value: str = "-", sub: str = "", tip: str = ""):
        super().__init__()
        self.setObjectName("Tile")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        self.l = lbl(label, "Small")
        self.v = lbl(value, "Value", wrap=False)
        self.s = lbl(sub, "Small")
        lay.addWidget(self.l)
        lay.addWidget(self.v)
        lay.addWidget(self.s)
        if tip:
            self.setToolTip(tip)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set(self, value: str, sub: str = "", color: str | None = None) -> None:
        self.v.setText(value)
        self.s.setText(sub)
        self.v.setStyleSheet(f"color:{color};" if color else "")


def badge(text: str, color: str | None = None, filled: bool = False) -> QLabel:
    p = theme.current()
    c = color or p.muted
    w = QLabel(text)
    if filled:
        w.setStyleSheet(f"background:{c};color:{p.bg};border-radius:9px;padding:1px 8px;font-weight:600;")
    else:
        w.setStyleSheet(f"color:{c};border:1px solid {c};border-radius:9px;padding:1px 8px;font-weight:600;")
    w.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return w


def bar(value: float, maximum: float = 100, kind: str | None = None, tip: str = "") -> QProgressBar:
    b = QProgressBar()
    b.setRange(0, 1000)
    b.setValue(int(max(0.0, min(1.0, value / maximum if maximum else 0)) * 1000))
    b.setTextVisible(False)
    b.setFixedHeight(8)
    if kind:
        b.setObjectName(kind)
    if tip:
        b.setToolTip(tip)
    b.setAccessibleName(tip or f"{value:.0f} of {maximum:.0f}")
    return b


class Page(QScrollArea):
    """Scrollable page body with a centred, width-limited column."""

    def __init__(self, max_width: int = 1280):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setObjectName("Page")
        outer = QHBoxLayout(inner)
        outer.setContentsMargins(28, 22, 28, 28)
        col = QWidget()
        col.setMaximumWidth(max_width)
        self.layout_ = QVBoxLayout(col)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(16)
        outer.addWidget(col)
        self.setWidget(inner)
        self.inner = inner
        # Owned by the page, so a pending fit dies with it (a bare singleShot could
        # fire after a dialog's page has been deleted).
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self.fit)
        col.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.LayoutRequest:
            self._fit_timer.start(0)
        return False

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit()

    def fit(self) -> None:
        """Word-wrapped labels need height-for-width; QScrollArea does not apply it, so
        set the content's minimum height explicitly to stop cards being squashed."""
        lay = self.inner.layout()
        if lay is None:
            return
        w = self.viewport().width()
        h = lay.totalHeightForWidth(w) if lay.hasHeightForWidth() else lay.totalSizeHint().height()
        if h > 0 and h != self.inner.minimumHeight():
            self.inner.setMinimumHeight(h)

    def add(self, *items) -> None:
        for it in items:
            _add(self.layout_, it)


def header(title: str, subtitle: str = "", eyebrow: str = "") -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 4)
    lay.setSpacing(3)
    if eyebrow:
        lay.addWidget(lbl(eyebrow.upper(), "Eyebrow"))
    lay.addWidget(lbl(title, "H1"))
    if subtitle:
        lay.addWidget(lbl(subtitle, "Muted"))
    return w


def grid(widgets: Sequence[QWidget], cols: int, spacing: int = 12) -> QGridLayout:
    g = QGridLayout()
    g.setSpacing(spacing)
    for i, w in enumerate(widgets):
        g.addWidget(w, i // cols, i % cols)
    for c in range(cols):
        g.setColumnStretch(c, 1)
    return g


# ------------------------------------------------------------------ tables
def make_table(headers: Sequence[str], stretch: int | Sequence[int] | None = None, select_rows: bool = True) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(list(headers))
    t.verticalHeader().setVisible(False)
    t.setAlternatingRowColors(True)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows if select_rows else QAbstractItemView.SelectItems)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setWordWrap(True)
    hh = t.horizontalHeader()
    hh.setSectionResizeMode(QHeaderView.ResizeToContents)
    for col in ([stretch] if isinstance(stretch, int) else stretch or []):
        hh.setSectionResizeMode(col, QHeaderView.Stretch)
    hh.setHighlightSections(False)
    t.setShowGrid(False)
    return t


def set_rows(t: QTableWidget, rows: Iterable[Sequence], colors: dict[tuple[int, int], str] | None = None,
             data: Sequence | None = None) -> None:
    rows = list(rows)
    t.setSortingEnabled(False)
    t.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            it = QTableWidgetItem("" if val is None else str(val))
            if isinstance(val, (int, float)):
                it.setData(Qt.DisplayRole, val)
            if colors and (r, c) in colors:
                it.setForeground(QColor(colors[(r, c)]))
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            if data is not None and c == 0:
                it.setData(Qt.UserRole, data[r])
            t.setItem(r, c, it)
    t.resizeRowsToContents()


def selected_data(t: QTableWidget):
    r = t.currentRow()
    if r < 0:
        return None
    it = t.item(r, 0)
    return it.data(Qt.UserRole) if it else None


def fit_height(t: QTableWidget, max_rows: int = 12) -> None:
    h = t.horizontalHeader().height() + 4
    for r in range(min(t.rowCount(), max_rows)):
        h += t.rowHeight(r)
    t.setMinimumHeight(min(h, 60 + 32 * max_rows))
    t.setMaximumHeight(max(h, 80))


# ---------------------------------------------------------------- painting
class HeatMap(QWidget):
    """Likelihood x impact grid. Click a cell to emit (likelihood, impact)."""

    cell_clicked = Signal(int, int)

    def __init__(self):
        super().__init__()
        self.size_ = 5
        self.counts: list[list[int]] = [[0] * 5 for _ in range(5)]
        self.bands: list[list[str]] = [["Low"] * 5 for _ in range(5)]
        self.l_labels: list[str] = [str(i) for i in range(1, 6)]
        self.i_labels: list[str] = [str(i) for i in range(1, 6)]
        self.marker: tuple[int, int] | None = None
        self.marker2: tuple[int, int] | None = None
        self.selected: tuple[int, int] | None = None
        self.setMinimumSize(300, 240)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("Risk heat map")

    def set_data(self, matrix, counts: list[list[int]] | None, marker=None, marker2=None) -> None:
        self.size_ = matrix.size
        self.counts = counts or [[0] * matrix.size for _ in range(matrix.size)]
        self.bands = [[matrix.band(l * i) for l in range(1, matrix.size + 1)] for i in range(1, matrix.size + 1)]
        self.l_labels = list(matrix.likelihood_labels)
        self.i_labels = list(matrix.impact_labels)
        self.marker, self.marker2 = marker, marker2
        tip = []
        for i in range(matrix.size, 0, -1):
            tip.append(" ".join(f"{self.counts[i - 1][l - 1]}" for l in range(1, matrix.size + 1)))
        self.setAccessibleDescription("Rows impact high to low: " + "; ".join(tip))
        self.update()

    def _geom(self):
        left, bottom, top, right = 92, 46, 6, 6
        w = (self.width() - left - right) / self.size_
        h = (self.height() - top - bottom) / self.size_
        return left, top, w, h

    def paintEvent(self, _):
        p = theme.current()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        left, top, w, h = self._geom()
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, self.font().pointSizeF() * 0.78))
        for i in range(1, self.size_ + 1):
            for l in range(1, self.size_ + 1):
                x = left + (l - 1) * w
                y = top + (self.size_ - i) * h
                c = QColor(theme.band_color(self.bands[i - 1][l - 1]))
                n = self.counts[i - 1][l - 1]
                c.setAlpha(235 if n else 70)
                qp.setPen(QPen(QColor(p.bg), 2))
                qp.setBrush(c)
                qp.drawRoundedRect(QRectF(x + 1, y + 1, w - 2, h - 2), 5, 5)
                if self.selected == (l, i):
                    qp.setPen(QPen(QColor(p.text), 2.5))
                    qp.setBrush(Qt.NoBrush)
                    qp.drawRoundedRect(QRectF(x + 3, y + 3, w - 6, h - 6), 4, 4)
                if n:
                    qp.setPen(QColor("#ffffff"))
                    f = QFont(self.font())
                    f.setBold(True)
                    qp.setFont(f)
                    qp.drawText(QRectF(x, y, w, h), Qt.AlignCenter, str(n))
        for mk, style in ((self.marker, Qt.SolidLine), (self.marker2, Qt.DashLine)):
            if mk:
                l, i = mk
                x = left + (l - 0.5) * w
                y = top + (self.size_ - i + 0.5) * h
                qp.setPen(QPen(QColor(p.text), 3, style))
                qp.setBrush(Qt.NoBrush)
                qp.drawEllipse(QPointF(x, y), min(w, h) * 0.28, min(w, h) * 0.28)
        if self.marker and self.marker2 and self.marker != self.marker2:
            (l1, i1), (l2, i2) = self.marker, self.marker2
            qp.setPen(QPen(QColor(p.text), 1.5, Qt.DotLine))
            qp.drawLine(QPointF(left + (l1 - 0.5) * w, top + (self.size_ - i1 + 0.5) * h),
                        QPointF(left + (l2 - 0.5) * w, top + (self.size_ - i2 + 0.5) * h))
        qp.setFont(small)
        qp.setPen(QColor(p.muted))
        for i in range(1, self.size_ + 1):
            y = top + (self.size_ - i) * h
            qp.drawText(QRectF(0, y, left - 8, h), Qt.AlignRight | Qt.AlignVCenter | Qt.TextWordWrap,
                        self.i_labels[i - 1])
        for l in range(1, self.size_ + 1):
            x = left + (l - 1) * w
            qp.drawText(QRectF(x, top + self.size_ * h + 2, w, 28), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
                        self.l_labels[l - 1])
        qp.drawText(QRectF(left, self.height() - 16, self.width() - left, 16), Qt.AlignCenter, "Likelihood →")
        qp.end()

    def mousePressEvent(self, e):
        left, top, w, h = self._geom()
        l = int((e.position().x() - left) // w) + 1
        i = self.size_ - int((e.position().y() - top) // h)
        if 1 <= l <= self.size_ and 1 <= i <= self.size_:
            self.selected = None if self.selected == (l, i) else (l, i)
            self.update()
            self.cell_clicked.emit(*(self.selected or (0, 0)))

    def keyPressEvent(self, e):
        l, i = self.selected or (1, 1)
        k = e.key()
        if k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            l = max(1, min(self.size_, l + (k == Qt.Key_Right) - (k == Qt.Key_Left)))
            i = max(1, min(self.size_, i + (k == Qt.Key_Up) - (k == Qt.Key_Down)))
            self.selected = (l, i)
            self.update()
            self.cell_clicked.emit(l, i)
        elif k == Qt.Key_Escape:
            self.selected = None
            self.update()
            self.cell_clicked.emit(0, 0)
        else:
            super().keyPressEvent(e)


class Spark(QWidget):
    """Small trend line with optional warning/critical guide lines."""

    def __init__(self, values: Sequence[float] = (), warn: float | None = None, crit: float | None = None,
                 color: str | None = None):
        super().__init__()
        self.values = list(values)
        self.warn, self.crit, self.color = warn, crit, color
        self.setMinimumSize(120, 34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(38)

    def set_values(self, values: Sequence[float], warn=None, crit=None, color=None) -> None:
        self.values = list(values)
        self.warn, self.crit, self.color = warn, crit, color
        self.update()

    def paintEvent(self, _):
        p = theme.current()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        vals = self.values
        guides = [g for g in (self.warn, self.crit) if g is not None]
        if len(vals) < 2:
            qp.setPen(QColor(p.muted))
            qp.drawText(self.rect(), Qt.AlignVCenter | Qt.AlignLeft, "Not enough history yet")
            qp.end()
            return
        lo, hi = min(vals + guides), max(vals + guides)
        span = (hi - lo) or 1.0
        w, h = self.width() - 6, self.height() - 6

        def pt(i, v):
            return QPointF(3 + i * w / (len(vals) - 1), 3 + h - (v - lo) / span * h)

        for g, c in ((self.warn, p.warn), (self.crit, p.bad)):
            if g is not None:
                pen = QPen(QColor(c), 1, Qt.DashLine)
                qp.setPen(pen)
                y = 3 + h - (g - lo) / span * h
                qp.drawLine(QPointF(3, y), QPointF(3 + w, y))
        path = QPainterPath(pt(0, vals[0]))
        for i, v in enumerate(vals[1:], start=1):
            path.lineTo(pt(i, v))
        qp.setPen(QPen(QColor(self.color or p.accent), 2))
        qp.drawPath(path)
        qp.setBrush(QColor(self.color or p.accent))
        qp.drawEllipse(pt(len(vals) - 1, vals[-1]), 3, 3)
        qp.end()


class RadarChart(QWidget):
    """Competency profile: current score against stage expectation."""

    def __init__(self):
        super().__init__()
        self.labels: list[str] = []
        self.values: list[float] = []
        self.expected: list[float] = []
        self.setMinimumSize(320, 300)

    def set_data(self, labels: list[str], values: list[float], expected: list[float] | None = None) -> None:
        self.labels, self.values, self.expected = labels, values, expected or []
        self.setAccessibleDescription("; ".join(f"{l} {v:.0f}" for l, v in zip(labels, values)))
        self.update()

    def paintEvent(self, _):
        import math
        p = theme.current()
        n = len(self.labels)
        if n < 3:
            return
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        r = min(cx, cy) - 56

        def pt(k, v):
            a = -math.pi / 2 + 2 * math.pi * k / n
            return QPointF(cx + math.cos(a) * r * v / 100, cy + math.sin(a) * r * v / 100)

        qp.setPen(QPen(QColor(p.border), 1))
        for ring in (25, 50, 75, 100):
            path = QPainterPath(pt(0, ring))
            for k in range(1, n):
                path.lineTo(pt(k, ring))
            path.closeSubpath()
            qp.drawPath(path)
        for k in range(n):
            qp.drawLine(QPointF(cx, cy), pt(k, 100))
        if self.expected:
            path = QPainterPath(pt(0, self.expected[0]))
            for k in range(1, n):
                path.lineTo(pt(k, self.expected[k]))
            path.closeSubpath()
            qp.setPen(QPen(QColor(p.gold), 1.5, Qt.DashLine))
            qp.setBrush(Qt.NoBrush)
            qp.drawPath(path)
        path = QPainterPath(pt(0, self.values[0]))
        for k in range(1, n):
            path.lineTo(pt(k, self.values[k]))
        path.closeSubpath()
        fill = QColor(p.accent)
        fill.setAlpha(70)
        qp.setPen(QPen(QColor(p.accent), 2))
        qp.setBrush(fill)
        qp.drawPath(path)
        f = QFont(self.font())
        f.setPointSizeF(max(7.0, self.font().pointSizeF() * 0.8))
        qp.setFont(f)
        qp.setPen(QColor(p.muted))
        for k, label in enumerate(self.labels):
            q = pt(k, 122)
            qp.drawText(QRectF(q.x() - 60, q.y() - 10, 120, 20), Qt.AlignCenter, label)
        qp.end()


# ------------------------------------------------------------------ charts
class Chart(QWidget):
    """Matplotlib canvas styled from the current palette."""

    def __init__(self, height: float = 3.0, width: float = 6.0):
        super().__init__()
        import matplotlib
        matplotlib.use("QtAgg")
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure
        self.fig = Figure(figsize=(width, height), dpi=100, layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setMinimumHeight(int(height * 80))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas)
        self.ax = self.fig.add_subplot(111)
        self.style()

    def style(self, ax=None) -> None:
        p = theme.current()
        self.fig.set_facecolor(p.surface)
        for a in ([ax] if ax else self.fig.axes):
            a.set_facecolor(p.surface)
            for s in ("top", "right"):
                a.spines[s].set_visible(False)
            for s in ("left", "bottom"):
                a.spines[s].set_color(p.border)
            a.tick_params(colors=p.muted, labelsize=8)
            a.xaxis.label.set_color(p.muted)
            a.yaxis.label.set_color(p.muted)
            a.title.set_color(p.text)
            a.grid(True, color=p.border, alpha=0.5, linewidth=0.6)
            a.set_axisbelow(True)

    def reset(self):
        self.fig.clear()
        self.ax = self.fig.add_subplot(111)
        self.style()
        return self.ax

    def draw(self) -> None:
        self.style()
        p = theme.current()
        for a in self.fig.axes:
            leg = a.get_legend()
            if leg:
                leg.get_frame().set_facecolor(p.surface)
                leg.get_frame().set_edgecolor(p.border)
                for t in leg.get_texts():
                    t.set_color(p.text)
        self.canvas.draw_idle()


class Checklist(QFrame):
    """Visible task checklist (focus mode support)."""

    def __init__(self, title: str = "Checklist"):
        super().__init__()
        self.setObjectName("CardMuted")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(14, 10, 14, 10)
        self.lay.setSpacing(4)
        self.title = title

    def set_items(self, items: Sequence[tuple[str, bool]], current: int | None = None) -> None:
        clear_layout(self.lay)
        self.lay.addWidget(lbl(self.title.upper(), "Eyebrow"))
        p = theme.current()
        for k, (text, done) in enumerate(items):
            mark = "✓" if done else ("▶" if k == current else "○")
            w = lbl(f"{mark}  {text}", None)
            if done:
                w.setStyleSheet(f"color:{p.good};")
            elif k == current:
                w.setStyleSheet("font-weight:600;")
            else:
                w.setStyleSheet(f"color:{p.muted};")
            self.lay.addWidget(w)


# ------------------------------------------------------------------ dialogs
class Dialogs:
    """All modal prompts go through here so tests can replace them."""

    @staticmethod
    def info(parent, title: str, text: str) -> None:
        QMessageBox.information(parent, title, text)

    @staticmethod
    def error(parent, title: str, text: str) -> None:
        QMessageBox.warning(parent, title, text)

    @staticmethod
    def confirm(parent, title: str, text: str) -> bool:
        return QMessageBox.question(parent, title, text, QMessageBox.Yes | QMessageBox.No,
                                    QMessageBox.No) == QMessageBox.Yes

    @staticmethod
    def typed_confirm(parent, title: str, text: str, word: str) -> bool:
        d = QDialog(parent)
        d.setWindowTitle(title)
        lay = QVBoxLayout(d)
        lay.addWidget(lbl(text))
        lay.addWidget(lbl(f"Type {word} to confirm.", "Muted"))
        edit = QLineEdit()
        lay.addWidget(edit)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok = bb.button(QDialogButtonBox.Ok)
        ok.setEnabled(False)
        edit.textChanged.connect(lambda t: ok.setEnabled(t.strip() == word))
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        return d.exec() == QDialog.Accepted and edit.text().strip() == word

    @staticmethod
    def save_file(parent, title: str, default: str, filt: str) -> str:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(parent, title, default, filt)
        return path

    @staticmethod
    def open_file(parent, title: str, start: str, filt: str) -> str:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(parent, title, start, filt)
        return path

    @staticmethod
    def text(parent, title: str, label: str, default: str = "") -> str | None:
        t, ok = QInputDialog.getText(parent, title, label, text=default)
        return t if ok else None


DIALOGS = Dialogs()
