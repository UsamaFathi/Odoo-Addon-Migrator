from pathlib import Path
import json
import shutil

import pytest

from odoo_migrator.analysis.compat import Severity
from odoo_migrator.application.services import AnalysisService, MigrationService
from odoo_migrator.migrations.v16_to_v17.frontend import analyze as analyze_frontend
from odoo_migrator.migrations.v16_to_v17.dependencies import analyze as analyze_dependencies
from odoo_migrator.migrations.v16_to_v17.manifest import Manifest16To17Rule
from odoo_migrator.migrations.v16_to_v17.python import analyze as analyze_python
from odoo_migrator.migrations.v16_to_v17.reports import analyze as analyze_reports
from odoo_migrator.migrations.v16_to_v17.security import analyze as analyze_security
from odoo_migrator.migrations.v16_to_v17.xml import analyze as analyze_xml
from odoo_migrator.migrations.v16_to_v17 import frontend as frontend_pack
from odoo_migrator.sources.diff import compare_indexes
from odoo_migrator.sources.indexer import ModelInfo, ModuleInfo, OdooIndex, SourceIndexer, ViewInfo
from odoo_migrator.sources.registry import SourceSnapshot
from odoo_migrator.validation import validate_project


def test_manifest_16_to_17_positive_noop_malformed_wrong_source_and_multi_addon(tmp_path: Path):
    first = tmp_path / "first"; second = tmp_path / "second"
    first.mkdir(); second.mkdir()
    (first / "__manifest__.py").write_text("{'name': 'First', 'version': '16.0.3.2.1'}")
    (second / "__manifest__.py").write_text("{'name': 'Second', 'version': '16.0.1'}")
    rule = Manifest16To17Rule()
    assert len(rule.apply(tmp_path)) == 2
    assert "17.0.3.2.1" in (first / "__manifest__.py").read_text()
    assert "17.0.1" in (second / "__manifest__.py").read_text()
    assert rule.apply(tmp_path) == []
    (first / "__manifest__.py").write_text("{'name': 'First', 'version': '15.0.1'}")
    assert rule.apply(tmp_path) == []
    (second / "__manifest__.py").write_text("{'name': 'Second', 'version': '16.0.1'")
    assert rule.apply(tmp_path) == []


def _python_indexes():
    custom = OdooIndex("custom", {
        "demo": ModuleInfo("demo", "demo", models={
            "sale.order": ModelInfo(
                "sale.order", methods={"gone", "changed"}, fields={"old"},
                source_path="models/sale_order.py", line=3,
                method_locations={"gone": ("models/sale_order.py", 8), "changed": ("models/sale_order.py", 11)},
                field_locations={"old": ("models/sale_order.py", 6)},
            )
        })
    })
    source = OdooIndex("16", {"sale": ModuleInfo("sale", "sale", models={
        "sale.order": ModelInfo("sale.order", methods={"gone", "changed"}, fields={"old"}, signatures={"changed": "self, value"})
    })}, source_commit="sha-16")
    target = OdooIndex("17", {"sale": ModuleInfo("sale", "sale", models={
        "sale.order": ModelInfo("sale.order", methods={"changed"}, fields=set(), signatures={"changed": "self, value, extra"})
    })}, source_commit="sha-17")
    return custom, source, target


def test_python_removed_method_field_signature_and_locations():
    custom, source, target = _python_indexes()
    findings = analyze_python(custom, source, target, compare_indexes(source, target))
    assert {finding.code for finding in findings} == {
        "python.method.removed", "python.signature.changed", "python.field.removed"
    }
    assert all(finding.migration_step == "16_to_17" for finding in findings)
    assert all(finding.rule_id.endswith(".16_to_17") for finding in findings)
    assert any(finding.path == "models/sale_order.py" and finding.line for finding in findings)


def test_python_removed_model_is_blocker_and_compatible_is_noop():
    custom = OdooIndex("custom", {"demo": ModuleInfo("demo", "demo", models={
        "removed.model": ModelInfo("removed.model", source_path="models/x.py", line=4)
    })})
    source = OdooIndex("16", {"base": ModuleInfo("base", "base", models={"removed.model": ModelInfo("removed.model")})})
    target = OdooIndex("17", {"base": ModuleInfo("base", "base")})
    finding = analyze_python(custom, source, target, compare_indexes(source, target))[0]
    assert finding.severity is Severity.BLOCKER
    assert finding.migration_step == "16_to_17" and finding.target_state == "removed"
    compatible = OdooIndex("17", {"base": ModuleInfo("base", "base", models={"removed.model": ModelInfo("removed.model")})})
    assert analyze_python(custom, source, compatible, compare_indexes(source, compatible)) == []


