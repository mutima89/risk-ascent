"""Learning engine: spaced review (Leitner boxes) and confidence calibration.

All review data is local. Intervals are configurable (in game days; one game
day equals one real calendar day by default, measured from the local clock).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Sequence

DEFAULT_INTERVALS = [1, 3, 7, 14, 30, 60]


@dataclass
class ReviewCard:
    concept_id: str
    box: int = 0
    due: str = ""  # ISO date
    reviews: int = 0
    lapses: int = 0
    last_result: str = ""

    def is_due(self, today: date) -> bool:
        return not self.due or date.fromisoformat(self.due) <= today


def schedule(card: ReviewCard, correct: bool, today: date,
             intervals: Sequence[int] = DEFAULT_INTERVALS) -> ReviewCard:
    """Correct answers move the card up one box (longer interval); errors
    return it to box 0 for tomorrow. No penalties beyond rescheduling."""
    if not intervals or any(i <= 0 for i in intervals):
        raise ValueError("Intervals must be positive")
    if correct:
        card.box = min(card.box + 1, len(intervals) - 1)
    else:
        card.box = 0
        card.lapses += 1
    card.reviews += 1
    card.last_result = "correct" if correct else "incorrect"
    card.due = (today + timedelta(days=intervals[card.box])).isoformat()
    return card


def due_cards(cards: Sequence[ReviewCard], today: date, limit: int = 10) -> list[ReviewCard]:
    due = [c for c in cards if c.is_due(today)]
    due.sort(key=lambda c: (c.due or "", c.box))
    return due[:limit]


@dataclass
class Calibration:
    pairs: list[tuple[float, bool]] = field(default_factory=list)  # (confidence 0.5-1, correct)

    def add(self, confidence: float, correct: bool) -> None:
        if not 0 <= confidence <= 1:
            raise ValueError("Confidence must be between 0 and 1")
        self.pairs.append((confidence, correct))

    def brier(self) -> float | None:
        if not self.pairs:
            return None
        return sum((c - (1.0 if ok else 0.0)) ** 2 for c, ok in self.pairs) / len(self.pairs)

    def bins(self) -> list[dict]:
        edges = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]
        out = []
        for lo, hi in edges:
            sel = [(c, ok) for c, ok in self.pairs if lo <= c < hi]
            if sel:
                out.append({"range": f"{int(lo * 100)}-{min(100, int(hi * 100))}%",
                            "mean_conf": sum(c for c, _ in sel) / len(sel),
                            "accuracy": sum(1 for _, ok in sel if ok) / len(sel),
                            "n": len(sel)})
        return out

    def bias(self) -> float | None:
        """Mean confidence minus accuracy. Positive = overconfident."""
        if not self.pairs:
            return None
        mc = sum(c for c, _ in self.pairs) / len(self.pairs)
        acc = sum(1 for _, ok in self.pairs if ok) / len(self.pairs)
        return mc - acc

    def message(self) -> str:
        b = self.bias()
        n = len(self.pairs)
        if b is None or n < 5:
            return ("Record your confidence on a few more decisions to see a calibration "
                    "profile (at least 5 needed).")
        if b > 0.12:
            return (f"Across {n} rated decisions you were overconfident by about {b * 100:.0f} "
                    "points. Before committing, ask what evidence would change your mind and "
                    "what you have not yet checked.")
        if b < -0.12:
            return (f"Across {n} rated decisions you were underconfident by about {-b * 100:.0f} "
                    "points. Your analysis is better than you credit; state conclusions more "
                    "firmly when the evidence supports them.")
        return (f"Across {n} rated decisions your confidence tracked your accuracy within "
                f"{abs(b) * 100:.0f} points. That is well calibrated.")

    def summary(self) -> dict:
        return {"n": len(self.pairs), "brier": self.brier(), "bias": self.bias(),
                "bins": self.bins(), "message": self.message()}
