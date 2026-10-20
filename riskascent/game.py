"""Game service layer.

`Game` owns one career (one save slot) and is the only object the UI talks
to. It coordinates the content, the engines in riskascent.core and the
SQLite save. Every state-changing method runs inside a database transaction.
"""

from __future__ import annotations

import csv
import json
import random
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .core import achievements as ach
from . import __version__
from .core.bcm import Process, criticality, recovery_order, validate_bia
from .core.career import CompContext, Level, eligible, negotiate, promotion_checks, salary_range
from .core.competency import (BRANCHES, COMPETENCIES, CompetencyState, branch_score, branch_tier,
                              new_states, performance_review)
from .core.content import Content
from .core.controls import combined_effectiveness
from .core.crisis import CrisisExercise, build_exercise
from .core.difficulty import DIFFICULTIES, scaffolding_level
from .core.finance import expected_loss
from .core.kri import KRI
from .core.learning import Calibration, ReviewCard, due_cards, schedule
from .core.mission_engine import MissionResult, MissionRun, mission_available
from .core.org_sim import World, apply_effects, tick
from .core.risk_engine import RISK_CATEGORIES, TREATMENTS, Appetite, RiskMatrix
from .core.util import fmt_money, render, stable_seed
from .persistence.db import Database
from .persistence.saves import SaveManager

PERIOD_ADVANCING = {"career", "capstone", "crisis", "executive"}
RISK_FIELDS = ["risk_id", "title", "cause", "event", "consequence", "category", "owner", "inh_l", "inh_i",
               "controls", "control_eff", "res_l", "res_i", "treatment", "action_owner", "target_date",
               "status", "notes", "source", "lib_id", "created_period", "updated_period"]
