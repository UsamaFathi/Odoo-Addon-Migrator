from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from collections.abc import Callable, Mapping

from odoo_migrator.analysis.compat import Finding, compare_custom_to_target, deduplicate_findings
from odoo_migrator.analysis.project import ProjectScan, scan_custom_addons
from odoo_migrator.core.planner import MigrationPlan, build_plan
from odoo_migrator.migrations.engine import MigrationEngine, MigrationResult
from odoo_migrator.migrations.autonomous import autonomous_resolvers_for
from odoo_migrator.sources.indexer import SourceIndexer
from odoo_migrator.sources.manager import SourceManager, SourceManagerError
from odoo_migrator.sources.registry import SourceMode, SourceSelection, SourceSnapshot
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
    resolved_findings: tuple[Finding, ...] = ()
    resolution_passes: int = 0

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
    initial_findings: tuple[Finding, ...] = ()
    resolved_findings: tuple[Finding, ...] = ()
    resolution_passes: int = 0


class AnalysisService:
    def __init__(self, registry: MigrationPackRegistry | None = None, source_manager: SourceManager | None = None):
        self.registry = registry or default_registry()
        self.source_manager = source_manager

    def source_status(self, source: int, target: int, manager: SourceManager | None = None,
                     source_selections: Mapping[int, SourceSelection] | None = None) -> dict[int, SourceSnapshot | None]:
        """Read source readiness without downloading or updating official caches."""
        manager = manager or self.source_manager or SourceManager()
        snapshot = getattr(manager, "snapshot", None)
        statuses = {}
        for version in range(source, target + 1):
            selection = (source_selections or {}).get(version)
            if selection and selection.mode is SourceMode.LOCAL_EXACT_SOURCE:
                try:
                    value = manager.resolve_selection(selection)
                except SourceManagerError:
                    value = None
            elif selection and selection.mode is not SourceMode.VERIFIED_SNAPSHOT:
                value = snapshot(version, mode=selection.mode) if snapshot else None
            else:
                value = snapshot(version) if snapshot else None
            if value is not None and value.source_mode.value == "verified_snapshot" and value.expected_commit != value.actual_commit:
                value = None
            statuses[version] = value
        return statuses

    def _collect_step_findings(self, custom_index, source_index, target_index, diff, pack, step_key: str,
                               report: Callable[[str, int], None] | None = None) -> tuple[Finding, ...]:
        findings = [
            replace(item, migration_step=item.migration_step or step_key)
            for item in compare_custom_to_target(custom_index, source_index, target_index)
        ]
        analyzer_names = ("Python / ORM", "Dependencies", "XML / views", "Security", "Frontend", "Reports / QWeb")
        for index, analyzer in enumerate(pack.analyzers):
            if report:
                report(f"Analyzing {analyzer_names[index] if index < len(analyzer_names) else 'compatibility'} ({step_key})", 45 + index * 7)
            findings.extend(
                replace(item, migration_step=item.migration_step or step_key)
                for item in analyzer(custom_index, source_index, target_index, diff)
            )
        return deduplicate_findings(findings)

    def analyze(self, root: Path, source: int, target: int, manager: SourceManager | None = None,
                progress: Callable[[str, int], None] | None = None,
                source_selections: Mapping[int, SourceSelection] | None = None) -> AnalysisResult:
        def report(stage: str, percent: int) -> None:
            if progress:
                progress(stage, percent)

        manager = manager or self.source_manager or SourceManager()
        report("Validating migration path", 2)
        plan = build_plan(source, target)
        self.registry.require_plan(plan.steps)
        report("Scanning custom addons", 8)
        report("Checking local Odoo sources", 10)
        scan = scan_custom_addons(root); indexer = SourceIndexer()
        snapshots = {}
        for offset, version in enumerate(range(source, target + 1)):
            selection = (source_selections or {}).get(version)
            snapshot_reader = getattr(manager, "snapshot", None)
            cached = None
            if selection and selection.mode is SourceMode.LOCAL_EXACT_SOURCE:
                report(f"Using local Odoo {version} source", 12 + offset * 6)
                snapshots[version] = manager.resolve_selection(selection)
            else:
                selected_mode = selection.mode if selection else SourceMode.VERIFIED_SNAPSHOT
                cached = snapshot_reader(version, mode=selected_mode) if snapshot_reader else None
                if cached is None:
                    report(f"Downloading Odoo {version} verified snapshot", 12 + offset * 6)
                else:
                    report(f"Odoo {version} verified snapshot ready locally", 12 + offset * 6)
                snapshots[version] = manager.resolve_selection(selection) if selection else manager.ensure(version)
            report(f"Preparing Odoo {version}", 15 + offset * 6)
        indexes = {}
        for offset, version in enumerate(snapshots):
            report(f"Indexing Odoo {version}", 30 + offset * 4)
            indexes[version] = indexer.index(
                snapshots[version].path,
                source_commit=snapshots[version].actual_commit,
                source_mode=snapshots[version].source_mode.value,
                source_version=version,
            )
        report("Official source indexes ready", 42)
        findings = []
        resolved_findings = []
        step_results = []
        candidates = []
        candidate_keys: set[tuple[str, str, str]] = set()
        total_resolution_passes = 0
        with tempfile.TemporaryDirectory(prefix="odoo-migrator-plan-") as staging:
            planning_root = Path(staging) / "project"
            shutil.copytree(scan.root, planning_root)
            cache_dir = Path(staging) / "indexes"
            for step in plan.steps:
                step_key = step.key
                before = indexer.project_fingerprint(planning_root)
                diff = compare_indexes(indexes[step.source], indexes[step.target])
                pack = self.registry.require(step.source, step.target)

                custom_index = indexer.index(planning_root, cache_dir=cache_dir)
                initial_findings = self._collect_step_findings(
                    custom_index, indexes[step.source], indexes[step.target], diff, pack, step_key, report
                )

                step_candidates = []
                passes = 0
                for pass_index in range(3):
                    report(f"Applying automatic fixes ({step_key}) · pass {pass_index + 1}", min(94, 82 + pass_index * 4))
                    round_before = indexer.project_fingerprint(planning_root)
                    changed = False
                    for rule in pack.rule_factory():
                        if not rule.automatic:
                            continue
                        proposed_changes = rule.apply(planning_root, dry_run=True)
                        if not proposed_changes:
                            continue
                        changed = True
                        for change in proposed_changes:
                            relative = change.path.relative_to(planning_root).as_posix()
                            key = (change.rule_id, relative, step_key)
                            if key in candidate_keys:
                                continue
                            candidate_keys.add(key)
                            candidate = AutoFixCandidate(change.rule_id, relative, change.description, step_key)
                            candidates.append(candidate)
                            step_candidates.append(candidate)
                        rule.apply(planning_root, dry_run=False)

                    resolver_index = indexer.index(planning_root, cache_dir=cache_dir)
                    for resolver in autonomous_resolvers_for(step.source, step.target):
                        proposed_changes = resolver.apply(
                            planning_root,
                            resolver_index,
                            indexes[step.source],
                            indexes[step.target],
                            diff,
                            dry_run=True,
                        )
                        if not proposed_changes:
                            continue
                        changed = True
                        for change in proposed_changes:
                            relative = change.path.relative_to(planning_root).as_posix()
                            key = (change.rule_id, relative, step_key)
                            if key in candidate_keys:
                                continue
                            candidate_keys.add(key)
                            candidate = AutoFixCandidate(change.rule_id, relative, change.description, step_key)
                            candidates.append(candidate)
                            step_candidates.append(candidate)
                        resolver.apply(
                            planning_root,
                            resolver_index,
                            indexes[step.source],
                            indexes[step.target],
                            diff,
                            dry_run=False,
                        )
                        resolver_index = indexer.index(planning_root, cache_dir=cache_dir)
                    round_after = indexer.project_fingerprint(planning_root)
                    if not changed or round_after == round_before:
                        break
                    passes += 1

                total_resolution_passes += passes
                after = indexer.project_fingerprint(planning_root)
                post_index = indexer.index(planning_root, cache_dir=cache_dir)
                post_findings = self._collect_step_findings(
                    post_index, indexes[step.source], indexes[step.target], diff, pack, step_key
                )
                remaining_identities = {finding.identity for finding in post_findings}
                resolved = tuple(
                    finding for finding in initial_findings
                    if finding.identity not in remaining_identities
                )
                resolved_findings.extend(resolved)
                findings.extend(post_findings)
                step_results.append(AdjacentAnalysis(
                    step.source,
                    step.target,
                    snapshots[step.source],
                    snapshots[step.target],
                    diff,
                    tuple(post_findings),
                    tuple(step_candidates),
                    before,
                    after,
                    tuple(initial_findings),
                    resolved,
                    passes,
                ))
        findings = deduplicate_findings(findings)
        resolved_findings = deduplicate_findings(resolved_findings)
        report("Analysis complete", 100)
        return AnalysisResult(
            scan,
            plan,
            snapshots[source],
            snapshots[target],
            findings,
            tuple(candidates),
            tuple(step_results),
            tuple(resolved_findings),
            total_resolution_passes,
        )


class MigrationService:
    def __init__(self, registry: MigrationPackRegistry | None = None):
        self.registry = registry or default_registry()

    def migrate(self, root: Path, output: Path, analysis: AnalysisResult, dry_run: bool = False,
                progress: Callable[[str, int], None] | None = None) -> MigrationResult:
        if analysis.blockers:
            raise ValueError("Migration is blocked until all blocker findings are resolved.")
        self.registry.require_plan(analysis.plan.steps)
        ordered_snapshots = [step.source_snapshot for step in analysis.steps]
        ordered_snapshots.append(analysis.steps[-1].target_snapshot if analysis.steps else analysis.target_snapshot)
        return MigrationEngine(self.registry).migrate(root, output, analysis.plan.source, analysis.plan.target,
                                         dry_run=dry_run,
                                         source_snapshot=analysis.source_snapshot,
                                         target_snapshot=analysis.target_snapshot,
                                         source_snapshots=tuple(ordered_snapshots),
                                         findings=analysis.findings,
                                         modules_analyzed=analysis.scan.module_count,
                                         progress=progress)
