from pathlib import Path
from odoo_migrator.analysis.compat import Finding, Severity
from odoo_migrator.sources.indexer import OdooIndex


def analyze(custom: OdooIndex, source: OdooIndex | None = None, target: OdooIndex | None = None) -> list[Finding]:
    findings = []
    for name, module in custom.modules.items():
        for path in Path(module.path).rglob("*.js"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            # Evidence-backed narrow rule: imports of legacy web.core/web.ajax
            # require review because those APIs changed during the 14/15 web
            # client transition. A generic odoo.define alone is not enough.
            if "web.core" in text or "web.ajax" in text:
                findings.append(Finding(Severity.REVIEW_REQUIRED, "frontend.legacy.module", name,
                    "Legacy JavaScript module pattern requires review for Odoo 15 frontend compatibility.",
                    path.relative_to(Path(module.path)).as_posix(), rule_id="frontend.legacy.module.14_to_15",
                    migration_step="14_to_15", suggested_action="Review module imports and asset registration."))
    return findings
