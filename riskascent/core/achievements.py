"""Achievement rules.

Every achievement is tied to a specific, verifiable condition evaluated
against recorded game statistics. No achievement is granted for time spent,
log-in streaks or random chance.
"""

from __future__ import annotations

from typing import Any

# Supported condition types and the stats they read:
#   mission:        {"type": "mission", "id": str, "min_score": float}
#   missions_count: {"type": "missions_count", "n": int, "mission_type": str?, "min_score": float?}
#   level:          {"type": "level", "n": int}
#   competency:     {"type": "competency", "key": str, "min": float}
#   branch_tier:    {"type": "branch_tier", "branch": str, "tier": int}
#   counter:        {"type": "counter", "key": str, "n": int}
#   flag:           {"type": "flag", "flag": str}
#   calibration:    {"type": "calibration", "max_abs_bias": float, "min_n": int}
#   all_branches:   {"type": "all_branches", "tier": int}
#   stakeholder:    {"type": "stakeholder", "min_trust": float, "count": int}
#   path:           {"type": "path", "id": str}

def check(cond: dict, stats: dict[str, Any]) -> bool:
    t = cond["type"]
    if t == "mission":
        best = stats.get("best_scores", {}).get(cond["id"])
        return best is not None and best >= cond.get("min_score", 0.0)
    if t == "missions_count":
        rows = stats.get("completed", [])
        if cond.get("mission_type"):
            rows = [r for r in rows if r["type"] == cond["mission_type"]]
        if "min_score" in cond:
            rows = [r for r in rows if r["score"] >= cond["min_score"]]
        return len({r["id"] for r in rows}) >= cond["n"]
    if t == "level":
        return stats.get("level", 1) >= cond["n"]
    if t == "competency":
        return stats.get("competencies", {}).get(cond["key"], 0) >= cond["min"]
    if t == "branch_tier":
        return stats.get("branch_tiers", {}).get(cond["branch"], 0) >= cond["tier"]
    if t == "counter":
        return stats.get("counters", {}).get(cond["key"], 0) >= cond["n"]
    if t == "flag":
        return cond["flag"] in stats.get("flags", set())
    if t == "calibration":
        cal = stats.get("calibration", {})
        return (cal.get("n", 0) >= cond.get("min_n", 10) and cal.get("bias") is not None
                and abs(cal["bias"]) <= cond["max_abs_bias"])
    if t == "all_branches":
        tiers = stats.get("branch_tiers", {})
        return len(tiers) >= 5 and all(v >= cond["tier"] for v in tiers.values())
    if t == "stakeholder":
        trust = stats.get("stakeholder_trust", {})
        return sum(1 for v in trust.values() if v >= cond["min_trust"]) >= cond["count"]
    if t == "path":
        return cond["id"] in stats.get("paths_completed", set())
    raise ValueError(f"Unknown achievement condition type: {t}")


def evaluate(definitions: list[dict], stats: dict[str, Any], already: set[str]) -> list[dict]:
    """Return newly earned achievement definitions."""
    return [d for d in definitions if d["id"] not in already and check(d["condition"], stats)]
