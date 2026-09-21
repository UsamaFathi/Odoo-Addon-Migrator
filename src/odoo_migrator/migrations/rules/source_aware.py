from __future__ import annotations

from pathlib import Path

from odoo_migrator.analysis.compat import Finding, Severity
from odoo_migrator.sources.diff import SourceDiff
from odoo_migrator.sources.indexer import OdooIndex, SourceIndexer


def analyze_removed_dependencies(
    custom: OdooIndex,
    diff: SourceDiff,
    *,
    source_version: int,
    target_version: int,
    migration_step: str,
) -> list[Finding]:
    """Report only official modules removed across this adjacent transition."""
    findings: list[Finding] = []
    for module_name, module in custom.modules.items():
        for dependency in sorted(set(module.depends) & diff.modules_removed):
            if dependency in custom.modules:
                continue
            findings.append(Finding(
                Severity.BLOCKER,
                "dependency.module_removed",
                module_name,
                f"Dependency '{dependency}' exists in Odoo {source_version} but was removed from Odoo {target_version}.",
                rule_id=f"dependency.module_removed.{migration_step}",
                migration_step=migration_step,
                object_name=dependency,
                source_state="present",
                target_state="removed",
                suggested_action="Remove the dependency only after selecting a verified replacement or redesign.",
            ))
    return findings


def _asset_bundles(index: OdooIndex) -> set[str]:
    bundles: set[str] = set()
    for module in index.modules.values():
        assets = module.manifest.get("assets", {})
        if isinstance(assets, dict):
            bundles.update(str(name) for name in assets)
    return bundles


def analyze_frontend(
    custom: OdooIndex,
    source: OdooIndex,
    target: OdooIndex,
    *,
    source_version: int,
    target_version: int,
    migration_step: str,
) -> list[Finding]:
    """Compare actual imported JS modules and declared asset bundle keys."""
    findings: list[Finding] = []
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
                    f"JavaScript dependency '{dependency}' was removed from the Odoo {target_version} web source.",
                    path.relative_to(Path(module.path)).as_posix(),
                    rule_id=f"frontend.legacy_dependency.removed.{migration_step}",
                    migration_step=migration_step,
                    object_name=dependency,
                    source_state=f"present in Odoo {source_version}",
                    target_state="removed",
                    suggested_action=f"Replace it with the Odoo {target_version} service/component API after review.",
                ))
        assets = module.manifest.get("assets", {})
        if isinstance(assets, dict):
            for bundle in sorted(set(assets) & source_bundles - target_bundles):
                findings.append(Finding(
                    Severity.REVIEW_REQUIRED,
                    "frontend.asset_bundle.removed",
                    module_name,
                    f"Asset bundle '{bundle}' exists in Odoo {source_version} but is absent from Odoo {target_version}.",
                    "__manifest__.py",
                    rule_id=f"frontend.asset_bundle.removed.{migration_step}",
                    migration_step=migration_step,
                    object_name=str(bundle),
                    source_state="present",
                    target_state="removed",
                    suggested_action=f"Review the Odoo {target_version} asset bundle structure; no replacement is inferred.",
                ))
    return findings
