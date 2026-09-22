from __future__ import annotations

from odoo_migrator import __version__


def display_version(version: str = __version__) -> str:
    """Turn Python packaging's 1.0.0rc2 into user-facing 1.0.0-rc.2."""
    if "rc" in version:
        base, candidate = version.split("rc", 1)
        return f"{base}-rc.{candidate}"
    return version
