"""Visual theme: colour tokens and the Qt style sheet built from them.

Colours are restrained: one accent (teal) for interactive elements, and the
status colours (good / warn / bad) used only where they carry meaning.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    surface: str
    surface2: str
    border: str
    text: str
    muted: str
    accent: str
    accent_text: str
    accent_soft: str
    gold: str
    good: str
    warn: str
    bad: str
    info: str
    medium: str


DARK = Palette("dark", bg="#0e131d", surface="#151c29", surface2="#1c2535", border="#2a3449",
               text="#e7ebf3", muted="#97a2b6", accent="#3fb8b7", accent_text="#05201f",
               accent_soft="#173b40", gold="#e9b44c", good="#4bb47a", warn="#e39a37", bad="#e5594f",
               info="#5b9fe3", medium="#c9b23a")
LIGHT = Palette("light", bg="#f3f5f9", surface="#ffffff", surface2="#eef1f6", border="#d4dae5",
                text="#18202e", muted="#566175", accent="#0f7478", accent_text="#ffffff",
                accent_soft="#d7eeee", gold="#a8740f", good="#2b7a4b", warn="#a85f00", bad="#b3261e",
                info="#1f62b0", medium="#8c7a00")
DARK_HC = Palette("dark-hc", bg="#000000", surface="#0b0b0b", surface2="#161616", border="#8a8a8a",
                  text="#ffffff", muted="#d0d0d0", accent="#4fe0dc", accent_text="#000000",
                  accent_soft="#003c3c", gold="#ffd060", good="#5ee08f", warn="#ffb347", bad="#ff6e64",
                  info="#7ab8ff", medium="#f0dc4a")
LIGHT_HC = Palette("light-hc", bg="#ffffff", surface="#ffffff", surface2="#f0f0f0", border="#202020",
                   text="#000000", muted="#202020", accent="#00585b", accent_text="#ffffff",
                   accent_soft="#cdeeee", gold="#7a5200", good="#14592f", warn="#7a4200", bad="#8e0b05",
                   info="#0b3f80", medium="#5c5000")

_current: Palette = DARK


def palette_for(theme: str, high_contrast: bool) -> Palette:
    if theme == "light":
        return LIGHT_HC if high_contrast else LIGHT
    return DARK_HC if high_contrast else DARK


def set_current(p: Palette) -> None:
    global _current
    _current = p


def current() -> Palette:
    return _current


def band_color(band: str, p: Palette | None = None) -> str:
    p = p or _current
    return {"Low": p.good, "Medium": p.medium, "High": p.warn, "Critical": p.bad}.get(band, p.muted)


def status_color(status: str, p: Palette | None = None) -> str:
    p = p or _current
    s = status.lower()
    if s.startswith(("critical", "outside", "declined", "failed")):
        return p.bad
    if s.startswith(("warning", "above", "high")):
        return p.warn
    if s.startswith(("normal", "within", "approved", "passed", "low")):
        return p.good
    return p.muted


def stylesheet(p: Palette, scale: float = 1.0) -> str:
    fs = round(10 * scale, 1)

    def pt(n: float) -> str:
        return f"{round(n * scale, 1)}pt"

    return f"""
* {{ font-family: "Segoe UI", "Inter", "Noto Sans", "DejaVu Sans", sans-serif; font-size: {fs}pt; color: {p.text}; }}
QMainWindow, QWidget#Root, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {p.bg}; }}
QWidget#Page {{ background: {p.bg}; }}
QToolTip {{ background: {p.surface2}; color: {p.text}; border: 1px solid {p.border}; padding: 6px; }}

QFrame#Sidebar {{ background: {p.surface}; border-right: 1px solid {p.border}; }}
QLabel#Brand {{ font-size: {pt(14)}; font-weight: 700; letter-spacing: 1px; color: {p.text}; }}
QLabel#BrandSub {{ color: {p.muted}; font-size: {pt(8.5)}; }}
QListWidget#Nav {{ background: transparent; border: none; outline: none; }}
QListWidget#Nav::item {{ padding: 7px 10px; border-radius: 6px; margin: 1px 6px; color: {p.muted}; }}
QListWidget#Nav::item:hover {{ background: {p.surface2}; color: {p.text}; }}
QListWidget#Nav::item:selected {{ background: {p.accent_soft}; color: {p.text}; font-weight: 600; }}
QListWidget#Nav::item:disabled {{ color: {p.muted}; background: transparent; font-size: {pt(8)}; font-weight: 700; padding-top: 12px; }}

QFrame#TopBar {{ background: {p.bg}; border-bottom: 1px solid {p.border}; }}
QLabel#Crumb {{ font-size: {pt(13)}; font-weight: 600; }}
QLabel#Timer {{ color: {p.muted}; font-family: "Consolas", "DejaVu Sans Mono", monospace; }}
QFrame#Banner {{ background: {p.accent_soft}; border: 1px solid {p.accent}; border-radius: 8px; }}
QFrame#BannerWarn {{ background: {p.surface2}; border: 1px solid {p.warn}; border-radius: 8px; }}

