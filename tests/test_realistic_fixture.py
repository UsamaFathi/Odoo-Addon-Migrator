from pathlib import Path
from odoo_migrator.analysis.project import scan_custom_addons
from odoo_migrator.application.services import AnalysisResult
from odoo_migrator.migrations.engine import MigrationEngine
from odoo_migrator.sources.registry import SourceSnapshot
from odoo_migrator.validation import validate_project
import json


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
