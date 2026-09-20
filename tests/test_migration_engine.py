from pathlib import Path
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
