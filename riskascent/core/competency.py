"""Competency model, skill branches and assessment rubrics.

Competency scores (0-100) move only when the player demonstrates
performance. Each piece of evidence nudges the score towards the observed
performance using an adaptive moving average, so early evidence moves the
score quickly and later evidence refines it. There is no way to buy
competency with points.
"""

from __future__ import annotations

from dataclasses import dataclass, field

COMPETENCIES: dict[str, str] = {
    "technical": "Technical accuracy",
    "evidence": "Evidence quality",
    "analysis": "Analytical reasoning",
    "prioritization": "Risk prioritisation",
    "financial": "Financial judgement",
    "decision": "Decision quality",
    "communication": "Communication",
    "stakeholder": "Stakeholder management",
    "ethics": "Ethical judgement",
    "leadership": "Leadership",
    "strategy": "Strategic thinking",
}

BRANCHES: dict[str, tuple[str, list[str]]] = {
    "analytical": ("Analytical Thinking", ["analysis", "evidence", "decision"]),
    "controls": ("Risk and Controls", ["technical", "prioritization"]),
    "quant": ("Financial and Quantitative Modelling", ["financial"]),
    "influence": ("Communication and Influence", ["communication", "stakeholder"]),
    "leadership": ("Leadership and Strategy", ["leadership", "strategy", "ethics"]),
}

TIERS = [
    # name, min branch score, min evidence count
    ("Beginner", 40, 2),
    ("Intermediate", 55, 6),
    ("Advanced", 70, 12),
    ("Executive", 82, 20),
]

STARTING_SCORE = 30.0


@dataclass
class CompetencyState:
    score: float = STARTING_SCORE
    evidence: int = 0
    history: list[float] = field(default_factory=list)  # recent observed performances

    def update(self, performance: float, weight: float = 1.0) -> float:
        """performance in 0..1; returns the delta applied."""
        if not 0 <= performance <= 1:
            raise ValueError("Performance must be between 0 and 1")
        alpha = max(0.12, 1.0 / (self.evidence + 2)) * max(0.25, min(weight, 1.5))
        alpha = min(alpha, 0.6)
        target = performance * 100
        old = self.score
        self.score = old + alpha * (target - old)
        self.evidence += 1
        self.history = (self.history + [performance])[-12:]
        return self.score - old

    def recent_mean(self, n: int = 5) -> float | None:
        if not self.history:
            return None
        h = self.history[-n:]
        return sum(h) / len(h)


def branch_score(states: dict[str, CompetencyState], branch: str) -> tuple[float, int]:
    _, members = BRANCHES[branch]
    scores = [states[m].score for m in members]
    ev = sum(states[m].evidence for m in members)
    return sum(scores) / len(scores), ev


def branch_tier(states: dict[str, CompetencyState], branch: str) -> int:
    """Number of tiers unlocked (0..4)."""
    score, ev = branch_score(states, branch)
    unlocked = 0
    for _, s_min, e_min in TIERS:
        if score >= s_min and ev >= e_min:
            unlocked += 1
        else:
            break
    return unlocked


def new_states() -> dict[str, CompetencyState]:
    return {k: CompetencyState() for k in COMPETENCIES}


def rating_label(score: float, expected: float) -> str:
    gap = score - expected
    if gap >= 10:
        return "Exceeds expectations"
    if gap >= 0:
        return "Meets expectations"
    if gap >= -10:
        return "Developing"
    return "Below expectations"


def performance_review(states: dict[str, CompetencyState], expectations: dict[str, float],
                       evidence: list[dict], recommendations: dict[str, list[str]],
                       calibration: dict | None = None) -> dict:
    """Build a structured performance review.

    expectations: competency -> expected score at the player's stage.
    evidence: recent mission results [{mission, title, score, competencies:{k: perf}}]
    recommendations: competency -> list of suggested activities.
    """
    rows = []
    for k, label in COMPETENCIES.items():
        st = states[k]
        exp = expectations.get(k, 50)
        rows.append({"key": k, "label": label, "score": round(st.score, 1),
                     "expected": exp, "gap": round(st.score - exp, 1),
                     "rating": rating_label(st.score, exp), "evidence": st.evidence})
    with_ev = [r for r in rows if r["evidence"] > 0]
    strengths = sorted(with_ev, key=lambda r: r["gap"], reverse=True)[:3]
    weaknesses = sorted(rows, key=lambda r: r["gap"])[:3]
    weaknesses = [w for w in weaknesses if w["gap"] < 5]

    def cite(comp: str, best: bool) -> list[str]:
        relevant = [e for e in evidence if comp in e.get("competencies", {})]
        relevant.sort(key=lambda e: e["competencies"][comp], reverse=best)
        return [f"{e['title']} ({e['competencies'][comp] * 100:.0f}%)" for e in relevant[:2]]

    for s in strengths:
        s["evidence_refs"] = cite(s["key"], True)
    for w in weaknesses:
        w["evidence_refs"] = cite(w["key"], False)
        w["development"] = recommendations.get(w["key"], [])[:3]

    met = sum(1 for r in rows if r["gap"] >= 0)
    overall = ("Exceeds expectations" if met >= 10 else "Meets expectations" if met >= 7
               else "Developing" if met >= 4 else "Below expectations")
    review = {"rows": rows, "strengths": strengths, "weaknesses": weaknesses,
              "overall": overall, "met": met, "total": len(rows)}
    if calibration:
        review["calibration"] = calibration
    return review
