"""Risk assessment engine.

Methodology (also documented in docs/GAME_DESIGN_AND_SCORING.md):

* Likelihood and impact are rated on ordinal scales (default 1-5).
* The qualitative risk score is likelihood x impact (1-25). This is an
  ORDINAL ranking aid, not a financial measurement: a score of 20 is not
  "twice as bad" as a score of 10. Quantitative analysis (expected loss,
  Monte Carlo) lives in finance.py and should be used for money decisions.
* Residual ratings come from the inherent rating reduced by control
  effectiveness. Preventive controls reduce likelihood; detective and
  corrective controls reduce impact.
* Appetite and tolerance thresholds are configured per risk category on the
  same ordinal score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

LIMITATIONS = (
    "Heat-map scores are ordinal. They rank risks for discussion; they do not "
    "measure money, cannot be meaningfully added across risks, and compress "
    "very different risks into the same cell (range compression). A 5x5 "
    "rating also hides uncertainty: the same cell can contain a well-understood "
    "risk and a poorly understood one. Use quantitative modelling for "
    "investment and capital decisions."
)

CONTROL_EFFECTIVENESS = ["None", "Weak", "Partial", "Effective", "Strong"]
CONTROL_TYPES = ["Preventive", "Detective", "Corrective"]
TREATMENTS = ["Mitigate", "Transfer", "Accept", "Avoid", "Pursue"]
RISK_CATEGORIES = [
    "Strategic", "Financial", "Operational", "Compliance", "Technology",
    "Cyber", "People", "Reputational", "Health & Safety", "Environmental",
    "Project", "Third Party", "Liquidity",
]

# How many ordinal steps a control of a given effectiveness removes.
_STEP_REDUCTION = {0: 0, 1: 0, 2: 1, 3: 1, 4: 2}


@dataclass
class RiskMatrix:
    """Configurable likelihood-impact matrix."""

    size: int = 5
    likelihood_labels: list[str] = field(default_factory=lambda: [
        "Rare", "Unlikely", "Possible", "Likely", "Almost certain"])
    impact_labels: list[str] = field(default_factory=lambda: [
        "Minor", "Moderate", "Significant", "Major", "Severe"])
    # Annual probability ranges attached to each likelihood rating.
    likelihood_ranges: list[tuple[float, float]] = field(default_factory=lambda: [
        (0.0, 0.05), (0.05, 0.20), (0.20, 0.50), (0.50, 0.80), (0.80, 1.0)])
    # Financial impact ranges (in org currency units, before scaling).
    impact_ranges: list[tuple[float, float]] = field(default_factory=lambda: [
        (0, 50_000), (50_000, 250_000), (250_000, 1_000_000),
        (1_000_000, 5_000_000), (5_000_000, 25_000_000)])
    # Upper bounds (inclusive) of each band on the L x I score.
    bands: list[tuple[str, int]] = field(default_factory=lambda: [
        ("Low", 4), ("Medium", 9), ("High", 15), ("Critical", 25)])

    def __post_init__(self) -> None:
        if not 3 <= self.size <= 7:
            raise ValueError("Matrix size must be between 3 and 7")
        if len(self.likelihood_labels) != self.size or len(self.impact_labels) != self.size:
            raise ValueError("Label count must equal matrix size")
        last = 0
        for _, upper in self.bands:
            if upper <= last:
                raise ValueError("Band thresholds must be strictly increasing")
            last = upper
        if last < self.size * self.size:
            raise ValueError("Highest band must cover the maximum score")

    def validate_rating(self, value: int, what: str = "rating") -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{what} must be an integer")
        if not 1 <= value <= self.size:
            raise ValueError(f"{what} must be between 1 and {self.size}")
        return value

    def score(self, likelihood: int, impact: int) -> int:
        self.validate_rating(likelihood, "Likelihood")
        self.validate_rating(impact, "Impact")
        return likelihood * impact

    def band(self, score: int) -> str:
        for name, upper in self.bands:
            if score <= upper:
                return name
        return self.bands[-1][0]

    def rate(self, likelihood: int, impact: int) -> tuple[int, str]:
        s = self.score(likelihood, impact)
        return s, self.band(s)

    def likelihood_from_probability(self, p: float) -> int:
        if not 0 <= p <= 1:
            raise ValueError("Probability must be between 0 and 1")
        for i, (lo, hi) in enumerate(self.likelihood_ranges):
            if p < hi or i == self.size - 1:
                return i + 1
        return self.size

    def impact_from_amount(self, amount: float, scale: float = 1.0) -> int:
        if amount < 0:
            raise ValueError("Impact amount cannot be negative")
        for i, (lo, hi) in enumerate(self.impact_ranges):
            if amount < hi * scale or i == self.size - 1:
                return i + 1
        return self.size

    def midpoint_probability(self, likelihood: int) -> float:
        lo, hi = self.likelihood_ranges[likelihood - 1]
        return (lo + hi) / 2

    def midpoint_impact(self, impact: int, scale: float = 1.0) -> float:
        lo, hi = self.impact_ranges[impact - 1]
        return (lo + hi) / 2 * scale

    def to_dict(self) -> dict:
        return {
            "size": self.size,
            "likelihood_labels": self.likelihood_labels,
            "impact_labels": self.impact_labels,
            "likelihood_ranges": [list(r) for r in self.likelihood_ranges],
            "impact_ranges": [list(r) for r in self.impact_ranges],
            "bands": [list(b) for b in self.bands],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RiskMatrix":
        return cls(
            size=d["size"],
            likelihood_labels=list(d["likelihood_labels"]),
            impact_labels=list(d["impact_labels"]),
            likelihood_ranges=[tuple(r) for r in d["likelihood_ranges"]],
            impact_ranges=[tuple(r) for r in d["impact_ranges"]],
            bands=[(b[0], int(b[1])) for b in d["bands"]],
        )

    @classmethod
    def sized(cls, size: int) -> "RiskMatrix":
        """Build a default matrix of the given size (3, 4 or 5)."""
        if size == 5:
            return cls()
        if size == 4:
            return cls(
                size=4,
                likelihood_labels=["Unlikely", "Possible", "Likely", "Almost certain"],
                impact_labels=["Minor", "Moderate", "Major", "Severe"],
                likelihood_ranges=[(0, 0.1), (0.1, 0.4), (0.4, 0.8), (0.8, 1.0)],
                impact_ranges=[(0, 100_000), (100_000, 1_000_000),
                               (1_000_000, 5_000_000), (5_000_000, 25_000_000)],
                bands=[("Low", 3), ("Medium", 6), ("High", 11), ("Critical", 16)],
            )
        if size == 3:
            return cls(
                size=3,
                likelihood_labels=["Low", "Medium", "High"],
                impact_labels=["Low", "Medium", "High"],
                likelihood_ranges=[(0, 0.2), (0.2, 0.6), (0.6, 1.0)],
                impact_ranges=[(0, 250_000), (250_000, 2_500_000), (2_500_000, 25_000_000)],
                bands=[("Low", 2), ("Medium", 4), ("High", 6), ("Critical", 9)],
            )
        raise ValueError("Default matrices exist for sizes 3, 4 and 5")


@dataclass
class ControlRating:
    control_type: str  # Preventive / Detective / Corrective
    effectiveness: int  # 0..4

    def __post_init__(self) -> None:
        if self.control_type not in CONTROL_TYPES:
            raise ValueError(f"Unknown control type: {self.control_type}")
        if not 0 <= self.effectiveness <= 4:
            raise ValueError("Control effectiveness must be 0-4")


def suggested_residual(likelihood: int, impact: int,
                       controls: Iterable[ControlRating]) -> tuple[int, int]:
    """Residual (likelihood, impact) after controls.

    The strongest preventive control reduces likelihood; the strongest
    detective/corrective control reduces impact. Controls do not stack
    beyond the strongest in each family, which avoids the common error of
    claiming large reductions from many weak controls.
    """
    prev = 0
    corr = 0
    for c in controls:
        if c.control_type == "Preventive":
            prev = max(prev, c.effectiveness)
        else:
            corr = max(corr, c.effectiveness)
    rl = max(1, likelihood - _STEP_REDUCTION[prev])
    ri = max(1, impact - _STEP_REDUCTION[corr])
    return rl, ri


def overall_effectiveness(controls: Sequence[ControlRating]) -> int:
    if not controls:
        return 0
    return max(c.effectiveness for c in controls)


def validate_residual(inherent: tuple[int, int], residual: tuple[int, int],
                      effectiveness: int) -> list[str]:
    """Return warnings about an analyst's residual rating."""
    warnings: list[str] = []
    il, ii = inherent
    rl, ri = residual
    if rl > il or ri > ii:
        warnings.append("Residual rating exceeds inherent rating. Controls cannot "
                        "increase risk; re-check the inherent assessment.")
    reduction = (il - rl) + (ii - ri)
    allowed = _STEP_REDUCTION[effectiveness] * 2
    if reduction > allowed:
        warnings.append(f"Residual reduces risk by {reduction} steps but control "
                        f"effectiveness '{CONTROL_EFFECTIVENESS[effectiveness]}' "
                        f"supports at most {allowed}. Provide evidence or revise.")
    if effectiveness >= 3 and reduction == 0:
        warnings.append("Controls are rated effective but residual equals inherent. "
                        "Either the controls do not address this risk or the "
                        "effectiveness rating is overstated.")
    return warnings


