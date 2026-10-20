"""Executive reporting workspace: generate reports from live data, preview,
and export to HTML, PDF and CSV."""

from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QPainter, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import QComboBox, QLineEdit, QPlainTextEdit, QTextBrowser

from ...core.reporting import REPORT_KINDS, generate
from ...paths import reports_dir
from ..base import Screen
from ..widgets import Card, button, fit_height, grid, hbox, lbl, make_table, set_rows, vbox
from .. import theme

_SVG = re.compile(r"<svg\b.*?</svg>", re.S)


def svg_to_images(html: str) -> tuple[str, dict[str, QImage]]:
    """QTextDocument cannot draw inline SVG; render each to an image resource."""
    from PySide6.QtSvg import QSvgRenderer
    images: dict[str, QImage] = {}

    def repl(m):
        svg = m.group(0)
        r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        size = r.defaultSize()
        w, h = max(1, size.width()), max(1, size.height())
        img = QImage(w * 2, h * 2, QImage.Format_ARGB32)
        img.fill(0)
        qp = QPainter(img)
        r.render(qp)
        qp.end()
        name = f"svg{len(images)}.png"
        images[name] = img
        return f"<img src='{name}' width='{w}' height='{h}'>"

    return _SVG.sub(repl, html), images


class ResourceDocument(QTextDocument):
    def __init__(self, images: dict[str, QImage]):
        super().__init__()
        self.images = images

    def loadResource(self, kind, url):
        img = self.images.get(url.toString())
        if img is not None:
            return img
        return super().loadResource(kind, url)


class ReportBrowser(QTextBrowser):
    images: dict[str, QImage] = {}

    def loadResource(self, kind, url):
        img = self.images.get(url.toString())
        if img is not None:
            return img
        return super().loadResource(kind, url)


