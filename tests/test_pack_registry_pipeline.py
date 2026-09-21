from pathlib import Path

import pytest

from odoo_migrator.analysis.compat import Finding, Severity
from odoo_migrator.application.services import AnalysisService, MigrationService
from odoo_migrator.core.planner import build_plan
from odoo_migrator.migrations.engine import MigrationEngine
from odoo_migrator.migrations.registry import (
    MigrationPack, MigrationPackRegistry, UnsupportedMigrationPathError, default_registry,
)
from odoo_migrator.migrations.rules.manifest_version import ManifestVersionRule
from odoo_migrator.sources.registry import SourceSnapshot
from typer.testing import CliRunner
from odoo_migrator.cli.main import app
from odoo_migrator.validation import validate_project
import json


def _source_tree(root: Path, version: int) -> Path:
    path = root / f"odoo{version}" / "base"
    path.mkdir(parents=True)
    (path / "__manifest__.py").write_text("{'name': 'Base'}")
    return path.parent


class _Manager:
    def __init__(self, roots): self.roots = roots
    def ensure(self, version):
        return SourceSnapshot(version, f"{version}.0", "official", f"sha-{version}", self.roots[version])


def test_registry_support_and_unsupported_paths():
    registry = default_registry()
    assert registry.supports(14, 15)
    assert registry.supports(15, 16)
    assert registry.supports(16, 17)
    assert registry.supports(17, 18)
    assert registry.reachable_targets(14) == (15, 16, 17, 18)
    assert registry.reachable_targets(15) == (16, 17, 18)
    assert registry.reachable_targets(16) == (17, 18)
    assert registry.reachable_targets(17) == (18,)
    assert registry.missing_steps(build_plan(14, 19).steps)[0].label == "18 -> 19"
    assert [rule.rule_id for rule in MigrationEngine(registry).rules_for(16, 17)] == ["manifest.version.16_to_17"]
    assert [rule.rule_id for rule in MigrationEngine(registry).rules_for(17, 18)] == [
        "manifest.version.17_to_18", "xml.view_root.tree_to_list.17_to_18",
        "xml.action_view_mode.tree_to_list.17_to_18"
    ]


def test_registry_rejects_invalid_and_duplicate_packs():
    registry = MigrationPackRegistry()
    with pytest.raises(ValueError, match="adjacent"):
        registry.register(MigrationPack(14, 16))
    registry.register(MigrationPack(14, 15))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(MigrationPack(14, 15))
    with pytest.raises(ValueError, match="does not match"):
        registry.register(MigrationPack(15, 16, rule_factory=lambda: [ManifestVersionRule(14, 15)]))


def test_multihop_analysis_uses_evolving_staged_custom_state(tmp_path: Path):
    custom = tmp_path / "custom"; module = custom / "demo"; module.mkdir(parents=True)
    manifest = module / "__manifest__.py"
    manifest.write_text("{'name': 'Demo', 'version': '14.0.1.0.0'}")
    roots = {version: _source_tree(tmp_path, version) for version in (14, 15, 16)}
    registry = default_registry()
    analysis = AnalysisService(registry).analyze(custom, 14, 16, manager=_Manager(roots))

    assert [item.migration_step for item in analysis.auto_fix_candidates] == ["14_to_15", "15_to_16"]
    assert analysis.steps[0].custom_fingerprint_before != analysis.steps[0].custom_fingerprint_after
    assert analysis.steps[1].custom_fingerprint_before == analysis.steps[0].custom_fingerprint_after
    assert "14.0.1.0.0" in manifest.read_text()

    output = tmp_path / "output"
    result = MigrationService(registry).migrate(custom, output, analysis)
    assert [change.rule_id for change in result.changes] == ["manifest.version.14_to_15", "manifest.version.15_to_16"]
    assert "16.0.1.0.0" in (output / "demo" / "__manifest__.py").read_text()
    assert "14.0.1.0.0" in manifest.read_text()
    metadata = json.loads(result.metadata_path.read_text())
    assert metadata["migration_path"] == ["14_to_15", "15_to_16"]
    assert metadata["source_snapshot"]["commit"] == "sha-14"
    assert metadata["target_snapshot"]["commit"] == "sha-16"
    assert metadata["rules"] == ["manifest.version.14_to_15", "manifest.version.15_to_16"]
    assert validate_project(output) == ()


def test_services_refuse_full_unsupported_path(tmp_path: Path):
    custom = tmp_path / "custom" / "demo"; custom.mkdir(parents=True)
    (custom / "__manifest__.py").write_text("{'name': 'Demo', 'version': '14.0.1'}")
    with pytest.raises(UnsupportedMigrationPathError) as exc:
        AnalysisService().analyze(custom.parent, 14, 19)
    assert [(step.source, step.target) for step in exc.value.steps] == [(18, 19)]


def test_cli_reports_missing_pack_without_traceback(tmp_path: Path):
    result = CliRunner().invoke(app, ["analyze", str(tmp_path), "--from", "14", "--to", "19"])
    assert result.exit_code == 2
    assert "Missing pack: 18 -> 19" in result.stdout
