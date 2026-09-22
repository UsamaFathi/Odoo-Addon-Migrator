from __future__ import annotations

import ast
from pathlib import Path

from odoo_migrator.application.services import AnalysisService, MigrationService
from odoo_migrator.migrations.registry import MigrationPack, MigrationPackRegistry
from odoo_migrator.sources.registry import SourceMode, SourceSnapshot


def _module(root: Path, name: str, *, version: int, depends=(), model: str | None = None) -> None:
    module = root / name
    module.mkdir(parents=True)
    (module / "__manifest__.py").write_text(
        repr({"name": name, "version": f"{version}.0.1.0.0", "depends": list(depends)}),
        encoding="utf-8",
    )
    if model:
        (module / "models.py").write_text(
            "from odoo import models\n"
            "class Owned(models.Model):\n"
            f"    _name = {model!r}\n",
            encoding="utf-8",
        )


class _Manager:
    def __init__(self, snapshots):
        self.snapshots = snapshots

    def snapshot(self, version, mode=SourceMode.VERIFIED_SNAPSHOT):
        return self.snapshots[version]

    def ensure(self, version):
        return self.snapshots[version]


def _snapshot(version: int, root: Path) -> SourceSnapshot:
    return SourceSnapshot(version, f"{version}.0", "controlled://odoo", f"{version:040d}", root)


def _registry() -> MigrationPackRegistry:
    registry = MigrationPackRegistry()
    registry.register(MigrationPack(18, 19))
    return registry


def test_unique_official_model_owner_resolves_removed_dependency_and_replays_in_migration(tmp_path: Path):
    source_root = tmp_path / "odoo18"
    target_root = tmp_path / "odoo19"
    custom_root = tmp_path / "custom"
    _module(source_root, "legacy_dep", version=18, model="x.thing")
    _module(target_root, "modern_dep", version=19, model="x.thing")
    _module(custom_root, "demo", version=18, depends=("legacy_dep",))

    snapshots = {18: _snapshot(18, source_root), 19: _snapshot(19, target_root)}
    analysis = AnalysisService(_registry(), _Manager(snapshots)).analyze(custom_root, 18, 19)

    assert analysis.blockers == ()
    assert any(item.rule_id == "autonomous.dependency_rename.18_to_19" for item in analysis.auto_fix_candidates)
    assert any(item.code == "dependency.missing" for item in analysis.resolved_findings)
    assert ast.literal_eval((custom_root / "demo" / "__manifest__.py").read_text(encoding="utf-8"))["depends"] == ["legacy_dep"]

    output = tmp_path / "custom_19"
    result = MigrationService(_registry()).migrate(custom_root, output, analysis)
    migrated = ast.literal_eval((output / "demo" / "__manifest__.py").read_text(encoding="utf-8"))
    original = ast.literal_eval((custom_root / "demo" / "__manifest__.py").read_text(encoding="utf-8"))

    assert migrated["depends"] == ["modern_dep"]
    assert original["depends"] == ["legacy_dep"]
    assert any(change.rule_id == "autonomous.dependency_rename.18_to_19" for change in result.changes)


def test_ambiguous_dependency_successor_stays_blocked(tmp_path: Path):
    source_root = tmp_path / "odoo18"
    target_root = tmp_path / "odoo19"
    custom_root = tmp_path / "custom"
    _module(source_root, "legacy_dep", version=18, model="x.thing")
    _module(target_root, "candidate_a", version=19, model="x.thing")
    _module(target_root, "candidate_b", version=19, model="x.thing")
    _module(custom_root, "demo", version=18, depends=("legacy_dep",))

    snapshots = {18: _snapshot(18, source_root), 19: _snapshot(19, target_root)}
    analysis = AnalysisService(_registry(), _Manager(snapshots)).analyze(custom_root, 18, 19)

    assert analysis.blockers
    assert not any(item.rule_id == "autonomous.dependency_rename.18_to_19" for item in analysis.auto_fix_candidates)
