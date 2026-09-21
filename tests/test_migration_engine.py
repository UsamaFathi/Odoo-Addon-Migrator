from pathlib import Path
import json
from odoo_migrator.migrations.engine import MigrationEngine


def test_engine_copies_and_updates_manifest(tmp_path: Path):
    src = tmp_path / "addons"
    mod = src / "demo"; mod.mkdir(parents=True)
    (mod / "__manifest__.py").write_text("{'name': 'Demo', 'version': '15.0.1.2.0', 'depends': ['base']}\n")
    out = tmp_path / "out"
    result = MigrationEngine().migrate(src, out, 15, 18)
    assert (mod / "__manifest__.py").read_text().find("15.0.1.2.0") >= 0
    assert (out / "demo" / "__manifest__.py").read_text().find("18.0.1.2.0") >= 0
    assert len(result.changes) == 3
    assert result.metadata_path == out / ".odoo_migrator_run.json"
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["migration_path"] == ["15_to_16", "16_to_17", "17_to_18"]
    assert metadata["changes"][0]["path"] == "demo/__manifest__.py"


def test_engine_dry_run_does_not_create_output_or_metadata(tmp_path: Path):
    src = tmp_path / "addons"; mod = src / "demo"; mod.mkdir(parents=True)
    (mod / "__manifest__.py").write_text("{'name': 'Demo', 'version': '15.0.1'}\n")
    out = tmp_path / "out"
    result = MigrationEngine().migrate(src, out, 15, 16, dry_run=True)
    assert result.output == src
    assert result.metadata_path is None
    assert not out.exists()
    assert "15.0.1" in (mod / "__manifest__.py").read_text()


def test_engine_rejects_nested_output(tmp_path: Path):
    src = tmp_path / "addons"; (src / "demo").mkdir(parents=True)
    (src / "demo" / "__manifest__.py").write_text("{'name': 'Demo'}\n")
    import pytest
    with pytest.raises(ValueError, match="inside the input"):
        MigrationEngine().migrate(src, src / "migrated", 15, 16)
