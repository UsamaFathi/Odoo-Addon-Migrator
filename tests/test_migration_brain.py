from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from odoo_migrator.brain.pack import BrainPack, new_brain_payload
from odoo_migrator.brain.ranker import LogisticRanker, RankedExample
from odoo_migrator.brain.runtime import BrainRuntimeMigrator
from odoo_migrator.brain.trainer import BrainTrainer
from odoo_migrator.brain.history import mine_git_method_renames
from odoo_migrator.sources.registry import SourceSnapshot
from odoo_migrator.sources.indexer import SourceIndexer


def _addon(root: Path, name: str, version: int, *, depends=(), model: str | None = None) -> Path:
    module = root / name
    module.mkdir(parents=True, exist_ok=True)
    (module / "__manifest__.py").write_text(
        repr({"name": name, "version": f"{version}.0.1.0.0", "depends": list(depends)}),
        encoding="utf-8",
    )
    if model:
        (module / "models.py").write_text(
            f"""from odoo import models

class Demo(models.Model):
    _name = {model!r}

    def stable_method(self, vals):
        self.ensure_one()
        if not vals:
            return False
        self.message_post(body='stable')
        return vals

    def other_method(self):
        self.ensure_one()
        return self.name
""",
            encoding="utf-8",
        )
    return module


def test_logistic_ranker_learns_separable_semantic_examples():
    positives = [
        RankedExample(
            {
                "ast": 1.0, "calls": 1.0, "attrs": 1.0, "signature": 1.0,
                "control": 1.0, "decorators": 0.8, "strings": 0.8, "name": 0.9,
            },
            1,
        )
        for _ in range(12)
    ]
    negatives = [
        RankedExample(
            {
                "ast": 0.1, "calls": 0.0, "attrs": 0.1, "signature": 0.3,
                "control": 0.2, "decorators": 0.0, "strings": 0.0, "name": 0.1,
            },
            0,
        )
        for _ in range(12)
    ]
    model = LogisticRanker().fit([*positives, *negatives])

    assert model.predict_proba(positives[0].features) > 0.80
    assert model.predict_proba(negatives[0].features) < 0.20
    metrics = model.evaluate([*positives, *negatives])
    assert metrics.accuracy > 0.90


def test_brain_pack_roundtrip_and_fingerprint(tmp_path: Path):
    ranker = LogisticRanker()
    payload = new_brain_payload(
        source=18,
        target=19,
        ranker=ranker,
        steps={
            "18_to_19": {
                "source": 18,
                "target": 19,
                "method_renames": [],
                "model_renames": [],
                "dependency_renames": [],
                "automatic_rules": [],
            }
        },
        training={"dataset": {"total": 0}, "validation": {}},
        source_identities={},
    )
    path = BrainPack(payload).save(tmp_path / "migration_brain.omb")
    loaded = BrainPack.load(path)

    assert loaded.supports(18, 19)
    assert loaded.fingerprint
    assert loaded.source == 18
    assert loaded.target == 19


class _Manager:
    def __init__(self, roots: dict[int, Path]):
        self.roots = roots

    def ensure(self, version: int):
        return SourceSnapshot(
            version,
            f"{version}.0",
            "controlled://community",
            None,
            self.roots[version],
        )


def test_brain_trainer_builds_pack_from_source_once(tmp_path: Path):
    old = tmp_path / "odoo18"
    new = tmp_path / "odoo19"
    _addon(old, "demo_core", 18, model="demo.model")
    _addon(new, "demo_core", 19, model="demo.model")

    output = tmp_path / "brain.omb"
    result = BrainTrainer(source_manager=_Manager({18: old, 19: new})).build(
        output,
        source=18,
        target=19,
    )

    assert output.is_file()
    assert result.pack.supports(18, 19)
    assert result.training_samples > 0
    assert result.pack.payload["training"]["dataset"]["positives"] > 0
    assert result.pack.payload["training"]["dataset"]["negatives"] > 0


