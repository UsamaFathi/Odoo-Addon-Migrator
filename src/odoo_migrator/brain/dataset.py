from __future__ import annotations

from dataclasses import dataclass, field
import heapq
import hashlib
import logging
from time import perf_counter
from collections.abc import Callable, Iterable, Mapping

from odoo_migrator.migrations.method_matching import (
    high_confidence_method_renames,
    method_similarity_components,
)
from odoo_migrator.sources.diff import SourceDiff, compare_indexes
from odoo_migrator.sources.indexer import OdooIndex

from .ranker import RankedExample


logger = logging.getLogger(__name__)
DatasetProgress = Callable[[str, int], None]


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
    step_counts: dict[str, dict[str, int]] = field(default_factory=dict)

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
            "steps": {
                step: dict(counts)
                for step, counts in sorted(self.step_counts.items())
            },
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


def _set_overlap(left, right) -> float:
    left_values = set(left or ())
    right_values = set(right or ())
    if not left_values and not right_values:
        return 0.5
    if not left_values or not right_values:
        return 0.0
    return len(left_values & right_values) / len(left_values | right_values)


def _signature_shape_similarity(left: dict, right: dict) -> float:
    keys = ("positional", "kwonly", "defaults", "kw_defaults", "vararg", "kwarg")
    return sum(left.get(key) == right.get(key) for key in keys) / len(keys)


def _cheap_candidate_score(
    source_name: str,
    source_features: dict,
    target_name: str,
    target_features: dict,
) -> float | None:
    """Rank a broad candidate pool without the expensive AST sequence matcher."""
    source_nodes = int(source_features.get("node_count", 0))
    target_nodes = int(target_features.get("node_count", 0))
    if source_nodes < 6 or target_nodes < 6:
        return None

    # A method more than eight times larger/smaller cannot be a useful hard
    # negative for structural rename ranking. The deliberately broad range
    # keeps substantial refactors while removing pathological comparisons.
    node_ratio = min(source_nodes, target_nodes) / max(source_nodes, target_nodes)
    if node_ratio < 0.125:
        return None

    source_tokens = set(source_name.lower().split("_"))
    target_tokens = set(target_name.lower().split("_"))
    name_overlap = _set_overlap(source_tokens, target_tokens)
    signature = _signature_shape_similarity(
        source_features.get("signature_shape", {}),
        target_features.get("signature_shape", {}),
    )
    calls = _set_overlap(source_features.get("calls"), target_features.get("calls"))
    attributes = _set_overlap(
        source_features.get("attributes"), target_features.get("attributes")
    )
    return (
        node_ratio * 0.35
        + signature * 0.30
        + calls * 0.15
        + attributes * 0.10
        + name_overlap * 0.10
    )


