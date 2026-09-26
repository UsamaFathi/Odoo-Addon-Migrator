from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from odoo_migrator.brain.pack import BrainPack, new_brain_payload
from odoo_migrator.brain.audit import assert_no_source_leakage
from odoo_migrator.brain.overlay import BrainBundle, EnterpriseOverlayTrainer
from odoo_migrator.brain.ranker import LogisticRanker, RankedExample
from odoo_migrator.brain.runtime import BrainRuntimeMigrator
from odoo_migrator.brain.trainer import BrainTrainer
from odoo_migrator.brain.history import (
    mine_git_method_renames,
    mine_git_method_renames_with_status,
)
import odoo_migrator.brain.dataset as dataset_module
import odoo_migrator.brain.history as history_module
import odoo_migrator.brain.trainer as trainer_module
from odoo_migrator.sources.registry import SourceSnapshot
from odoo_migrator.sources.indexer import ModelInfo, ModuleInfo, OdooIndex, SourceIndexer


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


def _method_features(seed: int, *, node_count: int = 20) -> dict:
    return {
        "node_count": node_count,
        "structure": ("FunctionDef", "arguments", "If", "Call", "Return"),
        "calls": (f"service_{seed % 7}", "ensure_one"),
        "attributes": (f"field_{seed % 11}", "env"),
        "decorators": ("api.model",),
        "strings": (f"token_{seed % 5}",),
        "signature_shape": {
            "positional": 2 + seed % 2,
            "kwonly": 0,
            "defaults": seed % 2,
            "kw_defaults": 0,
            "vararg": False,
            "kwarg": False,
        },
        "returns": 1,
        "raises": 0,
        "branches": 1,
        "loops": 0,
    }


def _semantic_index(version: int, *, candidate_count: int = 8) -> OdooIndex:
    features = {"stable_method": _method_features(0)}
    features.update({
        f"candidate_{index:03d}": _method_features(index + 1)
        for index in range(candidate_count)
    })
    model = ModelInfo(
        "demo.model",
        methods=set(features),
        method_features=features,
    )
    module = ModuleInfo("demo", "demo", models={"demo.model": model})
    return OdooIndex(str(version), {"demo": module}, source_version=version)


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
    assert result.pack.pack_kind == "community"
    assert result.pack.enterprise_knowledge is False
    assert result.pack.distribution_policy == "public_community"


def test_brain_trainer_reports_dataset_progress_beyond_fifty_percent(tmp_path: Path):
    old = tmp_path / "odoo18"
    new = tmp_path / "odoo19"
    _addon(old, "demo_core", 18, model="demo.model")
    _addon(new, "demo_core", 19, model="demo.model")
    progress = []

    BrainTrainer(source_manager=_Manager({18: old, 19: new})).build(
        tmp_path / "progress.omb",
        source=18,
        target=19,
        progress=lambda stage, percent: progress.append((stage, percent)),
    )

    dataset_updates = [
        (stage, percent)
        for stage, percent in progress
        if stage.startswith("Dataset Odoo 18 -> 19")
    ]
    assert dataset_updates
    assert any(50 < percent < 62 for _, percent in dataset_updates)
    assert any("stable API samples" in stage for stage, _ in dataset_updates)
    assert any("exact semantic rename samples" in stage for stage, _ in dataset_updates)


def test_brain_trainer_resumes_ranker_and_completed_steps_from_checkpoint(
    tmp_path: Path,
    monkeypatch,
):
    old = tmp_path / "odoo18"
    new = tmp_path / "odoo19"
    _addon(old, "demo_core", 18, model="demo.model")
    _addon(new, "demo_core", 19, model="demo.model")
    manager = _Manager({18: old, 19: new})
    checkpoint = tmp_path / "training.checkpoint.json"
    original_save = trainer_module._save_training_checkpoint
    interrupted = False

    def save_then_interrupt(path, payload):
        nonlocal interrupted
        original_save(path, payload)
        if payload.get("steps") and not interrupted:
            interrupted = True
            raise RuntimeError("simulated Colab disconnect")

    monkeypatch.setattr(trainer_module, "_save_training_checkpoint", save_then_interrupt)
    with pytest.raises(RuntimeError, match="simulated Colab disconnect"):
        BrainTrainer(source_manager=manager).build(
            tmp_path / "interrupted.omb",
            source=18,
            target=19,
            checkpoint_path=checkpoint,
        )

    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert "18_to_19" in saved["steps"]
    assert saved["training"]["dataset"]["total"] > 0

    monkeypatch.setattr(trainer_module, "_save_training_checkpoint", original_save)
    monkeypatch.setattr(
        trainer_module,
        "_fit_semantic_ranker",
        lambda *args, **kwargs: pytest.fail("ranker training should be restored"),
    )
    monkeypatch.setattr(
        trainer_module,
        "compare_indexes",
        lambda *args, **kwargs: pytest.fail("completed API step should be restored"),
    )
    progress = []
    result = BrainTrainer(source_manager=manager).build(
        tmp_path / "resumed.omb",
        source=18,
        target=19,
        checkpoint_path=checkpoint,
        progress=lambda stage, percent: progress.append((stage, percent)),
    )

    assert result.pack.supports(18, 19)
    assert any("Resuming semantic training checkpoint" in stage for stage, _ in progress)
    assert any("Checkpoint restored Odoo 18 -> 19" in stage for stage, _ in progress)


