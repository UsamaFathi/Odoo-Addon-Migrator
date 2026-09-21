import csv
from pathlib import Path
from odoo_migrator.analysis.compat import Finding, Severity
from odoo_migrator.sources.indexer import OdooIndex


def analyze(custom: OdooIndex, target: OdooIndex) -> list[Finding]:
    findings = []
    for name, module in custom.modules.items():
        for path in Path(module.path).rglob("ir.model.access.csv"):
            try:
                rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
                required = {"id", "model_id:id", "group_id:id", "perm_read", "perm_write", "perm_create", "perm_unlink"}
                if not rows or not required <= set(rows[0]): raise ValueError("missing access CSV columns")
                for row in rows:
                    model_ref = row.get("model_id:id", "")
                    if "." not in model_ref and model_ref:
                        model_ref = f"{name}.{model_ref}"
                    model_name = target.model_xml_ids.get(model_ref) or custom.model_xml_ids.get(model_ref)
                    if not model_name and model_ref.startswith(f"{name}.model_"):
                        candidate = model_ref.rsplit(".model_", 1)[1].replace("_", ".")
                        if candidate in custom.models: model_name = candidate
                    if model_name and model_name not in target.models and model_name not in custom.models:
                        findings.append(Finding(Severity.BLOCKER, "security.model_missing", name,
                            f"Access rule references model '{model_ref}', which is absent from the target source.",
                            path.relative_to(Path(module.path)).as_posix(), rule_id="security.model_missing.14_to_15",
                            migration_step="14_to_15", object_name=model_ref, suggested_action="Review or remove the access rule."))
                    group_ref = row.get("group_id:id", "")
                    if "." not in group_ref and group_ref:
                        group_ref = f"{name}.{group_ref}"
                    if group_ref and group_ref not in target.xml_ids and group_ref not in custom.xml_ids and group_ref != "1":
                        findings.append(Finding(Severity.REVIEW_REQUIRED, "security.group_missing", name,
                            f"Access rule references group '{group_ref}', which is absent from the target index.",
                            path.relative_to(Path(module.path)).as_posix(), rule_id="security.group_missing.14_to_15",
                            migration_step="14_to_15", object_name=group_ref, suggested_action="Verify the group external ID."))
            except (OSError, UnicodeError, ValueError, csv.Error) as exc:
                findings.append(Finding(Severity.BLOCKER, "security.access_csv.invalid", name, str(exc),
                    path.relative_to(Path(module.path)).as_posix(), rule_id="security.access_csv.invalid.14_to_15",
                    migration_step="14_to_15", suggested_action="Correct the access CSV before migration."))
    return findings
