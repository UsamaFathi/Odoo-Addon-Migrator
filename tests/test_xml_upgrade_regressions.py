from __future__ import annotations

from pathlib import Path

from odoo_migrator.migrations.v16_to_v17.modifiers import LegacyAttrsStatesRule
from odoo_migrator.migrations.v17_to_v18.xml import XPathTreeToListRule


def test_attrs_buttons_convert_to_inline_modifiers(tmp_path: Path):
    root = tmp_path / "addons"
    module = root / "uf_stock_pulse"
    module.mkdir(parents=True)
    path = module / "views.xml"
    path.write_text(
        """<odoo><record id="view_test" model="ir.ui.view"><field name="arch" type="xml"><form><header>
<button name="action_review" string="Start Review" type="object" class="btn-secondary" attrs="{'invisible': [('state', '!=', 'draft')]}"/>
<button name="action_review" string="Reopen Review" type="object" class="btn-secondary" groups="uf_stock_pulse.group_stockpulse_manager" attrs="{'invisible': [('state', '!=', 'approved')]}"/>
<button name="action_approve" string="Approve" type="object" class="btn-primary" groups="uf_stock_pulse.group_stockpulse_manager" attrs="{'invisible': [('state', '!=', 'review')]}"/>
<button name="action_create_rfq" string="Create Draft RFQ" type="object" class="btn-primary" attrs="{'invisible': [('can_create_rfq', '=', False)]}"/>
<button name="action_create_rfq" string="Open RFQ" type="object" class="btn-secondary" groups="purchase.group_purchase_user" attrs="{'invisible': [('can_read_rfq', '=', False)]}"/>
<button name="action_cancel" string="Cancel" type="object" groups="uf_stock_pulse.group_stockpulse_manager" attrs="{'invisible': [('state', 'not in', ('draft', 'review'))]}"/>
<field name="state" widget="statusbar" statusbar_visible="draft,review,approved,converted,cancelled" options="{'clickable': false}"/>
</header></form></field></record></odoo>""",
        encoding="utf-8",
    )

    changes = LegacyAttrsStatesRule().apply(root, dry_run=False)
    result = path.read_text(encoding="utf-8")

    assert len(changes) == 1
    assert "attrs=" not in result
    assert 'invisible="(state != &#x27;draft&#x27;)"' in result
    assert 'invisible="(state != &#x27;approved&#x27;)"' in result
    assert 'invisible="(state != &#x27;review&#x27;)"' in result
    assert 'invisible="(can_create_rfq == False)"' in result
    assert 'invisible="(can_read_rfq == False)"' in result
    assert "state not in" in result
    assert "statusbar_visible" in result


def test_states_shorthand_merges_with_existing_invisible(tmp_path: Path):
    root = tmp_path / "addons"
    module = root / "demo"
    module.mkdir(parents=True)
    path = module / "view.xml"
    path.write_text(
        '<odoo><button name="x" invisible="locked" states="draft,review"/></odoo>',
        encoding="utf-8",
    )

    LegacyAttrsStatesRule().apply(root, dry_run=False)
    result = path.read_text(encoding="utf-8")

    assert "states=" not in result
    assert "(locked) or (state not in" in result


def test_unsupported_attrs_domain_is_left_unchanged(tmp_path: Path):
    root = tmp_path / "addons"
    module = root / "demo"
    module.mkdir(parents=True)
    path = module / "view.xml"
    original = '<odoo><button attrs="{\'invisible\': [(\'name\', \'ilike\', \'x\')]}"/></odoo>'
    path.write_text(original, encoding="utf-8")

    changes = LegacyAttrsStatesRule().apply(root, dry_run=False)

    assert changes == []
    assert path.read_text(encoding="utf-8") == original


def test_xpath_tree_node_is_converted_to_list(tmp_path: Path):
    root = tmp_path / "addons"
    module = root / "demo"
    module.mkdir(parents=True)
    path = module / "view.xml"
    path.write_text(
        """<odoo><record id="view" model="ir.ui.view"><field name="arch" type="xml">
<xpath expr="//field[@name='invoice_line_ids']//tree//field[@name='discount']" position="attributes">
<attribute name="optional">hide</attribute>
<attribute name="string">Total discount</attribute>
<attribute name="force_save">1</attribute>
</xpath>
</field></record></odoo>""",
        encoding="utf-8",
    )

    changes = XPathTreeToListRule().apply(root, dry_run=False)
    result = path.read_text(encoding="utf-8")

    assert len(changes) == 1
    assert "//field[@name='invoice_line_ids']//list//field[@name='discount']" in result
    assert "//tree" not in result


def test_xpath_tree_text_inside_string_literal_is_not_changed(tmp_path: Path):
    root = tmp_path / "addons"
    module = root / "demo"
    module.mkdir(parents=True)
    path = module / "view.xml"
    original = """<odoo><xpath expr="//field[@string='tree']" position="attributes"/></odoo>"""
    path.write_text(original, encoding="utf-8")

    changes = XPathTreeToListRule().apply(root, dry_run=False)

    assert changes == []
    assert path.read_text(encoding="utf-8") == original
