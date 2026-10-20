"""Difficulty settings and adaptive scaffolding."""

from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class Difficulty:
    key: str
    label: str
    description: str
    hints: str             # "always", "on_request", "after_error"
    worked_examples: bool
    retries: int           # retries allowed on calculation steps
    tolerance_mult: float  # widens/narrows numeric answer tolerance
    event_severity: float  # multiplier on random-event impact
    budget_mult: float     # multiplier on the risk function budget
    retry_credit: float    # share of credit retained on a retry


DIFFICULTIES = {
    "guided": Difficulty("guided", "Guided", "Hints and worked examples are always available. "
                         "Generous tolerances. Recommended for newcomers to risk management.",
                         "always", True, 3, 1.5, 0.7, 1.2, 0.8),
    "standard": Difficulty("standard", "Professional", "Hints on request. Normal tolerances "
                           "and event severity.", "on_request", True, 1, 1.0, 1.0, 1.0, 0.6),
    "expert": Difficulty("expert", "Executive", "No worked examples, hints only after an "
                         "error, tight tolerances and harsher events.", "after_error", False,
                         0, 0.6, 1.3, 0.85, 0.5),
}


def scaffolding_level(recent: list[float]) -> str:
    """Adaptive layer on top of the chosen difficulty.

    'support'  - recent performance is weak: offer hints proactively, show the
                 worked example first, break steps into sub-checklists.
    'normal'   - default.
    'stretch'  - consistent mastery: hide hints unless asked, add ambiguity
                 (stretch documents) and tighter tolerances.
    """
    if len(recent) < 3:
        return "normal"
    window = recent[-6:]
    m = sum(window) / len(window)
    if m < 0.5:
        return "support"
    if m >= 0.85 and len(window) >= 5:
        return "stretch"
    return "normal"


def effective_tolerance(base_pct: float, diff: Difficulty, level: str) -> float:
    t = base_pct * diff.tolerance_mult
    if level == "stretch":
        t *= 0.75
    elif level == "support":
        t *= 1.25
    return t


def hint_available(diff: Difficulty, level: str, had_error: bool) -> bool:
    if level == "support" or diff.hints == "always":
        return True
    if diff.hints == "on_request":
        return True
    return had_error


def hint_auto_open(diff: Difficulty, level: str) -> bool:
    return level == "support" or diff.hints == "always"
