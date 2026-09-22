from __future__ import annotations

import json
from pathlib import Path
import shutil

from odoo_migrator.analysis.compat import Severity
from odoo_migrator.application.services import AnalysisService, MigrationService
from odoo_migrator.migrations.registry import default_registry
from odoo_migrator.migrations.v18_to_v19.dependencies import analyze as analyze_dependencies
from odoo_migrator.migrations.v18_to_v19.frontend import analyze as analyze_frontend
from odoo_migrator.migrations.v18_to_v19.manifest import Manifest18To19Rule
from odoo_migrator.migrations.v18_to_v19.python import analyze as analyze_python
from odoo_migrator.migrations.v18_to_v19.reports import analyze as analyze_reports
from odoo_migrator.migrations.v18_to_v19.security import analyze as analyze_security
from odoo_migrator.migrations.v18_to_v19.xml import analyze as analyze_xml
from odoo_migrator.sources.diff import compare_indexes
from odoo_migrator.sources.indexer import ModelInfo, ModuleInfo, OdooIndex, SourceIndexer, ViewInfo
from odoo_migrator.sources.registry import SourceSnapshot
from odoo_migrator.validation import validate_project


SOURCE_SHA = "3c3e3b3d17cbd98584c7685e607d9085712adfe0"
TARGET_SHA = "dd153b3cb418c2e4d4302ac62398ef95d51c9891"


def test_manifest_18_to_19_positive_noop_wrong_source_malformed_and_idempotent(tmp_path: Path):
    first = tmp_path / "first"; second = tmp_path / "second"
    first.mkdir(); second.mkdir()
    (first / "__manifest__.py").write_text("{'name': 'First', 'version': '18.0.4.3.2'}")
    (second / "__manifest__.py").write_text("{'name': 'Second', 'version': '18.0.1'}")
    rule = Manifest18To19Rule()
    assert len(rule.apply(tmp_path)) == 2
    assert "19.0.4.3.2" in (first / "__manifest__.py").read_text()
    assert rule.apply(tmp_path) == []
    (first / "__manifest__.py").write_text("{'name': 'First', 'version': '17.0.1'}")
    (second / "__manifest__.py").write_text("{'name': 'Second', 'version': '18.0.1'")
    assert rule.apply(tmp_path) == []


def _python_indexes():
    custom = OdooIndex("custom", {"demo": ModuleInfo("demo", "demo", models={
        "sale.order": ModelInfo("sale.order", methods={"gone", "changed"}, fields={"old"},
                                  source_path="models/sale_order.py", line=3,
                                  method_locations={"gone": ("models/sale_order.py", 8), "changed": ("models/sale_order.py", 11)},
                                  field_locations={"old": ("models/sale_order.py", 6)})
    })})
    source = OdooIndex("18", {"sale": ModuleInfo("sale", "sale", models={
        "sale.order": ModelInfo("sale.order", methods={"gone", "changed"}, fields={"old"}, signatures={"changed": "self, value"})
    })}, source_commit=SOURCE_SHA)
    target = OdooIndex("19", {"sale": ModuleInfo("sale", "sale", models={
        "sale.order": ModelInfo("sale.order", methods={"changed"}, fields=set(), signatures={"changed": "self, value, extra"})
    })}, source_commit=TARGET_SHA)
    return custom, source, target


def test_python_removed_model_members_and_signature_are_step_specific():
    custom, source, target = _python_indexes()
    findings = analyze_python(custom, source, target, compare_indexes(source, target))
    assert {item.code for item in findings} == {"python.method.removed", "python.signature.changed", "python.field.removed"}
    assert all(item.migration_step == "18_to_19" and item.rule_id.endswith(".18_to_19") for item in findings)
    assert all(item.path == "models/sale_order.py" and item.line for item in findings)


def test_python_removed_model_is_blocker_and_compatible_source_is_noop():
    custom = OdooIndex("custom", {"demo": ModuleInfo("demo", "demo", models={
        "product.packaging": ModelInfo("product.packaging", source_path="models/packaging.py", line=4)
    })})
    source = OdooIndex("18", {"product": ModuleInfo("product", "product", models={"product.packaging": ModelInfo("product.packaging")})})
    target = OdooIndex("19", {"product": ModuleInfo("product", "product")})
    finding = analyze_python(custom, source, target, compare_indexes(source, target))[0]
    assert finding.severity is Severity.BLOCKER
    assert finding.migration_step == "18_to_19"
    compatible = OdooIndex("19", {"product": ModuleInfo("product", "product", models={"product.packaging": ModelInfo("product.packaging")})})
    assert analyze_python(custom, source, compatible, compare_indexes(source, compatible)) == []


