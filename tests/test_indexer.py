from pathlib import Path
from odoo_migrator.sources.indexer import SourceIndexer


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
