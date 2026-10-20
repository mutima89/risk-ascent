# Backup and recovery

Risk Ascent keeps everything on your PC, in one folder:

```
%LOCALAPPDATA%\RiskAscent\          (paste this into the Explorer address bar)
  saves\slot_1.db … slot_5.db       one SQLite database per career
  backups\slot_N\*.db               backups for that slot
  reports\                          generated reports (HTML)
  logs\riskascent.log               local log (rotates at 2 MB)
  settings.json                     display and accessibility settings
```

You can open the folder from **Settings & accessibility → Privacy and data → Open data folder**.

## How saving works

- Every action (a decision, a register edit, a month advancing) is written straight away inside a database transaction. A crash or power cut cannot leave a half-written save: the change is either fully there or not there at all. The database uses SQLite's write-ahead log with `synchronous=FULL`.
- A half-finished mission is checkpointed after every step and resumes at the same step, with the same answers, after a restart.
- **Automatic backups** are taken after every completed mission, after every promotion, when a session ends, and before a restore or reset. The newest 15 automatic backups per slot are kept. **Manual backups and pre-restore safety copies are never deleted automatically.**
- Older saves are upgraded in place when a newer version first opens them (schema migrations run inside a transaction). A save from a *newer* version than the one you're running is refused rather than damaged.

## Make a backup

- In the game: **Saves & recovery → Back up now**, or press **Ctrl + B** anywhere.
- **Export a copy** saves a standalone `.db` file wherever you choose (a USB stick, OneDrive and so on).
- Outside the game: close Risk Ascent and copy the whole `%LOCALAPPDATA%\RiskAscent` folder.

## Restore a backup

1. Open **Saves & recovery**.
2. Choose a backup in *Backups for this slot*. The *Valid* column shows the result of an integrity check.
3. Press **Restore selected backup** and confirm.

Before restoring, the game takes a *pre-restore* safety copy of your current save, so a restore can always be undone. Backups that fail the integrity check are refused.

## Automatic recovery from a damaged save

If a save fails to open (for example after a disk error), the game:

1. moves the damaged file aside as `slot_N.corrupt-<timestamp>.db` (it is kept, not deleted);
2. copies in the newest backup that passes the integrity check;
3. opens it and tells you which backup it used.

You lose at most the progress since that backup, which is usually one mission.

## Move to another PC

Close the game on both PCs and copy `%LOCALAPPDATA%\RiskAscent` from the old PC to the same place on the new one. Or move one career: copy `saves\slot_N.db` (and optionally `backups\slot_N\`) into the same folders on the new PC.

To keep the data somewhere else (for example a portable install on a USB drive), start the game with `RiskAscent.exe --data-dir "E:\RiskAscentData"`.

## Delete or reset

- **Delete a career** (title screen) or **Reset** (Settings): you have to type the confirmation word. A backup is taken first, so even a reset can be restored from `backups\`.
- **Uninstalling** removes the program but **keeps your saves** unless you tick *"Also delete my saves, backups and settings"* in the uninstaller.

## Verify

**Saves & recovery → Verify integrity** runs SQLite's `PRAGMA integrity_check` on the current save. `RiskAscent.exe --self-test` checks the whole game (including close/reopen persistence and mission resume) in a temporary folder without touching your saves.
