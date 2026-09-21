from __future__ import annotations

from odoo_migrator.analysis.compat import Finding, Severity
from odoo_migrator.sources.diff import SourceDiff
from odoo_migrator.sources.indexer import OdooIndex


def analyze(custom: OdooIndex, source: OdooIndex, target: OdooIndex, diff: SourceDiff) -> list[Finding]:
    findings = []
    for module_name, module in custom.modules.items():
        for model_name, model in module.models.items():
            if model_name in diff.models_removed:
                findings.append(Finding(Severity.BLOCKER, "python.model.removed", module_name,
                    f"Inherited standard model '{model_name}' was removed from Odoo 15.", module.path,
                    rule_id="python.model.removed.14_to_15", migration_step="14_to_15",
                    object_name=model_name, source_state="present", target_state="removed",
                    suggested_action="Choose a replacement model or update the inheritance explicitly."))
                continue
            change = next((item for item in diff.model_changes if item.model == model_name), None)
            if not change: continue
            for method in sorted(model.methods & change.removed_methods):
                findings.append(Finding(Severity.REVIEW_REQUIRED, "python.method.removed", module_name,
                    f"Override candidate '{model_name}.{method}()' is absent in Odoo 15.", module.path,
                    rule_id="python.method.removed.14_to_15", migration_step="14_to_15", object_name=f"{model_name}.{method}",
                    source_state="present", target_state="removed", suggested_action="Review the override and its business behavior."))
            for method in sorted(model.methods & change.signature_changes):
                findings.append(Finding(Severity.REVIEW_REQUIRED, "python.signature.changed", module_name,
                    f"Method signature for '{model_name}.{method}()' changed in Odoo 15.", module.path,
                    rule_id="python.signature.changed.14_to_15", migration_step="14_to_15", object_name=f"{model_name}.{method}",
                    source_state="signature changed", target_state="signature changed", suggested_action="Update callers and super() usage after review."))
            for field in sorted(model.fields & change.removed_fields):
                findings.append(Finding(Severity.REVIEW_REQUIRED, "python.field.removed", module_name,
                    f"Field '{model_name}.{field}' was removed from Odoo 15.", module.path,
                    rule_id="python.field.removed.14_to_15", migration_step="14_to_15", object_name=f"{model_name}.{field}",
                    source_state="present", target_state="removed", suggested_action="Review field references; no automatic replacement is inferred."))
    return findings
