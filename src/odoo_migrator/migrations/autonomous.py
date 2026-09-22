from __future__ import annotations

import ast
import re
from pathlib import Path

from odoo_migrator.migrations.base import Change
from odoo_migrator.sources.diff import SourceDiff
from odoo_migrator.sources.indexer import OdooIndex


_DEPENDS_FIELD = re.compile(
    r"(?P<prefix>['\"]depends['\"]\s*:\s*\[)(?P<body>.*?)(?P<suffix>\])",
    re.DOTALL,
)


class DependencyModuleRenameResolver:
    """Resolve an official dependency rename only when source ownership proves one successor.

    A removed source module is considered safely replaceable only when it defines at least
    one technical model and exactly one target module defines the identical model set.
    This intentionally prefers false negatives over guessing.
    """

    category = "dependency"
    automatic = True
    confidence = 1.0

    def __init__(self, source: int, target: int):
        self.source = source
        self.target = target
        self.rule_id = f"autonomous.dependency_rename.{source}_to_{target}"
        self.description = "Replace a removed official dependency with its unique model-owner successor."

    @staticmethod
    def _successor(dependency: str, source: OdooIndex, target: OdooIndex) -> str | None:
        source_module = source.modules.get(dependency)
        if source_module is None:
            return None
        owned_models = frozenset(source_module.defined_models)
        if not owned_models:
            return None
        candidates = [
            name
            for name, module in target.modules.items()
            if name != dependency and frozenset(module.defined_models) == owned_models
        ]
        return candidates[0] if len(candidates) == 1 else None

    @staticmethod
    def _replace_dependency(manifest: Path, old: str, new: str) -> str | None:
        try:
            text = manifest.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None
        match = _DEPENDS_FIELD.search(text)
        if not match:
            return None
        literal = re.compile(rf"(?P<quote>['\"]){re.escape(old)}(?P=quote)")
        body, count = literal.subn(lambda item: f"{item.group('quote')}{new}{item.group('quote')}", match.group("body"))
        if count == 0:
            return None
        updated = text[:match.start("body")] + body + text[match.end("body"):]
        try:
            parsed = ast.literal_eval(updated)
        except Exception:
            return None
        if not isinstance(parsed, dict):
            return None
        dependencies = parsed.get("depends", [])
        if old in dependencies or new not in dependencies:
            return None
        return updated

    def apply(
        self,
        root: Path,
        custom: OdooIndex,
        source: OdooIndex,
        target: OdooIndex,
        diff: SourceDiff,
        *,
        dry_run: bool = False,
    ) -> list[Change]:
        changes: list[Change] = []
        removed = set(diff.modules_removed)
        for module_name, module in custom.modules.items():
            for dependency in sorted(set(module.depends) & removed):
                if dependency in custom.modules:
                    continue
                successor = self._successor(dependency, source, target)
                if successor is None:
                    continue
                manifest = Path(root) / module_name / "__manifest__.py"
                updated = self._replace_dependency(manifest, dependency, successor)
                if updated is None:
                    continue
                changes.append(Change(
                    self.rule_id,
                    manifest,
                    f"Dependency {dependency} → {successor} "
                    f"(unique official model-owner match; confidence {self.confidence:.2f})",
                    migration_step=f"{self.source}_to_{self.target}",
                ))
                if not dry_run:
                    manifest.write_text(updated, encoding="utf-8")
        return changes


def autonomous_resolvers_for(source: int, target: int) -> tuple[DependencyModuleRenameResolver, ...]:
    return (DependencyModuleRenameResolver(source, target),)
