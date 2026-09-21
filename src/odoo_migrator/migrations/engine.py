from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import json
from datetime import datetime, timezone
from tempfile import mkdtemp
import os
import shutil as _shutil
from odoo_migrator import __version__
from odoo_migrator.sources.registry import SourceSnapshot

from odoo_migrator.core.planner import MigrationPlan, build_plan
from .base import Change, MigrationRule
from .rules.manifest_version import ManifestVersionRule
from .v14_to_v15.manifest import Manifest14To15Rule
from .registry import default_registry


@dataclass(frozen=True, slots=True)
class MigrationResult:
    output: Path
    plan: MigrationPlan
    changes: tuple[Change, ...]
    metadata_path: Path | None = None


class MigrationEngine:
    def rules_for(self, source: int, target: int) -> list[MigrationRule]:
        pack = default_registry().get(source, target)
        if pack:
            return pack.rule_factory()
        return [ManifestVersionRule(source, target)]

    def migrate(self, input_root: Path, output_root: Path, source: int, target: int,
                dry_run: bool = False, source_snapshot: SourceSnapshot | None = None,
                target_snapshot: SourceSnapshot | None = None) -> MigrationResult:
        input_root = Path(input_root).resolve()
        output_root = Path(output_root).resolve()
        if input_root == output_root:
            raise ValueError("Output directory must differ from input directory.")
        if not input_root.is_dir():
            raise ValueError(f"Input directory does not exist: {input_root}")
        if input_root in output_root.parents:
            raise ValueError("Output directory cannot be inside the input directory.")
        if output_root in input_root.parents:
            raise ValueError("Input directory cannot be inside the output directory.")
        if any(path.is_symlink() for path in (input_root, output_root)):
            raise ValueError("Input and output directories must not be symbolic links.")
        internal_links = [path for path in input_root.rglob("*") if path.is_symlink()]
        if internal_links:
            raise ValueError(f"Input contains symbolic links, which are not migrated: {internal_links[0]}")
        if not output_root.parent.is_dir():
            raise ValueError(f"Output parent directory does not exist: {output_root.parent}")
        plan = build_plan(source, target)

        work_root = input_root
        staging_root = None
        if not dry_run:
            if output_root.exists():
                raise FileExistsError(f"Output already exists: {output_root}")
            staging_root = Path(mkdtemp(prefix=f".{output_root.name}.", dir=str(output_root.parent)))
            _shutil.rmtree(staging_root)
            shutil.copytree(input_root, staging_root, symlinks=False)
            work_root = staging_root

        changes: list[Change] = []
        try:
            for step in plan.steps:
                for rule in self.rules_for(step.source, step.target):
                    changes.extend(rule.apply(work_root, dry_run=dry_run))
        except Exception:
            if staging_root and staging_root.exists():
                shutil.rmtree(staging_root, ignore_errors=True)
            raise
        metadata_path = None
        if not dry_run:
            metadata_path = work_root / ".odoo_migrator_run.json"
            metadata_path.write_text(json.dumps({
                "tool_version": __version__,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "input_path": str(input_root),
                "output_path": str(output_root),
                "source_version": plan.source,
                "target_version": plan.target,
                "migration_path": [step.key for step in plan.steps],
                "source_snapshot": source_snapshot.as_dict() if source_snapshot else None,
                "target_snapshot": target_snapshot.as_dict() if target_snapshot else None,
                "validation": {"state": "not_run", "level": 0},
                "rules": sorted({c.rule_id for c in changes}),
                "changes": [
                    {"rule_id": c.rule_id, "path": c.path.relative_to(work_root).as_posix(), "description": c.description}
                    for c in changes
                ],
            }, indent=2), encoding="utf-8")
            os.replace(work_root, output_root)
            metadata_path = output_root / ".odoo_migrator_run.json"
        return MigrationResult(output_root if not dry_run else input_root, plan, tuple(changes), metadata_path)
