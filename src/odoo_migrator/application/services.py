from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from odoo_migrator.analysis.compat import Finding, compare_custom_to_target, deduplicate_findings
from odoo_migrator.analysis.project import ProjectScan, scan_custom_addons
from odoo_migrator.core.planner import MigrationPlan, build_plan
from odoo_migrator.migrations.engine import MigrationEngine, MigrationResult
from odoo_migrator.sources.indexer import SourceIndexer
from odoo_migrator.sources.manager import SourceManager
from odoo_migrator.sources.registry import SourceSnapshot
from odoo_migrator.sources.diff import compare_indexes
from odoo_migrator.migrations.registry import MigrationPackRegistry, default_registry
import tempfile
import shutil


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    scan: ProjectScan
    plan: MigrationPlan
    source_snapshot: SourceSnapshot
    target_snapshot: SourceSnapshot
    findings: tuple[Finding, ...]
    auto_fix_candidates: tuple["AutoFixCandidate", ...] = ()
    steps: tuple["AdjacentAnalysis", ...] = ()

    @property
    def blockers(self) -> tuple[Finding, ...]:
        return tuple(item for item in self.findings if item.severity.value == "blocker")

    @property
    def auto_fixable(self) -> tuple[Finding, ...]:
        return tuple()

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(item for item in self.findings if item.severity.value == "warning")

    @property
    def review_required(self) -> tuple[Finding, ...]:
        return tuple(item for item in self.findings if item.severity.value == "review_required")


class ProjectScanService:
    def scan(self, root: Path) -> ProjectScan:
        return scan_custom_addons(root)


@dataclass(frozen=True, slots=True)
class AutoFixCandidate:
    rule_id: str
    path: str
    description: str
    migration_step: str | None = None


@dataclass(frozen=True, slots=True)
class AdjacentAnalysis:
    source: int
    target: int
    source_snapshot: SourceSnapshot
    target_snapshot: SourceSnapshot
    source_diff: object
    findings: tuple[Finding, ...]
    auto_fix_candidates: tuple[AutoFixCandidate, ...] = ()
    custom_fingerprint_before: str = ""
    custom_fingerprint_after: str = ""


class AnalysisService:
    def __init__(self, registry: MigrationPackRegistry | None = None):
        self.registry = registry or default_registry()

    def analyze(self, root: Path, source: int, target: int, manager: SourceManager | None = None) -> AnalysisResult:
        manager = manager or SourceManager()
        plan = build_plan(source, target)
        self.registry.require_plan(plan.steps)
        scan = scan_custom_addons(root); indexer = SourceIndexer()
        snapshots = {version: manager.ensure(version) for version in range(source, target + 1)}
        indexes = {
            version: indexer.index(
                snapshots[version].path,
                source_commit=snapshots[version].actual_commit,
                source_mode=snapshots[version].source_mode.value,
                source_version=version,
            )
            for version in snapshots
        }
        findings = []; step_results = []; candidates = []; engine = MigrationEngine(self.registry)
        with tempfile.TemporaryDirectory(prefix="odoo-migrator-plan-") as staging:
            planning_root = Path(staging) / "project"; shutil.copytree(scan.root, planning_root)
            for step in plan.steps:
                step_key = step.key
                custom_index = indexer.index(planning_root, cache_dir=Path(staging) / "indexes")
                before = indexer.project_fingerprint(planning_root)
                diff = compare_indexes(indexes[step.source], indexes[step.target])
                step_findings = [replace(item, migration_step=item.migration_step or step_key)
                                 for item in compare_custom_to_target(custom_index, indexes[step.source], indexes[step.target])]
                pack = self.registry.require(step.source, step.target)
                for analyzer in pack.analyzers:
                    step_findings.extend(replace(item, migration_step=item.migration_step or step_key)
                                         for item in analyzer(custom_index, indexes[step.source], indexes[step.target], diff))
                step_candidates = []
                for rule in pack.rule_factory():
                    changes = rule.apply(planning_root, dry_run=True)
                    if rule.automatic:
                        proposed = [AutoFixCandidate(change.rule_id, change.path.relative_to(planning_root).as_posix(), change.description, step_key) for change in changes]
                        candidates.extend(proposed); step_candidates.extend(proposed)
                        rule.apply(planning_root, dry_run=False)
                after = indexer.project_fingerprint(planning_root)
                step_findings = list(deduplicate_findings(step_findings)); findings.extend(step_findings)
                step_results.append(AdjacentAnalysis(step.source, step.target, snapshots[step.source], snapshots[step.target], diff,
                    tuple(step_findings), tuple(step_candidates), before, after))
        findings = deduplicate_findings(findings)
        return AnalysisResult(scan, plan, snapshots[source], snapshots[target], findings, tuple(candidates), tuple(step_results))


class MigrationService:
    def __init__(self, registry: MigrationPackRegistry | None = None):
        self.registry = registry or default_registry()

    def migrate(self, root: Path, output: Path, analysis: AnalysisResult, dry_run: bool = False) -> MigrationResult:
        if analysis.blockers:
            raise ValueError("Migration is blocked until all blocker findings are resolved.")
        self.registry.require_plan(analysis.plan.steps)
        return MigrationEngine(self.registry).migrate(root, output, analysis.plan.source, analysis.plan.target,
                                         dry_run=dry_run,
                                         source_snapshot=analysis.source_snapshot,
                                         target_snapshot=analysis.target_snapshot)