def test_brain_trainer_composes_per_version_enterprise_knowledge(tmp_path: Path):
    community18 = tmp_path / "odoo18"
    community19 = tmp_path / "odoo19"
    enterprise18 = tmp_path / "enterprise18"
    enterprise19 = tmp_path / "enterprise19"
    _addon(community18, "demo_core", 18, model="demo.model")
    _addon(community19, "demo_core", 19, model="demo.model")
    _addon(enterprise18, "account_reports", 18, model="account.report")
    _addon(enterprise19, "account_reports", 19, model="account.report")

    result = BrainTrainer(source_manager=_Manager({18: community18, 19: community19})).build(
        tmp_path / "enterprise.omb",
        source=18,
        target=19,
        enterprise_roots={18: enterprise18, 19: enterprise19},
    )

    assert result.pack.training["enterprise_versions"] == [18, 19]
    assert result.pack.source_identities["18"]["enterprise"] is True
    assert result.pack.source_identities["19"]["enterprise"] is True


def test_brain_runtime_migrates_without_odoo_source(tmp_path: Path):
    custom = tmp_path / "custom"
    module = _addon(
        custom,
        "custom_sale",
        18,
        depends=("legacy_dep",),
    )
    models = module / "models.py"
    models.write_text(
        """from odoo import models

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_review(self, vals):
        result = super().action_review(vals)
        self.action_review(vals)
        return result
""",
        encoding="utf-8",
    )

    payload = new_brain_payload(
        source=18,
        target=19,
        ranker=LogisticRanker(),
        steps={
            "18_to_19": {
                "source": 18,
                "target": 19,
                "automatic_rules": ["manifest.version.18_to_19"],
                "dependency_renames": [
                    {
                        "from": "legacy_dep",
                        "to": "modern_dep",
                        "confidence": 1.0,
                    }
                ],
                "model_renames": [],
                "method_renames": [
                    {
                        "model": "sale.order",
                        "from": "action_review",
                        "to": "action_start_review",
                        "confidence": 0.97,
                        "margin": 0.31,
                    }
                ],
            }
        },
        training={"dataset": {"total": 100}, "validation": {"accuracy": 0.95}},
        source_identities={},
    )
    brain = BrainPack(payload)
    brain_path = brain.save(tmp_path / "brain.omb")

    output = tmp_path / "migrated"
    result = BrainRuntimeMigrator(brain_path).migrate(
        custom,
        output,
        source=18,
        target=19,
    )

    migrated_manifest = ast.literal_eval(
        (output / "custom_sale" / "__manifest__.py").read_text(encoding="utf-8")
    )
    migrated_python = (output / "custom_sale" / "models.py").read_text(encoding="utf-8")
    original_python = models.read_text(encoding="utf-8")

    assert migrated_manifest["depends"] == ["modern_dep"]
    assert migrated_manifest["version"].startswith("19.")
    assert "def action_start_review(" in migrated_python
    assert "super().action_start_review(" in migrated_python
    assert "self.action_start_review(" in migrated_python
    assert "action_review" in original_python
    assert result.metadata_path.is_file()

    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["engine"] == "migration_brain"
    assert metadata["source_code_indexed_at_runtime"] is False


def test_brain_pack_contains_derived_knowledge_only(tmp_path: Path):
    payload = new_brain_payload(
        source=16,
        target=18,
        ranker=LogisticRanker(),
        steps={
            "16_to_17": {"source": 16, "target": 17, "automatic_rules": []},
            "17_to_18": {"source": 17, "target": 18, "automatic_rules": []},
        },
        training={"validation": {"precision": 1.0, "false_positive_rate": 0.0}},
        source_identities={"16": {"community_commit": "sha16"}},
    )
    path = BrainPack(payload).save(tmp_path / "derived.omb")
    loaded = BrainPack.load(path)

    assert loaded.contains_source_code is False
    assert loaded.payload["knowledge_policy"]["source_code_embedded"] is False
    assert loaded.training["validation"]["precision"] == 1.0


def test_brain_pack_rejects_embedded_source_text(tmp_path: Path):
    payload = new_brain_payload(
        source=18,
        target=19,
        ranker=LogisticRanker(),
        steps={"18_to_19": {"source": 18, "target": 19, "automatic_rules": []}},
        training={"validation": {}},
        source_identities={},
    )
    payload["steps"]["18_to_19"]["source_code"] = "class Secret(models.Model): pass"

    with pytest.raises(ValueError, match="must not contain Odoo source code"):
        BrainPack(payload).save(tmp_path / "unsafe.omb")