def test_removed_dependency_is_a_step_specific_blocker():
    custom = OdooIndex("custom", {"demo": ModuleInfo("demo", "demo", depends=["legacy_mod"])})
    source = OdooIndex("16", {"legacy_mod": ModuleInfo("legacy_mod", "legacy_mod")})
    target = OdooIndex("17", {})
    finding = analyze_dependencies(custom, source, target, compare_indexes(source, target))[0]
    assert finding.severity is Severity.BLOCKER
    assert finding.migration_step == "16_to_17"
    assert finding.target_state == "removed"


def _xml_indexes(tmp_path: Path, expression: str, *, target_view=True, target_arch="<form><field name='name'/></form>", attrs=False, states=False):
    addon = tmp_path / "demo"; addon.mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{'name': 'Demo'}")
    modifiers = []
    if attrs:
        modifiers.append("attrs=\"{'invisible': [('state', '=', 'done')]}\"")
    if states:
        modifiers.append('states="draft,confirmed"')
    modifier = (" " + " ".join(modifiers)) if modifiers else ""
    (addon / "view.xml").write_text(
        f"<odoo><record id='x' model='ir.ui.view'><field name='inherit_id' ref='base.view_form'/><field name='arch' type='xml'><xpath expr=\"{expression}\" position='inside'><field name='name'{modifier}/></xpath></field></record></odoo>"
    )
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "custom-cache")
    source_view = ViewInfo("base.view_form", architecture="<form><field name='name'/><field name='old'/></form>")
    source = OdooIndex("16", {"base": ModuleInfo("base", "base", xml_ids={"base.view_form"}, views={"base.view_form": source_view})})
    module = ModuleInfo("base", "base")
    if target_view:
        module.xml_ids.add("base.view_form")
        module.views["base.view_form"] = ViewInfo("base.view_form", architecture=target_arch)
    return custom, source, OdooIndex("17", {"base": module})


def test_xml_view_preserved_missing_unknown_and_modifier_review(tmp_path: Path):
    custom, source, target = _xml_indexes(tmp_path / "preserved", "//field[@name='name']")
    assert analyze_xml(custom, source, target) == []
    custom, source, target = _xml_indexes(tmp_path / "removed", "//field[@name='name']", target_view=False)
    assert analyze_xml(custom, source, target)[0].code == "xml.inherit.target_missing"
    custom, source, target = _xml_indexes(tmp_path / "xpath", "//field[@name='old']")
    finding = analyze_xml(custom, source, target)[0]
    assert finding.code == "xml.xpath.target_missing" and finding.target_state == "missing"
    custom, source, target = _xml_indexes(tmp_path / "unknown", "//field[contains(@name, 'na')]")
    finding = analyze_xml(custom, source, target)[0]
    assert finding.code == "xml.xpath.static_unknown" and finding.target_state == "unknown"
    custom, source, target = _xml_indexes(tmp_path / "attrs", "//field[@name='name']", attrs=True)
    finding = next(item for item in analyze_xml(custom, source, target) if item.code == "xml.view_modifier.legacy_attribute")
    assert finding.severity is Severity.REVIEW_REQUIRED
    assert finding.source_state == "supported" and finding.target_state == "rejected"


def test_xml_states_and_attrs_are_distinct_view_findings(tmp_path: Path):
    custom, source, target = _xml_indexes(tmp_path / "both", "//field[@name='name']", attrs=True, states=True)
    findings = [item for item in analyze_xml(custom, source, target) if item.code == "xml.view_modifier.legacy_attribute"]
    assert {item.object_name for item in findings} == {"attrs", "states"}
    assert all(item.severity is Severity.REVIEW_REQUIRED for item in findings)
    assert all(item.migration_step == "16_to_17" and item.source_state == "supported" and item.target_state == "rejected" for item in findings)


