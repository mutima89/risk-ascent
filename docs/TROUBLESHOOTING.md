# Troubleshooting

## "Windows protected your PC" (SmartScreen)

Risk Ascent 1.0.0 is **not code-signed**, so SmartScreen shows this warning for new downloads. If you downloaded it from this repository's Releases page, click **More info → Run anyway**. You can check the download against the SHA-256 checksums on the release page:

```powershell
Get-FileHash .\RiskAscent_Setup.exe -Algorithm SHA256
```

Some antivirus products flag PyInstaller-built executables in general. If yours quarantines the game, restore it and add an exception, or build it yourself from source (see the README).

## The installer asks for administrator rights

It shouldn't. It installs per user into `%LOCALAPPDATA%\Programs\RiskAscent`. If your organisation blocks running programs from `AppData`, use the portable `RiskAscent.exe` from an allowed folder, or ask your IT team.

## The portable exe is slow to start

The single-file `RiskAscent.exe` unpacks itself to a temporary folder on every start, which takes a few seconds (longer while antivirus scans it). The installed version starts faster.

## It doesn't start, or closes immediately

1. Look at the log: `%LOCALAPPDATA%\RiskAscent\logs\riskascent.log`.
2. Run the self-test from a command prompt:
   ```
   "%LOCALAPPDATA%\Programs\RiskAscent\RiskAscent.exe" --self-test --self-test-report "%USERPROFILE%\Desktop\ra_selftest.txt"
   ```
   It writes a pass/fail report for each check.
3. "Game content failed validation" means the bundled content was modified. Reinstall.
4. Windows 10 builds older than 1809 are not supported by Qt 6.

## Blank window, flicker or graphics glitches

This usually means a graphics driver or remote-desktop problem. Try software rendering:

```
set QT_OPENGL=software
RiskAscent.exe
```

## Text is too small or too large

Use **Ctrl + =** / **Ctrl + −** (or **Ctrl + 0** to reset), or **Settings → Text size**. The game also follows Windows display scaling.

## Read-aloud does nothing

Turn it on in **Settings → Narration**. It uses the speech voices installed in Windows (**Settings → Time & language → Speech**). If no speech engine is available, the game shows a short notice instead.

## My save says it was recovered from a backup

The save file failed its integrity check, so the game restored the newest valid backup and kept the damaged file as `slot_N.corrupt-*.db`. See [BACKUP_AND_RECOVERY.md](BACKUP_AND_RECOVERY.md).

## "Save was created by a newer version"

You opened a save with an older copy of the game. Install the latest version. The save has not been changed.

## Reports look plainer in the app than in a browser

The in-app preview and the PDF export use Qt's rich-text engine, which supports less CSS. The saved `.html` report (**Open reports folder**) is the full-fidelity version.

## Reporting a bug

Open an issue with the steps to reproduce it, your Windows version, and the end of `riskascent.log`. The log contains no personal data beyond your in-game display name.
