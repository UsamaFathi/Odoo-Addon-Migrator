from __future__ import annotations

import ast
import csv
import io
import tokenize
import re
from pathlib import Path

from odoo_migrator.migrations.base import Change
from odoo_migrator.migrations.method_matching import high_confidence_method_renames
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


class MethodRenameResolver:
    """Rename a custom override only when source semantics prove a unique target method."""

    category = "python"
    automatic = True
    confidence = 0.88

    def __init__(self, source: int, target: int):
        self.source = source
        self.target = target
        self.rule_id = f"autonomous.method_rename.{source}_to_{target}"
        self.description = "Rename custom Python overrides to a high-confidence target method."

    @staticmethod
    def _class_models(node: ast.ClassDef) -> set[str]:
        declared: list[str] = []
        inherited: list[str] = []
        for statement in node.body:
            if not isinstance(statement, ast.Assign):
                continue
            values = []
            if isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
                values = [statement.value.value]
            elif isinstance(statement.value, (ast.List, ast.Tuple)):
                values = [
                    item.value for item in statement.value.elts
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                ]
            for target in statement.targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id == "_name":
                    declared.extend(values)
                elif target.id == "_inherit":
                    inherited.extend(values)
        return set(declared or inherited)

    @staticmethod
    def _rewrite_file(path: Path, model: str, old: str, new: str) -> str | None:
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
        except (OSError, UnicodeError, SyntaxError):
            return None

        ranges = [
            (node.lineno, getattr(node, "end_lineno", node.lineno))
            for node in tree.body
            if isinstance(node, ast.ClassDef) and model in MethodRenameResolver._class_models(node)
        ]
        if not ranges:
            return None

        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        significant: list[tokenize.TokenInfo] = []
        replacements: list[tuple[int, int, int, int, str]] = []
        for token in tokens:
            if token.type in {tokenize.ENCODING, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
                              tokenize.DEDENT, tokenize.COMMENT, tokenize.ENDMARKER}:
                continue
            in_model_class = any(start <= token.start[0] <= end for start, end in ranges)
            if in_model_class and token.type == tokenize.NAME and token.string == old:
                previous = [item.string for item in significant[-8:]]
                rename = bool(previous and previous[-1] == "def")
                if previous and previous[-1] == ".":
                    if len(previous) >= 2 and previous[-2] in {"self", "cls"}:
                        rename = True
                    elif len(previous) >= 2 and previous[-2] == ")" and "super" in previous:
                        rename = True
                if rename:
                    replacements.append((*token.start, *token.end, new))
            significant.append(token)

        if not replacements:
            return None

        lines = text.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))

        def absolute(line: int, column: int) -> int:
            return offsets[line - 1] + column

        updated = text
        for start_line, start_col, end_line, end_col, replacement in reversed(replacements):
            start = absolute(start_line, start_col)
            end = absolute(end_line, end_col)
            updated = updated[:start] + replacement + updated[end:]
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
        matches = high_confidence_method_renames(source, target, diff)
        if not matches:
            return changes
        for match in matches:
            for module_name, module in custom.modules.items():
                model = module.models.get(match.model)
                if model is None or match.source_method not in model.methods:
                    continue
                candidate_paths: set[Path] = set()
                location = model.method_locations.get(match.source_method)
                if location:
                    candidate_paths.add(Path(root) / module_name / location[0])
                else:
                    candidate_paths.update((Path(root) / module_name).rglob("*.py"))
                for path in sorted(candidate_paths):
                    updated = self._rewrite_file(path, match.model, match.source_method, match.target_method)
                    if updated is None:
                        continue
                    changes.append(Change(
                        self.rule_id,
                        path,
                        f"Method {match.model}.{match.source_method} → {match.target_method} "
                        f"(semantic score {match.score:.3f}, margin {match.margin:.3f}; "
                        + ", ".join(match.evidence) + ")",
                        migration_step=f"{self.source}_to_{self.target}",
                    ))
                    if not dry_run:
                        path.write_text(updated, encoding="utf-8")
        return changes

class SecurityModelReferenceResolver:
    """Update access-CSV model references when an exact model successor is proven."""

    category = "security"
    automatic = True
    confidence = 1.0

    def __init__(self, source: int, target: int):
        self.source = source
        self.target = target
        self.rule_id = f"autonomous.security_model_ref.{source}_to_{target}"
        self.description = "Update access CSV model references to a proven successor model."
        self._models = ModelRenameResolver(source, target)

    @staticmethod
    def _target_external_id(model_name: str, target: OdooIndex, qualified: bool) -> str | None:
        short = f"model_{model_name.replace('.', '_')}"
        owners = ModelRenameResolver._owners(target, model_name)
        candidates = sorted(xml_id for xml_id, value in target.model_xml_ids.items() if value == model_name)
        if qualified and len(owners) == 1:
            preferred = f"{owners[0]}.{short}"
            if preferred in candidates:
                return preferred
        if short in candidates:
            return short
        if qualified:
            qualified_candidates = [item for item in candidates if '.' in item]
            if len(qualified_candidates) == 1:
                return qualified_candidates[0]
        return candidates[0] if len(candidates) == 1 else None

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
        for module_name in sorted(custom.modules):
            module_root = Path(root) / module_name
            for path in sorted(module_root.rglob("ir.model.access.csv")):
                try:
                    text = path.read_text(encoding="utf-8")
                    rows = list(csv.DictReader(text.splitlines()))
                except (OSError, UnicodeError, csv.Error):
                    continue
                if not rows:
                    continue
                replacements: dict[str, str] = {}
                for row in rows:
                    model_ref = (row.get("model_id:id") or "").strip()
                    if not model_ref or target.resolve_model_external_id(model_ref) is not None:
                        continue
                    source_model = source.resolve_model_external_id(model_ref)
                    if source_model is None:
                        continue
                    successor = self._models._successor(source_model, source, target, diff)
                    if successor is None:
                        continue
                    replacement = self._target_external_id(successor, target, qualified="." in model_ref)
                    if replacement is None or replacement == model_ref:
                        continue
                    replacements[model_ref] = replacement
                if not replacements:
                    continue

                updated = text
                for old, new in replacements.items():
                    updated = updated.replace(old, new)
                try:
                    updated_rows = list(csv.DictReader(updated.splitlines()))
                except csv.Error:
                    continue
                if len(updated_rows) != len(rows):
                    continue
                changes.append(Change(
                    self.rule_id,
                    path,
                    "Updated access CSV model references: " + ", ".join(
                        f"{old} → {new}" for old, new in sorted(replacements.items())
                    ) + f" (confidence {self.confidence:.2f})",
                    migration_step=f"{self.source}_to_{self.target}",
                ))
                if not dry_run:
                    path.write_text(updated, encoding="utf-8")
        return changes


def autonomous_resolvers_for(source: int, target: int) -> tuple[DependencyModuleRenameResolver | ModelRenameResolver | MethodRenameResolver | SecurityModelReferenceResolver, ...]:
    return (
        DependencyModuleRenameResolver(source, target),
        ModelRenameResolver(source, target),
        MethodRenameResolver(source, target),
        SecurityModelReferenceResolver(source, target),
    )
