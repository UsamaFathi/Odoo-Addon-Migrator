from pathlib import Path
import shutil

from odoo_migrator.migrations.v15_to_v16.frontend import analyze as analyze_frontend
from odoo_migrator.migrations.v15_to_v16.manifest import Manifest15To16Rule
from odoo_migrator.migrations.v15_to_v16.python import analyze as analyze_python
from odoo_migrator.migrations.v15_to_v16.security import analyze as analyze_security
from odoo_migrator.sources.diff import compare_indexes
from odoo_migrator.sources.indexer import ModelInfo, ModuleInfo, OdooIndex, SourceIndexer, ViewInfo
from odoo_migrator.migrations.v15_to_v16.xml import analyze as analyze_xml
from odoo_migrator.migrations.v15_to_v16.reports import analyze as analyze_reports
from odoo_migrator.application.services import AnalysisService, MigrationService
from odoo_migrator.sources.registry import SourceSnapshot
from odoo_migrator.validation import validate_project
import pytest
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


def test_python_removed_model_blocker_and_compatible_noop():
    custom_model = ModelInfo("removed.model", source_path="models/x.py", line=4)
    custom = OdooIndex("custom", {"demo": ModuleInfo("demo", "demo", models={"removed.model": custom_model})})
    source = OdooIndex("15", {"base": ModuleInfo("base", "base", models={"removed.model": ModelInfo("removed.model")})})
    target = OdooIndex("16", {"base": ModuleInfo("base", "base")})
    findings = analyze_python(custom, source, target, compare_indexes(source, target))
    assert findings[0].severity.value == "blocker"
    assert findings[0].path == "models/x.py" and findings[0].line == 4
    assert findings[0].migration_step == "15_to_16"
    compatible = OdooIndex("16", {"base": ModuleInfo("base", "base", models={"removed.model": ModelInfo("removed.model")})})
    assert analyze_python(custom, source, compatible, compare_indexes(source, compatible)) == []


def test_frontend_removed_dependency_positive_and_generic_negative(tmp_path: Path):
    addon = tmp_path / "demo"; (addon / "static").mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{'name': 'Demo'}")
    js = addon / "static" / "x.js"; js.write_text("require('web.PieChart')")
    index = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "cache")
    source = OdooIndex("15", {"web": ModuleInfo("web", "web", js_modules={"web.PieChart"})})
    target = OdooIndex("16", {"web": ModuleInfo("web", "web")})
    assert analyze_frontend(index, source, target)[0].object_name == "web.PieChart"
    js.write_text("odoo.define('demo.x', function () {})")
    index = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "cache2")
    assert analyze_frontend(index, source, target) == []
    js.write_text("// require('web.PieChart')\nconst label = 'web.PieChart';")
    index = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "cache3")
    assert analyze_frontend(index, source, target) == []


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
    web = root / f"odoo{version}" / "web"; (web / "static").mkdir(parents=True)
    (web / "__manifest__.py").write_text("{'name': 'Web'}")
    if version == 15:
        (web / "static" / "pie.js").write_text("odoo.define('web.PieChart', function () {});")
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
    pack_findings = [item for item in analysis.findings if item.rule_id]
    assert all(item.migration_step == "15_to_16" for item in pack_findings)
    assert all("14_to_15" not in item.rule_id for item in pack_findings)
    assert all("Odoo 15" not in item.message for item in pack_findings)
    assert not analysis.blockers
    output = tmp_path / "output"
    result = MigrationService().migrate(custom, output, analysis)
    assert "15.0.2.3.1" in (custom / "__manifest__.py").read_text()
    assert "16.0.2.3.1" in (output / "__manifest__.py").read_text()
    metadata = json.loads(result.metadata_path.read_text())
    assert metadata["migration_path"] == ["15_to_16"]
    assert metadata["source_snapshot"]["commit"] == "sha-15"
    assert validate_project(output) == ()


def _security_indexes(tmp_path: Path, model_ref: str, group_ref: str, malformed: bool = False):
    target = tmp_path / "target" / "base"; (target / "models").mkdir(parents=True)
    (target / "__manifest__.py").write_text("{'name': 'Base'}")
    (target / "models" / "sale.py").write_text("from odoo import models\nclass Sale(models.Model):\n _name='sale.order'\n")
    (target / "groups.xml").write_text("<odoo><record id='group_user' model='res.groups'/></odoo>")
    custom = tmp_path / "custom" / "demo"; (custom / "models").mkdir(parents=True)
    (custom / "__manifest__.py").write_text("{'name': 'Demo'}")
    (custom / "models" / "custom.py").write_text("from odoo import models\nclass X(models.Model):\n _name='x.custom'\n")
    (custom / "groups.xml").write_text("<odoo><record id='group_custom' model='res.groups'/></odoo>")
    csv_text = "id,name\nbad,row\n" if malformed else f"id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\na,A,{model_ref},{group_ref},1,0,0,0\n"
    (custom / "ir.model.access.csv").write_text(csv_text)
    return (SourceIndexer().index(custom.parent, cache_dir=tmp_path / "ccache"),
            SourceIndexer().index(target.parent, cache_dir=tmp_path / "tcache"))


