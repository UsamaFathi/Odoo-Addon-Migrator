from pathlib import Path
import shutil

from odoo_migrator.migrations.v15_to_v16.frontend import analyze as analyze_frontend
from odoo_migrator.migrations.v15_to_v16.manifest import Manifest15To16Rule
from odoo_migrator.migrations.v15_to_v16.python import analyze as analyze_python
from odoo_migrator.sources.diff import compare_indexes
from odoo_migrator.sources.indexer import ModelInfo, ModuleInfo, OdooIndex, SourceIndexer
from odoo_migrator.application.services import AnalysisService, MigrationService
from odoo_migrator.sources.registry import SourceSnapshot
from odoo_migrator.validation import validate_project
import json


def test_manifest_rule_positive_noop_malformed_and_idempotent(tmp_path: Path):
    addon = tmp_path / "demo"; addon.mkdir(); manifest = addon / "__manifest__.py"
    manifest.write_text("{'name': 'Demo', 'version': '15.0.2.3.1'}")
    rule = Manifest15To16Rule()
    assert len(rule.apply(tmp_path)) == 1
    assert "16.0.2.3.1" in manifest.read_text()
    assert rule.apply(tmp_path) == []
    manifest.write_text("{'name': 'Demo', 'version': '17.0.1'}")
    assert rule.apply(tmp_path) == []
    manifest.write_text("{'name': 'Demo', 'version': '15.0.1'")
    assert rule.apply(tmp_path) == []


def test_python_source_diff_findings_for_15_to_16():
    custom = OdooIndex("custom", {"demo": ModuleInfo("demo", "demo", models={"x": ModelInfo("x", {"gone", "changed"}, {"old"})})})
    source = OdooIndex("15", {"base": ModuleInfo("base", "base", models={"x": ModelInfo("x", {"gone", "changed"}, {"old"}, signatures={"changed": "a"})})})
    target = OdooIndex("16", {"base": ModuleInfo("base", "base", models={"x": ModelInfo("x", {"changed"}, set(), signatures={"changed": "b"})})})
    findings = analyze_python(custom, source, target, compare_indexes(source, target))
    assert {item.code for item in findings} == {"python.method.removed", "python.signature.changed", "python.field.removed"}
    assert all(item.migration_step == "15_to_16" for item in findings)


def test_frontend_removed_dependency_positive_and_generic_negative(tmp_path: Path):
    addon = tmp_path / "demo"; (addon / "static").mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{'name': 'Demo'}")
    js = addon / "static" / "x.js"; js.write_text("require('web.PieChart')")
    index = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "cache")
    assert analyze_frontend(index, OdooIndex("15", {}), OdooIndex("16", {}))[0].object_name == "web.PieChart"
    js.write_text("odoo.define('demo.x', function () {})")
    index = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "cache2")
    assert analyze_frontend(index, OdooIndex("15", {}), OdooIndex("16", {})) == []


def _odoo_tree(root: Path, version: int) -> Path:
    base = root / f"odoo{version}" / "base"; base.mkdir(parents=True)
    (base / "__manifest__.py").write_text("{'name': 'Base'}")
    (base / "groups.xml").write_text("<odoo><record id='group_user' model='res.groups'/></odoo>")
    sale = root / f"odoo{version}" / "sale"; (sale / "models").mkdir(parents=True); (sale / "views").mkdir()
    (sale / "__manifest__.py").write_text("{'name': 'Sale', 'depends': ['base']}")
    method = "legacy_method" if version == 15 else "new_method"
    field = "legacy_note" if version == 15 else "name"
    (sale / "models" / "sale.py").write_text(f"from odoo import models, fields\nclass Sale(models.Model):\n _name='sale.order'\n {field}=fields.Char()\n def {method}(self): return True\n")
    (sale / "views" / "sale.xml").write_text(f"<odoo><record id='view_order_form' model='ir.ui.view'><field name='arch' type='xml'><form><field name='{field}'/></form></field></record></odoo>")
    if version == 15:
        (sale / "report.xml").write_text("<odoo><template id='report_saleorder_document'/></odoo>")
    return base.parent


class _Manager:
    def __init__(self, roots): self.roots = roots
    def ensure(self, version): return SourceSnapshot(version, f"{version}.0", "official", f"sha-{version}", self.roots[version])


def test_application_level_15_to_16_migration(tmp_path: Path):
    fixture = Path(__file__).parent / "fixtures" / "odoo15_realistic_addon"
    custom = tmp_path / "custom"; shutil.copytree(fixture, custom)
    roots = {version: _odoo_tree(tmp_path, version) for version in (15, 16)}
    analysis = AnalysisService().analyze(custom, 15, 16, manager=_Manager(roots))
    codes = {item.code for item in analysis.findings}
    assert "python.method.removed" in codes
    assert "xml.xpath.target_missing" in codes
    assert "frontend.legacy_dependency.removed" in codes
    assert "report.template_missing" in codes
    assert analysis.auto_fix_candidates[0].rule_id == "manifest.version.15_to_16"
    assert not analysis.blockers
    output = tmp_path / "output"
    result = MigrationService().migrate(custom, output, analysis)
    assert "15.0.2.3.1" in (custom / "__manifest__.py").read_text()
    assert "16.0.2.3.1" in (output / "__manifest__.py").read_text()
    metadata = json.loads(result.metadata_path.read_text())
    assert metadata["migration_path"] == ["15_to_16"]
    assert metadata["source_snapshot"]["commit"] == "sha-15"
    assert validate_project(output) == ()
