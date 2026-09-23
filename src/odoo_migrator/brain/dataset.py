from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Mapping

from odoo_migrator.migrations.method_matching import (
    high_confidence_method_renames,
    method_similarity_components,
)
from odoo_migrator.sources.diff import compare_indexes
from odoo_migrator.sources.indexer import OdooIndex

from .ranker import RankedExample


@dataclass(frozen=True, slots=True)
class MethodTrainingSample:
    step: str
    model: str
    source_method: str
    target_method: str
    features: dict[str, float]
    label: int
    weight: float
    origin: str

    @property
    def key(self) -> str:
        return (
            f"{self.step}|{self.model}|{self.source_method}|"
            f"{self.target_method}|{self.label}|{self.origin}"
        )

    def ranked(self) -> RankedExample:
        return RankedExample(self.features, self.label, self.weight)

    @property
    def group(self) -> str:
        """Leakage-resistant split unit for one source API decision."""
        return f"{self.step}|{self.model}|{self.source_method}"


@dataclass(frozen=True, slots=True)
class Dataset:
    train: tuple[MethodTrainingSample, ...]
    validation: tuple[MethodTrainingSample, ...]
    positives: int
    negatives: int
    split_strategy: str = "grouped_source_api_sha256"

    @property
    def total(self) -> int:
        return len(self.train) + len(self.validation)

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "train": len(self.train),
            "validation": len(self.validation),
            "positives": self.positives,
            "negatives": self.negatives,
            "split_strategy": self.split_strategy,
        }


def _holdout_group(group: str) -> bool:
    digest = hashlib.sha256(group.encode("utf-8")).digest()
    return digest[0] % 5 == 0


def _feature_pair(source_name: str, source_features: dict,
                  target_name: str, target_features: dict) -> dict[str, float]:
    return method_similarity_components(
        source_name,
        source_features,
        target_name,
        target_features,
    )


def _same_name_samples(source: OdooIndex, target: OdooIndex, step: str,
                       hard_negatives: int = 3) -> list[MethodTrainingSample]:
    samples: list[MethodTrainingSample] = []
    source_models = source.models
    target_models = target.models

    for model_name in sorted(source_models.keys() & target_models.keys()):
        old = source_models[model_name]
        new = target_models[model_name]
        common = sorted(old.methods & new.methods)
        for method_name in common:
            old_features = old.method_features.get(method_name)
            new_features = new.method_features.get(method_name)
            if not old_features or not new_features:
                continue
            if min(old_features.get("node_count", 0), new_features.get("node_count", 0)) < 6:
                continue

            samples.append(MethodTrainingSample(
                step,
                model_name,
                method_name,
                method_name,
                _feature_pair(method_name, old_features, method_name, new_features),
                1,
                1.0,
                "stable_api",
            ))

            candidates = []
            for candidate_name, candidate_features in new.method_features.items():
                if candidate_name == method_name:
                    continue
                if candidate_features.get("node_count", 0) < 6:
                    continue
                features = _feature_pair(
                    method_name, old_features, candidate_name, candidate_features
                )
                hardness = (
                    features["ast"] * 0.40
                    + features["calls"] * 0.25
                    + features["attrs"] * 0.15
                    + features["signature"] * 0.10
                    + features["name"] * 0.10
                )
                candidates.append((hardness, candidate_name, features))

            for _, candidate_name, features in sorted(candidates, reverse=True)[:hard_negatives]:
                samples.append(MethodTrainingSample(
                    step,
                    model_name,
                    method_name,
                    candidate_name,
                    features,
                    0,
                    1.0,
                    "hard_negative",
                ))
    return samples