def test_removed_dependency_is_blocker_and_custom_dependency_is_valid():
    custom = OdooIndex("custom", {"demo": ModuleInfo("demo", "demo", depends=["web_editor", "other_custom"])})
    source = OdooIndex("18", {"web_editor": ModuleInfo("web_editor", "web_editor"), "other_custom": ModuleInfo("other_custom", "other_custom")})
    target = OdooIndex("19", {"other_custom": ModuleInfo("other_custom", "other_custom")})
    finding = analyze_dependencies(custom, source, target, compare_indexes(source, target))[0]
    assert finding.severity is Severity.BLOCKER
    assert finding.rule_id == "dependency.module_removed.18_to_19"
    valid = OdooIndex("custom", {"demo": ModuleInfo("demo", "demo", depends=["other_custom"])})
    assert analyze_dependencies(valid, source, target, compare_indexes(source, target)) == []


def _xml_indexes(tmp_path: Path, expression: str, *, target_view=True, target_arch="<list><field name='name'/></list>"):
    addon = tmp_path / "demo"; addon.mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{'name': 'Demo'}")
    (addon / "view.xml").write_text(
        f"<odoo><record id='x' model='ir.ui.view'><field name='inherit_id' ref='sale.view_order_tree'/><field name='arch' type='xml'><xpath expr=\"{expression}\" position='inside'/></field></record></odoo>"
    )
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "custom-cache")
    source_view = ViewInfo("sale.view_order_tree", architecture="<list><field name='name'/></list>")
    source = OdooIndex("18", {"sale": ModuleInfo("sale", "sale", xml_ids={"sale.view_order_tree"}, views={"sale.view_order_tree": source_view})}, source_commit=SOURCE_SHA)
    module = ModuleInfo("sale", "sale")
    if target_view:
        module.xml_ids.add("sale.view_order_tree")
        module.views["sale.view_order_tree"] = ViewInfo("sale.view_order_tree", architecture=target_arch)
    return custom, source, OdooIndex("19", {"sale": module}, source_commit=TARGET_SHA)


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


def test_direct_18_to_19_xml_does_not_replay_tree_list_or_action_rules(tmp_path: Path):
    addon = tmp_path / "demo"; addon.mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{'name': 'Demo'}")
    (addon / "view.xml").write_text("""<odoo>
      <record id="view" model="ir.ui.view"><field name="inherit_id" ref="sale.view_order_tree"/>
        <field name="arch" type="xml"><xpath expr="//field[@name='name']" position="inside"/></field></record>
      <record id="action" model="ir.actions.act_window"><field name="view_mode">list,form</field></record>
    </odoo>""")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "cache")
    source = OdooIndex("18", {"sale": ModuleInfo("sale", "sale", xml_ids={"sale.view_order_tree"}, views={"sale.view_order_tree": ViewInfo("sale.view_order_tree", architecture="<list><field name='name'/></list>" )})})
    target = OdooIndex("19", {"sale": ModuleInfo("sale", "sale", xml_ids={"sale.view_order_tree"}, views={"sale.view_order_tree": ViewInfo("sale.view_order_tree", architecture="<list><field name='name'/></list>" )})})
    findings = analyze_xml(custom, source, target, compare_indexes(source, target))
    assert not findings
    assert [rule.rule_id for rule in default_registry().get(18, 19).rule_factory()] == ["manifest.version.18_to_19"]


def test_security_valid_invalid_and_malformed(tmp_path: Path):
    addon = tmp_path / "demo"; addon.mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{'name': 'Demo'}")
    access = addon / "ir.model.access.csv"
    access.write_text("id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\nok,ok,base.model_sale_order,base.group_user,1,0,0,0\n")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "c1")
    target = OdooIndex("19", {"base": ModuleInfo("base", "base", xml_ids={"base.group_user"}, model_xml_ids={"base.model_sale_order": "sale.order"}, models={"sale.order": ModelInfo("sale.order")})})
    assert analyze_security(custom, target) == []
    access.write_text("id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\nbad,bad,wrong.model,wrong.group,1,0,0,0\n")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "c2")
    assert {item.code for item in analyze_security(custom, target)} == {"security.model_missing", "security.group_missing"}
    access.write_text("id,name\nbad,row\n")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "c3")
    assert [item.code for item in analyze_security(custom, target)] == ["security.access_csv.invalid"]


