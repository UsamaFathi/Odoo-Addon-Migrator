from __future__ import annotations

from dataclasses import dataclass, field
from odoo_migrator.sources.indexer import OdooIndex


@dataclass(frozen=True, slots=True)
class ModelDiff:
    model: str
    added_fields: frozenset[str] = frozenset()
    removed_fields: frozenset[str] = frozenset()
    added_methods: frozenset[str] = frozenset()
    removed_methods: frozenset[str] = frozenset()
    signature_changes: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class SourceDiff:
    source_commit: str | None
    target_commit: str | None
    modules_added: frozenset[str] = frozenset()
    modules_removed: frozenset[str] = frozenset()
    models_added: frozenset[str] = frozenset()
    models_removed: frozenset[str] = frozenset()
    model_changes: tuple[ModelDiff, ...] = ()
    xml_ids_added: frozenset[str] = frozenset()
    xml_ids_removed: frozenset[str] = frozenset()
    dependency_changes: dict[str, tuple[frozenset[str], frozenset[str]]] = field(default_factory=dict)


def compare_indexes(source: OdooIndex, target: OdooIndex) -> SourceDiff:
    source_models, target_models = source.models, target.models
    model_changes = []
    for name in sorted(source_models.keys() & target_models.keys()):
        old, new = source_models[name], target_models[name]
        changed = ModelDiff(name, frozenset(new.fields - old.fields), frozenset(old.fields - new.fields),
                            frozenset(new.methods - old.methods), frozenset(old.methods - new.methods),
                            frozenset(method for method in old.signatures.keys() & new.signatures.keys()
                                      if old.signatures[method] != new.signatures[method]))
        if any((changed.added_fields, changed.removed_fields, changed.added_methods, changed.removed_methods, changed.signature_changes)):
            model_changes.append(changed)
    dependencies = {}
    for name in source.modules.keys() & target.modules.keys():
        old = frozenset(source.modules[name].depends); new = frozenset(target.modules[name].depends)
        if old != new: dependencies[name] = (old, new)
    return SourceDiff(source.source_commit, target.source_commit,
        frozenset(target.modules) - frozenset(source.modules), frozenset(source.modules) - frozenset(target.modules),
        frozenset(target_models) - frozenset(source_models), frozenset(source_models) - frozenset(target_models),
        tuple(model_changes), target.xml_ids - source.xml_ids, source.xml_ids - target.xml_ids, dependencies)
