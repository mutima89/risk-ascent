"""Financial risk modelling.

All money values are in the organisation's currency. Probabilities are
annual unless stated. Every function documents its formula so the UI can
show assumptions alongside results.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np


def _check_prob(p: float, name: str = "probability") -> None:
    if not (0.0 <= p <= 1.0) or math.isnan(p):
        raise ValueError(f"{name} must be between 0 and 1")


def _check_nonneg(x: float, name: str) -> None:
    if x < 0 or math.isnan(x):
        raise ValueError(f"{name} cannot be negative")


def expected_loss(probability: float, impact: float) -> float:
    """EL = p x impact."""
    _check_prob(probability)
    _check_nonneg(impact, "impact")
    return probability * impact


def scenario_weighted_loss(scenarios: Sequence[tuple[float, float]]) -> dict:
    """Probability-weighted loss across mutually exclusive scenarios.

    scenarios: list of (probability, loss). Probabilities must sum to <= 1;
    the remainder is the 'no loss' scenario.
    Returns expected loss and worst-case (largest loss with non-zero p).
    """
    if not scenarios:
        raise ValueError("At least one scenario is required")
    total_p = 0.0
    el = 0.0
    worst = 0.0
    for p, loss in scenarios:
        _check_prob(p)
        _check_nonneg(loss, "loss")
        total_p += p
        el += p * loss
        if p > 0:
            worst = max(worst, loss)
    if total_p > 1.0 + 1e-9:
        raise ValueError(f"Scenario probabilities sum to {total_p:.3f} (> 1)")
    return {"expected_loss": el, "worst_case": worst, "p_no_loss": max(0.0, 1 - total_p)}


def npv(cashflows: Sequence[float], rate: float) -> float:
    """NPV = sum CF_t / (1+r)^t, t starting at 0."""
    if rate <= -1:
        raise ValueError("Discount rate must be greater than -100%")
    return sum(cf / (1 + rate) ** t for t, cf in enumerate(cashflows))


@dataclass
class CostBenefit:
    annual_risk_reduction: float
    total_cost: float
    npv: float
    roi: float  # (benefit - cost) / cost over the horizon, undiscounted
    payback_years: float | None
    benefit_cost_ratio: float


def cost_benefit(el_before: float, el_after: float, upfront_cost: float,
                 annual_cost: float, years: int = 3, discount_rate: float = 0.08) -> CostBenefit:
    """Cost-benefit of a risk treatment.

    Annual benefit = EL_before - EL_after (avoided expected loss).
    Cashflow year 0 = -upfront; years 1..n = benefit - annual_cost.
    ROI (a.k.a. ROSI for security controls) = (total benefit - total cost) / total cost.
    """
    for v, n in [(el_before, "EL before"), (el_after, "EL after"),
                 (upfront_cost, "upfront cost"), (annual_cost, "annual cost")]:
        _check_nonneg(v, n)
    if years < 1:
        raise ValueError("Horizon must be at least one year")
    benefit = el_before - el_after
    total_cost = upfront_cost + annual_cost * years
    flows = [-upfront_cost] + [benefit - annual_cost] * years
    value = npv(flows, discount_rate)
    roi = (benefit * years - total_cost) / total_cost if total_cost > 0 else float("inf")
    net_annual = benefit - annual_cost
    payback = (upfront_cost / net_annual) if net_annual > 0 else None
    bcr = (benefit * years) / total_cost if total_cost > 0 else float("inf")
    return CostBenefit(benefit, total_cost, value, roi, payback, bcr)


def lognormal_params(median: float, p90: float) -> tuple[float, float]:
    """mu, sigma of a lognormal from its median and 90th percentile."""
    if median <= 0 or p90 <= median:
        raise ValueError("Need 0 < median < p90")
    mu = math.log(median)
    sigma = (math.log(p90) - mu) / 1.2815515655446004
    return mu, sigma


@dataclass
class MonteCarloResult:
    losses: np.ndarray
    mean: float
    median: float
    p90: float
    p95: float
    p99: float
    expected_shortfall_95: float
    prob_any_loss: float
    seed: int
    n: int

    def prob_exceeding(self, threshold: float) -> float:
        return float((self.losses > threshold).mean())

    def summary(self) -> dict:
        return {"mean": self.mean, "median": self.median, "p90": self.p90,
                "p95": self.p95, "p99": self.p99, "es95": self.expected_shortfall_95,
                "prob_any_loss": self.prob_any_loss, "seed": self.seed, "n": self.n}


def monte_carlo_annual_loss(frequency: float, severity_median: float, severity_p90: float,
                            n: int = 20_000, seed: int = 42,
                            severity_cap: float | None = None) -> MonteCarloResult:
    """Simulate annual aggregate loss.

    Frequency ~ Poisson(lambda = expected events per year).
    Severity  ~ Lognormal fitted to (median, p90), optionally capped
                (e.g. at an insurance limit or maximum credible loss).
    Seeded for reproducibility.
    """
    _check_nonneg(frequency, "frequency")
    if n < 100 or n > 1_000_000:
        raise ValueError("Number of simulations must be 100-1,000,000")
    mu, sigma = lognormal_params(severity_median, severity_p90)
    rng = np.random.default_rng(seed)
    counts = rng.poisson(frequency, size=n)
    total_events = int(counts.sum())
    sev = rng.lognormal(mu, sigma, size=total_events)
    if severity_cap is not None:
        sev = np.minimum(sev, severity_cap)
    losses = np.zeros(n)
    if total_events:
        idx = np.repeat(np.arange(n), counts)
        np.add.at(losses, idx, sev)
    p95 = float(np.percentile(losses, 95))
    tail = losses[losses >= p95]
    es = float(tail.mean()) if tail.size else p95
    return MonteCarloResult(
        losses=losses, mean=float(losses.mean()), median=float(np.median(losses)),
        p90=float(np.percentile(losses, 90)), p95=p95, p99=float(np.percentile(losses, 99)),
        expected_shortfall_95=es, prob_any_loss=float((counts > 0).mean()), seed=seed, n=n)


def contingency_reserve(result: MonteCarloResult, confidence: float = 0.9) -> dict:
    """Reserve needed to cover annual losses at a confidence level.

    Reserve = loss percentile at the confidence level. The 'unexpected loss'
    component is that percentile minus the mean (expected loss is usually
    budgeted in operating costs, not reserved).
    """
    _check_prob(confidence, "confidence")
    q = float(np.percentile(result.losses, confidence * 100))
    return {"reserve": q, "expected_loss": result.mean, "unexpected_loss": max(0.0, q - result.mean),
            "confidence": confidence}


def tornado(model: Callable[[dict], float], base: dict, ranges: dict[str, tuple[float, float]]) -> list[dict]:
    """One-at-a-time sensitivity analysis.

    For each parameter, evaluate the model at its low and high value while
    holding others at base. Returns rows sorted by swing (largest first).
    """
    base_val = model(base)
    rows = []
    for name, (lo, hi) in ranges.items():
        lo_v = model({**base, name: lo})
        hi_v = model({**base, name: hi})
        rows.append({"parameter": name, "low": lo_v, "high": hi_v,
                     "swing": abs(hi_v - lo_v), "base": base_val})
    rows.sort(key=lambda r: r["swing"], reverse=True)
    return rows


@dataclass
class StressInputs:
    monthly_revenue: float
    monthly_costs: float
    cash: float
    committed_facility: float = 0.0
    monthly_debt_service: float = 0.0
    min_cash_covenant: float = 0.0


def stress_test(inp: StressInputs, revenue_shock: float, cost_shock: float = 0.0,
                facility_withdrawn: bool = False, months: int = 12) -> dict:
    """Basic liquidity stress test.

    Applies a % revenue fall and % cost increase, projects month-end cash and
    reports runway (months until cash + available facility < 0) and the first
    month the minimum-cash covenant is breached.
    """
    if not -1 <= revenue_shock <= 1 or not -1 <= cost_shock <= 2:
        raise ValueError("Shock outside plausible range")
    rev = inp.monthly_revenue * (1 - revenue_shock)
    cost = inp.monthly_costs * (1 + cost_shock) + inp.monthly_debt_service
    facility = 0.0 if facility_withdrawn else inp.committed_facility
    cash = inp.cash
    path = []
    runway = None
    breach = None
    for m in range(1, months + 1):
        cash += rev - cost
        path.append(cash)
        if breach is None and cash < inp.min_cash_covenant:
            breach = m
        if runway is None and cash + facility < 0:
            runway = m
    return {"monthly_net": rev - cost, "cash_path": path, "runway_months": runway,
            "covenant_breach_month": breach, "ending_cash": cash,
            "survives_horizon": runway is None}
