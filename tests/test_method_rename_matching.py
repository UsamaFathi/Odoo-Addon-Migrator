from __future__ import annotations

from pathlib import Path

from odoo_migrator.migrations.autonomous import MethodRenameResolver
from odoo_migrator.migrations.method_matching import high_confidence_method_renames
from odoo_migrator.sources.diff import compare_indexes
from odoo_migrator.sources.indexer import SourceIndexer


def _addon(root: Path, version: int, method_name: str, *, second_method: str | None = None) -> None:
    module = root / "sale"
    module.mkdir(parents=True)
    (module / "__manifest__.py").write_text(
        repr({"name": "Sale", "version": f"{version}.0.1.0.0", "depends": ["base"]}),
        encoding="utf-8",
    )
    extra = ""
    if second_method:
        extra = f"""
    def {second_method}(self, vals):
        self.ensure_one()
        if self.state != 'draft':
            return False
        result = self._prepare_invoice(vals)
        self.message_post(body='reviewed')
        return result
"""
    (module / "models.py").write_text(
        f"""from odoo import models

class SaleOrder(models.Model):
    _name = 'sale.order'

    def {method_name}(self, vals):
        self.ensure_one()
        if self.state != 'draft':
            return False
        result = self._prepare_invoice(vals)
        self.message_post(body='reviewed')
        return result
{extra}
""",
        encoding="utf-8",
    )


def test_semantic_method_matcher_detects_unique_method_rename(tmp_path: Path):
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    _addon(old_root, 18, "action_review")
    _addon(new_root, 19, "action_start_review")

    indexer = SourceIndexer()
    old = indexer.index(old_root, cache_dir=tmp_path / "cache-old")
    new = indexer.index(new_root, cache_dir=tmp_path / "cache-new")
    matches = high_confidence_method_renames(old, new, compare_indexes(old, new))

    assert len(matches) == 1
    match = matches[0]
    assert match.model == "sale.order"
    assert match.source_method == "action_review"
    assert match.target_method == "action_start_review"
    assert match.score >= 0.88
    assert match.margin >= 0.12


def test_semantic_method_matcher_rejects_ambiguous_candidates(tmp_path: Path):
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    _addon(old_root, 18, "action_review")
    _addon(new_root, 19, "action_start_review", second_method="action_reopen_review")

    indexer = SourceIndexer()
    old = indexer.index(old_root, cache_dir=tmp_path / "cache-old")
    new = indexer.index(new_root, cache_dir=tmp_path / "cache-new")

    assert high_confidence_method_renames(old, new, compare_indexes(old, new)) == ()


def test_method_rename_resolver_updates_override_and_super_call_only(tmp_path: Path):
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    custom_root = tmp_path / "custom"
    _addon(old_root, 18, "action_review")
    _addon(new_root, 19, "action_start_review")

    custom = custom_root / "custom_sale"
    custom.mkdir(parents=True)
    (custom / "__manifest__.py").write_text(
        repr({"name": "Custom Sale", "version": "18.0.1.0.0", "depends": ["sale"]}),
        encoding="utf-8",
    )
    path = custom / "models.py"
    path.write_text(
        """from odoo import models

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_review(self, vals):
        result = super().action_review(vals)
        self.action_review()
        other.action_review()
        return result
""",
        encoding="utf-8",
    )

    indexer = SourceIndexer()
    old = indexer.index(old_root, cache_dir=tmp_path / "cache-old")
    new = indexer.index(new_root, cache_dir=tmp_path / "cache-new")
    custom_index = indexer.index(custom_root, cache_dir=tmp_path / "cache-custom")
    resolver = MethodRenameResolver(18, 19)

    changes = resolver.apply(custom_root, custom_index, old, new, compare_indexes(old, new), dry_run=False)
    result = path.read_text(encoding="utf-8")

    assert len(changes) == 1
    assert "def action_start_review(" in result
    assert "super().action_start_review(" in result
    assert "self.action_start_review()" in result
    assert "other.action_review()" in result



def test_semantic_method_matcher_rejects_two_old_methods_mapping_to_one_new_method(tmp_path: Path):
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    module = old_root / "sale"
    module.mkdir(parents=True)
    (module / "__manifest__.py").write_text(
        repr({"name": "Sale", "version": "18.0.1.0.0"}),
        encoding="utf-8",
    )
    (module / "models.py").write_text(
        """from odoo import models

class SaleOrder(models.Model):
    _name = 'sale.order'

    def action_review(self, vals):
        self.ensure_one()
        if self.state != 'draft':
            return False
        result = self._prepare_invoice(vals)
        self.message_post(body='reviewed')
        return result

    def action_reopen(self, vals):
        self.ensure_one()
        if self.state != 'draft':
            return False
        result = self._prepare_invoice(vals)
        self.message_post(body='reviewed')
        return result
""",
        encoding="utf-8",
    )
    _addon(new_root, 19, "action_start_review")

    indexer = SourceIndexer()
    old = indexer.index(old_root, cache_dir=tmp_path / "cache-old")
    new = indexer.index(new_root, cache_dir=tmp_path / "cache-new")

    assert high_confidence_method_renames(old, new, compare_indexes(old, new)) == ()
