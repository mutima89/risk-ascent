"""Mission engine.

Runs a mission definition (from content JSON) step by step, scores each
step, records decisions and produces a debrief. It has no UI dependencies:
the UI and the automated tests drive it through the same API.

Scoring separates decision quality from outcome. A choice is scored on the
quality of the decision given the information available. Any stochastic
outcome (seeded and logged) affects the organisation, and the debrief
explains whether a result came from judgement or from luck.
"""

from __future__ import annotations

import itertools
import random
import re
from dataclasses import dataclass, field
from typing import Any

from .difficulty import DIFFICULTIES, Difficulty, effective_tolerance
from .util import fmt_money, render, safe_eval, stable_seed

STEP_TYPES = {"choice", "multi", "numeric", "classify", "rank", "allocate", "matrix", "write"}
QUALITY_LABELS = {3: "Strong", 2: "Reasonable", 1: "Weak", 0: "Poor"}


@dataclass
class StepResult:
    step_id: str
    score: float
    final: bool
    feedback: str
    details: list[str] = field(default_factory=list)
    competencies: dict[str, float] = field(default_factory=dict)
    effects: list[dict] = field(default_factory=list)
    outcome: str = ""            # narrative of what happened
    luck: str = ""               # judgement vs luck explanation
    quality: int | None = None
    correct_answer: str = ""
    retry_allowed: bool = False
    confidence: float | None = None
    correct: bool | None = None  # for calibration

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> "StepResult":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class MissionResult:
    mission_id: str
    score: float
    competency_perf: dict[str, float]
    ending: dict
    step_results: list[StepResult]
    effects: list[dict]
    xp: int
    debrief: dict
    luck_notes: list[str]


def _weights(comp: Any) -> dict[str, float]:
    if isinstance(comp, dict):
        return {k: float(v) for k, v in comp.items()}
    return {k: 1.0 for k in (comp or [])}


