from pathlib import Path
import json
import shutil

import pytest

from odoo_migrator.analysis.compat import Severity
from odoo_migrator.application.services import AnalysisService, MigrationService
from odoo_migrator.migrations.v17_to_v18.dependencies import analyze as analyze_dependencies
from odoo_migrator.migrations.v17_to_v18.frontend import analyze as analyze_frontend
from odoo_migrator.migrations.v17_to_v18.manifest import Manifest17To18Rule
from odoo_migrator.migrations.v17_to_v18.python import analyze as analyze_python
from odoo_migrator.migrations.v17_to_v18.reports import analyze as analyze_reports
from odoo_migrator.migrations.v17_to_v18.security import analyze as analyze_security
from odoo_migrator.migrations.v17_to_v18.xml import TreeToListRule, analyze as analyze_xml
from odoo_migrator.sources.diff import compare_indexes
from odoo_migrator.sources.indexer import ModelInfo, ModuleInfo, OdooIndex, SourceIndexer, ViewInfo
from odoo_migrator.sources.registry import SourceSnapshot
from odoo_migrator.validation import validate_project


def test_manifest_17_to_18_positive_noop_malformed_wrong_source_and_multiple_addons(tmp_path: Path):
    first = tmp_path / "first"; second = tmp_path / "second"
    first.mkdir(); second.mkdir()
    (first / "__manifest__.py").write_text("{'name': 'First', 'version': '17.0.4.2.1'}")
    (second / "__manifest__.py").write_text("{'name': 'Second', 'version': '17.0.1'}")
    rule = Manifest17To18Rule()
    assert len(rule.apply(tmp_path)) == 2
    assert "18.0.4.2.1" in (first / "__manifest__.py").read_text()
    assert "18.0.1" in (second / "__manifest__.py").read_text()
    assert rule.apply(tmp_path) == []
    (first / "__manifest__.py").write_text("{'name': 'First', 'version': '16.0.1'}")
    assert rule.apply(tmp_path) == []
    (second / "__manifest__.py").write_text("{'name': 'Second', 'version': '17.0.1'")
    assert rule.apply(tmp_path) == []


def _python_indexes():
    custom = OdooIndex("custom", {"demo": ModuleInfo("demo", "demo", models={
        "sale.order": ModelInfo("sale.order", methods={"gone", "changed"}, fields={"old"},
                                  source_path="models/sale_order.py", line=3,
                                  method_locations={"gone": ("models/sale_order.py", 8), "changed": ("models/sale_order.py", 11)},
                                  field_locations={"old": ("models/sale_order.py", 6)})
    })})
    source = OdooIndex("17", {"sale": ModuleInfo("sale", "sale", models={
        "sale.order": ModelInfo("sale.order", methods={"gone", "changed"}, fields={"old"}, signatures={"changed": "self, value"})
    })}, source_commit="sha-17")
    target = OdooIndex("18", {"sale": ModuleInfo("sale", "sale", models={
        "sale.order": ModelInfo("sale.order", methods={"changed"}, fields=set(), signatures={"changed": "self, value, extra"})
    })}, source_commit="sha-18")
    return custom, source, target


def test_python_removed_model_members_and_signature_are_step_specific():
    custom, source, target = _python_indexes()
    findings = analyze_python(custom, source, target, compare_indexes(source, target))
    assert {item.code for item in findings} == {"python.method.removed", "python.signature.changed", "python.field.removed"}
    assert all(item.migration_step == "17_to_18" and item.rule_id.endswith(".17_to_18") for item in findings)
    assert all(item.path == "models/sale_order.py" and item.line for item in findings)


def test_python_removed_standard_model_is_blocker_and_compatible_is_noop():
    custom = OdooIndex("custom", {"demo": ModuleInfo("demo", "demo", models={
        "removed.model": ModelInfo("removed.model", source_path="models/x.py", line=4)
    })})
    source = OdooIndex("17", {"base": ModuleInfo("base", "base", models={"removed.model": ModelInfo("removed.model")})})
    target = OdooIndex("18", {"base": ModuleInfo("base", "base")})
    finding = analyze_python(custom, source, target, compare_indexes(source, target))[0]
    assert finding.severity is Severity.BLOCKER and finding.migration_step == "17_to_18"
    compatible = OdooIndex("18", {"base": ModuleInfo("base", "base", models={"removed.model": ModelInfo("removed.model")})})
    assert analyze_python(custom, source, compatible, compare_indexes(source, compatible)) == []


