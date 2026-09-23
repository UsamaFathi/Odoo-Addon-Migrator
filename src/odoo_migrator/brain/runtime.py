from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
import shutil
import ast
import difflib
import html
import io
import tokenize
from tempfile import mkdtemp
from collections.abc import Callable

from odoo_migrator.analysis.compat import Finding, Severity
from odoo_migrator.core.planner import build_plan
from odoo_migrator.migrations.autonomous import (
    DependencyModuleRenameResolver,
    MethodRenameResolver,
    ModelRenameResolver,
)
from odoo_migrator.migrations.base import Change
from odoo_migrator.migrations.registry import MigrationPackRegistry, default_registry
from odoo_migrator.validation import ValidationItem, validate_project
from odoo_migrator.sources.indexer import SourceIndexer

from .pack import BrainPack


@dataclass(frozen=True, slots=True)
class BrainMigrationResult:
    output: Path
    changes: tuple[Change, ...]
    metadata_path: Path
    validation_state: str
    validation_issues: tuple[ValidationItem, ...]
    report_path: Path | None = None
    diff_path: Path | None = None
    findings: tuple[Finding, ...] = ()


def _append_change(
    changes: list[Change],
    rule_id: str,
    path: Path,
    description: str,
    step: str,
) -> None:
    changes.append(Change(rule_id, path, description, migration_step=step))


def _apply_dependency_mappings(root: Path, mappings: list[dict], step: str,
                               changes: list[Change]) -> None:
    for manifest in root.rglob("__manifest__.py"):
        for item in mappings:
            updated = DependencyModuleRenameResolver._replace_dependency(
                manifest,
                str(item["from"]),
                str(item["to"]),
            )
            if updated is None:
                continue
            manifest.write_text(updated, encoding="utf-8")
            _append_change(
                changes,
                f"brain.dependency_rename.{step}",
                manifest,
                f"Dependency {item['from']} -> {item['to']} "
                f"(brain confidence {float(item.get('confidence', 0.0)):.3f})",
                step,
            )


def _apply_model_mappings(root: Path, mappings: list[dict], step: str,
                          changes: list[Change]) -> None:
    for path in root.rglob("*.py"):
        if path.name == "__manifest__.py" or "__pycache__" in path.parts:
            continue
        current = path.read_text(encoding="utf-8", errors="replace")
        updated = current
        descriptions = []
        for item in mappings:
            candidate = ModelRenameResolver._replace_inherit(
                path if updated == current else _temporary_python_view(path, updated),
                str(item["from"]),
                str(item["to"]),
            )
            if candidate is None:
                continue
            updated = candidate
            descriptions.append(
                f"{item['from']} -> {item['to']} "
                f"({float(item.get('confidence', 0.0)):.3f})"
            )
        if updated == current:
            continue
        path.write_text(updated, encoding="utf-8")
        _append_change(
            changes,
            f"brain.model_rename.{step}",
            path,
            "Model inheritance: " + ", ".join(descriptions),
            step,
        )


def _temporary_python_view(path: Path, text: str) -> Path:
    """Provide sequential mapping support without leaving temporary files behind."""
    shadow = path.with_name(f".{path.name}.brain-tmp")
    shadow.write_text(text, encoding="utf-8")
    return shadow


def _cleanup_shadow_files(root: Path) -> None:
    for path in root.rglob(".*.brain-tmp"):
        try:
            path.unlink()
        except OSError:
            pass


def _apply_method_mappings(root: Path, mappings: list[dict], step: str,
                           changes: list[Change]) -> None:
    python_files = [
        path
        for path in root.rglob("*.py")
        if path.name != "__manifest__.py" and "__pycache__" not in path.parts
    ]
    for item in mappings:
        model = str(item["model"])
        old = str(item["from"])
        new = str(item["to"])
        for path in python_files:
            updated = MethodRenameResolver._rewrite_file(path, model, old, new)
            if updated is None:
                continue
            path.write_text(updated, encoding="utf-8")
            _append_change(
                changes,
                f"brain.method_rename.{step}",
                path,
                f"Method {model}.{old} -> {new} "
                f"(brain confidence {float(item.get('confidence', 0.0)):.3f}, "
                f"margin {float(item.get('margin', 0.0)):.3f})",
                step,
            )


