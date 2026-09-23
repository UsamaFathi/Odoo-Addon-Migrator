from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable

from odoo_migrator.migrations.autonomous import (
    DependencyModuleRenameResolver,
    ModelRenameResolver,
)
from odoo_migrator.migrations.method_matching import method_similarity_components
from odoo_migrator.migrations.registry import MigrationPackRegistry, default_registry
from odoo_migrator.sources.composite import compose_indexes
from odoo_migrator.sources.diff import SourceDiff, compare_indexes
from odoo_migrator.sources.enterprise import resolve_enterprise_source
from odoo_migrator.sources.indexer import OdooIndex, SourceIndexer
from odoo_migrator.sources.manager import SourceManager

from .dataset import build_method_dataset
from .pack import BrainPack, new_brain_payload
from .ranker import LogisticRanker, RankedExample


@dataclass(frozen=True, slots=True)
class BrainTrainingResult:
    pack: BrainPack
    output: Path
    training_samples: int
    validation_metrics: dict
    method_renames: int
    model_renames: int
    dependency_renames: int


def _learned_method_renames(
    source: OdooIndex,
    target: OdooIndex,
    diff: SourceDiff,
    ranker: LogisticRanker,
    *,
    threshold: float = 0.90,
    minimum_margin: float = 0.10,
) -> list[dict]:
    predictions: list[dict] = []
    changes = {item.model: item for item in diff.model_changes}

    for model_name, change in changes.items():
        if not change.removed_methods or not change.added_methods:
            continue
        old_model = source.models.get(model_name)
        new_model = target.models.get(model_name)
        if old_model is None or new_model is None:
            continue

        for old_name in sorted(change.removed_methods):
            old_features = old_model.method_features.get(old_name)
            if not old_features or old_features.get("node_count", 0) < 6:
                continue

            ranked: list[tuple[float, str, dict[str, float]]] = []
            for new_name in sorted(change.added_methods):
                new_features = new_model.method_features.get(new_name)
                if not new_features or new_features.get("node_count", 0) < 6:
                    continue
                features = method_similarity_components(
                    old_name,
                    old_features,
                    new_name,
                    new_features,
                )
                ranked.append((ranker.predict_proba(features), new_name, features))

            if not ranked:
                continue
            ranked.sort(reverse=True, key=lambda item: item[0])
            best_probability, best_name, features = ranked[0]
            second = ranked[1][0] if len(ranked) > 1 else 0.0
            margin = best_probability - second
            if best_probability < threshold or margin < minimum_margin:
                continue
            predictions.append({
                "model": model_name,
                "from": old_name,
                "to": best_name,
                "confidence": round(best_probability, 6),
                "margin": round(margin, 6),
                "features": {key: round(value, 6) for key, value in features.items()},
            })

    # Never allow two removed methods to collapse onto the same target method.
    target_use: dict[tuple[str, str], int] = {}
    for item in predictions:
        key = (item["model"], item["to"])
        target_use[key] = target_use.get(key, 0) + 1
    return [
        item
        for item in predictions
        if target_use[(item["model"], item["to"])] == 1
    ]


def _model_renames(source: OdooIndex, target: OdooIndex, diff: SourceDiff,
                   source_version: int, target_version: int) -> list[dict]:
    resolver = ModelRenameResolver(source_version, target_version)
    values = []
    for old_name in sorted(diff.models_removed):
        successor = resolver._successor(old_name, source, target, diff)
        if successor:
            values.append({
                "from": old_name,
                "to": successor,
                "confidence": 1.0,
                "evidence": "unique_exact_api_fingerprint",
            })

    target_use: dict[str, int] = {}
    for item in values:
        target_use[item["to"]] = target_use.get(item["to"], 0) + 1
    return [item for item in values if target_use[item["to"]] == 1]


def _dependency_renames(source: OdooIndex, target: OdooIndex, diff: SourceDiff,
                        source_version: int, target_version: int) -> list[dict]:
    resolver = DependencyModuleRenameResolver(source_version, target_version)
    values = []
    for old_name in sorted(diff.modules_removed):
        successor = resolver._successor(old_name, source, target)
        if successor:
            values.append({
                "from": old_name,
                "to": successor,
                "confidence": 1.0,
                "evidence": "unique_model_owner_match",
            })

    target_use: dict[str, int] = {}
    for item in values:
        target_use[item["to"]] = target_use.get(item["to"], 0) + 1
    return [item for item in values if target_use[item["to"]] == 1]


