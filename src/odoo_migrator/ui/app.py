from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path


def smoke_test(app) -> bool:
    """Exercise packaged window creation and queued worker-to-GUI delivery."""
    from PySide6.QtCore import QSettings, QThread

    from odoo_migrator.ui.main_window import MainWindow
    from odoo_migrator.ui.settings import DesktopSettings

    completed = []
    gui_callbacks = []
    with tempfile.TemporaryDirectory(prefix="odoo-migrator-smoke-") as temporary:
        settings = DesktopSettings(QSettings(str(Path(temporary) / "smoke.ini"), QSettings.IniFormat))
        window = MainWindow(settings=settings)
        window._show_page(1, 1)
        window.analysis_page.set_progress = lambda _stage, _percent: gui_callbacks.append(QThread.isMainThread())

        def operation(progress=None):
            progress("Checking desktop worker", 50)
            return "ready"

        def success(_token, result):
            gui_callbacks.append(QThread.isMainThread())
            completed.append(result)

        window._start_task("smoke", operation, (), success, lambda _busy: None)
        deadline = time.monotonic() + 10
        while window._busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        passed = completed == ["ready"] and gui_callbacks == [True, True]
        window.close()
        app.processEvents()
        return passed


def capture_ui(app, output: Path, page_name: str = "project") -> bool:
    """Render one workflow page through the active Qt platform and save it."""
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
        page_indexes = {"project": (0, 0), "analysis": (1, 2), "migration": (2, 3), "results": (3, 4)}
        if page_name not in page_indexes:
            window.close()
            return False
        if page_name == "analysis":
            window.analysis_page.set_context(18, 19, Path("C:/Projects/custom_addons"))
            window.analysis_page.set_progress("Reviewing compatibility findings", 72)
        elif page_name == "migration":
            window.migration_page.set_destination(Path("C:/Projects/custom_addons_19"))
            window.migration_page.set_progress("Applying Odoo 18 to 19 fixes", 58)
        elif page_name == "results":
            from types import SimpleNamespace
            result = SimpleNamespace(changes=(1, 2, 3), output=Path("C:/Projects/custom_addons_19"), metadata_path=None, validation_state="passed", validation_issues=())
            analysis = SimpleNamespace(review_required=(1, 2), blockers=(), plan=SimpleNamespace(source=18, target=19))
            window.results_page.set_result(result, analysis)
        window._show_page(*page_indexes[page_name])
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
        return 0 if smoke_test(app) else 1
    if "--capture-ui" in argv:
        output = Path(os.environ.get("ODOO_MIGRATOR_UI_CAPTURE", "OdooAddonMigrator-Project-1366x768.png"))
        page_name = os.environ.get("ODOO_MIGRATOR_UI_PAGE", "project").casefold()
        if not capture_ui(app, output, page_name):
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
