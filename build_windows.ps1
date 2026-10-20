# Builds Risk Ascent on Windows 10/11 (64-bit) from source.
#   powershell -ExecutionPolicy Bypass -File build_windows.ps1
# Requires: Python 3.12 (64-bit) on PATH as "py -3.12" or "python", and NSIS 3
# (makensis) on PATH or in its default folder. No administrator rights are needed.
# Output: dist\RiskAscent.exe (portable), dist\RiskAscent\ (folder build),
#         dist\RiskAscent_Setup.exe (per-user installer), build\*.txt test logs.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = if (Get-Command py -ErrorAction SilentlyContinue) { "py -3.12" } else { "python" }
Write-Host "== Creating virtual environment"
Invoke-Expression "$py -m venv .venv"
$vpy = ".\.venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip
& $vpy -m pip install -r requirements-dev.txt

New-Item -ItemType Directory -Force build | Out-Null
Write-Host "== Running automated tests"
$env:QT_QPA_PLATFORM = "offscreen"
& $vpy -m pytest -q --junitxml build\test-results.xml | Tee-Object build\pytest_output.txt
if ($LASTEXITCODE -ne 0) { throw "Tests failed - see build\pytest_output.txt" }
Remove-Item Env:QT_QPA_PLATFORM

Write-Host "== Building folder version (for the installer)"
& $vpy -m PyInstaller --noconfirm --clean --distpath dist --workpath build\work packaging\RiskAscent.spec
Write-Host "== Building single-file RiskAscent.exe"
$env:RA_ONEFILE = "1"
& $vpy -m PyInstaller --noconfirm --distpath dist --workpath build\work1 packaging\RiskAscent.spec
Remove-Item Env:RA_ONEFILE

Write-Host "== Self-test of the packaged exe"
$p = Start-Process -FilePath dist\RiskAscent.exe -ArgumentList "--self-test","--self-test-report","build\selftest_report.txt" -Wait -PassThru
Get-Content build\selftest_report.txt
if ($p.ExitCode -ne 0) { throw "Packaged self-test failed" }

Write-Host "== Building installer"
$makensis = (Get-Command makensis -ErrorAction SilentlyContinue).Source
if (-not $makensis) { $makensis = "${env:ProgramFiles(x86)}\NSIS\makensis.exe" }
& $makensis /DSRCDIR="$PWD\dist\RiskAscent" /DOUTFILE="$PWD\dist\RiskAscent_Setup.exe" packaging\RiskAscent.nsi
if ($LASTEXITCODE -ne 0) { throw "Installer build failed" }

Get-FileHash dist\RiskAscent.exe, dist\RiskAscent_Setup.exe -Algorithm SHA256 | Format-Table -AutoSize | Out-String | Tee-Object build\SHA256SUMS.txt
Write-Host "Done. Note: the executables are not code-signed."
