from __future__ import annotations

import sys


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
    from odoo_migrator.ui.main_window import MainWindow
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
