from __future__ import annotations

from pathlib import Path
import ast
import re

from odoo_migrator.migrations.base import Change, MigrationRule
from odoo_migrator.migrations.base import Classification

_VERSION_LINE = re.compile(r"(?P<prefix>['\"]version['\"]\s*:\s*['\"])(?P<version>[^'\"]+)(?P<suffix>['\"]\s*,?)")


class ManifestVersionRule(MigrationRule):
    """Safely changes only a leading Odoo-major prefix such as 15.0.x -> 16.0.x."""

    def __init__(self, source: int, target: int):
        super().__init__(source, target, f"manifest.version.{source}_to_{target}", "manifest",
                         Classification.SAFE_AUTO_FIX,
                         "Update the Odoo major version prefix while preserving the addon suffix.",
                         "Verified against official Odoo 14.0/15.0 addon version conventions.", True)

    def apply(self, root: Path, dry_run: bool = False) -> list[Change]:
        changes: list[Change] = []
        for path in Path(root).rglob("__manifest__.py"):
            text = path.read_text(encoding="utf-8")
            match = _VERSION_LINE.search(text)
            if not match:
                continue
            current = match.group("version")
            prefix = f"{self.source}.0"
            if not (current == prefix or current.startswith(prefix + ".")):
                continue
            new_version = f"{self.target}.0" + current[len(prefix):]
            updated = text[:match.start("version")] + new_version + text[match.end("version"):]
            try:
                ast.literal_eval(updated)
            except Exception:
                continue
            changes.append(Change(self.rule_id, path, f"Manifest version {current} → {new_version}"))
            if not dry_run:
                path.write_text(updated, encoding="utf-8")
        return changes