def test_frontend_removed_dependency_asset_bundle_and_false_positive_protection(tmp_path: Path):
    addon = tmp_path / "demo"; (addon / "static" / "src").mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{'name': 'Demo', 'assets': {'web_editor.assets_wysiwyg': ['x.js']}}")
    js = addon / "static" / "src" / "widget.js"
    js.write_text("import dialog from '@web_editor/components/media_dialog/media_dialog';")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "c1")
    source = OdooIndex("18", {"web_editor": ModuleInfo("web_editor", "web_editor", js_modules={"@web_editor/components/media_dialog/media_dialog"}, manifest={"assets": {"web_editor.assets_wysiwyg": []}})})
    target = OdooIndex("19", {"web": ModuleInfo("web", "web", manifest={"assets": {"web.assets_web": []}})})
    findings = analyze_frontend(custom, source, target)
    assert {item.code for item in findings} == {"frontend.legacy_dependency.removed", "frontend.asset_bundle.removed"}
    assert all(item.migration_step == "18_to_19" and item.rule_id.endswith(".18_to_19") for item in findings)
    js.write_text("// import dialog from '@web_editor/components/media_dialog/media_dialog';\nconst text = '@web_editor/components/media_dialog/media_dialog';")
    (addon / "__manifest__.py").write_text("{'name': 'Demo'}")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "c2")
    assert analyze_frontend(custom, source, target) == []


def test_reports_missing_and_valid_target(tmp_path: Path):
    addon = tmp_path / "demo"; addon.mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{'name': 'Demo'}")
    (addon / "report.xml").write_text("<odoo><template id='x' inherit_id='sale.report_saleorder_document'/><t t-inherit='sale.other'/></odoo>")
    custom = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "c1")
    assert len(analyze_reports(custom, OdooIndex("19", {}))) == 2
    target = OdooIndex("19", {"sale": ModuleInfo("sale", "sale", xml_ids={"sale.report_saleorder_document", "sale.other"})})
    assert analyze_reports(custom, target) == []


def test_realistic_fixture_has_source_backed_18_to_19_findings(tmp_path: Path):
    fixture = Path(__file__).parent / "fixtures" / "odoo18_realistic_addon"
    custom_root = tmp_path / "custom"; shutil.copytree(fixture, custom_root)
    custom = SourceIndexer().index(custom_root, cache_dir=tmp_path / "custom-index")
    source = OdooIndex("18", {
        "base": ModuleInfo("base", "base", xml_ids={"base.group_user"}),
        "sale": ModuleInfo("sale", "sale", xml_ids={"sale.view_order_tree", "sale.report_saleorder_document"},
                            views={"sale.view_order_tree": ViewInfo("sale.view_order_tree", architecture="<list><field name='name'/></list>")}),
        "product": ModuleInfo("product", "product", models={"product.packaging": ModelInfo("product.packaging")}),
        "web_editor": ModuleInfo("web_editor", "web_editor", js_modules={"@web_editor/components/media_dialog/media_dialog"},
                                  manifest={"assets": {"web_editor.assets_wysiwyg": []}}),
    }, source_commit=SOURCE_SHA)
    source.modules["sale"].models["sale.order"] = ModelInfo("sale.order", methods={"_cart_update"}, fields={"show_task_button"})
    target = OdooIndex("19", {
        "base": ModuleInfo("base", "base", xml_ids={"base.group_user"}),
        "sale": ModuleInfo("sale", "sale", xml_ids={"sale.view_order_tree", "sale.report_saleorder_document"},
                            views={"sale.view_order_tree": ViewInfo("sale.view_order_tree", architecture="<list><field name='name'/></list>")},
                            models={"sale.order": ModelInfo("sale.order")}),
        "web": ModuleInfo("web", "web", manifest={"assets": {"web.assets_web": []}}),
    }, source_commit=TARGET_SHA)
    diff = compare_indexes(source, target)
    findings = []
    findings.extend(analyze_python(custom, source, target, diff))
    findings.extend(analyze_dependencies(custom, source, target, diff))
    findings.extend(analyze_frontend(custom, source, target))
    findings.extend(analyze_security(custom, target))
    findings.extend(analyze_reports(custom, target))
    findings.extend(analyze_xml(custom, source, target, diff))
    assert {item.code for item in findings} >= {
        "python.model.removed", "dependency.module_removed", "frontend.legacy_dependency.removed",
        "frontend.asset_bundle.removed", "security.model_missing",
    }
    assert not any("17_to_18" in (item.rule_id or "") or "16_to_17" in (item.rule_id or "") for item in findings)
    assert all(item.migration_step == "18_to_19" for item in findings)


class _Manager:
    def __init__(self, roots): self.roots = roots
    def ensure(self, version):
        sha = {18: SOURCE_SHA, 19: TARGET_SHA}.get(version, f"sha-{version}")
        return SourceSnapshot(version, f"{version}.0", "official", sha, self.roots[version])


