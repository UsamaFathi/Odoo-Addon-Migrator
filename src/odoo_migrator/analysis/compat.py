from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from odoo_migrator.sources.indexer import OdooIndex


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    REVIEW_REQUIRED = "review_required"
    BLOCKER = "blocker"


@dataclass(frozen=True, slots=True)
class Finding:
    severity: Severity
    code: str
    module: str
    message: str
    path: str | None = None
    line: int | None = None
    rule_id: str | None = None
    migration_step: str | None = None
    object_name: str | None = None
    source_state: str | None = None
    target_state: str | None = None
    suggested_action: str | None = None

    @property
    def concern(self) -> str:
        code = self.code
        for marker, name in (("method", "method"), ("signature", "signature"), ("field", "field"),
                             ("model", "model"), ("dependency", "dependency"), ("xpath", "xpath"),
                             ("inherit", "inherited_view"), ("xml", "xml_id")):
            if marker in code: return name
        return code

    @property
    def identity(self) -> tuple[str, str, str, str | None, str | None]:
        if self.object_name:
            return (self.module, self.concern, self.object_name, None, self.migration_step)
        return (self.module, self.concern, self.message, self.path, self.migration_step)

    @property
    def richness(self) -> int:
        return sum(value is not None for value in (self.path, self.line, self.rule_id, self.object_name, self.source_state, self.target_state, self.suggested_action))


def deduplicate_findings(findings: list[Finding] | tuple[Finding, ...]) -> tuple[Finding, ...]:
    selected: dict[tuple[str, str, str, str | None, str | None], Finding] = {}
    for finding in findings:
        key = finding.identity
        current = selected.get(key)
        if current is None or finding.richness > current.richness:
            selected[key] = finding
    return tuple(selected.values())


def compare_custom_to_target(custom: OdooIndex, source: OdooIndex, target: OdooIndex) -> list[Finding]:
    findings: list[Finding] = []
    source_models = source.models
    target_models = target.models

    for module_name, module in custom.modules.items():
        for dependency in module.depends:
            if dependency not in target.modules and dependency not in custom.modules:
                findings.append(Finding(
                    Severity.BLOCKER, "dependency.missing", module_name,
                    f"Dependency '{dependency}' is not present in the target source index.",
                    rule_id=None, object_name=dependency, source_state="present" if dependency in source.modules else "unknown",
                    target_state="missing", suggested_action="Review the dependency against the target source."
                ))

        for model_name, custom_model in module.models.items():
            if model_name not in target_models and model_name in source_models:
                findings.append(Finding(
                    Severity.BLOCKER, "model.removed", module_name,
                    f"Standard model '{model_name}' exists in source but not target.",
                    object_name=model_name, source_state="present", target_state="removed",
                    suggested_action="Select a verified replacement model."
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
                        Severity.REVIEW_REQUIRED, "method.missing_target", module_name,
                        f"Override candidate '{model_name}.{method}()' exists in source Odoo but not target. Review migration.",
                        object_name=f"{model_name}.{method}", source_state="present", target_state="removed",
                        suggested_action="Review the target API and business behavior."
                    ))

    return findings
