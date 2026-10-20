"""Unit tests for the simulation and calculation engines."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from riskascent.core import controls, finance, learning
from riskascent.core.bcm import Process, criticality, recovery_order, validate_bia
from riskascent.core.crisis import build_exercise
from riskascent.core.kri import KRI, STATUS_CRIT, STATUS_OK, STATUS_WARN
from riskascent.core.mission_engine import optimal_allocation
from riskascent.core.risk_engine import (Appetite, ControlRating, RiskMatrix, heatmap_counts, prioritize,
                                         suggested_residual, validate_residual)
from riskascent.core.util import fmt_money, render, safe_eval, stable_seed


# ------------------------------------------------------------------ risk matrix
def test_matrix_scores_and_bands():
    m = RiskMatrix()
    assert m.rate(1, 1) == (1, "Low")
    assert m.rate(3, 3) == (9, "Medium")
    assert m.rate(3, 5) == (15, "High")
    assert m.rate(5, 5) == (25, "Critical")
    with pytest.raises(ValueError):
        m.score(0, 3)
    with pytest.raises(ValueError):
        m.score(6, 1)


def test_matrix_probability_and_amount_mapping():
    m = RiskMatrix()
    assert m.likelihood_from_probability(0.01) == 1
    assert m.likelihood_from_probability(0.3) == 3
    assert m.likelihood_from_probability(0.95) == 5
    assert m.impact_from_amount(10_000) == 1
    assert m.impact_from_amount(2_000_000) == 4
    # money_scale stretches the impact bands for larger organisations
    assert m.impact_from_amount(2_000_000, scale=10) == 2


@pytest.mark.parametrize("size", [3, 4, 5])
def test_matrix_resizes(size):
    m = RiskMatrix.sized(size)
    assert m.size == size and len(m.likelihood_labels) == size
    assert m.band(size * size) == "Critical"
    assert RiskMatrix.from_dict(m.to_dict()).to_dict() == m.to_dict()


def test_matrix_rejects_bad_config():
    with pytest.raises(ValueError):
        RiskMatrix(size=2)
    with pytest.raises(ValueError):
        RiskMatrix(bands=[("Low", 9), ("High", 5), ("Critical", 25)])


def test_residual_controls_do_not_stack():
    weak = [ControlRating("Preventive", 1)] * 5
    strong = [ControlRating("Preventive", 4)]
    assert suggested_residual(4, 4, weak)[0] >= suggested_residual(4, 4, strong)[0]
    # Preventive reduces likelihood, detective/corrective reduce impact.
    rl, ri = suggested_residual(4, 4, [ControlRating("Detective", 4)])
    assert rl == 4 and ri < 4
    with pytest.raises(ValueError):
        ControlRating("Magic", 2)


def test_residual_validation_catches_common_errors():
    assert validate_residual((3, 3), (4, 3), 2)  # residual above inherent
    assert validate_residual((5, 5), (1, 1), 1)  # implausible reduction for weak controls
    assert validate_residual((4, 4), (4, 4), 4)  # effective controls but no reduction
    assert validate_residual((4, 4), (3, 4), 2) == []


def test_appetite_and_prioritisation():
    a = Appetite(6, 12, {"Compliance": (3, 6)})
    assert a.status("Strategic", 6) == "Within appetite"
    assert a.status("Strategic", 10) == "Above appetite"
    assert a.status("Compliance", 8) == "Outside tolerance"
    risks = [{"risk_id": "A", "category": "Strategic", "res_l": 2, "res_i": 2, "inh_l": 2, "inh_i": 2},
             {"risk_id": "B", "category": "Compliance", "res_l": 3, "res_i": 3, "inh_l": 4, "inh_i": 4}]
    assert prioritize(risks, a)[0]["risk_id"] == "B"
    counts = heatmap_counts(risks, 5, True)
    assert sum(map(sum, counts)) == 2


# ------------------------------------------------------------------ finance
def test_expected_loss_and_validation():
    assert finance.expected_loss(0.3, 500_000) == pytest.approx(150_000)
    with pytest.raises(ValueError):
        finance.expected_loss(1.5, 10)
    with pytest.raises(ValueError):
        finance.expected_loss(0.5, -1)


def test_scenario_weighted_loss():
    r = finance.scenario_weighted_loss([(0.1, 1_000_000), (0.3, 100_000)])
    assert r["expected_loss"] == pytest.approx(130_000)
    with pytest.raises(ValueError):
        finance.scenario_weighted_loss([(0.7, 1), (0.6, 1)])


def test_npv_and_cost_benefit():
    assert finance.npv([-100, 110], 0.10) == pytest.approx(0, abs=1e-9)
    cb = finance.cost_benefit(300_000, 120_000, 150_000, 20_000, years=3, discount_rate=0.08)
    assert cb.annual_risk_reduction == pytest.approx(180_000)
    assert cb.total_cost == pytest.approx(210_000)
    assert cb.payback_years == pytest.approx(150_000 / 160_000)
    assert cb.npv == pytest.approx(-150_000 + sum(160_000 / 1.08 ** t for t in (1, 2, 3)))
    assert cb.benefit_cost_ratio == pytest.approx(540_000 / 210_000)
    with pytest.raises(ValueError):
        finance.cost_benefit(1, 0, 1, 0, years=0)


def test_monte_carlo_is_reproducible_and_sane():
    a = finance.monte_carlo_annual_loss(0.5, 200_000, 800_000, n=20_000, seed=7)
    b = finance.monte_carlo_annual_loss(0.5, 200_000, 800_000, n=20_000, seed=7)
    assert np.array_equal(a.losses, b.losses)
    assert a.median <= a.p90 <= a.p95 <= a.p99
    assert a.expected_shortfall_95 >= a.p95
    # P(any loss) for Poisson(0.5) is 1 - e^-0.5 = 0.393
    assert a.prob_any_loss == pytest.approx(1 - np.exp(-0.5), abs=0.02)
    res = finance.contingency_reserve(a, 0.9)
    assert res["reserve"] == pytest.approx(a.p90, rel=0.01)


def test_lognormal_params_round_trip():
    mu, sigma = finance.lognormal_params(100_000, 400_000)
    assert np.exp(mu) == pytest.approx(100_000)
    assert np.exp(mu + 1.2815515655 * sigma) == pytest.approx(400_000, rel=1e-6)


def test_tornado_orders_by_swing():
    rows = finance.tornado(lambda p: p["a"] * 10 + p["b"], {"a": 1, "b": 1}, {"a": (0, 2), "b": (0, 2)})
    assert rows[0]["parameter"] == "a" and rows[0]["swing"] == 20


def test_stress_test_runway_and_covenant():
    inp = finance.StressInputs(monthly_revenue=100, monthly_costs=90, cash=50, committed_facility=20,
                               min_cash_covenant=30)
    base = finance.stress_test(inp, 0.0)
    assert base["survives_horizon"]
    shock = finance.stress_test(inp, 0.3)  # net -20/month
    assert shock["covenant_breach_month"] == 2 and shock["runway_months"] == 4
    assert finance.stress_test(inp, 0.3, facility_withdrawn=True)["runway_months"] == 3
    with pytest.raises(ValueError):
        finance.stress_test(inp, 2.0)


# ------------------------------------------------------------------ KRIs
def test_kri_thresholds_and_trend():
    k = KRI("K1", "Overdue actions", "count", 5, 5, 8, 14)
    assert k.status() == STATUS_OK
    assert k.record(9) == (STATUS_OK, STATUS_WARN)
    assert k.record(15) == (STATUS_WARN, STATUS_CRIT)
    assert k.trend() == "Worsening"
    low = KRI("K2", "Occupancy", "%", 80, 80, 70, 62, higher_is_worse=False)
    assert low.status(65) == STATUS_WARN and low.status(60) == STATUS_CRIT
    with pytest.raises(ValueError):
        KRI("K3", "Bad", "%", 1, 1, 10, 5)
    assert KRI.from_dict(k.to_dict()) == k


# ------------------------------------------------------------------ controls and BIA
def test_control_design_and_operating_tests():
    all_yes = {k: True for k, _ in controls.DESIGN_CRITERIA}
    assert controls.design_rating(all_yes) == (4, [])
    no_owner = dict(all_yes, owner=False)
    assert controls.design_rating(no_owner)[0] == 1
    assert controls.operating_result("Daily", 10, 0)["conclusion"] == "Insufficient evidence"
    assert controls.operating_result("Daily", 25, 0)["rating"] == 4
    assert controls.operating_result("Daily", 25, 1)["rating"] == 2
    assert controls.operating_result("Quarterly", 2, 1)["rating"] == 1
    with pytest.raises(ValueError):
        controls.operating_result("Daily", 5, 6)
    assert controls.combined_effectiveness(4, 1) == 1
    assert controls.combined_effectiveness(4, None) == 2


def test_bia_checks():
    pay = Process("PAY", "Payments", "CFO", [2, 4, 5, 5], 24, 36, 1, ["IT"])
    it = Process("IT", "IT platform", "CIO", [1, 3, 4, 5], 72, 48, 4)
    assert criticality(pay) == "Tier 1 - Critical"
    issues = validate_bia([pay, it])
    assert any("RTO" in i and "MTPD" in i for i in issues)
    assert any("IT platform" in i for i in issues)  # dependency recovers slower than dependant
    assert recovery_order([pay, it]).index("IT") < recovery_order([pay, it]).index("PAY")
    with pytest.raises(ValueError):
        Process("X", "X", "o", [3, 2, 1, 0], 1, 1, 1)


# ------------------------------------------------------------------ learning
def test_spaced_repetition_schedule():
    card = learning.ReviewCard("C1")
    today = date(2026, 1, 1)
    assert card.is_due(today)
    learning.schedule(card, True, today, [1, 3, 7])
    assert card.box == 1 and card.due == "2026-01-04"
    learning.schedule(card, False, today, [1, 3, 7])
    assert card.box == 0 and card.lapses == 1 and card.due == "2026-01-02"
    with pytest.raises(ValueError):
        learning.schedule(card, True, today, [0, 3])


def test_calibration_detects_overconfidence():
    cal = learning.Calibration()
    for i in range(20):
        cal.add(0.95, i % 2 == 0)
    assert cal.bias() > 0.3
    assert "overconfident" in cal.message().lower()
    assert 0 <= cal.brier() <= 1


# ------------------------------------------------------------------ crisis, utils
def test_crisis_exercise_is_seeded(content):
    a = build_exercise(content.crisis_threats, 99, 4)
    b = build_exercise(content.crisis_threats, 99, 4)
    assert [t.tid for t in a.threats] == [t.tid for t in b.threats]
    for ex in (a, b):
        while not ex.finished:
            worst = max(ex.active(), key=lambda t: t.severity)
            ex.play_turn([("investigate", worst.tid), ("contain", worst.tid)])
    assert a.score() == b.score()


def test_safe_eval_blocks_code():
    assert safe_eval("p * impact + 2 ** 3", {"p": 0.5, "impact": 100}) == 58
    for bad in ["__import__('os').system('echo hi')", "open('x')", "(1).__class__", "[x for x in ()]"]:
        with pytest.raises(Exception):
            safe_eval(bad, {})


def test_stable_seed_and_rendering():
    assert stable_seed("M01", 3) == stable_seed("M01", 3)
    assert stable_seed("M01", 3) != stable_seed("M01", 4)
    assert fmt_money(1_250_000, "SAR").startswith("SAR")
    assert "SAR" in render("Budget {m:100000}", {"currency": "SAR", "money_scale": 1.0, "people": {}})


def test_optimal_allocation():
    items = [{"id": "a", "cost": 5, "value": 10}, {"id": "b", "cost": 4, "value": 7},
             {"id": "c", "cost": 3, "value": 6}]
    ids, value = optimal_allocation(items, 7)
    assert set(ids) == {"b", "c"} and value == 13
