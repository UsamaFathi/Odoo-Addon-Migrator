from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def capture_ui(app, output: Path) -> bool:
    """Render the Project page through the active Qt platform and save it."""
    from PySide6.QtCore import QSettings

    from odoo_migrator.ui.main_window import MainWindow
    from odoo_migrator.ui.settings import DesktopSettings

    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="odoo-migrator-ui-capture-") as temporary:
        settings = DesktopSettings(QSettings(str(Path(temporary) / "capture.ini"), QSettings.IniFormat))
        window = MainWindow(settings=settings)
        window.resize(1366, 768)
        window.show()
        app.processEvents()
        window.repaint()
        app.processEvents()
        screen = window.screen() or app.primaryScreen()
        pixmap = screen.grabWindow(int(window.winId())) if screen else window.grab()
        if pixmap.isNull():
            pixmap = window.grab()
        saved = pixmap.save(str(output), "PNG")
        window.close()
        app.processEvents()
        return saved


def main(argv: list[str] | None = None) -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise SystemExit('Desktop dependency missing. Install with: pip install -e ".[desktop]"') from exc

    from odoo_migrator import __version__
    if argv is None:
        argv = sys.argv[1:]
    if "--version" in argv:
        print(__version__)
        return 0
    app = QApplication([sys.argv[0], *argv])
    if "--smoke-test" in argv:
        from odoo_migrator.ui.main_window import MainWindow
        window = MainWindow()
        window.close()
        return 0
    if "--capture-ui" in argv:
        output = Path(os.environ.get("ODOO_MIGRATOR_UI_CAPTURE", "OdooAddonMigrator-Project-1366x768.png"))
        if not capture_ui(app, output):
            print(f"Unable to save UI capture: {output}", file=sys.stderr)
            return 1
        print(str(output.resolve()))
        return 0
    from odoo_migrator.ui.main_window import MainWindow
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
