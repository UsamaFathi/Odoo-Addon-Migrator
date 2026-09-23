from __future__ import annotations

"""Derived migration knowledge extracted during Brain training.

This module deliberately returns JSON-safe summaries only.  It must never
copy Odoo source text or source paths into a reusable ``.omb`` pack.
"""

from difflib import SequenceMatcher
import ast
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



def _flatten_views(index: OdooIndex, attribute: str) -> dict[str, Any]:
    return {
        key: value
        for module in index.modules.values()
        for key, value in getattr(module, attribute).items()
    }


def _unique_exact_identifier_mappings(
    old: dict[str, Any],
    new: dict[str, Any],
    *,
    signature,
    kind: str,
) -> list[dict[str, Any]]:
    removed = sorted(old.keys() - new.keys())
    added = sorted(new.keys() - old.keys())
    targets: dict[Any, list[str]] = {}
    for identifier in added:
        targets.setdefault(signature(new[identifier]), []).append(identifier)

    values: list[dict[str, Any]] = []
    target_use: dict[str, int] = {}
    for identifier in removed:
        candidates = targets.get(signature(old[identifier]), [])
        if len(candidates) != 1:
            continue
        replacement = candidates[0]
        values.append({
            "kind": kind,
            "from": identifier,
            "to": replacement,
            "confidence": 1.0,
            "evidence": "unique_exact_derived_signature",
        })
        target_use[replacement] = target_use.get(replacement, 0) + 1
    return [item for item in values if target_use[item["to"]] == 1]


def xml_id_renames(source: OdooIndex, target: OdooIndex) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []

    for attribute, kind in (("views", "view"), ("templates", "template")):
        old = _flatten_views(source, attribute)
        new = _flatten_views(target, attribute)
        values.extend(_unique_exact_identifier_mappings(
            old,
            new,
            signature=lambda item: (
                item.inherit_id or "",
                tuple(item.xpaths),
                item.architecture,
            ),
            kind=kind,
        ))

    old_model_ids = source.model_xml_ids
    new_model_ids = target.model_xml_ids
    values.extend(_unique_exact_identifier_mappings(
        old_model_ids,
        new_model_ids,
        signature=lambda model: model,
        kind="model_xml_id",
    ))
    return values


def js_module_renames(source: OdooIndex, target: OdooIndex) -> list[dict[str, Any]]:
    old_locations = {
        name: location
        for module in source.modules.values()
        for name, location in module.js_module_locations.items()
    }
    new_locations = {
        name: location
        for module in target.modules.values()
        for name, location in module.js_module_locations.items()
    }
    removed = sorted(set(old_locations) - set(new_locations))
    added = sorted(set(new_locations) - set(old_locations))
    by_location: dict[str, list[str]] = {}
    for name in added:
        by_location.setdefault(new_locations[name], []).append(name)

    values = []
    target_use: dict[str, int] = {}
    for name in removed:
        candidates = by_location.get(old_locations[name], [])
        if len(candidates) != 1:
            continue
        replacement = candidates[0]
        values.append({
            "from": name,
            "to": replacement,
            "confidence": 1.0,
            "evidence": "unique_same_static_source_location",
        })
        target_use[replacement] = target_use.get(replacement, 0) + 1
    return [item for item in values if target_use[item["to"]] == 1]


def _asset_bundle_signatures(index: OdooIndex) -> dict[str, tuple]:
    signatures: dict[str, tuple] = {}
    for module in index.modules.values():
        assets = module.manifest.get("assets", {})
        if not isinstance(assets, dict):
            continue
        for bundle, entries in assets.items():
            if isinstance(entries, (list, tuple)):
                signature = tuple(str(item) for item in entries)
            else:
                signature = (str(entries),)
            signatures[str(bundle)] = signature
    return signatures


def asset_bundle_renames(source: OdooIndex, target: OdooIndex) -> list[dict[str, Any]]:
    old = _asset_bundle_signatures(source)
    new = _asset_bundle_signatures(target)
    removed = sorted(set(old) - set(new))
    added = sorted(set(new) - set(old))
    targets: dict[tuple, list[str]] = {}
    for name in added:
        targets.setdefault(new[name], []).append(name)

    values = []
    target_use: dict[str, int] = {}
    for name in removed:
        candidates = targets.get(old[name], [])
        if len(candidates) != 1:
            continue
        replacement = candidates[0]
        values.append({
            "from": name,
            "to": replacement,
            "confidence": 1.0,
            "evidence": "unique_exact_asset_declaration",
        })
        target_use[replacement] = target_use.get(replacement, 0) + 1
    return [item for item in values if target_use[item["to"]] == 1]


