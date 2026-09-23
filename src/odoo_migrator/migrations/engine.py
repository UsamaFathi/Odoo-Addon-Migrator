from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import shutil
import json
import difflib
import html
from datetime import datetime, timezone
from tempfile import mkdtemp
import os
import shutil as _shutil
from collections.abc import Callable, Iterable, Mapping
from odoo_migrator import __version__
from odoo_migrator.sources.registry import SourceSnapshot
from odoo_migrator.sources.indexer import SourceIndexer
from odoo_migrator.sources.diff import compare_indexes
from odoo_migrator.sources.composite import compose_indexes
from odoo_migrator.sources.enterprise import validate_enterprise_tree
from odoo_migrator.validation import ValidationItem, validate_project

from odoo_migrator.core.planner import MigrationPlan, build_plan
from .base import Change, MigrationRule
from .registry import MigrationPackRegistry, default_registry
from .autonomous import autonomous_resolvers_for


@dataclass(frozen=True, slots=True)
class MigrationResult:
    output: Path
    plan: MigrationPlan
    changes: tuple[Change, ...]
    metadata_path: Path | None = None
    report_path: Path | None = None
    diff_path: Path | None = None
    validation_state: str = "not_run"
    validation_issues: tuple[ValidationItem, ...] = ()


class MigrationEngine:
    def __init__(self, registry: MigrationPackRegistry | None = None):
        self.registry = registry or default_registry()

    def rules_for(self, source: int, target: int) -> list[MigrationRule]:
        return self.registry.require(source, target).rule_factory()

    def migrate(self, input_root: Path, output_root: Path, source: int, target: int,
                dry_run: bool = False, source_snapshot: SourceSnapshot | None = None,
                target_snapshot: SourceSnapshot | None = None,
                source_snapshots: Iterable[SourceSnapshot] | None = None,
                findings: Iterable[object] = (), modules_analyzed: int | None = None,
                enterprise_sources: Mapping[int, str | Path] | None = None,
                progress: Callable[[str, int], None] | None = None) -> MigrationResult:
        def report(stage: str, percent: int) -> None:
            if progress:
                progress(stage, percent)

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
        self.registry.require_plan(plan.steps)

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
        planned_rules = [rule for step in plan.steps for rule in self.rules_for(step.source, step.target)]
        planned_resolvers = [resolver for step in plan.steps for resolver in autonomous_resolvers_for(step.source, step.target)]
        snapshot_tuple = tuple(source_snapshots or ())
        snapshot_map = {snapshot.version: snapshot for snapshot in snapshot_tuple}
        if source_snapshot is not None:
            snapshot_map.setdefault(source_snapshot.version, source_snapshot)
        if target_snapshot is not None:
            snapshot_map.setdefault(target_snapshot.version, target_snapshot)
        source_indexes = {}
        indexer = SourceIndexer()
        for version, snapshot in snapshot_map.items():
            source_indexes[version] = indexer.index(
                snapshot.path,
                source_commit=snapshot.actual_commit,
                source_mode=snapshot.source_mode.value,
                source_version=version,
            )
            enterprise_path = (enterprise_sources or {}).get(version)
            if enterprise_path:
                enterprise_root = validate_enterprise_tree(enterprise_path)
                enterprise_index = indexer.index(
                    enterprise_root,
                    cache_dir=Path.home() / ".odoo-addon-migrator" / "enterprise-indexes",
                    source_mode="enterprise_local",
                    source_version=version,
                )
                source_indexes[version] = compose_indexes(source_indexes[version], enterprise_index)
        try:
            report("Creating safe output copy", 5)
            for step in plan.steps:
                report(f"Applying {step.source}→{step.target} fixes", 15 + plan.steps.index(step) * 12)
                for rule in self.rules_for(step.source, step.target):
                    if rule.automatic:
                        changes.extend(rule.apply(work_root, dry_run=dry_run))
                if step.source in source_indexes and step.target in source_indexes:
                    custom_index = indexer.index(work_root)
                    diff = compare_indexes(source_indexes[step.source], source_indexes[step.target])
                    for resolver in autonomous_resolvers_for(step.source, step.target):
                        changes.extend(resolver.apply(
                            work_root,
                            custom_index,
                            source_indexes[step.source],
                            source_indexes[step.target],
                            diff,
                            dry_run=dry_run,
                        ))
                        if not dry_run:
                            custom_index = indexer.index(work_root)
        except Exception:
            if staging_root and staging_root.exists():
                shutil.rmtree(staging_root, ignore_errors=True)
            raise
        metadata_path = None
        report_path = None
        diff_path = None
        validation_state = "not_run"
        validation_issues: tuple[ValidationItem, ...] = ()
        if not dry_run:
            report("Writing migration metadata and diff", 82)
            diff_path = work_root / "migration.diff"
            diff_path.write_text(_unified_diff(input_root, work_root), encoding="utf-8")
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
                "source_snapshots": [snapshot.as_dict() for snapshot in snapshot_tuple],
                "enterprise_sources": {
                    str(version): str(validate_enterprise_tree(path))
                    for version, path in sorted((enterprise_sources or {}).items())
                },
                "validation": {"state": "not_run", "level": 0},
                "rules": sorted({c.rule_id for c in changes}),
                "rule_versions": {
                    **{
                        rule.rule_id: {
                            "source": rule.source,
                            "target": rule.target,
                            "classification": rule.classification.value,
                            "automatic": rule.automatic,
                        }
                        for rule in planned_rules
                    },
                    **{
                        resolver.rule_id: {
                            "source": resolver.source,
                            "target": resolver.target,
                            "classification": "safe_auto_fix",
                            "automatic": True,
                            "autonomous": True,
                            "confidence": resolver.confidence,
                        }
                        for resolver in planned_resolvers
                    },
                },
                "changes": [
                    {"rule_id": c.rule_id, "path": c.path.relative_to(work_root).as_posix(), "description": c.description,
                     "migration_step": c.migration_step}
                    for c in changes
                ],
            }, indent=2), encoding="utf-8")
            os.replace(work_root, output_root)
            metadata_path = output_root / ".odoo_migrator_run.json"
            report("Validating migrated output", 92)
            validation = validate_project(output_root)
            validation_state = "passed" if not validation else "failed"
            validation_issues = tuple(validation)
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["validation"] = {
                "state": validation_state,
                "level": 1,
                "issues": [asdict(item) for item in validation],
            }
            metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            report_path = output_root / "migration_report.html"
            _write_html_report(report_path, metadata, findings, modules_analyzed)
            diff_path = output_root / "migration.diff"
            report("Migration complete", 100)
        return MigrationResult(output_root if not dry_run else input_root, plan, tuple(changes), metadata_path,
                               report_path, diff_path, validation_state, validation_issues)


