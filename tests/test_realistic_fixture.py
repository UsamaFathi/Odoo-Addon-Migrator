from pathlib import Path
from odoo_migrator.analysis.project import scan_custom_addons
from odoo_migrator.application.services import AnalysisResult
from odoo_migrator.migrations.engine import MigrationEngine


def test_realistic_fixture_migrates_manifest_without_touching_source(tmp_path: Path):
    fixture = Path(__file__).parent / "fixtures" / "odoo14_realistic_addon"
    source = tmp_path / "addons"; import shutil; shutil.copytree(fixture, source)
    output = tmp_path / "migrated"
    result = MigrationEngine().migrate(source, output, 14, 15)
    assert "14.0.1.0.0" in (source / "__manifest__.py").read_text()
    assert "15.0.1.0.0" in (output / "__manifest__.py").read_text()
    assert len(result.changes) == 1
