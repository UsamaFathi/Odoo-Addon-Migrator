from odoo_migrator.analysis.compat import Finding, Severity
from odoo_migrator.sources.diff import SourceDiff
from odoo_migrator.sources.indexer import OdooIndex


def analyze(custom: OdooIndex, source: OdooIndex, target: OdooIndex, diff: SourceDiff):
    findings = []
    for module_name, module in custom.modules.items():
        for dependency in sorted(set(module.depends) & diff.modules_removed):
            if dependency in custom.modules:
                continue
            findings.append(Finding(
                Severity.BLOCKER,
                "dependency.module_removed",
                module_name,
                f"Dependency '{dependency}' exists in Odoo 17 but was removed from Odoo 18.",
                rule_id="dependency.module_removed.17_to_18",
                migration_step="17_to_18",
                object_name=dependency,
                source_state="present",
                target_state="removed",
                suggested_action="Remove the dependency only after selecting a verified replacement or redesign.",
            ))
    return findings
