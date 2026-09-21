from pathlib import Path
from odoo_migrator.migrations.v14_to_v15.python import analyze
from odoo_migrator.migrations.v14_to_v15.frontend import analyze as frontend_analyze
from odoo_migrator.migrations.v14_to_v15.xml import analyze as xml_analyze
from odoo_migrator.migrations.v14_to_v15.security import analyze as security_analyze
from odoo_migrator.sources.diff import compare_indexes
from odoo_migrator.sources.indexer import ModelInfo, ModuleInfo, OdooIndex, SourceIndexer


def test_python_pack_flags_removed_method_and_signature():
    custom_model = ModelInfo("x", methods={"go"}, fields={"old"})
    custom = OdooIndex("custom", {"demo": ModuleInfo("demo", "demo", models={"x": custom_model})})
    old = OdooIndex("old", {"base": ModuleInfo("base", "base", models={"x": ModelInfo("x", {"go"}, {"old"}, signatures={"go": "a"})})}, source_commit="14sha")
    new = OdooIndex("new", {"base": ModuleInfo("base", "base", models={"x": ModelInfo("x", {"go"}, set(), signatures={"go": "b"})})}, source_commit="15sha")
    findings = analyze(custom, old, new, compare_indexes(old, new))
    assert {item.code for item in findings} == {"python.field.removed", "python.signature.changed"}
    assert all(item.severity.value == "review_required" for item in findings)


def test_frontend_legacy_pattern_is_review(tmp_path: Path):
    module = tmp_path / "demo"; (module / "static").mkdir(parents=True)
    (module / "__manifest__.py").write_text("{'name': 'Demo'}", encoding="utf-8")
    (module / "static" / "x.js").write_text("odoo.define('demo.x', function (require) {});", encoding="utf-8")
    index = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "cache")
    findings = frontend_analyze(index)
    assert findings[0].severity.value == "review_required"


def test_xml_missing_inherited_view_is_review(tmp_path: Path):
    module = tmp_path / "demo"; module.mkdir()
    (module / "__manifest__.py").write_text("{'name': 'Demo'}", encoding="utf-8")
    (module / "view.xml").write_text("<odoo><record id='x' model='ir.ui.view'><field name='inherit_id' ref='base.missing'/></record></odoo>", encoding="utf-8")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "cache")
    source = OdooIndex("source", {"base": ModuleInfo("base", "base", xml_ids={"base.missing"})})
    target = OdooIndex("target", {"base": ModuleInfo("base", "base")})
    findings = xml_analyze(custom, source, target)
    assert findings[0].code == "xml.inherit.target_missing"


def test_malformed_access_csv_is_blocker(tmp_path: Path):
    module = tmp_path / "demo"; module.mkdir()
    (module / "__manifest__.py").write_text("{'name': 'Demo'}", encoding="utf-8")
    (module / "ir.model.access.csv").write_text("id,name\n", encoding="utf-8")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "cache")
    finding = security_analyze(custom, OdooIndex("target", {}))[0]
    assert finding.severity.value == "blocker"
