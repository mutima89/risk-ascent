"""Escalating crisis mode (Crisis Command Center).

Several threats develop at once. The player has limited response capacity
each turn and incomplete information: the visible severity of a threat is an
estimate until it is investigated. Threats grow each turn unless contained.
New threats can emerge mid-exercise. Fully seeded and replayable.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .util import clamp, stable_seed

ACTIONS = {
    "investigate": {"cost": 1, "label": "Investigate", "desc": "Establish facts. Reveals true severity and makes containment more effective."},
    "contain": {"cost": 2, "label": "Contain", "desc": "Commit responders to reduce severity. Far more effective once the facts are known."},
    "communicate": {"cost": 1, "label": "Communicate", "desc": "Brief stakeholders and the public. Halves reputational spread this turn and protects trust."},
    "escalate": {"cost": 1, "label": "Escalate to executives", "desc": "Mobilise executive support: +2 capacity next turn. Escalating minor threats costs credibility."},
}


@dataclass
class Threat:
    tid: str
    name: str
    domain: str
    severity: float
    growth: float
    reputational: float  # 0..1 share of growth that is reputational spread
    estimate_error: float
    investigated: bool = False
    resolved: bool = False
    failed: bool = False
    appears_turn: int = 1

    def visible(self) -> float:
        if self.investigated:
            return round(self.severity, 1)
        return round(clamp(self.severity * (1 + self.estimate_error), 0, 100), 1)


@dataclass
class CrisisExercise:
    seed: int
    turns: int
    base_capacity: int
    threats: list[Threat]
    turn: int = 1
    reputation: float = 70.0
    credibility: float = 70.0
    bonus_capacity: int = 0
    log: list[str] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    finished: bool = False

    def active(self) -> list[Threat]:
        return [t for t in self.threats if t.appears_turn <= self.turn and not t.resolved and not t.failed]

    def capacity(self) -> int:
        return self.base_capacity + self.bonus_capacity

    def play_turn(self, plan: list[tuple[str, str]]) -> list[str]:
        """plan: list of (action, threat_id). Returns the turn's log lines."""
        if self.finished:
            raise RuntimeError("Exercise finished")
        cost = sum(ACTIONS[a]["cost"] for a, _ in plan)
        if cost > self.capacity():
            raise ValueError(f"Plan needs {cost} capacity; only {self.capacity()} available")
        by_id = {t.tid: t for t in self.active()}
        lines: list[str] = []
        communicated: set[str] = set()
        contained: set[str] = set()
        next_bonus = 0
        rng = random.Random(stable_seed(self.seed, self.turn, "crisis"))
        # Prioritisation evidence: was the most severe threat addressed?
        worst = max(self.active(), key=lambda t: t.severity, default=None)
        addressed = {tid for _, tid in plan}
        self.history.append({"turn": self.turn, "worst": worst.tid if worst else None,
                             "addressed_worst": bool(worst and worst.tid in addressed),
                             "plan": list(plan)})
        for action, tid in plan:
            t = by_id.get(tid)
            if t is None:
                raise ValueError(f"Threat {tid} is not active")
            if action == "investigate":
                t.investigated = True
                lines.append(f"Investigated {t.name}: true severity {t.severity:.0f}.")
            elif action == "contain":
                cut = (24 if t.investigated else 11) + rng.uniform(-3, 3)
                t.severity = clamp(t.severity - cut, 0, 100)
                contained.add(tid)
                lines.append(f"Containment on {t.name} reduced severity by {cut:.0f}"
                             + ("" if t.investigated else " (limited: facts not yet established)") + ".")
            elif action == "communicate":
                communicated.add(tid)
                self.credibility = clamp(self.credibility + 2, 0, 100)
                lines.append(f"Stakeholder briefing issued on {t.name}.")
            elif action == "escalate":
                if t.severity >= 45:
                    next_bonus += 2
                    self.credibility = clamp(self.credibility + 3, 0, 100)
                    lines.append(f"Escalated {t.name}; executives commit extra resources next turn.")
                else:
                    next_bonus += 1
                    self.credibility = clamp(self.credibility - 6, 0, 100)
                    lines.append(f"Escalated {t.name}, but executives judged it minor. Credibility fell.")
            else:
                raise ValueError(f"Unknown action {action}")
        # Growth of everything not contained this turn.
        for t in self.active():
            if t.tid in contained:
                growth = t.growth * 0.2
            else:
                growth = t.growth * (1 + rng.uniform(-0.25, 0.35))
            rep = growth * t.reputational * (0.5 if t.tid in communicated else 1.0)
            self.reputation = clamp(self.reputation - rep * 0.5, 0, 100)
            t.severity = clamp(t.severity + growth, 0, 100)
            if t.severity <= 5:
                t.resolved = True
                lines.append(f"{t.name} is under control.")
            elif t.severity >= 100:
                t.failed = True
                self.reputation = clamp(self.reputation - 12, 0, 100)
                lines.append(f"{t.name} escalated beyond control. Major impact.")
        self.bonus_capacity = next_bonus
        self.turn += 1
        for t in self.threats:
            if t.appears_turn == self.turn:
                lines.append(f"NEW: {t.name} reported (initial estimate {t.visible():.0f}).")
        if self.turn > self.turns or not [t for t in self.threats if not t.resolved and not t.failed]:
            self.finished = True
            lines.append("Exercise complete.")
        self.log.extend(f"T{self.turn - 1}: {l}" for l in lines)
        return lines

    def score(self) -> dict:
        residual = sum(t.severity for t in self.threats if not t.resolved) / max(1, len(self.threats))
        failed = sum(1 for t in self.threats if t.failed)
        prio = (sum(1 for h in self.history if h["addressed_worst"]) / len(self.history)) if self.history else 0
        containment = clamp(1 - residual / 100 - 0.25 * failed, 0, 1)
        s = 0.5 * containment + 0.2 * prio + 0.15 * self.reputation / 100 + 0.15 * self.credibility / 100
        return {"score": round(s, 3), "containment": round(containment, 3), "prioritisation": round(prio, 3),
                "reputation": round(self.reputation, 1), "credibility": round(self.credibility, 1),
                "failed": failed, "residual_severity": round(residual, 1)}


def build_exercise(templates: list[dict], seed: int, level: int, difficulty_mult: float = 1.0) -> CrisisExercise:
    """Pick threats from templates. Higher levels face more, faster threats."""
    rng = random.Random(stable_seed(seed, "build"))
    n = 3 if level < 7 else 4
    pool = list(templates)
    rng.shuffle(pool)
    chosen = pool[: n + 1]
    threats = []
    for i, tpl in enumerate(chosen):
        threats.append(Threat(
            tid=tpl["id"], name=tpl["name"], domain=tpl["domain"],
            severity=rng.uniform(*tpl["severity"]),
            growth=rng.uniform(*tpl["growth"]) * difficulty_mult * (1 + 0.04 * level),
            reputational=tpl.get("reputational", 0.3),
            estimate_error=rng.uniform(-0.45, 0.45),
            appears_turn=1 if i < n else 3))
    return CrisisExercise(seed=seed, turns=6, base_capacity=3 + (1 if level >= 8 else 0), threats=threats)
