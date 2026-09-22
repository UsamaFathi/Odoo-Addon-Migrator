from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from odoo_migrator.application.services import AnalysisResult
from odoo_migrator.migrations.engine import MigrationResult
from odoo_migrator.analysis.project import ProjectScan


class WorkflowPhase(str, Enum):
    PROJECT = "project"
    ANALYZE = "analyze"
    REVIEW = "review"
    MIGRATE = "migrate"
    VALIDATE = "validate"
    RESULTS = "results"


@dataclass
class ApplicationState:
    phase: WorkflowPhase = WorkflowPhase.PROJECT
    project_root: Path | None = None
    output_root: Path | None = None
    source_version: int | None = None
    target_version: int | None = None
    scan: ProjectScan | None = None
    analysis: AnalysisResult | None = None
    migration: MigrationResult | None = None
    operation_token: int = 0
    last_error: str | None = None
    status: str = "Ready to select a project"
    _extra: dict[str, Any] = field(default_factory=dict, repr=False)

    def begin_operation(self, operation: str | None = None) -> int:
        self.operation_token += 1
        if operation == "analysis":
            self.phase = WorkflowPhase.ANALYZE
        elif operation == "migration":
            self.phase = WorkflowPhase.MIGRATE
        return self.operation_token

    def reset_project(self, root: Path | None = None) -> None:
        self.project_root = root.resolve() if root else None
        self.output_root = None
        self.scan = None
        self.analysis = None
        self.migration = None
        self.phase = WorkflowPhase.PROJECT
        self.last_error = None

    def set_scan(self, scan: ProjectScan) -> None:
        self.scan = scan
        self.analysis = None
        self.migration = None
        self.phase = WorkflowPhase.PROJECT

    def set_versions(self, source: int, target: int | None) -> None:
        self.source_version = source
        self.target_version = target
        self.analysis = None
        self.migration = None

    def set_output_root(self, output: Path | None) -> None:
        self.output_root = output.resolve() if output else None

    def set_analysis(self, analysis: AnalysisResult) -> None:
        self.analysis = analysis
        self.source_version = analysis.plan.source
        self.target_version = analysis.plan.target
        self.phase = WorkflowPhase.REVIEW

    def set_migration(self, migration: MigrationResult) -> None:
        self.migration = migration
        self.output_root = migration.output
        self.phase = WorkflowPhase.RESULTS

    @property
    def can_migrate(self) -> bool:
        return bool(self.analysis and not self.analysis.blockers and self.output_root)

    @property
    def is_stale(self) -> bool:
        if not self.analysis or not self.project_root:
            return True
        return (self.analysis.scan.root != self.project_root
                or self.analysis.plan.source != self.source_version
                or self.analysis.plan.target != self.target_version)


def suggested_output_path(root: Path, target: int) -> Path:
    return root.parent / f"{root.name}_{target}"


def finding_counts(analysis: AnalysisResult | None) -> dict[str, int]:
    counts = {"auto_fix": 0, "blocker": 0, "review_required": 0, "warning": 0}
    if not analysis:
        return counts
    counts["auto_fix"] = len(analysis.auto_fix_candidates)
    for finding in analysis.findings:
        key = finding.severity.value
        if key in counts:
            counts[key] += 1
    return counts
