from pathlib import Path
import xml.etree.ElementTree as ET

from odoo_migrator.analysis.compat import Finding, Severity
from odoo_migrator.sources.indexer import OdooIndex
from odoo_migrator.migrations.v15_to_v16.xml import analyze as analyze_views


def analyze(custom: OdooIndex, source: OdooIndex, target: OdooIndex):
    findings = analyze_views(custom, source, target, target_version=17, migration_step="16_to_17")
    for module_name, module in custom.modules.items():
        for path in Path(module.path).rglob("*.xml"):
            try:
                root = ET.parse(path).getroot()
            except (ET.ParseError, OSError, UnicodeError):
                continue
            for view_record in root.iter("record"):
                if view_record.attrib.get("model") != "ir.ui.view":
                    continue
                for architecture in view_record.findall("field"):
                    if architecture.attrib.get("name") != "arch":
                        continue
                    for content in architecture:
                        for node in content.iter():
                            for attribute in ("attrs", "states"):
                                if attribute not in node.attrib:
                                    continue
                                findings.append(Finding(
                                    Severity.REVIEW_REQUIRED,
                                    "xml.view_modifier.legacy_attribute",
                                    module_name,
                                    f"Odoo 17 rejects the view attribute '{attribute}'; its boolean semantics require manual review.",
                                    path.relative_to(Path(module.path)).as_posix(),
                                    rule_id="xml.view_modifier.legacy_attribute.16_to_17",
                                    migration_step="16_to_17",
                                    object_name=attribute,
                                    source_state="supported",
                                    target_state="rejected",
                                    suggested_action="Convert the expression to Odoo 17 inline modifiers only after verifying equivalent behavior.",
                                ))
    return findings
