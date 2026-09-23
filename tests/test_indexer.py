from pathlib import Path
from odoo_migrator.sources.indexer import INDEX_SCHEMA_VERSION, SourceIndexer


def test_indexer_finds_model_fields_methods_and_xmlids(tmp_path: Path):
    mod = tmp_path / "x_demo"; (mod / "models").mkdir(parents=True); (mod / "views").mkdir()
    (mod / "__manifest__.py").write_text("{'name':'X','depends':['sale']}\n")
    (mod / "models" / "sale.py").write_text("from odoo import fields, models\nclass SaleOrder(models.Model):\n    _inherit = \"sale.order\"\n    x_note = fields.Char()\n    def action_confirm(self):\n        return super().action_confirm()\n")
    (mod / "views" / "view.xml").write_text('<odoo><record id="x_sale_view" model="ir.ui.view"/></odoo>')
    idx = SourceIndexer().index(tmp_path)
    assert idx.modules["x_demo"].depends == ["sale"]
    assert "sale.order" in idx.modules["x_demo"].models
    model = idx.modules["x_demo"].models["sale.order"]
    assert "x_note" in model.fields
    assert "action_confirm" in model.methods
    assert "x_demo.x_sale_view" in idx.modules["x_demo"].xml_ids


def test_custom_index_cache_invalidates_when_file_changes(tmp_path: Path):
    mod = tmp_path / "demo"; mod.mkdir()
    manifest = mod / "__manifest__.py"
    manifest.write_text("{'name': 'Demo', 'depends': []}\n")
    cache = tmp_path / "cache"
    indexer = SourceIndexer(); first = indexer.index(tmp_path, cache_dir=cache)
    manifest.write_text("{'name': 'Demo', 'depends': ['sale']}\n")
    second = indexer.index(tmp_path, cache_dir=cache)
    assert first.modules["demo"].depends == []
    assert second.modules["demo"].depends == ["sale"]


def test_javascript_path_index_covers_files_without_odoo_module_marker(tmp_path: Path):
    mod = tmp_path / "demo"
    (mod / "static" / "src").mkdir(parents=True)
    (mod / "__manifest__.py").write_text("{'name': 'Demo'}\n")
    path = mod / "static" / "src" / "unmarked.js"
    path.write_text("export const value = 1;\n")

    index = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "cache")

    assert index.schema_version == INDEX_SCHEMA_VERSION == 8
    assert "@demo/unmarked" in index.js_modules
    assert index.js_module_locations["@demo/unmarked"] == "static/src/unmarked.js"


def test_model_name_and_inheritance_are_indexed_separately(tmp_path: Path):
    mod = tmp_path / "demo"; (mod / "models").mkdir(parents=True)
    (mod / "__manifest__.py").write_text("{'name': 'Demo'}")
    (mod / "models" / "model.py").write_text("""from odoo import models, fields
class New(models.Model):
    _name = 'custom.model'
    _inherit = ['sale.order']
    _inherits = {'res.partner': 'partner_id'}
    value = fields.Char()
class Extension(models.Model):
    _inherit = 'stock.picking'
    note = fields.Char()
""")
    index = SourceIndexer().index(tmp_path, cache_dir=tmp_path / "cache")
    assert set(index.modules["demo"].models) == {"custom.model", "stock.picking"}
    model = index.modules["demo"].models["custom.model"]
    assert model.inherits == {"sale.order"}; assert model.delegated_inherits == {"res.partner"}
    assert index.resolve_model_external_id("demo.model_custom_model") == "custom.model"
    assert index.resolve_model_external_id("model_custom_model") == "custom.model"
    assert index.resolve_model_external_id("wrong.model_custom_model") is None
    assert "demo.model_stock_picking" not in index.model_xml_ids
