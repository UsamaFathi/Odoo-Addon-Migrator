from __future__ import annotations

import argparse
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from odoo_migrator.ui.main_window import MainWindow


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture offscreen desktop GUI diagnostics.")
    parser.add_argument("--output", type=Path, default=Path("gui-screenshots"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    app = QApplication([])
    for width, height in ((1366, 768), (1920, 1080)):
        window = MainWindow()
        window.resize(width, height)
        window.show()
        app.processEvents()
        output = args.output / f"project-empty-{width}x{height}.png"
        if not window.grab().save(str(output), "PNG"):
            raise RuntimeError(f"Unable to save GUI screenshot: {output}")
        window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