def _relative_files(root: Path) -> set[str]:
    ignored = {".odoo_migrator_run.json", "migration_report.html", "migration.diff"}
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name not in ignored and ".git" not in path.parts
    }


def _unified_diff(before: Path, after: Path) -> str:
    chunks: list[str] = []
    for relative in sorted(_relative_files(before) | _relative_files(after)):
        old_path, new_path = before / relative, after / relative
        old = old_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if old_path.exists() else []
        new = new_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if new_path.exists() else []
        if old != new:
            chunks.extend(difflib.unified_diff(old, new, fromfile=f"a/{relative}", tofile=f"b/{relative}"))
    return "".join(chunks)


def _write_html_report(path: Path, metadata: dict, findings: Iterable[object], modules_analyzed: int | None) -> None:
    source = metadata.get("source_snapshot") or {}
    target = metadata.get("target_snapshot") or {}
    source_mode = html.escape(str(source.get("source_mode", "unknown")))
    target_mode = html.escape(str(target.get("source_mode", "unknown")))
    source_path = html.escape(str(source.get("path", "")))
    target_path = html.escape(str(target.get("path", "")))
    source_commit = html.escape(str(source.get("actual_commit") or source.get("commit") or "unavailable"))
    target_commit = html.escape(str(target.get("actual_commit") or target.get("commit") or "unavailable"))
    source_rows = []
    for snapshot in metadata.get("source_snapshots", ()):
        source_rows.append("<tr>" + "".join(f"<td>{html.escape(str(value or 'unavailable'))}</td>" for value in (
            snapshot.get("version"), snapshot.get("source_mode"), snapshot.get("path"), snapshot.get("actual_commit") or snapshot.get("commit"), snapshot.get("branch"), snapshot.get("origin"),
        )) + "</tr>")
    finding_rows = []
    for finding in findings:
        finding_rows.append(
            "<tr>" + "".join(f"<td>{html.escape(str(value or ''))}</td>" for value in (
                getattr(finding, "severity", ""), getattr(finding, "migration_step", ""),
                getattr(finding, "module", ""), getattr(finding, "path", ""),
                getattr(finding, "line", ""), getattr(finding, "rule_id", ""),
                getattr(finding, "message", ""),
            )) + "</tr>"
        )
    if not finding_rows:
        finding_rows.append('<tr><td colspan="7">No compatibility findings were reported.</td></tr>')
    html_text = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Odoo Addon Migrator report</title>
<style>body{{font:14px Segoe UI,Arial,sans-serif;color:#172033;background:#f5f7fa;margin:0;padding:32px}}main{{max-width:1100px;margin:auto;background:white;padding:28px;border-radius:12px}}h1{{margin-top:0}}table{{border-collapse:collapse;width:100%;margin-top:18px}}th,td{{border:1px solid #d9dee8;padding:8px;text-align:left;vertical-align:top}}th{{background:#eef2f7}}.note{{background:#fff4d6;padding:12px;border-radius:8px}}</style></head>
<body><main><h1>Odoo Addon Migrator</h1><p><strong>Static migration report</strong></p>
<p>Source: Odoo {html.escape(str(metadata.get('source_version', '')))}<br>Mode: {source_mode}<br>Commit: {source_commit}<br>Path: {source_path}<br>
Target: Odoo {html.escape(str(metadata.get('target_version', '')))}<br>Mode: {target_mode}<br>Commit: {target_commit}<br>Path: {target_path}<br>
Path: {html.escape(' → '.join(metadata.get('migration_path', [])))}<br>
Modules analyzed: {html.escape(str(modules_analyzed if modules_analyzed is not None else 'unknown'))}<br>
Validation: {html.escape(str(metadata.get('validation', {}).get('state', 'unknown')))}</p>
<div class="note">Static validation and source analysis do not prove runtime compatibility. Review all findings and validate installation/tests separately.</div>
<h2>Source identities</h2><table><thead><tr><th>Version</th><th>Mode</th><th>Path</th><th>Commit</th><th>Branch</th><th>Origin</th></tr></thead><tbody>{''.join(source_rows) or '<tr><td colspan="6">Source identity details unavailable.</td></tr>'}</tbody></table>
<h2>Automatic changes</h2><p>{len(metadata.get('changes', []))} automatic change(s) applied.</p>
<h2>Findings</h2><table><thead><tr><th>Severity</th><th>Step</th><th>Addon</th><th>File</th><th>Line</th><th>Rule</th><th>Message</th></tr></thead><tbody>{''.join(finding_rows)}</tbody></table>
</main></body></html>"""
    path.write_text(html_text, encoding="utf-8")