def test_removed_dependency_is_blocker_and_custom_dependency_is_valid():
    custom = OdooIndex("custom", {"demo": ModuleInfo("demo", "demo", depends=["legacy_mod", "other_custom"])})
    source = OdooIndex("17", {"legacy_mod": ModuleInfo("legacy_mod", "legacy_mod"), "other_custom": ModuleInfo("other_custom", "other_custom")})
    target = OdooIndex("18", {"other_custom": ModuleInfo("other_custom", "other_custom")})
    finding = analyze_dependencies(custom, source, target, compare_indexes(source, target))[0]
    assert finding.severity is Severity.BLOCKER
    assert finding.rule_id == "dependency.module_removed.17_to_18"
    assert analyze_dependencies(OdooIndex("custom", {"demo": ModuleInfo("demo", "demo", depends=["other_custom"])}), source, target, compare_indexes(source, target)) == []


def _xml_indexes(tmp_path: Path, expression: str, *, target_view=True, target_arch="<list><field name='name'/></list>"):
    addon = tmp_path / "demo"; addon.mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{'name': 'Demo'}")
    (addon / "view.xml").write_text(
        f"<odoo><record id='x' model='ir.ui.view'><field name='inherit_id' ref='sale.view_order_tree'/><field name='arch' type='xml'><xpath expr=\"{expression}\" position='inside'/></field></record></odoo>"
    )
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "custom-cache")
    source_view = ViewInfo("sale.view_order_tree", architecture="<tree><field name='name'/></tree>")
    source = OdooIndex("17", {"sale": ModuleInfo("sale", "sale", xml_ids={"sale.view_order_tree"}, views={"sale.view_order_tree": source_view})})
    module = ModuleInfo("sale", "sale")
    if target_view:
        module.xml_ids.add("sale.view_order_tree")
        module.views["sale.view_order_tree"] = ViewInfo("sale.view_order_tree", architecture=target_arch)
    return custom, source, OdooIndex("18", {"sale": module})


def test_xml_inheritance_exists_missing_xpath_and_unknown(tmp_path: Path):
    custom, source, target = _xml_indexes(tmp_path / "exists", "//field[@name='name']")
    assert analyze_xml(custom, source, target, compare_indexes(source, target)) == []
    custom, source, target = _xml_indexes(tmp_path / "missing_view", "//field[@name='name']", target_view=False)
    assert analyze_xml(custom, source, target, compare_indexes(source, target))[0].code == "xml.inherit.target_missing"
    custom, source, target = _xml_indexes(tmp_path / "missing_xpath", "//field[@name='old']")
    finding = analyze_xml(custom, source, target, compare_indexes(source, target))[0]
    assert finding.code == "xml.xpath.target_missing" and finding.target_state == "missing"
    custom, source, target = _xml_indexes(tmp_path / "unknown", "//field[contains(@name, 'na')]")
    finding = analyze_xml(custom, source, target, compare_indexes(source, target))[0]
    assert finding.code == "xml.xpath.static_unknown" and finding.target_state == "unknown"


def test_tree_to_list_is_structured_view_only_and_idempotent(tmp_path: Path):
    addon = tmp_path / "demo"; addon.mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{'name': 'Demo'}")
    view = addon / "view.xml"
    view.write_text("<odoo><record id='v' model='ir.ui.view'><field name='arch' type='xml'><tree><field name='name'/></tree></field></record><record id='data' model='x.data'><tree/></record></odoo>")
    rule = TreeToListRule()
    assert len(rule.apply(tmp_path)) == 1
    text = view.read_text()
    assert "<list>" in text and "model=\"x.data\"><tree" in text
    assert rule.apply(tmp_path) == []