def _rewrite_field_file(path: Path, model: str, old: str, new: str) -> str | None:
    """Rename only field declarations and record attribute access in one model class."""
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
    except (OSError, UnicodeError, SyntaxError):
        return None
    class_ranges = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if model not in MethodRenameResolver._class_models(node):
            continue
        class_ranges.append((node.lineno, getattr(node, "end_lineno", node.lineno)))
    if not class_ranges:
        return None

    tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    significant = [item for item in tokens if item.type not in {
        tokenize.ENCODING, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
        tokenize.DEDENT, tokenize.COMMENT, tokenize.ENDMARKER,
    }]
    replacements: list[tuple[int, int, int, int]] = []
    for index, token in enumerate(significant):
        if token.type != tokenize.NAME or token.string != old:
            continue
        if not any(start <= token.start[0] <= end for start, end in class_ranges):
            continue
        previous = significant[index - 1].string if index else ""
        following = significant[index + 1].string if index + 1 < len(significant) else ""
        before_previous = significant[index - 2].string if index >= 2 else ""
        is_declaration = following == "=" and index + 2 < len(significant) and significant[index + 2].string == "fields"
        is_attribute = previous == "." and before_previous == "self"
        if is_declaration or is_attribute:
            replacements.append((*token.start, *token.end))
    if not replacements:
        return None
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    updated = text
    for start_line, start_col, end_line, end_col in reversed(replacements):
        start = offsets[start_line - 1] + start_col
        end = offsets[end_line - 1] + end_col
        updated = updated[:start] + new + updated[end:]
    try:
        ast.parse(updated, filename=str(path))
    except SyntaxError:
        return None
    return updated


def _apply_field_mappings(root: Path, mappings: list[dict], step: str,
                          changes: list[Change]) -> None:
    for item in mappings:
        model, old, new = str(item["model"]), str(item["from"]), str(item["to"])
        for path in sorted(root.rglob("*.py")):
            if path.name == "__manifest__.py" or "__pycache__" in path.parts:
                continue
            updated = _rewrite_field_file(path, model, old, new)
            if updated is None:
                continue
            path.write_text(updated, encoding="utf-8")
            _append_change(
                changes,
                f"brain.field_rename.{step}",
                path,
                f"Field {model}.{old} -> {new} "
                f"(brain confidence {float(item.get('confidence', 0.0)):.3f}, "
                f"margin {float(item.get('margin', 0.0)):.3f})",
                step,
            )


def _xml_reference_matches(reference: str, removed: set[str]) -> bool:
    value = reference.strip()
    if value in removed:
        return True
    return any(item.rsplit(".", 1)[-1] == value for item in removed if "." in item)


def _security_reference(value: str, module_name: str) -> str:
    value = value.strip()
    if value and "." not in value:
        return f"{module_name}.{value}"
    return value


