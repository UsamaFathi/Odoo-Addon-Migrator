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


_INHERIT_ASSIGNMENT = re.compile(
    r"(?P<prefix>\b_inherit\s*=\s*)(?P<value>\[[^\]]*\]|\([^\)]*\)|['\"][^'\"]+['\"])",
    re.DOTALL,
)


class ModelRenameResolver:
    """Rewrite custom _inherit only for a uniquely proven standard-model rename."""

    category = "model"
    automatic = True
    confidence = 1.0

    def __init__(self, source: int, target: int):
        self.source = source
        self.target = target
        self.rule_id = f"autonomous.model_rename.{source}_to_{target}"
        self.description = "Replace a removed standard model with its unique exact-API successor."

    @staticmethod
    def _owners(index: OdooIndex, model_name: str) -> tuple[str, ...]:
        return tuple(
            name
            for name, module in index.modules.items()
            if model_name in module.defined_models
        )

    @staticmethod
    def _fingerprint(index: OdooIndex, model_name: str) -> tuple[frozenset[str], frozenset[str]] | None:
        info = index.models.get(model_name)
        if info is None:
            return None
        return frozenset(info.fields), frozenset(info.methods)

    def _successor(self, model_name: str, source: OdooIndex, target: OdooIndex, diff: SourceDiff) -> str | None:
        if model_name not in diff.models_removed:
            return None
        source_fp = self._fingerprint(source, model_name)
        if source_fp is None:
            return None
        source_fields, source_methods = source_fp
        feature_count = len(source_fields) + len(source_methods)
        source_owners = self._owners(source, model_name)
        if len(source_owners) != 1:
            return None

        candidates: list[str] = []
        for candidate in sorted(diff.models_added):
            target_fp = self._fingerprint(target, candidate)
            if target_fp != source_fp:
                continue
            target_owners = self._owners(target, candidate)
            if len(target_owners) != 1:
                continue
            same_owner = target_owners[0] == source_owners[0]
            minimum_features = 4 if same_owner else 8
            if feature_count < minimum_features:
                continue
            candidates.append(candidate)
        return candidates[0] if len(candidates) == 1 else None

    @staticmethod
    def _replace_inherit(path: Path, old: str, new: str) -> str | None:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None
        literal = re.compile(rf"(?P<quote>['\\\"]){re.escape(old)}(?P=quote)")
        changed = False

        def replacement(match: re.Match[str]) -> str:
            nonlocal changed
            value, count = literal.subn(
                lambda item: f"{item.group('quote')}{new}{item.group('quote')}",
                match.group("value"),
            )
            if count:
                changed = True
            return match.group("prefix") + value

        updated = _INHERIT_ASSIGNMENT.sub(replacement, text)
        if not changed:
            return None
        try:
            ast.parse(updated, filename=str(path))
        except SyntaxError:
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
        for module_name, module in custom.modules.items():
            removed_models = sorted(set(module.models) & set(diff.models_removed))
            for model_name in removed_models:
                successor = self._successor(model_name, source, target, diff)
                if successor is None:
                    continue
                module_root = Path(root) / module_name
                for path in sorted(module_root.rglob("*.py")):
                    if path.name == "__manifest__.py" or "__pycache__" in path.parts:
                        continue
                    updated = self._replace_inherit(path, model_name, successor)
                    if updated is None:
                        continue
                    changes.append(Change(
                        self.rule_id,
                        path,
                        f"Model _inherit {model_name} → {successor} "
                        f"(unique exact API fingerprint; confidence {self.confidence:.2f})",
                        migration_step=f"{self.source}_to_{self.target}",
                    ))
                    if not dry_run:
                        path.write_text(updated, encoding="utf-8")
        return changes

def autonomous_resolvers_for(source: int, target: int) -> tuple[DependencyModuleRenameResolver | ModelRenameResolver, ...]:
    return (
        DependencyModuleRenameResolver(source, target),
        ModelRenameResolver(source, target),
    )
