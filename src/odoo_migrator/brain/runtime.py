from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from tempfile import mkdtemp
from collections.abc import Callable

from odoo_migrator.core.planner import build_plan
from odoo_migrator.migrations.autonomous import (
    DependencyModuleRenameResolver,
    MethodRenameResolver,
    ModelRenameResolver,
)
from odoo_migrator.migrations.base import Change
from odoo_migrator.migrations.registry import MigrationPackRegistry, default_registry
from odoo_migrator.validation import ValidationItem, validate_project

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

        try:
            for index, step in enumerate(plan.steps):
                key = step.key
                learned = self.brain.step(step.source, step.target)
                report(
                    f"Brain migration {step.source} -> {step.target}",
                    10 + int(index / max(1, len(plan.steps)) * 70),
                )

                allowed_rules = set(learned.get("automatic_rules", ()))
                for rule in self.registry.require(step.source, step.target).rule_factory():
                    if rule.automatic and rule.rule_id in allowed_rules:
                        changes.extend(rule.apply(staging, dry_run=False))

                _apply_dependency_mappings(
                    staging,
                    list(learned.get("dependency_renames", ())),
                    key,
                    changes,
                )
                _apply_model_mappings(
                    staging,
                    list(learned.get("model_renames", ())),
                    key,
                    changes,
                )
                _cleanup_shadow_files(staging)
                _apply_method_mappings(
                    staging,
                    list(learned.get("method_renames", ())),
                    key,
                    changes,
                )

            report("Validating Brain-migrated output", 88)
            issues = tuple(validate_project(staging))
            state = "passed" if not issues else "failed"

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
                "validation": {
                    "state": state,
                    "issues": [asdict(item) for item in issues],
                },
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
            output_path.parent.mkdir(parents=True, exist_ok=True)
            staging.replace(output_path)
            metadata_path = output_path / metadata_path.name
            report("Brain migration complete", 100)
            return BrainMigrationResult(
                output_path,
                tuple(changes),
                metadata_path,
                state,
                issues,
            )
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