class MissionRun:
    """A single attempt at a mission. Serialisable to a checkpoint dict."""

    def __init__(self, mission: dict, ctx: dict, seed: int, difficulty: str = "standard",
                 scaffolding: str = "normal", state: dict | None = None):
        self.m = mission
        self.ctx = ctx
        self.seed = seed
        self.diff: Difficulty = DIFFICULTIES.get(difficulty, DIFFICULTIES["standard"])
        self.scaffolding = scaffolding
        self.steps: list[dict] = mission["steps"]
        self.state: dict = state or {
            "mission_id": mission["id"], "seed": seed, "phase": "briefing", "step_index": 0,
            "answers": {}, "results": {}, "attempts": {}, "docs_viewed": [], "notes": "",
            "info_answer": None, "info_result": None, "hints_used": [], "examples_used": [],
            "difficulty": difficulty, "scaffolding": scaffolding,
        }

    # ---------- navigation ----------
    @property
    def phase(self) -> str:
        return self.state["phase"]

    def set_phase(self, phase: str) -> None:
        if phase not in ("briefing", "investigation", "steps", "debrief"):
            raise ValueError(phase)
        self.state["phase"] = phase

    @property
    def index(self) -> int:
        return self.state["step_index"]

    def current_step(self) -> dict | None:
        if self.index < len(self.steps):
            return self.steps[self.index]
        return None

    def is_complete(self) -> bool:
        return all(s["id"] in self.state["results"] and self.state["results"][s["id"]]["final"]
                   for s in self.steps)

    def advance(self) -> None:
        step = self.current_step()
        if step and step["id"] in self.state["results"] and self.state["results"][step["id"]]["final"]:
            self.state["step_index"] += 1

    def mark_doc(self, doc_id: str) -> None:
        if doc_id not in self.state["docs_viewed"]:
            self.state["docs_viewed"].append(doc_id)

    def use_hint(self, step_id: str, example: bool = False) -> None:
        key = "examples_used" if example else "hints_used"
        if step_id not in self.state[key]:
            self.state[key].append(step_id)

    def documents(self) -> list[dict]:
        docs = list(self.m.get("documents", []))
        if self.scaffolding == "stretch":
            docs += self.m.get("stretch_documents", [])
        return docs

    # ---------- investigation ----------
    def submit_investigation(self, selected: list[int]) -> StepResult:
        iq = self.m.get("info_questions")
        if not iq:
            raise ValueError("Mission has no investigation questions")
        opts = iq["options"]
        score, details = _score_multi(opts, selected, "relevant")
        docs = [d for d in self.documents() if d.get("key")]
        viewed = set(self.state["docs_viewed"])
        if docs:
            coverage = sum(1 for d in docs if d["id"] in viewed) / len(docs)
            if coverage < 1:
                details.append(f"You opened {coverage * 100:.0f}% of the key documents before "
                               "deciding what was missing.")
            score = score * (0.8 + 0.2 * coverage)
        res = StepResult("investigation", round(score, 3), True,
                         _band_text(score, "Your gap analysis"), details,
                         {"evidence": score, "analysis": score})
        self.state["info_answer"] = selected
        self.state["info_result"] = res.to_dict()
        return res

    # ---------- steps ----------
    def tolerance(self, step: dict) -> float:
        return effective_tolerance(step.get("tolerance_pct", 5.0), self.diff, self.scaffolding)

    def numeric_answer(self, step: dict) -> float:
        variables = dict(step.get("vars", {}))
        scale = self.ctx.get("money_scale", 1.0)
        for name in step.get("money_vars", []):
            variables[name] = variables[name] * scale
        value = safe_eval(step["formula"], variables)
        if step.get("unit") == "money" and not step.get("money_vars"):
            # Constants in money formulas are reference amounts: scale the result.
            value *= scale
        return value

    def submit(self, step_id: str, answer: Any, confidence: float | None = None) -> StepResult:
        step = next((s for s in self.steps if s["id"] == step_id), None)
        if step is None:
            raise KeyError(step_id)
        prev = self.state["results"].get(step_id)
        if prev and prev["final"]:
            return StepResult.from_dict(prev)
        attempts = self.state["attempts"].get(step_id, 0) + 1
        self.state["attempts"][step_id] = attempts
        t = step["type"]
        fn = getattr(self, f"_score_{t}")
        res: StepResult = fn(step, answer, attempts)
        res.competencies = {k: res.score * 1.0 for k in _weights(step.get("competencies"))}
        if step_id in self.state["examples_used"] and res.score > 0.5:
            res.details.append("Worked example used: credit is kept, but the competency "
                               "evidence is weighted lower than independent work.")
        if confidence is not None:
            res.confidence = confidence
            if res.correct is None:
                res.correct = res.score >= 0.67
        self.state["answers"][step_id] = answer
        self.state["results"][step_id] = res.to_dict()
        return res

    def _score_choice(self, step: dict, answer: str, attempts: int) -> StepResult:
        opt = next((o for o in step["options"] if o["id"] == answer), None)
        if opt is None:
            raise ValueError("Unknown option")
        q = int(opt["quality"])
        score = q / 3
        best = max(step["options"], key=lambda o: o["quality"])
        res = StepResult(step["id"], round(score, 3), True, render(opt.get("feedback", ""), self.ctx),
                         quality=q)
        res.correct = q >= 2
        effects = []
        if opt.get("effects"):
            effects.append(opt["effects"])
        outcome = opt.get("outcome")
        if outcome:
            rng = random.Random(stable_seed(self.seed, step["id"], opt["id"]))
            p_bad = float(outcome.get("p_bad", 0)) * self.diff.event_severity
            p_bad = min(0.95, p_bad)
            roll = rng.random()
            bad = roll < p_bad
            res.outcome = render(outcome["bad"] if bad else outcome.get("good", ""), self.ctx)
            eff = outcome.get("bad_effects" if bad else "good_effects")
            if eff:
                effects.append(eff)
            res.luck = _luck_text(q, bad, p_bad)
            res.details.append(f"Outcome roll {roll:.3f} vs adverse probability {p_bad:.2f} "
                               f"(seed {self.seed}).")
        res.effects = effects
        if q < 3:
            res.correct_answer = render(best["text"], self.ctx)
            if best.get("feedback"):
                res.details.append("Stronger option: " + render(best["feedback"], self.ctx))
        if step.get("to"):
            res.details.append(f"Message to {render('{shr:' + step['to'] + '}', self.ctx)}.")
        return res

    def _score_multi(self, step: dict, answer: list[int], attempts: int) -> StepResult:
        score, details = _score_multi(step["options"], answer, "correct")
        for i, o in enumerate(step["options"]):
            if o.get("why") and (i in answer) != bool(o.get("correct")):
                details.append(render(o["why"], self.ctx))
        res = StepResult(step["id"], round(score, 3), True, _band_text(score, "Your selection"), details)
        res.correct_answer = "; ".join(render(o["text"], self.ctx) for o in step["options"] if o.get("correct"))
        res.correct = score >= 0.67
        return res

    def _score_numeric(self, step: dict, answer: float, attempts: int) -> StepResult:
        try:
            value = float(answer)
        except (TypeError, ValueError):
            raise ValueError("Please enter a number")
        target = self.numeric_answer(step)
        tol = self.tolerance(step) / 100
        err = abs(value - target) / abs(target) if target else abs(value)
        unit = step.get("unit", "number")
        shown = self._fmt(target, unit)
        allowed_attempts = 1 + self.diff.retries
        solution = render(step.get("solution", ""), self.ctx)
        if err <= tol:
            credit = self.diff.retry_credit ** (attempts - 1)
            res = StepResult(step["id"], round(credit, 3), True,
                             "Correct." + (" (Credit reduced for retries.)" if attempts > 1 else ""),
                             [solution] if solution else [])
            res.correct = True
        elif err <= tol * 3 and attempts >= allowed_attempts:
            res = StepResult(step["id"], round(0.4 * self.diff.retry_credit ** (attempts - 1), 3), True,
                             f"Close, but outside tolerance. The answer is {shown}.", [solution])
            res.correct = False
        elif attempts < allowed_attempts:
            direction = "high" if value > target else "low"
            res = StepResult(step["id"], 0.0, False,
                             f"Not quite: your answer looks too {direction}. Check your units and "
                             f"formula, then try again ({allowed_attempts - attempts} retry left).",
                             retry_allowed=True)
            return res
        else:
            res = StepResult(step["id"], 0.0, True, f"Incorrect. The answer is {shown}.", [solution])
            res.correct = False
        res.correct_answer = shown
        return res

    def _score_classify(self, step: dict, answer: dict[str, str], attempts: int) -> StepResult:
        items = step["items"]
        right = 0
        details = []
        for i, it in enumerate(items):
            given = answer.get(str(i))
            if given == it["answer"]:
                right += 1
            else:
                details.append(f"'{render(it['text'], self.ctx)}' is {it['answer']}"
                               + (f": {render(it['why'], self.ctx)}" if it.get("why") else "."))
        score = right / len(items)
        res = StepResult(step["id"], round(score, 3), True,
                         f"{right} of {len(items)} classified correctly.", details)
        res.correct = score >= 0.67
        return res

    def _score_rank(self, step: dict, answer: list[str], attempts: int) -> StepResult:
        truth = step["answer"]
        if sorted(answer) != sorted(truth):
            raise ValueError("Ranking must include every item exactly once")
        n = len(truth)
        pos = {k: i for i, k in enumerate(truth)}
        footrule = sum(abs(i - pos[k]) for i, k in enumerate(answer))
        worst = (n * n) // 2
        score = 1 - footrule / worst if worst else 1.0
        names = {it["id"]: render(it["text"], self.ctx) for it in step["items"]}
        res = StepResult(step["id"], round(score, 3), True,
                         "Exact match." if footrule == 0 else f"Ranking agreement {score * 100:.0f}%.",
                         [render(step.get("why", ""), self.ctx)] if step.get("why") else [])
        res.correct_answer = " > ".join(names[k] for k in truth)
        res.correct = score >= 0.67
        return res

    def _score_allocate(self, step: dict, answer: list[str], attempts: int) -> StepResult:
        items = {it["id"]: it for it in step["items"]}
        scale = self.ctx.get("money_scale", 1.0)
        budget = step["budget"]
        unit = step.get("unit", "money")

        def show(v: float) -> str:
            return self._fmt(v * scale, "money") if unit == "money" else f"{v:g} {unit}"

        cost = sum(items[i]["cost"] for i in answer)
        if cost > budget + 1e-9:
            raise ValueError(f"Selection costs {show(cost)}, over the {show(budget)} budget")
        best_set, best_val = optimal_allocation(step["items"], budget)
        val = sum(items[i]["value"] for i in answer)
        score = val / best_val if best_val else 1.0
        details = [f"Your package delivers {val:g} risk-reduction points for "
                   f"{show(cost)}. The best achievable within budget is {best_val:g}."]
        for i in answer:
            if items[i].get("note"):
                details.append(f"{render(items[i]['text'], self.ctx)}: {render(items[i]['note'], self.ctx)}")
        res = StepResult(step["id"], round(score, 3), True,
                         _band_text(score, "Your allocation"), details)
        res.correct_answer = ", ".join(render(items[i]["text"], self.ctx) for i in best_set)
        res.correct = score >= 0.85
        eff = step.get("effects_per_item", {})
        res.effects = [eff[i] for i in answer if i in eff]
        return res

    def _score_matrix(self, step: dict, answer: dict, attempts: int) -> StepResult:
        exp = step["expected"]
        axis = {0: 1.0, 1: 0.6, 2: 0.2}
        parts = []
        details = []
        for key, label in [("l", "inherent likelihood"), ("i", "inherent impact"),
                           ("rl", "residual likelihood"), ("ri", "residual impact")]:
            if key in exp:
                d = abs(int(answer.get(key, 0)) - exp[key])
                parts.append(axis.get(d, 0.0))
                if d:
                    details.append(f"Expected {label} {exp[key]}; you chose {answer.get(key)}.")
        if "rl" in answer and "l" in answer and (answer["rl"] > answer["l"] or answer["ri"] > answer["i"]):
            details.append("Residual cannot be higher than inherent.")
            parts.append(0.0)
        score = sum(parts) / len(parts)
        if step.get("why"):
            details.append(render(step["why"], self.ctx))
        res = StepResult(step["id"], round(score, 3), True, _band_text(score, "Your rating"), details)
        res.correct_answer = ", ".join(f"{k.upper()}={v}" for k, v in exp.items())
        res.correct = score >= 0.67
        return res

    def _score_write(self, step: dict, answer: str, attempts: int) -> StepResult:
        text = (answer or "").lower()
        words = len(re.findall(r"\w+", text))
        covered, missing = [], []
        for el in step["rubric"]:
            if any(k.lower() in text for k in el["keywords"]):
                covered.append(el["element"])
            else:
                missing.append(el)
        score = len(covered) / len(step["rubric"])
        details = []
        min_words = step.get("min_words", 20)
        max_words = step.get("max_words", 200)
        if words < min_words:
            score *= 0.7
            details.append(f"Too brief ({words} words). Aim for at least {min_words}.")
        elif words > max_words:
            score *= 0.85
            details.append(f"Too long ({words} words). Executives need it in under {max_words}.")
        for el in missing:
            details.append(f"Missing: {el['element']}. {el.get('tip', '')}")
        if covered:
            details.append("Covered: " + ", ".join(covered) + ".")
        details.append("Note: written answers are checked locally for required elements using "
                       "keyword matching. Compare yourself against the model answer.")
        res = StepResult(step["id"], round(score, 3), True, _band_text(score, "Your write-up"), details)
        res.correct_answer = render(step.get("model_answer", ""), self.ctx)
        res.correct = score >= 0.67
        return res

    def _fmt(self, v: float, unit: str) -> str:
        if unit == "money":
            return fmt_money(v, self.ctx.get("currency", "USD"), compact=False)
        if unit == "percent":
            return f"{v:.1f}%"
        if unit == "ratio":
            return f"{v:.2f}"
        return f"{v:,.2f}".rstrip("0").rstrip(".")

    # ---------- completion ----------
    def finish(self) -> MissionResult:
        if not self.is_complete():
            raise RuntimeError("Mission has unanswered steps")
        results = [StepResult.from_dict(self.state["results"][s["id"]]) for s in self.steps]
        total_w = 0.0
        acc = 0.0
        comp_sum: dict[str, float] = {}
        comp_w: dict[str, float] = {}
        for s, r in zip(self.steps, results):
            w = float(s.get("weight", 1.0))
            total_w += w
            acc += w * r.score
            ex_factor = 0.7 if s["id"] in self.state["examples_used"] else 1.0
            for k, cw in _weights(s.get("competencies")).items():
                comp_sum[k] = comp_sum.get(k, 0) + r.score * cw * w * ex_factor
                comp_w[k] = comp_w.get(k, 0) + cw * w
        if self.state.get("info_result"):
            ir = StepResult.from_dict(self.state["info_result"])
            total_w += 0.5
            acc += 0.5 * ir.score
            for k in ("evidence", "analysis"):
                comp_sum[k] = comp_sum.get(k, 0) + ir.score * 0.5
                comp_w[k] = comp_w.get(k, 0) + 0.5
        score = acc / total_w if total_w else 0.0
        comp = {k: comp_sum[k] / comp_w[k] for k in comp_sum if comp_w[k] > 0}
        flags = set(self.ctx.get("flags", []))
        effects = [e for r in results for e in r.effects]
        oc = self.m.get("on_complete", {})
        if oc.get("effects"):
            effects.append(oc["effects"])
        for band in sorted(oc.get("effects_by_score", []), key=lambda b: -b["min"]):
            if score >= band["min"]:
                effects.append(band["effects"])
                break
        for e in effects:
            flags.update(e.get("flags", []))
        ending = select_ending(self.m.get("endings", []), score, flags)
        xp = int(round(self.m.get("xp", 100) * score)) if score >= 0.4 else int(self.m.get("xp", 100) * 0.1)
        luck = [r.luck for r in results if r.luck]
        db = self.m.get("debrief", {})
        debrief = {
            "summary": render(db.get("summary", ""), self.ctx),
            "key_points": [render(p, self.ctx) for p in db.get("key_points", [])],
            "stronger_approach": render(db.get("stronger_approach", ""), self.ctx),
            "transfer": render(db.get("transfer", ""), self.ctx),
            "ending": render(ending.get("text", ""), self.ctx),
            "ending_title": ending.get("title", ""),
        }
        return MissionResult(self.m["id"], round(score, 4), comp, ending, results, effects, xp,
                             debrief, luck)


