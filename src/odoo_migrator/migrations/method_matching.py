from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from math import sqrt
import re

from odoo_migrator.sources.diff import SourceDiff
from odoo_migrator.sources.indexer import OdooIndex


@dataclass(frozen=True, slots=True)
class MethodRenameMatch:
    model: str
    source_method: str
    target_method: str
    score: float
    margin: float
    evidence: tuple[str, ...]


def _jaccard(left, right) -> float:
    a, b = set(left or ()), set(right or ())
    if not a and not b:
        return 0.5
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _cosine_tokens(left, right) -> float:
    def counts(values):
        result = {}
        for value in values or ():
            result[value] = result.get(value, 0) + 1
        return result
    a, b = counts(left), counts(right)
    if not a or not b:
        return 0.0
    dot = sum(value * b.get(key, 0) for key, value in a.items())
    norm_a = sqrt(sum(value * value for value in a.values()))
    norm_b = sqrt(sum(value * value for value in b.values()))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def _name_tokens(name: str) -> tuple[str, ...]:
    return tuple(token for token in re.split(r"[_\W]+", name.lower()) if token)


def _shape_similarity(left: dict, right: dict) -> float:
    keys = ("positional", "kwonly", "defaults", "kw_defaults", "vararg", "kwarg")
    return sum(left.get(key) == right.get(key) for key in keys) / len(keys)


def method_similarity_components(source_method: str, source_features: dict,
                                 target_method: str, target_features: dict) -> dict[str, float]:
    structure = SequenceMatcher(
        None,
        source_features.get("structure", ()),
        target_features.get("structure", ()),
        autojunk=False,
    ).ratio()
    calls = _jaccard(source_features.get("calls"), target_features.get("calls"))
    attributes = _jaccard(source_features.get("attributes"), target_features.get("attributes"))
    strings = _cosine_tokens(source_features.get("strings"), target_features.get("strings"))
    decorators = _jaccard(source_features.get("decorators"), target_features.get("decorators"))
    signature = _shape_similarity(
        source_features.get("signature_shape", {}),
        target_features.get("signature_shape", {}),
    )
    name = SequenceMatcher(None, _name_tokens(source_method), _name_tokens(target_method), autojunk=False).ratio()
    control = 1.0 - min(
        1.0,
        (
            abs(source_features.get("returns", 0) - target_features.get("returns", 0))
            + abs(source_features.get("raises", 0) - target_features.get("raises", 0))
            + abs(source_features.get("branches", 0) - target_features.get("branches", 0))
            + abs(source_features.get("loops", 0) - target_features.get("loops", 0))
        ) / 6.0,
    )

    return {
        "ast": structure,
        "calls": calls,
        "attrs": attributes,
        "signature": signature,
        "control": control,
        "decorators": decorators,
        "strings": strings,
        "name": name,
    }


def method_similarity(source_method: str, source_features: dict,
                      target_method: str, target_features: dict) -> tuple[float, tuple[str, ...]]:
    components = method_similarity_components(
        source_method, source_features, target_method, target_features
    )
    score = (
        components["ast"] * 0.30
        + components["calls"] * 0.22
        + components["attrs"] * 0.13
        + components["signature"] * 0.12
        + components["control"] * 0.08
        + components["decorators"] * 0.05
        + components["strings"] * 0.05
        + components["name"] * 0.05
    )
    evidence = tuple(f"{key}={value:.2f}" for key, value in components.items())
    return score, evidence


def high_confidence_method_renames(
    source: OdooIndex,
    target: OdooIndex,
    diff: SourceDiff,
    *,
    threshold: float = 0.88,
    minimum_margin: float = 0.12,
) -> tuple[MethodRenameMatch, ...]:
    matches: list[MethodRenameMatch] = []
    changes = {item.model: item for item in diff.model_changes}
    for model_name, change in changes.items():
        if not change.removed_methods or not change.added_methods:
            continue
        source_model = source.models.get(model_name)
        target_model = target.models.get(model_name)
        if source_model is None or target_model is None:
            continue
        for old_name in sorted(change.removed_methods):
            old_features = source_model.method_features.get(old_name)
            if not old_features or old_features.get("node_count", 0) < 8:
                continue
            ranked = []
            for new_name in sorted(change.added_methods):
                new_features = target_model.method_features.get(new_name)
                if not new_features or new_features.get("node_count", 0) < 8:
                    continue
                score, evidence = method_similarity(old_name, old_features, new_name, new_features)
                ranked.append((score, new_name, evidence))
            if not ranked:
                continue
            ranked.sort(reverse=True)
            best_score, best_name, evidence = ranked[0]
            second_score = ranked[1][0] if len(ranked) > 1 else 0.0
            margin = best_score - second_score
            if best_score >= threshold and margin >= minimum_margin:
                matches.append(MethodRenameMatch(
                    model_name,
                    old_name,
                    best_name,
                    round(best_score, 4),
                    round(margin, 4),
                    evidence,
                ))
    target_use: dict[tuple[str, str], int] = {}
    for match in matches:
        key = (match.model, match.target_method)
        target_use[key] = target_use.get(key, 0) + 1
    return tuple(
        match
        for match in matches
        if target_use[(match.model, match.target_method)] == 1
    )
