; Risk Ascent per-user installer (NSIS 3). No administrator rights are needed:
; the game installs to %LOCALAPPDATA%\Programs\RiskAscent and registers its
; uninstaller under HKCU. Saves live separately in %LOCALAPPDATA%\RiskAscent
; and are kept on uninstall unless the player ticks the box to remove them.
;
; Build:  makensis /DSRCDIR=<path to dist\RiskAscent> /DOUTFILE=<path\RiskAscent_Setup.exe> RiskAscent.nsi

Unicode true
!include "MUI2.nsh"
!include "FileFunc.nsh"

!define APPNAME "Risk Ascent"
!define APPID "RiskAscent"
!define VERSION "1.0.0"
!ifndef SRCDIR
  !define SRCDIR "..\dist\RiskAscent"
!endif
!ifndef OUTFILE
  !define OUTFILE "..\dist\RiskAscent_Setup.exe"
!endif
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}"

Name "${APPNAME}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\${APPID}"
InstallDirRegKey HKCU "Software\${APPID}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
ShowInstDetails show
BrandingText "${APPNAME} ${VERSION}"

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APPNAME}"
VIAddVersionKey "FileDescription" "${APPNAME} installer"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "Risk Ascent"

!define MUI_ICON "RiskAscent.ico"
!define MUI_UNICON "RiskAscent.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\RiskAscent.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Start Risk Ascent"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_COMPONENTS
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "Risk Ascent (required)" SecMain
  SectionIn RO
  ; Replace any previous version cleanly; saves are elsewhere and untouched.
  RMDir /r "$INSTDIR\_internal"
  SetOutPath "$INSTDIR"
  File /r "${SRCDIR}\*.*"
  File "RiskAscent.ico"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortcut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\RiskAscent.exe" "" "$INSTDIR\RiskAscent.ico"
  CreateShortcut "$SMPROGRAMS\${APPNAME}\Uninstall ${APPNAME}.lnk" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\${APPID}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINSTKEY}" "Publisher" "Risk Ascent"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayIcon" "$INSTDIR\RiskAscent.ico"
  WriteRegStr HKCU "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTKEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegDWORD HKCU "${UNINSTKEY}" "EstimatedSize" $0
SectionEnd

Section "Desktop shortcut" SecDesktop
  CreateShortcut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\RiskAscent.exe" "" "$INSTDIR\RiskAscent.ico"
SectionEnd

Section "un.Risk Ascent program files" UnSecMain
  SectionIn RO
  Delete "$DESKTOP\${APPNAME}.lnk"
  RMDir /r "$SMPROGRAMS\${APPNAME}"
  RMDir /r "$INSTDIR\_internal"
  Delete "$INSTDIR\RiskAscent.exe"
  Delete "$INSTDIR\RiskAscent.ico"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNINSTKEY}"
  DeleteRegKey HKCU "Software\${APPID}"
SectionEnd

Section /o "un.Also delete my saves, backups and settings" UnSecData
  RMDir /r "$LOCALAPPDATA\${APPID}"
SectionEnd

LangString DESC_Main ${LANG_ENGLISH} "The game itself."
LangString DESC_Desktop ${LANG_ENGLISH} "Put a Risk Ascent shortcut on the desktop."
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} $(DESC_Main)
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} $(DESC_Desktop)
!insertmacro MUI_FUNCTION_DESCRIPTION_END
