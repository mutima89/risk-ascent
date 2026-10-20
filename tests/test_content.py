"""Content packs load, validate and meet the minimum scope."""

from __future__ import annotations

import json
from pathlib import Path

from riskascent.core.content import count_decision_points, validate, validate_mission
from riskascent.paths import content_dir


def test_content_validates(content):
    assert validate(content) == []


def test_minimum_scope(content):
    types = [m["type"] for m in content.missions.values()]
    assert len(content.missions) >= 30
    assert count_decision_points(content) >= 100
    assert len(content.achievements) >= 50
    assert len(content.orgs) >= 3
    assert len(content.careers["levels"]) == 10
    assert len(content.careers["tracks"]) == 10
    assert types.count("executive") == 7
    assert types.count("crisis") == 12
    assert len({o["industry"] for o in content.orgs.values()}) >= 8


def test_hotel_and_saudi_packs(content):
    assert any(o["industry"] == "hospitality" for o in content.orgs.values())
    saudi = [o for o in content.orgs.values() if o.get("geography") == "saudi"]
    assert saudi and saudi[0]["currency"] == "SAR"
    assert any("saudi" in (m.get("geographies") or []) for m in content.missions.values())


def test_every_option_has_feedback(content):
    for m in content.missions.values():
        for s in m["steps"]:
            for o in s.get("options", []):
                if "quality" in o:
                    assert o.get("feedback"), f"{m['id']}/{s['id']} option without feedback"


def test_salaries_are_labelled_illustrative(content):
    text = json.dumps(content.careers).lower()
    assert "illustrative" in text


def test_validator_rejects_broken_mission(content):
    m = json.loads((content_dir() / "missions").glob("*.json").__next__().read_text(encoding="utf-8"))
    m = m[0] if isinstance(m, list) else m
    bad = dict(m, steps=[{"id": "s1", "type": "choice", "prompt": "?", "options": []}])
    assert validate_mission(bad, set(), set(), set())


def test_achievements_have_verifiable_conditions(content):
    kinds = {"mission", "missions_count", "level", "counter", "branch_tier", "all_branches", "competency",
             "stakeholder", "flag", "calibration"}
    ids = set()
    for a in content.achievements:
        assert a["id"] not in ids
        ids.add(a["id"])
        assert a["condition"]["type"] in kinds, a["id"]
