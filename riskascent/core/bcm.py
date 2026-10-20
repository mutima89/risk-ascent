"""Business continuity: business impact analysis and recovery prioritisation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass
class Process:
    pid: str
    name: str
    owner: str
    # Impact score (0-5) if disrupted for 4h, 24h, 72h, 1 week.
    impact_curve: list[int]
    mtpd_hours: float  # maximum tolerable period of disruption
    rto_hours: float   # recovery time objective
    rpo_hours: float   # recovery point objective (data loss tolerance)
    dependencies: list[str] = field(default_factory=list)
    strategy: str = ""
    capability_hours: float | None = None  # demonstrated recovery time (from tests)

    TIME_POINTS = (4, 24, 72, 168)

    def __post_init__(self) -> None:
        if len(self.impact_curve) != 4 or any(not 0 <= x <= 5 for x in self.impact_curve):
            raise ValueError("Impact curve needs four scores between 0 and 5")
        if any(self.impact_curve[i] > self.impact_curve[i + 1] for i in range(3)):
            raise ValueError("Impact cannot decrease as disruption lengthens")
        for v, n in [(self.mtpd_hours, "MTPD"), (self.rto_hours, "RTO"), (self.rpo_hours, "RPO")]:
            if v < 0:
                raise ValueError(f"{n} cannot be negative")

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, d: dict) -> "Process":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def criticality(p: Process) -> str:
    """Tier from the earliest time point at which impact reaches 4+."""
    for t, score in zip(Process.TIME_POINTS, p.impact_curve):
        if score >= 4:
            return {4: "Tier 1 - Critical", 24: "Tier 1 - Critical", 72: "Tier 2 - Important",
                    168: "Tier 3 - Standard"}[t]
    return "Tier 4 - Deferrable"


def validate_bia(processes: Sequence[Process]) -> list[str]:
    """Return inconsistencies a reviewer would challenge."""
    issues = []
    by_id = {p.pid: p for p in processes}
    for p in processes:
        if p.rto_hours > p.mtpd_hours:
            issues.append(f"{p.name}: RTO ({p.rto_hours:g}h) exceeds MTPD ({p.mtpd_hours:g}h).")
        for d in p.dependencies:
            dep = by_id.get(d)
            if dep is None:
                issues.append(f"{p.name}: depends on unknown process '{d}'.")
            elif dep.rto_hours > p.rto_hours:
                issues.append(f"{p.name} (RTO {p.rto_hours:g}h) depends on {dep.name} "
                              f"(RTO {dep.rto_hours:g}h); the dependency recovers too slowly.")
        if p.capability_hours is not None and p.capability_hours > p.rto_hours:
            issues.append(f"{p.name}: tested recovery ({p.capability_hours:g}h) misses RTO "
                          f"({p.rto_hours:g}h). This is a continuity capability gap.")
        if not p.strategy.strip() and criticality(p).startswith("Tier 1"):
            issues.append(f"{p.name}: critical process has no continuity strategy.")
    if _has_cycle(processes):
        issues.append("Dependency cycle detected; recovery order cannot be determined.")
    return issues


def _has_cycle(processes: Sequence[Process]) -> bool:
    graph = {p.pid: list(p.dependencies) for p in processes}
    state: dict[str, int] = {}

    def visit(n: str) -> bool:
        if state.get(n) == 1:
            return True
        if state.get(n) == 2 or n not in graph:
            return False
        state[n] = 1
        if any(visit(m) for m in graph[n]):
            return True
        state[n] = 2
        return False

    return any(visit(p.pid) for p in processes)


def recovery_order(processes: Sequence[Process]) -> list[str]:
    """Dependencies first, then shortest RTO. Raises on cycles."""
    if _has_cycle(processes):
        raise ValueError("Dependency cycle detected")
    by_id = {p.pid: p for p in processes}
    order: list[str] = []
    done: set[str] = set()

    def place(pid: str) -> None:
        if pid in done or pid not in by_id:
            return
        for d in sorted(by_id[pid].dependencies, key=lambda x: by_id[x].rto_hours if x in by_id else 0):
            place(d)
        done.add(pid)
        order.append(pid)

    for p in sorted(processes, key=lambda x: (x.rto_hours, x.pid)):
        place(p.pid)
    return order
