# Test report: Risk Ascent 1.0.0

Date: 20 October 2026. This report says exactly what was run, where, and what was not.

## Summary

| Test | Environment | Result |
|---|---|---|
| Automated suite, 67 tests | Linux, Python 3.12, PySide6 6.12 (offscreen Qt) | **67 passed**, 0 failed (42 s) |
| Automated suite without UI tests | **Windows** Python 3.12 (CPython for Windows, same pinned packages) under **Wine** | **60 passed**, 0 failed. 2 save tests deselected (see below); 5 UI tests not run (see below). |
| Built-in `--self-test` (10 checks) from source | Linux | **10/10 passed** |
| Packaged folder build `dist\RiskAscent\RiskAscent.exe --self-test` | Wine, offscreen Qt | **10/10 passed** |
| Packaged single-file `RiskAscent.exe --self-test` | Wine, offscreen Qt | **10/10 passed** |
| `RiskAscent_Setup.exe /S` silent install | Wine | Passed: files in `%LOCALAPPDATA%\Programs\RiskAscent`, Start-menu and desktop shortcuts, HKCU uninstall entry, no elevation |
| Installed exe `--self-test` | Wine | **10/10 passed** |
| Installed exe normal launch | Wine | Started, created `%LOCALAPPDATA%\RiskAscent\{saves,backups,logs}`, ran until closed |
| Silent uninstall | Wine | Passed: program files, shortcuts and registry entry removed; saves kept (by design) |
| Visual review | Linux screenshots of all 23 screens, light theme at 130% text, focus mode | Reviewed by eye; layout issues found and fixed (listed below) |

**Not performed:** no testing on a physical Windows 10 or 11 PC, no clean-machine verification, no screen-reader testing, and no testing with real speech voices. The repository's GitHub Actions workflow (`.github/workflows/windows-build.yml`) runs the full suite, builds, self-tests, and installs and uninstalls on GitHub's `windows-latest` runners. Check the Actions tab for those results. They are not included in this report.

## Automated suite (`pytest`)

| File | Tests | Covers |
|---|---|---|
| `test_engines.py` | 25 | Risk matrix scoring, bands, probability and amount mapping, resizing; residual validation; controls do not stack; appetite and prioritisation; expected loss, scenario loss, NPV, cost-benefit (hand-checked figures); Monte Carlo reproducibility, percentile order, P(any loss) against the Poisson formula; lognormal fit; tornado; stress test runway and covenant month; KRI thresholds both directions and trend; control design and operating tests; BIA RTO/MTPD and dependency checks; spaced-repetition schedule; calibration; seeded crisis exercise; the safe formula evaluator rejecting code; seeds and money formatting; knapsack optimum |
| `test_content.py` | 7 | Content validates with zero problems; at least 30 missions (67), 100 decision points (281), 50 achievements (81), 3 organisations (9); 10 levels, 10 tracks, 7 executive paths, 12 crises, 8 industries; hotel and Saudi/SAR packs present; every scored option has feedback; salaries labelled illustrative; validator rejects a broken mission; every achievement has a known, checkable condition type |
| `test_saves.py` | 11 | Fresh database migrates to the latest schema; an old schema upgrades in place; a newer schema is refused; a transaction rolls back on a simulated crash; backup → modify → restore; an invalid backup is refused; a corrupt save auto-recovers from the newest valid backup and is kept for inspection; backup rotation keeps manual backups; delete and reset need exact confirmation and reset leaves a backup; input validation for new careers and register entries |
| `test_campaign.py` | 6 | **Mission → close → reopen keeps XP, scores, period, register and achievements**; a half-finished mission resumes at the same step with the same answers after restart; weak choices score lower; the same seed gives an identical world; the Saudi organisation uses SAR; **a full campaign from level 1 to CRO** (all required missions, 9 promotions with interviews, the board simulation, all 7 executive paths, at least 40 achievements, then New Game Plus) |
| `test_reports.py` | 11 | All 8 report types generate from live data with no scripts; top-risk report matches the prioritised register; the investment report requires inputs; register CSV export |
| `test_offline.py` | 2 | Source scan: no network modules (`socket`, `urllib.request`, `http.client`, `requests`, `QtNetwork`, ...), no `eval`/`exec`/`__import__`; data stays in the data folder |
| `test_ui.py` | 5 | pytest-qt: the full built-in self-test passes; **no dead buttons**: every visible, enabled button on every screen (and the title screen) has a handler connected; reset is refused without the typed confirmation; keyboard shortcuts (Ctrl+1, F6, Esc) work |

