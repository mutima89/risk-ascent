"""Gameplay through the engine: missions persist across restarts, a half-done
mission resumes, outcomes are seeded, and a full career reaches CRO."""

from __future__ import annotations

from riskascent.autoplay import best_answer, play, worst_choice
from riskascent.core.career import eligible
from riskascent.game import Game
from riskascent.persistence.db import open_database

from conftest import play_mission


def reopen(g: Game) -> Game:
    c, saves, slot = g.c, g.saves, g.slot
    g.close()
    return Game(c, open_database(saves.slot_path(slot)), saves, slot)


def test_mission_restart_state_preserved(game):
    out = play_mission(game, "M01")
    assert out["result"].score > 0.9
    xp, best, period = game.profile["xp"], game.best_scores(), game.period()
    risks = [dict(r) for r in game.list_risks()]
    g = reopen(game)
    assert g.profile["xp"] == xp and g.best_scores() == best and g.period() == period
    assert [dict(r) for r in g.list_risks()] == risks
    assert g.earned_achievements(), "first-mission achievement should persist"
    g.close()


def test_half_finished_mission_resumes(game):
    rid, run = game.start_or_resume("M02")
    play(run, 0.7, stop_after=2)
    game.save_checkpoint(rid, run)
    answers = dict(run.state.get("answers", {}))
    g = reopen(game)
    rid2, run2 = g.start_or_resume("M02")
    assert rid2 == rid and run2.index == 2
    assert run2.state.get("answers", {}) == answers
    play(run2)
    out = g.complete_mission(rid2, run2)
    assert out["result"].score > 0.9
    g.close()


def test_poor_choices_score_lower_and_luck_is_separate(content, saves):
    g = Game.new_career(content, saves, 3, "Weak", "meridian", "erm", seed=5)
    rid, run = g.start_or_resume("M01")
    for d in run.documents():
        run.mark_doc(d["id"])
    run.set_phase("steps")
    while not run.is_complete():
        step = run.current_step()
        ans = worst_choice(step) if step["type"] == "choice" else best_answer(run, step)
        run.submit(step["id"], ans, 0.9)
        run.advance()
    out = g.complete_mission(rid, run)
    assert out["result"].score < 0.9
    g.close()


def test_same_seed_same_world(content, saves):
    def world(slot):
        g = Game.new_career(content, saves, slot, "Seed", "alwaha", "erm", seed=777)
        play_mission(g, "M01")
        g.advance_period("test")
        snap = (g.metrics(), [e["title"] for e in g.events(50)])
        g.close()
        return snap
    assert world(4) == world(5)


def test_saudi_org_uses_sar(content, saves):
    g = Game.new_career(content, saves, 2, "Noura", "alwaha", "erm", seed=3)
    assert g.money(1_000_000).startswith("SAR")
    assert any("saudi" in (m["mission"].get("geographies") or ["saudi"]) for m in g.mission_status())
    g.close()


def test_full_campaign_to_cro(content, saves):
    """Plays every required mission and promotion from level 1 to CRO, then the
    board simulation and the executive paths. Takes a few seconds."""
    g = Game.new_career(content, saves, 1, "Campaign", "meridian", "erm", seed=42)
    promotions = 0
    for _ in range(200):
        status = {s["mission"]["id"]: s for s in g.mission_status()}
        lvl = g.level_def()
        for mid in lvl.required_missions + ([lvl.capstone] if lvl.capstone else []):
            if mid not in g.best_scores():
                assert status[mid]["available"], (mid, status[mid]["reason"])
                play_mission(g, mid)
        if g.next_level_def() is None:
            break
        if not eligible(g.promotion_checks()):
            extra = [s for s in g.mission_status() if s["available"] and s["best"] is None
                     and s["mission"]["type"] != "executive"]
            assert extra, [c.detail for c in g.promotion_checks() if not c.passed]
            play_mission(g, extra[0]["mission"]["id"])
            continue
        qs = g.interview_questions()
        ans = [(q, max(range(len(q["options"])), key=lambda i: q["options"][i]["quality"])) for q in qs]
        r = g.promote(ans, 0.6)
        assert r["promoted"], r["feedback"]
        promotions += 1
    assert g.level == 10 and promotions == 9
    assert g.cro_passed() and g.exec_unlocked()
    for ep in g.exec_paths():
        play_mission(g, ep["assessment"])
    assert all(ep["completed"] for ep in g.exec_paths())
    assert len(g.earned_achievements()) >= 40
    g2 = g.new_game_plus("alwaha", "expert")
    assert g2.level == 1 and g2.profile["ngplus"] >= 1
    g2.close()