def _exact_semantic_rename_samples(
    source: OdooIndex,
    target: OdooIndex,
    step: str,
    *,
    hard_negatives: int = 3,
) -> list[MethodTrainingSample]:
    """Build trusted rename examples from unique exact semantic fingerprints.

    This does not depend on the learned ranker or the legacy weighted matcher:
    a removed method and an added method must have the same structural/call/
    attribute/signature/control fingerprint and the match must be one-to-one.
    """
    diff = compare_indexes(source, target)
    samples: list[MethodTrainingSample] = []

    def fingerprint(features: dict) -> tuple:
        shape = features.get("signature_shape", {})
        return (
            tuple(features.get("structure", ())),
            tuple(features.get("calls", ())),
            tuple(features.get("attributes", ())),
            tuple(features.get("decorators", ())),
            tuple(features.get("strings", ())),
            tuple(sorted(shape.items())),
            int(features.get("returns", 0)),
            int(features.get("raises", 0)),
            int(features.get("branches", 0)),
            int(features.get("loops", 0)),
        )

    for change in diff.model_changes:
        if not change.removed_methods or not change.added_methods:
            continue
        old_model = source.models.get(change.model)
        new_model = target.models.get(change.model)
        if old_model is None or new_model is None:
            continue

        added_by_fp: dict[tuple, list[str]] = {}
        for new_name in sorted(change.added_methods):
            features = new_model.method_features.get(new_name)
            if not features or features.get("node_count", 0) < 8:
                continue
            added_by_fp.setdefault(fingerprint(features), []).append(new_name)

        candidate_use: dict[str, int] = {}
        positives: list[tuple[str, str]] = []
        for old_name in sorted(change.removed_methods):
            old_features = old_model.method_features.get(old_name)
            if not old_features or old_features.get("node_count", 0) < 8:
                continue
            candidates = added_by_fp.get(fingerprint(old_features), [])
            if len(candidates) != 1:
                continue
            new_name = candidates[0]
            positives.append((old_name, new_name))
            candidate_use[new_name] = candidate_use.get(new_name, 0) + 1

        for old_name, new_name in positives:
            if candidate_use[new_name] != 1:
                continue
            old_features = old_model.method_features[old_name]
            new_features = new_model.method_features[new_name]
            samples.append(MethodTrainingSample(
                step,
                change.model,
                old_name,
                new_name,
                _feature_pair(old_name, old_features, new_name, new_features),
                1,
                1.0,
                "exact_semantic_rename",
            ))

            negatives = []
            for candidate_name in sorted(change.added_methods):
                if candidate_name == new_name:
                    continue
                candidate_features = new_model.method_features.get(candidate_name)
                if not candidate_features or candidate_features.get("node_count", 0) < 6:
                    continue
                features = _feature_pair(
                    old_name, old_features, candidate_name, candidate_features
                )
                hardness = (
                    features["ast"] * 0.40
                    + features["calls"] * 0.25
                    + features["attrs"] * 0.15
                    + features["signature"] * 0.10
                    + features["name"] * 0.10
                )
                negatives.append((hardness, candidate_name, features))
            for _, candidate_name, features in sorted(negatives, reverse=True)[:hard_negatives]:
                samples.append(MethodTrainingSample(
                    step,
                    change.model,
                    old_name,
                    candidate_name,
                    features,
                    0,
                    1.0,
                    "exact_rename_hard_negative",
                ))
    return samples

def _weak_rename_samples(source: OdooIndex, target: OdooIndex, step: str) -> list[MethodTrainingSample]:
    """Use only existing ultra-conservative rename matches as weak supervision."""
    diff = compare_indexes(source, target)
    samples = []
    for match in high_confidence_method_renames(
        source,
        target,
        diff,
        threshold=0.94,
        minimum_margin=0.18,
    ):
        old = source.models.get(match.model)
        new = target.models.get(match.model)
        if old is None or new is None:
            continue
        old_features = old.method_features.get(match.source_method)
        new_features = new.method_features.get(match.target_method)
        if not old_features or not new_features:
            continue
        samples.append(MethodTrainingSample(
            step,
            match.model,
            match.source_method,
            match.target_method,
            _feature_pair(
                match.source_method,
                old_features,
                match.target_method,
                new_features,
            ),
            1,
            0.60,
            "weak_rename",
        ))
    return samples



