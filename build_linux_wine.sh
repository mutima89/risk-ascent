#!/usr/bin/env bash
# Cross-builds the Windows exe and installer from Linux using Wine + Windows Python 3.12
# (how the 1.0.0 release was produced). Expects WINEPREFIX to contain C:\Python312 with
# requirements-dev.txt installed, plus makensis, xvfb-run and script on the host.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="${OUT:-$ROOT/dist}"
export WINEDEBUG=-all
WPY() { script -qec "wine C:\\\\Python312\\\\python.exe $(printf '%q ' "$@")" /dev/null; }
W() { winepath -w "$1"; }
mkdir -p "$OUT"
WPY -m PyInstaller --noconfirm --clean --distpath "$(W "$OUT")" --workpath "$(W "$ROOT/build/work")" "$(W "$ROOT/packaging/RiskAscent.spec")"
RA_ONEFILE=1 WPY -m PyInstaller --noconfirm --distpath "$(W "$OUT")" --workpath "$(W "$ROOT/build/work1")" "$(W "$ROOT/packaging/RiskAscent.spec")"
makensis -V2 -DSRCDIR="$OUT/RiskAscent" -DOUTFILE="$OUT/RiskAscent_Setup.exe" "$ROOT/packaging/RiskAscent.nsi"
mkdir -p "$ROOT/build/wine-selftest"
xvfb-run -a script -qec "wine $(printf '%q' "$OUT/RiskAscent.exe") --self-test --data-dir $(printf '%q' "$(W "$ROOT/build/wine-selftest")") --self-test-report $(printf '%q' "$(W "$ROOT/build/wine-selftest/report.txt")") -platform offscreen" /dev/null || true
cat "$ROOT/build/wine-selftest/report.txt"
(cd "$OUT" && sha256sum RiskAscent.exe RiskAscent_Setup.exe)