def select_ending(endings: list[dict], score: float, flags: set[str]) -> dict:
    for e in endings:
        if score < e.get("min_score", 0):
            continue
        if e.get("flags_all") and not set(e["flags_all"]) <= flags:
            continue
        if e.get("flags_any") and not (set(e["flags_any"]) & flags):
            continue
        if e.get("flags_none") and set(e["flags_none"]) & flags:
            continue
        return e
    return {"id": "default", "title": "Assignment closed", "text": ""}


def optimal_allocation(items: list[dict], budget: float) -> tuple[list[str], float]:
    """Exact 0/1 knapsack by enumeration (content keeps item counts small)."""
    if len(items) > 16:
        raise ValueError("Too many items for exact allocation")
    best: tuple[list[str], float, float] = ([], 0.0, 0.0)
    for r in range(len(items) + 1):
        for combo in itertools.combinations(items, r):
            c = sum(i["cost"] for i in combo)
            if c > budget:
                continue
            v = sum(i["value"] for i in combo)
            if v > best[1] or (v == best[1] and c < best[2]):
                best = ([i["id"] for i in combo], v, c)
    return best[0], best[1]


def _score_multi(options: list[dict], selected: list[int], key: str) -> tuple[float, list[str]]:
    sel = set(selected)
    correct = {i for i, o in enumerate(options) if o.get(key)}
    tp = len(sel & correct)
    fp = len(sel - correct)
    fn = len(correct - sel)
    score = max(0.0, (tp - 0.5 * fp) / (tp + fn)) if (tp + fn) else 1.0
    details = []
    if fn:
        details.append(f"You missed {fn} relevant item(s).")
    if fp:
        details.append(f"{fp} selection(s) were not relevant and would waste effort.")
    return score, details