def test_xml_modifier_detection_ignores_non_view_qweb_comments_and_text(tmp_path: Path):
    addon = tmp_path / "demo"; addon.mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{'name': 'Demo'}")
    (addon / "unrelated.xml").write_text(
        "<odoo>"
        "<!-- attrs='ignored' states='ignored' -->"
        "<record id='data' model='x.data'><field name='value' attrs='ignored' states='ignored'>text attrs states</field></record>"
        "<template id='qweb'><div attrs='qweb' states='qweb'>text attrs states</div></template>"
        "</odoo>"
    )
    (addon / "arch_field.xml").write_text(
        "<odoo><record id='view' model='ir.ui.view'><field name='arch' type='xml' attrs='data-only'><form/></field></record></odoo>"
    )
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "cache")
    source = OdooIndex("16", {})
    target = OdooIndex("17", {})
    assert [item for item in analyze_xml(custom, source, target) if item.code == "xml.view_modifier.legacy_attribute"] == []


def test_security_standard_custom_missing_and_malformed(tmp_path: Path):
    addon = tmp_path / "demo"; addon.mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{'name': 'Demo'}")
    (addon / "ir.model.access.csv").write_text(
        "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
        "ok,ok,base.model_sale_order,base.group_user,1,0,0,0\n"
    )
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "c1")
    target = OdooIndex("17", {"base": ModuleInfo("base", "base", xml_ids={"base.group_user"}, model_xml_ids={"base.model_sale_order": "sale.order"}, models={"sale.order": ModelInfo("sale.order")})})
    assert analyze_security(custom, target) == []
    (addon / "ir.model.access.csv").write_text(
        "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
        "bad,bad,wrong.model,wrong.group,1,0,0,0\n"
    )
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "c2")
    findings = analyze_security(custom, target)
    assert {finding.code for finding in findings} == {"security.model_missing", "security.group_missing"}
    (addon / "ir.model.access.csv").write_text("id,name\nbad,row\n")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "c3")
    assert [finding.code for finding in analyze_security(custom, target)] == ["security.access_csv.invalid"]


def test_frontend_exact_removed_dependency_and_false_positive_protection(tmp_path: Path):
    addon = tmp_path / "demo"; (addon / "static").mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{'name': 'Demo'}")
    js = addon / "static" / "widget.js"
    js.write_text("import { FormController } from 'web.FormController';")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "c1")
    source = OdooIndex("16", {"web": ModuleInfo("web", "web", js_modules=set(frontend_pack.REMOVED_LEGACY_MODULES))})
    target = OdooIndex("17", {"web": ModuleInfo("web", "web")})
    findings = analyze_frontend(custom, source, target)
    assert findings[0].object_name == "web.FormController"
    js.write_text("// import { FormController } from 'web.FormController';\nconst text = 'web.FormController';")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "c2")
    assert analyze_frontend(custom, source, target) == []


def test_frontend_es_module_index_has_stable_name_and_location(tmp_path: Path):
    addon = tmp_path / "demo"; (addon / "static" / "src").mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{'name': 'Demo'}")
    path = addon / "static" / "src" / "widget.js"
    path.write_text("/** @odoo-module **/\nexport const value = 1;")
    index = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "cache")
    assert "@demo/widget" in index.js_modules
    assert index.js_module_locations["@demo/widget"] == "static/src/widget.js"


def test_frontend_patch_signature_change_is_precise(tmp_path: Path):
    addon = tmp_path / "demo"; (addon / "static" / "src").mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{'name': 'Demo'}")
    path = addon / "static" / "src" / "patch.js"
    path.write_text("/** @odoo-module **/\nimport { patch } from '@web/core/utils/patch';\npatch(Target.prototype, 'DemoPatch', { value() {} });")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "c1")
    source = OdooIndex("16", {"web": ModuleInfo("web", "web", js_modules={"@web/core/utils/patch"})})
    target = OdooIndex("17", {"web": ModuleInfo("web", "web", js_modules={"@web/core/utils/patch"})})
    finding = analyze_frontend(custom, source, target)[0]
    assert finding.code == "frontend.patch_signature.changed"
    path.write_text("// patch(Target.prototype, 'DemoPatch', {});\nconst text = \"patch(Target, 'name', {})\";")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "c2")
    assert analyze_frontend(custom, source, target) == []


