# PyInstaller build recipe:   pyinstaller packaging/veilmark.spec --noconfirm
# Produces dist/VeilMark/VeilMark.exe (desktop app) and veilmark-cli.exe (command line).
from pathlib import Path

ROOT = Path(SPECPATH).parent
EXCLUDES = [
    "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtQuick",
    "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtPdf", "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSql", "PySide6.QtTest",
    "docx", "pptx", "openpyxl", "pytest",
]

a = Analysis(
    [str(ROOT / "run_veilmark.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "assets" / "veilmark.ico"), "assets"), (str(ROOT / "assets" / "veilmark.png"), "assets"),
           (str(ROOT / "assets" / "check.svg"), "assets")],
    hiddenimports=["veilmark.gui.main", "veilmark.cli"],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)

gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VeilMark", console=False,
          icon=str(ROOT / "assets" / "veilmark.ico"), version=str(ROOT / "packaging" / "version_info.txt"))
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="veilmark-cli", console=True,
          icon=str(ROOT / "assets" / "veilmark.ico"), version=str(ROOT / "packaging" / "version_info.txt"))
coll = COLLECT(gui, cli, a.binaries, a.datas, strip=False, upx=False, name="VeilMark")
