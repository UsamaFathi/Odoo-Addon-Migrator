from __future__ import annotations
from pathlib import Path
import xml.etree.ElementTree as ET
from odoo_migrator.analysis.compat import Finding, Severity
from odoo_migrator.sources.indexer import OdooIndex


def analyze(custom: OdooIndex, source: OdooIndex, target: OdooIndex) -> list[Finding]:
    findings = []
    for module_name, module in custom.modules.items():
        for path in Path(module.path).rglob("*.xml"):
            try: root = ET.parse(path).getroot()
            except ET.ParseError: continue
            for record in root.iter("record"):
                inherit = next((field.attrib.get("ref") for field in record.findall("field") if field.attrib.get("name") == "inherit_id"), None)
                if inherit and "." not in inherit: inherit = f"{module_name}.{inherit}"
                if inherit and inherit not in target.xml_ids:
                    findings.append(Finding(Severity.REVIEW_REQUIRED, "xml.inherit.target_missing", module_name,
                        f"Inherited view target '{inherit}' is not present in Odoo 15.", path.relative_to(Path(module.path)).as_posix(),
                        rule_id="xml.inherit.target_missing.14_to_15", migration_step="14_to_15", object_name=inherit,
                        source_state="present" if inherit in source.xml_ids else "unknown", target_state="missing",
                        suggested_action="Review the target view and update the inheritance explicitly."))
                if inherit and inherit in target.xml_ids:
                    target_view = next((view for info in target.modules.values() for key, view in info.views.items() if key == inherit), None)
                    for xpath in [node.attrib.get("expr") for node in record.iter("xpath") if node.attrib.get("expr")]:
                        if target_view and not _xpath_exists(target_view.architecture, xpath):
                            findings.append(Finding(Severity.REVIEW_REQUIRED, "xml.xpath.target_missing", module_name,
                                f"XPath target '{xpath}' is not present in inherited view '{inherit}' in Odoo 15.",
                                str(path), rule_id="xml.xpath.target_missing.14_to_15", migration_step="14_to_15", object_name=inherit,
                                source_state="present" if _xpath_exists(target_view.architecture, xpath) else "changed",
                                target_state="missing", suggested_action="Review the target view; no replacement XPath is guessed."))
    return findings


def _xpath_exists(architecture: str, expression: str) -> bool:
    """Handle the common Odoo //tag and //tag[@attr='value'] XPath subset."""
    try:
        root = ET.fromstring(architecture)
    except ET.ParseError:
        return False
    if expression.startswith("//"):
        expression = "." + expression
    try:
        return bool(root.findall(expression))
    except SyntaxError:
        return False
