# PyInstaller onedir build for the Windows desktop application.
from pathlib import Path
import os

ROOT = Path(SPECPATH).parent
VERSION_FILE = os.environ.get("ODOO_MIGRATOR_VERSION_FILE")
hiddenimports = ["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"]
a = Analysis(
    [str(ROOT / "src/odoo_migrator/ui/app.py")], pathex=[str(ROOT / "src")], binaries=[], datas=[],
    hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["pytest", "tests"], noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], [], [], name="OdooAddonMigrator",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, version=VERSION_FILE)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="OdooAddonMigrator")
