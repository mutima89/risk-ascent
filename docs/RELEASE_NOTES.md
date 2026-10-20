# Release notes

## 1.0.0 (2026-10-20)

First release.

**Game**
- 10-level career from Graduate Trainee to Chief Risk Officer, management/expert paths, and 7 executive paths after the CRO board simulation; New Game Plus.
- 10 career tracks and 9 organisations in 8 industries, including a hotel pack and a Saudi Arabia pack (SAR).
- 67 missions (30 career, 12 crisis, 12 side, 6 capstones, 7 executive) with 281 decision points across 8 step types.
- A living organisation: monthly simulation of cash, reputation, compliance, controls, resilience, morale and exposure; delayed consequences; stakeholder trust.
- Judgement-versus-luck scoring with seeded, replayable outcomes.
- Working tools: risk register, assessment workbench (configurable 3×3 to 5×5 matrix and appetite), control testing and findings, BIA, KRI monitor, financial lab (Monte Carlo, cost-benefit, tornado, stress test), budget and investments, 8 report types (HTML, PDF, CSV), and an escalating crisis exercise.
- XP, a 5-branch skill tree, 11 competencies, 81 achievements, promotion interviews, salary negotiation (illustrative figures), performance reviews.
- Learning: spaced retrieval, confidence calibration, worked examples, hints, adaptive scaffolding, 3 difficulty levels.
- Accessibility: light/dark/high-contrast themes, text scaling, focus mode, reduced motion, session timer, read-aloud, keyboard shortcuts.

**Engineering**
- SQLite saves with migrations, transactions, step checkpoints, automatic and manual backups, integrity checks and automatic recovery.
- Fully offline: no network code, telemetry, accounts or API keys.
- `--self-test`, `--data-dir`, `--version` command-line options.
- 67 automated tests; Windows build workflow for GitHub Actions.

**Fixed before release (found by Windows CI)**
- Recovery of a damaged save could not move the file aside on Windows.
- A notification timer could fire after the window closed.

**Known limitations**
- The executables are not code-signed.
- Tested automatically on GitHub's Windows runners (tests, packaged self-test, install and uninstall), but not hands-on on a physical Windows 10/11 PC or a clean consumer machine. See [TEST_REPORT.md](TEST_REPORT.md).
- Written answers are checked by local keyword matching, not by an AI model.
- The organisation's "exposure index" assumes a 5×5 matrix, so on smaller matrices it is approximate.
- The in-app report preview and PDF use simplified styling. The HTML export is full fidelity.
