"""Save files: migrations, transactions, backups, restore and corruption recovery."""

from __future__ import annotations

import sqlite3

import pytest

from riskascent.game import Game
from riskascent.persistence.db import SCHEMA_VERSION, Database, SaveCorrupt, open_database


def test_fresh_database_migrates_to_latest(tmp_path):
    db = open_database(tmp_path / "x.db")
    assert db.version == SCHEMA_VERSION
    assert db.integrity_ok()
    assert db.migrate() == []  # idempotent
    db.close()


def test_old_schema_upgrades_in_place(tmp_path):
    db = Database(tmp_path / "old.db")
    db.migrate(target=1)
    assert db.version == 1
    db.close()
    db = open_database(tmp_path / "old.db")
    assert db.version == SCHEMA_VERSION
    db.close()


def test_newer_save_is_refused(tmp_path):
    con = sqlite3.connect(tmp_path / "new.db")
    con.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 5}")
    con.close()
    with pytest.raises(SaveCorrupt):
        open_database(tmp_path / "new.db")


def test_transaction_rolls_back_on_error(game):
    before = len(game.list_risks())
    with pytest.raises(RuntimeError):
        with game.db.tx():
            game.db.ex("DELETE FROM risks")
            raise RuntimeError("simulated crash mid-save")
    assert len(game.list_risks()) == before


def test_backup_and_restore(game, saves, content):
    xp0 = game.profile["xp"]
    b = game.backup("manual")
    assert saves.verify(b)
    game.db.ex("UPDATE profile SET xp = xp + 999")
    game.close()
    safety = saves.restore(1, b)
    assert safety.exists()
    g2 = Game(content, open_database(saves.slot_path(1)), saves, 1)
    assert g2.profile["xp"] == xp0
    g2.close()


def test_restore_refuses_invalid_backup(game, saves, tmp_path):
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not a database")
    with pytest.raises(SaveCorrupt):
        saves.restore(1, bad, current=game.db)


def test_corrupt_save_recovers_from_newest_valid_backup(game, saves):
    game.backup("after-mission")
    game.close()
    path = saves.slot_path(1)
    for suffix in ("-wal", "-shm"):
        p = path.with_name(path.name + suffix)
        if p.exists():
            p.unlink()
    path.write_bytes(b"\x00garbage" * 500)
    db, recovered = saves.open_with_recovery(1)
    assert recovered and db.integrity_ok()
    assert db.one("SELECT name FROM profile")["name"] == "Tester"
    assert list(path.parent.glob("slot_1.corrupt-*.db")), "corrupt file should be kept for inspection"
    db.close()


def test_backups_rotate_but_keep_manual(game, saves):
    from riskascent.persistence.saves import KEEP_BACKUPS
    game.backup("manual")
    for _ in range(KEEP_BACKUPS + 4):
        game.backup("auto")
    names = [b["name"] for b in saves.list_backups(1)]
    assert sum("manual" in n for n in names) == 1
    assert sum("auto" in n for n in names) == KEEP_BACKUPS


def test_delete_and_reset_need_explicit_confirmation(game, saves):
    with pytest.raises(PermissionError):
        saves.delete_slot(1, "yes")
    with pytest.raises(PermissionError):
        game.reset_career("reset")
    assert saves.slot_path(1).exists()
    game.reset_career("RESET")
    assert not saves.slot_path(1).exists()
    assert any("pre-reset" in b["name"] for b in saves.list_backups(1)), "reset keeps a backup"


def test_new_career_validates_input(content, saves):
    with pytest.raises(ValueError):
        Game.new_career(content, saves, 2, "", "meridian", "erm")
    with pytest.raises(ValueError):
        Game.new_career(content, saves, 2, "x" * 41, "meridian", "erm")
    with pytest.raises(ValueError):
        Game.new_career(content, saves, 2, "Ok", "nope", "erm")


def test_register_validation_rejects_bad_input(game):
    r = dict(game.list_risks()[0])
    r["title"] = ""
    assert game.validate_risk(r)
    r = dict(game.list_risks()[0], inh_l=9)
    assert game.validate_risk(r)
