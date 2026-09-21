from pathlib import Path
import xml.etree.ElementTree as ET
from odoo_migrator.analysis.compat import Finding, Severity
from odoo_migrator.sources.indexer import OdooIndex


def analyze(custom: OdooIndex, target: OdooIndex, *, target_version: int = 15, migration_step: str = "14_to_15") -> list[Finding]:
    findings = []
    for name, module in custom.modules.items():
        for path in Path(module.path).rglob("*.xml"):
            try: root = ET.parse(path).getroot()
            except ET.ParseError: continue
            for template in root.iter():
                inherit = template.attrib.get("inherit_id") or template.attrib.get("t-inherit")
                if not inherit:
                    continue
                if inherit and "." not in inherit: inherit = f"{name}.{inherit}"
                if inherit and inherit not in target.xml_ids:
                    findings.append(Finding(Severity.REVIEW_REQUIRED, "report.template_missing", name,
                        f"Inherited QWeb template '{inherit}' is missing from Odoo {target_version}.", path.name,
                        rule_id=f"report.template_missing.{migration_step}", migration_step=migration_step, object_name=inherit,
                        suggested_action="Review the report template inheritance."))
    return findings
