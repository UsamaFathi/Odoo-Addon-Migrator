from pathlib import Path

from odoo_migrator.analysis.compat import Finding, Severity
from odoo_migrator.sources.indexer import OdooIndex, SourceIndexer


def _asset_bundles(index: OdooIndex) -> set[str]:
    bundles = set()
    for module in index.modules.values():
        assets = module.manifest.get("assets", {})
        if isinstance(assets, dict):
            bundles.update(str(name) for name in assets)
    return bundles


def analyze(custom: OdooIndex, source: OdooIndex, target: OdooIndex):
    findings = []
    removed_modules = source.js_modules - target.js_modules
    source_bundles = _asset_bundles(source)
    target_bundles = _asset_bundles(target)
    for module_name, module in custom.modules.items():
        for path in Path(module.path).rglob("*.js"):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except (OSError, UnicodeError):
                continue
            dependencies = SourceIndexer.javascript_dependencies(text)
            for dependency in sorted(dependencies & removed_modules):
                findings.append(Finding(
                    Severity.REVIEW_REQUIRED,
                    "frontend.legacy_dependency.removed",
                    module_name,
                    f"Legacy JavaScript dependency '{dependency}' was removed from the Odoo 18 web source.",
                    path.relative_to(Path(module.path)).as_posix(),
                    rule_id="frontend.legacy_dependency.removed.17_to_18",
                    migration_step="17_to_18",
                    object_name=dependency,
                    source_state="present",
                    target_state="removed",
                    suggested_action="Replace it with the Odoo 18 service/component API after review.",
                ))
        assets = module.manifest.get("assets", {})
        if isinstance(assets, dict):
            for bundle in sorted(set(assets) & source_bundles - target_bundles):
                findings.append(Finding(
                    Severity.REVIEW_REQUIRED,
                    "frontend.asset_bundle.removed",
                    module_name,
                    f"Asset bundle '{bundle}' exists in Odoo 17 but is absent from Odoo 18.",
                    "__manifest__.py",
                    rule_id="frontend.asset_bundle.removed.17_to_18",
                    migration_step="17_to_18",
                    object_name=str(bundle),
                    source_state="present",
                    target_state="removed",
                    suggested_action="Review the Odoo 18 asset bundle structure; no replacement is inferred.",
                ))
    return findings