def test_security_standard_and_custom_references(tmp_path: Path):
    custom, target = _security_indexes(tmp_path / "standard", "base.model_sale_order", "base.group_user")
    assert analyze_security(custom, target) == []
    custom, target = _security_indexes(tmp_path / "custom", "model_x_custom", "group_custom")
    assert analyze_security(custom, target) == []


def test_security_missing_and_malformed_references(tmp_path: Path):
    custom, target = _security_indexes(tmp_path / "missing_model", "wrong.model_sale_order", "base.group_user")
    assert {item.code for item in analyze_security(custom, target)} == {"security.model_missing"}
    custom, target = _security_indexes(tmp_path / "missing_group", "base.model_sale_order", "wrong.group")
    assert {item.code for item in analyze_security(custom, target)} == {"security.group_missing"}
    custom, target = _security_indexes(tmp_path / "malformed", "", "", malformed=True)
    assert {item.code for item in analyze_security(custom, target)} == {"security.access_csv.invalid"}


def _xml_indexes(tmp_path: Path, expr: str, target_has_view: bool = True, target_arch: str = "<form><field name='name'/></form>"):
    addon = tmp_path / "demo"; addon.mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{'name':'Demo'}")
    (addon / "view.xml").write_text(f"<odoo><record id='x' model='ir.ui.view'><field name='inherit_id' ref='base.view_form'/><field name='arch' type='xml'><xpath expr=\"{expr}\" position='inside'/></field></record></odoo>")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "cache")
    source_view = ViewInfo("base.view_form", architecture="<form><field name='name'/><field name='old'/></form>")
    source = OdooIndex("15", {"base": ModuleInfo("base", "base", xml_ids={"base.view_form"}, views={"base.view_form": source_view})})
    target_module = ModuleInfo("base", "base")
    if target_has_view:
        target_module.xml_ids.add("base.view_form"); target_module.views["base.view_form"] = ViewInfo("base.view_form", architecture=target_arch)
    return custom, source, OdooIndex("16", {"base": target_module})


def test_xml_view_and_xpath_cases(tmp_path: Path):
    custom, source, target = _xml_indexes(tmp_path / "missing_view", "//field[@name='name']", False)
    assert analyze_xml(custom, source, target)[0].code == "xml.inherit.target_missing"
    custom, source, target = _xml_indexes(tmp_path / "valid", "//field[@name='name']")
    assert analyze_xml(custom, source, target) == []
    custom, source, target = _xml_indexes(tmp_path / "missing_xpath", "//field[@name='old']")
    assert analyze_xml(custom, source, target)[0].code == "xml.xpath.target_missing"
    custom, source, target = _xml_indexes(tmp_path / "unknown", "//field[contains(@name, 'na')]")
    finding = analyze_xml(custom, source, target)[0]
    assert finding.code == "xml.xpath.static_unknown" and finding.severity.value == "review_required"


def test_report_messages_and_inheritance_forms_target_odoo16(tmp_path: Path):
    addon = tmp_path / "demo"; addon.mkdir(); (addon / "__manifest__.py").write_text("{'name':'Demo'}")
    (addon / "report.xml").write_text("<odoo><template id='a' inherit_id='sale.missing'/><t t-inherit='sale.other'/></odoo>")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "cache")
    findings = analyze_reports(custom, OdooIndex("16", {}))
    assert len(findings) == 2
    assert all("Odoo 16" in item.message and "Odoo 15" not in item.message for item in findings)
    assert all(item.migration_step == "15_to_16" and item.rule_id.endswith("15_to_16") for item in findings)
    target = OdooIndex("16", {"sale": ModuleInfo("sale", "sale", xml_ids={"sale.missing", "sale.other"})})
    assert analyze_reports(custom, target) == []


def test_removed_dependency_is_step_specific_blocker(tmp_path: Path):
    custom = tmp_path / "custom" / "demo"; custom.mkdir(parents=True)
    (custom / "__manifest__.py").write_text("{'name':'Demo','version':'15.0.1','depends':['legacy_mod']}")
    roots = {version: _odoo_tree(tmp_path, version) for version in (15, 16)}
    legacy = roots[15] / "legacy_mod"; legacy.mkdir(); (legacy / "__manifest__.py").write_text("{'name':'Legacy'}")
    analysis = AnalysisService().analyze(custom.parent, 15, 16, manager=_Manager(roots))
    finding = next(item for item in analysis.findings if item.code == "dependency.missing")
    assert finding.severity.value == "blocker" and finding.migration_step == "15_to_16"
    with pytest.raises(ValueError, match="blocked"):
        MigrationService().migrate(custom.parent, tmp_path / "out", analysis)
