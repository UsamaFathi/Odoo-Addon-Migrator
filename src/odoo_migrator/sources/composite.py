from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from odoo_migrator.sources.indexer import ModelInfo, ModuleInfo, OdooIndex


def validate_addons_source(path: str | Path) -> Path:
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Enterprise source folder does not exist: {root}")
    try:
        has_manifest = any(item.is_file() and item.name == "__manifest__.py" for item in root.rglob("__manifest__.py"))
    except OSError as exc:
        raise ValueError(f"Unable to read Enterprise source folder: {root}") from exc
    if not has_manifest:
        raise ValueError(f"No Odoo addon manifests were found in Enterprise source: {root}")
    return root


def _merge_model(left: ModelInfo, right: ModelInfo) -> ModelInfo:
    result = deepcopy(left)
    result.methods.update(right.methods)
    result.fields.update(right.fields)
    result.inherits.update(right.inherits)
    result.delegated_inherits.update(right.delegated_inherits)
    result.signatures.update(right.signatures)
    result.method_locations.update(right.method_locations)
    result.field_locations.update(right.field_locations)
    result.method_features.update(right.method_features)
    if not result.source_path and right.source_path:
        result.source_path, result.line = right.source_path, right.line
    return result


def _merge_module(left: ModuleInfo, right: ModuleInfo) -> ModuleInfo:
    result = deepcopy(left)
    result.depends = list(dict.fromkeys([*left.depends, *right.depends]))
    for model_name, model in right.models.items():
        if model_name in result.models:
            result.models[model_name] = _merge_model(result.models[model_name], model)
        else:
            result.models[model_name] = deepcopy(model)
    result.xml_ids.update(right.xml_ids)
    result.manifest.update(right.manifest)
    for key, value in right.files.items():
        result.files[key] = result.files.get(key, 0) + value
    for key, values in right.controllers.items():
        result.controllers.setdefault(key, [])
        result.controllers[key] = list(dict.fromkeys([*result.controllers[key], *values]))
    result.assets.update(right.assets)
    result.views.update(deepcopy(right.views))
    result.model_xml_ids.update(right.model_xml_ids)
    result.defined_models.update(right.defined_models)
    result.js_modules.update(right.js_modules)
    result.js_dependencies.update(right.js_dependencies)
    result.js_module_locations.update(right.js_module_locations)
    return result


def compose_indexes(community: OdooIndex, enterprise: OdooIndex) -> OdooIndex:
    modules = deepcopy(community.modules)
    for module_name, module in enterprise.modules.items():
        if module_name in modules:
            modules[module_name] = _merge_module(modules[module_name], module)
        else:
            modules[module_name] = deepcopy(module)
    return OdooIndex(
        root=f"{community.root} | enterprise:{enterprise.root}",
        modules=modules,
        source_commit=community.source_commit,
        source_mode=f"{community.source_mode or 'community'}+enterprise_local",
        source_version=community.source_version,
    )