@dataclass
class Appetite:
    """Appetite and tolerance thresholds on the ordinal score, per category."""

    default_appetite: int = 6
    default_tolerance: int = 12
    by_category: dict[str, tuple[int, int]] = field(default_factory=dict)

    def thresholds(self, category: str) -> tuple[int, int]:
        return self.by_category.get(category, (self.default_appetite, self.default_tolerance))

    def status(self, category: str, score: int) -> str:
        appetite, tolerance = self.thresholds(category)
        if score <= appetite:
            return "Within appetite"
        if score <= tolerance:
            return "Above appetite"
        return "Outside tolerance"

    def to_dict(self) -> dict:
        return {"default_appetite": self.default_appetite,
                "default_tolerance": self.default_tolerance,
                "by_category": {k: list(v) for k, v in self.by_category.items()}}

    @classmethod
    def from_dict(cls, d: dict) -> "Appetite":
        return cls(d.get("default_appetite", 6), d.get("default_tolerance", 12),
                   {k: (int(v[0]), int(v[1])) for k, v in d.get("by_category", {}).items()})


APPETITE_ORDER = {"Outside tolerance": 2, "Above appetite": 1, "Within appetite": 0}


def prioritize(risks: Sequence[dict], appetite: Appetite) -> list[dict]:
    """Sort risks for management attention.

    Order: appetite status (outside tolerance first), residual score,
    residual impact (severity before frequency), then inherent score.
    Each risk dict needs: category, res_l, res_i, inh_l, inh_i.
    """
    def key(r: dict):
        rs = r["res_l"] * r["res_i"]
        st = APPETITE_ORDER[appetite.status(r.get("category", ""), rs)]
        return (-st, -rs, -r["res_i"], -(r["inh_l"] * r["inh_i"]))
    return sorted(risks, key=key)