RISK_STATUSES = ["Open", "Treatment in progress", "Monitoring", "Escalated", "Closed"]


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Game:
    def __init__(self, content: Content, db: Database, saves: SaveManager, slot: int):
        self.c = content
        self.db = db
        self.saves = saves
        self.slot = slot
        self._profile: dict | None = None

    # ------------------------------------------------------------------ setup
    @classmethod
    def new_career(cls, content: Content, saves: SaveManager, slot: int, name: str, org_id: str,
                   track: str, difficulty: str = "standard", avatar: str = "A", seed: int | None = None,
                   ngplus: int = 0, carry: dict | None = None) -> "Game":
        name = (name or "").strip()
        if not 1 <= len(name) <= 40:
            raise ValueError("Name must be 1-40 characters")
        if org_id not in content.orgs:
            raise ValueError("Unknown organisation")
        if track not in {t["id"] for t in content.careers["tracks"]}:
            raise ValueError("Unknown career track")
        if difficulty not in DIFFICULTIES:
            raise ValueError("Unknown difficulty")
        path = saves.slot_path(slot)
        for f in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
            f.unlink(missing_ok=True)
        from .persistence.db import open_database
        db = open_database(path)
        g = cls(content, db, saves, slot)
        seed = seed if seed is not None else random.SystemRandom().randrange(1, 2**31)
        org = content.orgs[org_id]
        lvl1 = content.level(1)
        with db.tx():
            db.ex("INSERT INTO profile(id, name, avatar, track, industry, org_id, geography, career_path, level, xp,"
                  " salary, seed, difficulty, ngplus, created_at, updated_at) VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (name, avatar, track, org["industry"], org_id, org["geography"], "management", 1, 0, 0.0,
                   seed, difficulty, ngplus, now(), now()))
            g._profile = None
            sal = g.salary_range(Level.from_dict(lvl1))
            db.ex("UPDATE profile SET salary=?", (sal["mid"],))
            g._profile = None
            g._init_org(org, difficulty)
            states = new_states()
            if carry and carry.get("competencies"):
                for k, v in carry["competencies"].items():
                    if k in states:
                        states[k].score = max(states[k].score, v["score"] * 0.8)
                        states[k].evidence = v["evidence"]
            g._save_competencies(states)
            for cid in content.concepts:
                db.ex("INSERT INTO review_cards(concept_id, box, due, reviews, lapses, last_result) VALUES(?,?,?,?,?,?)",
                      (cid, 0, "", 0, 0, ""))
            if carry:
                for a in carry.get("achievements", []):
                    db.ex("INSERT OR IGNORE INTO achievements(id, earned_at, period) VALUES(?,?,?)", (a, now(), 0))
            db.meta_set("created_version", __version__)
            db.meta_set("seed", seed)
            db.ex("INSERT INTO career_history(period, event, detail, level, title, salary, created_at) VALUES(?,?,?,?,?,?,?)",
                  (0, "Joined", f"Joined {org['name']} as {lvl1['title']}", 1, lvl1["title"], sal["mid"], now()))
            mentor = g.person("mentor")
            g._add_message("mentor", f"Welcome to {org['name']}",
                           render(content.careers["welcome"], g.ctx()) + f"\n\n{mentor['name']}", [])
        g.backup("new-career")
        return g

    def _init_org(self, org: dict, difficulty: str) -> None:
        d = DIFFICULTIES[difficulty]
        metrics = {k: (v * org["money_scale"] if k in ("revenue", "operating_costs", "cash") else v)
                   for k, v in org["start"].items()}
        trust = {r: float(org["people"][r].get("trust", 50)) for r in self.c.roles}
        matrix = RiskMatrix()
        appetite = Appetite.from_dict(org.get("appetite", {}))
        budget = org["risk_budget"] * org["money_scale"] * d.budget_mult
        self.db.ex("INSERT INTO org_state(id, period, metrics_json, trust_json, budget, scheduled_json, matrix_json,"
                   " appetite_json) VALUES(1,0,?,?,?,?,?,?)",
                   (json.dumps(metrics), json.dumps(trust), budget, "[]", json.dumps(matrix.to_dict()),
                    json.dumps(appetite.to_dict())))
        self.db.ex("INSERT INTO org_history(period, metrics_json) VALUES(0, ?)", (json.dumps(metrics),))
        for n, rid in enumerate(org["risks"], start=1):
            lib = self.c.risk_library[rid]
            row = {k: lib.get(k, "") for k in RISK_FIELDS}
            row.update({"risk_id": f"R-{n:03d}", "lib_id": rid, "source": "Inherited register",
                        "status": lib.get("status", "Open"), "owner": self.person(lib["owner_role"])["name"],
                        "action_owner": self.person(lib.get("action_role", lib["owner_role"]))["name"],
                        "created_period": 0, "updated_period": 0, "target_date": lib.get("target_date", ""),
                        "title": render(lib["title"], self.ctx()), "cause": render(lib["cause"], self.ctx()),
                        "event": render(lib["event"], self.ctx()),
                        "consequence": render(lib["consequence"], self.ctx())})
            self._write_risk(row)
        for kid in org["kris"]:
            lib = dict(self.c.kri_library[kid])
            lib["kri_id"] = kid
            lib["owner"] = self.person(lib.pop("owner_role"))["name"]
            lib["history"] = []
            k = KRI.from_dict(lib)
            self.db.ex("INSERT INTO kris(kri_id, data_json) VALUES(?, ?)", (kid, json.dumps(k.to_dict())))
            self.db.ex("INSERT INTO kri_history(kri_id, period, value) VALUES(?,?,?)", (kid, 0, k.current))
        for cid in org["controls"]:
            lib = dict(self.c.control_library[cid])
            lib["control_id"] = cid
            lib["owner"] = self.person(lib.get("owner_role", "coo"))["name"]
            self.db.ex("INSERT INTO controls(control_id, data_json) VALUES(?, ?)", (cid, json.dumps(lib)))
        for pid in org["processes"]:
            lib = dict(self.c.bia_library[pid])
            lib["pid"] = pid
            lib["owner"] = self.person(lib.pop("owner_role", "coo"))["name"]
            Process.from_dict(lib)  # validate
            self.db.ex("INSERT INTO bia(pid, data_json) VALUES(?, ?)", (pid, json.dumps(lib)))

    def close(self) -> None:
        self.db.close()

    def backup(self, reason: str) -> Path:
        return self.saves.backup(self.db, self.slot, reason)

    # ------------------------------------------------------------ basic data
    @property
    def profile(self) -> dict:
        if self._profile is None:
            self._profile = dict(self.db.one("SELECT * FROM profile"))
        return self._profile

    def _touch(self, **fields: Any) -> None:
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            self.db.ex(f"UPDATE profile SET {sets}, updated_at=? WHERE id=1", (*fields.values(), now()))
        else:
            self.db.ex("UPDATE profile SET updated_at=? WHERE id=1", (now(),))
        self._profile = None

    @property
    def org(self) -> dict:
        return self.c.orgs[self.profile["org_id"]]

    @property
    def level(self) -> int:
        return int(self.profile["level"])

    def level_def(self, n: int | None = None) -> Level:
        return Level.from_dict(self.c.level(n or self.level))

    def next_level_def(self) -> Level | None:
        n = self.level + 1
        if n > len(self.c.careers["levels"]):
            return None
        return self.level_def(n)

    def title(self) -> str:
        t = self.level_def().title_for(self.profile["career_path"])
        track = self.track()
        if self.level <= 9 and track.get("title_suffix"):
            return f"{t}, {track['title_suffix']}"
        return t

    def track(self) -> dict:
        return next(t for t in self.c.careers["tracks"] if t["id"] == self.profile["track"])

    def difficulty(self):
        return DIFFICULTIES[self.profile["difficulty"]]

    def person(self, role: str) -> dict:
        p = dict(self.org["people"][role])
        p.update({k: v for k, v in self.c.roles[role].items() if k not in p})
        p["role"] = role
        return p

    def ctx(self) -> dict:
        org = self.org
        people = {r: {"name": org["people"][r]["name"], "title": org["people"][r]["title"]} for r in self.c.roles}
        return {"org": org["name"], "cur": org["currency"], "currency": org["currency"],
                "money_scale": org["money_scale"], "player": self.profile["name"],
                "industry": org["industry_label"], "title": self.level_def().title_for(self.profile["career_path"]),
                "city": org["city"], "regulator": org["regulator"], "stakeholders": people,
                "flags": sorted(self.flags())}

    def money(self, v: float, compact: bool = True) -> str:
        return fmt_money(v, self.org["currency"], compact)

    def flags(self) -> set[str]:
        return {r["flag"] for r in self.db.q("SELECT flag FROM flags")}

    def period(self) -> int:
        return int(self.db.one("SELECT period FROM org_state")[0])

    def matrix(self) -> RiskMatrix:
        return RiskMatrix.from_dict(json.loads(self.db.one("SELECT matrix_json FROM org_state")[0]))

    def set_matrix(self, m: RiskMatrix) -> None:
        old = self.matrix().size
        with self.db.tx():
            self.db.ex("UPDATE org_state SET matrix_json=?", (json.dumps(m.to_dict()),))
            if m.size != old:
                # Re-express existing ratings on the new scale so the register stays valid.
                def conv(v: int) -> int:
                    return max(1, min(m.size, round((v - 1) * (m.size - 1) / (old - 1)) + 1))
                for r in self.list_risks():
                    for k in ("inh_l", "inh_i", "res_l", "res_i"):
                        r[k] = conv(int(r[k]))
                    r["res_l"] = min(r["res_l"], r["inh_l"])
                    r["res_i"] = min(r["res_i"], r["inh_i"])
                    self._write_risk(r)
            self.db.counter_add("matrix_configured")

    def appetite(self) -> Appetite:
        return Appetite.from_dict(json.loads(self.db.one("SELECT appetite_json FROM org_state")[0]))

    def set_appetite(self, a: Appetite) -> None:
        if a.default_appetite >= a.default_tolerance:
            raise ValueError("Appetite must be below tolerance")
        with self.db.tx():
            self.db.ex("UPDATE org_state SET appetite_json=?", (json.dumps(a.to_dict()),))
            self.db.counter_add("appetite_set")

    def counters(self) -> dict[str, int]:
        return self.db.counters()

    def count(self, key: str, n: int = 1) -> None:
        with self.db.tx():
            self.db.counter_add(key, n)

    # ------------------------------------------------------------------ world
    def load_world(self) -> World:
        row = self.db.one("SELECT * FROM org_state")
        p = self.profile
        return World(
            seed=int(p["seed"]), period=int(row["period"]), metrics=json.loads(row["metrics_json"]),
            trust=json.loads(row["trust_json"]), flags=self.flags(), budget=float(row["budget"]),
            kris=self.list_kris(), risks=self.list_risks(), scheduled=json.loads(row["scheduled_json"]),
            money_scale=self.org["money_scale"], currency=self.org["currency"],
            event_severity=self.difficulty().event_severity, ctx=self.ctx())

    def _save_world(self, w: World) -> None:
        self.db.ex("UPDATE org_state SET period=?, metrics_json=?, trust_json=?, budget=?, scheduled_json=?",
                   (w.period, json.dumps(w.metrics), json.dumps(w.trust), w.budget, json.dumps(w.scheduled)))
        existing = self.flags()
        for f in w.flags - existing:
            self.db.ex("INSERT OR IGNORE INTO flags(flag, set_period) VALUES(?,?)", (f, w.period))
        for f in existing - w.flags:
            self.db.ex("DELETE FROM flags WHERE flag=?", (f,))
        for k in w.kris:
            self.db.ex("UPDATE kris SET data_json=? WHERE kri_id=?", (json.dumps(k.to_dict()), k.kri_id))
        for r in w.risks:
            self._write_risk(r)

    def metrics(self) -> dict[str, float]:
        w = self.load_world()
        return w.snapshot()

    def trust(self) -> dict[str, float]:
        return json.loads(self.db.one("SELECT trust_json FROM org_state")[0])

    def budget(self) -> float:
        return float(self.db.one("SELECT budget FROM org_state")[0])

    def metrics_history(self) -> list[tuple[int, dict]]:
        return [(r["period"], json.loads(r["metrics_json"])) for r in
                self.db.q("SELECT period, metrics_json FROM org_history ORDER BY period")]

    def advance_period(self, reason: str = "manual") -> list[dict]:
        """Advance the organisation one month and record what happened."""
        with self.db.tx():
            w = self.load_world()
            events = tick(w, self.c.events, self._random_pool(), self.matrix())
            if w.period % 3 == 0:  # quarterly budget refresh
                w.budget += self.org["risk_budget"] * self.org["money_scale"] * 0.25 * self.difficulty().budget_mult
            self._save_world(w)
            snap = w.snapshot()
            self.db.ex("INSERT OR REPLACE INTO org_history(period, metrics_json) VALUES(?,?)",
                       (w.period, json.dumps(snap)))
            for k in w.kris:
                self.db.ex("INSERT OR REPLACE INTO kri_history(kri_id, period, value) VALUES(?,?,?)",
                           (k.kri_id, w.period, k.current))
            for e in events:
                self._log_event(e)
            self._generate_messages(events, w)
            self.db.counter_add("periods_advanced")
            self._touch()
        return events

    def _random_pool(self) -> list[dict]:
        ind = self.org["industry"]
        return [e for e in self.c.random_events if not e.get("industries") or ind in e["industries"]]

    def _log_event(self, e: dict) -> None:
        data = {k: v for k, v in e.items() if k not in ("title", "text", "type", "severity", "period")}
        self.db.ex("INSERT INTO events(period, type, title, text, severity, data_json) VALUES(?,?,?,?,?,?)",
                   (e.get("period", self.period()), e["type"], e["title"], e.get("text", ""),
                    int(e.get("severity", 0)), json.dumps(data, default=str)))

    def events(self, limit: int = 100, unacknowledged: bool = False) -> list[dict]:
        sql = "SELECT * FROM events"
        if unacknowledged:
            sql += " WHERE acknowledged=0"
        rows = self.db.q(sql + " ORDER BY id DESC LIMIT ?", (limit,))
        out = []
        for r in rows:
            d = dict(r)
            d["data"] = json.loads(d.pop("data_json") or "{}")
            out.append(d)
        return out

    def acknowledge_event(self, event_id: int) -> None:
        with self.db.tx():
            self.db.ex("UPDATE events SET acknowledged=1 WHERE id=?", (event_id,))

    # --------------------------------------------------------------- register
    def _write_risk(self, r: dict) -> None:
        row = {k: r.get(k) for k in RISK_FIELDS}
        cols = ", ".join(RISK_FIELDS)
        ph = ", ".join("?" for _ in RISK_FIELDS)
        self.db.ex(f"INSERT OR REPLACE INTO risks({cols}) VALUES({ph})", tuple(row[k] for k in RISK_FIELDS))

    def list_risks(self) -> list[dict]:
        return [dict(r) for r in self.db.q("SELECT * FROM risks ORDER BY risk_id")]

    def get_risk(self, risk_id: str) -> dict | None:
        r = self.db.one("SELECT * FROM risks WHERE risk_id=?", (risk_id,))
        return dict(r) if r else None

    def next_risk_id(self) -> str:
        nums = [int(r["risk_id"].split("-")[1]) for r in self.list_risks() if r["risk_id"].startswith("R-")]
        return f"R-{(max(nums) + 1) if nums else 1:03d}"

    def validate_risk(self, r: dict) -> list[str]:
        errs = []
        if not str(r.get("title", "")).strip():
            errs.append("Risk title is required.")
        if len(str(r.get("title", ""))) > 120:
            errs.append("Risk title must be 120 characters or fewer.")
        if r.get("category") not in RISK_CATEGORIES:
            errs.append("Choose a valid risk category.")
        size = self.matrix().size
        names = {"inh_l": "Inherent likelihood", "inh_i": "Inherent impact", "res_l": "Residual likelihood",
                 "res_i": "Residual impact"}
        for k in ("inh_l", "inh_i", "res_l", "res_i"):
            v = r.get(k)
            if not isinstance(v, int) or not 1 <= v <= size:
                errs.append(f"{names[k]} must be 1-{size}.")
        if not errs and (r["res_l"] > r["inh_l"] or r["res_i"] > r["inh_i"]):
            errs.append("Residual rating cannot exceed inherent rating.")
        if r.get("treatment") not in TREATMENTS:
            errs.append("Choose a treatment strategy.")
        if r.get("status") not in RISK_STATUSES:
            errs.append("Choose a valid status.")
        if not 0 <= int(r.get("control_eff", 0) or 0) <= 4:
            errs.append("Control effectiveness must be 0-4.")
        if not str(r.get("cause", "")).strip() or not str(r.get("consequence", "")).strip():
            errs.append("Describe both the cause and the consequence (cause - event - consequence).")
        return errs

    def save_risk(self, r: dict) -> dict:
        errs = self.validate_risk(r)
        if errs:
            raise ValueError("\n".join(errs))
        with self.db.tx():
            new = self.get_risk(r.get("risk_id", "")) is None
            if not r.get("risk_id"):
                r["risk_id"] = self.next_risk_id()
            r.setdefault("source", "Analyst")
            r.setdefault("lib_id", "")
            r.setdefault("created_period", self.period())
            r["updated_period"] = self.period()
            self._write_risk(r)
            self.db.counter_add("risks_added" if new else "risks_edited")
        return r

    def delete_risk(self, risk_id: str) -> None:
        with self.db.tx():
            self.db.ex("DELETE FROM risks WHERE risk_id=?", (risk_id,))
            self.db.counter_add("risks_deleted")

    def export_register_csv(self, path: Path) -> Path:
        risks = self.list_risks()
        appetite = self.appetite()
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["Risk ID", "Title", "Cause", "Event", "Consequence", "Category", "Owner",
                        "Inherent L", "Inherent I", "Inherent score", "Existing controls", "Control effectiveness",
                        "Residual L", "Residual I", "Residual score", "Appetite status", "Treatment",
                        "Action owner", "Target date", "Status", "Notes"])
            for r in risks:
                rs = r["res_l"] * r["res_i"]
                w.writerow([r["risk_id"], r["title"], r["cause"], r["event"], r["consequence"], r["category"],
                            r["owner"], r["inh_l"], r["inh_i"], r["inh_l"] * r["inh_i"], r["controls"],
                            r["control_eff"], r["res_l"], r["res_i"], rs, appetite.status(r["category"], rs),
                            r["treatment"], r["action_owner"], r["target_date"], r["status"], r["notes"]])
        self.count("exports")
        return path

    # ------------------------------------------------------------------- KRIs
    def list_kris(self) -> list[KRI]:
        return [KRI.from_dict(json.loads(r["data_json"])) for r in self.db.q("SELECT data_json FROM kris ORDER BY kri_id")]

    def save_kri(self, k: KRI) -> None:
        k.validate()
        with self.db.tx():
            new = self.db.one("SELECT 1 FROM kris WHERE kri_id=?", (k.kri_id,)) is None
            self.db.ex("INSERT OR REPLACE INTO kris(kri_id, data_json) VALUES(?,?)", (k.kri_id, json.dumps(k.to_dict())))
            if new:
                self.db.ex("INSERT OR REPLACE INTO kri_history(kri_id, period, value) VALUES(?,?,?)",
                           (k.kri_id, self.period(), k.current))
            self.db.counter_add("kri_created" if new else "kri_edited")

    def delete_kri(self, kri_id: str) -> None:
        with self.db.tx():
            self.db.ex("DELETE FROM kris WHERE kri_id=?", (kri_id,))
            self.db.ex("DELETE FROM kri_history WHERE kri_id=?", (kri_id,))

    def kri_history(self, kri_id: str) -> list[tuple[int, float]]:
        return [(r["period"], r["value"]) for r in
                self.db.q("SELECT period, value FROM kri_history WHERE kri_id=? ORDER BY period", (kri_id,))]

    def escalate_kri(self, kri_id: str, action: str) -> str:
        """Record the escalation action on a breached KRI. Proper escalation of a
        critical KRI builds trust and reduces drift; ignoring it is recorded too."""
        k = next(x for x in self.list_kris() if x.kri_id == kri_id)
        status = k.status()
        with self.db.tx():
            w = self.load_world()
            if action == "escalate":
                if status == "Normal":
                    apply_effects(w, {"trust": {"coo": -2}})
                    msg = "Escalated, but the KRI is within normal range. Over-escalation erodes credibility."
                else:
                    apply_effects(w, {"trust": {"coo": 2, "ceo": 1},
                                      "kri_adjust": [{"kri": kri_id, "drift": -0.03}]})
                    msg = f"Escalated to {k.owner} with the required action: {k.escalation}. Drift reduced."
                    self.db.counter_add("kri_escalated")
            elif action == "monitor":
                msg = "Recorded as 'monitor'. No change to drift."
                if status == "Critical":
                    apply_effects(w, {"flags": [f"ignored_kri_{kri_id}"]})
                    msg += " A critical breach left unescalated is recorded against you."
            else:
                raise ValueError("Unknown action")
            self._save_world(w)
            self._log_event({"type": "kri_action", "title": f"KRI {action}: {k.name}", "text": msg,
                             "severity": 0, "period": w.period})
        return msg

    # --------------------------------------------------------------- controls
    def list_controls(self) -> list[dict]:
        return [json.loads(r["data_json"]) for r in self.db.q("SELECT data_json FROM controls ORDER BY control_id")]

    def save_control(self, ctl: dict) -> None:
        if not ctl.get("name", "").strip():
            raise ValueError("Control name is required")
        with self.db.tx():
            self.db.ex("INSERT OR REPLACE INTO controls(control_id, data_json) VALUES(?,?)",
                       (ctl["control_id"], json.dumps(ctl)))

    def record_control_test(self, control_id: str, design: int, operating: int | None,
                            gaps: list[str], conclusion: str) -> dict:
        ctl = next(c for c in self.list_controls() if c["control_id"] == control_id)
        ctl["design_rating"] = design
        ctl["operating_rating"] = operating
        ctl["effectiveness"] = combined_effectiveness(design, operating)
        ctl["last_test"] = {"period": self.period(), "gaps": gaps, "conclusion": conclusion}
        with self.db.tx():
            self.save_control(ctl)
            # Propagate to linked register risks (residual reassessment).
            for r in self.list_risks():
                if r.get("lib_id") in ctl.get("mitigates", []):
                    r["control_eff"] = ctl["effectiveness"]
                    self._write_risk(r)
            self.db.counter_add("control_tests")
            w = self.load_world()
            avg = sum(c.get("effectiveness", 2) for c in self.list_controls()) / max(1, len(self.list_controls()))
            w.metrics["control_effectiveness"] = round(avg / 4 * 100, 1)
            self._save_world(w)
        return ctl

    def list_findings(self) -> list[dict]:
        return [json.loads(r["data_json"]) for r in self.db.q("SELECT data_json FROM findings ORDER BY finding_id")]

    def save_finding(self, f: dict) -> None:
        if not f.get("title", "").strip():
            raise ValueError("Finding title is required")
        with self.db.tx():
            new = self.db.one("SELECT 1 FROM findings WHERE finding_id=?", (f["finding_id"],)) is None
            self.db.ex("INSERT OR REPLACE INTO findings(finding_id, data_json) VALUES(?,?)",
                       (f["finding_id"], json.dumps(f)))
            if new:
                self.db.counter_add("findings_raised")
            if f.get("status") == "Closed":
                self.db.counter_add("findings_closed")

    def next_finding_id(self) -> str:
        return f"F-{len(self.list_findings()) + 1:03d}"

    # -------------------------------------------------------------------- BIA
    def list_processes(self) -> list[Process]:
        return [Process.from_dict(json.loads(r["data_json"])) for r in self.db.q("SELECT data_json FROM bia ORDER BY pid")]

    def save_process(self, p: Process) -> None:
        with self.db.tx():
            self.db.ex("INSERT OR REPLACE INTO bia(pid, data_json) VALUES(?,?)", (p.pid, json.dumps(p.to_dict())))

    def bia_review(self) -> dict:
        procs = self.list_processes()
        issues = validate_bia(procs)
        try:
            order = recovery_order(procs)
        except ValueError:
            order = []
        self.count("bia_reviews")
        if not issues:
            self.count("bia_clean")
        return {"issues": issues, "order": order, "tiers": {p.pid: criticality(p) for p in procs}}

    # --------------------------------------------------------------- messages
    def _add_message(self, role: str, subject: str, body: str, options: list[dict], data: dict | None = None) -> None:
        self.db.ex("INSERT INTO messages(period, sender, subject, body, options_json, status, data_json) VALUES(?,?,?,?,?,?,?)",
                   (self.period() if self.db.one("SELECT 1 FROM org_state") else 0, role, subject, body,
                    json.dumps(options), "unread", json.dumps(data or {})))

    def _generate_messages(self, events: list[dict], w: World) -> None:
        ctx = self.ctx()
        used = {r["subject"] for r in self.db.q("SELECT subject FROM messages")}
        for e in events:
            trig = {"kri_breach": "kri_breach", "incident": "incident", "scheduled": "scheduled",
                    "random": "random"}.get(e["type"])
            if not trig:
                continue
            tpl = next((t for t in self.c.messages if t["trigger"] == trig), None)
            if tpl:
                self._add_message(tpl["sender"], render(tpl["subject"], ctx) + f": {e['title']}",
                                  render(tpl["body"], ctx) + "\n\n" + e.get("text", ""), tpl["options"],
                                  {"event": e["title"]})
        pool = [t for t in self.c.messages if t["trigger"] == "periodic" and render(t["subject"], ctx) not in used
                and t.get("min_level", 1) <= self.level]
        if pool:
            rng = random.Random(stable_seed(w.seed, w.period, "msg"))
            if rng.random() < 0.7:
                tpl = rng.choice(pool)
                self._add_message(tpl["sender"], render(tpl["subject"], ctx), render(tpl["body"], ctx), tpl["options"])

    def list_messages(self) -> list[dict]:
        out = []
        for r in self.db.q("SELECT * FROM messages ORDER BY id DESC"):
            d = dict(r)
            d["options"] = json.loads(d.pop("options_json") or "[]")
            d["data"] = json.loads(d.pop("data_json") or "{}")
            out.append(d)
        return out

    def mark_read(self, msg_id: int) -> None:
        with self.db.tx():
            self.db.ex("UPDATE messages SET status='read' WHERE id=? AND status='unread'", (msg_id,))

    def reply_message(self, msg_id: int, option_index: int) -> dict:
        m = next(x for x in self.list_messages() if x["id"] == msg_id)
        if m["status"] == "replied":
            raise ValueError("Already replied")
        opt = m["options"][option_index]
        role = m["sender"]
        person = self.person(role)
        fit = 0
        if opt.get("approach") in person.get("prefers", []):
            fit = 3
        elif opt.get("approach") in person.get("dislikes", []):
            fit = -3
        q = int(opt.get("quality", 2))
        delta = (q - 1.5) * 2 + fit
        effects = dict(opt.get("effects", {}))
        effects["trust"] = {**effects.get("trust", {}), role: effects.get("trust", {}).get(role, 0) + delta}
        with self.db.tx():
            w = self.load_world()
            notes = apply_effects(w, effects, f"message:{msg_id}")
            self._save_world(w)
            self.db.ex("UPDATE messages SET status='replied', reply=? WHERE id=?", (opt["text"], msg_id))
            self.db.counter_add("messages_replied")
            st = self.load_competencies()
            st["stakeholder"].update(q / 3, 0.5)
            st["communication"].update(q / 3, 0.5)
            self._save_competencies(st)
            self._touch()
        style = person.get("style", "")
        explanation = render(opt.get("feedback", ""), self.ctx())
        if fit > 0:
            explanation += f" {person['name']} responds well to this approach ({style})."
        elif fit < 0:
            explanation += f" {person['name']} finds this approach frustrating ({style})."
        return {"trust_delta": delta, "notes": notes, "feedback": explanation}

    # ------------------------------------------------------------ investments
    def authority_limit(self) -> float:
        return self.level_def().authority_limit * self.org["money_scale"]

    def propose_investment(self, risk_id: str, title: str, cost: float, el_before: float, el_after: float,
                           res_l_delta: int = 0, res_i_delta: int = 0) -> dict:
        """Approve within delegated authority, otherwise the CFO decides based on
        the business case (benefit/cost) and their trust in the player."""
        if cost <= 0:
            raise ValueError("Cost must be positive")
        if el_after > el_before:
            raise ValueError("Expected loss after treatment cannot exceed before")
        if cost > self.budget():
            raise ValueError(f"Cost exceeds the remaining risk budget ({self.money(self.budget())})")
        benefit = el_before - el_after
        ratio = benefit * 3 / cost  # three-year benefit/cost
        trust = self.trust().get("cfo", 50)
        within = cost <= self.authority_limit()
        if within:
            approved, decided_by = ratio >= 0.5, "You (within delegated authority)"
            reason = ("Approved under your delegated authority." if approved else
                      "Even within your authority you declined it: the benefit/cost ratio is below 0.5.")
        else:
            rng = random.Random(stable_seed(self.profile["seed"], self.period(), "cfo", risk_id, cost))
            p = min(0.95, max(0.05, 0.25 * ratio + (trust - 50) / 100))
            approved = rng.random() < p
            decided_by = self.person("cfo")["name"] + " (CFO)"
            reason = (f"Above your {self.money(self.authority_limit())} authority. The CFO weighed a 3-year "
                      f"benefit/cost ratio of {ratio:.2f} and trust of {trust:.0f} (approval chance {p * 100:.0f}%): "
                      + ("approved." if approved else "declined. Strengthen the business case or build trust."))
        with self.db.tx():
            self.db.ex("INSERT INTO investments(risk_id, title, cost, el_before, el_after, status, decided_by, period, data_json)"
                       " VALUES(?,?,?,?,?,?,?,?,?)",
                       (risk_id, title, cost, el_before, el_after, "Approved" if approved else "Declined",
                        decided_by, self.period(), json.dumps({"ratio": ratio, "reason": reason})))
            if approved:
                w = self.load_world()
                w.budget -= cost
                w.metrics["operating_costs"] += cost * 0.1
                for r in w.risks:
                    if r["risk_id"] == risk_id:
                        r["res_l"] = max(1, r["res_l"] + res_l_delta)
                        r["res_i"] = max(1, r["res_i"] + res_i_delta)
                        r["status"] = "Treatment in progress"
                        r["notes"] = (r.get("notes") or "") + f"\n[P{w.period}] Investment approved: {title}."
                w.metrics["resilience"] = min(100, w.metrics["resilience"] + 1)
                self._save_world(w)
                self.db.counter_add("investments_approved")
            else:
                self.db.counter_add("investments_declined")
        return {"approved": approved, "decided_by": decided_by, "reason": reason, "ratio": ratio}

    def list_investments(self) -> list[dict]:
        out = []
        for r in self.db.q("SELECT * FROM investments ORDER BY id DESC"):
            d = dict(r)
            d["data"] = json.loads(d.pop("data_json") or "{}")
            out.append(d)
        return out

    # ------------------------------------------------------------ competency
    def load_competencies(self) -> dict[str, CompetencyState]:
        st = new_states()
        for r in self.db.q("SELECT * FROM competencies"):
            if r["key"] in st:
                st[r["key"]] = CompetencyState(r["score"], r["evidence"], json.loads(r["history_json"] or "[]"))
        return st

    def _save_competencies(self, st: dict[str, CompetencyState]) -> None:
        for k, v in st.items():
            self.db.ex("INSERT OR REPLACE INTO competencies(key, score, evidence, history_json) VALUES(?,?,?,?)",
                       (k, v.score, v.evidence, json.dumps(v.history)))

    def competency_scores(self) -> dict[str, float]:
        return {k: v.score for k, v in self.load_competencies().items()}

    def branch_tiers(self) -> dict[str, int]:
        st = self.load_competencies()
        return {b: branch_tier(st, b) for b in BRANCHES}

    def branch_scores(self) -> dict[str, tuple[float, int]]:
        st = self.load_competencies()
        return {b: branch_score(st, b) for b in BRANCHES}

    def recent_step_scores(self, n: int = 8) -> list[float]:
        return [r["score"] for r in self.db.q("SELECT score FROM decisions ORDER BY id DESC LIMIT ?", (n,))][::-1]

    def scaffolding(self) -> str:
        return scaffolding_level(self.recent_step_scores())

    # --------------------------------------------------------------- missions
    def best_scores(self) -> dict[str, float]:
        return {r["mission_id"]: r["s"] for r in
                self.db.q("SELECT mission_id, MAX(score) AS s FROM mission_runs WHERE status='completed' GROUP BY mission_id")}

    def mission_status(self) -> list[dict]:
        best = self.best_scores()
        active = {r["mission_id"]: r["run_id"] for r in self.db.q("SELECT mission_id, run_id FROM mission_runs WHERE status='active'")}
        flags = self.flags()
        out = []
        for m in self.c.mission_list():
            ok, why = mission_available(m, self.level, flags, best, self.org["industry"], self.profile["track"],
                                        self.org.get("geography", ""))
            if m["type"] == "executive":
                ok = ok and self.exec_unlocked()
                why = why or ("" if ok else "Unlocked after passing the CRO board simulation")
            out.append({"mission": m, "available": ok, "reason": why, "best": best.get(m["id"]),
                        "active_run": active.get(m["id"]),
                        "recommended": self.profile["track"] in m.get("tracks", [])})
        return out

    def start_or_resume(self, mission_id: str, modifier: str | None = None) -> tuple[int, MissionRun]:
        m = self.c.missions[mission_id]
        row = self.db.one("SELECT run_id, seed, checkpoint_json FROM mission_runs WHERE mission_id=? AND status='active'"
                          " ORDER BY run_id DESC", (mission_id,))
        if row:
            state = json.loads(row["checkpoint_json"])
            run = MissionRun(self._apply_modifier(m, state.get("modifier")), self.ctx(), row["seed"],
                             state.get("difficulty", self.profile["difficulty"]), state.get("scaffolding", "normal"), state)
            return row["run_id"], run
        attempt = self.db.one("SELECT count(*) FROM mission_runs WHERE mission_id=?", (mission_id,))[0]
        seed = stable_seed(self.profile["seed"], mission_id, attempt)
        diff = "expert" if modifier == "expert_constraints" else self.profile["difficulty"]
        run = MissionRun(self._apply_modifier(m, modifier), self.ctx(), seed, diff, self.scaffolding())
        run.state["modifier"] = modifier
        with self.db.tx():
            cur = self.db.ex("INSERT INTO mission_runs(mission_id, status, seed, checkpoint_json, started_at, period)"
                             " VALUES(?,?,?,?,?,?)", (mission_id, "active", seed, json.dumps(run.state), now(), self.period()))
            run_id = int(cur.lastrowid)
        return run_id, run

    def _apply_modifier(self, m: dict, modifier: str | None) -> dict:
        if not modifier:
            return m
        m = json.loads(json.dumps(m))
        if modifier == "tight_budget":
            for s in m["steps"]:
                if s["type"] == "allocate":
                    s["budget"] = s["budget"] * 0.75
                    if not any(i["cost"] <= s["budget"] for i in s["items"]):
                        s["budget"] = min(i["cost"] for i in s["items"])
        elif modifier == "no_hints":
            for s in m["steps"]:
                s.pop("hint", None)
                s.pop("worked_example", None)
        return m

    def save_checkpoint(self, run_id: int, run: MissionRun) -> None:
        with self.db.tx():
            self.db.ex("UPDATE mission_runs SET checkpoint_json=? WHERE run_id=? AND status='active'",
                       (json.dumps(run.state), run_id))

    def abandon(self, run_id: int) -> None:
        with self.db.tx():
            self.db.ex("UPDATE mission_runs SET status='abandoned', completed_at=? WHERE run_id=?", (now(), run_id))

    def complete_mission(self, run_id: int, run: MissionRun) -> dict:
        res: MissionResult = run.finish()
        m = self.c.missions[res.mission_id]
        prev_best = self.best_scores().get(res.mission_id)
        period = self.period()
        if prev_best is None:
            xp = res.xp
        elif res.score > prev_best:
            xp = int(res.xp * 0.25)
        else:
            xp = 0
        with self.db.tx():
            self.db.ex("UPDATE mission_runs SET status='completed', score=?, result_json=?, completed_at=?, checkpoint_json=?"
                       " WHERE run_id=?", (res.score, json.dumps(self._result_json(res)), now(), json.dumps(run.state), run_id))
            for s in run.steps:
                r = res.step_results[[x["id"] for x in run.steps].index(s["id"])]
                self.db.ex("INSERT INTO decisions(run_id, mission_id, step_id, answer_json, score, quality, confidence, correct,"
                           " outcome, luck, period) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (run_id, m["id"], s["id"], json.dumps(run.state["answers"].get(s["id"])), r.score, r.quality,
                            r.confidence, None if r.correct is None else int(r.correct), r.outcome, r.luck, period))
                if r.confidence is not None and r.correct is not None:
                    self.db.ex("INSERT INTO calibration(confidence, correct, source, period) VALUES(?,?,?,?)",
                               (r.confidence, int(r.correct), f"{m['id']}/{s['id']}", period))
            st = self.load_competencies()
            weight = 1.0 + 0.1 * max(0, m["level"] - 1) / 3
            for k, perf in res.competency_perf.items():
                st[k].update(max(0.0, min(1.0, perf)), weight)
                self.db.ex("INSERT INTO competency_evidence(key, perf, mission_id, period) VALUES(?,?,?,?)",
                           (k, perf, m["id"], period))
            self._save_competencies(st)
            w = self.load_world()
            notes = []
            for e in res.effects:
                notes += apply_effects(w, e, m["id"])
            self._save_world(w)
            self._touch(xp=self.profile["xp"] + xp)
            self.db.counter_add("missions_completed")
            self.db.counter_add(f"type_{m['type']}")
            if not run.state["hints_used"] and not run.state["examples_used"]:
                self.db.counter_add("independent_missions")
            if any("bad luck" in l for l in res.luck_notes):
                self.db.counter_add("good_decision_bad_luck")
            if run.state.get("modifier"):
                self.db.counter_add("weekly_challenges")
            for e in m.get("on_complete", {}).get("counters", []):
                self.db.counter_add(e)
            self._log_event({"type": "mission", "title": f"Completed: {m['title']}",
                             "text": f"Score {res.score * 100:.0f}%. {res.debrief.get('ending_title', '')}",
                             "severity": 0, "period": period, "changes": notes})
            self.db.ex("INSERT INTO career_history(period, event, detail, level, title, salary, created_at) VALUES(?,?,?,?,?,?,?)",
                       (period, "Mission", f"{m['title']} - {res.score * 100:.0f}%", self.level, self.title(),
                        self.profile["salary"], now()))
            if m["type"] == "executive" and res.score >= 0.7:
                path = next((p for p in self.c.careers["exec_paths"] if p["assessment"] == m["id"]), None)
                if path:
                    self.db.ex("INSERT OR REPLACE INTO exec_paths(path_id, status, score, period) VALUES(?,?,?,?)",
                               (path["id"], "completed", res.score, period))
            if m["id"] == self.c.careers["final_assessment"] and res.score >= 0.7:
                self.db.meta_set("cro_passed", True)
        events: list[dict] = []
        if m["type"] in PERIOD_ADVANCING:
            events = self.advance_period("mission")
        new_ach = self.check_achievements()
        self.backup("auto")
        return {"result": res, "xp": xp, "effects": notes, "events": events, "achievements": new_ach,
                "promotion_ready": eligible(self.promotion_checks()), "first_completion": prev_best is None}

    def _result_json(self, res: MissionResult) -> dict:
        return {"score": res.score, "competency_perf": res.competency_perf, "ending": res.ending, "xp": res.xp,
                "debrief": res.debrief, "luck": res.luck_notes,
                "steps": [r.to_dict() for r in res.step_results]}

    def mission_results(self, limit: int = 50) -> list[dict]:
        out = []
        for r in self.db.q("SELECT * FROM mission_runs WHERE status='completed' ORDER BY run_id DESC LIMIT ?", (limit,)):
            d = dict(r)
            d["result"] = json.loads(d.pop("result_json") or "{}")
            m = self.c.missions.get(d["mission_id"], {})
            d["title"] = m.get("title", d["mission_id"])
            d["type"] = m.get("type", "")
            out.append(d)
        return out

    def weekly_challenges(self, today: date | None = None) -> list[dict]:
        """Three replayable missions with alternative constraints, chosen per ISO week.
        Optional: nothing is lost by skipping a week."""
        today = today or date.today()
        y, wk, _ = today.isocalendar()
        best = self.best_scores()
        pool = sorted(mid for mid in best if self.c.missions[mid]["type"] in ("career", "side", "crisis"))
        if not pool:
            return []
        rng = random.Random(stable_seed(self.profile["seed"], y, wk))
        mods = [("tight_budget", "Budget cut by 25%"), ("no_hints", "No hints or worked examples"),
                ("expert_constraints", "Executive tolerances and event severity")]
        picks = rng.sample(pool, min(3, len(pool)))
        return [{"mission_id": mid, "modifier": mods[i % 3][0], "label": mods[i % 3][1],
                 "title": self.c.missions[mid]["title"]} for i, mid in enumerate(picks)]

    # ------------------------------------------------------------- promotion
    def mission_titles(self) -> dict[str, str]:
        return {k: v["title"] for k, v in self.c.missions.items()}

    def promotion_checks(self):
        return promotion_checks(self.level_def(), self.next_level_def(), self.profile["career_path"],
                                self.profile["xp"], self.best_scores(), self.competency_scores(), self.mission_titles())

    def comp_context(self) -> CompContext:
        car = self.c.careers
        geo = next(g for g in car["geographies"] if g["key"] == self.org["geography"])
        return CompContext(geo, car["industry_multipliers"].get(self.org["industry"], 1.0),
                           car["size_multipliers"].get(self.org["size"], 1.0), self.track().get("pay_multiplier", 1.0))

    def salary_range(self, level: Level | None = None) -> dict:
        return salary_range(level or self.level_def(), self.comp_context())

    def interview_questions(self) -> list[dict]:
        nxt = self.next_level_def()
        if not nxt:
            return []
        stage = str(nxt.stage)
        pool = self.c.interview["stages"].get(stage, [])
        rng = random.Random(stable_seed(self.profile["seed"], "interview", nxt.level,
                                        self.db.counters().get("interviews", 0)))
        return rng.sample(pool, min(3, len(pool)))

    def evidence_strength(self) -> float:
        best = self.best_scores()
        ids = self.level_def().required_missions + ([self.level_def().capstone] if self.level_def().capstone else [])
        vals = [best.get(i, 0) for i in ids]
        return sum(vals) / len(vals) if vals else 0.5

    def promote(self, interview: list[tuple[dict, int]], ask_position: float, path: str | None = None) -> dict:
        """interview: list of (question, chosen option index). Returns outcome."""
        checks = self.promotion_checks()
        if not eligible(checks):
            raise ValueError("Promotion requirements are not yet met")
        nxt = self.next_level_def()
        assert nxt is not None
        q_scores = [q["options"][i]["quality"] / 3 for q, i in interview]
        iscore = sum(q_scores) / len(q_scores) if q_scores else 0
        feedback = [q["options"][i].get("feedback", "") for q, i in interview]
        with self.db.tx():
            self.db.counter_add("interviews")
        if iscore < 0.5:
            return {"promoted": False, "interview_score": iscore, "feedback": feedback,
                    "note": "The panel was not yet convinced. Review the feedback and try again when ready; "
                            "there is no waiting period."}
        new_path = path or self.profile["career_path"]
        if new_path not in ("management", "expert"):
            raise ValueError("Unknown path")
        rng_range = salary_range(nxt, self.comp_context())
        neg = negotiate(rng_range, ask_position, self.evidence_strength(), self.trust().get("chro", 50))
        with self.db.tx():
            self._touch(level=nxt.level, salary=neg["salary"], career_path=new_path)
            w = self.load_world()
            apply_effects(w, {"trust": {"chro": neg["trust_delta"]}})
            w.budget += nxt.authority_limit * self.org["money_scale"] * 0.5
            self._save_world(w)
            self.db.counter_add("promotions")
            if neg["position"] >= neg["supported"] - 0.05 and ask_position > 0.5:
                self.db.counter_add("strong_negotiations")
            title = nxt.title_for(new_path)
            self.db.ex("INSERT INTO career_history(period, event, detail, level, title, salary, created_at) VALUES(?,?,?,?,?,?,?)",
                       (self.period(), "Promotion", f"Promoted to {title}. {neg['note']}", nxt.level, title,
                        neg["salary"], now()))
            self._add_message("mentor", f"Congratulations on becoming {title}",
                              render(self.c.careers["promotion_note"], self.ctx()) + "\n\nNew responsibilities:\n- "
                              + "\n- ".join(nxt.responsibilities), [])
        self.check_achievements()
        self.backup("promotion")
        return {"promoted": True, "interview_score": iscore, "feedback": feedback, "negotiation": neg,
                "title": nxt.title_for(new_path), "level": nxt.level, "salary_range": rng_range}

    def change_track(self, track: str) -> None:
        if track not in {t["id"] for t in self.c.careers["tracks"]}:
            raise ValueError("Unknown track")
        with self.db.tx():
            old = self.profile["track"]
            self._touch(track=track)
            self.db.counter_add("track_changes")
            self.db.ex("INSERT INTO career_history(period, event, detail, level, title, salary, created_at) VALUES(?,?,?,?,?,?,?)",
                       (self.period(), "Lateral move", f"Moved from {old} to {track}", self.level, self.title(),
                        self.profile["salary"], now()))

    def change_organisation(self, org_id: str) -> "Game":
        """Move to a new organisation/industry, keeping level, competencies and achievements.
        The organisation simulation restarts for the new employer."""
        if org_id not in self.c.orgs or org_id == self.profile["org_id"]:
            raise ValueError("Choose a different organisation")
        self.backup("pre-move")
        carry = {"competencies": {k: {"score": v.score, "evidence": v.evidence} for k, v in self.load_competencies().items()},
                 "achievements": [r["id"] for r in self.db.q("SELECT id FROM achievements")]}
        prof = dict(self.profile)
        best = self.db.q("SELECT mission_id, status, seed, checkpoint_json, score, result_json, started_at, completed_at, period"
                         " FROM mission_runs WHERE status='completed'")
        best = [dict(r) for r in best]
        history = [dict(r) for r in self.db.q("SELECT * FROM career_history ORDER BY id")]
        counters = self.db.counters()
        calib = [dict(r) for r in self.db.q("SELECT confidence, correct, source, period FROM calibration")]
        self.close()
        g = Game.new_career(self.c, self.saves, self.slot, prof["name"], org_id, prof["track"], prof["difficulty"],
                            prof["avatar"], seed=stable_seed(prof["seed"], org_id), ngplus=prof["ngplus"], carry=carry)
        with g.db.tx():
            # Keep competencies exactly (not discounted) for a lateral move.
            st = g.load_competencies()
            for k, v in carry["competencies"].items():
                st[k].score, st[k].evidence = v["score"], v["evidence"]
            g._save_competencies(st)
            g._touch(level=prof["level"], xp=prof["xp"], career_path=prof["career_path"])
            sal = g.salary_range()
            g._touch(salary=sal["mid"])
            for r in best:
                g.db.ex("INSERT INTO mission_runs(mission_id, status, seed, checkpoint_json, score, result_json, started_at,"
                        " completed_at, period) VALUES(:mission_id,:status,:seed,:checkpoint_json,:score,:result_json,"
                        ":started_at,:completed_at,:period)", r)
            g.db.ex("DELETE FROM career_history")
            for h in history:
                g.db.ex("INSERT INTO career_history(period, event, detail, level, title, salary, created_at) VALUES(?,?,?,?,?,?,?)",
                        (h["period"], h["event"], h["detail"], h["level"], h["title"], h["salary"], h["created_at"]))
            g.db.ex("INSERT INTO career_history(period, event, detail, level, title, salary, created_at) VALUES(?,?,?,?,?,?,?)",
                    (0, "Industry move", f"Joined {g.org['name']} ({g.org['industry_label']})", g.level, g.title(),
                     sal["mid"], now()))
            for k, v in counters.items():
                g.db.ex("INSERT OR REPLACE INTO counters(key, value) VALUES(?,?)", (k, v))
            g.db.counter_add("org_changes")
            for cal in calib:
                g.db.ex("INSERT INTO calibration(confidence, correct, source, period) VALUES(:confidence,:correct,:source,:period)", cal)
        return g

    def new_game_plus(self, org_id: str, difficulty: str = "expert") -> "Game":
        """Restart the career at level 1 in a new organisation with harder settings.
        Achievements and a share of competency carry over."""
        carry = {"competencies": {k: {"score": v.score, "evidence": v.evidence} for k, v in self.load_competencies().items()},
                 "achievements": [r["id"] for r in self.db.q("SELECT id FROM achievements")]}
        prof = dict(self.profile)
        self.backup("pre-ngplus")
        self.close()
        return Game.new_career(self.c, self.saves, self.slot, prof["name"], org_id, prof["track"], difficulty,
                               prof["avatar"], ngplus=prof["ngplus"] + 1, carry=carry)

    def career_history(self) -> list[dict]:
        return [dict(r) for r in self.db.q("SELECT * FROM career_history ORDER BY id")]

    # ------------------------------------------------------- executive paths
    def cro_passed(self) -> bool:
        return bool(self.db.meta_get("cro_passed", False))

    def exec_unlocked(self) -> bool:
        return self.level >= len(self.c.careers["levels"]) and self.cro_passed()

    def exec_paths(self) -> list[dict]:
        done = {r["path_id"]: dict(r) for r in self.db.q("SELECT * FROM exec_paths")}
        comps = self.competency_scores()
        best = self.best_scores()
        out = []
        for p in self.c.careers["exec_paths"]:
            gaps = [f"{k} {comps.get(k, 0):.0f}/{v}" for k, v in p["minima"].items() if comps.get(k, 0) < v]
            out.append({**p, "unlocked": self.exec_unlocked(), "competency_gaps": gaps,
                        "ready": self.exec_unlocked() and not gaps, "completed": p["id"] in done,
                        "best": best.get(p["assessment"])})
        return out

    # ------------------------------------------------------------- learning
    def review_cards(self) -> list[ReviewCard]:
        return [ReviewCard(r["concept_id"], r["box"], r["due"], r["reviews"], r["lapses"], r["last_result"])
                for r in self.db.q("SELECT * FROM review_cards")]

    def unlocked_concepts(self) -> set[str]:
        """Concepts become reviewable once a mission that teaches them is completed."""
        best = self.best_scores()
        out = set()
        for mid in best:
            out.update(self.c.missions[mid].get("concepts", []))
        return out

    def due_reviews(self, intervals: list[int] | None = None, today: date | None = None, limit: int = 10) -> list[ReviewCard]:
        today = today or date.today()
        unlocked = self.unlocked_concepts()
        cards = [c for c in self.review_cards() if c.concept_id in unlocked]
        return due_cards(cards, today, limit)

    def record_review(self, concept_id: str, chosen: int, confidence: float | None,
                      intervals: list[int], today: date | None = None) -> dict:
        today = today or date.today()
        concept = self.c.concepts[concept_id]
        correct = chosen == concept["answer"]
        card = next(c for c in self.review_cards() if c.concept_id == concept_id)
        schedule(card, correct, today, intervals)
        with self.db.tx():
            self.db.ex("UPDATE review_cards SET box=?, due=?, reviews=?, lapses=?, last_result=? WHERE concept_id=?",
                       (card.box, card.due, card.reviews, card.lapses, card.last_result, concept_id))
            self.db.counter_add("reviews_done")
            if correct:
                self.db.counter_add("reviews_correct")
            if confidence is not None:
                self.db.ex("INSERT INTO calibration(confidence, correct, source, period) VALUES(?,?,?,?)",
                           (confidence, int(correct), f"review/{concept_id}", self.period()))
            st = self.load_competencies()
            comp = concept.get("competency", "technical")
            st[comp].update(1.0 if correct else 0.2, 0.3)
            self._save_competencies(st)
        return {"correct": correct, "explanation": concept["explanation"], "next_due": card.due, "box": card.box}

    def calibration(self) -> Calibration:
        cal = Calibration()
        for r in self.db.q("SELECT confidence, correct FROM calibration"):
            cal.add(float(r["confidence"]), bool(r["correct"]))
        return cal

    # ------------------------------------------------------------- crisis
    def start_crisis_exercise(self) -> CrisisExercise:
        n = self.db.counters().get("crisis_exercises_started", 0)
        self.count("crisis_exercises_started")
        seed = stable_seed(self.profile["seed"], "crisis", n)
        return build_exercise(self.c.crisis_threats, seed, self.level, self.difficulty().event_severity)

    def finish_crisis_exercise(self, ex: CrisisExercise) -> dict:
        sc = ex.score()
        with self.db.tx():
            self.db.counter_add("crisis_exercises")
            if sc["score"] >= 0.7:
                self.db.counter_add("crisis_wins")
            if sc["failed"] == 0 and sc["prioritisation"] >= 0.8:
                self.db.counter_add("crisis_flawless")
            st = self.load_competencies()
            st["prioritization"].update(sc["prioritisation"], 0.8)
            st["decision"].update(sc["containment"], 0.8)
            st["leadership"].update(sc["score"], 0.6)
            st["communication"].update(sc["credibility"] / 100, 0.4)
            self._save_competencies(st)
            w = self.load_world()
            apply_effects(w, {"org": {"resilience": round((sc["score"] - 0.5) * 6, 1)}})
            self._save_world(w)
            self._log_event({"type": "crisis_exercise", "title": "Crisis exercise completed",
                             "text": f"Score {sc['score'] * 100:.0f}%, {sc['failed']} threat(s) lost control, "
                                     f"prioritisation {sc['prioritisation'] * 100:.0f}% (seed {ex.seed}).",
                             "severity": 0, "period": w.period})
        self.check_achievements()
        return sc

    # --------------------------------------------------------- achievements
    def stats(self) -> dict:
        best = self.best_scores()
        completed = [{"id": mid, "type": self.c.missions[mid]["type"], "score": s} for mid, s in best.items()]
        return {"best_scores": best, "completed": completed, "level": self.level,
                "competencies": self.competency_scores(), "branch_tiers": self.branch_tiers(),
                "counters": self.db.counters(), "flags": self.flags(), "calibration": self.calibration().summary(),
                "stakeholder_trust": self.trust(),
                "paths_completed": {r["path_id"] for r in self.db.q("SELECT path_id FROM exec_paths WHERE status='completed'")}}

    def check_achievements(self) -> list[dict]:
        have = {r["id"] for r in self.db.q("SELECT id FROM achievements")}
        new = ach.evaluate(self.c.achievements, self.stats(), have)
        if new:
            with self.db.tx():
                for a in new:
                    self.db.ex("INSERT OR IGNORE INTO achievements(id, earned_at, period) VALUES(?,?,?)",
                               (a["id"], now(), self.period()))
        return new

    def earned_achievements(self) -> dict[str, dict]:
        return {r["id"]: dict(r) for r in self.db.q("SELECT * FROM achievements")}

    # ------------------------------------------------------------- reviews
    def performance_review(self) -> dict:
        stage = str(self.level_def().stage)
        expectations = self.c.rubrics["stage_expectations"][stage]
        evidence = []
        for r in self.mission_results(20):
            evidence.append({"mission": r["mission_id"], "title": r["title"], "score": r["score"],
                             "competencies": r["result"].get("competency_perf", {})})
        return performance_review(self.load_competencies(), expectations, evidence,
                                  self.c.rubrics["recommendations"], self.calibration().summary())

    # -------------------------------------------------------------- reset
    def reset_career(self, confirm: str) -> None:
        if confirm != "RESET":
            raise PermissionError("Reset requires typing RESET")
        self.backup("pre-reset")
        self.close()
        self.saves.delete_slot(self.slot, "DELETE")

    # -------------------------------------------------------- report data
    def report_data(self) -> dict:
        risks = self.list_risks()
        appetite = self.appetite()
        m = self.matrix()
        scale = self.org["money_scale"]
        for r in risks:
            r["res_score"] = r["res_l"] * r["res_i"]
            r["inh_score"] = r["inh_l"] * r["inh_i"]
            r["appetite"] = appetite.status(r["category"], r["res_score"])
            r["el"] = expected_loss(m.midpoint_probability(r["res_l"]), m.midpoint_impact(r["res_i"], scale))
        kris = self.list_kris()
        return {
            "org": self.org, "player": self.profile["name"], "title": self.title(), "period": self.period(),
            "currency": self.org["currency"], "risks": risks, "matrix": m, "appetite": appetite,
            "kris": [{"kri": k, "history": self.kri_history(k.kri_id)} for k in kris],
            "metrics": self.metrics(), "history": self.metrics_history(), "events": self.events(60),
            "investments": self.list_investments(), "findings": self.list_findings(),
            "controls": self.list_controls(), "budget": self.budget(), "trust": self.trust(),
            "people": {r: self.person(r) for r in self.c.roles}, "level": self.level,
        }

    def record_report(self, kind: str, title: str, path: str) -> None:
        with self.db.tx():
            self.db.ex("INSERT INTO reports(kind, title, period, path, created_at) VALUES(?,?,?,?,?)",
                       (kind, title, self.period(), path, now()))
            self.db.counter_add("reports_generated")
            self.db.counter_add(f"report_{kind}")
        self.check_achievements()
