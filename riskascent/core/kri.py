"""Key Risk Indicators."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

STATUS_OK = "Normal"
STATUS_WARN = "Warning"
STATUS_CRIT = "Critical"


@dataclass
class KRI:
    kri_id: str
    name: str
    unit: str
    baseline: float
    current: float
    warning: float
    critical: float
    higher_is_worse: bool = True
    data_source: str = ""
    frequency: str = "Monthly"
    owner: str = ""
    escalation: str = ""
    linked_risk: str = ""
    history: list[float] = field(default_factory=list)
    drift: float = 0.0       # expected change per period without action
    volatility: float = 0.05  # relative std-dev of period noise

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("KRI name is required")
        if self.higher_is_worse and not self.warning < self.critical:
            raise ValueError("For 'higher is worse' KRIs the warning threshold must be below critical")
        if not self.higher_is_worse and not self.warning > self.critical:
            raise ValueError("For 'lower is worse' KRIs the warning threshold must be above critical")

    def status(self, value: float | None = None) -> str:
        v = self.current if value is None else value
        if self.higher_is_worse:
            if v >= self.critical:
                return STATUS_CRIT
            if v >= self.warning:
                return STATUS_WARN
        else:
            if v <= self.critical:
                return STATUS_CRIT
            if v <= self.warning:
                return STATUS_WARN
        return STATUS_OK

    def trend(self, window: int = 4) -> str:
        """'Worsening', 'Improving' or 'Stable' based on least-squares slope."""
        series = (self.history + [self.current])[-window:]
        s = slope(series)
        scale = max(abs(self.baseline), 1e-9)
        if abs(s) / scale < 0.02:
            return "Stable"
        worse = s > 0 if self.higher_is_worse else s < 0
        return "Worsening" if worse else "Improving"

    def record(self, value: float) -> tuple[str, str]:
        """Record a new reading; returns (old_status, new_status)."""
        old = self.status()
        self.history.append(self.current)
        self.current = value
        return old, self.status()

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, d: dict) -> "KRI":
        fields = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in fields})


def slope(series: Sequence[float]) -> float:
    n = len(series)
    if n < 2:
        return 0.0
    mx = (n - 1) / 2
    my = sum(series) / n
    num = sum((i - mx) * (y - my) for i, y in enumerate(series))
    den = sum((i - mx) ** 2 for i in range(n))
    return num / den if den else 0.0


def breach_events(kri: KRI, old: str, new: str) -> list[dict]:
    order = {STATUS_OK: 0, STATUS_WARN: 1, STATUS_CRIT: 2}
    if order[new] > order[old]:
        return [{"type": "kri_breach", "kri_id": kri.kri_id, "name": kri.name,
                 "level": new, "value": kri.current, "escalation": kri.escalation,
                 "owner": kri.owner}]
    if order[new] < order[old]:
        return [{"type": "kri_recovered", "kri_id": kri.kri_id, "name": kri.name,
                 "level": new, "value": kri.current}]
    return []
