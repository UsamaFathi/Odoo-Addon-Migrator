from __future__ import annotations

"""Derived migration knowledge extracted during Brain training.

This module deliberately returns JSON-safe summaries only.  It must never
copy Odoo source text or source paths into a reusable ``.omb`` pack.
"""

from difflib import SequenceMatcher
from typing import Any

from odoo_migrator.sources.diff import SourceDiff
from odoo_migrator.sources.indexer import OdooIndex


def _field_similarity(left: dict, right: dict) -> float:
    if not left or not right:
        return 0.0
    left_type, right_type = left.get("type"), right.get("type")
    type_score = 1.0 if left_type == right_type else 0.0
    keys = ("comodel_name", "relation", "compute", "inverse", "store", "readonly")
    comparable = [key for key in keys if key in left or key in right]
    metadata_score = (
        sum(left.get(key) == right.get(key) for key in comparable) / len(comparable)
        if comparable else 0.5
    )
    return type_score * 0.65 + metadata_score * 0.35


def field_renames(source: OdooIndex, target: OdooIndex, diff: SourceDiff) -> list[dict[str, Any]]:
    """Return only unique, strongly matching field replacements."""
    results: list[dict[str, Any]] = []
    for change in diff.model_changes:
        if not change.removed_fields or not change.added_fields:
            continue
        old_model = source.models.get(change.model)
        new_model = target.models.get(change.model)
        if old_model is None or new_model is None:
            continue
        for old_name in sorted(change.removed_fields):
            old_features = old_model.field_features.get(old_name, {})
            ranked = []
            for new_name in sorted(change.added_fields):
                new_features = new_model.field_features.get(new_name, {})
                score = _field_similarity(old_features, new_features)
                name_score = SequenceMatcher(None, old_name, new_name, autojunk=False).ratio()
                combined = score * 0.8 + name_score * 0.2
                ranked.append((combined, new_name, score, name_score))
            ranked.sort(reverse=True)
            if not ranked:
                continue
            best = ranked[0]
            second = ranked[1][0] if len(ranked) > 1 else 0.0
            margin = best[0] - second
            if best[0] < 0.92 or margin < 0.12:
                continue
            results.append({
                "model": change.model,
                "from": old_name,
                "to": best[1],
                "confidence": round(best[0], 6),
                "margin": round(margin, 6),
                "evidence": "unique_field_type_and_metadata_match",
            })
    target_use: dict[tuple[str, str], int] = {}
    for item in results:
        key = (item["model"], item["to"])
        target_use[key] = target_use.get(key, 0) + 1
    return [item for item in results if target_use[(item["model"], item["to"])] == 1]


def _asset_bundles(index: OdooIndex) -> set[str]:
    bundles: set[str] = set()
    for module in index.modules.values():
        assets = module.manifest.get("assets", {})
        if isinstance(assets, dict):
            bundles.update(str(key) for key in assets)
    return bundles


def _architecture_changes(source: OdooIndex, target: OdooIndex, attribute: str) -> list[str]:
    old = {
        key: value
        for module in source.modules.values()
        for key, value in getattr(module, attribute).items()
    }
    new = {
        key: value
        for module in target.modules.values()
        for key, value in getattr(module, attribute).items()
    }
    return sorted(
        key for key in old.keys() & new.keys()
        if old[key].architecture != new[key].architecture
    )


def _method_moves(source: OdooIndex, target: OdooIndex) -> list[dict[str, str]]:
    old_owners: dict[str, set[str]] = {}
    new_owners: dict[str, set[str]] = {}
    for model_name, model in source.models.items():
        for method in model.methods:
            old_owners.setdefault(method, set()).add(model_name)
    for model_name, model in target.models.items():
        for method in model.methods:
            new_owners.setdefault(method, set()).add(model_name)
    values = []
    for method, owners in old_owners.items():
        for old_model in sorted(owners):
            moved_to = sorted(new_owners.get(method, set()) - {old_model})
            if len(moved_to) == 1:
                values.append({"method": method, "from_model": old_model, "to_model": moved_to[0]})
    return values


def _model_ownership_changes(source: OdooIndex, target: OdooIndex) -> list[dict[str, Any]]:
    old = {}
    new = {}
    for module in source.modules.values():
        for model in module.models:
            old.setdefault(model, set()).add(module.name)
    for module in target.modules.values():
        for model in module.models:
            new.setdefault(model, set()).add(module.name)
    return [
        {"model": model, "source_modules": sorted(old_modules), "target_modules": sorted(new[model])}
        for model, old_modules in sorted(old.items())
        if model in new and old_modules != new[model]
    ]


def step_knowledge(source: OdooIndex, target: OdooIndex, diff: SourceDiff) -> dict[str, Any]:
    """Serialize a compact, source-free compatibility summary for one step."""
    model_changes = []
    for change in diff.model_changes:
        model_changes.append({
            "model": change.model,
            "removed_fields": sorted(change.removed_fields),
            "removed_methods": sorted(change.removed_methods),
            "signature_changes": sorted(change.signature_changes),
        })
    return {
        "removed_modules": sorted(diff.modules_removed),
        "added_modules": sorted(diff.modules_added),
        "removed_models": sorted(diff.models_removed),
        "added_models": sorted(diff.models_added),
        "removed_xml_ids": sorted(diff.xml_ids_removed),
        "added_xml_ids": sorted(diff.xml_ids_added),
        "removed_js_modules": sorted(source.js_modules - target.js_modules),
        "added_js_modules": sorted(target.js_modules - source.js_modules),
        "removed_asset_bundles": sorted(_asset_bundles(source) - _asset_bundles(target)),
        "added_asset_bundles": sorted(_asset_bundles(target) - _asset_bundles(source)),
        "changed_view_architectures": _architecture_changes(source, target, "views"),
        "changed_template_architectures": _architecture_changes(source, target, "templates"),
        "method_moves": _method_moves(source, target),
        "model_ownership_changes": _model_ownership_changes(source, target),
        "removed_model_xml_ids": sorted(
            xml_id for xml_id, model in source.model_xml_ids.items()
            if xml_id not in target.model_xml_ids or model not in target.models
        ),
        "removed_group_xml_ids": sorted(source.group_xml_ids - target.group_xml_ids),
        "model_changes": model_changes,
        "dependency_changes": {
            name: {"removed": sorted(old - new), "added": sorted(new - old)}
            for name, (old, new) in sorted(diff.dependency_changes.items())
        },
    }
