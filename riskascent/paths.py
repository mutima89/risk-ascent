"""Filesystem locations.

User data lives in a user-writable directory (no admin rights needed):
  Windows: %LOCALAPPDATA%\\RiskAscent
  macOS:   ~/Library/Application Support/RiskAscent
  Linux:   $XDG_DATA_HOME/RiskAscent or ~/.local/share/RiskAscent
Set RISKASCENT_HOME to override (used by tests and portable installs).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_ID


def user_data_dir() -> Path:
    env = os.environ.get("RISKASCENT_HOME")
    if env:
        base = Path(env)
    elif sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        base = Path(root) / APP_ID
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_ID
    else:
        root = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        base = Path(root) / APP_ID
    base.mkdir(parents=True, exist_ok=True)
    return base


def _sub(name: str) -> Path:
    p = user_data_dir() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def saves_dir() -> Path:
    return _sub("saves")


def backups_dir() -> Path:
    return _sub("backups")


def reports_dir() -> Path:
    return _sub("reports")


def logs_dir() -> Path:
    return _sub("logs")


def settings_file() -> Path:
    return user_data_dir() / "settings.json"


def resource_dir() -> Path:
    """Directory holding bundled read-only resources (content JSON, assets)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "riskascent"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def content_dir() -> Path:
    return resource_dir() / "content"