def _brain_findings(root: Path, step: str, compatibility: dict) -> tuple[Finding, ...]:
    """Detect references using derived Brain knowledge and the custom tree only."""
    findings: list[Finding] = []
    index = SourceIndexer().index(root)
    removed_modules = set(compatibility.get("removed_modules", ()))
    removed_models = set(compatibility.get("removed_models", ()))
    removed_xml_ids = set(compatibility.get("removed_xml_ids", ()))
    removed_model_xml_ids = set(compatibility.get("removed_model_xml_ids", ()))
    removed_group_xml_ids = set(compatibility.get("removed_group_xml_ids", ()))
    changed_view_architectures = set(compatibility.get("changed_view_architectures", ()))
    changed_template_architectures = set(compatibility.get("changed_template_architectures", ()))
    method_moves = compatibility.get("method_moves", ())
    model_ownership_changes = {
        item.get("model"): item for item in compatibility.get("model_ownership_changes", ())
    }
    removed_js = set(compatibility.get("removed_js_modules", ()))
    removed_assets = set(compatibility.get("removed_asset_bundles", ()))
    model_changes = {item["model"]: item for item in compatibility.get("model_changes", ())}
    custom_modules = set(index.modules)

    for module_name, module in index.modules.items():
        for dependency in sorted(set(module.depends) & removed_modules - custom_modules):
            findings.append(Finding(
                Severity.BLOCKER, "brain.dependency.removed", module_name,
                f"Dependency '{dependency}' was present in the trained source and is absent in the target.",
                rule_id=f"brain.dependency.removed.{step}", migration_step=step,
                object_name=dependency, source_state="present", target_state="removed",
                suggested_action="Use the trained replacement mapping if one exists, otherwise review the target dependency.",
            ))
        for model_name, model in module.models.items():
            if model_name in removed_models:
                findings.append(Finding(
                    Severity.BLOCKER, "brain.model.removed", module_name,
                    f"Custom addon references removed model '{model_name}'.",
                    path=model.source_path, line=model.line,
                    rule_id=f"brain.model.removed.{step}", migration_step=step,
                    object_name=model_name, source_state="present", target_state="removed",
                    suggested_action="Review the target model or provide a verified replacement.",
                ))
                continue
            change = model_changes.get(model_name)
            ownership = model_ownership_changes.get(model_name)
            if ownership:
                findings.append(Finding(
                    Severity.REVIEW_REQUIRED, "brain.model.ownership_changed", module_name,
                    f"Model '{model_name}' changed official module ownership between source and target.",
                    path=model.source_path, line=model.line,
                    rule_id=f"brain.model.ownership_changed.{step}", migration_step=step,
                    object_name=model_name, source_state=", ".join(ownership.get("source_modules", ())),
                    target_state=", ".join(ownership.get("target_modules", ())),
                    suggested_action="Review module dependencies and the target model provider.",
                ))
            for move in method_moves:
                if move.get("from_model") == model_name and move.get("method") in model.methods:
                    findings.append(Finding(
                        Severity.REVIEW_REQUIRED, "brain.method.moved", module_name,
                        f"Method '{model_name}.{move['method']}()' moved to '{move.get('to_model')}'.",
                        path=model.method_locations.get(move["method"], (model.source_path, None))[0],
                        line=model.method_locations.get(move["method"], (None, None))[1],
                        rule_id=f"brain.method.moved.{step}", migration_step=step,
                        object_name=f"{model_name}.{move['method']}", source_state="present",
                        target_state=f"moved to {move.get('to_model')}",
                        suggested_action="Review callers and overrides; no cross-model rewrite is attempted.",
                    ))
            if not change:
                continue
            for method in sorted(set(model.methods) & set(change.get("removed_methods", ()) )):
                location = model.method_locations.get(method)
                findings.append(Finding(
                    Severity.REVIEW_REQUIRED, "brain.method.removed", module_name,
                    f"Custom addon references removed method '{model_name}.{method}()'.",
                    path=location[0] if location else model.source_path,
                    line=location[1] if location else model.line,
                    rule_id=f"brain.method.removed.{step}", migration_step=step,
                    object_name=f"{model_name}.{method}", source_state="present", target_state="removed",
                    suggested_action="Review the trained target API before installation.",
                ))
            for field in sorted(set(model.fields) & set(change.get("removed_fields", ()) )):
                location = model.field_locations.get(field)
                findings.append(Finding(
                    Severity.REVIEW_REQUIRED, "brain.field.removed", module_name,
                    f"Custom addon references removed field '{model_name}.{field}'.",
                    path=location[0] if location else model.source_path,
                    line=location[1] if location else model.line,
                    rule_id=f"brain.field.removed.{step}", migration_step=step,
                    object_name=f"{model_name}.{field}", source_state="present", target_state="removed",
                    suggested_action="Review the trained target field API.",
                ))
            for method in sorted(set(model.methods) & set(change.get("signature_changes", ()) )):
                location = model.method_locations.get(method)
                findings.append(Finding(
                    Severity.REVIEW_REQUIRED, "brain.signature.changed", module_name,
                    f"Method signature changed for '{model_name}.{method}()'.",
                    path=location[0] if location else model.source_path,
                    line=location[1] if location else model.line,
                    rule_id=f"brain.signature.changed.{step}", migration_step=step,
                    object_name=f"{model_name}.{method}", source_state="changed", target_state="changed",
                    suggested_action="Review callers and overridden method signatures.",
                ))
        for dependency in sorted(set(module.js_dependencies) & removed_js):
            findings.append(Finding(
                Severity.REVIEW_REQUIRED, "brain.frontend.module_removed", module_name,
                f"Frontend dependency '{dependency}' was removed in the trained target.",
                rule_id=f"brain.frontend.module_removed.{step}", migration_step=step,
                object_name=dependency, source_state="present", target_state="removed",
                suggested_action="Review the target Owl/web-client API.",
            ))
        for bundle in sorted(set(module.manifest.get("assets", {})) & removed_assets):
            findings.append(Finding(
                Severity.REVIEW_REQUIRED, "brain.frontend.asset_bundle_removed", module_name,
                f"Asset bundle '{bundle}' was removed in the trained target.",
                path="__manifest__.py", rule_id=f"brain.frontend.asset_bundle_removed.{step}",
                migration_step=step, object_name=bundle, source_state="present", target_state="removed",
                suggested_action="Review target asset bundles; no replacement is guessed.",
            ))
        for view in module.views.values():
            if view.inherit_id and _xml_reference_matches(view.inherit_id, removed_xml_ids):
                findings.append(Finding(
                    Severity.REVIEW_REQUIRED, "brain.xml.target_removed", module_name,
                    f"Inherited XML target '{view.inherit_id}' was removed in the trained target.",
                    rule_id=f"brain.xml.target_removed.{step}", migration_step=step,
                    object_name=view.inherit_id, source_state="present", target_state="removed",
                    suggested_action="Review the target view/template and inherited XPath.",
                ))
            elif view.inherit_id and _xml_reference_matches(view.inherit_id, changed_view_architectures):
                findings.append(Finding(
                    Severity.REVIEW_REQUIRED, "brain.xml.architecture_changed", module_name,
                    f"Inherited view target '{view.inherit_id}' changed architecture in the trained target.",
                    path=Path(module.path).relative_to(root).as_posix(),
                    rule_id=f"brain.xml.architecture_changed.{step}", migration_step=step,
                    object_name=view.inherit_id, source_state="changed", target_state="changed",
                    suggested_action="Review inherited XPath and target structure before installation.",
                ))
        for template in module.templates.values():
            if template.inherit_id and _xml_reference_matches(template.inherit_id, removed_xml_ids):
                findings.append(Finding(
                    Severity.REVIEW_REQUIRED, "brain.qweb.target_removed", module_name,
                    f"Inherited QWeb target '{template.inherit_id}' was removed in the trained target.",
                    rule_id=f"brain.qweb.target_removed.{step}", migration_step=step,
                    object_name=template.inherit_id, source_state="present", target_state="removed",
                    suggested_action="Review the target QWeb/Owl template and inherited XPath.",
                ))
            elif template.inherit_id and _xml_reference_matches(template.inherit_id, changed_template_architectures):
                findings.append(Finding(
                    Severity.REVIEW_REQUIRED, "brain.qweb.architecture_changed", module_name,
                    f"Inherited QWeb target '{template.inherit_id}' changed architecture in the trained target.",
                    rule_id=f"brain.qweb.architecture_changed.{step}", migration_step=step,
                    object_name=template.inherit_id, source_state="changed", target_state="changed",
                    suggested_action="Review the target template and inherited XPath before installation.",
                ))
        for access_path in Path(module.path).rglob("ir.model.access.csv"):
            try:
                with access_path.open(encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    required = {"id", "model_id:id", "group_id:id", "perm_read", "perm_write", "perm_create", "perm_unlink"}
                    if not reader.fieldnames or not required <= set(reader.fieldnames):
                        raise ValueError("missing access CSV columns")
                    for row in reader:
                        model_ref = row.get("model_id:id", "").strip()
                        if model_ref and _security_reference(model_ref, module_name) in removed_model_xml_ids:
                            findings.append(Finding(
                                Severity.BLOCKER, "brain.security.model_removed", module_name,
                                f"Access rule references removed model external ID '{model_ref}'.",
                                path=access_path.relative_to(root).as_posix(),
                                rule_id=f"brain.security.model_removed.{step}", migration_step=step,
                                object_name=model_ref, source_state="present", target_state="removed",
                                suggested_action="Review or remove the access rule for the target Odoo version.",
                            ))
                        group_ref = _security_reference(row.get("group_id:id", ""), module_name)
                        if group_ref and group_ref in removed_group_xml_ids and group_ref not in index.group_xml_ids:
                            findings.append(Finding(
                                Severity.REVIEW_REQUIRED, "brain.security.group_removed", module_name,
                                f"Access rule references removed group external ID '{group_ref}'.",
                                path=access_path.relative_to(root).as_posix(),
                                rule_id=f"brain.security.group_removed.{step}", migration_step=step,
                                object_name=group_ref, source_state="present", target_state="removed",
                                suggested_action="Verify the target group external ID and permissions.",
                            ))
            except (OSError, UnicodeError, ValueError, csv.Error) as exc:
                findings.append(Finding(
                    Severity.BLOCKER, "brain.security.access_csv_invalid", module_name,
                    str(exc), path=access_path.relative_to(root).as_posix(),
                    rule_id=f"brain.security.access_csv_invalid.{step}", migration_step=step,
                    suggested_action="Correct the access CSV before migration.",
                ))
    return tuple(findings)


def _unified_diff(before: Path, after: Path) -> str:
    ignored = {".odoo_migration_brain_run.json", "migration_report.html", "migration.diff"}
    files = {p.relative_to(before).as_posix() for p in before.rglob("*") if p.is_file() and p.name not in ignored}
    files |= {p.relative_to(after).as_posix() for p in after.rglob("*") if p.is_file() and p.name not in ignored}
    chunks: list[str] = []
    for relative in sorted(files):
        old = (before / relative).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if (before / relative).exists() else []
        new = (after / relative).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if (after / relative).exists() else []
        chunks.extend(difflib.unified_diff(old, new, fromfile=f"a/{relative}", tofile=f"b/{relative}"))
    return "".join(chunks)


def _write_brain_report(path: Path, metadata: dict, findings: tuple[Finding, ...]) -> None:
    rows = []
    for finding in findings:
        rows.append(
            "<tr>" + "".join(
                f"<td>{html.escape(str(value or ''))}</td>"
                for value in (
                    finding.severity.value,
                    finding.migration_step,
                    finding.module,
                    finding.path,
                    finding.line,
                    finding.rule_id,
                    finding.message,
                )
            ) + "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="7">No unresolved compatibility findings.</td></tr>')
    html_text = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Migration Brain report</title>
<style>body{{font:14px Segoe UI,Arial,sans-serif;background:#f5f7fa;color:#172033;padding:28px}}main{{max-width:1200px;margin:auto;background:#fff;padding:28px;border-radius:12px}}table{{border-collapse:collapse;width:100%;margin-top:18px}}th,td{{border:1px solid #d9dee8;padding:8px;text-align:left;vertical-align:top}}th{{background:#eef2f7}}.note{{background:#fff4d6;padding:12px;border-radius:8px}}</style></head>
<body><main><h1>Odoo Addon Migrator - Migration Brain</h1>
<p><strong>Source:</strong> Odoo {metadata['source_version']}<br><strong>Target:</strong> Odoo {metadata['target_version']}<br>
<strong>Path:</strong> {html.escape(' -> '.join(metadata['migration_path']))}<br>
<strong>Brain fingerprint:</strong> {html.escape(metadata['brain_fingerprint'])}<br>
<strong>Validation:</strong> {html.escape(metadata['validation']['state'])}</p>
<div class="note">This report was produced without indexing Odoo Community or Enterprise source at runtime. Static validation is not runtime compatibility proof.</div>
<h2>Decisions</h2><p>{len(metadata['changes'])} automatic changes; {len(findings)} unresolved compatibility finding(s).</p>
<h2>Findings</h2><table><thead><tr><th>Severity</th><th>Step</th><th>Addon</th><th>File</th><th>Line</th><th>Rule</th><th>Message</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
</main></body></html>"""
    path.write_text(html_text, encoding="utf-8")


class BrainRuntimeMigrator:
    """Migrate custom addons using a pre-trained brain pack only.

    Official Community/Enterprise source trees are intentionally not accepted
    here. Source code belongs to the training phase, not the daily runtime path.
    """

    def __init__(
        self,
        brain: BrainPack | str | Path,
        *,
        registry: MigrationPackRegistry | None = None,
    ):
        self.brain = brain if isinstance(brain, BrainPack) else BrainPack.load(brain)
        self.registry = registry or default_registry()

    def migrate(
        self,
        input_root: str | Path,
        output_root: str | Path,
        *,
        source: int,
        target: int,
        progress: Callable[[str, int], None] | None = None,
    ) -> BrainMigrationResult:
        input_path = Path(input_root).expanduser().resolve()
        output_path = Path(output_root).expanduser().resolve()

        if not input_path.is_dir():
            raise ValueError(f"Input addons directory does not exist: {input_path}")
        if output_path.exists():
            raise FileExistsError(f"Output already exists: {output_path}")
        if input_path == output_path or input_path in output_path.parents or output_path in input_path.parents:
            raise ValueError("Input and output directories must be separate.")
        if not self.brain.supports(source, target):
            raise ValueError(f"Migration Brain does not support Odoo {source} -> {target}.")

        plan = build_plan(source, target)
        self.registry.require_plan(plan.steps)

        def report(stage: str, percent: int) -> None:
            if progress:
                progress(stage, percent)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(mkdtemp(prefix=f".{output_path.name}.brain-", dir=output_path.parent))
        shutil.rmtree(staging)
        shutil.copytree(input_path, staging, symlinks=False)
        changes: list[Change] = []
        findings: list[Finding] = []
        input_fingerprint = SourceIndexer.project_fingerprint(input_path)

        try:
            for index, step in enumerate(plan.steps):
                key = step.key
                learned = self.brain.step(step.source, step.target)
                report(
                    f"Brain migration {step.source} -> {step.target}",
                    10 + int(index / max(1, len(plan.steps)) * 70),
                )

                allowed_rules = set(learned.get("automatic_rules", ()))
                before_iteration = None
                for iteration in range(3):
                    fingerprint = SourceIndexer.project_fingerprint(staging)
                    if fingerprint == before_iteration:
                        break
                    before_iteration = fingerprint
                    for rule in self.registry.require(step.source, step.target).rule_factory():
                        if rule.automatic and rule.rule_id in allowed_rules:
                            changes.extend(rule.apply(staging, dry_run=False))

                    _apply_dependency_mappings(staging, list(learned.get("dependency_renames", ())), key, changes)
                    _apply_model_mappings(staging, list(learned.get("model_renames", ())), key, changes)
                    _apply_field_mappings(staging, list(learned.get("field_renames", ())), key, changes)
                    _cleanup_shadow_files(staging)
                    _apply_method_mappings(staging, list(learned.get("method_renames", ())), key, changes)

                findings.extend(_brain_findings(staging, key, learned.get("compatibility", {})))

            report("Validating Brain-migrated output", 88)
            issues = tuple(validate_project(staging))
            if any(item.severity is Severity.BLOCKER for item in findings):
                state = "blocked"
            else:
                state = "passed" if not issues else "failed"
            output_fingerprint = SourceIndexer.project_fingerprint(staging)

            metadata = {
                "tool": "Odoo Addon Migrator",
                "engine": "migration_brain",
                "brain_fingerprint": self.brain.fingerprint,
                "brain_source_version": self.brain.source,
                "brain_target_version": self.brain.target,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_version": source,
                "target_version": target,
                "migration_path": [step.key for step in plan.steps],
                "source_code_indexed_at_runtime": False,
                "brain_training": self.brain.training,
                "input_fingerprint": input_fingerprint,
                "output_fingerprint_before_metadata": output_fingerprint,
                "validation": {
                    "state": state,
                    "level": 1,
                    "issues": [asdict(item) for item in issues],
                },
                "findings": [asdict(item) for item in findings],
                "changes": [
                    {
                        "rule_id": item.rule_id,
                        "path": item.path.relative_to(staging).as_posix(),
                        "description": item.description,
                        "migration_step": item.migration_step,
                    }
                    for item in changes
                ],
            }
            metadata_path = staging / ".odoo_migration_brain_run.json"
            metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            diff_path = staging / "migration.diff"
            diff_path.write_text(_unified_diff(input_path, staging), encoding="utf-8")
            report_path = staging / "migration_report.html"
            _write_brain_report(report_path, metadata, tuple(findings))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            staging.replace(output_path)
            metadata_path = output_path / metadata_path.name
            report_path = output_path / "migration_report.html"
            diff_path = output_path / "migration.diff"
            report("Brain migration complete", 100)
            return BrainMigrationResult(
                output_path,
                tuple(changes),
                metadata_path,
                state,
                issues,
                report_path,
                diff_path,
                tuple(findings),
            )
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
