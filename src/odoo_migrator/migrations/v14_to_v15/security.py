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
            except (OSError, UnicodeError, ValueError, csv.Error) as exc:
                findings.append(Finding(Severity.BLOCKER, "security.access_csv.invalid", name, str(exc),
                    path.relative_to(Path(module.path)).as_posix(), rule_id="security.access_csv.invalid.14_to_15",
                    migration_step="14_to_15", suggested_action="Correct the access CSV before migration."))
    return findings
