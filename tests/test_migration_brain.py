from __future__ import annotations

import ast
import json
from pathlib import Path

from odoo_migrator.brain.pack import BrainPack, new_brain_payload
from odoo_migrator.brain.ranker import LogisticRanker, RankedExample
from odoo_migrator.brain.runtime import BrainRuntimeMigrator
from odoo_migrator.brain.trainer import BrainTrainer
from odoo_migrator.sources.registry import SourceSnapshot


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
