"""Application entry point.

Usage:
  RiskAscent.exe                     start normally
  RiskAscent.exe --data-dir PATH     keep saves somewhere else (portable use)
  RiskAscent.exe --self-test         run the built-in smoke test and exit (0 = pass)
  RiskAscent.exe --version
Qt options such as -platform offscreen are passed through to Qt.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from . import APP_NAME, __version__


def _parse(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    ap = argparse.ArgumentParser(prog="RiskAscent", add_help=True)
    ap.add_argument("--data-dir", help="Folder for saves, backups, reports and settings")
    ap.add_argument("--self-test", action="store_true", help="Run the built-in smoke test and exit")
    ap.add_argument("--self-test-report", help="Write the self-test report to this file")
    ap.add_argument("--version", action="store_true")
    return ap.parse_known_args(argv)


def _setup_logging() -> Path:
    from .paths import logs_dir
    log = logs_dir() / "riskascent.log"
    try:
        if log.exists() and log.stat().st_size > 2_000_000:
            log.replace(log.with_suffix(".old.log"))
    except OSError:
        pass
    logging.basicConfig(filename=str(log), level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return log


def main(argv: list[str] | None = None) -> int:
    args, qt_args = _parse(sys.argv[1:] if argv is None else argv)
    if args.version:
        print(f"{APP_NAME} {__version__}")
        return 0
    if args.data_dir:
        os.environ["RISKASCENT_HOME"] = str(Path(args.data_dir).resolve())
    if args.self_test and not os.environ.get("RISKASCENT_HOME"):
        import tempfile
        os.environ["RISKASCENT_HOME"] = tempfile.mkdtemp(prefix="riskascent-selftest-")

    log_path = _setup_logging()
    logging.info("Starting %s %s (python %s, frozen=%s)", APP_NAME, __version__, sys.version.split()[0],
                 getattr(sys, "frozen", False))

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("RiskAscent")
    from PySide6.QtGui import QIcon
    from .paths import resource_dir
    icon = resource_dir() / "assets" / "icon.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    def excepthook(et, ev, tb):
        text = "".join(traceback.format_exception(et, ev, tb))
        logging.error("Unhandled error:\n%s", text)
        if args.self_test:
            print(text, file=sys.stderr)
            return
        QMessageBox.critical(None, APP_NAME, "Something went wrong, but your progress up to the last action is "
                             f"saved.\n\n{ev}\n\nDetails were written to:\n{log_path}")

    sys.excepthook = excepthook

    splash = None
    if not args.self_test:
        pm = QPixmap(560, 300)
        pm.fill(QColor("#0e131d"))
        qp = QPainter(pm)
        qp.setPen(QColor("#3fb8b7"))
        f = QFont("Segoe UI", 26, QFont.Bold)
        qp.setFont(f)
        qp.drawText(pm.rect().adjusted(0, -40, 0, 0), Qt.AlignCenter, "RISK ASCENT")
        qp.setPen(QColor("#97a2b6"))
        qp.setFont(QFont("Segoe UI", 10))
        qp.drawText(pm.rect().adjusted(0, 40, 0, 0), Qt.AlignCenter, "From Junior Analyst to Chief Risk Officer")
        qp.end()
        splash = QSplashScreen(pm)
        splash.show()
        splash.showMessage("Loading content...", Qt.AlignBottom | Qt.AlignHCenter, QColor("#e7ebf3"))
        app.processEvents()

    from .core.content import ContentError, load_content
    from .paths import backups_dir, content_dir, saves_dir, settings_file, user_data_dir
    from .persistence.saves import SaveManager
    from .settings import load_settings

    try:
        content = load_content(content_dir())
    except ContentError as exc:
        logging.error("%s", exc)
        QMessageBox.critical(None, APP_NAME, f"Game content failed validation:\n\n{exc}")
        return 2
    if splash:
        splash.showMessage("Checking saves...", Qt.AlignBottom | Qt.AlignHCenter, QColor("#e7ebf3"))
        app.processEvents()
    saves = SaveManager(saves_dir(), backups_dir())
    settings = load_settings(settings_file())

    from .ui.main_window import MainWindow
    win = MainWindow(content, saves, settings, user_data_dir(), settings_file())
    if args.self_test:
        from .selftest import run_self_test
        return run_self_test(app, win, args.self_test_report)
    win.show()
    if splash:
        splash.finish(win)
    code = app.exec()
    logging.info("Exit %s at %s", code, datetime.now().isoformat(timespec="seconds"))
    return code


if __name__ == "__main__":
    sys.exit(main())
