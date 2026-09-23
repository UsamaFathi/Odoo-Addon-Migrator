from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable, Mapping

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
from .history import mine_git_method_renames
from .knowledge import (
    asset_bundle_renames,
    field_renames,
    js_module_renames,
    signature_adapters,
    step_knowledge,
    xml_id_renames,
)
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
    field_renames: int = 0
    xml_id_renames: int = 0
    js_module_renames: int = 0
    asset_bundle_renames: int = 0
    signature_adapters: int = 0


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


def _grouped_decision_metrics(ranker: LogisticRanker, samples, *, threshold: float, margin: float) -> dict:
    groups: dict[str, list] = {}
    for sample in samples:
        groups.setdefault(sample.group, []).append(sample)

    correct = false_auto = abstained = 0
    for rows in groups.values():
        ranked = sorted(
            (
                (ranker.predict_proba(sample.features), sample)
                for sample in rows
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        if not ranked:
            continue
        best_probability, best_sample = ranked[0]
        second_probability = ranked[1][0] if len(ranked) > 1 else 0.0
        if best_probability < threshold or best_probability - second_probability < margin:
            abstained += 1
            continue
        if best_sample.label == 1:
            correct += 1
        else:
            false_auto += 1

    decisions = correct + false_auto
    total = len(groups)
    precision = correct / decisions if decisions else 0.0
    recall = correct / total if total else 0.0
    false_auto_rate = false_auto / decisions if decisions else 0.0
    coverage = decisions / total if total else 0.0
    return {
        "groups": total,
        "decisions": decisions,
        "correct_auto_fixes": correct,
        "false_auto_fixes": false_auto,
        "abstained": abstained,
        "precision": precision,
        "recall": recall,
        "false_auto_fix_rate": false_auto_rate,
        "coverage": coverage,
        "threshold": threshold,
        "margin": margin,
    }


def _calibrate_decision_gate(ranker: LogisticRanker, samples) -> dict:
    rows = tuple(samples)
    if not rows:
        return _grouped_decision_metrics(ranker, rows, threshold=0.90, margin=0.10)

    candidates = []
    for threshold in (0.80, 0.85, 0.88, 0.90, 0.92, 0.94, 0.96, 0.98):
        for margin in (0.08, 0.10, 0.12, 0.15, 0.20):
            metrics = _grouped_decision_metrics(
                ranker,
                rows,
                threshold=threshold,
                margin=margin,
            )
            if metrics["decisions"]:
                candidates.append(metrics)

    if not candidates:
        return _grouped_decision_metrics(ranker, rows, threshold=0.98, margin=0.20)

    zero_false = [item for item in candidates if item["false_auto_fixes"] == 0]
    pool = zero_false or candidates
    pool.sort(
        key=lambda item: (
            item["precision"],
            item["recall"],
            item["coverage"],
            item["threshold"],
            item["margin"],
        ),
        reverse=True,
    )
    return pool[0]


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
        enterprise_roots: Mapping[int, str | Path] | None = None,
        history_repo: str | Path | None = None,
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

        resolved_direct_enterprise: dict[Path, list[int]] = {}
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
                "version": version,
                "community_commit": snapshot.actual_commit,
                "community_mode": snapshot.source_mode.value,
                "community_branch": snapshot.branch,
                "community_origin": snapshot.origin,
                "enterprise": False,
            }

            selected_enterprise = (enterprise_roots or {}).get(version, enterprise_root)
            if selected_enterprise is not None:
                report(f"Preparing Enterprise Odoo {version}", 20 + int(offset / count * 25))
                resolution = resolve_enterprise_source(selected_enterprise, version)
                if resolution.mode == "direct_folder":
                    resolved_direct_enterprise.setdefault(
                        resolution.source_root.resolve(), []
                    ).append(version)
                    reused_versions = resolved_direct_enterprise[resolution.source_root.resolve()]
                    if len(reused_versions) > 1:
                        joined = ", ".join(str(item) for item in reused_versions)
                        raise ValueError(
                            "The selected Enterprise folder is a single direct addons tree "
                            f"and cannot safely represent multiple Odoo versions ({joined}). "
                            "For a multi-version Brain build, select a repository root with "
                            "version folders/branches, or configure a separate Enterprise "
                            "folder for each Odoo version."
                        )
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
                    "enterprise_source_layer": "enterprise",
                })
            indexes[version] = community

        report("Building supervised semantic dataset", 50)
        history_root = Path(history_repo).expanduser().resolve() if history_repo else None
        if history_root is None and enterprise_root is not None:
            candidate = Path(enterprise_root).expanduser().resolve()
            if (candidate / ".git").exists():
                history_root = candidate

        history_pairs: dict[str, set[tuple[str, str]]] = {}
        history_label_count = 0
        if history_root is not None and (history_root / ".git").exists():
            for version in range(source, target):
                items = mine_git_method_renames(history_root, version, version + 1)
                pairs = {(item.source_method, item.target_method) for item in items}
                history_pairs[f"{version}_to_{version + 1}"] = pairs
                history_label_count += len(pairs)

        dataset = build_method_dataset(
            indexes,
            source,
            target,
            history_pairs=history_pairs,
        )
        if dataset.positives == 0 or dataset.negatives == 0:
            raise ValueError(
                "Not enough semantic training examples were discovered in the selected Odoo sources."
            )

        report("Training semantic API ranker", 62)
        ranker = LogisticRanker()
        ranker.fit(sample.ranked() for sample in dataset.train)
        baseline_validation = ranker.evaluate(
            (sample.ranked() for sample in dataset.validation),
            threshold=0.50,
        )
        production_gate = _calibrate_decision_gate(ranker, dataset.validation)
        production_threshold = float(production_gate["threshold"])
        production_margin = float(production_gate["margin"])

        steps: dict[str, dict] = {}
        method_count = model_count = dependency_count = field_count = 0
        xml_id_count = js_module_count = asset_bundle_count = signature_adapter_count = 0
        for offset, version in enumerate(range(source, target)):
            next_version = version + 1
            report(
                f"Learning Odoo {version} -> {next_version} API changes",
                70 + int(offset / max(1, target - source) * 22),
            )
            old, new = indexes[version], indexes[next_version]
            diff = compare_indexes(old, new)
            methods = _learned_method_renames(
                old,
                new,
                diff,
                ranker,
                threshold=production_threshold,
                minimum_margin=production_margin,
            )
            models = _model_renames(old, new, diff, version, next_version)
            dependencies = _dependency_renames(old, new, diff, version, next_version)
            fields = field_renames(old, new, diff)
            xml_ids = xml_id_renames(old, new)
            js_modules = js_module_renames(old, new)
            asset_bundles = asset_bundle_renames(old, new)
            signatures = signature_adapters(old, new, diff)
            rule_metadata = [
                {
                    "rule_id": rule.rule_id,
                    "category": rule.category,
                    "classification": rule.classification.value,
                    "automatic": rule.automatic,
                    "description": rule.description,
                    "evidence": rule.evidence,
                }
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
                "field_renames": fields,
                "xml_id_renames": xml_ids,
                "js_module_renames": js_modules,
                "asset_bundle_renames": asset_bundles,
                "signature_adapters": signatures,
                "automatic_rules": [item["rule_id"] for item in rule_metadata],
                "transformations": rule_metadata,
                "compatibility": step_knowledge(old, new, diff),
            }
            method_count += len(methods)
            model_count += len(models)
            dependency_count += len(dependencies)
            field_count += len(fields)
            xml_id_count += len(xml_ids)
            js_module_count += len(js_modules)
            asset_bundle_count += len(asset_bundles)
            signature_adapter_count += len(signatures)

        training = {
            "dataset": dataset.as_dict(),
            "validation": baseline_validation.as_dict(),
            "production_validation": {
                key: round(value, 6) if isinstance(value, float) else value
                for key, value in production_gate.items()
            },
            "enterprise_versions": enterprise_versions,
            "method_threshold": production_threshold,
            "method_margin": production_margin,
            "metrics": {
                "precision": production_gate["precision"],
                "recall": production_gate["recall"],
                "false_auto_fix_rate": production_gate["false_auto_fix_rate"],
                "coverage": production_gate["coverage"],
                "baseline_f1_at_0_5": baseline_validation.f1,
            },
            "split_strategy": dataset.split_strategy,
            "history_supervision": {
                "enabled": bool(history_pairs),
                "rename_pairs": history_label_count,
                "steps": {
                    step: len(pairs)
                    for step, pairs in sorted(history_pairs.items())
                },
            },
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
            training["production_validation"],
            method_count,
            model_count,
            dependency_count,
            field_count,
            xml_id_count,
            js_module_count,
            asset_bundle_count,
            signature_adapter_count,
        )
