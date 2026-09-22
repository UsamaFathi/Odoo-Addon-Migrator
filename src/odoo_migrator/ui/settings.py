from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QSettings


ORGANIZATION = "OdooAddonMigrator"
APPLICATION = "OdooAddonMigrator"


def production_settings() -> QSettings:
    return QSettings(ORGANIZATION, APPLICATION)


def is_safe_project_path(value: str | Path | None) -> bool:
    """Accept only existing, non-temporary addon roots for restoration."""
    if not value:
        return False
    try:
        path = Path(value).expanduser().resolve()
        temp_root = Path(tempfile.gettempdir()).resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    if not path.is_dir() or "pytest-of-" in str(path).casefold():
        return False
    try:
        if path.is_relative_to(temp_root):
            return False
    except (OSError, ValueError):
        return False
    try:
        return any(item.is_file() and item.name == "__manifest__.py" for item in path.rglob("__manifest__.py"))
    except OSError:
        return False


class DesktopSettings:
    """Small settings boundary so GUI tests never touch production QSettings."""

    def __init__(self, settings: QSettings | None = None):
        self._settings = settings or production_settings()

    @property
    def raw(self) -> QSettings:
        return self._settings

    def load_geometry(self):
        return self._settings.value("geometry")

    def save_geometry(self, geometry) -> None:
        self._settings.setValue("geometry", geometry)
        self._settings.sync()

    def load_last_project(self) -> Path | None:
        value = self._settings.value("last_path", "")
        return Path(str(value)) if is_safe_project_path(value) else None

    def save_last_project(self, path: str | Path | None) -> None:
        if is_safe_project_path(path):
            self._settings.setValue("last_path", str(Path(path).resolve()))
        else:
            self._settings.remove("last_path")
        self._settings.sync()

    def clear(self) -> None:
        self._settings.clear()
        self._settings.sync()
