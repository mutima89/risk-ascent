"""Content loading and validation.

Game content is data, not code: JSON files under riskascent/content.
`load_content` reads and validates everything at start-up and raises
ContentError with a readable list of problems if anything is malformed, so
authors find mistakes before players do. See docs/SCENARIO_AUTHORING_GUIDE.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .competency import COMPETENCIES
from .mission_engine import STEP_TYPES, optimal_allocation
from .util import safe_eval

MISSION_TYPES = {"career", "side", "crisis", "capstone", "executive", "weekly"}


class ContentError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("Content validation failed:\n  " + "\n  ".join(problems))
        self.problems = problems


@dataclass
class Content:
    careers: dict
    orgs: dict[str, dict]
    departments: list[dict]
    roles: dict[str, dict]
    risk_library: dict[str, dict]
    kri_library: dict[str, dict]
    control_library: dict[str, dict]
    bia_library: dict[str, dict]
    events: dict[str, dict]
    random_events: list[dict]
    crisis_threats: list[dict]
    concepts: dict[str, dict]
    achievements: list[dict]
    rubrics: dict
    skills: dict
    interview: dict
    messages: list[dict]
    missions: dict[str, dict] = field(default_factory=dict)

    def mission_list(self) -> list[dict]:
        order = {"career": 0, "capstone": 1, "crisis": 2, "side": 3, "weekly": 4, "executive": 5}
        return sorted(self.missions.values(), key=lambda m: (m["level"], order.get(m["type"], 9), m["id"]))

    def level(self, n: int) -> dict:
        return next(l for l in self.careers["levels"] if l["level"] == n)


def _read(path: Path) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise ContentError([f"{path.name}: invalid JSON at line {exc.lineno}: {exc.msg}"]) from exc


def load_content(root: Path) -> Content:
    def by_id(items: list[dict]) -> dict[str, dict]:
        return {i["id"]: i for i in items}

    c = Content(
        careers=_read(root / "careers.json"),
        orgs=by_id(_read(root / "orgs.json")),
        departments=_read(root / "departments.json"),
        roles=by_id(_read(root / "stakeholder_roles.json")),
        risk_library=by_id(_read(root / "risk_library.json")),
        kri_library=by_id(_read(root / "kri_library.json")),
        control_library=by_id(_read(root / "control_library.json")),
        bia_library=by_id(_read(root / "bia_library.json")),
        events=by_id(_read(root / "events.json")["scheduled"]),
        random_events=_read(root / "events.json")["random"],
        crisis_threats=_read(root / "crisis_threats.json"),
        concepts=by_id(_read(root / "concepts.json")),
        achievements=_read(root / "achievements.json"),
        rubrics=_read(root / "rubrics.json"),
        skills=_read(root / "skills.json"),
        interview=_read(root / "interview.json"),
        messages=_read(root / "messages.json"),
    )
    problems: list[str] = []
    for f in sorted((root / "missions").glob("*.json")):
        data = _read(f)
        for m in data:
            if m.get("id") in c.missions:
                problems.append(f"{f.name}: duplicate mission id {m.get('id')}")
            c.missions[m.get("id", f"?{len(c.missions)}")] = m
            m["_file"] = f.name
    problems += validate(c)
    if problems:
        raise ContentError(problems)
    return c


def validate(c: Content) -> list[str]:
    p: list[str] = []
    roles = set(c.roles)
    events = set(c.events)
    for m in c.missions.values():
        p += validate_mission(m, roles, events, set(c.concepts))
    level_ids = [l["level"] for l in c.careers["levels"]]
    if level_ids != list(range(1, len(level_ids) + 1)):
        p.append("careers.json: levels must be numbered 1..n in order")
    for l in c.careers["levels"]:
        for mid in l.get("required_missions", []) + ([l["capstone"]] if l.get("capstone") else []):
            if mid not in c.missions:
                p.append(f"careers.json level {l['level']}: unknown mission {mid}")
        for comp in list(l.get("minima", {})) + list(l.get("minima_expert", {})):
            if comp not in COMPETENCIES:
                p.append(f"careers.json level {l['level']}: unknown competency {comp}")
    for path in c.careers.get("exec_paths", []):
        if path["assessment"] not in c.missions:
            p.append(f"exec path {path['id']}: unknown assessment mission {path['assessment']}")
    for org in c.orgs.values():
        for key, lib in [("risks", c.risk_library), ("kris", c.kri_library),
                         ("controls", c.control_library), ("processes", c.bia_library)]:
            for rid in org.get(key, []):
                if rid not in lib:
                    p.append(f"orgs.json {org['id']}: unknown {key} entry {rid}")
        for role in roles:
            if role not in org.get("people", {}):
                p.append(f"orgs.json {org['id']}: no person defined for role {role}")
    ach_ids = set()
    for a in c.achievements:
        if a["id"] in ach_ids:
            p.append(f"achievements.json: duplicate id {a['id']}")
        ach_ids.add(a["id"])
        cond = a.get("condition", {})
        if cond.get("type") == "mission" and cond.get("id") not in c.missions:
            p.append(f"achievement {a['id']}: unknown mission {cond.get('id')}")
    for ev in c.events.values():
        for k in ("id", "title", "text"):
            if k not in ev:
                p.append(f"events.json: scheduled event missing {k}")
    return p


def validate_mission(m: dict, roles: set[str], events: set[str], concepts: set[str]) -> list[str]:
    p: list[str] = []
    mid = m.get("id", "?")
    where = f"{m.get('_file', '?')}:{mid}"
    for k in ("id", "title", "type", "level", "objective", "briefing", "steps", "debrief", "xp"):
        if k not in m:
            p.append(f"{where}: missing '{k}'")
    if p:
        return p
    if m["type"] not in MISSION_TYPES:
        p.append(f"{where}: unknown type {m['type']}")
    if m.get("from") and m["from"] not in roles:
        p.append(f"{where}: unknown sender role {m['from']}")
    for cid in m.get("concepts", []):
        if cid not in concepts:
            p.append(f"{where}: unknown concept {cid}")
    if not m["steps"]:
        p.append(f"{where}: no steps")
    seen = set()
    for s in m["steps"]:
        sid = s.get("id")
        sw = f"{where}/{sid}"
        if not sid or sid in seen:
            p.append(f"{sw}: missing or duplicate step id")
        seen.add(sid)
        t = s.get("type")
        if t not in STEP_TYPES:
            p.append(f"{sw}: unknown step type {t}")
            continue
        if not s.get("prompt"):
            p.append(f"{sw}: missing prompt")
        for comp in (s.get("competencies") or []):
            if comp not in COMPETENCIES:
                p.append(f"{sw}: unknown competency {comp}")
        if not s.get("competencies"):
            p.append(f"{sw}: no competencies assessed")
        if s.get("to") and s["to"] not in roles:
            p.append(f"{sw}: unknown recipient role {s['to']}")
        if t == "choice":
            opts = s.get("options", [])
            if len(opts) < 2:
                p.append(f"{sw}: choice needs at least two options")
            ids = [o.get("id") for o in opts]
            if len(set(ids)) != len(ids):
                p.append(f"{sw}: duplicate option ids")
            if opts and max(o.get("quality", -1) for o in opts) < 2:
                p.append(f"{sw}: no option of at least 'reasonable' quality")
            for o in opts:
                if not 0 <= o.get("quality", -1) <= 3:
                    p.append(f"{sw}/{o.get('id')}: quality must be 0-3")
                if not o.get("feedback"):
                    p.append(f"{sw}/{o.get('id')}: missing feedback")
                for eff in [o.get("effects", {}), (o.get("outcome") or {}).get("bad_effects", {}),
                            (o.get("outcome") or {}).get("good_effects", {})]:
                    for sch in eff.get("schedule", []):
                        if sch["event"] not in events:
                            p.append(f"{sw}/{o.get('id')}: unknown scheduled event {sch['event']}")
                    for role in eff.get("trust", {}):
                        if role not in roles:
                            p.append(f"{sw}/{o.get('id')}: unknown trust role {role}")
                if o.get("outcome") and "bad" not in o["outcome"]:
                    p.append(f"{sw}/{o.get('id')}: outcome needs 'bad' text")
        elif t == "multi":
            if not any(o.get("correct") for o in s.get("options", [])):
                p.append(f"{sw}: multi needs at least one correct option")
        elif t == "numeric":
            try:
                vars_ = dict(s.get("vars", {}))
                safe_eval(s["formula"], vars_)
                for mv in s.get("money_vars", []):
                    if mv not in vars_:
                        p.append(f"{sw}: money var {mv} not in vars")
            except Exception as exc:  # noqa: BLE001
                p.append(f"{sw}: bad formula: {exc}")
        elif t == "classify":
            cats = set(s.get("categories", []))
            for it in s.get("items", []):
                if it.get("answer") not in cats:
                    p.append(f"{sw}: item answer '{it.get('answer')}' not in categories")
        elif t == "rank":
            ids = [i["id"] for i in s.get("items", [])]
            if sorted(ids) != sorted(s.get("answer", [])):
                p.append(f"{sw}: rank answer must list every item id once")
        elif t == "allocate":
            items = s.get("items", [])
            if not items or "budget" not in s:
                p.append(f"{sw}: allocate needs items and budget")
            else:
                best, _ = optimal_allocation(items, s["budget"])
                if not best:
                    p.append(f"{sw}: no item fits in the budget")
        elif t == "matrix":
            exp = s.get("expected", {})
            if not {"l", "i"} <= set(exp):
                p.append(f"{sw}: matrix needs expected l and i")
            for v in exp.values():
                if not 1 <= v <= 5:
                    p.append(f"{sw}: matrix expectation out of range")
        elif t == "write":
            if not s.get("rubric"):
                p.append(f"{sw}: write needs a rubric")
            if not s.get("model_answer"):
                p.append(f"{sw}: write needs a model answer")
    iq = m.get("info_questions")
    if iq and not any(o.get("relevant") for o in iq.get("options", [])):
        p.append(f"{where}: investigation needs at least one relevant option")
    for d in m.get("documents", []) + m.get("stretch_documents", []):
        if "id" not in d or "title" not in d:
            p.append(f"{where}: document missing id/title")
    db = m.get("debrief", {})
    for k in ("summary", "stronger_approach", "transfer"):
        if not db.get(k):
            p.append(f"{where}: debrief missing {k}")
    return p


def count_decision_points(c: Content) -> int:
    return sum(len(m["steps"]) + (1 if m.get("info_questions") else 0) for m in c.missions.values())
