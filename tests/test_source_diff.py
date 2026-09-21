from odoo_migrator.sources.diff import compare_indexes
from odoo_migrator.sources.indexer import ModelInfo, ModuleInfo, OdooIndex


def test_source_diff_reports_models_fields_methods_signatures_and_dependencies():
    old = ModelInfo("x", methods={"go", "old"}, fields={"a"}, signatures={"go": "a"})
    new = ModelInfo("x", methods={"go", "new"}, fields={"b"}, signatures={"go": "b"})
    before = OdooIndex("old", {"m": ModuleInfo("m", "m", ["base"], {"x": old})}, source_commit="a")
    after = OdooIndex("new", {"m": ModuleInfo("m", "m", ["base", "sale"], {"x": new}), "added": ModuleInfo("added", "added")}, source_commit="b")
    diff = compare_indexes(before, after)
    assert diff.modules_added == {"added"}; assert diff.models_added == set()
    change = diff.model_changes[0]
    assert change.removed_methods == {"old"}; assert change.signature_changes == {"go"}
    assert diff.dependency_changes["m"] == ({"base"}, {"base", "sale"})
