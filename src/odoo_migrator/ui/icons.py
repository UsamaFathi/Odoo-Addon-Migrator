from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon


def icon_path() -> Path:
    return Path(__file__).parent / "assets" / "migrator.svg"


def app_icon() -> QIcon:
    return QIcon(str(icon_path()))
