# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


PROJECT_ROOT = Path(SPECPATH).resolve()
ENGINE_ROOT = Path(
    os.environ.get(
        "GFCI_ANALYSIS_ROOT",
        PROJECT_ROOT.parent / "gfci_analysis_refactored",
    )
).resolve()
ENGINE_PACKAGE = ENGINE_ROOT / "gfci_analysis"

if not (ENGINE_PACKAGE / "__init__.py").is_file():
    raise SystemExit(
        f"gfci_analysis package not found at {ENGINE_PACKAGE}. "
        "Set GFCI_ANALYSIS_ROOT to the directory containing gfci_analysis."
    )

# Hook collection imports the package, so make the sibling engine visible first.
sys.path.insert(0, str(ENGINE_ROOT))
hiddenimports = sorted(collect_submodules("gfci_analysis"))

APP_NAME = os.environ.get("GFCI_APP_NAME", "TorchDragon")
DEFAULT_ICON = PROJECT_ROOT / "assets" / "torchdragon.ico"
APP_ICON = os.environ.get("GFCI_APP_ICON")
if APP_ICON:
    APP_ICON = str(Path(APP_ICON).expanduser().resolve())
    if not Path(APP_ICON).is_file():
        raise SystemExit(f"Application icon not found: {APP_ICON}")
elif sys.platform == "win32" and DEFAULT_ICON.is_file():
    APP_ICON = str(DEFAULT_ICON)

if sys.platform == "darwin" and (
    not APP_ICON or Path(APP_ICON).suffix.lower() != ".icns"
):
    raise SystemExit(
        "macOS requires an .icns application icon. "
        "Build through scripts/build_app.py so assets/torchdragon.ico "
        "is converted automatically."
    )

app_datas = []
if DEFAULT_ICON.is_file():
    app_datas.append((str(DEFAULT_ICON), "assets"))

# Windows version resource. Embedding company/product/version metadata makes the
# executable look like a legitimate application and reduces the chance of
# SmartScreen / antivirus heuristics flagging it as suspicious.
APP_VERSION = os.environ.get("GFCI_APP_VERSION", "0.0.3.2")
APP_PUBLISHER = os.environ.get("GFCI_APP_PUBLISHER", "GFCI")
_version_parts = [p for p in APP_VERSION.split(".") if p.isdigit()]
while len(_version_parts) < 4:
    _version_parts.append("0")
_version_tuple = tuple(int(p) for p in _version_parts[:4])

VERSION_FILE = PROJECT_ROOT / "build" / "version_info.txt"
VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
VERSION_FILE.write_text(
    "\n".join(
        [
            "VSVersionInfo(",
            "  ffi=FixedFileInfo(",
            f"    filevers={_version_tuple},",
            f"    prodvers={_version_tuple},",
            "    mask=0x3f,",
            "    flags=0x0,",
            "    OS=0x40004,",
            "    fileType=0x1,",
            "    subtype=0x0,",
            "    date=(0, 0),",
            "  ),",
            "  kids=[",
            "    StringFileInfo([",
            "      StringTable(",
            "        u'040904B0',",
            "        [StringStruct(u'CompanyName', u'%s')," % APP_PUBLISHER,
            "         StringStruct(u'FileDescription', u'GFCI Oscilloscope Data Analysis Tool'),",
            "         StringStruct(u'FileVersion', u'%s')," % APP_VERSION,
            "         StringStruct(u'InternalName', u'gfci_gui'),",
            "         StringStruct(u'OriginalFilename', u'%s.exe')," % APP_NAME,
            "         StringStruct(u'ProductName', u'%s')," % APP_NAME,
            "         StringStruct(u'ProductVersion', u'%s')])" % APP_VERSION,
            "    ]),",
            "    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])",
            "  ]",
            ")",
        ]
    ),
    encoding="utf-8",
)


analysis = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT), str(ENGINE_ROOT)],
    binaries=[],
    datas=app_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={
        "matplotlib": {"backends": ["Agg"]},
    },
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

if sys.platform == "darwin":
    exe = EXE(
        pyz,
        analysis.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=os.environ.get("MACOS_CODESIGN_IDENTITY") or None,
        entitlements_file=os.environ.get("MACOS_ENTITLEMENTS") or None,
    )
    collection = COLLECT(
        exe,
        analysis.binaries,
        analysis.datas,
        strip=False,
        upx=False,
        name=APP_NAME,
    )
    app = BUNDLE(
        collection,
        name=f"{APP_NAME}.app",
        icon=APP_ICON,
        bundle_identifier=os.environ.get(
            "MACOS_BUNDLE_IDENTIFIER",
            "com.gfci.analyzer",
        ),
        info_plist={
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": "0.0.3.2",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
elif sys.platform == "win32":
    exe = EXE(
        pyz,
        analysis.scripts,
        analysis.binaries,
        analysis.datas,
        [],
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=APP_ICON,
        version=str(VERSION_FILE),
    )
else:
    raise SystemExit("This spec supports macOS and Windows only.")
