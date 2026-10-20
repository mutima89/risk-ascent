# PyInstaller spec for Risk Ascent.
#   pyinstaller packaging/RiskAscent.spec                 -> dist/RiskAscent/ (folder build, used by the installer)
#   set RA_ONEFILE=1 && pyinstaller packaging/RiskAscent.spec -> dist/RiskAscent.exe (single portable exe)
import os
from pathlib import Path

ROOT = Path(SPECPATH).parent
ONEFILE = os.environ.get("RA_ONEFILE") == "1"

datas = [(str(ROOT / "riskascent" / "content"), "riskascent/content"),
         (str(ROOT / "riskascent" / "assets"), "riskascent/assets")]

hidden = ["PySide6.QtSvg", "PySide6.QtPrintSupport", "PySide6.QtTextToSpeech",
          "matplotlib.backends.backend_qtagg"]

excludes = ["tkinter", "_tkinter", "pydoc_data", "test", "pytest", "pytestqt",
            "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
            "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtNetwork", "PySide6.QtQml",
            "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
            "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtBluetooth",
            "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSql", "PySide6.QtTest",
            "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtPdf",
            "PySide6.QtSerialPort", "PySide6.QtSensors", "PySide6.QtNfc", "PySide6.QtRemoteObjects",
            "PySide6.QtScxml", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtOpenGL",
            "PySide6.QtOpenGLWidgets", "PySide6.QtSpatialAudio", "PySide6.QtHttpServer",
            "matplotlib.backends.backend_tkagg", "matplotlib.backends.backend_wx",
            "matplotlib.backends.backend_gtk3agg", "matplotlib.backends.backend_webagg"]

a = Analysis([str(ROOT / "RiskAscent.py")], pathex=[str(ROOT)], datas=datas, hiddenimports=hidden,
             excludes=excludes, noarchive=False)

# Never ship test-only DLL shims that may exist in a build machine's Python folder.
SHIMS = {"icuuc.dll", "ucrtbase.dll"}
a.binaries = [b for b in a.binaries if Path(b[0]).name.lower() not in SHIMS]

pyz = PYZ(a.pure)
common = dict(name="RiskAscent", icon=str(ROOT / "packaging" / "RiskAscent.ico"),
              version=str(ROOT / "packaging" / "version_info.txt"), console=False, upx=False,
              debug=False, strip=False)

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], runtime_tmpdir=None, **common)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="RiskAscent")