def test_security_valid_invalid_and_malformed(tmp_path: Path):
    addon = tmp_path / "demo"; addon.mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{'name': 'Demo'}")
    access = addon / "ir.model.access.csv"
    access.write_text("id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\nok,ok,base.model_sale_order,base.group_user,1,0,0,0\n")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "c1")
    target = OdooIndex("18", {"base": ModuleInfo("base", "base", xml_ids={"base.group_user"}, model_xml_ids={"base.model_sale_order": "sale.order"}, models={"sale.order": ModelInfo("sale.order")})})
    assert analyze_security(custom, target) == []
    access.write_text("id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\nbad,bad,wrong.model,wrong.group,1,0,0,0\n")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "c2")
    assert {item.code for item in analyze_security(custom, target)} == {"security.model_missing", "security.group_missing"}
    access.write_text("id,name\nbad,row\n")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "c3")
    assert [item.code for item in analyze_security(custom, target)] == ["security.access_csv.invalid"]


def test_frontend_removed_dependency_asset_bundle_and_false_positive_protection(tmp_path: Path):
    addon = tmp_path / "demo"; (addon / "static" / "src").mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{'name': 'Demo', 'assets': {'web.pdf_js_lib': ['x.js']}}")
    js = addon / "static" / "src" / "widget.js"
    js.write_text("import worker from '@hw_drivers/js/worker';")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "c1")
    source = OdooIndex("17", {"web": ModuleInfo("web", "web", js_modules={"@hw_drivers/js/worker"}, manifest={"assets": {"web.pdf_js_lib": []}})})
    target = OdooIndex("18", {"web": ModuleInfo("web", "web", manifest={"assets": {"web.assets_web": []}})})
    findings = analyze_frontend(custom, source, target)
    assert {item.code for item in findings} == {"frontend.legacy_dependency.removed", "frontend.asset_bundle.removed"}
    assert {item.object_name for item in findings} == {"@hw_drivers/js/worker", "web.pdf_js_lib"}
    js.write_text("// import worker from '@hw_drivers/js/worker';\nconst text = '@hw_drivers/js/worker';")
    (addon / "__manifest__.py").write_text("{'name': 'Demo'}")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "c2")
    assert analyze_frontend(custom, source, target) == []


def test_reports_missing_and_valid_target(tmp_path: Path):
    addon = tmp_path / "demo"; addon.mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{'name': 'Demo'}")
    (addon / "report.xml").write_text("<odoo><template id='x' inherit_id='sale.report_saleorder_document'/><t t-inherit='sale.other'/></odoo>")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "c1")
    assert len(analyze_reports(custom, OdooIndex("18", {}))) == 2
    target = OdooIndex("18", {"sale": ModuleInfo("sale", "sale", xml_ids={"sale.report_saleorder_document", "sale.other"})})
    assert analyze_reports(custom, target) == []


class _Manager:
    def __init__(self, roots): self.roots = roots
    def ensure(self, version): return SourceSnapshot(version, f"{version}.0", "official", f"sha-{version}", self.roots[version])


def _source_tree(root: Path, version: int) -> Path:
    base = root / f"odoo{version}" / "base"; (base / "models").mkdir(parents=True)
    (base / "__manifest__.py").write_text("{'name': 'Base'}")
    (base / "groups.xml").write_text("<odoo><record id='group_user' model='res.groups'/></odoo>")
    sale = root / f"odoo{version}" / "sale"; (sale / "models").mkdir(parents=True); (sale / "views").mkdir(); (sale / "reports").mkdir()
    (sale / "__manifest__.py").write_text("{'name': 'Sale', 'depends': ['base']}")
    method = "legacy_method" if version == 17 else "new_method"
    field = "legacy_note" if version == 17 else "name"
    (sale / "models" / "sale.py").write_text(f"from odoo import fields, models\nclass Sale(models.Model):\n _name='sale.order'\n {field}=fields.Char()\n def {method}(self): return True\n")
    root_tag = "tree" if version == 17 else "list"
    (sale / "views" / "sale.xml").write_text(f"<odoo><record id='view_order_tree' model='ir.ui.view'><field name='arch' type='xml'><{root_tag}><field name='name'/></{root_tag}></field></record></odoo>")
    (sale / "reports" / "report.xml").write_text("<odoo><template id='report_saleorder_document'/></odoo>")
    web = root / f"odoo{version}" / "web"; (web / "static").mkdir(parents=True)
    asset = ", 'assets': {'web.pdf_js_lib': []}" if version == 17 else ""
    (web / "__manifest__.py").write_text("{'name': 'Web'" + asset + "}")
    if version == 17:
        (web / "static" / "legacy.js").write_text("odoo.define('web.ListController', function () {});")
    return base.parent


