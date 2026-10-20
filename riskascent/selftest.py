"""Built-in smoke test (RiskAscent.exe --self-test).

Drives the real user interface in a throwaway data folder: creates a career,
opens every screen, plays a mission through the UI widgets, closes and
reopens the save to prove persistence, resumes a half-finished mission,
generates and exports reports and runs the financial models. Exit code 0
means every check passed. Intended for verifying a packaged build.
"""

from __future__ import annotations

import json
import time
import traceback
from pathlib import Path

from .autoplay import best_answer


class _Recorder:
    def __init__(self):
        self.messages: list[str] = []

    def info(self, parent, title, text):
        self.messages.append(f"info: {title}: {text}")

    def error(self, parent, title, text):
        self.messages.append(f"error: {title}: {text}")

    def confirm(self, parent, title, text):
        return True

    def typed_confirm(self, parent, title, text, word):
        return True

    def save_file(self, parent, title, default, filt):
        return default

    def open_file(self, parent, title, start, filt):
        return ""

    def text(self, parent, title, label, default=""):
        return default


def run_self_test(app, win, report_path: str | None = None) -> int:
    from .game import Game
    from .paths import user_data_dir
    from .ui import widgets

    rec = _Recorder()
    for name in ("info", "error", "confirm", "typed_confirm", "save_file", "open_file", "text"):
        setattr(widgets.DIALOGS, name, getattr(rec, name))
    win.settings.reduced_motion = True
    win.resize(1360, 860)
    win.show()
    out_dir = user_data_dir() / "selftest"
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []

    def pump(n: int = 3):
        for _ in range(n):
            app.processEvents()

    def check(name: str, fn):
        t0 = time.perf_counter()
        try:
            detail = fn() or ""
            results.append({"check": name, "ok": True, "detail": str(detail), "secs": round(time.perf_counter() - t0, 2)})
        except Exception as exc:  # noqa: BLE001 - report every failure
            results.append({"check": name, "ok": False, "detail": f"{exc}\n{traceback.format_exc()}",
                            "secs": round(time.perf_counter() - t0, 2)})

    c = win.content

    def content():
        from .core.content import count_decision_points
        n, dp = len(c.missions), count_decision_points(c)
        assert n >= 30 and dp >= 100 and len(c.achievements) >= 50
        return f"{n} missions, {dp} decision points, {len(c.achievements)} achievements, {len(c.orgs)} organisations"

    def new_career():
        win.screens["startup"].refresh()
        pump()
        g = Game.new_career(c, win.saves, 1, "Self Test", "meridian", "erm", "standard", seed=1234)
        win.start_game(g, first=True)
        pump()
        assert win.game is not None and win.stack.currentWidget() is win.screens["dashboard"]
        return f"slot file {win.saves.slot_path(1)}"

    def all_screens():
        keys = [k for k in win.screens if k not in ("startup", "mission")]
        for k in keys:
            win.go(k)
            pump()
            win.grab().save(str(out_dir / f"screen_{k}.png"))
        win.go("mission", mission_id="M01")
        pump()
        win.grab().save(str(out_dir / "screen_mission_briefing.png"))
        return f"{len(keys) + 2} screens opened (including title and mission briefing)"

    def play_mission(mid: str, stop_after: int | None = None):
        s = win.screens["mission"]
        win.go("mission", mission_id=mid)
        pump()
        if s.run is None or s.run.phase == "briefing":
            s.accept()
            pump()
        if s.run.phase == "investigation":
            for i in range(s.doc_list.count()):
                s.doc_list.setCurrentRow(i)
                pump(1)
            if s.mission.get("info_questions") and not s.run.state.get("info_result"):
                for i, o in enumerate(s.mission["info_questions"]["options"]):
                    s.iq_boxes[i].setChecked(bool(o.get("relevant")))
                s.submit_info()
                pump(1)
            win.grab().save(str(out_dir / f"mission_{mid}_investigation.png"))
            s.to_steps()
            pump(1)
        done = 0
        while s.completion is None:
            if stop_after is not None and done >= stop_after:
                return s
            step = s.run.current_step()
            s.step_widget.set_answer(best_answer(s.run, step))
            s.submit()
            pump(1)
            if done == 0:
                win.grab().save(str(out_dir / f"mission_{mid}_feedback.png"))
            s.next_step()
            pump(3)
            done += 1
        win.grab().save(str(out_dir / f"mission_{mid}_debrief.png"))
        return s

    def mission_ui():
        s = play_mission("M01")
        score = s.completion["result"].score
        assert score >= 0.95, f"expected a near-perfect score, got {score}"
        return f"M01 completed through the UI with score {score:.2f}, XP {s.completion['xp']}"

    def persistence():
        before = win.game.best_scores()
        xp = win.game.profile["xp"]
        win.close_game()
        pump()
        assert win.game is None
        win.open_slot(1)
        pump()
        after = win.game.best_scores()
        assert after == before and win.game.profile["xp"] == xp, (before, after)
        assert win.saves.list_backups(1), "no backups were written"
        return f"best scores {after}, XP {xp} preserved across close/reopen; {len(win.saves.list_backups(1))} backups"

    def checkpoint():
        play_mission("M02", stop_after=2)
        s = win.screens["mission"]
        idx = s.run.index
        win.close_game()
        pump()
        win.open_slot(1)
        pump()
        row = win.game.db.one("SELECT mission_id FROM mission_runs WHERE status='active'")
        assert row and row["mission_id"] == "M02", "active mission not restored"
        win.go("mission")
        pump()
        assert s.run.index == idx, (s.run.index, idx)
        play_mission("M02")
        return f"M02 resumed at decision {idx + 1} after restart and completed ({s.completion['result'].score:.2f})"

    def reports():
        r = win.screens["reports"]
        win.go("reports", kind="exec_dashboard")
        pump()
        r.generate()
        pump()
        assert r.html and "Executive risk dashboard" in r.html
        pdf = out_dir / "exec_dashboard.pdf"
        from .ui.screens.reports import write_pdf
        write_pdf(r.html, pdf)
        assert pdf.stat().st_size > 2000, "PDF too small"
        win.grab().save(str(out_dir / "reports_preview.png"))
        csv_path = out_dir / "register.csv"
        win.game.export_register_csv(csv_path)
        assert csv_path.stat().st_size > 200
        return f"HTML report generated, PDF {pdf.stat().st_size} bytes, register CSV written"

    def finance():
        f = win.screens["finance"]
        win.go("finance")
        pump()
        f.run_mc()
        f.run_cba()
        f.run_tornado()
        f.run_stress()
        pump()
        assert f.last_mc.n == f.mc_n.value()
        win.grab().save(str(out_dir / "finance_lab.png"))
        return f"Monte Carlo mean {f.last_mc.mean:,.0f}, P99 {f.last_mc.p99:,.0f}; CBA NPV {f.last_cba['npv']:,.0f}"

    def tools():
        g = win.game
        r = dict(g.list_risks()[0])
        r["title"] = r["title"] + " (reviewed)"
        g.save_risk(r)
        k = g.list_kris()[0]
        g.escalate_kri(k.kri_id, "escalate")
        ex = g.start_crisis_exercise()
        while not ex.finished:
            worst = max(ex.active(), key=lambda t: t.severity)
            plan = [("contain", worst.tid)] if worst.investigated else [("investigate", worst.tid), ("contain", worst.tid)]
            ex.play_turn(plan)
        sc = g.finish_crisis_exercise(ex)
        msgs = [m for m in g.list_messages() if m["options"] and m["status"] != "replied"]
        if msgs:
            g.reply_message(msgs[0]["id"], 0)
        g.advance_period("selftest")
        return f"register edit, KRI escalation, crisis exercise ({sc['score']:.2f}), month advanced to {g.period()}"

    def settings_toggle():
        s = win.settings
        s.theme, s.text_scale = "light", 1.3
        win.apply_settings()
        win.go("dashboard")
        pump()
        win.grab().save(str(out_dir / "dashboard_light_large.png"))
        s.theme, s.text_scale, s.focus_mode = "dark", 1.0, True
        win.apply_settings()
        pump()
        win.grab().save(str(out_dir / "dashboard_focus.png"))
        s.focus_mode = False
        win.apply_settings()
        return "light theme, 130% text and focus mode applied"

    for name, fn in [("Content loads and validates", content), ("Create a new career", new_career),
                     ("Open every screen", all_screens), ("Play a mission through the UI", mission_ui),
                     ("Progress survives close and reopen", persistence),
                     ("Half-finished mission resumes after restart", checkpoint),
                     ("Reports generate and export", reports), ("Financial models run", finance),
                     ("Workspace tools", tools), ("Accessibility settings apply", settings_toggle)]:
        check(name, fn)
        pump()

    ok = all(r["ok"] for r in results)
    lines = [f"Risk Ascent self-test: {'PASS' if ok else 'FAIL'}", f"Data folder: {user_data_dir()}", ""]
    for r in results:
        lines.append(f"[{'PASS' if r['ok'] else 'FAIL'}] {r['check']} ({r['secs']}s): {r['detail']}")
    errors = [m for m in rec.messages if m.startswith("error")]
    if errors:
        lines.append("")
        lines.append("Error dialogs shown during the run:")
        lines.extend(errors)
    text = "\n".join(lines)
    print(text)
    target = Path(report_path) if report_path else out_dir / "selftest_report.txt"
    target.write_text(text, encoding="utf-8")
    (out_dir / "selftest_report.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    try:
        if win.game:
            win.close_game()
    except Exception:
        pass
    return 0 if ok and not errors else 1