def _minimal_source_tree(root: Path, version: int) -> Path:
    base = root / f"odoo{version}" / "base"; base.mkdir(parents=True)
    (base / "__manifest__.py").write_text("{'name': 'Base'}")
    sale = root / f"odoo{version}" / "sale"; sale.mkdir(parents=True)
    (sale / "__manifest__.py").write_text("{'name': 'Sale', 'depends': ['base']}")
    (sale / "view.xml").write_text("<odoo><record id='view_order_tree' model='ir.ui.view'><field name='arch' type='xml'><list><field name='name'/></list></field></record></odoo>")
    return base.parent


def test_application_18_to_19_records_exact_metadata_and_preserves_input(tmp_path: Path):
    custom = tmp_path / "custom" / "demo"; custom.mkdir(parents=True)
    (custom / "__manifest__.py").write_text("{'name': 'Demo', 'version': '18.0.1.0.0'}")
    roots = {version: _minimal_source_tree(tmp_path, version) for version in (18, 19)}
    before = (custom / "__manifest__.py").read_bytes()
    analysis = AnalysisService().analyze(custom.parent, 18, 19, manager=_Manager(roots))
    result = MigrationService().migrate(custom.parent, tmp_path / "output", analysis)
    assert (custom / "__manifest__.py").read_bytes() == before
    assert "19.0.1.0.0" in (tmp_path / "output" / "demo" / "__manifest__.py").read_text()
    metadata = json.loads(result.metadata_path.read_text())
    assert metadata["migration_path"] == ["18_to_19"]
    assert metadata["source_snapshot"]["commit"] == SOURCE_SHA
    assert metadata["target_snapshot"]["commit"] == TARGET_SHA
    assert [item["version"] for item in metadata["source_snapshots"]] == [18, 19]
    assert [item["actual_commit"] for item in metadata["source_snapshots"]] == [SOURCE_SHA, TARGET_SHA]
    assert "Source identities" in (tmp_path / "output" / "migration_report.html").read_text(encoding="utf-8")
    assert metadata["validation"]["state"] == "passed"
    assert "manifest.version.18_to_19" in metadata["rule_versions"]
    assert validate_project(tmp_path / "output") == ()


def test_production_multihops_17_16_15_to_19_use_all_adjacent_packs(tmp_path: Path):
    for source in (17, 16, 15):
        case = tmp_path / f"from-{source}"
        custom = case / "custom" / "demo"; custom.mkdir(parents=True)
        manifest = custom / "__manifest__.py"
        manifest.write_text(f"{{'name': 'Multi Hop', 'version': '{source}.0.1.0.0'}}")
        before = manifest.read_bytes()
        roots = {version: _minimal_source_tree(case, version) for version in range(source, 20)}
        analysis = AnalysisService().analyze(custom.parent, source, 19, manager=_Manager(roots))
        expected_steps = [f"{version}_to_{version + 1}" for version in range(source, 19)]
        assert [step.source for step in analysis.steps] == list(range(source, 19))
        result = MigrationService().migrate(custom.parent, case / "output", analysis)
        assert "19.0.1.0.0" in (case / "output" / "demo" / "__manifest__.py").read_text()
        assert manifest.read_bytes() == before
        assert json.loads(result.metadata_path.read_text())["migration_path"] == expected_steps


def test_production_multihop_14_to_19_reaches_final_version_and_preserves_input(tmp_path: Path):
    custom = tmp_path / "custom" / "demo"; custom.mkdir(parents=True)
    manifest = custom / "__manifest__.py"
    manifest.write_text("{'name': 'Multi Hop', 'version': '14.0.1.0.0'}")
    before = manifest.read_bytes()
    roots = {version: _minimal_source_tree(tmp_path, version) for version in range(14, 20)}
    # The source snapshots used by this synthetic integration test carry the
    # pinned final SHA values through the manager, while each production rule
    # still receives its own adjacent state.
    manager = _Manager({18: roots[18], 19: roots[19]})
    manager.roots.update({version: roots[version] for version in range(14, 18)})
    analysis = AnalysisService().analyze(custom.parent, 14, 19, manager=manager)
    assert [step.source for step in analysis.steps] == [14, 15, 16, 17, 18]
    result = MigrationService().migrate(custom.parent, tmp_path / "output", analysis)
    assert "19.0.1.0.0" in (tmp_path / "output" / "demo" / "__manifest__.py").read_text()
    assert manifest.read_bytes() == before
    metadata = json.loads(result.metadata_path.read_text())
    assert metadata["migration_path"] == ["14_to_15", "15_to_16", "16_to_17", "17_to_18", "18_to_19"]
    assert validate_project(tmp_path / "output") == ()
