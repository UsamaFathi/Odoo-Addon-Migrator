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
    return findings
