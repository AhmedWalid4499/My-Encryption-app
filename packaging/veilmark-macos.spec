# PyInstaller build recipe for the Mac:   pyinstaller packaging/veilmark-macos.spec --noconfirm
# Produces dist/VeilMark.app (double-click app). The command line tool is inside it:
#   VeilMark.app/Contents/MacOS/veilmark-cli
# The app is built for the processor of the Python that runs PyInstaller (Apple silicon or Intel), or for
# VEILMARK_TARGET_ARCH (arm64 / x86_64) when set - CI uses that to build the Intel app under Rosetta.
import os
import re
from pathlib import Path

ROOT = Path(SPECPATH).parent
VERSION = re.search(r'__version__ = "(.+?)"', (ROOT / "veilmark" / "__init__.py").read_text()).group(1)
TARGET_ARCH = os.environ.get("VEILMARK_TARGET_ARCH") or None
EXCLUDES = [
    "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtQuick",
    "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtPdf", "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSql", "PySide6.QtTest",
    "docx", "pptx", "openpyxl", "pytest",
]

a = Analysis(
    [str(ROOT / "run_veilmark.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "assets" / "veilmark.png"), "assets"), (str(ROOT / "assets" / "check.svg"), "assets")],
    hiddenimports=["veilmark.gui.main", "veilmark.cli", "PySide6.QtSvg", "truststore", "certifi"],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)

gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VeilMark", console=False, target_arch=TARGET_ARCH,
          icon=str(ROOT / "assets" / "veilmark.icns"))
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="veilmark-cli", console=True,
          target_arch=TARGET_ARCH)
coll = COLLECT(gui, cli, a.binaries, a.datas, strip=False, upx=False, name="VeilMark")

app = BUNDLE(
    coll,
    name="VeilMark.app",
    icon=str(ROOT / "assets" / "veilmark.icns"),
    bundle_identifier="com.ahmedwalid.veilmark",
    version=VERSION,
    info_plist={
        "CFBundleName": "VeilMark",
        "CFBundleDisplayName": "VeilMark",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHumanReadableCopyright": "© Ahmed Walid",
        "LSApplicationCategoryType": "public.app-category.productivity",
        "LSMinimumSystemVersion": "14.0",
        "NSHighResolutionCapable": True,
        # the app is designed in light colours: keep it light even when the Mac is in Dark Mode
        "NSRequiresAquaSystemAppearance": True,
        # shown when macOS asks for permission to read/save files in these folders
        "NSDocumentsFolderUsageDescription": "VeilMark watermarks, traces and encrypts the files you choose.",
        "NSDesktopFolderUsageDescription": "VeilMark watermarks, traces and encrypts the files you choose.",
        "NSDownloadsFolderUsageDescription": "VeilMark watermarks, traces and encrypts the files you choose.",
        "NSRemovableVolumesUsageDescription": "VeilMark watermarks, traces and encrypts the files you choose.",
        "NSNetworkVolumesUsageDescription": "VeilMark watermarks, traces and encrypts the files you choose.",
    },
)
