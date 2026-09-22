from __future__ import annotations

import ast
from pathlib import Path

from odoo_migrator.analysis.compat import Finding, Severity
from odoo_migrator.application.services import AnalysisService
from odoo_migrator.migrations.base import Change, Classification, MigrationRule
from odoo_migrator.migrations.registry import MigrationPack, MigrationPackRegistry
from odoo_migrator.sources.registry import SourceMode, SourceSnapshot


class _LegacyFlagRule(MigrationRule):
    def __init__(self):
        super().__init__(
            18,
            19,
            "test.legacy_flag",
            "manifest",
            Classification.SAFE_AUTO_FIX,
            "Remove a deterministic legacy manifest flag.",
            "test fixture",
            automatic=True,
        )

    def apply(self, root: Path, dry_run: bool = False) -> list[Change]:
        manifest = root / "demo" / "__manifest__.py"
        data = ast.literal_eval(manifest.read_text(encoding="utf-8"))
        if not data.get("legacy"):
            return []
        change = Change(self.rule_id, manifest, "Removed legacy manifest flag", "18_to_19")
        if not dry_run:
            data["legacy"] = False
            manifest.write_text(repr(data), encoding="utf-8")
        return [change]


def _legacy_analyzer(custom, source, target, diff):
    module = custom.modules.get("demo")
    if module and module.manifest.get("legacy"):
        return [
            Finding(
                Severity.BLOCKER,
                "manifest.legacy",
                "demo",
                "Legacy flag must be removed.",
                "__manifest__.py",
                rule_id="test.legacy_flag",
                migration_step="18_to_19",
                object_name="legacy",
            )
        ]
    return []


class _Manager:
    def __init__(self, snapshots):
        self.snapshots = snapshots

    def snapshot(self, version, mode=SourceMode.VERIFIED_SNAPSHOT):
        return self.snapshots[version]

    def ensure(self, version):
        return self.snapshots[version]


def _source(root: Path, version: int) -> SourceSnapshot:
    module = root / "base"
    module.mkdir(parents=True)
    (module / "__manifest__.py").write_text(repr({"name": "Base", "version": f"{version}.0.1.0.0"}), encoding="utf-8")
    return SourceSnapshot(version, f"{version}.0", "controlled://odoo", str(version), root)


def test_analysis_reanalyzes_after_automatic_fixes_and_drops_resolved_blocker(tmp_path: Path):
    custom = tmp_path / "custom"
    demo = custom / "demo"
    demo.mkdir(parents=True)
    original = {"name": "Demo", "version": "18.0.1.0.0", "legacy": True}
    (demo / "__manifest__.py").write_text(repr(original), encoding="utf-8")

    source = _source(tmp_path / "odoo18", 18)
    target = _source(tmp_path / "odoo19", 19)
    registry = MigrationPackRegistry()
    registry.register(MigrationPack(18, 19, analyzers=(_legacy_analyzer,), rule_factory=lambda: [_LegacyFlagRule()]))

    result = AnalysisService(registry, _Manager({18: source, 19: target})).analyze(custom, 18, 19)

    assert result.blockers == ()
    assert len(result.resolved_findings) == 1
    assert result.resolved_findings[0].code == "manifest.legacy"
    assert len(result.auto_fix_candidates) == 1
    assert result.resolution_passes >= 1
    assert result.steps[0].initial_findings[0].severity is Severity.BLOCKER
    assert result.steps[0].findings == ()
    # Analysis works on a planning copy only.
    assert ast.literal_eval((demo / "__manifest__.py").read_text(encoding="utf-8"))["legacy"] is True