def test_reports_missing_and_valid_target_ids(tmp_path: Path):
    addon = tmp_path / "demo"; addon.mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{'name': 'Demo'}")
    report = addon / "report.xml"
    report.write_text("<odoo><template id='x' inherit_id='sale.report_order'/><t t-inherit='sale.other'/></odoo>")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "c1")
    assert len(analyze_reports(custom, OdooIndex("17", {}))) == 2
    target = OdooIndex("17", {"sale": ModuleInfo("sale", "sale", xml_ids={"sale.report_order", "sale.other"})})
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
    method = "legacy_method" if version == 16 else "new_method"
    field = "legacy_note" if version == 16 else "name"
    (sale / "models" / "sale.py").write_text(f"from odoo import fields, models\nclass Sale(models.Model):\n _name='sale.order'\n {field}=fields.Char()\n def {method}(self): return True\n")
    (sale / "views" / "sale.xml").write_text("<odoo><record id='view_order_form' model='ir.ui.view'><field name='arch' type='xml'><form><field name='name'/></form></field></record></odoo>")
    (sale / "reports" / "report.xml").write_text("<odoo><template id='report_order'/></odoo>")
    web = root / f"odoo{version}" / "web"; (web / "static").mkdir(parents=True)
    (web / "__manifest__.py").write_text("{'name': 'Web'}")
    if version == 16:
        (web / "static" / "legacy.js").write_text("odoo.define('web.FormController', function () {});")
    return base.parent


def test_application_16_to_17_preserves_original_and_metadata(tmp_path: Path):
    fixture = Path(__file__).parent / "fixtures" / "odoo16_realistic_addon"
    custom = tmp_path / "custom"; shutil.copytree(fixture, custom)
    roots = {version: _source_tree(tmp_path, version) for version in (16, 17)}
    analysis = AnalysisService().analyze(custom, 16, 17, manager=_Manager(roots))
    assert analysis.auto_fix_candidates[0].rule_id == "manifest.version.16_to_17"
    assert all(item.migration_step == "16_to_17" for item in analysis.findings if item.rule_id)
    assert not any(item.code == "xml.view_modifier.legacy_attribute" for item in analysis.findings)
    assert any(item.code == "xml.view_modifier.legacy_attribute" for item in analysis.resolved_findings)
    assert any(
        item.rule_id == "xml.modifiers.attrs_states_to_inline.16_to_17"
        for item in analysis.auto_fix_candidates
    )
    assert any(item.code == "frontend.legacy_dependency.removed" for item in analysis.findings)
    output = tmp_path / "output"
    result = MigrationService().migrate(custom, output, analysis)
    assert "16.0.3.2.1" in (custom / "__manifest__.py").read_text()
    assert "17.0.3.2.1" in (output / "__manifest__.py").read_text()
    metadata = json.loads(result.metadata_path.read_text())
    assert metadata["migration_path"] == ["16_to_17"]
    assert metadata["source_snapshot"]["commit"] == "sha-16"
    assert metadata["target_snapshot"]["commit"] == "sha-17"
    assert metadata["rule_versions"]["manifest.version.16_to_17"]["source"] == 16
    assert metadata["validation"]["state"] == "passed"
    assert validate_project(output) == ()


@pytest.mark.parametrize("source, expected_path", [(15, ["15_to_16", "16_to_17"]), (14, ["14_to_15", "15_to_16", "16_to_17"])])
def test_real_multi_hop_ends_at_17_and_preserves_original(tmp_path: Path, source: int, expected_path: list[str]):
    custom = tmp_path / "custom" / "demo"; custom.mkdir(parents=True)
    (custom / "__manifest__.py").write_text(
        f"{{'name': 'Multi Hop', 'version': '{source}.0.1.0.0'}}"
    )
    roots = {version: _source_tree(tmp_path, version) for version in range(source, 18)}
    analysis = AnalysisService().analyze(custom.parent, source, 17, manager=_Manager(roots))
    assert [step.source for step in analysis.steps] == list(range(source, 17))
    assert {item.migration_step for item in analysis.findings if item.migration_step} <= set(expected_path)
    output = tmp_path / "output"
    result = MigrationService().migrate(custom.parent, output, analysis)
    assert f"{source}.0.1.0.0" in (custom / "__manifest__.py").read_text()
    assert "17.0.1.0.0" in (output / "demo" / "__manifest__.py").read_text()
    metadata = json.loads(result.metadata_path.read_text())
    assert metadata["migration_path"] == expected_path
    assert validate_project(output) == ()


def test_all_v16_to_v17_findings_are_step_specific():
    custom, source, target = _python_indexes()
    findings = analyze_python(custom, source, target, compare_indexes(source, target))
    assert findings
    for finding in findings:
        assert finding.migration_step == "16_to_17"
        assert finding.rule_id and finding.rule_id.endswith(".16_to_17")
        assert "14_to_15" not in finding.rule_id and "15_to_16" not in finding.rule_id
        assert "Odoo 16" not in finding.message
