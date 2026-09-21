import csv
from pathlib import Path
from odoo_migrator.analysis.compat import Finding, Severity
from odoo_migrator.sources.indexer import OdooIndex


def analyze(custom: OdooIndex, target: OdooIndex, *, target_version: int = 15, migration_step: str = "14_to_15") -> list[Finding]:
    findings = []
    for name, module in custom.modules.items():
        for path in Path(module.path).rglob("ir.model.access.csv"):
            try:
                rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
                required = {"id", "model_id:id", "group_id:id", "perm_read", "perm_write", "perm_create", "perm_unlink"}
                if not rows or not required <= set(rows[0]): raise ValueError("missing access CSV columns")
                for row in rows:
                    model_ref = row.get("model_id:id", "")
                    model_name = target.resolve_model_external_id(model_ref) or custom.resolve_model_external_id(model_ref)
                    if model_ref and (not model_name or (model_name not in target.models and model_name not in custom.models)):
                        findings.append(Finding(Severity.BLOCKER, "security.model_missing", name,
                            f"Access rule references model '{model_ref}', which is absent from Odoo {target_version}.",
                            path.relative_to(Path(module.path)).as_posix(), rule_id=f"security.model_missing.{migration_step}",
                            migration_step=migration_step, object_name=model_ref, suggested_action="Review or remove the access rule."))
                    group_ref = row.get("group_id:id", "")
                    if "." not in group_ref and group_ref:
                        group_ref = f"{name}.{group_ref}"
                    if group_ref and group_ref not in target.xml_ids and group_ref not in custom.xml_ids and group_ref != "1":
                        findings.append(Finding(Severity.REVIEW_REQUIRED, "security.group_missing", name,
                            f"Access rule references group '{group_ref}', which is absent from Odoo {target_version}.",
                            path.relative_to(Path(module.path)).as_posix(), rule_id=f"security.group_missing.{migration_step}",
                            migration_step=migration_step, object_name=group_ref, suggested_action="Verify the group external ID."))
            except (OSError, UnicodeError, ValueError, csv.Error) as exc:
                findings.append(Finding(Severity.BLOCKER, "security.access_csv.invalid", name, str(exc),
                    path.relative_to(Path(module.path)).as_posix(), rule_id=f"security.access_csv.invalid.{migration_step}",
                    migration_step=migration_step, suggested_action="Correct the access CSV before migration."))
    return findings
