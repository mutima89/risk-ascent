"""Living organisation simulation.

The World holds the organisation's state: financials, health indices,
stakeholder trust, flags set by earlier decisions, the risk register, KRIs,
the risk-function budget and scheduled (delayed) consequences.

Each period (one simulated month) `tick` advances the world:
  1. Operating cash flow.
  2. KRI readings move (drift + seeded noise, damped by controls).
  3. Delayed consequences of earlier decisions fire (or are averted).
  4. Register risks may materialise according to their residual likelihood.
  5. Industry random events may occur.
Every random draw uses a seed derived from (world seed, period, purpose) and
is logged, so any run can be reproduced exactly.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

from .kri import KRI, breach_events
from .risk_engine import RiskMatrix
from .util import clamp, fmt_money, render, stable_seed

INDEX_METRICS = ["confidence", "morale", "compliance", "control_effectiveness", "resilience",
                 "reputation", "strategic_progress"]
MONEY_METRICS = ["revenue", "operating_costs", "cash"]
METRIC_LABELS = {
    "revenue": "Revenue (annual)", "operating_costs": "Operating costs (annual)", "cash": "Cash & liquidity",
    "confidence": "Customer / stakeholder confidence", "morale": "Employee morale",
    "compliance": "Regulatory compliance", "control_effectiveness": "Control effectiveness",
    "resilience": "Operational resilience", "reputation": "Reputation",
    "risk_exposure": "Risk exposure", "strategic_progress": "Strategic progress",
}


@dataclass
class World:
    seed: int
    period: int
    metrics: dict[str, float]
    trust: dict[str, float]
    flags: set[str]
    budget: float
    kris: list[KRI]
    risks: list[dict]
    scheduled: list[dict] = field(default_factory=list)
    money_scale: float = 1.0
    currency: str = "USD"
    event_severity: float = 1.0
    ctx: dict = field(default_factory=dict)

    def exposure_index(self) -> float:
        """0-100 index of residual exposure from open register risks."""
        open_r = [r for r in self.risks if r.get("status") != "Closed"]
        if not open_r:
            return 0.0
        avg = sum(r["res_l"] * r["res_i"] for r in open_r) / len(open_r)
        return round(clamp(avg / 25 * 100, 0, 100), 1)

    def snapshot(self) -> dict[str, float]:
        snap = dict(self.metrics)
        snap["risk_exposure"] = self.exposure_index()
        return snap


def apply_effects(world: World, effects: dict, source: str = "") -> list[str]:
    """Apply an effects dict from content. Returns human-readable change notes."""
    notes: list[str] = []
    for k, v in effects.get("org", {}).items():
        if k in MONEY_METRICS:
            delta = v * world.money_scale
            world.metrics[k] = world.metrics.get(k, 0) + delta
            notes.append(f"{METRIC_LABELS.get(k, k)} {'+' if delta >= 0 else ''}{fmt_money(delta, world.currency)}")
        elif k in INDEX_METRICS:
            world.metrics[k] = clamp(world.metrics.get(k, 50) + v, 0, 100)
            notes.append(f"{METRIC_LABELS.get(k, k)} {'+' if v >= 0 else ''}{v:g}")
    for role, v in effects.get("trust", {}).items():
        world.trust[role] = clamp(world.trust.get(role, 50) + v, 0, 100)
        notes.append(f"Trust with {role.upper()} {'+' if v >= 0 else ''}{v:g}")
    for f in effects.get("flags", []):
        world.flags.add(f)
    for f in effects.get("unflags", []):
        world.flags.discard(f)
    if "budget" in effects:
        delta = effects["budget"] * world.money_scale
        world.budget += delta
        notes.append(f"Risk budget {'+' if delta >= 0 else ''}{fmt_money(delta, world.currency)}")
    for s in effects.get("schedule", []):
        world.scheduled.append({"event": s["event"], "due": world.period + int(s.get("after", 1)),
                                "p": float(s.get("p", 1.0)), "source": source})
    for s in effects.get("cancel", []):
        world.scheduled = [x for x in world.scheduled if x["event"] != s]
    for adj in effects.get("risk_adjust", []):
        for r in world.risks:
            if r.get("lib_id") == adj["risk"] or r["risk_id"] == adj["risk"]:
                r["res_l"] = int(clamp(r["res_l"] + adj.get("res_l", 0), 1, 5))
                r["res_i"] = int(clamp(r["res_i"] + adj.get("res_i", 0), 1, 5))
                if "control_eff" in adj:
                    r["control_eff"] = int(clamp(r.get("control_eff", 0) + adj["control_eff"], 0, 4))
                notes.append(f"Risk {r['risk_id']} residual now L{r['res_l']} x I{r['res_i']}")
    for adj in effects.get("kri_adjust", []):
        for k in world.kris:
            if k.kri_id == adj["kri"]:
                k.drift += adj.get("drift", 0)
                if "shift" in adj:
                    k.current = k.current * (1 + adj["shift"])
    return notes


def _monthly_prob(annual: float) -> float:
    annual = clamp(annual, 0, 0.999)
    return 1 - (1 - annual) ** (1 / 12)


def tick(world: World, events_lib: dict[str, dict], random_pool: list[dict],
         matrix: RiskMatrix | None = None) -> list[dict]:
    """Advance one period. Returns logged events."""
    matrix = matrix or RiskMatrix()
    world.period += 1
    log: list[dict] = []
    m = world.metrics

    # 1. Operating cash flow and gentle mean reversion of indices.
    net = (m["revenue"] - m["operating_costs"]) / 12
    m["cash"] += net
    for k in INDEX_METRICS:
        m[k] = clamp(m[k] + (55 - m[k]) * 0.02, 0, 100)

    # 2. KRIs.
    ctrl = m["control_effectiveness"] / 100
    for k in world.kris:
        rng = random.Random(stable_seed(world.seed, world.period, "kri", k.kri_id))
        noise = rng.gauss(0, k.volatility)
        damp = 1 - 0.5 * ctrl
        change = (k.drift * damp + noise)
        value = k.current * (1 + change) if k.current else k.baseline * change
        value = max(0.0, round(value, 3))
        old, new = k.record(value)
        for ev in breach_events(k, old, new):
            ev.update({"period": world.period, "title": f"KRI {ev['level'].lower()}: {k.name}",
                       "text": (f"{k.name} reached {value:g} {k.unit} (warning {k.warning:g}, critical "
                                f"{k.critical:g}). Required action: {k.escalation or 'review with owner'}.")
                       if ev["type"] == "kri_breach" else f"{k.name} back to {new.lower()} at {value:g} {k.unit}.",
                       "severity": 2 if ev["level"] == "Critical" else 1 if ev["type"] == "kri_breach" else 0})
            log.append(ev)

    # 3. Scheduled delayed consequences.
    remaining = []
    for s in world.scheduled:
        if s["due"] > world.period:
            remaining.append(s)
            continue
        ev_def = events_lib.get(s["event"])
        if not ev_def:
            continue
        log.extend(_fire_event(world, ev_def, s["p"], "scheduled", s.get("source", "")))
    world.scheduled = remaining

    # 4. Register risks materialising.
    incidents = 0
    for r in sorted(world.risks, key=lambda x: -(x["res_l"] * x["res_i"])):
        if r.get("status") == "Closed" or incidents >= 2:
            continue
        annual = matrix.midpoint_probability(r["res_l"]) * 0.6  # register midpoints are cautious
        p = _monthly_prob(annual)
        rng = random.Random(stable_seed(world.seed, world.period, "risk", r["risk_id"]))
        roll = rng.random()
        if roll < p:
            incidents += 1
            sev = matrix.midpoint_impact(r["res_i"], world.money_scale) * 0.15
            sev *= rng.lognormvariate(0, 0.5) * world.event_severity
            m["cash"] -= sev
            rep = -min(8, r["res_i"] * 1.2)
            m["reputation"] = clamp(m["reputation"] + rep, 0, 100)
            controlled = r.get("control_eff", 0) >= 3
            log.append({
                "type": "incident", "period": world.period, "risk_id": r["risk_id"],
                "title": f"Incident: {r['title']}", "severity": 2 if r["res_i"] >= 4 else 1,
                "text": (f"{r['event'] or r['title']} occurred this month. Loss of "
                         f"{fmt_money(sev, world.currency)}. The monthly probability implied by "
                         f"residual likelihood {r['res_l']} was {p * 100:.1f}% (roll {roll:.3f})."),
                "judgement": ("Controls were rated effective, so this is consistent with residual "
                              "risk: some risk always remains. Review whether the control operated."
                              if controlled else
                              "Controls were weak or untested. Strengthening them would have reduced "
                              "the likelihood or severity of this event."),
                "loss": sev, "seed": world.seed, "roll": roll, "p": p})

    # 5. Random industry events.
    for ev_def in random_pool:
        rng = random.Random(stable_seed(world.seed, world.period, "rand", ev_def["id"]))
        roll = rng.random()
        if roll < ev_def.get("p_month", 0.02):
            log.extend(_fire_event(world, ev_def, 1.0, "random", "", forced_roll=roll))
            break  # at most one random event per month keeps the load manageable

    for e in log:
        e.setdefault("seed", world.seed)
    return log


def _fire_event(world: World, ev: dict, p: float, kind: str, source: str,
                forced_roll: float | None = None) -> list[dict]:
    rng = random.Random(stable_seed(world.seed, world.period, "event", ev["id"]))
    roll = rng.random() if forced_roll is None else forced_roll
    if forced_roll is None and roll >= p:
        return [{"type": "averted", "period": world.period, "title": f"Averted: {ev['title']}",
                 "text": f"A consequence of an earlier decision ({source or 'unknown'}) did not "
                         f"materialise this time (probability {p * 100:.0f}%, roll {roll:.3f}).",
                 "severity": 0, "roll": roll, "p": p}]
    mitigated = bool(set(ev.get("mitigated_by", [])) & world.flags)
    aggravated = bool(set(ev.get("aggravated_by", [])) & world.flags)
    mult = world.event_severity * (0.35 if mitigated else 1.0) * (1.4 if aggravated else 1.0)
    effects = ev.get("effects", {})
    scaled = {"org": {k: v * mult for k, v in effects.get("org", {}).items()},
              "trust": {k: v * mult for k, v in effects.get("trust", {}).items()},
              "flags": effects.get("flags", [])}
    notes = apply_effects(world, scaled, ev["id"])
    text = render(ev["text"], world.ctx)
    if mitigated:
        text += " " + render(ev.get("mitigated_text", "Earlier preparation significantly reduced the damage."), world.ctx)
    if aggravated:
        text += " " + render(ev.get("aggravated_text", "Earlier decisions made the situation worse."), world.ctx)
    judgement = ""
    if kind == "scheduled":
        judgement = ("This was a delayed consequence of an earlier decision." if not mitigated else
                     "This event was linked to earlier decisions; your preparation limited the impact.")
    elif kind == "random":
        judgement = (f"External event (monthly probability {ev.get('p_month', 0) * 100:.1f}%). "
                     "You did not cause it; your preparation determined how much it hurt.")
    return [{"type": kind, "event_id": ev["id"], "period": world.period, "title": ev["title"],
             "text": text, "severity": ev.get("severity", 1), "changes": notes,
             "judgement": judgement, "roll": roll, "p": p, "mitigated": mitigated,
             "aggravated": aggravated, "crisis": ev.get("crisis")}]