def test_dataset_reports_every_adjacent_step_and_reuses_one_diff(monkeypatch):
    indexes = {
        16: _semantic_index(16),
        17: _semantic_index(17),
        18: _semantic_index(18),
    }
    original_compare = dataset_module.compare_indexes
    compare_calls = []

    def counted_compare(source, target):
        compare_calls.append((source.source_version, target.source_version))
        return original_compare(source, target)

    monkeypatch.setattr(dataset_module, "compare_indexes", counted_compare)
    progress = []
    dataset = dataset_module.build_method_dataset(
        indexes,
        16,
        18,
        progress=lambda stage, percent: progress.append((stage, percent)),
    )

    assert compare_calls == [(16, 17), (17, 18)]
    assert any("Odoo 16 -> 17" in stage for stage, _ in progress)
    assert any("Odoo 17 -> 18" in stage for stage, _ in progress)
    assert set(dataset.step_counts) == {"16_to_17", "17_to_18"}


def test_same_name_hard_negatives_are_bounded_and_deterministic():
    source = _semantic_index(18, candidate_count=0)
    target = _semantic_index(19, candidate_count=120)
    first_diagnostics = {}
    second_diagnostics = {}

    first = dataset_module._same_name_samples(
        source,
        target,
        "18_to_19",
        hard_negatives=3,
        diagnostics=first_diagnostics,
    )
    second = dataset_module._same_name_samples(
        source,
        target,
        "18_to_19",
        hard_negatives=3,
        diagnostics=second_diagnostics,
    )

    negatives = [sample for sample in first if sample.origin == "hard_negative"]
    assert len(negatives) <= 3
    assert [sample.key for sample in first] == [sample.key for sample in second]
    assert [sample.features for sample in first] == [sample.features for sample in second]
    assert first_diagnostics == second_diagnostics
    assert first_diagnostics["candidate_methods_considered"] == 120
    assert first_diagnostics["similarity_comparisons"] <= 24
    assert first_diagnostics["similarity_comparisons"] < 120


def test_dataset_output_is_deterministic_with_step_counters():
    indexes = {18: _semantic_index(18, candidate_count=30), 19: _semantic_index(19, candidate_count=30)}

    first = dataset_module.build_method_dataset(indexes, 18, 19)
    second = dataset_module.build_method_dataset(indexes, 18, 19)

    assert [sample.key for sample in first.train] == [sample.key for sample in second.train]
    assert [sample.key for sample in first.validation] == [sample.key for sample in second.validation]
    assert first.step_counts == second.step_counts
    assert first.step_counts["18_to_19"]["common_api_positives"] > 0
    assert first.step_counts["18_to_19"]["hard_negatives"] > 0


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
    assert result.pack.pack_kind == "enterprise_composite"
    assert result.pack.distribution_policy == "local_authorized_use_only"
    assert result.pack.payload["source_leakage_audit"]["status"] == "passed"