def test_brain_runtime_is_source_free_and_preserves_input(tmp_path: Path):
    custom = tmp_path / "custom"
    module = _addon(custom, "custom_sale", 18, depends=("removed_official",), model="sale.order")
    (module / "models.py").write_text(
        "from odoo import models\n\nclass Sale(models.Model):\n    _inherit = 'removed.model'\n",
        encoding="utf-8",
    )
    before = SourceIndexer.project_fingerprint(custom)
    brain = BrainPack(new_brain_payload(
        source=18,
        target=19,
        ranker=LogisticRanker(),
        steps={"18_to_19": {
            "source": 18,
            "target": 19,
            "automatic_rules": [],
            "compatibility": {
                "removed_modules": ["removed_official"],
                "removed_models": ["removed.model"],
                "model_changes": [],
            },
        }},
        training={"validation": {}},
        source_identities={},
    ))
    result = BrainRuntimeMigrator(brain).migrate(custom, tmp_path / "migrated", source=18, target=19)

    assert SourceIndexer.project_fingerprint(custom) == before
    assert result.validation_state == "blocked"
    assert any(item.code == "brain.dependency.removed" for item in result.findings)
    assert any(item.code == "brain.model.removed" for item in result.findings)
    assert result.report_path and result.report_path.is_file()
    assert result.diff_path and result.diff_path.is_file()


def test_brain_runtime_applies_high_confidence_field_mapping_only_in_model_class(tmp_path: Path):
    custom = tmp_path / "custom"
    module = _addon(custom, "custom_sale", 18, model="sale.order")
    source = """from odoo import fields, models

class Sale(models.Model):
    _inherit = 'sale.order'
    legacy_field = fields.Char()

    def check(self, other):
        return self.legacy_field, other.legacy_field
"""
    (module / "models.py").write_text(source, encoding="utf-8")
    brain = BrainPack(new_brain_payload(
        source=18,
        target=19,
        ranker=LogisticRanker(),
        steps={"18_to_19": {
            "source": 18,
            "target": 19,
            "automatic_rules": [],
            "field_renames": [{
                "model": "sale.order", "from": "legacy_field", "to": "modern_field",
                "confidence": 0.99, "margin": 0.40,
            }],
            "compatibility": {"model_changes": []},
        }},
        training={"validation": {}},
        source_identities={},
    ))
    output = tmp_path / "migrated"
    BrainRuntimeMigrator(brain).migrate(custom, output, source=18, target=19)
    migrated = (output / "custom_sale" / "models.py").read_text(encoding="utf-8")

    assert "modern_field = fields.Char()" in migrated
    assert "self.modern_field" in migrated
    assert "other.legacy_field" in migrated
    assert "other.modern_field" not in migrated
    assert "legacy_field" in source
    assert "legacy_field = fields.Char()" in (custom / "custom_sale" / "models.py").read_text(encoding="utf-8")


def test_brain_runtime_composes_16_to_18_without_source_trees(tmp_path: Path):
    custom = tmp_path / "custom"
    module = _addon(custom, "custom_view", 16)
    (module / "views.xml").write_text(
        """<odoo><record id='view' model='ir.ui.view'><field name='arch' type='xml'>
        <form attrs=\"{'invisible': [('state', '=', 'done')]}\"><field name='lines'><tree><field name='name'/></tree></field></form>
        </field></record></odoo>""",
        encoding="utf-8",
    )
    brain = BrainPack(new_brain_payload(
        source=16,
        target=18,
        ranker=LogisticRanker(),
        steps={
            "16_to_17": {
                "source": 16, "target": 17,
                "automatic_rules": ["manifest.version.16_to_17", "xml.modifiers.attrs_states_to_inline.16_to_17"],
                "compatibility": {},
            },
            "17_to_18": {
                "source": 17, "target": 18,
                "automatic_rules": ["manifest.version.17_to_18", "xml.view_root.tree_to_list.17_to_18", "xml.xpath.tree_to_list.17_to_18"],
                "compatibility": {},
            },
        },
        training={"validation": {}},
        source_identities={},
    ))
    output = tmp_path / "migrated"
    result = BrainRuntimeMigrator(brain).migrate(custom, output, source=16, target=18)
    xml = (output / "custom_view" / "views.xml").read_text(encoding="utf-8")
    manifest = ast.literal_eval((output / "custom_view" / "__manifest__.py").read_text(encoding="utf-8"))

    assert manifest["version"].startswith("18.")
    assert "<list>" in xml
    assert "attrs=" not in xml
    assert result.metadata_path.is_file()


