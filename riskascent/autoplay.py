"""Deterministic "expert player" used by the automated tests and the built-in self-test.

It answers every step type through the same MissionRun API the UI uses,
choosing the best answer the content defines. This proves that every
mission is completable and scores as designed.
"""

from __future__ import annotations

from .core.mission_engine import MissionRun, optimal_allocation


def best_answer(run: MissionRun, step: dict):
    t = step["type"]
    if t == "choice":
        return max(step["options"], key=lambda o: o["quality"])["id"]
    if t == "multi":
        return [i for i, o in enumerate(step["options"]) if o.get("correct")]
    if t == "numeric":
        return run.numeric_answer(step)
    if t == "classify":
        return {str(i): it["answer"] for i, it in enumerate(step["items"])}
    if t == "rank":
        return list(step["answer"])
    if t == "allocate":
        return optimal_allocation(step["items"], step["budget"])[0]
    if t == "matrix":
        return dict(step["expected"])
    if t == "write":
        words = " ".join(el["keywords"][0] for el in step["rubric"])
        filler = " because the evidence supports a clear recommendation to the owner" * 4
        text = words + filler
        n = len(text.split())
        if n > step.get("max_words", 200):
            text = " ".join(text.split()[: step.get("max_words", 200)])
        return text
    raise ValueError(t)


def worst_choice(step: dict):
    return min(step["options"], key=lambda o: o["quality"])["id"]


def play(run: MissionRun, confidence: float | None = 0.8, stop_after: int | None = None) -> MissionRun:
    """Play a run to completion (or stop after N steps, for checkpoint tests)."""
    for d in run.documents():
        run.mark_doc(d["id"])
    if run.m.get("info_questions") and run.state.get("info_result") is None:
        run.submit_investigation([i for i, o in enumerate(run.m["info_questions"]["options"]) if o.get("relevant")])
    run.set_phase("steps")
    done = 0
    while run.current_step() is not None:
        if stop_after is not None and done >= stop_after:
            return run
        step = run.current_step()
        res = run.submit(step["id"], best_answer(run, step), confidence)
        assert res.final, (run.m["id"], step["id"], res.feedback)
        run.advance()
        done += 1
    return run