def test_enterprise_overlay_is_bound_to_community_brain_and_contains_no_source(tmp_path: Path):
    community18 = tmp_path / "community18"
    community19 = tmp_path / "community19"
    enterprise18 = tmp_path / "enterprise18"
    enterprise19 = tmp_path / "enterprise19"
    _addon(community18, "demo_core", 18, model="demo.model")
    _addon(community19, "demo_core", 19, model="demo.model")
    enterprise_module = _addon(
        enterprise18, "account_reports", 18, model="account.report"
    )
    _addon(enterprise19, "account_reports", 19, model="account.report")
    secret = (
        "ENTERPRISE_PRIVATE_IMPLEMENTATION_MARKER_"
        "this_line_must_never_be_embedded_in_the_overlay_payload"
    )
    (enterprise_module / "private.py").write_text(
        f"PRIVATE_MARKER = {secret!r}\n",
        encoding="utf-8",
    )
    manager = _Manager({18: community18, 19: community19})
    base = BrainTrainer(source_manager=manager).build(
        tmp_path / "community.omb", source=18, target=19
    ).pack

    result = EnterpriseOverlayTrainer(source_manager=manager).build(
        base,
        tmp_path / "enterprise-overlay.omb",
        enterprise_roots={18: enterprise18, 19: enterprise19},
    )

    overlay = result.pack
    assert overlay.pack_kind == "enterprise_overlay"
    assert overlay.base_fingerprint == base.fingerprint
    assert overlay.enterprise_knowledge is True
    assert overlay.distribution_policy == "local_authorized_use_only"
    assert overlay.payload["source_leakage_audit"]["status"] == "passed"
    assert overlay.payload["source_leakage_audit"]["files_scanned"] > 0
    assert secret not in json.dumps(overlay.payload)
    assert BrainBundle(base, overlay).enterprise_knowledge is True


def test_enterprise_overlay_rejects_wrong_community_brain(tmp_path: Path):
    base_payload = new_brain_payload(
        source=18,
        target=19,
        ranker=LogisticRanker(),
        steps={"18_to_19": {"source": 18, "target": 19, "automatic_rules": []}},
        training={"validation": {}},
        source_identities={},
    )
    base = BrainPack.load(BrainPack(base_payload).save(tmp_path / "base.omb"))
    other_payload = new_brain_payload(
        source=18,
        target=19,
        ranker=LogisticRanker(),
        steps={"18_to_19": {"source": 18, "target": 19, "automatic_rules": []}},
        training={"validation": {"precision": 0.5}},
        source_identities={},
    )
    other = BrainPack.load(BrainPack(other_payload).save(tmp_path / "other.omb"))
    overlay_payload = new_brain_payload(
        source=18,
        target=19,
        ranker=LogisticRanker(),
        steps={"18_to_19": {"source": 18, "target": 19, "automatic_rules": []}},
        training={"validation": {}, "enterprise_versions": [18, 19]},
        source_identities={},
        pack_kind="enterprise_overlay",
        base_fingerprint=base.fingerprint,
        source_leakage_audit={
            "status": "passed",
            "files_scanned": 1,
            "fragments_checked": 1,
        },
    )
    overlay = BrainPack.load(
        BrainPack(overlay_payload).save(tmp_path / "overlay.omb")
    )

    with pytest.raises(ValueError, match="different Community Brain"):
        BrainBundle(other, overlay)


def test_enterprise_overlay_runtime_needs_no_training_sources(tmp_path: Path):
    community18 = tmp_path / "community18"
    community19 = tmp_path / "community19"
    enterprise18 = tmp_path / "enterprise18"
    enterprise19 = tmp_path / "enterprise19"
    _addon(community18, "demo_core", 18, model="demo.model")
    _addon(community19, "demo_core", 19, model="demo.model")
    _addon(enterprise18, "account_reports", 18, model="account.report")
    _addon(enterprise19, "account_reports", 19, model="account.report")
    manager = _Manager({18: community18, 19: community19})
    base = BrainTrainer(source_manager=manager).build(
        tmp_path / "base.omb", source=18, target=19
    ).pack
    overlay = EnterpriseOverlayTrainer(source_manager=manager).build(
        base,
        tmp_path / "overlay.omb",
        enterprise_roots={18: enterprise18, 19: enterprise19},
    ).pack
    custom = tmp_path / "custom"
    _addon(custom, "custom_sale", 18, model="sale.order")
    before = SourceIndexer.project_fingerprint(custom)
    shutil.rmtree(community18)
    shutil.rmtree(community19)
    shutil.rmtree(enterprise18)
    shutil.rmtree(enterprise19)

    result = BrainRuntimeMigrator(base, overlay=overlay).migrate(
        custom,
        tmp_path / "migrated",
        source=18,
        target=19,
    )

    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["source_code_indexed_at_runtime"] is False
    assert metadata["enterprise_knowledge"] is True
    assert metadata["brain_components"] == {
        "community": base.fingerprint,
        "enterprise_overlay": overlay.fingerprint,
    }
    assert SourceIndexer.project_fingerprint(custom) == before