def _history_rename_samples(
    source: OdooIndex,
    target: OdooIndex,
    step: str,
    pairs: set[tuple[str, str]],
    *,
    hard_negatives: int = 3,
) -> list[MethodTrainingSample]:
    if not pairs:
        return []
    diff = compare_indexes(source, target)
    samples: list[MethodTrainingSample] = []

    for old_name, new_name in sorted(pairs):
        matches = [
            change
            for change in diff.model_changes
            if old_name in change.removed_methods and new_name in change.added_methods
        ]
        if len(matches) != 1:
            continue
        change = matches[0]
        old_model = source.models.get(change.model)
        new_model = target.models.get(change.model)
        if old_model is None or new_model is None:
            continue
        old_features = old_model.method_features.get(old_name)
        new_features = new_model.method_features.get(new_name)
        if not old_features or not new_features:
            continue
        if min(old_features.get("node_count", 0), new_features.get("node_count", 0)) < 6:
            continue

        samples.append(MethodTrainingSample(
            step,
            change.model,
            old_name,
            new_name,
            _feature_pair(old_name, old_features, new_name, new_features),
            1,
            1.25,
            "git_history_rename",
        ))

        negatives = []
        for candidate_name in sorted(change.added_methods):
            if candidate_name == new_name:
                continue
            candidate_features = new_model.method_features.get(candidate_name)
            if not candidate_features or candidate_features.get("node_count", 0) < 6:
                continue
            features = _feature_pair(
                old_name, old_features, candidate_name, candidate_features
            )
            hardness = (
                features["ast"] * 0.40
                + features["calls"] * 0.25
                + features["attrs"] * 0.15
                + features["signature"] * 0.10
                + features["name"] * 0.10
            )
            negatives.append((hardness, candidate_name, features))
        for _, candidate_name, features in sorted(negatives, reverse=True)[:hard_negatives]:
            samples.append(MethodTrainingSample(
                step,
                change.model,
                old_name,
                candidate_name,
                features,
                0,
                1.0,
                "git_history_hard_negative",
            ))
    return samples

def build_method_dataset(
    indexes: Mapping[int, OdooIndex],
    source: int,
    target: int,
    *,
    history_pairs: Mapping[str, set[tuple[str, str]]] | None = None,
) -> Dataset:
    samples: list[MethodTrainingSample] = []
    for version in range(source, target):
        old = indexes[version]
        new = indexes[version + 1]
        step = f"{version}_to_{version + 1}"
        samples.extend(_same_name_samples(old, new, step))
        samples.extend(_history_rename_samples(
            old,
            new,
            step,
            set((history_pairs or {}).get(step, set())),
        ))
        samples.extend(_exact_semantic_rename_samples(old, new, step))
        samples.extend(_weak_rename_samples(old, new, step))

    unique: dict[str, MethodTrainingSample] = {}
    for sample in samples:
        unique.setdefault(sample.key, sample)
    rows = tuple(unique.values())

    train = tuple(sample for sample in rows if not _holdout_group(sample.group))
    validation = tuple(sample for sample in rows if _holdout_group(sample.group))
    positives = sum(sample.label == 1 for sample in rows)
    negatives = sum(sample.label == 0 for sample in rows)

    if not validation and rows:
        groups = sorted({sample.group for sample in rows})
        if len(groups) > 1:
            validation_group_count = max(1, len(groups) // 5)
            validation_groups = set(groups[-validation_group_count:])
            validation = tuple(sample for sample in rows if sample.group in validation_groups)
            train = tuple(sample for sample in rows if sample.group not in validation_groups)
        else:
            # Tiny synthetic fixtures may contain only one decision group.
            # Keep training possible, but the trainer will expose zero-coverage
            # production metrics rather than treating this as independent holdout.
            train = rows
            validation = ()
    return Dataset(train, validation, positives, negatives)