def test_brain_runtime_reports_security_and_template_compatibility_without_source(tmp_path: Path):
    custom = tmp_path / "custom"
    module = _addon(custom, "custom_security", 18)
    (module / "security").mkdir()
    (module / "security" / "ir.model.access.csv").write_text(
        "id,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
        "access_old,base.model_old,base.group_old,1,0,0,0\n",
        encoding="utf-8",
    )
    (module / "views.xml").write_text(
        "<odoo><template id='custom_template' t-inherit='base.template_changed'>"
        "<xpath expr=\"//div\" position='inside'><span/></xpath>"
        "</template></odoo>",
        encoding="utf-8",
    )
    brain = BrainPack(new_brain_payload(
        source=18,
        target=19,
        ranker=LogisticRanker(),
        steps={"18_to_19": {
            "source": 18,
            "target": 19,
            "automatic_rules": [],
            "compatibility": {
                "removed_model_xml_ids": ["base.model_old"],
                "removed_group_xml_ids": ["base.group_old"],
                "changed_template_architectures": ["base.template_changed"],
            },
        }},
        training={"validation": {}},
        source_identities={},
    ))

    result = BrainRuntimeMigrator(brain).migrate(
        custom, tmp_path / "migrated", source=18, target=19
    )

    codes = {finding.code for finding in result.findings}
    assert "brain.security.model_removed" in codes
    assert "brain.security.group_removed" in codes
    assert "brain.qweb.architecture_changed" in codes
    assert result.validation_state == "blocked"


def test_brain_does_not_guess_cross_model_method_moves(tmp_path: Path):
    custom = tmp_path / "custom"
    module = _addon(custom, "custom_models", 18, model="old.model")
    source = module / "models.py"
    original = source.read_text(encoding="utf-8")
    source.write_text(original.replace("def stable_method", "def moved_method"), encoding="utf-8")
    brain = BrainPack(new_brain_payload(
        source=18,
        target=19,
        ranker=LogisticRanker(),
        steps={"18_to_19": {
            "source": 18,
            "target": 19,
            "automatic_rules": [],
            "compatibility": {
                "method_moves": [{
                    "method": "moved_method",
                    "from_model": "old.model",
                    "to_model": "new.model",
                }],
            },
        }},
        training={"validation": {}},
        source_identities={},
    ))
    result = BrainRuntimeMigrator(brain).migrate(
        custom, tmp_path / "migrated", source=18, target=19
    )

    migrated = (tmp_path / "migrated" / "custom_models" / "models.py").read_text(encoding="utf-8")
    assert migrated == source.read_text(encoding="utf-8")
    assert any(item.code == "brain.method.moved" for item in result.findings)



def test_brain_pack_schema_v3_rejects_unknown_knowledge_keys(tmp_path: Path):
    payload = new_brain_payload(
        source=18,
        target=19,
        ranker=LogisticRanker(),
        steps={
            "18_to_19": {
                "source": 18,
                "target": 19,
                "automatic_rules": [],
                "unexpected_raw_payload": "not allowed",
            }
        },
        training={"validation": {}},
        source_identities={},
    )
    with pytest.raises(ValueError, match="unsupported keys"):
        BrainPack(payload).save(tmp_path / "bad-schema.omb")


def test_brain_runtime_applies_parameter_name_only_signature_adapter(tmp_path: Path):
    custom = tmp_path / "custom"
    module = _addon(custom, "custom_demo", 18)
    path = module / "models.py"
    path.write_text(
        """from odoo import models

class Demo(models.Model):
    _inherit = 'demo.model'

    def action_demo(self, vals, context=None):
        return self._do(vals, context)
""",
        encoding="utf-8",
    )
    brain = BrainPack(new_brain_payload(
        source=18,
        target=19,
        ranker=LogisticRanker(),
        steps={
            "18_to_19": {
                "source": 18,
                "target": 19,
                "automatic_rules": [],
                "signature_adapters": [{
                    "model": "demo.model",
                    "method": "action_demo",
                    "source_signature": "self, vals, context=None",
                    "target_signature": "self, values, context=None",
                    "parameter_renames": [{"from": "vals", "to": "values"}],
                    "confidence": 1.0,
                    "evidence": "parameter_names_only_same_shape_defaults_annotations",
                }],
                "compatibility": {
                    "model_changes": [{
                        "model": "demo.model",
                        "removed_fields": [],
                        "removed_methods": [],
                        "signature_changes": ["action_demo"],
                        "signature_details": [{
                            "method": "action_demo",
                            "source": "self, vals, context=None",
                            "target": "self, values, context=None",
                        }],
                    }],
                },
            }
        },
        training={"validation": {}},
        source_identities={},
    ))

    result = BrainRuntimeMigrator(brain).migrate(
        custom, tmp_path / "migrated", source=18, target=19
    )
    migrated = (tmp_path / "migrated" / "custom_demo" / "models.py").read_text(encoding="utf-8")

    assert "def action_demo(self, values, context=None):" in migrated
    assert "self._do(values, context)" in migrated
    assert not any(item.code == "brain.signature.changed" for item in result.findings)


