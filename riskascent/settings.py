"""Application preferences (global, not per career). Stored as JSON, written atomically."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .core.learning import DEFAULT_INTERVALS


@dataclass
class Settings:
    theme: str = "dark"               # dark | light
    text_scale: float = 1.0           # 0.85 - 1.6
    reduced_motion: bool = False
    focus_mode: bool = False
    show_timer: bool = True
    session_minutes: int = 25         # gentle break suggestion; 0 = never
    tts_enabled: bool = False
    high_contrast: bool = False
    review_intervals: list[int] = field(default_factory=lambda: list(DEFAULT_INTERVALS))
    review_reminders: bool = True     # show "reviews due" on dashboard (never a pop-up)
    autosave_backups: bool = True
    last_slot: int = 0
    sidebar_compact: bool = False

    def validate(self) -> None:
        if self.theme not in ("dark", "light"):
            self.theme = "dark"
        self.text_scale = min(1.6, max(0.85, float(self.text_scale)))
        self.session_minutes = max(0, min(120, int(self.session_minutes)))
        if not self.review_intervals or any(int(i) <= 0 for i in self.review_intervals):
            self.review_intervals = list(DEFAULT_INTERVALS)
        self.review_intervals = [int(i) for i in self.review_intervals][:8]


def load_settings(path: Path) -> Settings:
    s = Settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        names = {f.name for f in fields(Settings)}
        for k, v in data.items():
            if k in names:
                setattr(s, k, v)
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, ValueError):
        pass
    s.validate()
    return s


def save_settings(s: Settings, path: Path) -> None:
    s.validate()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(s), indent=2), encoding="utf-8")
    os.replace(tmp, path)
