from odoo_migrator.analysis.compat import Finding, Severity
from odoo_migrator.sources.diff import SourceDiff
from odoo_migrator.sources.indexer import OdooIndex


def analyze(custom: OdooIndex, source: OdooIndex, target: OdooIndex, diff: SourceDiff, *, target_version: int = 16, migration_step: str = "15_to_16") -> list[Finding]:
    findings = []
    changes = {item.model: item for item in diff.model_changes}
    for module_name, module in custom.modules.items():
        for model_name, model in module.models.items():
            if model_name in diff.models_removed:
                path, line = model.source_path or module.path, model.line
                findings.append(Finding(Severity.BLOCKER, "python.model.removed", module_name,
                    f"Inherited standard model '{model_name}' was removed from Odoo {target_version}.", path, line,
                    rule_id=f"python.model.removed.{migration_step}", migration_step=migration_step, object_name=model_name,
                    source_state="present", target_state="removed", suggested_action="Select a verified replacement model."))
                continue
            change = changes.get(model_name)
            if not change: continue
            for concern, values, suffix, label in (
                ("method", model.methods & change.removed_methods, "removed", "Override candidate"),
                ("signature", model.methods & change.signature_changes, "changed", "Method signature"),
                ("field", model.fields & change.removed_fields, "removed", "Field"),
            ):
                for name in sorted(values):
                    obj = f"{model_name}.{name}"
                    location = model.field_locations.get(name) if concern == "field" else model.method_locations.get(name)
                    path, line = location if location else (model.source_path or module.path, model.line)
                    findings.append(Finding(Severity.REVIEW_REQUIRED, f"python.{concern}.{suffix}", module_name,
                        f"{label} '{obj}' changed in Odoo {target_version} and requires review.", path, line,
                        rule_id=f"python.{concern}.{suffix}.{migration_step}", migration_step=migration_step, object_name=obj,
                        source_state="present", target_state=suffix, suggested_action="Review target API and business behavior."))
    return findings