def test_application_17_to_18_records_source_target_metadata_and_validation(tmp_path: Path):
    fixture = Path(__file__).parent / "fixtures" / "odoo17_realistic_addon"
    custom = tmp_path / "custom"; shutil.copytree(fixture, custom)
    roots = {version: _source_tree(tmp_path, version) for version in (17, 18)}
    analysis = AnalysisService().analyze(custom, 17, 18, manager=_Manager(roots))
    assert any(item.code == "frontend.asset_bundle.removed" for item in analysis.findings)
    assert any(item.code == "xml.xpath.target_missing" for item in analysis.findings)
    assert [item.rule_id for item in analysis.auto_fix_candidates] == ["manifest.version.17_to_18", "xml.view_root.tree_to_list.17_to_18"]
    output = tmp_path / "output"
    result = MigrationService().migrate(custom, output, analysis)
    assert "17.0.4.2.1" in (custom / "__manifest__.py").read_text()
    assert "18.0.4.2.1" in (output / "__manifest__.py").read_text()
    assert "<list" in (output / "views" / "sale_order_views.xml").read_text()
    metadata = json.loads(result.metadata_path.read_text())
    assert metadata["migration_path"] == ["17_to_18"]
    assert metadata["source_snapshot"]["commit"] == "sha-17"
    assert metadata["target_snapshot"]["commit"] == "sha-18"
    assert metadata["tool_version"]
    assert metadata["input_path"] == str(custom.resolve())
    assert metadata["output_path"] == str(output.resolve())
    assert metadata["created_at"].endswith("+00:00")
    assert "manifest.version.17_to_18" in metadata["rule_versions"]
    assert metadata["validation"]["state"] == "passed"
    assert validate_project(output) == ()


def test_all_17_to_18_findings_are_step_specific_and_target_18(tmp_path: Path):
    fixture = Path(__file__).parent / "fixtures" / "odoo17_realistic_addon"
    custom = tmp_path / "custom"; shutil.copytree(fixture, custom)
    roots = {version: _source_tree(tmp_path, version) for version in (17, 18)}
    findings = AnalysisService().analyze(custom, 17, 18, manager=_Manager(roots)).findings

    assert findings
    for finding in findings:
        assert finding.migration_step == "17_to_18"
        assert finding.rule_id.endswith(".17_to_18")
        assert "14_to_15" not in finding.rule_id and "15_to_16" not in finding.rule_id
        assert "Odoo 16" not in finding.message


@pytest.mark.parametrize("source, expected_path", [(16, ["16_to_17", "17_to_18"]), (15, ["15_to_16", "16_to_17", "17_to_18"]), (14, ["14_to_15", "15_to_16", "16_to_17", "17_to_18"])])
def test_production_multihop_reaches_18_in_order(tmp_path: Path, source: int, expected_path: list[str]):
    custom = tmp_path / "custom" / "demo"; custom.mkdir(parents=True)
    (custom / "__manifest__.py").write_text(f"{{'name': 'Multi Hop', 'version': '{source}.0.1.0.0'}}")
    roots = {version: _source_tree(tmp_path, version) for version in range(source, 19)}
    analysis = AnalysisService().analyze(custom.parent, source, 18, manager=_Manager(roots))
    assert [step.source for step in analysis.steps] == list(range(source, 18))
    output = tmp_path / "output"
    result = MigrationService().migrate(custom.parent, output, analysis)
    assert f"18.0.1.0.0" in (output / "demo" / "__manifest__.py").read_text()
    assert f"{source}.0.1.0.0" in (custom / "__manifest__.py").read_text()
    assert json.loads(result.metadata_path.read_text())["migration_path"] == expected_path