def test_source_leakage_audit_rejects_verbatim_enterprise_fragment(tmp_path: Path):
    enterprise = tmp_path / "enterprise"
    enterprise.mkdir()
    source_line = (
        "def private_enterprise_algorithm(self, records): return "
        "self._perform_confidential_enterprise_calculation(records)"
    )
    (enterprise / "private.py").write_text(source_line + "\n", encoding="utf-8")
    payload = {"description": source_line}

    with pytest.raises(ValueError, match="source leakage audit failed"):
        assert_no_source_leakage(payload, [enterprise])


def test_enterprise_pack_cannot_be_saved_without_completed_leakage_audit(tmp_path: Path):
    payload = new_brain_payload(
        source=18,
        target=19,
        ranker=LogisticRanker(),
        steps={"18_to_19": {"source": 18, "target": 19, "automatic_rules": []}},
        training={"validation": {}, "enterprise_versions": [18, 19]},
        source_identities={},
        pack_kind="enterprise_overlay",
        base_fingerprint="a" * 64,
    )

    with pytest.raises(ValueError, match="source leakage audit did not pass"):
        BrainPack(payload).save(tmp_path / "unaudited-overlay.omb")


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


def test_git_history_timeout_is_non_fatal_and_reported(tmp_path: Path, monkeypatch):
    repo_path = tmp_path / "history-timeout"
    (repo_path / ".git").mkdir(parents=True)
    monkeypatch.setattr(history_module.shutil, "which", lambda name: "git")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs.get("timeout", 0))

    monkeypatch.setattr(history_module.subprocess, "run", timeout)

    result = mine_git_method_renames_with_status(
        repo_path,
        18,
        19,
        timeout_seconds=0.01,
    )

    assert result.renames == ()
    assert result.status == "timeout"
    assert "exceeded" in (result.detail or "")


def test_brain_training_continues_when_git_history_times_out(tmp_path: Path, monkeypatch):
    old = tmp_path / "odoo18"
    new = tmp_path / "odoo19"
    history = tmp_path / "history"
    (history / ".git").mkdir(parents=True)
    _addon(old, "demo_core", 18, model="demo.model")
    _addon(new, "demo_core", 19, model="demo.model")
    monkeypatch.setattr(history_module.shutil, "which", lambda name: "git")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs.get("timeout", 0))

    monkeypatch.setattr(history_module.subprocess, "run", timeout)
    progress = []
    result = BrainTrainer(
        source_manager=_Manager({18: old, 19: new}),
        history_timeout_seconds=0.01,
    ).build(
        tmp_path / "timeout.omb",
        source=18,
        target=19,
        history_repo=history,
        progress=lambda stage, percent: progress.append((stage, percent)),
    )

    diagnostics = result.pack.training["history_supervision"]["diagnostics"]["18_to_19"]
    assert result.pack.supports(18, 19)
    assert diagnostics["status"] == "timeout"
    assert diagnostics["rename_pairs"] == 0
    assert any("skipped after timeout" in stage for stage, _ in progress)


def test_brain_training_succeeds_without_history_supervision(tmp_path: Path):
    old = tmp_path / "odoo18"
    new = tmp_path / "odoo19"
    _addon(old, "demo_core", 18, model="demo.model")
    _addon(new, "demo_core", 19, model="demo.model")
    progress = []

    result = BrainTrainer(source_manager=_Manager({18: old, 19: new})).build(
        tmp_path / "without-history.omb",
        source=18,
        target=19,
        progress=lambda stage, percent: progress.append((stage, percent)),
    )

    assert result.pack.supports(18, 19)
    assert result.pack.training["history_supervision"]["enabled"] is False
    assert any("history supervision unavailable" in stage.lower() for stage, _ in progress)



def test_brain_trainer_rejects_one_direct_enterprise_tree_for_multiple_versions(tmp_path: Path):
    community18 = tmp_path / "community18"
    community19 = tmp_path / "community19"
    enterprise = tmp_path / "enterprise"
    _addon(community18, "demo_core", 18, model="demo.model")
    _addon(community19, "demo_core", 19, model="demo.model")
    _addon(enterprise, "web_enterprise", 18, model="web.enterprise")

    trainer = BrainTrainer(source_manager=_Manager({18: community18, 19: community19}))

    with pytest.raises(ValueError, match="single direct addons tree"):
        trainer.build(
            tmp_path / "brain.omb",
            source=18,
            target=19,
            enterprise_root=enterprise,
        )