def _band_text(score: float, what: str) -> str:
    if score >= 0.9:
        return f"{what} is excellent."
    if score >= 0.7:
        return f"{what} is solid, with minor gaps."
    if score >= 0.4:
        return f"{what} is partly right; review the points below."
    return f"{what} needs significant rework."


def _luck_text(quality: int, bad: bool, p_bad: float) -> str:
    good_decision = quality >= 2
    if good_decision and bad:
        return (f"Sound decision, unfavourable outcome. The adverse result had about a "
                f"{p_bad * 100:.0f}% chance. This was bad luck, not poor judgement: you would "
                "make the same call again with the same information.")
    if good_decision and not bad:
        return "Sound decision, favourable outcome. Judgement and results aligned."
    if not good_decision and not bad:
        return (f"Weak decision, favourable outcome. You avoided a roughly {p_bad * 100:.0f}% "
                "adverse chance by luck. Do not mistake this for evidence the approach works.")
    return "Weak decision, unfavourable outcome. The risk you accepted materialised."


def mission_available(m: dict, level: int, flags: set[str], best_scores: dict[str, float],
                      industry: str, track: str, geography: str = "") -> tuple[bool, str]:
    req = m.get("requires", {})
    if level < m.get("level", 1):
        return False, f"Requires career level {m['level']}"
    if m.get("max_level") and level > m["max_level"] and m["id"] not in best_scores:
        pass  # still available for practice
    for mid in req.get("missions", []):
        if mid not in best_scores:
            return False, f"Complete {mid} first"
    if req.get("flags_all") and not set(req["flags_all"]) <= flags:
        return False, "Unlocked by earlier decisions"
    if req.get("flags_none") and set(req["flags_none"]) & flags:
        return False, "Not available after earlier decisions"
    if m.get("industries") and industry not in m["industries"]:
        return False, "Specific to another industry"
    if m.get("geographies") and geography not in m["geographies"]:
        return False, "Specific to another region"
    if req.get("min_capstone") and best_scores.get(req["min_capstone"], 0) < 0.7:
        return False, "Requires passing the CRO board simulation"
    return True, ""
