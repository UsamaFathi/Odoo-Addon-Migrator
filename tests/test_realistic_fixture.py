from pathlib import Path
from odoo_migrator.analysis.project import scan_custom_addons
from odoo_migrator.application.services import AnalysisResult
from odoo_migrator.migrations.engine import MigrationEngine
from odoo_migrator.sources.registry import SourceSnapshot
from odoo_migrator.validation import validate_project
import json
from odoo_migrator.application.services import AnalysisService, MigrationService


def test_realistic_fixture_migrates_manifest_without_touching_source(tmp_path: Path):
    fixture = Path(__file__).parent / "fixtures" / "odoo14_realistic_addon"
    source = tmp_path / "addons"; import shutil; shutil.copytree(fixture, source)
    output = tmp_path / "migrated"
    result = MigrationEngine().migrate(source, output, 14, 15,
        source_snapshot=SourceSnapshot(14, "14.0", "official", "source-sha", source),
        target_snapshot=SourceSnapshot(15, "15.0", "official", "target-sha", output))
    assert "14.0.1.0.0" in (source / "__manifest__.py").read_text()
    assert "15.0.1.0.0" in (output / "__manifest__.py").read_text()
    assert len(result.changes) == 1
    metadata = json.loads(result.metadata_path.read_text())
    assert metadata["source_snapshot"]["commit"] == "source-sha"
    assert metadata["target_snapshot"]["commit"] == "target-sha"
    assert validate_project(output) == ()


def test_application_analyze_migrate_validate_with_controlled_snapshots(tmp_path: Path):
    fixture = Path(__file__).parent / "fixtures" / "odoo14_realistic_addon"
    custom = tmp_path / "custom"; import shutil; shutil.copytree(fixture, custom)
    source_root = tmp_path / "odoo14"; target_root = tmp_path / "odoo15"
    for root in (source_root, target_root):
        base = root / "base"; (base / "models").mkdir(parents=True)
        (base / "__manifest__.py").write_text("{'name': 'Base'}")
        (base / "models" / "sale.py").write_text("""from odoo import models
class Sale(models.Model):
    _name = 'sale.order'
    def removed_in_target(self):
        return True
""" if root == source_root else """from odoo import models
class Sale(models.Model):
    _name = 'sale.order'
    def other(self):
        return True
""")
    (source_root / "base" / "groups.xml").write_text("<odoo><record id='group_user' model='res.groups'/></odoo>")
    (target_root / "base" / "groups.xml").write_text("<odoo><record id='group_user' model='res.groups'/></odoo>")

    class Manager:
        def ensure(self, version):
            root = source_root if version == 14 else target_root
            return SourceSnapshot(version, f"{version}.0", "official", f"sha-{version}", root)

    analysis = AnalysisService().analyze(custom, 14, 15, manager=Manager())
    assert analysis.auto_fix_candidates
    assert any(item.code == "python.method.removed" for item in analysis.findings)
    assert not analysis.blockers
    output = tmp_path / "output"
    result = MigrationService().migrate(custom, output, analysis)
    assert "14.0" in (custom / "__manifest__.py").read_text()
    assert "15.0" in (output / "__manifest__.py").read_text()
    assert json.loads(result.metadata_path.read_text())["source_snapshot"]["commit"] == "sha-14"
    assert validate_project(output) == ()
