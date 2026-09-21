from pathlib import Path

from odoo_migrator.analysis.compat import Finding, Severity
from odoo_migrator.sources.indexer import OdooIndex, SourceIndexer


# These aliases are declared by files in Odoo 16's legacy web tree and have no
# corresponding declaration in the Odoo 17 web tree.  The rule only reports a
# custom addon when it actually imports one of them.
REMOVED_LEGACY_MODULES = frozenset({
    "web.AbstractAction",
    "web.AbstractModel",
    "web.FormController",
    "web.ListController",
})
PATCH_MODULE = "@web/core/utils/patch"


def _has_legacy_patch_signature(text: str) -> bool:
    """Find patch(obj, name, extension) calls without matching strings/comments."""
    code = SourceIndexer._strip_js_comments(text)
    index = 0
    while index < len(code):
        if code[index] in {"'", '"', "`"}:
            quote = code[index]; index += 1
            while index < len(code):
                if code[index] == "\\": index += 2; continue
                if code[index] == quote: index += 1; break
                index += 1
            continue
        if code.startswith("patch", index) and (index == 0 or not (code[index - 1].isalnum() or code[index - 1] in "_$")):
            end = index + 5
            if end == len(code) or not (code[end].isalnum() or code[end] in "_$"):
                while end < len(code) and code[end].isspace(): end += 1
                if end < len(code) and code[end] == "(":
                    depth = 0; commas = 0; quote = None; cursor = end
                    while cursor < len(code):
                        char = code[cursor]
                        if quote:
                            if char == "\\": cursor += 2; continue
                            if char == quote: quote = None
                        elif char in {"'", '"', "`"}:
                            quote = char
                        elif char in "([{": depth += 1
                        elif char in ")]}":
                            depth -= 1
                            if depth == 0: break
                        elif char == "," and depth == 1:
                            commas += 1
                        cursor += 1
                    if commas >= 2:
                        return True
        index += 1
    return False


def analyze(custom: OdooIndex, source: OdooIndex, target: OdooIndex):
    findings = []
    for module_name, module in custom.modules.items():
        for path in Path(module.path).rglob("*.js"):
            dependencies = SourceIndexer.javascript_dependencies(path.read_text(encoding="utf-8", errors="ignore"))
            removed = dependencies & REMOVED_LEGACY_MODULES & source.js_modules - target.js_modules
            for dependency in sorted(removed):
                findings.append(Finding(
                    Severity.REVIEW_REQUIRED,
                    "frontend.legacy_dependency.removed",
                    module_name,
                    f"Legacy JavaScript dependency '{dependency}' was removed from the Odoo 17 web source.",
                    path.relative_to(Path(module.path)).as_posix(),
                    rule_id="frontend.legacy_dependency.removed.16_to_17",
                    migration_step="16_to_17",
                    object_name=dependency,
                    source_state="present",
                    target_state="removed",
                    suggested_action="Replace it with the Odoo 17 service/component API after review.",
                ))
            if (PATCH_MODULE in dependencies and PATCH_MODULE in source.js_modules
                    and PATCH_MODULE in target.js_modules
                    and _has_legacy_patch_signature(path.read_text(encoding="utf-8", errors="ignore"))):
                findings.append(Finding(
                    Severity.REVIEW_REQUIRED,
                    "frontend.patch_signature.changed",
                    module_name,
                    "The Odoo 16 patch API accepts a patch name as a second argument; Odoo 17 uses patch(target, extension).",
                    path.relative_to(Path(module.path)).as_posix(),
                    rule_id="frontend.patch_signature.changed.16_to_17",
                    migration_step="16_to_17",
                    object_name=PATCH_MODULE,
                    source_state="patch(object, name, extension)",
                    target_state="patch(object, extension)",
                    suggested_action="Review the patch call and remove the legacy name argument while preserving behavior.",
                ))
    return findings
