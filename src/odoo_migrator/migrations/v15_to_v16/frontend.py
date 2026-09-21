from pathlib import Path
from odoo_migrator.analysis.compat import Finding, Severity
from odoo_migrator.sources.indexer import OdooIndex, SourceIndexer


REMOVED_LEGACY_MODULES = frozenset({"web.fileUploadMixin", "report.client_action", "web.ReportService", "web.PieChart"})


def analyze(custom: OdooIndex, source: OdooIndex, target: OdooIndex):
    findings = []
    for module_name, module in custom.modules.items():
        for path in Path(module.path).rglob("*.js"):
            dependencies = SourceIndexer.javascript_dependencies(path.read_text(encoding="utf-8", errors="ignore"))
            removed = dependencies & REMOVED_LEGACY_MODULES & source.js_modules - target.js_modules
            for dependency in sorted(removed):
                findings.append(Finding(Severity.REVIEW_REQUIRED, "frontend.legacy_dependency.removed", module_name,
                    f"Legacy JavaScript dependency '{dependency}' was removed from the Odoo 16 web source.",
                    path.relative_to(Path(module.path)).as_posix(), rule_id="frontend.legacy_dependency.removed.15_to_16",
                    migration_step="15_to_16", object_name=dependency, source_state="present", target_state="removed",
                    suggested_action="Replace it with the Odoo 16 service/component API after review."))
    return findings
