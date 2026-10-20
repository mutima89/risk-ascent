"""SQLite persistence: connection handling, transactions and schema migrations.

Each career is one SQLite file (a save slot). Writes happen inside explicit
transactions so an interrupted save (crash, power loss) rolls back cleanly
instead of leaving half-written state. The schema version is stored in
PRAGMA user_version and upgraded by ordered migrations.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator


def _run(c: sqlite3.Connection, script: str) -> None:
    # executescript() would COMMIT implicitly; run statements one by one so the
    # whole migration stays inside the caller's transaction.
    for stmt in script.split(";"):
        if stmt.strip():
            c.execute(stmt)


def _m1(c: sqlite3.Connection) -> None:
    _run(c, """
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE profile (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        name TEXT NOT NULL, avatar TEXT, track TEXT, industry TEXT, org_id TEXT,
        geography TEXT, career_path TEXT, level INTEGER NOT NULL, xp INTEGER NOT NULL,
        salary REAL, seed INTEGER NOT NULL, difficulty TEXT, ngplus INTEGER DEFAULT 0,
        created_at TEXT, updated_at TEXT);
    CREATE TABLE org_state (
        id INTEGER PRIMARY KEY CHECK (id = 1), period INTEGER NOT NULL,
        metrics_json TEXT NOT NULL, trust_json TEXT NOT NULL, budget REAL NOT NULL,
        scheduled_json TEXT NOT NULL, matrix_json TEXT NOT NULL, appetite_json TEXT NOT NULL);
    CREATE TABLE org_history (period INTEGER PRIMARY KEY, metrics_json TEXT NOT NULL);
    CREATE TABLE flags (flag TEXT PRIMARY KEY, set_period INTEGER);
    CREATE TABLE risks (
        risk_id TEXT PRIMARY KEY, title TEXT NOT NULL, cause TEXT, event TEXT, consequence TEXT,
        category TEXT, owner TEXT, inh_l INTEGER, inh_i INTEGER, controls TEXT,
        control_eff INTEGER, res_l INTEGER, res_i INTEGER, treatment TEXT, action_owner TEXT,
        target_date TEXT, status TEXT, notes TEXT, source TEXT, lib_id TEXT,
        created_period INTEGER, updated_period INTEGER);
    CREATE TABLE kris (kri_id TEXT PRIMARY KEY, data_json TEXT NOT NULL);
    CREATE TABLE kri_history (kri_id TEXT, period INTEGER, value REAL, PRIMARY KEY (kri_id, period));
    CREATE TABLE mission_runs (
        run_id INTEGER PRIMARY KEY AUTOINCREMENT, mission_id TEXT NOT NULL, status TEXT NOT NULL,
        seed INTEGER, checkpoint_json TEXT, score REAL, result_json TEXT,
        started_at TEXT, completed_at TEXT, period INTEGER);
    CREATE TABLE decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER, mission_id TEXT, step_id TEXT,
        answer_json TEXT, score REAL, quality INTEGER, confidence REAL, correct INTEGER,
        outcome TEXT, luck TEXT, period INTEGER);
    CREATE TABLE competencies (key TEXT PRIMARY KEY, score REAL, evidence INTEGER, history_json TEXT);
    CREATE TABLE competency_evidence (
        id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT, perf REAL, mission_id TEXT, period INTEGER);
    CREATE TABLE events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, period INTEGER, type TEXT, title TEXT, text TEXT,
        severity INTEGER, data_json TEXT, acknowledged INTEGER DEFAULT 0);
    CREATE TABLE achievements (id TEXT PRIMARY KEY, earned_at TEXT, period INTEGER);
    CREATE TABLE review_cards (
        concept_id TEXT PRIMARY KEY, box INTEGER, due TEXT, reviews INTEGER, lapses INTEGER,
        last_result TEXT);
    CREATE TABLE counters (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
    CREATE TABLE career_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, period INTEGER, event TEXT, detail TEXT,
        level INTEGER, title TEXT, salary REAL, created_at TEXT);
    """)


def _m2(c: sqlite3.Connection) -> None:
    _run(c, """
    CREATE TABLE controls (control_id TEXT PRIMARY KEY, data_json TEXT NOT NULL);
    CREATE TABLE findings (finding_id TEXT PRIMARY KEY, data_json TEXT NOT NULL);
    CREATE TABLE bia (pid TEXT PRIMARY KEY, data_json TEXT NOT NULL);
    CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, period INTEGER, sender TEXT, subject TEXT,
        body TEXT, options_json TEXT, status TEXT DEFAULT 'unread', reply TEXT, data_json TEXT);
    """)


def _m3(c: sqlite3.Connection) -> None:
    _run(c, """
    CREATE TABLE calibration (
        id INTEGER PRIMARY KEY AUTOINCREMENT, confidence REAL, correct INTEGER, source TEXT, period INTEGER);
    CREATE TABLE investments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, risk_id TEXT, title TEXT, cost REAL,
        el_before REAL, el_after REAL, status TEXT, decided_by TEXT, period INTEGER, data_json TEXT);
    CREATE TABLE exec_paths (path_id TEXT PRIMARY KEY, status TEXT, score REAL, period INTEGER);
    CREATE TABLE reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, title TEXT, period INTEGER, path TEXT, created_at TEXT);
    CREATE INDEX idx_decisions_mission ON decisions(mission_id);
    CREATE INDEX idx_events_period ON events(period);
    """)


MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [_m1, _m2, _m3]
SCHEMA_VERSION = len(MIGRATIONS)


class SaveCorrupt(Exception):
    pass


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.conn = sqlite3.connect(str(self.path), isolation_level=None, timeout=10)
        self.conn.row_factory = sqlite3.Row
        try:
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.conn.execute("PRAGMA synchronous = FULL")
        except sqlite3.DatabaseError:
            # A damaged file: release the handle so Windows lets recovery move it aside.
            self.conn.close()
            raise
        self._depth = 0

    # --- integrity & schema ---
    def integrity_ok(self) -> bool:
        try:
            row = self.conn.execute("PRAGMA integrity_check").fetchone()
            return row is not None and row[0] == "ok"
        except sqlite3.DatabaseError:
            return False

    @property
    def version(self) -> int:
        return int(self.conn.execute("PRAGMA user_version").fetchone()[0])

    def migrate(self, target: int = SCHEMA_VERSION) -> list[int]:
        applied = []
        current = self.version
        if current > SCHEMA_VERSION:
            raise SaveCorrupt(f"Save was created by a newer version (schema {current}).")
        for v in range(current, target):
            with self.tx():
                MIGRATIONS[v](self.conn)
                self.conn.execute(f"PRAGMA user_version = {v + 1}")
            applied.append(v + 1)
        return applied

    # --- transactions ---
    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Nested-safe transaction. Outermost level commits or rolls back."""
        if self._depth == 0:
            self.conn.execute("BEGIN IMMEDIATE")
        self._depth += 1
        try:
            yield self.conn
        except BaseException:
            self._depth -= 1
            if self._depth == 0:
                self.conn.execute("ROLLBACK")
            raise
        else:
            self._depth -= 1
            if self._depth == 0:
                self.conn.execute("COMMIT")

    # --- helpers ---
    def q(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def ex(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def meta_get(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return json.loads(row[0]) if row else default

    def meta_set(self, key: str, value: Any) -> None:
        self.ex("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)))

    def counter_add(self, key: str, n: int = 1) -> int:
        self.ex("INSERT INTO counters(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=value+?",
                (key, n, n))
        return int(self.one("SELECT value FROM counters WHERE key=?", (key,))[0])

    def counters(self) -> dict[str, int]:
        return {r["key"]: r["value"] for r in self.q("SELECT key, value FROM counters")}

    def checkpoint_wal(self) -> None:
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.DatabaseError:
            pass

    def close(self) -> None:
        try:
            self.checkpoint_wal()
        finally:
            try:
                self.conn.close()
            except sqlite3.Error:
                pass


def open_database(path: Path | str) -> Database:
    db = Database(path)
    if not db.integrity_ok():
        db.close()
        raise SaveCorrupt(f"Integrity check failed for {path}")
    db.migrate()
    return db