def test_brain_runtime_applies_exact_xml_js_and_asset_mappings(tmp_path: Path):
    custom = tmp_path / "custom"
    module = custom / "custom_web"
    (module / "static" / "src").mkdir(parents=True)
    (module / "__manifest__.py").write_text(
        repr({
            "name": "Custom Web",
            "version": "18.0.1.0.0",
            "depends": [],
            "assets": {"old.bundle": ["custom_web/static/src/main.js"]},
        }),
        encoding="utf-8",
    )
    (module / "views.xml").write_text(
        "<odoo><template id='x' t-inherit='old.template'>"
        "<t t-call='old.template'/></template></odoo>",
        encoding="utf-8",
    )
    (module / "static" / "src" / "main.js").write_text(
        "import { x } from '@old/module';\n"
        "const y = require('@old/module');\n",
        encoding="utf-8",
    )

    brain = BrainPack(new_brain_payload(
        source=18,
        target=19,
        ranker=LogisticRanker(),
        steps={
            "18_to_19": {
                "source": 18,
                "target": 19,
                "automatic_rules": [],
                "xml_id_renames": [{
                    "kind": "template",
                    "from": "old.template",
                    "to": "new.template",
                    "confidence": 1.0,
                    "evidence": "unique_exact_derived_signature",
                }],
                "js_module_renames": [{
                    "from": "@old/module",
                    "to": "@new/module",
                    "confidence": 1.0,
                    "evidence": "unique_same_static_source_location",
                }],
                "asset_bundle_renames": [{
                    "from": "old.bundle",
                    "to": "new.bundle",
                    "confidence": 1.0,
                    "evidence": "unique_exact_asset_declaration",
                }],
                "compatibility": {},
            }
        },
        training={"validation": {}},
        source_identities={},
    ))

    BrainRuntimeMigrator(brain).migrate(
        custom, tmp_path / "migrated", source=18, target=19
    )
    migrated = tmp_path / "migrated" / "custom_web"
    xml = (migrated / "views.xml").read_text(encoding="utf-8")
    js = (migrated / "static" / "src" / "main.js").read_text(encoding="utf-8")
    manifest = ast.literal_eval((migrated / "__manifest__.py").read_text(encoding="utf-8"))

    assert "new.template" in xml and "old.template" not in xml
    assert "@new/module" in js and "@old/module" not in js
    assert "new.bundle" in manifest["assets"] and "old.bundle" not in manifest["assets"]


def test_git_history_miner_finds_single_method_rename_hunk(tmp_path: Path):
    git = shutil.which("git")
    if not git:
        pytest.skip("Git unavailable")

    repo_path = tmp_path / "history"
    repo_path.mkdir()
    subprocess.run([git, "-C", str(repo_path), "init"], check=True, capture_output=True)
    subprocess.run([git, "-C", str(repo_path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run([git, "-C", str(repo_path), "config", "user.name", "Test"], check=True)

    path = repo_path / "model.py"
    path.write_text(
        "class Demo:\n    def old_method(self, vals):\n        return vals\n",
        encoding="utf-8",
    )
    subprocess.run([git, "-C", str(repo_path), "add", "."], check=True)
    subprocess.run([git, "-C", str(repo_path), "commit", "-m", "old"], check=True, capture_output=True)
    subprocess.run([git, "-C", str(repo_path), "branch", "18.0"], check=True)

    path.write_text(
        "class Demo:\n    def new_method(self, vals):\n        return vals\n",
        encoding="utf-8",
    )
    subprocess.run([git, "-C", str(repo_path), "add", "."], check=True)
    subprocess.run([git, "-C", str(repo_path), "commit", "-m", "new"], check=True, capture_output=True)
    subprocess.run([git, "-C", str(repo_path), "branch", "19.0"], check=True)

    pairs = mine_git_method_renames(repo_path, 18, 19)

    assert any(
        item.source_method == "old_method" and item.target_method == "new_method"
        for item in pairs
    )
