from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import json
from datetime import datetime, timezone

from odoo_migrator.core.planner import MigrationPlan, build_plan
from .base import Change, MigrationRule
from .rules.manifest_version import ManifestVersionRule


@dataclass(frozen=True, slots=True)
class MigrationResult:
    output: Path
    plan: MigrationPlan
    changes: tuple[Change, ...]
    metadata_path: Path | None = None


class MigrationEngine:
    def rules_for(self, source: int, target: int) -> list[MigrationRule]:
        return [ManifestVersionRule(source, target)]

    def migrate(self, input_root: Path, output_root: Path, source: int, target: int, dry_run: bool = False) -> MigrationResult:
        input_root = Path(input_root).resolve()
        output_root = Path(output_root).resolve()
        if input_root == output_root:
            raise ValueError("Output directory must differ from input directory.")
        if not input_root.is_dir():
            raise ValueError(f"Input directory does not exist: {input_root}")
        plan = build_plan(source, target)

        work_root = input_root
        if not dry_run:
            if output_root.exists():
                raise FileExistsError(f"Output already exists: {output_root}")
            shutil.copytree(input_root, output_root)
            work_root = output_root

        changes: list[Change] = []
        for step in plan.steps:
            for rule in self.rules_for(step.source, step.target):
                changes.extend(rule.apply(work_root, dry_run=dry_run))
        metadata_path = None
        if not dry_run:
            metadata_path = output_root / ".odoo_migrator_run.json"
            metadata_path.write_text(json.dumps({
                "tool_version": "0.1.0",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_version": plan.source,
                "target_version": plan.target,
                "migration_path": [step.key for step in plan.steps],
                "changes": [
                    {"rule_id": c.rule_id, "path": c.path.relative_to(output_root).as_posix(), "description": c.description}
                    for c in changes
                ],
            }, indent=2), encoding="utf-8")
        return MigrationResult(output_root if not dry_run else input_root, plan, tuple(changes), metadata_path)
