"""Career ladder, promotion gates and compensation.

Compensation figures are ILLUSTRATIVE SIMULATION DATA. They are built from a
reference band per level and multipliers for geography, industry, size and
track. They are not survey data and do not represent guaranteed market rates.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Level:
    level: int
    title: str
    expert_title: str
    stage: int
    stage_name: str
    xp_required: int
    required_missions: list[str]
    capstone: str | None
    minima_management: dict[str, float]
    minima_expert: dict[str, float]
    authority_limit: float
    team_size: int
    salary_usd: tuple[float, float]
    bonus_pct: tuple[float, float]
    responsibilities: list[str]
    unlocks: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Level":
        return cls(level=d["level"], title=d["title"], expert_title=d.get("expert_title", d["title"]),
                   stage=d["stage"], stage_name=d["stage_name"], xp_required=d["xp_required"],
                   required_missions=list(d.get("required_missions", [])), capstone=d.get("capstone"),
                   minima_management=dict(d.get("minima", {})),
                   minima_expert=dict(d.get("minima_expert", d.get("minima", {}))),
                   authority_limit=float(d["authority_limit"]), team_size=int(d["team_size"]),
                   salary_usd=tuple(d["salary_usd"]), bonus_pct=tuple(d.get("bonus_pct", (0, 0))),
                   responsibilities=list(d["responsibilities"]), unlocks=list(d.get("unlocks", [])))

    def title_for(self, path: str) -> str:
        return self.expert_title if path == "expert" else self.title

    def minima_for(self, path: str) -> dict[str, float]:
        return self.minima_expert if path == "expert" else self.minima_management


@dataclass
class PromotionCheck:
    label: str
    passed: bool
    detail: str


def promotion_checks(current: Level, nxt: Level | None, path: str, xp: int,
                     best_scores: dict[str, float], competencies: dict[str, float],
                     mission_titles: dict[str, str], pass_mark: float = 0.6,
                     capstone_mark: float = 0.7) -> list[PromotionCheck]:
    """Every gate the player must clear to be considered for the next level.

    Promotion needs ALL of: enough XP from demonstrated work, the level's
    core missions completed to standard, the stage capstone (if any) passed,
    and minimum competency scores for the next role on the chosen path.
    """
    if nxt is None:
        return []
    checks = [PromotionCheck("Experience", xp >= nxt.xp_required, f"{xp} / {nxt.xp_required} XP")]
    for mid in current.required_missions:
        s = best_scores.get(mid)
        checks.append(PromotionCheck(
            f"Core assignment: {mission_titles.get(mid, mid)}",
            s is not None and s >= pass_mark,
            "Not attempted" if s is None else f"Best score {s * 100:.0f}% (need {pass_mark * 100:.0f}%)"))
    if current.capstone:
        s = best_scores.get(current.capstone)
        checks.append(PromotionCheck(
            f"Stage capstone: {mission_titles.get(current.capstone, current.capstone)}",
            s is not None and s >= capstone_mark,
            "Not attempted" if s is None else f"Best score {s * 100:.0f}% (need {capstone_mark * 100:.0f}%)"))
    for comp, minimum in nxt.minima_for(path).items():
        v = competencies.get(comp, 0)
        checks.append(PromotionCheck(f"Competency: {comp}", v >= minimum, f"{v:.0f} / {minimum:.0f}"))
    return checks


def eligible(checks: list[PromotionCheck]) -> bool:
    return bool(checks) and all(c.passed for c in checks)


@dataclass
class CompContext:
    geography: dict  # {"key","label","currency","fx","multiplier"}
    industry_mult: float
    size_mult: float
    track_mult: float


def salary_range(level: Level, ctx: CompContext) -> dict:
    """Illustrative base salary range in local currency.

    local = USD reference band x geography x industry x size x track x FX.
    """
    m = ctx.geography["multiplier"] * ctx.industry_mult * ctx.size_mult * ctx.track_mult
    fx = ctx.geography["fx"]
    lo, hi = level.salary_usd
    lo_l, hi_l = lo * m * fx, hi * m * fx
    return {"min": round(lo_l, -3), "mid": round((lo_l + hi_l) / 2, -3), "max": round(hi_l, -3),
            "currency": ctx.geography["currency"], "bonus_pct": level.bonus_pct,
            "label": "Illustrative simulation data - not a market survey or guaranteed rate"}


def negotiate(offer_range: dict, ask_position: float, evidence_strength: float,
              trust: float) -> dict:
    """Salary negotiation outcome.

    ask_position: 0 (bottom of range) .. 1 (top). evidence_strength 0..1 from
    the player's portfolio. trust 0..100 with the hiring executive.
    An ask well beyond what the evidence supports is countered at a lower
    point and costs a little trust; a well-evidenced ask is usually met.
    """
    if not 0 <= ask_position <= 1:
        raise ValueError("Ask position must be 0..1")
    supported = 0.2 + 0.6 * evidence_strength + 0.2 * (trust / 100)
    if ask_position <= supported + 0.05:
        pos, trust_delta, note = ask_position, 2, "Your request was supported by your track record and accepted."
    else:
        pos = (supported + ask_position) / 2 if ask_position - supported < 0.25 else supported
        trust_delta = -3 if ask_position - supported >= 0.25 else 0
        note = ("The offer was countered. Your evidence supported a position around "
                f"{supported * 100:.0f}% of the range; anchoring far above it without new "
                "evidence weakened the conversation.")
    salary = offer_range["min"] + pos * (offer_range["max"] - offer_range["min"])
    return {"salary": round(salary, -3), "position": pos, "supported": supported,
            "trust_delta": trust_delta, "note": note}
