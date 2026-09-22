# PyInstaller onedir build for Linux desktop distribution.
from pathlib import Path

ROOT = Path(SPECPATH).parent
hiddenimports = ["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"]
datas = [(str(ROOT / "src/odoo_migrator/ui/assets"), "odoo_migrator/ui/assets")]

a = Analysis(
    [str(ROOT / "src/odoo_migrator/ui/app.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    [],
    [],
    name="OdooAddonMigrator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="OdooAddonMigrator",
)