QFrame#Card {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 10px; }}
QFrame#CardAccent {{ background: {p.surface}; border: 1px solid {p.accent}; border-radius: 10px; }}
QFrame#CardMuted {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: 10px; }}
QFrame#Tile {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 10px; }}
QFrame#Divider {{ background: {p.border}; max-height: 1px; min-height: 1px; }}

QLabel#H1 {{ font-size: {pt(19)}; font-weight: 700; }}
QLabel#H2 {{ font-size: {pt(13)}; font-weight: 650; }}
QLabel#H3 {{ font-size: {pt(10.5)}; font-weight: 650; }}
QLabel#Eyebrow {{ color: {p.accent}; font-size: {pt(8)}; font-weight: 700; letter-spacing: 1px; }}
QLabel#Muted {{ color: {p.muted}; }}
QLabel#Small {{ color: {p.muted}; font-size: {pt(8.5)}; }}
QLabel#Value {{ font-size: {pt(18)}; font-weight: 700; }}
QLabel#Good {{ color: {p.good}; font-weight: 600; }}
QLabel#Warn {{ color: {p.warn}; font-weight: 600; }}
QLabel#Bad {{ color: {p.bad}; font-weight: 600; }}
QLabel#Gold {{ color: {p.gold}; font-weight: 700; }}
QLabel#Body {{ line-height: 140%; }}

QPushButton {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: 7px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {p.accent}; }}
QPushButton:focus {{ border: 2px solid {p.accent}; }}
QPushButton:pressed {{ background: {p.accent_soft}; }}
QPushButton:disabled {{ color: {p.muted}; background: {p.surface}; border-color: {p.border}; }}
QPushButton#Primary {{ background: {p.accent}; color: {p.accent_text}; border: 1px solid {p.accent}; font-weight: 650; }}
QPushButton#Primary:disabled {{ background: {p.surface2}; color: {p.muted}; border-color: {p.border}; }}
QPushButton#Primary:focus {{ border: 2px solid {p.text}; }}
QPushButton#Ghost {{ background: transparent; border: 1px solid transparent; color: {p.accent}; }}
QPushButton#Ghost:hover {{ border-color: {p.border}; }}
QPushButton#Danger {{ background: transparent; border: 1px solid {p.bad}; color: {p.bad}; }}
QPushButton#Option {{ text-align: left; padding: 10px 12px; background: {p.surface}; }}
QPushButton#Option:checked {{ border: 2px solid {p.accent}; background: {p.accent_soft}; }}
QPushButton#MissionCard {{ text-align: left; }}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
  background: {p.surface2}; border: 1px solid {p.border}; border-radius: 6px; padding: 5px 7px;
  selection-background-color: {p.accent}; selection-color: {p.accent_text}; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
  border: 2px solid {p.accent}; }}
QComboBox QAbstractItemView {{ background: {p.surface}; border: 1px solid {p.border};
  selection-background-color: {p.accent_soft}; selection-color: {p.text}; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0px; border: none; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
QCheckBox::indicator {{ border: 1px solid {p.border}; border-radius: 3px; background: {p.surface2}; }}
QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; }}
QRadioButton::indicator {{ border: 1px solid {p.border}; border-radius: 8px; background: {p.surface2}; }}
QRadioButton::indicator:checked {{ background: {p.accent}; border: 3px solid {p.surface2}; }}
QCheckBox:focus, QRadioButton:focus {{ color: {p.accent}; }}
QSlider::groove:horizontal {{ height: 6px; background: {p.surface2}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {p.accent}; width: 16px; margin: -6px 0; border-radius: 8px; }}
QSlider::sub-page:horizontal {{ background: {p.accent}; border-radius: 3px; }}

QProgressBar {{ background: {p.surface2}; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 4px; }}
QProgressBar#Gold::chunk {{ background: {p.gold}; }}
QProgressBar#Good::chunk {{ background: {p.good}; }}
QProgressBar#Warn::chunk {{ background: {p.warn}; }}
QProgressBar#Bad::chunk {{ background: {p.bad}; }}

QTabWidget::pane {{ border: 1px solid {p.border}; border-radius: 8px; top: -1px; background: {p.surface}; }}
QTabBar::tab {{ background: transparent; padding: 8px 14px; color: {p.muted}; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {p.text}; border-bottom: 2px solid {p.accent}; font-weight: 600; }}
QTabBar::tab:hover {{ color: {p.text}; }}
QTabBar::tab:focus {{ color: {p.accent}; }}

QTableWidget, QTableView, QListWidget, QTreeWidget {{ background: {p.surface}; border: 1px solid {p.border};
  border-radius: 8px; gridline-color: {p.border}; alternate-background-color: {p.surface2};
  selection-background-color: {p.accent_soft}; selection-color: {p.text}; }}
QHeaderView::section {{ background: {p.surface2}; color: {p.muted}; border: none; border-bottom: 1px solid {p.border};
  padding: 6px; font-weight: 600; }}
QTextBrowser {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 8px; padding: 8px; }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p.border}; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p.border}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QGroupBox {{ border: 1px solid {p.border}; border-radius: 8px; margin-top: 12px; padding: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {p.muted}; }}
QDialog {{ background: {p.bg}; }}
QMessageBox {{ background: {p.bg}; }}
QStatusBar {{ background: {p.surface}; color: {p.muted}; border-top: 1px solid {p.border}; }}
"""
