from pathlib import Path
import xml.etree.ElementTree as ET
from odoo_migrator.analysis.compat import Finding, Severity
from odoo_migrator.sources.indexer import OdooIndex
from odoo_migrator.migrations.v14_to_v15.xml import XPathState, _xpath_state


def analyze(custom: OdooIndex, source: OdooIndex, target: OdooIndex) -> list[Finding]:
    findings = []
    source_views = {key: view for module in source.modules.values() for key, view in module.views.items()}
    target_views = {key: view for module in target.modules.values() for key, view in module.views.items()}
    for module_name, module in custom.modules.items():
        for path in Path(module.path).rglob("*.xml"):
            try: root = ET.parse(path).getroot()
            except ET.ParseError: continue
            for record in root.iter("record"):
                inherit = next((field.attrib.get("ref") for field in record.findall("field") if field.attrib.get("name") == "inherit_id"), None)
                if not inherit: continue
                if "." not in inherit: inherit = f"{module_name}.{inherit}"
                if inherit not in target.xml_ids:
                    findings.append(Finding(Severity.REVIEW_REQUIRED, "xml.inherit.target_missing", module_name,
                        f"Inherited view '{inherit}' is missing from Odoo 16.", str(path), rule_id="xml.inherit.target_missing.15_to_16",
                        migration_step="15_to_16", object_name=inherit, source_state="present" if inherit in source.xml_ids else "unknown",
                        target_state="missing", suggested_action="Review target view inheritance.")); continue
                for node in record.iter("xpath"):
                    expr = node.attrib.get("expr")
                    if not expr: continue
                    old = _xpath_state(source_views.get(inherit).architecture, expr) if source_views.get(inherit) else XPathState.UNKNOWN
                    new = _xpath_state(target_views.get(inherit).architecture, expr) if target_views.get(inherit) else XPathState.UNKNOWN
                    if new is not XPathState.EXISTS:
                        code = "xml.xpath.target_missing" if new is XPathState.MISSING else "xml.xpath.static_unknown"
                        findings.append(Finding(Severity.REVIEW_REQUIRED, code, module_name,
                            f"XPath '{expr}' is {new.value} in Odoo 16 view '{inherit}'.", str(path),
                            rule_id=f"{code}.15_to_16", migration_step="15_to_16", object_name=f"{inherit}:{expr}",
                            source_state=old.value, target_state=new.value, suggested_action="Review the Odoo 16 target architecture."))
    return findings
