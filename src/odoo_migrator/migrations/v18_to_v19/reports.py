from odoo_migrator.sources.indexer import OdooIndex
from odoo_migrator.migrations.v14_to_v15.reports import analyze as analyze_reports
from odoo_migrator.migrations.v14_to_v15.xml import XPathState, _xpath_state
from odoo_migrator.analysis.compat import Finding, Severity
from pathlib import Path
import xml.etree.ElementTree as ET


def analyze(custom: OdooIndex, source: OdooIndex, target: OdooIndex | None = None):
    if target is None:
        target = source
        source = None
    findings = analyze_reports(custom, target, target_version=19, migration_step="18_to_19")
    if source is None:
        return findings
    source_templates = {key: template for module in source.modules.values() for key, template in module.templates.items()}
    target_templates = {key: template for module in target.modules.values() for key, template in module.templates.items()}
    for module_name, module in custom.modules.items():
        for template in module.templates.values():
            inherit = template.inherit_id
            if not inherit:
                continue
            if "." not in inherit:
                inherit = f"{module_name}.{inherit}"
            old = source_templates.get(inherit)
            new = target_templates.get(inherit)
            if old is None or new is None:
                continue
            if old.architecture != new.architecture:
                findings.append(Finding(
                    Severity.REVIEW_REQUIRED,
                    "report.template.architecture_changed",
                    module_name,
                    f"Inherited QWeb template '{inherit}' changed between Odoo 18 and Odoo 19.",
                    rule_id="report.template.architecture_changed.18_to_19",
                    migration_step="18_to_19",
                    object_name=inherit,
                    source_state="architecture_changed",
                    target_state="architecture_changed",
                    suggested_action="Review all report XPath and template expressions against the Odoo 19 report architecture.",
                ))
            for path in Path(module.path).rglob("*.xml"):
                try:
                    root = ET.parse(path).getroot()
                except (ET.ParseError, OSError, UnicodeError):
                    continue
                for node in root.iter("template"):
                    node_inherit = node.attrib.get("inherit_id") or node.attrib.get("t-inherit")
                    if node_inherit and "." not in node_inherit:
                        node_inherit = f"{module_name}.{node_inherit}"
                    if node_inherit != inherit:
                        continue
                    for xpath in node.iter("xpath"):
                        expression = xpath.attrib.get("expr")
                        if not expression:
                            continue
                        old_state = _xpath_state(old.architecture, expression)
                        new_state = _xpath_state(new.architecture, expression)
                        if new_state is XPathState.EXISTS:
                            continue
                        code = "report.xpath.target_missing" if new_state is XPathState.MISSING else "report.xpath.static_unknown"
                        findings.append(Finding(
                            Severity.REVIEW_REQUIRED,
                            code,
                            module_name,
                            f"Report XPath '{expression}' is {new_state.value} in Odoo 19 template '{inherit}'.",
                            path=str(path),
                            rule_id=f"{code}.18_to_19",
                            migration_step="18_to_19",
                            object_name=f"{inherit}:{expression}",
                            source_state=old_state.value,
                            target_state=new_state.value,
                            suggested_action="Review the Odoo 19 report template and XPath target.",
                        ))
    return findings