class ReportsScreen(Screen):
    key = "reports"
    title = "Executive reports"

    def __init__(self, win):
        super().__init__(win)
        self.kind = "exec_dashboard"
        self.html = ""

    def open(self, kind: str | None = None, **_):
        if kind:
            self.kind = kind
        self.html = ""
        self.refresh()

    def populate(self) -> None:
        g = self.game
        lay = self.page.layout_
        lay.addWidget(lbl("EXECUTIVE REPORTING WORKSPACE", "Eyebrow"))
        lay.addWidget(lbl("Reports built from the live simulation", "H1"))
        lay.addWidget(lbl("Every figure comes from your organisation's current register, KRIs, events and "
                          "decisions. More senior report types unlock as your role grows.", "Muted"))
        self.combo = QComboBox()
        for k, (name, lvl) in REPORT_KINDS.items():
            self.combo.addItem(name + ("" if g.level >= lvl else f"  (unlocks at level {lvl})"), k)
        self.combo.setCurrentIndex(max(0, self.combo.findData(self.kind)))
        self.combo.currentIndexChanged.connect(self._kind_changed)
        lay.addLayout(hbox(lbl("Report", wrap=False), self.combo, button("Generate", self.generate, "Primary",
                                                                         shortcut="Ctrl+G"), stretch_end=True))
        self.options_card = Card("Report inputs")
        self._options()
        lay.addWidget(self.options_card)
        self.view = ReportBrowser()
        self.view.setMinimumHeight(520)
        self.view.setOpenExternalLinks(False)
        # Reports are printed documents: always preview them on white paper, whatever the theme.
        self.view.setStyleSheet("QTextBrowser{background:#ffffff;color:#1d2433;border:1px solid #d5dae3;}")
        if self.html:
            self._show(self.html)
        else:
            self.view.setHtml(f"<p style='color:#5b6475'>Choose a report and press Generate.</p>")
        lay.addWidget(self.view)
        lay.addLayout(hbox(button("Export HTML", self.export_html), button("Export PDF", self.export_pdf),
                           button("Export register CSV", self.export_csv),
                           button("Export KRI CSV", self.export_kri_csv), "stretch",
                           button("Open reports folder", self.open_folder, "Ghost")))
        if self.focus_mode:
            return
        rows = g.db.q("SELECT * FROM reports ORDER BY id DESC LIMIT 20")
        if rows:
            hc = Card("Report history")
            t = make_table(["Month", "Report", "File", "Created"], 2)
            set_rows(t, [(f"M{r['period']}", r["title"], r["path"], r["created_at"].replace("T", " ")) for r in rows])
            fit_height(t, 8)
            hc.add(t)
            lay.addWidget(hc)

    def _kind_changed(self, *_):
        self.kind = self.combo.currentData()
        self.html = ""
        self.refresh()

    def _options(self) -> None:
        g = self.game
        c = self.options_card
        self.inc_combo = None
        if self.kind == "post_incident":
            evs = [e for e in g.events(100) if e["type"] in ("incident", "scheduled", "random") and e["severity"] >= 1]
            self.inc_combo = QComboBox()
            for e in evs:
                self.inc_combo.addItem(f"Month {e['period']}: {e['title']}", e["id"])
            self.inc_events = {e["id"]: e for e in evs}
            self.root = QLineEdit()
            self.worked = QLineEdit()
            self.failed = QLineEdit()
            self.actions_e = QPlainTextEdit()
            self.actions_e.setMaximumHeight(70)
            c.add(lbl("Incident", "Small"), self.inc_combo)
            if not evs:
                c.add(lbl("No incidents have happened yet. Advance the organisation or complete missions.", "Muted"))
            for label, w in (("Root cause", self.root), ("What worked", self.worked), ("What did not", self.failed),
                             ("Actions (owner and date)", self.actions_e)):
                c.add(lbl(label, "Small"), w)
        elif self.kind == "investment_proposal":
            h = self.win.handoff.get("investment")
            if h:
                c.add(lbl(f"Using the cost-benefit case for {h['risk_id']}: {h['title']}. NPV {g.money(h['npv'])}.",
                          "Body"))
            else:
                c.add(lbl("Build a cost-benefit case in the Financial lab first, then choose 'Create investment "
                          "proposal report'.", "Muted"),
                      hbox(button("Open Financial lab", lambda: self.win.go("finance")), stretch_end=True))
            self.assumptions = QLineEdit()
            self.assumptions.setPlaceholderText("Key assumptions and uncertainty (optional)")
            c.add(self.assumptions)
        else:
            c.add(lbl("No inputs needed: this report is built entirely from current data.", "Small"))

    def generate(self) -> None:
        g = self.game
        lvl = REPORT_KINDS[self.kind][1]
        if g.level < lvl:
            self.fail(f"{REPORT_KINDS[self.kind][0]} is produced from level {lvl}. Until then, contribute to it "
                      "through your missions.")
            return
        opts = {}
        if self.kind == "post_incident":
            if not self.inc_combo or self.inc_combo.currentData() is None:
                self.fail("Choose an incident to review.")
                return
            opts = {"event": self.inc_events[self.inc_combo.currentData()], "root_cause": self.root.text().strip(),
                    "worked": self.worked.text().strip(), "failed": self.failed.text().strip(),
                    "actions": self.actions_e.toPlainText().strip()}
        elif self.kind == "investment_proposal":
            h = self.win.handoff.get("investment")
            if not h:
                self.fail("Build a cost-benefit case in the Financial lab first.")
                return
            opts = dict(h)
            if self.assumptions.text().strip():
                opts["assumptions"] = self.assumptions.text().strip()
        try:
            self.html = generate(self.kind, g.report_data(), opts)
        except ValueError as exc:
            self.fail(exc)
            return
        path = self._default_path("html")
        path.write_text(self.html, encoding="utf-8")
        g.record_report(self.kind, REPORT_KINDS[self.kind][0], str(path))
        self._show(self.html)
        self.notify(f"Report generated and saved to {path}")

    def _show(self, html: str) -> None:
        body, images = svg_to_images(html)
        self.view.images = images
        self.view.setHtml(body)

    def _default_path(self, ext: str) -> Path:
        return reports_dir() / f"{self.kind}_month{self.game.period()}_{datetime.now():%Y%m%d-%H%M%S}.{ext}"

    def _need_html(self) -> bool:
        if not self.html:
            self.fail("Generate a report first.")
            return False
        return True

    def export_html(self) -> None:
        if not self._need_html():
            return
        path = self.dialogs.save_file(self, "Export report", str(self._default_path("html")), "HTML (*.html)")
        if path:
            Path(path).write_text(self.html, encoding="utf-8")
            self.game.count("exports")
            self.game.check_achievements()
            self.notify(f"Saved {path}")

    def export_pdf(self) -> None:
        if not self._need_html():
            return
        path = self.dialogs.save_file(self, "Export PDF", str(self._default_path("pdf")), "PDF (*.pdf)")
        if not path:
            return
        write_pdf(self.html, Path(path))
        self.game.count("exports")
        self.game.check_achievements()
        self.notify(f"Saved {path}")

    def export_csv(self) -> None:
        path = self.dialogs.save_file(self, "Export register", str(reports_dir() / f"register_month{self.game.period()}.csv"),
                                      "CSV (*.csv)")
        if path:
            self.game.export_register_csv(Path(path))
            self.game.check_achievements()
            self.notify(f"Saved {path}")

    def export_kri_csv(self) -> None:
        g = self.game
        path = self.dialogs.save_file(self, "Export KRIs", str(reports_dir() / f"kris_month{g.period()}.csv"),
                                      "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["KRI", "Name", "Unit", "Month", "Value", "Warning", "Critical", "Higher is worse", "Status now",
                        "Owner", "Escalation"])
            for k in g.list_kris():
                for period, v in g.kri_history(k.kri_id):
                    w.writerow([k.kri_id, k.name, k.unit, period, v, k.warning, k.critical, k.higher_is_worse,
                                k.status(), k.owner, k.escalation])
        g.count("exports")
        g.check_achievements()
        self.notify(f"Saved {path}")

    def open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(reports_dir())))


def write_pdf(html: str, path: Path) -> None:
    body, images = svg_to_images(html)
    doc = ResourceDocument(images)
    doc.setHtml(body)
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setResolution(110)
    doc.setPageSize(writer.pageLayout().paintRectPixels(writer.resolution()).size().toSizeF())
    doc.print_(writer)