def _bounded_hard_negatives(
    source_name: str,
    source_features: dict,
    candidates: Iterable[tuple[str, dict]],
    *,
    excluded_name: str,
    hard_negatives: int,
    diagnostics: dict[str, int] | None = None,
) -> list[tuple[float, str, dict[str, float]]]:
    """Return deterministic top-K hard negatives with bounded expensive work."""
    if hard_negatives <= 0:
        return []

    # Cheap metadata narrows large Odoo models before SequenceMatcher runs.
    # Keep a deliberately generous pool so the final ranking still sees a
    # diverse set of plausible hard negatives.
    shortlist_size = max(24, hard_negatives * 8)
    shortlist: list[tuple[float, str, dict]] = []
    for candidate_name, candidate_features in sorted(candidates):
        if candidate_name == excluded_name:
            continue
        if diagnostics is not None:
            diagnostics["candidate_methods_considered"] = (
                diagnostics.get("candidate_methods_considered", 0) + 1
            )
        cheap_score = _cheap_candidate_score(
            source_name,
            source_features,
            candidate_name,
            candidate_features,
        )
        if cheap_score is None:
            if diagnostics is not None:
                diagnostics["candidate_methods_filtered"] = (
                    diagnostics.get("candidate_methods_filtered", 0) + 1
                )
            continue
        entry = (cheap_score, candidate_name, candidate_features)
        if len(shortlist) < shortlist_size:
            heapq.heappush(shortlist, entry)
        elif entry[:2] > shortlist[0][:2]:
            heapq.heapreplace(shortlist, entry)

    if diagnostics is not None:
        diagnostics["candidate_methods_shortlisted"] = (
            diagnostics.get("candidate_methods_shortlisted", 0) + len(shortlist)
        )

    best: list[tuple[float, str, dict[str, float]]] = []
    for _, candidate_name, candidate_features in sorted(shortlist, reverse=True):
        features = _feature_pair(
            source_name,
            source_features,
            candidate_name,
            candidate_features,
        )
        if diagnostics is not None:
            diagnostics["similarity_comparisons"] = (
                diagnostics.get("similarity_comparisons", 0) + 1
            )
        hardness = (
            features["ast"] * 0.40
            + features["calls"] * 0.25
            + features["attrs"] * 0.15
            + features["signature"] * 0.10
            + features["name"] * 0.10
        )
        entry = (hardness, candidate_name, features)
        if len(best) < hard_negatives:
            heapq.heappush(best, entry)
        elif entry[:2] > best[0][:2]:
            heapq.heapreplace(best, entry)
    return sorted(best, reverse=True)


def _same_name_samples(source: OdooIndex, target: OdooIndex, step: str,
                       hard_negatives: int = 3, *,
                       diagnostics: dict[str, int] | None = None) -> list[MethodTrainingSample]:
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

            candidates = _bounded_hard_negatives(
                method_name,
                old_features,
                new.method_features.items(),
                excluded_name=method_name,
                hard_negatives=hard_negatives,
                diagnostics=diagnostics,
            )
            for _, candidate_name, features in candidates:
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
    diff: SourceDiff,
    *,
    hard_negatives: int = 3,
    diagnostics: dict[str, int] | None = None,
) -> list[MethodTrainingSample]:
    """Build trusted rename examples from unique exact semantic fingerprints.

    This does not depend on the learned ranker or the legacy weighted matcher:
    a removed method and an added method must have the same structural/call/
    attribute/signature/control fingerprint and the match must be one-to-one.
    """
    samples: list[MethodTrainingSample] = []
    source_models = source.models
    target_models = target.models

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
        old_model = source_models.get(change.model)
        new_model = target_models.get(change.model)
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

            negatives = _bounded_hard_negatives(
                old_name,
                old_features,
                (
                    (candidate_name, new_model.method_features[candidate_name])
                    for candidate_name in change.added_methods
                    if candidate_name in new_model.method_features
                ),
                excluded_name=new_name,
                hard_negatives=hard_negatives,
                diagnostics=diagnostics,
            )
            for _, candidate_name, features in negatives:
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

