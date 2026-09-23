from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QSettings

from odoo_migrator.sources.registry import SourceMode, SourceSelection


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

    def load_source_selection(self, version: int) -> SourceSelection | None:
        mode = self._settings.value(f"sources/{version}/mode", "")
        if not mode:
            return None
        try:
            selected = SourceMode(str(mode))
        except ValueError:
            return None
        raw_path = self._settings.value(f"sources/{version}/path", "")
        return SourceSelection(version, selected, Path(str(raw_path)) if raw_path else None)

    def save_source_selection(self, selection: SourceSelection, *, validated: bool = False) -> None:
        if selection.mode is SourceMode.LOCAL_EXACT_SOURCE and not validated:
            return
        group = f"sources/{selection.version}"
        self._settings.setValue(f"{group}/mode", selection.mode.value)
        if selection.mode is SourceMode.LOCAL_EXACT_SOURCE and selection.path:
            self._settings.setValue(f"{group}/path", str(Path(selection.path).resolve()))
        else:
            self._settings.remove(f"{group}/path")
        self._settings.sync()

    def forget_source_selection(self, version: int) -> None:
        self._settings.remove(f"sources/{version}")
        self._settings.sync()

    def load_enterprise_source(self, version: int) -> Path | None:
        value = self._settings.value(f"enterprise_sources/{version}", "")
        if not value:
            return None
        try:
            path = Path(str(value)).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            return None
        return path if path.is_dir() else None

    def save_enterprise_source(self, version: int, path: str | Path) -> None:
        resolved = Path(path).expanduser().resolve()
        self._settings.setValue(f"enterprise_sources/{version}", str(resolved))
        self._settings.sync()

    def forget_enterprise_source(self, version: int) -> None:
        self._settings.remove(f"enterprise_sources/{version}")
        self._settings.sync()

    def load_brain_path(self) -> Path | None:
        value = self._settings.value("migration_brain/path", "")
        if not value:
            return None
        try:
            path = Path(str(value)).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            return None
        return path if path.is_file() and path.suffix.casefold() == ".omb" else None

    def save_brain_path(self, path: str | Path) -> None:
        resolved = Path(path).expanduser().resolve()
        self._settings.setValue("migration_brain/path", str(resolved))
        self._settings.sync()

    def forget_brain_path(self) -> None:
        self._settings.remove("migration_brain/path")
        self._settings.sync()

    def load_brain_overlay_path(self) -> Path | None:
        value = self._settings.value("migration_brain/enterprise_overlay", "")
        if not value:
            return None
        try:
            path = Path(str(value)).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            return None
        return path if path.is_file() and path.suffix.casefold() == ".omb" else None

    def save_brain_overlay_path(self, path: str | Path) -> None:
        resolved = Path(path).expanduser().resolve()
        self._settings.setValue("migration_brain/enterprise_overlay", str(resolved))
        self._settings.sync()

    def forget_brain_overlay_path(self) -> None:
        self._settings.remove("migration_brain/enterprise_overlay")
        self._settings.sync()

    def clear(self) -> None:
        self._settings.clear()
        self._settings.sync()