class BrainTrainer:
    """Build a reusable migration model from official Odoo source once."""

    def __init__(
        self,
        *,
        source_manager: SourceManager | None = None,
        registry: MigrationPackRegistry | None = None,
        indexer: SourceIndexer | None = None,
    ):
        self.source_manager = source_manager or SourceManager()
        self.registry = registry or default_registry()
        self.indexer = indexer or SourceIndexer()

    def build(
        self,
        output: str | Path,
        *,
        source: int = 14,
        target: int = 19,
        enterprise_root: str | Path | None = None,
        progress: Callable[[str, int], None] | None = None,
    ) -> BrainTrainingResult:
        if target <= source:
            raise ValueError("Migration Brain target must be higher than source.")
        for version in range(source, target):
            self.registry.require(version, version + 1)

        def report(message: str, percent: int) -> None:
            if progress:
                progress(message, percent)

        indexes: dict[int, OdooIndex] = {}
        identities: dict[str, dict] = {}
        enterprise_versions: list[int] = []
        count = target - source + 1

        for offset, version in enumerate(range(source, target + 1)):
            report(f"Preparing Community Odoo {version}", 5 + int(offset / count * 25))
            snapshot = self.source_manager.ensure(version)
            community = self.indexer.index(
                snapshot.path,
                source_commit=snapshot.actual_commit,
                source_mode=snapshot.source_mode.value,
                source_version=version,
            )
            identities[str(version)] = {
                "community_commit": snapshot.actual_commit,
                "community_mode": snapshot.source_mode.value,
                "enterprise": False,
            }

            if enterprise_root is not None:
                report(f"Preparing Enterprise Odoo {version}", 20 + int(offset / count * 25))
                resolution = resolve_enterprise_source(enterprise_root, version)
                enterprise = self.indexer.index(
                    resolution.source_root,
                    source_commit=resolution.commit,
                    source_mode="enterprise_local",
                    source_version=version,
                )
                community = compose_indexes(community, enterprise)
                enterprise_versions.append(version)
                identities[str(version)].update({
                    "enterprise": True,
                    "enterprise_mode": resolution.mode,
                    "enterprise_ref": resolution.ref,
                    "enterprise_commit": resolution.commit,
                })
            indexes[version] = community

        report("Building supervised semantic dataset", 50)
        dataset = build_method_dataset(indexes, source, target)
        if dataset.positives == 0 or dataset.negatives == 0:
            raise ValueError(
                "Not enough semantic training examples were discovered in the selected Odoo sources."
            )

        report("Training semantic API ranker", 62)
        ranker = LogisticRanker()
        ranker.fit(sample.ranked() for sample in dataset.train)
        validation = ranker.evaluate(sample.ranked() for sample in dataset.validation)

        steps: dict[str, dict] = {}
        method_count = model_count = dependency_count = 0
        for offset, version in enumerate(range(source, target)):
            next_version = version + 1
            report(
                f"Learning Odoo {version} -> {next_version} API changes",
                70 + int(offset / max(1, target - source) * 22),
            )
            old, new = indexes[version], indexes[next_version]
            diff = compare_indexes(old, new)
            methods = _learned_method_renames(old, new, diff, ranker)
            models = _model_renames(old, new, diff, version, next_version)
            dependencies = _dependency_renames(old, new, diff, version, next_version)
            rules = [
                rule.rule_id
                for rule in self.registry.require(version, next_version).rule_factory()
                if rule.automatic
            ]
            key = f"{version}_to_{next_version}"
            steps[key] = {
                "source": version,
                "target": next_version,
                "method_renames": methods,
                "model_renames": models,
                "dependency_renames": dependencies,
                "automatic_rules": rules,
            }
            method_count += len(methods)
            model_count += len(models)
            dependency_count += len(dependencies)

        training = {
            "dataset": dataset.as_dict(),
            "validation": validation.as_dict(),
            "enterprise_versions": enterprise_versions,
            "method_threshold": 0.90,
            "method_margin": 0.10,
        }
        payload = new_brain_payload(
            source=source,
            target=target,
            ranker=ranker,
            steps=steps,
            training=training,
            source_identities=identities,
        )
        pack = BrainPack(payload)
        report("Writing Migration Brain pack", 96)
        destination = pack.save(output)
        loaded = BrainPack.load(destination)
        report("Migration Brain ready", 100)
        return BrainTrainingResult(
            loaded,
            destination,
            dataset.total,
            validation.as_dict(),
            method_count,
            model_count,
            dependency_count,
        )