Raw output is in [`docs/test-results/`](test-results/): `pytest_output.txt`, `test-results.xml` (JUnit), `test-results-windows-python.xml`, and the packaged and installed self-test reports.

### Notes on the Windows-Python (Wine) run

- `test_backup_and_restore` and `test_corrupt_save_recovers_from_newest_valid_backup` were deselected. Python 3.12's `shutil.copy2` on Windows calls the Win32 `CopyFile2` API, which Wine does not implement, so Wine aborts. Real Windows 8 and later provide `CopyFile2`. Both tests pass on Linux, and the CI workflow runs them on real Windows.
- The 5 pytest-qt UI tests stalled under Wine's Qt event loop and were not run there. The packaged exe's `--self-test` covers the same user flows under Wine and passed.

## Built-in self-test (`RiskAscent.exe --self-test`)

This drives the real interface in a throwaway data folder and writes a report. Result for the packaged single-file exe under Wine:

```
Risk Ascent self-test: PASS
[PASS] Content loads and validates: 67 missions, 281 decision points, 81 achievements, 9 organisations
[PASS] Create a new career
[PASS] Open every screen: 23 screens opened (including title and mission briefing)
[PASS] Play a mission through the UI: M01 completed through the UI with score 1.00, XP 120
[PASS] Progress survives close and reopen: best scores {'M01': 1.0}, XP 120 preserved; 3 backups
[PASS] Half-finished mission resumes after restart: M02 resumed at decision 3 after restart and completed (1.00)
[PASS] Reports generate and export: HTML report generated, PDF 192949 bytes, register CSV written
[PASS] Financial models run: Monte Carlo mean 630,925, P99 6,940,803; CBA NPV 605,068
[PASS] Workspace tools: register edit, KRI escalation, crisis exercise (0.53), month advanced to 3
[PASS] Accessibility settings apply: light theme, 130% text and focus mode applied
```

The self-test's screenshots under Wine show no text glyphs. Wine's offscreen Qt platform has no font backend, and Wine's native Windows platform could not be used (it lacks `mscms.dll!WcsCreateIccProfile`). This affects only that test harness. Readable screenshots in `docs/screenshots/` come from the Linux run.

## Defects found by testing and fixed before release

| Found by | Defect | Fix |
|---|---|---|
| Packaged self-test (Wine) | Financial lab crashed in the exe: matplotlib → pyparsing needs `unittest`, which the spec excluded | Removed it from the PyInstaller excludes |
| UI test (keyboard) | F6 and Ctrl+Enter were bound twice (button shortcut + window shortcut), so Qt treated them as ambiguous and did nothing | One shortcut per key; Ctrl+Enter dispatches by mission phase |
| UI test | A deferred layout timer could fire after a dialog's page was deleted | Timer is now owned by the page |
| Screenshot review | Report preview unreadable in dark theme; report tiles collapsed in Qt rich text | Preview renders on white "paper"; tiles use a table |
| Screenshot review | Cards beside taller cards centred their content vertically; settings page scrolled sideways | Cards top-align; long path shown in a read-only field; wide controls constrained |
| Screenshot review | Department budget table squashed the objective column | Text columns share the width |
| Offline scan | `__import__` used to read the version | Normal import |
| Earlier engine work | Migrations committed early because `executescript` ends the transaction; stale salary cache on a new career; unseeded rank shuffle; Qt method names shadowed by attributes | Each fixed, with tests where applicable |

## How to reproduce

```bash
pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen python -m pytest -v          # Windows: set QT_QPA_PLATFORM=offscreen
python RiskAscent.py --self-test                       # or RiskAscent.exe --self-test
```
