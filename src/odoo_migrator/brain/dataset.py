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


@dataclass(frozen=True, slots=True)
class Dataset:
    train: tuple[MethodTrainingSample, ...]
    validation: tuple[MethodTrainingSample, ...]
    positives: int
    negatives: int

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
        }


def _holdout(sample: MethodTrainingSample) -> bool:
    digest = hashlib.sha256(sample.key.encode("utf-8")).digest()
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


def build_method_dataset(indexes: Mapping[int, OdooIndex], source: int, target: int) -> Dataset:
    samples: list[MethodTrainingSample] = []
    for version in range(source, target):
        old = indexes[version]
        new = indexes[version + 1]
        step = f"{version}_to_{version + 1}"
        samples.extend(_same_name_samples(old, new, step))
        samples.extend(_weak_rename_samples(old, new, step))

    unique: dict[str, MethodTrainingSample] = {}
    for sample in samples:
        unique.setdefault(sample.key, sample)
    rows = tuple(unique.values())

    train = tuple(sample for sample in rows if not _holdout(sample))
    validation = tuple(sample for sample in rows if _holdout(sample))
    positives = sum(sample.label == 1 for sample in rows)
    negatives = sum(sample.label == 0 for sample in rows)

    if not validation and train:
        validation = train[-max(1, len(train) // 5):]
        train = train[:-len(validation)] or validation
    return Dataset(train, validation, positives, negatives)