def _weak_rename_samples(source: OdooIndex, target: OdooIndex, step: str,
                         diff: SourceDiff) -> list[MethodTrainingSample]:
    """Use only existing ultra-conservative rename matches as weak supervision."""
    samples = []
    source_models = source.models
    target_models = target.models
    for match in high_confidence_method_renames(
        source,
        target,
        diff,
        threshold=0.94,
        minimum_margin=0.18,
    ):
        old = source_models.get(match.model)
        new = target_models.get(match.model)
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
    diff: SourceDiff,
    *,
    hard_negatives: int = 3,
    diagnostics: dict[str, int] | None = None,
) -> list[MethodTrainingSample]:
    if not pairs:
        return []
    samples: list[MethodTrainingSample] = []
    source_models = source.models
    target_models = target.models

    for old_name, new_name in sorted(pairs):
        matches = [
            change
            for change in diff.model_changes
            if old_name in change.removed_methods and new_name in change.added_methods
        ]
        if len(matches) != 1:
            continue
        change = matches[0]
        old_model = source_models.get(change.model)
        new_model = target_models.get(change.model)
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

        negatives = _bounded_hard_negatives(
            old_name,
            old_features,
            (
                (candidate_name, new_model.method_features[candidate_name])
                for candidate_name in change.added_methods
                if candidate_name in new_model.method_features
            ),
            excluded_name=new_name,
            hard_negatives=hard_negatives,
            diagnostics=diagnostics,
        )
        for _, candidate_name, features in negatives:
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
    progress: DatasetProgress | None = None,
) -> Dataset:
    samples: list[MethodTrainingSample] = []
    step_counts: dict[str, dict[str, int]] = {}
    pair_count = max(1, target - source)
    stage_count = pair_count * 5 + 1
    completed_stages = 0

    def report(message: str) -> None:
        if progress:
            progress(message, round(completed_stages / stage_count * 100))

    for version in range(source, target):
        started = perf_counter()
        old = indexes[version]
        new = indexes[version + 1]
        step = f"{version}_to_{version + 1}"
        display_step = f"Odoo {version} -> {version + 1}"
        diagnostics: dict[str, int] = {}

        report(f"Dataset {display_step}: comparing indexed APIs")
        diff = compare_indexes(old, new)
        completed_stages += 1

        report(f"Dataset {display_step}: stable API samples")
        stable = _same_name_samples(old, new, step, diagnostics=diagnostics)
        samples.extend(stable)
        completed_stages += 1

        report(f"Dataset {display_step}: Git-history rename samples")
        history = _history_rename_samples(
            old,
            new,
            step,
            set((history_pairs or {}).get(step, set())),
            diff,
            diagnostics=diagnostics,
        )
        samples.extend(history)
        completed_stages += 1

        report(f"Dataset {display_step}: exact semantic rename samples")
        exact = _exact_semantic_rename_samples(
            old, new, step, diff, diagnostics=diagnostics
        )
        samples.extend(exact)
        completed_stages += 1

        report(f"Dataset {display_step}: weak rename samples")
        weak = _weak_rename_samples(old, new, step, diff)
        samples.extend(weak)
        completed_stages += 1

        pair_samples = [*stable, *history, *exact, *weak]
        counts = {
            "common_api_positives": sum(item.origin == "stable_api" for item in stable),
            "hard_negatives": sum(item.label == 0 for item in pair_samples),
            "exact_rename_positives": sum(
                item.origin == "exact_semantic_rename" for item in exact
            ),
            "history_rename_positives": sum(
                item.origin == "git_history_rename" for item in history
            ),
            "weak_rename_positives": sum(item.origin == "weak_rename" for item in weak),
            "total_samples": len(pair_samples),
            **diagnostics,
        }
        step_counts[step] = counts
        logger.info(
            "Migration Brain dataset step=%s elapsed_seconds=%.3f "
            "common_api_positives=%d hard_negatives=%d exact_rename_positives=%d "
            "history_rename_positives=%d weak_rename_positives=%d total_samples=%d "
            "similarity_comparisons=%d candidates_considered=%d candidates_shortlisted=%d",
            step,
            perf_counter() - started,
            counts["common_api_positives"],
            counts["hard_negatives"],
            counts["exact_rename_positives"],
            counts["history_rename_positives"],
            counts["weak_rename_positives"],
            counts["total_samples"],
            counts.get("similarity_comparisons", 0),
            counts.get("candidate_methods_considered", 0),
            counts.get("candidate_methods_shortlisted", 0),
        )
        report(
            f"Dataset {display_step}: {counts['total_samples']} samples "
            f"({counts['common_api_positives']} stable, "
            f"{counts['hard_negatives']} hard negatives)"
        )

    report("Finalizing semantic dataset")
    completed_stages += 1
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
    if progress:
        progress("Semantic dataset ready", 100)
    return Dataset(train, validation, positives, negatives, step_counts=step_counts)
