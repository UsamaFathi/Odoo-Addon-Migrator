from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from odoo_migrator.analysis.compat import Finding, compare_custom_to_target, deduplicate_findings
from odoo_migrator.analysis.project import ProjectScan, scan_custom_addons
from odoo_migrator.core.planner import MigrationPlan, build_plan
from odoo_migrator.migrations.engine import MigrationEngine, MigrationResult
from odoo_migrator.sources.indexer import SourceIndexer
from odoo_migrator.sources.manager import SourceManager
from odoo_migrator.sources.registry import SourceSnapshot
from odoo_migrator.sources.diff import compare_indexes
from odoo_migrator.migrations.registry import default_registry
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


@dataclass(frozen=True, slots=True)
class AdjacentAnalysis:
    source: int
    target: int
    source_snapshot: SourceSnapshot
    target_snapshot: SourceSnapshot
    source_diff: object
    findings: tuple[Finding, ...]


class AnalysisService:
    def analyze(self, root: Path, source: int, target: int, manager: SourceManager | None = None) -> AnalysisResult:
        manager = manager or SourceManager()
        plan = build_plan(source, target); scan = scan_custom_addons(root); indexer = SourceIndexer(); registry = default_registry()
        snapshots = {version: manager.ensure(version) for version in range(source, target + 1)}
        indexes = {version: indexer.index(snapshots[version].path, source_commit=snapshots[version].commit) for version in snapshots}
        findings = list(compare_custom_to_target(scan.index, indexes[source], indexes[target])); step_results = []
        for step in plan.steps:
            diff = compare_indexes(indexes[step.source], indexes[step.target])
            step_findings = []
            pack = registry.get(step.source, step.target)
            if pack:
                for analyzer in pack.analyzers:
                    step_findings.extend(analyzer(scan.index, indexes[step.source], indexes[step.target], diff))
            step_results.append(AdjacentAnalysis(step.source, step.target, snapshots[step.source], snapshots[step.target], diff, tuple(step_findings)))
            findings.extend(step_findings)
        findings = deduplicate_findings(findings)
        engine = MigrationEngine(); candidates = []
        with tempfile.TemporaryDirectory(prefix="odoo-migrator-plan-") as staging:
            planning_root = Path(staging) / "project"; shutil.copytree(scan.root, planning_root)
            for step in plan.steps:
                for rule in engine.rules_for(step.source, step.target):
                    changes = rule.apply(planning_root, dry_run=True)
                    if rule.automatic:
                        candidates.extend(AutoFixCandidate(change.rule_id, change.path.relative_to(planning_root).as_posix(), change.description) for change in changes)
                    rule.apply(planning_root, dry_run=False)
        return AnalysisResult(scan, plan, snapshots[source], snapshots[target], findings, tuple(candidates), tuple(step_results))


class MigrationService:
    def migrate(self, root: Path, output: Path, analysis: AnalysisResult, dry_run: bool = False) -> MigrationResult:
        if analysis.blockers:
            raise ValueError("Migration is blocked until all blocker findings are resolved.")
        return MigrationEngine().migrate(root, output, analysis.plan.source, analysis.plan.target,
                                         dry_run=dry_run,
                                         source_snapshot=analysis.source_snapshot,
                                         target_snapshot=analysis.target_snapshot)
