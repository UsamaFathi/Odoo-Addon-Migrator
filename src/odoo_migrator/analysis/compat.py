from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from odoo_migrator.sources.indexer import OdooIndex


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


@dataclass(frozen=True, slots=True)
class Finding:
    severity: Severity
    code: str
    module: str
    message: str


def compare_custom_to_target(custom: OdooIndex, source: OdooIndex, target: OdooIndex) -> list[Finding]:
    findings: list[Finding] = []
    source_models = source.models
    target_models = target.models

    for module_name, module in custom.modules.items():
        for dependency in module.depends:
            if dependency not in target.modules and dependency not in custom.modules:
                findings.append(Finding(
                    Severity.BLOCKER, "dependency.missing", module_name,
                    f"Dependency '{dependency}' is not present in the target source index."
                ))

        for model_name, custom_model in module.models.items():
            if model_name not in target_models and model_name in source_models:
                findings.append(Finding(
                    Severity.BLOCKER, "model.removed", module_name,
                    f"Standard model '{model_name}' exists in source but not target."
                ))
                continue
            if model_name not in source_models:
                continue

            old = source_models[model_name]
            new = target_models.get(model_name)
            if not new:
                continue
            for method in sorted(custom_model.methods & old.methods):
                if method not in new.methods:
                    findings.append(Finding(
                        Severity.WARNING, "method.missing_target", module_name,
                        f"Override candidate '{model_name}.{method}()' exists in source Odoo but not target. Review migration."
                    ))

    return findings