def heatmap_counts(risks: Sequence[dict], size: int = 5, residual: bool = True) -> list[list[int]]:
    """Counts per cell; grid[impact-1][likelihood-1]."""
    grid = [[0] * size for _ in range(size)]
    for r in risks:
        l = r["res_l"] if residual else r["inh_l"]
        i = r["res_i"] if residual else r["inh_i"]
        if 1 <= l <= size and 1 <= i <= size:
            grid[i - 1][l - 1] += 1
    return grid


def sensitivity_of_rating(matrix: RiskMatrix, probability: float, amount: float,
                          shift: float = 0.25, scale: float = 1.0) -> dict:
    """How does the qualitative rating change if estimates are +/- shift?

    Highlights when a risk sits near a band boundary, i.e. when its rating is
    fragile to small estimation errors.
    """
    out = {}
    for label, pf, af in [("base", 1, 1), ("p_low", 1 - shift, 1), ("p_high", 1 + shift, 1),
                          ("impact_low", 1, 1 - shift), ("impact_high", 1, 1 + shift)]:
        p = min(1.0, max(0.0, probability * pf))
        l = matrix.likelihood_from_probability(p)
        i = matrix.impact_from_amount(amount * af, scale)
        s, b = matrix.rate(l, i)
        out[label] = {"likelihood": l, "impact": i, "score": s, "band": b}
    bands = {v["band"] for v in out.values()}
    out["fragile"] = len(bands) > 1
    return out
