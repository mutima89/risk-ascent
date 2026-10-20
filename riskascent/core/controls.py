"""Controls and assurance: design and operating effectiveness testing."""

from __future__ import annotations

from dataclasses import dataclass

# Design-effectiveness criteria. Each is a yes/no question the tester answers.
DESIGN_CRITERIA = [
    ("addresses_cause", "Addresses a specific cause of the risk (not just a symptom)"),
    ("owner", "Has a named, accountable owner"),
    ("frequency", "Operates at a defined frequency or trigger"),
    ("precision", "Is precise enough to detect or prevent material errors"),
    ("evidence", "Leaves evidence that it operated"),
    ("segregation", "Is performed independently of the activity it checks"),
]

# Typical sample sizes for operating-effectiveness tests by control frequency.
# These follow common internal-audit practice; they are guidance, not a standard.
SAMPLE_SIZES = {
    "Annual": 1, "Quarterly": 2, "Monthly": 3, "Weekly": 10,
    "Daily": 25, "Multiple times daily": 40, "Automated": 1,
}


def design_rating(answers: dict[str, bool]) -> tuple[int, list[str]]:
    """Return design effectiveness 0-4 and the list of design gaps.

    Missing the cause or the owner caps the rating at Weak (1) because a
    control nobody owns, or that does not address the cause, cannot be
    relied on regardless of its other qualities.
    """
    gaps = [label for key, label in DESIGN_CRITERIA if not answers.get(key, False)]
    met = len(DESIGN_CRITERIA) - len(gaps)
    if met == len(DESIGN_CRITERIA):
        rating = 4
    elif met >= 5:
        rating = 3
    elif met >= 3:
        rating = 2
    elif met >= 1:
        rating = 1
    else:
        rating = 0
    if not answers.get("addresses_cause") or not answers.get("owner"):
        rating = min(rating, 1)
    return rating, gaps


def required_sample(frequency: str) -> int:
    if frequency not in SAMPLE_SIZES:
        raise ValueError(f"Unknown control frequency: {frequency}")
    return SAMPLE_SIZES[frequency]


def operating_result(frequency: str, tested: int, exceptions: int) -> dict:
    """Assess operating effectiveness from a sample test.

    Zero exceptions in an adequate sample -> Effective. One exception in a
    large sample (>=25) -> Partially effective. Anything more -> Ineffective.
    An undersized sample cannot support a conclusion.
    """
    if tested < 0 or exceptions < 0 or exceptions > tested:
        raise ValueError("Invalid sample: exceptions must be between 0 and items tested")
    needed = required_sample(frequency)
    if tested < needed:
        return {"conclusion": "Insufficient evidence", "rating": None,
                "note": f"Sample of {tested} is below the {needed} expected for a {frequency.lower()} control."}
    if exceptions == 0:
        return {"conclusion": "Operating effectively", "rating": 4, "note": "No exceptions found."}
    if exceptions == 1 and tested >= 25:
        return {"conclusion": "Partially effective", "rating": 2,
                "note": "One exception in a large sample; investigate the root cause and extend testing."}
    return {"conclusion": "Not operating effectively", "rating": 1,
            "note": f"{exceptions} exception(s) in {tested} items."}


def combined_effectiveness(design: int, operating: int | None) -> int:
    """A control is only as good as the weaker of its design and operation."""
    if operating is None:
        return min(design, 2)
    return min(design, operating)


@dataclass
class Finding:
    finding_id: str
    title: str
    severity: str  # Low / Medium / High / Critical
    control_id: str
    root_cause: str
    action: str
    owner: str
    due_period: int
    status: str = "Open"

    SEVERITIES = ("Low", "Medium", "High", "Critical")

    def __post_init__(self) -> None:
        if self.severity not in self.SEVERITIES:
            raise ValueError("Unknown severity")
        if not self.title.strip():
            raise ValueError("Finding title is required")


def finding_severity(risk_score: int, operating_rating: int | None) -> str:
    if operating_rating is None:
        return "Medium"
    if risk_score >= 16 and operating_rating <= 1:
        return "Critical"
    if risk_score >= 10 and operating_rating <= 2:
        return "High"
    if operating_rating <= 2:
        return "Medium"
    return "Low"
