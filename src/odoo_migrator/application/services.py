from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from odoo_migrator.analysis.compat import Finding, compare_custom_to_target
from odoo_migrator.analysis.project import ProjectScan, scan_custom_addons
from odoo_migrator.core.planner import MigrationPlan, build_plan
from odoo_migrator.migrations.engine import MigrationEngine, MigrationResult
from odoo_migrator.sources.indexer import SourceIndexer
from odoo_migrator.sources.manager import SourceManager
from odoo_migrator.sources.registry import SourceSnapshot
from odoo_migrator.sources.diff import compare_indexes
from odoo_migrator.migrations.v14_to_v15 import python as v15_python, xml as v15_xml, security as v15_security, frontend as v15_frontend, reports as v15_reports


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    scan: ProjectScan
    plan: MigrationPlan
    source_snapshot: SourceSnapshot
    target_snapshot: SourceSnapshot
    findings: tuple[Finding, ...]
    auto_fix_candidates: tuple["AutoFixCandidate", ...] = ()

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


class AnalysisService:
    def analyze(self, root: Path, source: int, target: int, manager: SourceManager | None = None) -> AnalysisResult:
        manager = manager or SourceManager()
        src = manager.ensure(source); dst = manager.ensure(target)
        scan = scan_custom_addons(root); indexer = SourceIndexer()
        source_index = indexer.index(src.path, source_commit=src.commit)
        target_index = indexer.index(dst.path, source_commit=dst.commit)
        findings = list(compare_custom_to_target(scan.index, source_index, target_index))
        if (source, target) == (14, 15):
            diff = compare_indexes(source_index, target_index)
            findings.extend(v15_python.analyze(scan.index, source_index, target_index, diff))
            findings.extend(v15_xml.analyze(scan.index, source_index, target_index))
            findings.extend(v15_security.analyze(scan.index, target_index))
            findings.extend(v15_frontend.analyze(scan.index))
            findings.extend(v15_reports.analyze(scan.index, target_index))
        unique = {}
        for item in findings:
            identity = (item.module, item.object_name or item.code, item.path, item.line)
            current = unique.get(identity)
            if current is None or (item.rule_id and not current.rule_id):
                unique[identity] = item
        findings = tuple(unique.values())
        plan = build_plan(source, target); engine = MigrationEngine(); candidates = []
        for step in plan.steps:
            for rule in engine.rules_for(step.source, step.target):
                if rule.automatic:
                    candidates.extend(AutoFixCandidate(change.rule_id, str(change.path), change.description)
                                      for change in rule.apply(scan.root, dry_run=True))
        return AnalysisResult(scan, plan, src, dst, findings, tuple(candidates))


class MigrationService:
    def migrate(self, root: Path, output: Path, analysis: AnalysisResult, dry_run: bool = False) -> MigrationResult:
        if analysis.blockers:
            raise ValueError("Migration is blocked until all blocker findings are resolved.")
        return MigrationEngine().migrate(root, output, analysis.plan.source, analysis.plan.target,
                                         dry_run=dry_run,
                                         source_snapshot=analysis.source_snapshot,
                                         target_snapshot=analysis.target_snapshot)
