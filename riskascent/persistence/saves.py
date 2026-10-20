"""Save slots, backups and recovery.

Layout under the user data directory:
  saves/slot_1.db ... slot_N.db      one career per slot
  backups/slot_1/20261020-093000_auto.db

Backups use SQLite's online backup API, which produces a consistent copy
even while the game is running. Restoring always takes a safety backup of
the current file first, so a restore can itself be undone.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from .db import Database, SaveCorrupt, open_database

MAX_SLOTS = 5
KEEP_BACKUPS = 15


class SaveManager:
    def __init__(self, saves: Path, backups: Path):
        self.saves = Path(saves)
        self.backups = Path(backups)
        self.saves.mkdir(parents=True, exist_ok=True)
        self.backups.mkdir(parents=True, exist_ok=True)

    def slot_path(self, slot: int) -> Path:
        if not 1 <= slot <= MAX_SLOTS:
            raise ValueError(f"Slot must be 1-{MAX_SLOTS}")
        return self.saves / f"slot_{slot}.db"

    def backup_dir(self, slot: int) -> Path:
        d = self.backups / f"slot_{slot}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def verify(path: Path) -> bool:
        if not path.exists() or path.stat().st_size == 0:
            return False
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                ok = con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                has_profile = con.execute(
                    "SELECT count(*) FROM sqlite_master WHERE name='profile'").fetchone()[0] == 1
                return ok and has_profile
            finally:
                con.close()
        except sqlite3.DatabaseError:
            return False

    def slot_summary(self, slot: int) -> dict | None:
        p = self.slot_path(slot)
        if not p.exists():
            return None
        info = {"slot": slot, "path": str(p), "ok": False}
        try:
            con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            try:
                row = con.execute("SELECT name, level, xp, org_id, track, updated_at FROM profile").fetchone()
                if row:
                    info.update(dict(row))
                    info["ok"] = True
            finally:
                con.close()
        except sqlite3.DatabaseError as exc:
            info["error"] = str(exc)
        return info

    def list_slots(self) -> list[dict | None]:
        return [self.slot_summary(s) for s in range(1, MAX_SLOTS + 1)]

    def first_free_slot(self) -> int | None:
        for s in range(1, MAX_SLOTS + 1):
            if not self.slot_path(s).exists():
                return s
        return None

    def backup(self, db: Database, slot: int, reason: str = "manual") -> Path:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        safe_reason = "".join(ch for ch in reason if ch.isalnum() or ch in "-_")[:24] or "backup"
        dest = self.backup_dir(slot) / f"{ts}_{safe_reason}.db"
        target = sqlite3.connect(str(dest))
        try:
            db.conn.backup(target)
        finally:
            target.close()
        self._rotate(slot)
        return dest

    def _rotate(self, slot: int) -> None:
        files = sorted(self.backup_dir(slot).glob("*.db"))
        auto = [f for f in files if "manual" not in f.name and "pre-restore" not in f.name]
        for f in auto[:-KEEP_BACKUPS]:
            f.unlink(missing_ok=True)

    def list_backups(self, slot: int) -> list[dict]:
        out = []
        for f in sorted(self.backup_dir(slot).glob("*.db"), reverse=True):
            out.append({"path": str(f), "name": f.name, "size": f.stat().st_size,
                        "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
                        "valid": self.verify(f)})
        return out

    def restore(self, slot: int, backup_path: Path | str, current: Database | None = None) -> Path:
        """Replace the slot with a backup. Returns the safety backup path (if any)."""
        src = Path(backup_path)
        if not self.verify(src):
            raise SaveCorrupt(f"Backup {src.name} failed integrity check; not restored.")
        dest = self.slot_path(slot)
        safety = None
        if current is not None:
            safety = self.backup(current, slot, "pre-restore")
            current.close()
        elif dest.exists() and self.verify(dest):
            ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            safety = self.backup_dir(slot) / f"{ts}_pre-restore.db"
            shutil.copy2(dest, safety)
        for suffix in ("-wal", "-shm"):
            Path(str(dest) + suffix).unlink(missing_ok=True)
        tmp = dest.with_suffix(".restoring")
        shutil.copy2(src, tmp)
        tmp.replace(dest)  # atomic on the same volume
        return safety or dest

    def open_with_recovery(self, slot: int) -> tuple[Database, str | None]:
        """Open a slot; if it is corrupt, fall back to the newest valid backup."""
        path = self.slot_path(slot)
        try:
            return open_database(path), None
        except (SaveCorrupt, sqlite3.DatabaseError):
            for b in self.list_backups(slot):
                if b["valid"]:
                    corrupt = path.with_name(path.stem + f".corrupt-{datetime.now():%Y%m%d%H%M%S}.db")
                    if path.exists():
                        shutil.move(str(path), corrupt)
                    for suffix in ("-wal", "-shm"):
                        Path(str(path) + suffix).unlink(missing_ok=True)
                    shutil.copy2(b["path"], path)
                    return open_database(path), b["name"]
            raise

    def delete_slot(self, slot: int, confirm: str) -> None:
        """Delete a career. `confirm` must equal 'DELETE' (explicit confirmation)."""
        if confirm != "DELETE":
            raise PermissionError("Deletion requires explicit confirmation")
        p = self.slot_path(slot)
        for f in (p, Path(str(p) + "-wal"), Path(str(p) + "-shm")):
            f.unlink(missing_ok=True)
