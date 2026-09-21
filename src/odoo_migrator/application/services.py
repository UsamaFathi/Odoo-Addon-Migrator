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


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    scan: ProjectScan
    plan: MigrationPlan
    source_snapshot: SourceSnapshot
    target_snapshot: SourceSnapshot
    findings: tuple[Finding, ...]


class ProjectScanService:
    def scan(self, root: Path) -> ProjectScan:
        return scan_custom_addons(root)


class AnalysisService:
    def analyze(self, root: Path, source: int, target: int, manager: SourceManager | None = None) -> AnalysisResult:
        manager = manager or SourceManager()
        src = manager.ensure(source); dst = manager.ensure(target)
        scan = scan_custom_addons(root); indexer = SourceIndexer()
        source_index = indexer.index(src.path, source_commit=src.commit)
        target_index = indexer.index(dst.path, source_commit=dst.commit)
        findings = tuple(compare_custom_to_target(scan.index, source_index, target_index))
        return AnalysisResult(scan, build_plan(source, target), src, dst, findings)


class MigrationService:
    def migrate(self, root: Path, output: Path, analysis: AnalysisResult) -> MigrationResult:
        return MigrationEngine().migrate(root, output, analysis.plan.source, analysis.plan.target,
                                         source_snapshot=analysis.source_snapshot,
                                         target_snapshot=analysis.target_snapshot)