def _parse_signature(signature: str | None) -> ast.arguments | None:
    if not signature:
        return None
    try:
        tree = ast.parse(f"def _brain_signature({signature}):\n    pass\n")
    except SyntaxError:
        return None
    node = tree.body[0]
    return node.args if isinstance(node, ast.FunctionDef) else None


def _argument_metadata_equal(left: ast.arguments, right: ast.arguments) -> bool:
    if (
        len(left.posonlyargs) != len(right.posonlyargs)
        or len(left.args) != len(right.args)
        or len(left.kwonlyargs) != len(right.kwonlyargs)
        or len(left.defaults) != len(right.defaults)
        or len(left.kw_defaults) != len(right.kw_defaults)
        or bool(left.vararg) != bool(right.vararg)
        or bool(left.kwarg) != bool(right.kwarg)
    ):
        return False

    def annotation(arg: ast.arg | None):
        return ast.dump(arg.annotation, include_attributes=False) if arg and arg.annotation else None

    left_args = [*left.posonlyargs, *left.args, *left.kwonlyargs]
    right_args = [*right.posonlyargs, *right.args, *right.kwonlyargs]
    if any(annotation(a) != annotation(b) for a, b in zip(left_args, right_args)):
        return False
    if annotation(left.vararg) != annotation(right.vararg):
        return False
    if annotation(left.kwarg) != annotation(right.kwarg):
        return False

    if [ast.dump(item, include_attributes=False) for item in left.defaults] != [
        ast.dump(item, include_attributes=False) for item in right.defaults
    ]:
        return False

    def dump_default(item):
        return ast.dump(item, include_attributes=False) if item is not None else None

    return [dump_default(item) for item in left.kw_defaults] == [
        dump_default(item) for item in right.kw_defaults
    ]


def signature_adapters(source: OdooIndex, target: OdooIndex, diff: SourceDiff) -> list[dict[str, Any]]:
    """Return only parameter-name-only signature changes with identical semantics."""
    values: list[dict[str, Any]] = []
    for change in diff.model_changes:
        if not change.signature_changes:
            continue
        old_model = source.models.get(change.model)
        new_model = target.models.get(change.model)
        if old_model is None or new_model is None:
            continue
        for method in sorted(change.signature_changes):
            old_signature = old_model.signatures.get(method)
            new_signature = new_model.signatures.get(method)
            old_args = _parse_signature(old_signature)
            new_args = _parse_signature(new_signature)
            if old_args is None or new_args is None:
                continue
            if not _argument_metadata_equal(old_args, new_args):
                continue

            old_params = [
                *old_args.posonlyargs,
                *old_args.args,
                *old_args.kwonlyargs,
            ]
            new_params = [
                *new_args.posonlyargs,
                *new_args.args,
                *new_args.kwonlyargs,
            ]
            if old_args.vararg and new_args.vararg:
                old_params.append(old_args.vararg)
                new_params.append(new_args.vararg)
            if old_args.kwarg and new_args.kwarg:
                old_params.append(old_args.kwarg)
                new_params.append(new_args.kwarg)

            renames = []
            for old_param, new_param in zip(old_params, new_params):
                if old_param.arg == new_param.arg:
                    continue
                if old_param.arg in {"self", "cls"} or new_param.arg in {"self", "cls"}:
                    renames = []
                    break
                renames.append({"from": old_param.arg, "to": new_param.arg})
            if not renames:
                continue

            old_names = {item["from"] for item in renames}
            new_names = {item["to"] for item in renames}
            if len(old_names) != len(renames) or len(new_names) != len(renames):
                continue
            values.append({
                "model": change.model,
                "method": method,
                "source_signature": old_signature,
                "target_signature": new_signature,
                "parameter_renames": renames,
                "confidence": 1.0,
                "evidence": "parameter_names_only_same_shape_defaults_annotations",
            })
    return values

def step_knowledge(source: OdooIndex, target: OdooIndex, diff: SourceDiff) -> dict[str, Any]:
    """Serialize a compact, source-free compatibility summary for one step."""
    model_changes = []
    for change in diff.model_changes:
        source_model = source.models.get(change.model)
        target_model = target.models.get(change.model)
        signature_details = []
        for method in sorted(change.signature_changes):
            signature_details.append({
                "method": method,
                "source": source_model.signatures.get(method) if source_model else None,
                "target": target_model.signatures.get(method) if target_model else None,
            })
        model_changes.append({
            "model": change.model,
            "removed_fields": sorted(change.removed_fields),
            "removed_methods": sorted(change.removed_methods),
            "signature_changes": sorted(change.signature_changes),
            "signature_details": signature_details,
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
